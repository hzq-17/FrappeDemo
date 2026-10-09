"""通用接口：枚举字典、省份到大区的映射、指标口径说明。"""

import frappe

from user_growth.analytics import constants as C
from user_growth.analytics import metrics, periods


@frappe.whitelist()
def get_filter_options():
	"""返回全部受控枚举，供前端构建筛选器与图例（枚举的唯一来源在后端）。"""
	cache = frappe.cache()
	cache_key = "user_growth:filter_options"
	cached = cache.get_value(cache_key)
	if cached:
		return cached

	options = {
		"regions": C.REGIONS,
		"provinces": C.PROVINCES,
		"province_region_map": C.PROVINCE_TO_REGION,
		"channels": C.CHANNELS,
		"plans": C.PLAN_NAMES,
		"plan_tiers": C.PLAN_TIERS,
		"user_types": C.USER_TYPES,
		"segments": C.SEGMENTS,
		"industries": C.INDUSTRIES,
		"billing_cycles": C.BILLING_CYCLES,
		"statuses": C.STATUSES,
		"churn_types": C.CHURN_TYPES,
		"churn_reasons": C.CHURN_REASONS,
		"risk_levels": C.RISK_LEVELS,
		"granularities": periods.GRANULARITIES,
		"presets": periods.PRESETS,
		"churn_rate_denominators": metrics.CHURN_DENOMINATORS,
		"group_by": [{"value": "", "label": "不分组"}]
		+ [{"value": key, "label": label} for key, label in metrics.DIMENSIONS.items()],
		"status_colors": C.STATUS_COLORS,
		"hex": C.HEX,
	}
	cache.set_value(cache_key, options, expires_in_sec=3600)
	return options


@frappe.whitelist()
def get_region_for_province(province):
	"""省份 -> 大区。表单里选择省份时即时回填大区（口径与后端一致）。"""
	if not province:
		frappe.throw("请先选择省份", frappe.ValidationError)
	return {"province": province, "region": C.region_of(province)}


@frappe.whitelist()
def get_caliber_note():
	"""指标口径说明：报表页与文档都引用同一份文案。"""
	return {
		"active_users": "在服用户数：开通日期 <= 统计时点，且（未流失 或 流失日期 > 统计时点）",
		"new_users": "新增用户数：开通日期落在统计区间内的记录数（含新客与唤回）",
		"churned_users": "流失用户数：流失日期落在统计区间内、状态为已流失的记录数",
		"net_growth": "净增长 = 新增用户数 − 流失用户数",
		"churn_rate": "流失率 = 流失用户数 ÷ 分母；分母可选「期初在服」（默认）或「平均在服」（逐日在服均值）",
		"mrr": "MRR = 合同金额 ÷ 计费月数；免费套餐为 0；期末在服 MRR 用于计算 ARPU",
		"ltv": "LTV 估算 = ARPU ÷ 月流失率（简化估算，仅供参考）",
		"churn_date": "流失日期当天视为已不在服",
	}


@frappe.whitelist()
def generate_demo_data(months=None, reset=None):
	"""重新生成演示数据（仅系统管理员；幂等）。

	由单据列表/表单上的「生成演示数据」按钮调用，也可用命令行：
	    bench --site <site> execute user_growth.seed.runner.run_cli --kwargs "{'reset': 1}"
	"""
	if "System Manager" not in frappe.get_roles():
		frappe.throw("只有系统管理员可以生成演示数据", frappe.PermissionError)

	from user_growth.seed import runner

	return runner.run_cli(months=months or 24, reset=reset or 0)
