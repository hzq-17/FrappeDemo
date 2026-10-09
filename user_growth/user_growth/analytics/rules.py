"""单据的派生规则与校验规则（纯函数，不依赖 frappe，可单元测试）。

DocType 控制器与 Mock 数据生成器共用这里的实现，
保证"系统录入的数据"和"生成的数据"遵守完全相同的口径。
"""

from datetime import date, datetime

from user_growth.analytics.constants import (
	BILLING_CYCLE_MONTHS,
	CHURN_REASONS,
	CHURN_TYPES,
	FREE_PLAN,
	HEALTH_SCORE_DEFAULT,
	PLAN_MAP,
	PROVINCE_TO_REGION,
	RISK_THRESHOLDS,
	STATUSES,
)

ERROR = "error"
WARNING = "warning"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def to_date(value):
	"""把字符串 / date / datetime 统一转成 date；空值返回 None。"""
	if value in (None, ""):
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	text = str(value).strip()
	if not text:
		return None
	for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
		try:
			return datetime.strptime(text[: len(fmt) + 2].strip(), fmt).date()
		except ValueError:
			continue
	# 交给 datetime.fromisoformat 兜底
	try:
		return datetime.fromisoformat(text).date()
	except ValueError:
		return None


def today() -> date:
	return date.today()


# ---------------------------------------------------------------------------
# 派生字段
# ---------------------------------------------------------------------------
def plan_tier(plan: str) -> str:
	return PLAN_MAP.get(plan, {}).get("tier", "标准版")


def list_price(plan: str) -> float:
	return float(PLAN_MAP.get(plan, {}).get("price", 0) or 0)


def is_paid(plan: str) -> bool:
	return bool(plan) and plan != FREE_PLAN


def compute_mrr(plan: str, billing_cycle: str, contract_amount) -> float:
	"""MRR = 合同金额 / 计费月数；免费套餐恒为 0。"""
	if not is_paid(plan):
		return 0.0
	months = BILLING_CYCLE_MONTHS.get(billing_cycle or "", 1) or 1
	try:
		amount = float(contract_amount or 0)
	except (TypeError, ValueError):
		amount = 0.0
	return round(amount / months, 2)


def compute_lifecycle_days(activation_date, churn_date=None, ref: date | None = None) -> int | None:
	start = to_date(activation_date)
	if not start:
		return None
	end = to_date(churn_date) or (ref or today())
	return max((end - start).days, 0)


def compute_status(doc: dict, ref: date | None = None) -> str:
	"""状态机（优先级从高到低）：
	已流失 > 待生效 > 已暂停 > 已到期 > 服务中
	"""
	ref = ref or today()
	if to_date(doc.get("churn_date")):
		return "已流失"
	start = to_date(doc.get("service_start_date")) or to_date(doc.get("activation_date"))
	if start and ref < start:
		return "待生效"
	if doc.get("is_paused"):
		return "已暂停"
	expiry = to_date(doc.get("expiry_date"))
	if expiry and ref > expiry:
		return "已到期"
	return "服务中"


def compute_risk_level(health_score) -> str:
	try:
		score = float(health_score)
	except (TypeError, ValueError):
		score = HEALTH_SCORE_DEFAULT
	if score >= RISK_THRESHOLDS["low"]:
		return "低"
	if score >= RISK_THRESHOLDS["medium"]:
		return "中"
	return "高"


def compute_days_to_expiry(expiry_date, churn_date=None, ref: date | None = None) -> int | None:
	if to_date(churn_date):
		return None
	expiry = to_date(expiry_date)
	if not expiry:
		return None
	return (expiry - (ref or today())).days


def derive(doc: dict, ref: date | None = None) -> dict:
	"""返回派生字段字典（不改动入参，便于生成器批量调用）。"""
	ref = ref or today()
	plan = doc.get("plan")
	seq = int(doc.get("lifecycle_seq") or 1)
	activation = to_date(doc.get("activation_date"))
	return {
		"plan_tier": plan_tier(plan),
		"list_price": list_price(plan),
		"is_paid": 1 if is_paid(plan) else 0,
		"mrr": compute_mrr(plan, doc.get("billing_cycle"), doc.get("contract_amount")),
		"lifecycle_days": compute_lifecycle_days(activation, doc.get("churn_date"), ref),
		"days_to_expiry": compute_days_to_expiry(doc.get("expiry_date"), doc.get("churn_date"), ref),
		"is_new_customer": 1 if seq == 1 else 0,
		"is_winback": 1 if seq > 1 else 0,
		"risk_level": compute_risk_level(doc.get("health_score", HEALTH_SCORE_DEFAULT)),
		"status": compute_status(doc, ref),
		"region": doc.get("region") or PROVINCE_TO_REGION.get(doc.get("province"), "华北"),
	}


def apply_derive(doc: dict, ref: date | None = None) -> dict:
	"""就地写入派生字段，返回同一个 dict（控制器与生成器使用）。"""
	doc.update(derive(doc, ref))
	return doc


# ---------------------------------------------------------------------------
# 校验（纯规则部分；需要查库的规则在 DocType 控制器里补充）
# ---------------------------------------------------------------------------
def validate_rules(doc: dict, ref: date | None = None) -> list[dict]:
	ref = ref or today()
	issues: list[dict] = []

	def err(fieldname, message):
		issues.append({"fieldname": fieldname, "message": message, "level": ERROR})

	def warn(fieldname, message):
		issues.append({"fieldname": fieldname, "message": message, "level": WARNING})

	activation = to_date(doc.get("activation_date"))
	churn = to_date(doc.get("churn_date"))
	start = to_date(doc.get("service_start_date"))
	expiry = to_date(doc.get("expiry_date"))
	plan = doc.get("plan")
	seq = int(doc.get("lifecycle_seq") or 1)

	# RB-01
	if not activation:
		err("activation_date", "请填写本次开通日期")
	elif activation > ref:
		err("activation_date", "开通日期不能是未来日期")

	# RB-02
	if churn and activation and churn < activation:
		err("churn_date", "流失日期必须晚于或等于开通日期")

	# RB-03
	if start and activation and start < activation:
		err("service_start_date", "服务生效日期不能早于开通日期")

	# RB-04
	if expiry and start and expiry < start:
		err("expiry_date", "到期日期不能早于服务生效日期")
	elif expiry and not start and activation and expiry < activation:
		err("expiry_date", "到期日期不能早于开通日期")

	# RB-05 / RB-06
	if churn:
		if not doc.get("churn_type"):
			err("churn_type", "已流失记录必须填写流失类型")
		elif doc.get("churn_type") not in CHURN_TYPES:
			err("churn_type", "流失类型取值不合法")
		if not doc.get("churn_reason_category"):
			err("churn_reason_category", "已流失记录必须填写流失原因分类")
		elif doc.get("churn_reason_category") not in CHURN_REASONS:
			err("churn_reason_category", "流失原因分类取值不合法")
		if doc.get("churn_reason_category") == "竞品替换" and not doc.get("competitor"):
			err("competitor", "流失原因为竞品替换时，请填写替换的竞品名称")

	# RB-07 / RB-14
	try:
		amount = float(doc.get("contract_amount") or 0)
		if amount < 0:
			err("contract_amount", "合同金额不能为负数")
	except (TypeError, ValueError):
		err("contract_amount", "合同金额必须是数字")

	try:
		discount = float(doc.get("discount_percent") or 0)
		if discount < 0 or discount > 100:
			err("discount_percent", "折扣率必须在 0~100 之间")
	except (TypeError, ValueError):
		err("discount_percent", "折扣率必须是数字")

	try:
		score = float(doc.get("health_score", HEALTH_SCORE_DEFAULT))
		if score < 0 or score > 100:
			err("health_score", "客户健康分必须在 0~100 之间")
	except (TypeError, ValueError):
		err("health_score", "客户健康分必须是数字")

	if seq < 1:
		err("lifecycle_seq", "生命周期序号必须大于等于 1")

	# RB-09
	if seq == 1:
		first = to_date(doc.get("first_activation_date"))
		if first and activation and first != activation:
			err("first_activation_date", "首段生命周期的首次开通日期应等于本次开通日期")

	# RB-12
	if plan == FREE_PLAN and float(doc.get("contract_amount") or 0) > 0:
		err("contract_amount", "免费试用套餐不应填写合同金额")
	if plan != FREE_PLAN and not doc.get("billing_cycle"):
		err("billing_cycle", "付费套餐必须填写计费周期")

	# RB-13（信息提示，不阻断）
	# status 为派生字段，控制器会在保存前重算，此处仅做取值校验
	if doc.get("status") and doc.get("status") not in STATUSES:
		err("status", "服务状态取值不合法")

	# RB-15
	if not churn and doc.get("health_score") in (None, ""):
		warn("health_score", "建议填写客户健康分，以便进行流失预警")

	return issues


def error_messages(issues: list[dict]) -> list[dict]:
	return [i for i in issues if i["level"] == ERROR]


def warning_messages(issues: list[dict]) -> list[dict]:
	return [i for i in issues if i["level"] == WARNING]
