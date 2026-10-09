"""Mock 数据生成算法（纯函数：不查库、不写库，便于单测与复现）。

生成顺序严格按时间推进：先开通、后流失、再唤回。
这样"流失日期 >= 开通日期"是构造出来的，而不是事后修补出来的。
"""

import random
from datetime import date, timedelta

from user_growth.analytics import constants as C
from user_growth.analytics import periods as P
from user_growth.analytics import rules
from user_growth.seed import distributions as D


def _weighted(rnd: random.Random, weights: dict):
	items = list(weights.items())
	return rnd.choices([k for k, _ in items], weights=[w for _, w in items], k=1)[0]


def _region_province(rnd):
	region = _weighted(rnd, D.REGION_WEIGHTS)
	candidates = [p for p, r in C.PROVINCE_TO_REGION.items() if r == region]
	province = rnd.choice(candidates)
	city = rnd.choice(C.CITY_BY_PROVINCE.get(province, [province]))
	return region, province, city


def _make_name(rnd, index: int) -> str:
	# 前 200 个名称固定，便于演示时指认具体客户
	if index <= len(D.NAME_PREFIX) * len(D.NAME_SUFFIX):
		prefix = D.NAME_PREFIX[(index - 1) % len(D.NAME_PREFIX)]
		suffix = D.NAME_SUFFIX[(index - 1) // len(D.NAME_PREFIX) % len(D.NAME_SUFFIX)]
	else:
		prefix = rnd.choice(D.NAME_PREFIX)
		suffix = rnd.choice(D.NAME_SUFFIX)
	return f"{prefix}{suffix}"


def _deadline(rnd, activation: date, billing_cycle: str) -> date:
	if billing_cycle == "免费":
		return activation + timedelta(days=rnd.randint(*D.FREE_TRIAL_DAYS))
	months = C.BILLING_CYCLE_MONTHS.get(billing_cycle, 1)
	return P.add_months(activation, months)


def _churn_probability(plan: str, channel: str, user_type: str, billing_cycle: str) -> float:
	base = D.PLAN_CHURN_BASE.get(plan, 0.03)
	base *= D.CHANNEL_CHURN_FACTOR.get(channel, 1.0)
	base *= D.USER_TYPE_CHURN_FACTOR.get(user_type, 1.0)
	# 年付/多年付的客户流失率更低（决策成本更高）
	base *= {"月付": 1.15, "季付": 1.05, "半年付": 0.95, "年付": 0.85, "多年付": 0.7}.get(
		billing_cycle, 1.0
	)
	return max(0.002, min(base, 0.6))


def _health_score(rnd, plan: str, user_type: str) -> int:
	base = 74 + (8 if user_type == "企业" else 0) + {"旗舰版": 6, "定制版": 8}.get(plan, 0)
	return max(30, min(99, int(rnd.gauss(base, 9))))


def _build_record(rnd, index: int, activation: date, user_type: str, region: str,
                  province: str, city: str, channel: str, plan: str,
                  user_id: str, user_name: str, seq: int,
                  previous_churn: date | None, ref: date) -> dict:
	segment = _weighted(rnd, dict(D.SEGMENT_BY_TYPE[user_type]))
	industry = _weighted(rnd, D.INDUSTRY_WEIGHTS)
	billing_cycle = "免费" if plan == C.FREE_PLAN else _weighted(rnd, D.BILLING_WEIGHTS)
	seats = rnd.randint(*D.PLAN_SEATS.get(plan, (1, 3)))
	discount = 0 if plan == C.FREE_PLAN else _weighted(rnd, dict(D.DISCOUNT_CHOICES))

	price = D.PLAN_PRICE.get(plan, 0)
	if plan == C.FREE_PLAN:
		contract_amount = 0.0
	else:
		months = C.BILLING_CYCLE_MONTHS.get(billing_cycle, 1)
		contract_amount = round(price * months * (1 - discount / 100.0), 2)

	health = _health_score(rnd, plan, user_type)
	source_detail = rnd.choice(C.CHANNEL_SOURCE_DETAIL.get(channel, [channel]))
	campaign = (
		f"CMP-{activation.year}{activation.month:02d}-{rnd.randint(100, 999)}"
		if channel in C.PAID_CHANNELS else ""
	)
	partner = rnd.choice(["云生态联盟", "区域服务商", "行业集成商"]) if channel in (
		"合作伙伴", "代理商") else ""

	record = {
		"user_id": user_id,
		"user_name": user_name,
		"user_type": user_type,
		"segment": segment,
		"industry": industry,
		"country": "海外" if region == "海外" else "中国",
		"province": province,
		"city": city,
		"region": region,
		"acquisition_channel": channel,
		"source_detail": source_detail,
		"campaign": campaign,
		"partner_name": partner,
		"is_paid_acquisition": 1 if channel in C.PAID_CHANNELS else 0,
		"plan": plan,
		"billing_cycle": billing_cycle,
		"seats": seats,
		"currency": "CNY",
		"discount_percent": discount,
		"contract_amount": contract_amount,
		"auto_renew": 0 if plan == C.FREE_PLAN else (1 if rnd.random() < 0.62 else 0),
		"lifecycle_seq": seq,
		"activation_date": activation,
		"service_start_date": activation,
		"expiry_date": _deadline(rnd, activation, billing_cycle),
		"health_score": health,
		"is_recoverable": 1,
		"is_paused": 0,
		"previous_churn_date": previous_churn,
		"account_owner": "Administrator" if plan in ("企业版", "旗舰版", "定制版") else None,
		"data_source": "模拟数据",
		"_index": index,
	}
	return record


def generate(months: int = 24, seed: int = 20260101, ref: date | None = None) -> list[dict]:
	"""生成 24 个月（可配）的服务生命周期记录。"""
	rnd = random.Random(seed)
	ref = rules.to_date(ref) or date.today()
	months = max(6, min(int(months or 24), 60))
	first_month = P.month_start(P.add_months(ref, -(months - 1)))

	records: list[dict] = []
	active: list[dict] = []
	user_index = 0
	row_index = 0

	for offset in range(months):
		month = P.add_months(first_month, offset)
		month_end = P.month_end(month)
		if month > ref:
			break

		# ---- 1. 本月新增 ----
		year_factor = 1.0 + D.YEARLY_GROWTH * (month.year - first_month.year)
		seasonal = D.SEASONALITY[month.month - 1]
		count = max(6, int(D.BASE_NEW_USERS_PER_MONTH * year_factor * seasonal
		                  * rnd.uniform(0.92, 1.08)))
		# 当月只到"今天"为止（不做未来日期）
		last_day = min(month_end, ref)
		day_span = (last_day - month).days
		if day_span < 0:
			break

		for _ in range(count):
			user_index += 1
			row_index += 1
			activation = month + timedelta(days=rnd.randint(0, day_span))
			user_type = _weighted(rnd, D.USER_TYPE_WEIGHTS)
			plan = _weighted(rnd, D.PLAN_WEIGHTS)
			channel = _weighted(rnd, D.CHANNEL_WEIGHTS)
			region, province, city = _region_province(rnd)
			user_id = f"U{user_index:07d}"
			user_name = _make_name(rnd, user_index)
			record = _build_record(rnd, row_index, activation, user_type, region, province,
			                       city, channel, plan, user_id, user_name, 1, None, ref)
			records.append(record)
			active.append(record)

		# ---- 2. 本月流失判定（含唤回生成）----
		winbacks: list[dict] = []
		for record in active:
			if record.get("churn_date"):
				continue
			probability = _churn_probability(
				record["plan"], record["acquisition_channel"],
				record["user_type"], record["billing_cycle"],
			)
			if rnd.random() >= probability:
				continue
			start = max(record["activation_date"], month)
			if start > last_day:
				continue
			churn_date = start + timedelta(days=rnd.randint(0, (last_day - start).days))
			_finalize_churn(rnd, record, churn_date)

			# 唤回：生成同一客户的第二段生命周期
			if record["is_recoverable"] and rnd.random() < D.WINBACK_RATIO:
				delay = rnd.randint(*D.WINBACK_DELAY_DAYS)
				new_activation = churn_date + timedelta(days=delay)
				# 序号必须递增，否则同一客户会出现重复的生命周期序号
				next_seq = int(record["lifecycle_seq"]) + 1
				if new_activation <= ref and next_seq <= 3:
					row_index += 1
					upgraded = _upgrade_plan(rnd, record["plan"])
					winback = _build_record(
						rnd, row_index, new_activation, record["user_type"], record["region"],
						record["province"], record["city"], "老客推荐", upgraded,
						record["user_id"], record["user_name"], next_seq, churn_date, ref,
					)
					winback["first_activation_date"] = record.get(
						"first_activation_date", record["activation_date"]
					)
					winbacks.append(winback)

		active.extend(winbacks)
		records.extend(winbacks)

	# ---- 3. 收尾：未流失记录的空缺字段与派生字段 ----
	for record in records:
		record.pop("_index", None)
		record.setdefault("first_activation_date", record["activation_date"])
		if record["lifecycle_seq"] == 1:
			record["first_activation_date"] = record["activation_date"]
		if record.get("churn_date") and record["activation_date"] > record["churn_date"]:
			record["churn_date"] = record["activation_date"]
		if record["billing_cycle"] != "免费" and not record.get("churn_date"):
			renewed = P.add_months(record["service_start_date"], 1)
			record["last_renewal_date"] = renewed if renewed <= ref else None
		record.update(rules.derive(record, ref))

	return _assign_names(records)


def _upgrade_plan(rnd, plan: str) -> str:
	order = C.PLAN_NAMES
	if plan == C.FREE_PLAN:
		return _weighted(rnd, {"基础版": 60, "专业版": 40})
	index = min(order.index(plan) + (1 if rnd.random() < 0.35 else 0), len(order) - 1)
	return order[max(index, 1)]


def _finalize_churn(rnd, record: dict, churn_date: date) -> None:
	reason = _weighted(rnd, D.CHURN_REASON_WEIGHTS)
	if record["plan"] == C.FREE_PLAN and rnd.random() < 0.75:
		reason = "试用结束"
	record["churn_date"] = churn_date
	record["churn_reason_category"] = reason
	record["churn_type"] = D.CHURN_TYPE_BY_REASON.get(reason, "主动流失")
	record["churn_reason"] = D.CHURN_REASON_TEXT.get(reason, "")
	if reason == "竞品替换":
		record["competitor"] = rnd.choice(D.COMPETITORS)
	record["is_recoverable"] = 0 if (
		reason in D.NOT_RECOVERABLE_REASONS and rnd.random() < 0.7
	) else 1
	record["health_score"] = max(
		20, int(record["health_score"] * (0.78 if reason != "试用结束" else 0.9))
	)
	record["winback_note"] = "" if record["is_recoverable"] else "客户已转向替代方案，暂不跟进"


def _assign_names(records: list[dict]) -> list[dict]:
	"""把命名系列规则（USR-YYYY-#####）落到 name 字段，保证可重复生成同名记录。"""
	used: set[str] = set()
	for index, record in enumerate(records, start=1):
		year = rules.to_date(record["activation_date"]).year
		candidate = f"USR-{year}-{index:05d}"
		suffix = 0
		while candidate in used:
			suffix += 1
			candidate = f"USR-{year}-{index:05d}-{suffix}"
		used.add(candidate)
		record["name"] = candidate
	return records
