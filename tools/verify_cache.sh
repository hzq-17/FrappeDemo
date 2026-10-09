#!/usr/bin/env bash
# 缓存行为诊断：
#   1. 缓存是否真的生效（写入后能否读回、同 namespace 第二次是否命中）
#   2. 不同接口（namespace）是否互不串用 —— 这正是"切回日粒度趋势变空"的根因
#
#   docker compose exec bench bash -lc "/workspace/tools/verify_cache.sh"
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
SITE="${SITE:-${SITE_NAME:-growth.local}}"

cd "${BENCH_DIR}/sites"
"${BENCH_DIR}/env/bin/python" - <<'PY'
import pickle

import frappe

frappe.init(site="growth.local", sites_path=".")
frappe.connect()
frappe.set_user("Administrator")

from user_growth.analytics import metrics
from user_growth.api import growth_screen

cache = frappe.cache()
print("缓存实现:", type(cache).__module__ + "." + type(cache).__name__)

filters = metrics.normalize_filters(
    {"preset": "近30天", "granularity": "日"}, default_granularity="日"
)


def clear(namespace):
    cache.delete_value(growth_screen._cache_key(namespace, filters))


# ⚠️ 所有实验都用 verify-* 命名空间，绝不写脏真实接口的缓存键
VERIFY = ("verify-a", "verify-b", "verify-c")


def hit(namespace):
    """直接问 Redis。

    不能用 cache.get_value()：它先查 frappe.local.cache 这个「请求级 memo」，
    连未命中都会被记成 None（expires=True 也不绕过），同进程内看缓存会失真。
    跨请求（HTTP）才是真实行为，所以这里绕过 wrapper 直接读底层 client。
    """
    raw = cache.client().get(cache.make_key(growth_screen._cache_key(namespace, filters)))
    return pickle.loads(raw) if raw else None


try:
    for namespace in VERIFY:
        clear(namespace)

    # 1) 写入后必须能在 Redis 里读到（说明缓存确实生效）
    growth_screen._cached(lambda: {"kind": "trend"}, filters, namespace="verify-a")
    cached_value = hit("verify-a")
    print("写入后 Redis 读回:", cached_value)

    # 2) 不同 namespace 互不影响：verify-b 有自己的值，且不读到 verify-a 的值
    growth_screen._cached(lambda: {"kind": "dashboard"}, filters, namespace="verify-b")
    other = hit("verify-b")
    print("另一个 namespace 的值:", other)

    # 3) 复现修复前的机制：把「整包数据」预先写进趋势接口要用的键
    #    （等价于"另一个请求刚把整包缓存下来"），然后让趋势接口去读这个键。
    #    —— 修复前两者共用键，趋势接口就会把整包载荷当成趋势数据返回。
    clear("verify-c")
    cache.client().set(
        cache.make_key(growth_screen._cache_key("verify-c", filters)),
        pickle.dumps({"kind": "另一个请求缓存下来的整包数据"}),
    )
    stale, hit_stale = growth_screen._cached(
        lambda: {"kind": "本该计算的趋势数据"}, filters, namespace="verify-c"
    )
    print(f"键上已有整包数据时，趋势接口拿到={stale} 命中={hit_stale}")

    # 4) 修复后的行为：整包接口先缓存，也不会影响趋势接口（键不同）
    clear("verify-trend")
    clear("verify-dashboard")
    cache.client().set(
        cache.make_key(growth_screen._cache_key("verify-dashboard", filters)),
        pickle.dumps({"kind": "整包数据"}),
    )
    trend_value, trend_hit = growth_screen._cached(
        lambda: {"kind": "趋势数据"}, filters, namespace="verify-trend"
    )
    print(f"整包已缓存时，趋势接口拿到={trend_value} 命中={trend_hit}")

    print()
    problems = []
    if cached_value != {"kind": "trend"}:
        problems.append("写入后没有在 Redis 里读回（缓存未生效）")
    if other != {"kind": "dashboard"}:
        problems.append("不同 namespace 串用了别的数据")
    if not (hit_stale and stale == {"kind": "另一个请求缓存下来的整包数据"}):
        problems.append("没有复现共用键的串用机制（实验前提不成立）")
    if trend_hit or trend_value != {"kind": "趋势数据"}:
        problems.append("整包缓存影响了趋势接口（namespace 隔离失效）")
    if problems:
        print("FAILED:")
        for item in problems:
            print("  -", item)
        raise SystemExit(1)

    print("缓存行为符合预期：")
    print("  · 写入后能读回 → 缓存生效（TTL 由 Redis setex 保证）")
    print("  · 不同 namespace 各管各的 → 趋势/整包/KPI 不再互相串用")
    print("  · 共用键会把别人的载荷当成自己的 → 正是此前趋势变空的机制，现已隔离")
finally:
    for namespace in VERIFY:
        clear(namespace)
    frappe.destroy()
PY
