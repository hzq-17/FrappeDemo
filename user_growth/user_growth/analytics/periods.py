"""时间粒度与时间桶：把任意区间切成连续、无重叠、可比较的时间桶。

时间桶的三个硬约束（后续所有指标都依赖它们）：
1. 桶之间首尾相接、不重叠、不遗漏（相邻桶：next.start = cur.end + 1 天）；
2. 桶按自然日历对齐（周从周一开始、月/季度/年从自然起点开始），
   区间两端的桶被裁剪到区间内；
3. 桶的 key 与数据库聚合表达式的结果完全一致，避免 Python 与 SQL 口径漂移。
"""

import calendar
from datetime import date, timedelta

from user_growth.analytics.rules import to_date

GRANULARITIES = ["日", "周", "月", "季度", "年"]

PRESETS = ["近7天", "近30天", "近90天", "本月", "上月", "本季度", "今年", "近12个月", "自定义"]

# 桶数量上限：超过则提示使用者切换到更粗的粒度（保护查询与渲染性能）
MAX_BUCKETS = 400


# ---------------------------------------------------------------------------
# 日期工具
# ---------------------------------------------------------------------------
def today(ref=None) -> date:
	return to_date(ref) or date.today()


def month_start(d: date) -> date:
	return date(d.year, d.month, 1)


def month_end(d: date) -> date:
	return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def add_months(d: date, months: int) -> date:
	total = (d.year * 12 + d.month - 1) + months
	year, month = divmod(total, 12)
	month += 1
	return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def quarter_start(d: date) -> date:
	return date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)


def week_start(d: date) -> date:
	"""周一为一周的第一天。"""
	return d - timedelta(days=d.weekday())


# ---------------------------------------------------------------------------
# 区间解析
# ---------------------------------------------------------------------------
def resolve_range(preset=None, start=None, end=None, ref=None) -> tuple[date, date]:
	"""把"预设快捷区间"或"自定义起止日期"统一解析成 (start, end)。"""
	ref = today(ref)
	preset = (preset or "").strip()

	if preset in ("", "自定义") or (start and end and preset not in PRESETS):
		s = to_date(start) or (ref - timedelta(days=29))
		e = to_date(end) or ref
		if s > e:
			s, e = e, s
		return s, e

	if preset == "近7天":
		return ref - timedelta(days=6), ref
	if preset == "近30天":
		return ref - timedelta(days=29), ref
	if preset == "近90天":
		return ref - timedelta(days=89), ref
	if preset == "本月":
		return month_start(ref), ref
	if preset == "上月":
		first_this = month_start(ref)
		last_prev = first_this - timedelta(days=1)
		return month_start(last_prev), last_prev
	if preset == "本季度":
		return quarter_start(ref), ref
	if preset == "今年":
		return date(ref.year, 1, 1), ref
	if preset == "近12个月":
		return month_start(add_months(ref, -11)), ref

	# 未知预设：退化为近 30 天，保证不会因为脏参数直接报错
	return ref - timedelta(days=29), ref


def previous_range(start: date, end: date) -> tuple[date, date]:
	"""等长的上一区间（用于环比）。"""
	days = (end - start).days + 1
	prev_end = start - timedelta(days=1)
	return prev_end - timedelta(days=days - 1), prev_end


# ---------------------------------------------------------------------------
# 时间桶
# ---------------------------------------------------------------------------
def bucket_key(d: date, granularity: str) -> str:
	if granularity == "日":
		return d.isoformat()
	if granularity == "周":
		return week_start(d).isoformat()
	if granularity == "月":
		return f"{d.year:04d}-{d.month:02d}"
	if granularity == "季度":
		return f"{d.year:04d}-Q{(d.month - 1) // 3 + 1}"
	if granularity == "年":
		return f"{d.year:04d}"
	raise ValueError(f"未知时间粒度：{granularity}")


def bucket_label(key: str, granularity: str) -> str:
	if granularity == "日":
		return key[5:]  # MM-DD
	if granularity == "周":
		return f"{key[5:]} 周"
	if granularity == "月":
		return key
	if granularity == "季度":
		return key.replace("-", " ")
	if granularity == "年":
		return f"{key} 年"
	return key


def _next_bucket_start(d: date, granularity: str) -> date:
	if granularity == "日":
		return d + timedelta(days=1)
	if granularity == "周":
		return week_start(d) + timedelta(days=7)
	if granularity == "月":
		return month_start(add_months(month_start(d), 1))
	if granularity == "季度":
		return month_start(add_months(quarter_start(d), 3))
	if granularity == "年":
		return date(d.year + 1, 1, 1)
	raise ValueError(f"未知时间粒度：{granularity}")


def build_buckets(start: date, end: date, granularity: str,
                  max_buckets: int | None = MAX_BUCKETS) -> list[dict]:
	"""按粒度切分 [start, end]，返回连续无重叠的时间桶列表。

	max_buckets=None 表示不做上限检查（用于内部扩展区间：扩展段本身不面向用户，
	上限由"可见区间"单独控制）。
	"""
	start, end = to_date(start), to_date(end)
	if not start or not end or start > end:
		return []
	if granularity not in GRANULARITIES:
		raise ValueError(f"未知时间粒度：{granularity}")

	buckets: list[dict] = []
	cursor = start
	while cursor <= end:
		natural_end = _next_bucket_start(cursor, granularity) - timedelta(days=1)
		bucket_end = min(natural_end, end)
		key = bucket_key(cursor, granularity)
		buckets.append({
			"key": key,
			"label": bucket_label(key, granularity),
			"start": cursor,
			"end": bucket_end,
			"days": (bucket_end - cursor).days + 1,
		})
		cursor = bucket_end + timedelta(days=1)

	if max_buckets is not None and len(buckets) > max_buckets:
		raise ValueError(
			f"时间段过长：按「{granularity}」会生成 {len(buckets)} 个时间桶（上限 {max_buckets}），"
			"请缩小时间范围或切换到更粗的时间粒度。"
		)
	return buckets


# ---------------------------------------------------------------------------
# 同比：找到"去年同期"的桶 key
# ---------------------------------------------------------------------------
def shift_year_back_key(key: str, granularity: str) -> str:
	if granularity == "日":
		d = to_date(key)
		try:
			return date(d.year - 1, d.month, d.day).isoformat()
		except ValueError:  # 2/29
			return date(d.year - 1, d.month, 28).isoformat()
	if granularity == "周":
		d = to_date(key)
		return (d - timedelta(days=364)).isoformat()
	if granularity == "月":
		y, m = key.split("-")
		return f"{int(y) - 1:04d}-{m}"
	if granularity == "季度":
		y, q = key.split("-Q")
		return f"{int(y) - 1:04d}-Q{q}"
	if granularity == "年":
		return f"{int(key) - 1:04d}"
	return key


def extended_start(start: date, granularity: str) -> date:
	"""为了计算环比与同比，需要多取一段历史数据。"""
	start = to_date(start)
	if granularity == "日":
		return start - timedelta(days=370)
	if granularity == "周":
		return start - timedelta(days=378)
	if granularity == "月":
		return month_start(add_months(start, -12))
	if granularity == "季度":
		return month_start(add_months(quarter_start(start), -12))
	return date(start.year - 1, 1, 1)


def format_period(start: date, end: date, granularity: str | None = None) -> str:
	start, end = to_date(start), to_date(end)
	if granularity == "月" and start.year == end.year and start.month == end.month:
		return f"{start.year:04d}-{start.month:02d}"
	return f"{start.isoformat()} ~ {end.isoformat()}"
