"""增长大屏的数据接口。

设计要点
--------
* 首屏只需要一次请求（get_dashboard_data），避免大屏出现"面板陆续跳出"的抖动；
* 交互式切换（时间范围、粒度）走轻量接口，只更新需要变化的部分；
* 缓存键里带上数据版本（最近一次写入时间），因此任何数据变更都会自动失效缓存，
  不需要靠"记得清缓存"来保证正确性；
* 展示层只拿聚合结果，明细与自由文本不出接口，用户名称按规则脱敏。
"""

import frappe
from frappe.utils import now

from user_growth.analytics import metrics

DOCTYPE = "User Service Record"
CACHE_TTL = 60
# 缓存载荷的结构版本：返回结构变化时递增，避免旧缓存被新前端误读
CACHE_SCHEMA = "v1"


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _guard():
	"""登录态 + 单据读取权限校验（接口不信任前端）。"""
	user = frappe.session.user
	if not user or user == "Guest":
		raise frappe.PermissionError("请先登录后再访问增长大屏")
	if not frappe.has_permission(DOCTYPE, "read"):
		raise frappe.PermissionError("当前账号没有查看用户服务记录的权限，请联系管理员开通")


def _data_version() -> str:
	rows = frappe.db.sql(f"SELECT COALESCE(MAX(modified), '') AS v FROM `tab{DOCTYPE}`")
	return str(rows[0][0]) if rows else ""


def _cache_key(namespace: str, filters: dict) -> str:
	"""缓存键 = 数据集名 + 载荷结构版本 + 筛选条件指纹 + 数据版本。

	其中「数据集名」（namespace）是关键：见 _cached 的说明。
	数据版本取最近一次写入时间，因此任何数据变更都会自然失效，不依赖"记得清缓存"。
	"""
	return (
		f"{metrics.cache_key(f'user_growth:screen:{namespace}:{CACHE_SCHEMA}', filters)}"
		f":{_data_version()}"
	)


def _cached(builder, filters: dict, ttl: int = CACHE_TTL, namespace: str = "dashboard"):
	"""按「数据集名 + 筛选条件 + 数据版本」缓存。

	⚠️ 每个接口必须传不同的 namespace。曾经踩过的坑：整包接口与趋势接口共用同一个
	缓存键，同一次筛选下先请求整包（缓存下来）再请求趋势时，趋势接口会命中整包载荷，
	前端拿到的是没有 labels 字段的 dashboard 数据，趋势图就变成空白（且只在缓存有效期
	内、且顺序恰好时才复现 —— 典型的"有时候没数据"）。
	"""
	key = _cache_key(namespace, filters)
	cache = frappe.cache()
	hit = cache.get_value(key)
	if hit:
		return hit, True
	value = builder()
	cache.set_value(key, value, expires_in_sec=ttl)
	return value, False


def _envelope(data, filters: dict, cached: bool = False):
	return {
		"code": 0,
		"msg": "ok",
		"generated_at": now(),
		"cached": cached,
		"caliber": metrics.get_caliber(filters),
		"data": data,
	}


def _distributions(filters: dict) -> dict:
	province = metrics.compute_distribution(filters, "province")
	# 大区由省份聚合得到，保证"省份 -> 大区"只有一处映射
	region_map: dict[str, dict] = {}
	for row in province:
		region = metrics.C.region_of(row["key"])
		acc = region_map.setdefault(region, {"key": region, "label": region, "active": 0,
		                                    "new": 0, "churned": 0, "mrr": 0.0})
		for field in ("active", "new", "churned"):
			acc[field] += row[field]
		acc["mrr"] += row["mrr"]
	total = sum(item["active"] for item in region_map.values()) or 1
	regions = sorted(region_map.values(), key=lambda item: -item["active"])
	for item in regions:
		item["share"] = round(item["active"] / total * 100, 2)
		item["mrr"] = round(item["mrr"], 2)
	return {
		"region": regions,
		"province": province,
		"channel": metrics.compute_distribution(filters, "acquisition_channel"),
		"plan": metrics.compute_distribution(filters, "plan"),
		"user_type": metrics.compute_distribution(filters, "user_type"),
	}


def build_dashboard_payload(filters: dict, limit: int = 8) -> dict:
	"""组装大屏首屏所需的全部数据（不做权限判断，便于内部工具复用）。"""
	series = metrics.compute_series(filters)
	visible = series["visible"]
	return {
		"kpi": metrics.compute_kpi(filters),
		"trend": {
			"labels": [row["label"] for row in visible],
			"keys": [row["key"] for row in visible],
			"new": [row["new"] for row in visible],
			"churned": [row["churned"] for row in visible],
			"net": [row["net"] for row in visible],
			"active": [row["end"] for row in visible],
			"churn_rate": [row["churn_rate"] for row in visible],
			"granularity": series["granularity"],
		},
		"distribution": _distributions(filters),
		"churn_reasons": metrics.compute_churn_reasons(filters),
		"top_accounts": metrics.compute_top_accounts(filters, limit),
		"events": metrics.compute_event_feed(filters, 12),
		"filters": {
			"preset": filters["preset"],
			"start": str(filters["start"]),
			"end": str(filters["end"]),
			"granularity": filters["granularity"],
			"region": filters.get("region") or [],
			"plan": filters.get("plan") or [],
			"acquisition_channel": filters.get("acquisition_channel") or [],
		},
	}


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
@frappe.whitelist()
def get_dashboard_data(filters=None, limit=None):
	"""首屏全量数据：KPI + 趋势 + 分布 + 流失原因 + 重点客户 + 动态事件。"""
	_guard()
	normalized = metrics.normalize_filters(
		filters, default_granularity=metrics.SCREEN_GRANULARITY
	)
	limit = int(limit or 8)
	data, cached = _cached(
		lambda: build_dashboard_payload(normalized, limit), normalized, CACHE_TTL,
		namespace="dashboard",
	)
	return _envelope(data, normalized, cached)


@frappe.whitelist()
def get_kpi_summary(filters=None):
	_guard()
	normalized = metrics.normalize_filters(filters, default_granularity=metrics.SCREEN_GRANULARITY)
	data, cached = _cached(
		lambda: metrics.compute_kpi(normalized), normalized, CACHE_TTL, namespace="kpi"
	)
	return _envelope(data, normalized, cached)


@frappe.whitelist()
def get_trend_series(filters=None):
	_guard()
	normalized = metrics.normalize_filters(filters, default_granularity=metrics.SCREEN_GRANULARITY)

	def builder():
		series = metrics.compute_series(normalized)
		visible = series["visible"]
		return {
			"labels": [row["label"] for row in visible],
			"keys": [row["key"] for row in visible],
			"new": [row["new"] for row in visible],
			"churned": [row["churned"] for row in visible],
			"net": [row["net"] for row in visible],
			"active": [row["end"] for row in visible],
			"churn_rate": [row["churn_rate"] for row in visible],
			"granularity": series["granularity"],
		}

	data, cached = _cached(builder, normalized, CACHE_TTL, namespace="trend")
	return _envelope(data, normalized, cached)


@frappe.whitelist()
def get_region_breakdown(filters=None, region=None):
	"""区域下钻：某个大区内部的省份 / 渠道 / 套餐结构与 KPI。"""
	_guard()
	raw = frappe.parse_json(filters) if isinstance(filters, str) else dict(filters or {})
	if region:
		raw["region"] = [region]
	normalized = metrics.normalize_filters(raw, default_granularity=metrics.SCREEN_GRANULARITY)

	def builder():
		return {
			"region": region or "全部",
			"kpi": metrics.compute_kpi(normalized),
			"province": metrics.compute_distribution(normalized, "province"),
			"channel": metrics.compute_distribution(normalized, "acquisition_channel"),
			"plan": metrics.compute_distribution(normalized, "plan"),
		}

	data, cached = _cached(builder, normalized, CACHE_TTL, namespace="region")
	return _envelope(data, normalized, cached)


@frappe.whitelist()
def get_churn_reasons(filters=None):
	_guard()
	normalized = metrics.normalize_filters(filters, default_granularity=metrics.SCREEN_GRANULARITY)
	data, cached = _cached(
		lambda: metrics.compute_churn_reasons(normalized), normalized, CACHE_TTL * 2,
		namespace="churn",
	)
	return _envelope(data, normalized, cached)


@frappe.whitelist()
def get_top_accounts(filters=None, limit=None):
	_guard()
	normalized = metrics.normalize_filters(filters, default_granularity=metrics.SCREEN_GRANULARITY)
	limit = int(limit or 8)
	data, cached = _cached(
		lambda: metrics.compute_top_accounts(normalized, limit), normalized, CACHE_TTL * 2,
		namespace="top",
	)
	return _envelope(data, normalized, cached)


@frappe.whitelist()
def get_event_feed(filters=None, limit=None):
	_guard()
	normalized = metrics.normalize_filters(filters, default_granularity=metrics.SCREEN_GRANULARITY)
	return _envelope(
		metrics.compute_event_feed(normalized, int(limit or 12)), normalized, False
	)
