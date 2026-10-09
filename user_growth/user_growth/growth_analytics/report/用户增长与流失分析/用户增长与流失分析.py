"""用户增长与流失分析（脚本报表）。

表格设计原则（针对"表格很乱"的修正）：

1. **列只留决策必需项**（14 列）：原来的 16 列在小屏上必然横向滚动；
   「新客 / 唤回」是「新增」的拆分明细，放到大屏与单据里看更合适，不再挤在报表主表。
2. **每列用正确的字段类型**，让框架按类型格式化，而不是靠标签写单位：
   | 指标      | 类型              | 渲染效果        |
   | 人数      | Float（precision 0） | 4,838（带千分位） |
   | 比率      | Percent           | 4.87%（自带 %）  |
   | 金额      | Currency          | ¥214,743       |
   说明：Frappe 的 Int 类型不带千分位（源码里是 cint 直出），而人数是四千~五万量级，
   用 Float(0) 才能得到"4,838"这种可读格式，且导出到 Excel 仍是数字。
3. **不使用框架的盲求和合计行**——它会把"流失率""期末在服"也逐行相加，得到假数字。
   这里改为按指标口径自己算一行「合计」（期末在服取期末时点、流失率按区间重算），
   并通过返回值 skip_total_row 关掉框架合计行。
4. 表格上方保留一行**口径说明**，做到"数字自证"。
"""

import frappe

from user_growth.analytics import metrics

REPORT_NAME = "用户增长与流失分析"


def execute(filters=None):
	normalized = metrics.normalize_filters(
		filters or {}, default_granularity=metrics.DEFAULT_GRANULARITY
	)
	if normalized["group_by"]:
		columns, data = _grouped_view(normalized)
		chart = None
	else:
		columns, data = _flat_view(normalized)
		chart = _chart(data)
	# 返回值顺序：(columns, data, message, chart, report_summary, skip_total_row)
	# skip_total_row=True：关掉框架的盲求和合计行（我们用 _flat_view 里的「合计」行替代）
	return columns, data, _message(normalized), chart, None, True


# ---------------------------------------------------------------------------
# 不分组：一行一个时间桶 + 一行合计
# ---------------------------------------------------------------------------
def _flat_view(filters: dict):
	series = metrics.compute_series(filters)
	kpi = metrics.compute_kpi(filters)

	columns = [
		{"label": "期间", "fieldname": "label", "fieldtype": "Data", "width": 100},
		{"label": "期初在服", "fieldname": "begin", "fieldtype": "Float",
		 "precision": 0, "width": 84},
		{"label": "新增", "fieldname": "new", "fieldtype": "Float", "precision": 0, "width": 76},
		{"label": "流失", "fieldname": "churned", "fieldtype": "Float",
		 "precision": 0, "width": 76},
		{"label": "净增", "fieldname": "net", "fieldtype": "Float", "precision": 0, "width": 76},
		{"label": "期末在服", "fieldname": "end", "fieldtype": "Float",
		 "precision": 0, "width": 92},
		{"label": "流失率", "fieldname": "churn_rate", "fieldtype": "Percent",
		 "precision": 2, "width": 84},
		{"label": "新增 MRR", "fieldname": "mrr_new", "fieldtype": "Currency",
		 "precision": 0, "options": "CNY", "width": 100},
		{"label": "流失 MRR", "fieldname": "mrr_churned", "fieldtype": "Currency",
		 "precision": 0, "options": "CNY", "width": 100},
		{"label": "净 MRR", "fieldname": "mrr_net", "fieldtype": "Currency",
		 "precision": 0, "options": "CNY", "width": 100},
		{"label": "新增 ARPU", "fieldname": "arpu_new", "fieldtype": "Currency",
		 "precision": 0, "options": "CNY", "width": 96},
		{"label": "平均生命周期(天)", "fieldname": "avg_lifecycle", "fieldtype": "Float",
		 "precision": 1, "width": 112},
		{"label": "环比", "fieldname": "mom", "fieldtype": "Percent", "precision": 1, "width": 78},
		{"label": "同比", "fieldname": "yoy", "fieldtype": "Percent", "precision": 1, "width": 78},
	]

	data = []
	for row in series["visible"]:
		data.append({
			"label": row["label"],
			"begin": row["begin"],
			"new": row["new"],
			"churned": row["churned"],
			"net": row["net"],
			"end": row["end"],
			"churn_rate": row["churn_rate"],
			"mrr_new": row["mrr_new"],
			"mrr_churned": row["mrr_churned"],
			"mrr_net": row["mrr_net"],
			"arpu_new": row["arpu_new"],
			"avg_lifecycle": row["avg_lifecycle"],
			"mom": row["mom"],
			"yoy": row["yoy"],
		})

	# 合计行：按指标口径重算，而不是逐行相加
	data.append({
		"label": "合计",
		"begin": kpi["active_users_begin"],
		"new": kpi["new_users"],
		"churned": kpi["churned_users"],
		"net": kpi["net_growth"],
		"end": kpi["active_users"],
		"churn_rate": kpi["churn_rate"],
		"mrr_new": kpi["mrr_new"],
		"mrr_churned": kpi["mrr_churned"],
		"mrr_net": kpi["mrr_net"],
		"arpu_new": kpi["arpu"],
		"avg_lifecycle": kpi["avg_lifecycle_days"],
		"mom": kpi["net_growth_delta"],
		"yoy": None,
		"is_total": 1,
	})
	return columns, data


# ---------------------------------------------------------------------------
# 分组：期间 × 维度值（每个维度值 4 个子指标）
# ---------------------------------------------------------------------------
def _grouped_view(filters: dict):
	dimension = filters["group_by"]
	label = metrics.dimension_label(dimension)
	result = metrics.compute_grouped_series(filters, dimension)
	keys = result["keys"]

	columns = [{"label": "期间", "fieldname": "label", "fieldtype": "Data", "width": 100}]
	for index, key in enumerate(keys):
		for suffix, title in (("new", "新增"), ("churned", "流失"),
		                      ("net", "净增"), ("end", "在服")):
			columns.append({
				"label": f"{key} · {title}",
				"fieldname": f"c{index}_{suffix}",
				"fieldtype": "Float",
				"precision": 0,
				"width": 96,
			})

	data = []
	for row in result["rows"]:
		line = {"label": row["label"]}
		for index, key in enumerate(keys):
			cell = row["cells"].get(key, {})
			line[f"c{index}_new"] = cell.get("new", 0)
			line[f"c{index}_churned"] = cell.get("churned", 0)
			line[f"c{index}_net"] = cell.get("net", 0)
			line[f"c{index}_end"] = cell.get("end", 0)
		data.append(line)

	frappe.msgprint(
		f"当前按「{label}」分组，仅展示期末在服数排名前 {len(keys)} 个取值。",
		indicator="blue",
		alert=True,
	)
	return columns, data


# ---------------------------------------------------------------------------
# 图表（报表页工具栏的图表按钮使用；get_chart_data 会优先于这里的返回值）
# ---------------------------------------------------------------------------
def _chart(data: list[dict]):
	rows = [row for row in data if not row.get("is_total")]
	if not rows:
		return None
	return {
		"data": {
			"labels": [row["label"] for row in rows],
			"datasets": [
				{"name": "新增用户", "values": [row["new"] for row in rows], "chartType": "bar"},
				{"name": "流失用户", "values": [row["churned"] for row in rows], "chartType": "bar"},
				{"name": "期末在服", "values": [row["end"] for row in rows], "chartType": "line"},
			],
		},
		"type": "axis-mixed",
		"colors": ["#0891B2", "#F97316", "#3D5AFE"],
		"fieldtype": "Float",
	}


# ---------------------------------------------------------------------------
# 顶部口径说明
# ---------------------------------------------------------------------------
def _message(filters: dict) -> str:
	parts = [
		f"区间 <b>{filters['period_label']}</b>",
		f"粒度 <b>{filters['granularity']}</b>",
		f"流失率分母 <b>{filters['churn_rate_denominator']}</b>",
	]
	if filters["group_by"]:
		parts.append(f"分组 <b>{metrics.dimension_label(filters['group_by'])}</b>")
	if filters.get("is_paid") is not None:
		parts.append("仅统计 <b>" + ("付费客户" if filters["is_paid"] else "免费客户") + "</b>")
	parts.append("在服口径：开通日期 ≤ 时点 &lt; 流失日期")
	return "　·　".join(parts)
