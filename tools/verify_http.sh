#!/usr/bin/env bash
# HTTP 层冒烟测试：登录 → 大屏接口 → 报表接口 → 静态资源 → 页面路由
#
#   docker compose exec bench bash -lc "/workspace/tools/verify_http.sh"
#
# 只依赖 curl 与 python3（镜像内自带），不修改任何数据。
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
USERNAME="${USERNAME:-Administrator}"
PASSWORD="${PASSWORD:-admin}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "== 1. 登录（获取会话） =="
curl -s -c "${WORK}/cookies" -X POST "${BASE}/api/method/login" \
	-d "usr=${USERNAME}&pwd=${PASSWORD}" -o /dev/null -w "  login=%{http_code}\n"

echo "== 2. 大屏接口 get_dashboard_data =="
curl -s -b "${WORK}/cookies" -G \
	--data-urlencode 'filters={"preset":"近30天","granularity":"日"}' \
	"${BASE}/api/method/user_growth.api.growth_screen.get_dashboard_data" \
	-o "${WORK}/dashboard.json" \
	-w "  http=%{http_code} bytes=%{size_download} time=%{time_total}s\n"

python3 - "${WORK}/dashboard.json" <<'PY'
import json
import sys

raw = json.load(open(sys.argv[1], encoding="utf-8"))
if "exception" in raw:
	print("  接口异常:", raw.get("exception"), "| 来源:", raw.get("_exc_source"))
	for line in json.loads(raw.get("exc") or "[]")[-8:]:
		print("   ", line.rstrip())
	raise SystemExit(1)

message = raw.get("message", {})
data = message.get("data") or {}
kpi = data.get("kpi") or {}
caliber = message.get("caliber") or {}
trend = data.get("trend") or {}
distribution = data.get("distribution") or {}

print(f"  envelope: code={message.get('code')} cached={message.get('cached')} "
      f"generated_at={message.get('generated_at')}")
print(f"  口径: 分母={caliber.get('churn_rate_denominator')} 粒度={caliber.get('granularity')} "
      f"时区={caliber.get('timezone')}")
print(f"  KPI: 在服={kpi.get('active_users')} 新增={kpi.get('new_users')} "
      f"流失={kpi.get('churned_users')} 净增={kpi.get('net_growth')} "
      f"流失率={kpi.get('churn_rate')}% 净MRR={kpi.get('mrr_net')}")
print(f"  面板: 趋势={len(trend.get('labels') or [])}点 "
      f"大区={len(distribution.get('region') or [])} 省份={len(distribution.get('province') or [])} "
      f"渠道={len(distribution.get('channel') or [])} 套餐={len(distribution.get('plan') or [])} "
      f"流失原因={len(data.get('churn_reasons') or [])} 重点客户={len(data.get('top_accounts') or [])} "
      f"动态={len(data.get('events') or [])}")
assert message.get("code") == 0, "接口没有返回成功码"
assert kpi.get("active_users") is not None, "缺少 KPI：在服用户数"
assert (distribution.get("region") or []), "缺少地域分布数据"
print("  -> 大屏接口校验通过")
PY

echo "== 2.1 趋势接口（必须在整包接口之后仍然返回正确结构） =="
curl -s -b "${WORK}/cookies" -G \
	--data-urlencode 'filters={"preset":"近30天","granularity":"日"}' \
	"${BASE}/api/method/user_growth.api.growth_screen.get_trend_series" \
	-o "${WORK}/trend.json" -w "  第 1 次 http=%{http_code}\n"
curl -s -b "${WORK}/cookies" -G \
	--data-urlencode 'filters={"preset":"近30天","granularity":"日"}' \
	"${BASE}/api/method/user_growth.api.growth_screen.get_trend_series" \
	-o "${WORK}/trend2.json" -w "  第 2 次 http=%{http_code}\n"
curl -s -b "${WORK}/cookies" -G \
	--data-urlencode 'filters={"preset":"近30天","granularity":"日"}' \
	"${BASE}/api/method/user_growth.api.growth_screen.get_dashboard_data" \
	-o "${WORK}/dashboard_again.json" -w "  整包再次调用 http=%{http_code}\n"
python3 - "${WORK}/trend.json" "${WORK}/trend2.json" "${WORK}/dashboard_again.json" <<'PY'
import json
import sys

message = json.load(open(sys.argv[1], encoding="utf-8")).get("message", {})
second = json.load(open(sys.argv[2], encoding="utf-8")).get("message", {})
again = json.load(open(sys.argv[3], encoding="utf-8")).get("message", {})
data = message.get("data") or {}
labels = data.get("labels") or []
print(f"  cached={message.get('cached')} 数据点={len(labels)} 新增序列={len(data.get('new') or [])}")
print(f"  第二次调用 cached={second.get('cached')}（应为 True，证明缓存生效）")
print(f"  整包再次调用 cached={again.get('cached')} 含 kpi={'kpi' in (again.get('data') or {})}")

problems = []
if not labels:
    problems.append("趋势接口返回空数据（典型原因：缓存键与整包接口串用）")
if "active_users" in data or "trend" in data:
    problems.append("趋势接口返回了整包 dashboard 载荷（缓存命名空间冲突）")
if labels and len(labels) != len(data.get("new") or []):
    problems.append("趋势接口的 labels 与序列长度不一致")
if not second.get("cached"):
    problems.append("第二次请求没有命中缓存（缓存可能未生效）")
if "kpi" not in (again.get("data") or {}) or "trend" not in (again.get("data") or {}):
    problems.append("整包接口被其他接口的缓存污染了")
if problems:
    print("FAILED:")
    for item in problems:
        print("  -", item)
    raise SystemExit(1)
print("  -> 趋势接口结构正确、缓存生效、各接口互不串用（切粒度不再变空）")
PY

echo "== 3. 报表接口 query_report.run =="
curl -s -b "${WORK}/cookies" -G \
	--data-urlencode 'report_name=用户增长与流失分析' \
	--data-urlencode 'filters={"preset":"近12个月","granularity":"月"}' \
	"${BASE}/api/method/frappe.desk.query_report.run" \
	-o "${WORK}/report.json" -w "  http=%{http_code} time=%{time_total}s\n"

python3 - "${WORK}/report.json" <<'PY'
import json
import sys

raw = json.load(open(sys.argv[1], encoding="utf-8"))
if "exception" in raw:
	print("  报表异常:", raw.get("exception"), "| 来源:", raw.get("_exc_source"))
	for line in json.loads(raw.get("exc") or "[]")[-6:]:
		print("   ", line.rstrip())
	raise SystemExit(1)

message = raw.get("message", {})
columns = message.get("columns") or []
result = message.get("result") or []
rows = [row for row in result if isinstance(row, dict)]

total_width = sum(int(column.get("width") or 0) for column in columns)
print(f"  列数={len(columns)}  合计列宽={total_width}px  数据行={len(rows)}")
shape = "  ".join(
    f"{column.get('label')}[{column.get('fieldtype')}"
    + (f".{column['precision']}" if column.get("precision") is not None else "")
    + "]"
    for column in columns
)
print("  列定义:", shape)
if rows:
    first, last = rows[0], rows[-1]
    print(f"  首行: {first.get('label')} | 新增={first.get('new')} 流失={first.get('churned')} "
          f"净增={first.get('net')} 期末在服={first.get('end')} 流失率={first.get('churn_rate')} "
          f"净MRR={first.get('mrr_net')}")
    print(f"  末行: {last.get('label')} | 新增={last.get('new')} 流失={last.get('churned')} "
          f"净增={last.get('net')} 期末在服={last.get('end')} 流失率={last.get('churn_rate')} "
          f"净MRR={last.get('mrr_net')}")
print(f"  框架合计行 add_total_row={message.get('add_total_row')}（应为 0：合计由报表自己算）")
assert rows, "报表没有返回数据行"

# —— 表格可读性断言（这一组断言就是"表格很乱"的回归防护） ——
problems = []
if total_width > 1400:
    problems.append(f"列宽合计 {total_width}px 过宽，小屏会横向滚动")
rate_columns = [c for c in columns if c.get("fieldname") in
                ("churn_rate", "mom", "yoy")]
if any(c.get("fieldtype") != "Percent" for c in rate_columns):
    problems.append("比率列没有用 Percent 类型（数值不会带 %）")
money_columns = [c for c in columns if c.get("fieldname") in
                 ("mrr_new", "mrr_churned", "mrr_net", "arpu_new")]
if any(c.get("fieldtype") != "Currency" for c in money_columns):
    problems.append("金额列没有用 Currency 类型")
count_columns = [c for c in columns if c.get("fieldname") in
                 ("begin", "new", "churned", "net", "end")]
if any(c.get("fieldtype") != "Float" or c.get("precision") != 0 for c in count_columns):
    problems.append("人数列没有用 Float(precision=0)（不会有千分位）")
if message.get("add_total_row"):
    problems.append("框架合计行没有关闭（会得到假合计）")
if not rows[-1].get("is_total"):
    problems.append("最后一行不是自带合计行")
if rows[-1].get("end") != rows[0].get("begin") + sum(r.get("new", 0) - r.get("churned", 0) for r in rows[:-1]):
    problems.append("合计行的期末在服与逐期净增之和不一致")
if problems:
    print("FAILED:")
    for item in problems:
        print("  -", item)
    raise SystemExit(1)
print("  -> 报表接口校验通过")
PY

echo "== 3.1 报表分组模式 =="
curl -s -b "${WORK}/cookies" -G \
	--data-urlencode 'report_name=用户增长与流失分析' \
	--data-urlencode 'filters={"preset":"近90天","granularity":"月","group_by":"region"}' \
	"${BASE}/api/method/frappe.desk.query_report.run" \
	-o "${WORK}/grouped.json" -w "  http=%{http_code} time=%{time_total}s\n"
python3 - "${WORK}/grouped.json" <<'PY'
import json
import sys

raw = json.load(open(sys.argv[1], encoding="utf-8"))
if "exception" in raw:
	print("  分组模式异常:", raw.get("exception"))
	raise SystemExit(1)
message = raw.get("message", {})
columns = message.get("columns") or []
rows = [row for row in (message.get("result") or []) if isinstance(row, dict)]
print(f"  列数={len(columns)}（期间 + 每个大区 4 子列）数据行={len(rows)}")
if len(columns) < 5 or not rows:
	print("FAILED: 分组模式没有返回透视列")
	raise SystemExit(1)
print("  -> 分组模式校验通过")
PY

echo "== 4. 报表与大屏口径一致性（同一区间、同一粒度） =="
curl -s -b "${WORK}/cookies" -G \
	--data-urlencode 'filters={"preset":"近90天","granularity":"月"}' \
	"${BASE}/api/method/user_growth.api.growth_screen.get_kpi_summary" \
	-o "${WORK}/kpi.json" -w "  kpi http=%{http_code}\n"
curl -s -b "${WORK}/cookies" -G \
	--data-urlencode 'report_name=用户增长与流失分析' \
	--data-urlencode 'filters={"preset":"近90天","granularity":"月"}' \
	"${BASE}/api/method/frappe.desk.query_report.run" -o "${WORK}/report90.json" -w "  report http=%{http_code}\n"

python3 - "${WORK}/kpi.json" "${WORK}/report90.json" <<'PY'
import json
import sys

kpi = (json.load(open(sys.argv[1], encoding="utf-8")).get("message") or {}).get("data") or {}
report = (json.load(open(sys.argv[2], encoding="utf-8")).get("message") or {})
# 合计行是报表自己算的汇总（含期末时点值），不能参与"逐期求和"的一致性比对
rows = [row for row in (report.get("result") or [])
        if isinstance(row, dict) and not row.get("is_total")]
summary = report.get("report_summary") or []
total_new = sum(row.get("new") or 0 for row in rows)
total_churned = sum(row.get("churned") or 0 for row in rows)
total_end = rows[-1].get("end") if rows else None

print(f"  大屏 KPI : 新增={kpi.get('new_users')} 流失={kpi.get('churned_users')} "
      f"期末在服={kpi.get('active_users')}")
print(f"  报表明细 : 新增={total_new} 流失={total_churned} 期末在服={total_end}")
assert total_new == kpi.get("new_users"), "报表与大屏的新增不一致"
assert total_churned == kpi.get("churned_users"), "报表与大屏的流失不一致"
assert total_end == kpi.get("active_users"), "报表与大屏的期末在服不一致"
print("  -> 报表与大屏在同一区间/粒度下完全一致")
PY

echo "== 5. 静态资源 =="
BUNDLE_PATH="$(python3 -c "import json;print(json.load(open('/home/frappe/frappe-bench/sites/assets/assets.json'))['user_growth.bundle.js'])")"
echo "  bundle 逻辑名 user_growth.bundle.js -> ${BUNDLE_PATH}（由 assets.json 解析，文件名带内容 hash）"
for path in \
	"${BUNDLE_PATH}" \
	/assets/user_growth/css/growth_screen.css \
	/assets/user_growth/js/growth_screen/charts.js; do
	curl -s -o /dev/null -w "  %{http_code}  %{size_download} bytes  ${path}\n" "${BASE}${path}"
done

echo "== 6. 页面与单据路由 =="
# /app/... 会 301 跳到 Desk 单页应用入口，301/200 都说明路由存在
curl -s -o /dev/null -w "  %{http_code}  /app/growth-dashboard\n" "${BASE}/app/growth-dashboard"
curl -s -o /dev/null -w "  %{http_code}  /app/user-service-record\n" "${BASE}/app/user-service-record"
curl -s -o /dev/null -w "  %{http_code}  /app/query-report/%%E7%%94%%A8%%E6%%88%%B7%%E5%%A2%%9E%%E9%%95%%BF%%E4%%B8%%8E%%E6%%B5%%81%%E5%%A4%%B1%%E5%%88%%86%%E6%%9E%%90\n" \
	"${BASE}/app/query-report/%E7%94%A8%E6%88%B7%E5%A2%9E%E9%95%BF%E4%B8%8E%E6%B5%81%E5%A4%B1%E5%88%86%E6%9E%90"

echo "== 冒烟测试全部通过 =="
