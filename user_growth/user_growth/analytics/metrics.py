"""指标计算：报表与大屏共用的唯一实现。

核心思路
--------
1. 期间类指标（新增 / 流失 / MRR 变动）由数据库按日聚合，避免把明细全量搬到应用层；
2. 时点类指标（期初在服 / 期末在服 / 日均在服）用"日增量递推"得到：
      在服(d) = 在服(d-1) + 当日新增(d) - 当日流失(d)
   这条恒等式在"一段订阅一行"的模型下严格成立，因此只需一次基准查库，
   即可精确还原每一天的在服数，并把日均在服精确算出来（不是近似）；
3. 流失率分母可选（期初在服 / 平均在服），但实现只有一处，报表与大屏完全一致。

约定
----
* 流失日期当天算作"已不在服"：在服条件为 activation_date <= T < churn_date；
* 所有查询参数化，禁止拼接用户输入；
* 时间字段均为日期型，时区口径为 Asia/Shanghai（中国无夏令时）。
"""

from datetime import date, datetime, timedelta

import frappe

from user_growth.analytics import constants as C
from user_growth.analytics import periods as P
from user_growth.analytics.rules import to_date

TABLE = "tabUser Service Record"

# 可分组/可筛选的维度
DIMENSIONS = {
	"region": "大区",
	"province": "省份",
	"acquisition_channel": "获客渠道",
	"plan": "套餐",
	"user_type": "用户类型",
	"segment": "客户分层",
	"billing_cycle": "计费周期",
	"churn_reason_category": "流失原因",
}

# 参与筛选的字段（is_paid 为布尔字段，单独处理）
STRING_FILTERS = [
	"region", "province", "acquisition_channel", "plan",
	"user_type", "segment", "billing_cycle", "churn_reason_category",
]

CHURN_DENOMINATORS = ["期初在服", "平均在服"]
DEFAULT_CHURN_DENOMINATOR = "期初在服"
DEFAULT_GRANULARITY = "月"
SCREEN_GRANULARITY = "日"


# ---------------------------------------------------------------------------
# 筛选条件
# ---------------------------------------------------------------------------
def _as_list(value) -> list:
	if value in (None, "", [], ()):
		return []
	if isinstance(value, str):
		return [x.strip() for x in value.split(",") if x.strip()]
	return [x for x in value if x not in (None, "")]


def normalize_filters(filters=None, default_granularity: str | None = None) -> dict:
	"""把外部传入的筛选条件规范化，非法值抛出可读错误。"""
	if isinstance(filters, str):
		filters = frappe.parse_json(filters) or {}
	else:
		filters = dict(filters or {})

	preset = filters.get("preset") or filters.get("range")
	start, end = P.resolve_range(
		preset,
		filters.get("from_date") or filters.get("start_date") or filters.get("start"),
		filters.get("to_date") or filters.get("end_date") or filters.get("end"),
	)

	granularity = filters.get("granularity") or default_granularity or DEFAULT_GRANULARITY
	if granularity not in P.GRANULARITIES:
		raise frappe.ValidationError(
			f"时间粒度取值不合法：{granularity}（可选：{'/'.join(P.GRANULARITIES)}）"
		)

	# 大区间保护：只约束"可见时间桶"，扩展区间（用于同比）不计入上限
	try:
		visible_buckets = len(P.build_buckets(start, end, granularity,
		                                     max_buckets=P.MAX_BUCKETS + 1))
	except ValueError:
		visible_buckets = P.MAX_BUCKETS + 1
	if visible_buckets > P.MAX_BUCKETS:
		raise frappe.ValidationError(
			f"当前区间按「{granularity}」会切出约 {visible_buckets} 个时间点"
			f"（上限 {P.MAX_BUCKETS}），请缩小时间范围或选择更粗的时间粒度"
		)

	denominator = filters.get("churn_rate_denominator") or DEFAULT_CHURN_DENOMINATOR
	if denominator not in CHURN_DENOMINATORS:
		raise frappe.ValidationError(
			f"流失率口径取值不合法：{denominator}（可选：{'/'.join(CHURN_DENOMINATORS)}）"
		)

	group_by = filters.get("group_by") or filters.get("dimension") or ""
	if group_by in ("不分组", "全部"):
		group_by = ""
	if group_by and group_by not in DIMENSIONS:
		raise frappe.ValidationError(f"分组维度取值不合法：{group_by}")

	normalized = {
		"start": start,
		"end": end,
		"preset": preset or "自定义",
		"granularity": granularity,
		"churn_rate_denominator": denominator,
		"group_by": group_by,
		"period_label": P.format_period(start, end),
		"is_paid": _normalize_is_paid(filters.get("is_paid")),
		"only_churned": bool(filters.get("only_churned")),
	}
	for field in STRING_FILTERS:
		normalized[field] = _as_list(filters.get(field))
	return normalized


def _normalize_is_paid(value):
	if value in (None, "", "全部", "all"):
		return None
	text = str(value).strip()
	if text in ("付费", "1", "True", "true", "yes"):
		return 1
	if text in ("免费", "0", "False", "false", "no"):
		return 0
	raise frappe.ValidationError(f"是否付费筛选值不合法：{value}")


def _attr_where(filters: dict, exclude: tuple = ()) -> tuple[str, dict]:
	"""生成记录属性筛选的 SQL 片段（全部参数化）。"""
	clauses: list[str] = []
	params: dict = {}
	for field in STRING_FILTERS:
		values = filters.get(field) or []
		if not values or field in exclude:
			continue
		keys = []
		for i, value in enumerate(values):
			key = f"f_{field}_{i}"
			params[key] = value
			keys.append(f"%({key})s")
		clauses.append(f"AND r.{field} IN ({', '.join(keys)})")
	if filters.get("is_paid") is not None and "is_paid" not in exclude:
		clauses.append("AND r.is_paid = %(f_is_paid)s")
		params["f_is_paid"] = filters["is_paid"]
	return ("\n\t\t".join(clauses), params)


def _bucket_expr(field: str, granularity: str, alias: str = "r") -> str:
	"""与 periods.bucket_key 完全一致的 SQL 表达式（不使用 %% 转义，避免歧义）。"""
	col = f"{alias}.{field}"
	if granularity == "日":
		return f"CAST({col} AS CHAR)"
	if granularity == "周":
		return f"CAST(DATE_SUB({col}, INTERVAL WEEKDAY({col}) DAY) AS CHAR)"
	if granularity == "月":
		return f"CONCAT(YEAR({col}), '-', LPAD(MONTH({col}), 2, '0'))"
	if granularity == "季度":
		return f"CONCAT(YEAR({col}), '-Q', QUARTER({col}))"
	return f"CAST(YEAR({col}) AS CHAR)"


# ---------------------------------------------------------------------------
# 基础查询
# ---------------------------------------------------------------------------
def _daily_agg(field: str, start, end, filters, dimension=None) -> list[dict]:
	"""按日（可选按维度）聚合新增或流失事件。"""
	where, params = _attr_where(filters, exclude=(dimension,) if dimension else ())
	dim_select = f"r.{dimension} AS k," if dimension else ""
	sql = f"""
		SELECT {dim_select}
		       r.{field} AS d,
		       COUNT(*) AS cnt,
		       COALESCE(SUM(r.mrr), 0) AS mrr,
		       COALESCE(SUM(CASE WHEN r.lifecycle_seq > 1 THEN 1 ELSE 0 END), 0) AS winback,
		       COALESCE(SUM(r.lifecycle_days), 0) AS life_sum
		FROM `{TABLE}` r
		WHERE r.{field} BETWEEN %(start)s AND %(end)s
		{where}
		GROUP BY d{', k' if dimension else ''}
	"""
	params.update({"start": start, "end": end})
	return frappe.db.sql(sql, params, as_dict=True)


def _stock_at(day, filters, dimension=None) -> dict:
	"""某一时点（该日结束时）的在服数；dimension 不为空时按维度返回。"""
	where, params = _attr_where(filters, exclude=(dimension,) if dimension else ())
	dim_select = f"r.{dimension} AS k," if dimension else ""
	group = f"GROUP BY k" if dimension else ""
	sql = f"""
		SELECT {dim_select} COUNT(*) AS cnt
		FROM `{TABLE}` r
		WHERE r.activation_date <= %(d)s
		  AND (r.churn_date IS NULL OR r.churn_date > %(d)s)
		{where}
		{group}
	"""
	params["d"] = day
	rows = frappe.db.sql(sql, params, as_dict=True)
	if dimension:
		return {r.k: int(r.cnt or 0) for r in rows}
	return int(rows[0].cnt or 0) if rows else 0


def _daterange(start, end):
	cursor = start
	while cursor <= end:
		yield cursor
		cursor += timedelta(days=1)


def _churn_rate(churned: int, begin_stock: int, avg_active: float, denominator: str) -> float:
	base = avg_active if denominator == "平均在服" else begin_stock
	if not base:
		return 0.0
	return round(churned / base * 100, 2)


# ---------------------------------------------------------------------------
# 序列（趋势）
# ---------------------------------------------------------------------------
def compute_series(filters: dict) -> dict:
	"""按时间粒度输出完整指标序列，并附带环比、同比。"""
	start, end = filters["start"], filters["end"]
	granularity = filters["granularity"]
	ext_start = P.extended_start(start, granularity)
	# 扩展区间不设上限：可见部分的上限已由 normalize_filters 把关
	buckets = P.build_buckets(ext_start, end, granularity, max_buckets=None)

	base_day = ext_start - timedelta(days=1)
	stock = _stock_at(base_day, filters)

	new_rows = {to_date(r.d): r for r in _daily_agg("activation_date", ext_start, end, filters)}
	churn_rows = {to_date(r.d): r for r in _daily_agg("churn_date", ext_start, end, filters)}

	rows: list[dict] = []
	for bucket in buckets:
		# 可见区间的第一个桶可能"跨"区间起点（例如年粒度的首桶）。
		# 这里只统计区间内的部分，保证"合计不因时间粒度而漂移"——
		# 年粒度、月粒度、日粒度算出来的新增/流失必须完全相等。
		# 只有"跨越区间起点"的那个桶需要裁剪；完全落在区间之前的历史桶照常聚合
		# （它们只用于同比/环比对照，不参与展示）
		aggregate_from = (
			max(bucket["start"], start) if bucket["end"] >= start else bucket["start"]
		)
		begin_stock = None
		new_cnt = churned = winback = 0
		mrr_new = mrr_churned = 0.0
		life_sum = 0.0
		user_days = 0
		for day in _daterange(bucket["start"], bucket["end"]):
			visible_day = day >= aggregate_from
			if visible_day and begin_stock is None:
				begin_stock = stock
			if visible_day:
				node = new_rows.get(day)
				if node:
					new_cnt += int(node.cnt)
					mrr_new += float(node.mrr or 0)
					winback += int(node.winback or 0)
				node = churn_rows.get(day)
				if node:
					churned += int(node.cnt)
					mrr_churned += float(node.mrr or 0)
					life_sum += float(node.life_sum or 0)
			# 存量递推必须逐日进行，才能把跨桶边界的增减正确带入下一个桶
			stock += (int(new_rows[day].cnt) if day in new_rows else 0) - (
				int(churn_rows[day].cnt) if day in churn_rows else 0
			)
			if visible_day:
				user_days += stock

		end_stock = stock
		if begin_stock is None:
			# 整个桶都落在可见区间之前：仅供"同比/环比"对照，不参与展示
			begin_stock = end_stock
		days = (bucket["end"] - aggregate_from).days + 1
		days = days if days > 0 else 1
		avg_active = round(user_days / days, 2)
		rows.append({
			"key": bucket["key"],
			"label": bucket["label"],
			"start": bucket["start"],
			"end": bucket["end"],
			"in_range": bucket["end"] >= start,
			"begin": begin_stock,
			"new": new_cnt,
			"new_new": new_cnt - winback,
			"new_winback": winback,
			"churned": churned,
			"net": new_cnt - churned,
			"end": end_stock,
			"avg_active": avg_active,
			"churn_rate": _churn_rate(
				churned, begin_stock, avg_active, filters["churn_rate_denominator"]
			),
			"mrr_new": round(mrr_new, 2),
			"mrr_churned": round(mrr_churned, 2),
			"mrr_net": round(mrr_new - mrr_churned, 2),
			"arpu_new": round(mrr_new / new_cnt, 2) if new_cnt else 0.0,
			"avg_lifecycle": round(life_sum / churned, 1) if churned else 0.0,
		})

	by_key = {row["key"]: row for row in rows}
	for index, row in enumerate(rows):
		prev = rows[index - 1] if index > 0 else None
		row["mom"] = _growth(row["net"], prev["net"]) if prev else None
		same = by_key.get(P.shift_year_back_key(row["key"], granularity))
		row["yoy"] = _growth(row["net"], same["net"]) if same else None

	return {
		"rows": rows,
		"visible": [row for row in rows if row["in_range"]],
		"granularity": granularity,
		"period": {"start": start, "end": end, "label": filters["period_label"]},
		"buckets": buckets,
	}


def _growth(current, base):
	if not base:
		return None
	return round((current - base) / abs(base) * 100, 2)


# ---------------------------------------------------------------------------
# KPI（当期 + 上一期，用于环比）
# ---------------------------------------------------------------------------
def _period_metrics(filters: dict, start, end) -> dict:
	base_day = start - timedelta(days=1)
	stock = _stock_at(base_day, filters)
	new_rows = {to_date(r.d): r for r in _daily_agg("activation_date", start, end, filters)}
	churn_rows = {to_date(r.d): r for r in _daily_agg("churn_date", start, end, filters)}

	begin_stock = stock
	new_cnt = churned = winback = 0
	mrr_new = mrr_churned = 0.0
	life_sum = 0.0
	user_days = 0
	for day in _daterange(start, end):
		node = new_rows.get(day)
		if node:
			new_cnt += int(node.cnt)
			mrr_new += float(node.mrr or 0)
			winback += int(node.winback or 0)
		node = churn_rows.get(day)
		if node:
			churned += int(node.cnt)
			mrr_churned += float(node.mrr or 0)
			life_sum += float(node.life_sum or 0)
		stock += (int(new_rows[day].cnt) if day in new_rows else 0) - (
			int(churn_rows[day].cnt) if day in churn_rows else 0
		)
		user_days += stock

	days = (end - start).days + 1
	avg_active = round(user_days / days, 2) if days else 0.0
	return {
		"start": start,
		"end": end,
		"begin_stock": begin_stock,
		"end_stock": stock,
		"new": new_cnt,
		"new_new": new_cnt - winback,
		"new_winback": winback,
		"churned": churned,
		"net": new_cnt - churned,
		"avg_active": avg_active,
		"user_days": user_days,
		"churn_rate": _churn_rate(
			churned, begin_stock, avg_active, filters["churn_rate_denominator"]
		),
		"mrr_new": round(mrr_new, 2),
		"mrr_churned": round(mrr_churned, 2),
		"mrr_net": round(mrr_new - mrr_churned, 2),
		"avg_lifecycle": round(life_sum / churned, 1) if churned else 0.0,
	}


def compute_kpi(filters: dict) -> dict:
	current = _period_metrics(filters, filters["start"], filters["end"])
	prev_start, prev_end = P.previous_range(filters["start"], filters["end"])
	previous = _period_metrics(filters, prev_start, prev_end)

	arpu = round(0, 2)
	# 期末在服 MRR / 期末在服用户数
	mrr_active = _active_mrr(filters, filters["end"])
	if current["end_stock"]:
		arpu = round(mrr_active / current["end_stock"], 2)
	ltv = round(arpu / (current["churn_rate"] / 100), 2) if current["churn_rate"] else 0.0

	return {
		"period": {
			# 注意：接口返回会经过 json.dumps，日期必须转成字符串
			"start": str(current["start"]),
			"end": str(current["end"]),
			"label": filters["period_label"],
			"days": (current["end"] - current["start"]).days + 1,
		},
		"previous_period": {"start": str(prev_start), "end": str(prev_end)},
		"active_users": current["end_stock"],
		"active_users_delta": _growth(current["end_stock"], previous["end_stock"]),
		"active_users_begin": current["begin_stock"],
		"new_users": current["new"],
		"new_users_new": current["new_new"],
		"new_users_winback": current["new_winback"],
		"new_users_delta": _growth(current["new"], previous["new"]),
		"churned_users": current["churned"],
		"churned_users_delta": _growth(current["churned"], previous["churned"]),
		"net_growth": current["net"],
		"net_growth_delta": _growth(current["net"], previous["net"]),
		"avg_active_users": current["avg_active"],
		"user_days": current["user_days"],
		"churn_rate": current["churn_rate"],
		"churn_rate_delta": round(current["churn_rate"] - previous["churn_rate"], 2),
		"mrr_new": current["mrr_new"],
		"mrr_churned": current["mrr_churned"],
		"mrr_net": current["mrr_net"],
		"mrr_active": round(mrr_active, 2),
		"mrr_net_delta": _growth(current["mrr_net"], previous["mrr_net"]),
		"arpu": arpu,
		"ltv_estimate": ltv,
		"avg_lifecycle_days": current["avg_lifecycle"],
	}


def _active_mrr(filters: dict, day) -> float:
	where, params = _attr_where(filters)
	sql = f"""
		SELECT COALESCE(SUM(r.mrr), 0) AS mrr
		FROM `{TABLE}` r
		WHERE r.activation_date <= %(d)s
		  AND (r.churn_date IS NULL OR r.churn_date > %(d)s)
		{where}
	"""
	params["d"] = day
	rows = frappe.db.sql(sql, params, as_dict=True)
	return float(rows[0].mrr or 0) if rows else 0.0


# ---------------------------------------------------------------------------
# 分布（地域 / 渠道 / 套餐 / 用户类型）
# ---------------------------------------------------------------------------
def compute_distribution(filters: dict, dimension: str) -> list[dict]:
	if dimension not in DIMENSIONS:
		raise frappe.ValidationError(f"分组维度取值不合法：{dimension}")
	start, end = filters["start"], filters["end"]
	where, params = _attr_where(filters, exclude=(dimension,))
	sql = f"""
		SELECT r.{dimension} AS k,
		       SUM(CASE WHEN r.churn_date IS NULL OR r.churn_date > %(end)s THEN 1 ELSE 0 END) AS active_end,
		       SUM(CASE WHEN r.activation_date BETWEEN %(start)s AND %(end)s THEN 1 ELSE 0 END) AS new_in,
		       SUM(CASE WHEN r.churn_date BETWEEN %(start)s AND %(end)s THEN 1 ELSE 0 END) AS churned_in,
		       COALESCE(SUM(CASE WHEN r.churn_date IS NULL OR r.churn_date > %(end)s THEN r.mrr ELSE 0 END), 0) AS active_mrr
		FROM `{TABLE}` r
		WHERE r.activation_date <= %(end)s
		  AND (r.churn_date IS NULL OR r.churn_date >= %(start)s)
		{where}
		GROUP BY k
		ORDER BY active_end DESC, new_in DESC
	"""
	params.update({"start": start, "end": end})
	rows = frappe.db.sql(sql, params, as_dict=True)
	total = sum(int(r.active_end or 0) for r in rows) or 1
	return [
		{
			"key": r.k or "未知",
			"label": r.k or "未知",
			"active": int(r.active_end or 0),
			"new": int(r.new_in or 0),
			"churned": int(r.churned_in or 0),
			"mrr": round(float(r.active_mrr or 0), 2),
			"share": round(int(r.active_end or 0) / total * 100, 2),
		}
		for r in rows
	]


def compute_churn_reasons(filters: dict) -> list[dict]:
	start, end = filters["start"], filters["end"]
	where, params = _attr_where(filters, exclude=("churn_reason_category",))
	sql = f"""
		SELECT r.churn_reason_category AS k,
		       COUNT(*) AS cnt,
		       COALESCE(SUM(r.mrr), 0) AS mrr,
		       COALESCE(AVG(r.lifecycle_days), 0) AS avg_life,
		       COALESCE(AVG(CASE WHEN r.is_recoverable = 1 THEN 1 ELSE 0 END), 0) AS recoverable
		FROM `{TABLE}` r
		WHERE r.churn_date BETWEEN %(start)s AND %(end)s
		{where}
		GROUP BY k
		ORDER BY cnt DESC
	"""
	params.update({"start": start, "end": end})
	rows = frappe.db.sql(sql, params, as_dict=True)
	total = sum(int(r.cnt or 0) for r in rows) or 1
	return [
		{
			"key": r.k or "未知",
			"label": r.k or "未知",
			"count": int(r.cnt or 0),
			"mrr": round(float(r.mrr or 0), 2),
			"share": round(int(r.cnt or 0) / total * 100, 2),
			"avg_lifecycle": round(float(r.avg_life or 0), 1),
			"recoverable_ratio": round(float(r.recoverable or 0) * 100, 1),
		}
		for r in rows
	]


# ---------------------------------------------------------------------------
# 重点客户 / 动态事件
# ---------------------------------------------------------------------------
def compute_top_accounts(filters: dict, limit: int = 8) -> list[dict]:
	limit = max(1, min(int(limit or 8), 50))
	end = filters["end"]
	where, params = _attr_where(filters)
	sql = f"""
		SELECT r.name, r.user_id, r.user_name, r.plan, r.region, r.province,
		       r.mrr, r.health_score, r.risk_level, r.expiry_date,
		       r.lifecycle_seq, r.account_owner
		FROM `{TABLE}` r
		WHERE r.activation_date <= %(end)s
		  AND (r.churn_date IS NULL OR r.churn_date > %(end)s)
		  AND (
		        COALESCE(r.health_score, 0) < 80
		     OR (r.expiry_date IS NOT NULL AND r.expiry_date <= DATE_ADD(%(end)s, INTERVAL 45 DAY))
		  )
		{where}
		ORDER BY (COALESCE(r.mrr, 0) * (100 - COALESCE(r.health_score, 100))) DESC,
		         r.mrr DESC
		LIMIT %(limit)s
	"""
	params.update({"end": end, "limit": limit})
	rows = frappe.db.sql(sql, params, as_dict=True)
	result = []
	for r in rows:
		expiry = to_date(r.expiry_date)
		result.append({
			"name": r.name,
			"user_id": r.user_id,
			"user_name": mask_name(r.user_name),
			"plan": r.plan,
			"region": r.region,
			"province": r.province,
			"mrr": round(float(r.mrr or 0), 2),
			"health_score": int(r.health_score or 0),
			"risk_level": r.risk_level or "中",
			"days_to_expiry": (expiry - end).days if expiry else None,
			"lifecycle_seq": int(r.lifecycle_seq or 1),
			"account_owner": r.account_owner,
		})
	return result


def compute_event_feed(filters: dict, limit: int = 12) -> list[dict]:
	limit = max(1, min(int(limit or 12), 50))
	start, end = filters["start"], filters["end"]
	where, params = _attr_where(filters)
	sql = f"""
		(SELECT r.activation_date AS d, '开通' AS kind, r.user_name, r.plan,
		        r.region, r.mrr
		 FROM `{TABLE}` r
		 WHERE r.activation_date BETWEEN %(start)s AND %(end)s {where}
		 ORDER BY r.activation_date DESC, r.creation DESC
		 LIMIT %(limit)s)
		UNION ALL
		(SELECT r.churn_date AS d, '流失' AS kind, r.user_name, r.plan,
		        r.region, r.mrr
		 FROM `{TABLE}` r
		 WHERE r.churn_date BETWEEN %(start)s AND %(end)s {where}
		 ORDER BY r.churn_date DESC, r.creation DESC
		 LIMIT %(limit)s)
		ORDER BY d DESC
		LIMIT %(limit)s
	"""
	params.update({"start": start, "end": end, "limit": limit})
	rows = frappe.db.sql(sql, params, as_dict=True)
	return [
		{
			"date": str(to_date(r.d)),
			"kind": r.kind,
			"user_name": mask_name(r.user_name),
			"plan": r.plan,
			"region": r.region,
			"mrr": round(float(r.mrr or 0), 2),
		}
		for r in rows
	]


# ---------------------------------------------------------------------------
# 分组序列（报表透视模式）
# ---------------------------------------------------------------------------
def compute_grouped_series(filters: dict, dimension: str, top_n: int = 8) -> dict:
	"""按（时间桶 × 维度值）输出新增 / 流失 / 净增 / 期末在服。"""
	if dimension not in DIMENSIONS:
		raise frappe.ValidationError(f"分组维度取值不合法：{dimension}")

	start, end = filters["start"], filters["end"]
	granularity = filters["granularity"]
	buckets = P.build_buckets(start, end, granularity)
	base_day = start - timedelta(days=1)
	stock_by_key = _stock_at(base_day, filters, dimension=dimension)

	new_rows: dict[tuple, dict] = {}
	for r in _daily_agg("activation_date", start, end, filters, dimension=dimension):
		new_rows[(to_date(r.d), r.k)] = r
	churn_rows: dict[tuple, dict] = {}
	for r in _daily_agg("churn_date", start, end, filters, dimension=dimension):
		churn_rows[(to_date(r.d), r.k)] = r

	# 维度取值（按期末在服数排序，仅展示前 N 个，其余归入"其他"）
	keys = [k for k, _ in sorted(stock_by_key.items(), key=lambda kv: -kv[1])]
	if len(keys) > top_n:
		keys = keys[:top_n]

	stock = dict(stock_by_key)
	rows = []
	for bucket in buckets:
		cells: dict[str, dict] = {}
		for key in keys:
			cells[key] = {"begin": stock.get(key, 0), "new": 0, "churned": 0,
			              "mrr_new": 0.0, "mrr_churned": 0.0}
		for day in _daterange(bucket["start"], bucket["end"]):
			for key in keys:
				node = new_rows.get((day, key))
				if node:
					cells[key]["new"] += int(node.cnt)
					cells[key]["mrr_new"] += float(node.mrr or 0)
					stock[key] = stock.get(key, 0) + int(node.cnt)
				node = churn_rows.get((day, key))
				if node:
					cells[key]["churned"] += int(node.cnt)
					cells[key]["mrr_churned"] += float(node.mrr or 0)
					stock[key] = max(stock.get(key, 0) - int(node.cnt), 0)
		for key in keys:
			cells[key]["end"] = stock.get(key, 0)
			cells[key]["net"] = cells[key]["new"] - cells[key]["churned"]
		rows.append({"key": bucket["key"], "label": bucket["label"], "cells": cells})

	return {"rows": rows, "dimension": dimension, "keys": keys, "granularity": granularity}


# ---------------------------------------------------------------------------
# 口径说明与工具
# ---------------------------------------------------------------------------
def get_caliber(filters: dict) -> dict:
	return {
		"active_users": "区间重叠法：开通日期 <= 时点 且（未流失 或 流失日期 > 时点）",
		"churn_rate_denominator": filters["churn_rate_denominator"],
		"granularity": filters["granularity"],
		"timezone": "Asia/Shanghai",
		"bucket_aligned": "报表按自然时间桶对齐（周从周一起、月/季度/年从自然起点起）",
		"churn_date_semantics": "流失日期当天已不在服（在服 = 开通日期 <= 时点 < 流失日期）",
		"period": {
			"start": str(filters["start"]),
			"end": str(filters["end"]),
			"label": filters["period_label"],
		},
	}


def mask_name(name) -> str:
	"""企业/个人名称脱敏：保留前 2 个字。"""
	text = str(name or "").strip()
	if not text:
		return ""
	if len(text) <= 2:
		return text[0] + "*"
	return text[:2] + "*" * min(len(text) - 2, 4)


def cache_key(prefix: str, filters: dict) -> str:
	"""缓存键：与字典键顺序、多选值顺序无关（同样的筛选必然命中同一个缓存）。"""
	import hashlib
	import json

	payload = {}
	for key in sorted(filters):
		if key == "period_label":
			continue
		value = filters[key]
		if isinstance(value, (date, datetime)):
			value = value.isoformat()
		elif isinstance(value, list):
			value = sorted(
				item.isoformat() if isinstance(item, (date, datetime)) else item
				for item in value
			)
		payload[key] = value
	# 注意两点：
	#   1. 不能用 frappe.generate_hash —— 它带随机盐，同样输入会得到不同结果；
	#   2. 规范化后的筛选里仍可能含 date（区间起止），必须转成字符串再序列化。
	digest = hashlib.sha256(
		json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
	)
	return f"{prefix}:{digest.hexdigest()[:16]}"


def dimension_label(dimension: str) -> str:
	return DIMENSIONS.get(dimension, dimension)
