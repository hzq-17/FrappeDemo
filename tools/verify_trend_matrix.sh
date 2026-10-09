#!/usr/bin/env bash
# 遍历"时间范围 × 时间粒度"，确认每种组合都有数据（防止切粒度后趋势变空）
#
#   docker compose exec bench bash -lc "/workspace/tools/verify_trend_matrix.sh"
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
SITE="${SITE:-${SITE_NAME:-growth.local}}"

cd "${BENCH_DIR}/sites"
"${BENCH_DIR}/env/bin/python" - <<'PY'
import frappe

frappe.init(site="growth.local", sites_path=".")
frappe.connect()

from user_growth.analytics import metrics

PRESETS = ["近7天", "近30天", "近90天", "本月", "上月", "本季度", "今年", "近12个月"]
GRANULARITIES = ["日", "周", "月", "季度", "年"]

problems = []
print("范围 × 粒度 数据点数（括号内为新增合计）")
for preset in PRESETS:
    cells = []
    for granularity in GRANULARITIES:
        filters = metrics.normalize_filters(
            {"preset": preset, "granularity": granularity}, default_granularity="日"
        )
        try:
            visible = metrics.compute_series(filters)["visible"]
        except Exception as error:  # 例如区间过大被大区间保护拦下
            cells.append(f"{granularity}:ERR({type(error).__name__})")
            problems.append(f"{preset} × {granularity} 抛异常：{error}")
            continue
        new_total = sum(row["new"] for row in visible)
        cells.append(f"{granularity}:{len(visible)}点/{new_total}新增")
        if len(visible) == 0:
            problems.append(f"{preset} × {granularity} 返回 0 个数据点")
    print(f"  {preset:8s} " + "  ".join(cells))

print()
if problems:
    print("FAILED:")
    for item in problems:
        print("  -", item)
    raise SystemExit(1)
print("全部组合都有数据：PASS")
frappe.destroy()
PY
