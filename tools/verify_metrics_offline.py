"""离线校验指标口径：不需要数据库、不需要启动 Frappe，1 秒内可跑完。

做法：把 metrics 中仅有的三个数据库触点（_daily_agg / _stock_at / _active_mrr）
替换为基于内存合成记录的实现，然后把计算结果与"人工逐日推算"的结果逐一对比。

用途：
    python tools/verify_metrics_offline.py
适合在没有 Docker 环境时快速回归核心口径（发现过"扩展区间被误计入时间桶上限"这类问题）。
"""

import os
import sys
import types
from datetime import date, timedelta
from types import SimpleNamespace

# ---------------------------------------------------------------- frappe 桩
frappe = types.ModuleType("frappe")


class ValidationError(Exception):
	pass


frappe.ValidationError = ValidationError
frappe.parse_json = lambda value: value
frappe.generate_hash = lambda value="", length=16: "deadbeef"
frappe.as_json = lambda value: str(value)
frappe.log_error = lambda *a, **k: None
frappe.msgprint = lambda *a, **k: None


def _throw(message, exc=None, **kwargs):
	raise (exc or Exception)(message)


frappe.throw = _throw
frappe.db = SimpleNamespace(sql=lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应访问数据库")))
frappe.conf = {}
frappe.session = SimpleNamespace(user="Administrator")
frappe.cache = lambda: SimpleNamespace(get_value=lambda k: None, set_value=lambda *a, **k: None)
sys.modules["frappe"] = frappe

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "user_growth"))
from user_growth.analytics import metrics, periods  # noqa: E402

# ---------------------------------------------------------- 合成业务记录
# 每行：开通日期, 流失日期(None=在服), MRR, 生命周期序号, 大区, 渠道, 套餐
T = date(2026, 10, 9)


def d(days_ago):
	return T - timedelta(days=days_ago)


RECORDS = [
	# 长期在服
	{"act": d(400), "churn": None, "mrr": 299, "seq": 1, "region": "华东", "channel": "官网直销", "plan": "专业版"},
	{"act": d(300), "churn": None, "mrr": 899, "seq": 1, "region": "华南", "channel": "合作伙伴", "plan": "企业版"},
	{"act": d(60), "churn": None, "mrr": 99, "seq": 1, "region": "华东", "channel": "信息流", "plan": "基础版"},
	# 本期内即将流失
	{"act": d(200), "churn": d(10), "mrr": 299, "seq": 1, "region": "华北", "channel": "搜索广告", "plan": "专业版"},
	# 更早流失
	{"act": d(500), "churn": d(120), "mrr": 99, "seq": 1, "region": "华南", "channel": "官网直销", "plan": "基础版"},
	# 唤回（同一客户第二段）
	{"act": d(30), "churn": None, "mrr": 899, "seq": 2, "region": "华南", "channel": "老客推荐", "plan": "企业版"},
	# 免费试用流失
	{"act": d(45), "churn": d(20), "mrr": 0, "seq": 1, "region": "西南", "channel": "自然流量", "plan": "免费试用"},
]


def _active_on(day, region=None):
	count = 0
	for row in RECORDS:
		if region and row["region"] != region:
			continue
		if row["act"] <= day and (row["churn"] is None or row["churn"] > day):
			count += 1
	return count


def fake_stock_at(day, filters, dimension=None):
	if dimension:
		result = {}
		for row in RECORDS:
			if row["act"] <= day and (row["churn"] is None or row["churn"] > day):
				key = row[dimension]
				result[key] = result.get(key, 0) + 1
		return result
	return _active_on(day)


def fake_daily_agg(field, start, end, filters, dimension=None):
	buckets = {}
	for row in RECORDS:
		value = row["act"] if field == "activation_date" else row["churn"]
		if not value or not (start <= value <= end):
			continue
		key = (value, row[dimension]) if dimension else value
		node = buckets.setdefault(key, {"cnt": 0, "mrr": 0.0, "winback": 0, "life_sum": 0.0})
		node["cnt"] += 1
		node["mrr"] += row["mrr"]
		node["winback"] += 1 if row["seq"] > 1 else 0
		if field == "churn_date":
			node["life_sum"] += (row["churn"] - row["act"]).days
	rows = []
	for key, node in buckets.items():
		day = key[0] if dimension else key
		rows.append(SimpleNamespace(d=day, k=(key[1] if dimension else None), **node))
	return rows


metrics._stock_at = fake_stock_at
metrics._daily_agg = fake_daily_agg


def fake_active_mrr(filters, day):
	return sum(row["mrr"] for row in RECORDS
	           if row["act"] <= day and (row["churn"] is None or row["churn"] > day))


metrics._active_mrr = fake_active_mrr


def manual(start, end):
	new = sum(1 for r in RECORDS if r["act"] and start <= r["act"] <= end)
	churned = sum(1 for r in RECORDS if r["churn"] and start <= r["churn"] <= end)
	begin = _active_on(start - timedelta(days=1))
	end_stock = _active_on(end)
	user_days = sum(_active_on(start + timedelta(days=i)) for i in range((end - start).days + 1))
	return {
		"new": new, "churned": churned, "begin": begin, "end": end_stock,
		"net": new - churned, "avg_active": round(user_days / ((end - start).days + 1), 2),
		"mrr_new": sum(r["mrr"] for r in RECORDS if r["act"] and start <= r["act"] <= end),
		"mrr_churned": sum(r["mrr"] for r in RECORDS if r["churn"] and start <= r["churn"] <= end),
	}


FAILED = []


def check(label, actual, expected):
	ok = abs(actual - expected) < 0.011 if isinstance(expected, float) else actual == expected
	print(("  OK   " if ok else "  FAIL ") + f"{label}: actual={actual} expected={expected}")
	if not ok:
		FAILED.append(label)


print("== 1. 时间桶恒等式 ==")
filters = metrics.normalize_filters({"preset": "近90天", "granularity": "周"})
series = metrics.compute_series(filters)
for index, row in enumerate(series["rows"]):
	check(f"bucket{index} end = begin + new - churned",
	      row["end"], row["begin"] + row["new"] - row["churned"])
	if index:
		check(f"bucket{index} begin 衔接", row["begin"], series["rows"][index - 1]["end"])

print("== 2. 可见区间的期末在服 = 人工计算 ==")
visible = [r for r in series["rows"] if r["in_range"]]
check("最后一个可见桶的期末在服", visible[-1]["end"], manual(filters["start"], filters["end"])["end"])
check("第一个可见桶的期初在服", visible[0]["begin"],
      _active_on(visible[0]["start"] - timedelta(days=1)))

print("== 3. KPI 与人工计算一致 ==")
kpi = metrics.compute_kpi(filters)
expect = manual(filters["start"], filters["end"])
for key in ("new_users", "churned_users", "active_users", "net_growth", "avg_active_users"):
	check(f"kpi.{key}", kpi[key], expect[{"new_users": "new", "churned_users": "churned",
	                                      "active_users": "end", "net_growth": "net",
	                                      "avg_active_users": "avg_active"}[key]])
check("kpi.mrr_new", kpi["mrr_new"], expect["mrr_new"])
check("kpi.mrr_churned", kpi["mrr_churned"], expect["mrr_churned"])
expect_arpu = round(fake_active_mrr(filters, filters["end"]) / expect["end"], 2) if expect["end"] else 0
check("kpi.arpu", kpi["arpu"], expect_arpu)

print("== 4. 粒度无关性：月/周/日 的总量一致 ==")
totals = {}
for granularity in ("日", "周", "月"):
	f = metrics.normalize_filters({"preset": "近90天", "granularity": granularity})
	rows = [r for r in metrics.compute_series(f)["rows"] if r["in_range"]]
	totals[granularity] = (sum(r["new"] for r in rows), sum(r["churned"] for r in rows))
check("日新增强 = 周", totals["日"][0], totals["周"][0])
check("日流失 = 月", totals["日"][1], totals["月"][1])

print("== 5. 环比/同比 ==")
f = metrics.normalize_filters({"preset": "近12个月", "granularity": "月"})
result = metrics.compute_series(f)
rows = [r for r in result["rows"] if r["in_range"]]
by_key = {r["key"]: r for r in result["rows"]}
check("首行无环比", rows[0]["mom"], None)
for index in range(1, len(rows)):
	base = rows[index - 1]["net"]
	check(f"环比留空当且仅当上期净增为 0（row {index}）",
	      rows[index]["mom"] is None, base == 0)
check("末行去年同期桶已在扩展区间内计算",
      periods.shift_year_back_key(rows[-1]["key"], "月") in by_key, True)
check("去年同期为 0 时同比留空", rows[-1]["yoy"], None)

print("== 6. 流失率口径 ==")
f1 = metrics.normalize_filters({"preset": "近90天", "granularity": "月",
                               "churn_rate_denominator": "期初在服"})
f2 = metrics.normalize_filters({"preset": "近90天", "granularity": "月",
                               "churn_rate_denominator": "平均在服"})
k1 = metrics.compute_kpi(f1)
k2 = metrics.compute_kpi(f2)
check("口径切换后流失率变化", k1["churn_rate"] != k2["churn_rate"], True)
check("平均口径分母 = 人工日均", k2["avg_active_users"], expect["avg_active"])

print()
if FAILED:
	print(f"FAILED: {len(FAILED)} 项 -> {FAILED}")
	sys.exit(1)
print("全部恒等式与人工逐日推算一致：PASS")
