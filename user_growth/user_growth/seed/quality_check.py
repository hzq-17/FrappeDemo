"""数据质量自检：把"数据看起来对"变成可执行的断言。"""

from user_growth.analytics import constants as C

DOCTYPE = "User Service Record"
TABLE = "tabUser Service Record"


def _count(condition: str, params=None) -> int:
	import frappe

	rows = frappe.db.sql(f"SELECT COUNT(*) FROM `{TABLE}` WHERE {condition}", params or {})
	return int(rows[0][0] or 0) if rows else 0


def run() -> list[dict]:
	import frappe

	results: list[dict] = []

	def check(code, name, count, ok_message, level="fail"):
		ok = count == 0
		results.append({
			"code": code,
			"name": name,
			"status": "pass" if ok else level,
			"detail": ok_message if ok else f"{count} 条记录不符合要求",
			"count": count,
		})

	check("QC-01", "开通日期不得晚于今天",
	      _count("activation_date > CURDATE()"), "通过：无未来开通日期")
	check("QC-02", "流失日期不得早于开通日期",
	      _count("churn_date IS NOT NULL AND churn_date < activation_date"),
	      "通过：流失日期均不早于开通日期")
	check("QC-03", "到期日期不得早于服务生效日期",
	      _count("expiry_date IS NOT NULL AND service_start_date IS NOT NULL "
	             "AND expiry_date < service_start_date"),
	      "通过：到期日期合法")
	check("QC-04", "流失记录必须填写流失类型与原因",
	      _count("churn_date IS NOT NULL AND (churn_type IS NULL OR churn_reason_category IS NULL)"),
	      "通过：流失记录字段完整")
	check("QC-05", "枚举取值必须在受控列表内",
	      _count("region NOT IN %(regions)s OR plan NOT IN %(plans)s "
	             "OR acquisition_channel NOT IN %(channels)s "
	             "OR status NOT IN %(statuses)s",
	             {"regions": tuple(C.REGIONS), "plans": tuple(C.PLAN_NAMES),
	              "channels": tuple(C.CHANNELS), "statuses": tuple(C.STATUSES)}),
	      "通过：枚举取值受控")
	check("QC-06", "金额非负、折扣率与健康分在范围内",
	      _count("contract_amount < 0 OR discount_percent < 0 OR discount_percent > 100 "
	             "OR health_score < 0 OR health_score > 100"),
	      "通过：数值范围合法")

	duplicates = frappe.db.sql(
		f"SELECT COUNT(*) FROM (SELECT user_id, lifecycle_seq FROM `{TABLE}` "
		"GROUP BY user_id, lifecycle_seq HAVING COUNT(*) > 1) t"
	)
	check("QC-07", "同一用户的生命周期序号唯一",
	      int(duplicates[0][0] or 0) if duplicates else 0, "通过：生命周期序号唯一")

	overlaps = frappe.db.sql(
		f"""
		SELECT COUNT(*) FROM `{TABLE}` a
		JOIN `{TABLE}` b
		  ON a.user_id = b.user_id AND a.name < b.name
		WHERE a.activation_date < COALESCE(b.churn_date, '9999-12-31')
		  AND b.activation_date < COALESCE(a.churn_date, '9999-12-31')
		"""
	)
	check("QC-07b", "同一用户的多段生命周期不重叠",
	      int(overlaps[0][0] or 0) if overlaps else 0, "通过：生命周期区间不重叠")

	trend = frappe.db.sql(
		f"""
		SELECT DATE_FORMAT(activation_date, '%Y-%m') AS m, COUNT(*) AS c
		FROM `{TABLE}`
		GROUP BY m ORDER BY m
		"""
	)
	counts = [int(row[1]) for row in trend]
	if len(counts) >= 6:
		first_half = sum(counts[: len(counts) // 2]) / max(len(counts) // 2, 1)
		second_half = sum(counts[len(counts) // 2:]) / max(len(counts) - len(counts) // 2, 1)
		growing = second_half > first_half * 1.1
		volatile = (max(counts) - min(counts)) / max(sum(counts) / len(counts), 1) > 0.25
		results.append({
			"code": "QC-08",
			"name": "新增量呈上升趋势且存在季节波动",
			"status": "pass" if (growing and volatile) else "warn",
			"detail": f"前半段月均 {first_half:.0f}，后半段月均 {second_half:.0f}，"
			          f"波动幅度 {(max(counts) - min(counts)) / max(sum(counts) / len(counts), 1):.0%}",
			"count": 0,
		})
	else:
		results.append({
			"code": "QC-08", "name": "新增量趋势", "status": "warn",
			"detail": "数据不足 6 个月，跳过趋势检查", "count": 0,
		})

	churn = frappe.db.sql(
		f"""
		SELECT COUNT(*) AS churned,
		       (SELECT COUNT(*) FROM `{TABLE}` WHERE activation_date <= CURDATE()) AS total
		FROM `{TABLE}` WHERE churn_date IS NOT NULL
		"""
	)
	if churn and int(churn[0][1] or 0) > 0:
		ratio = int(churn[0][0]) / int(churn[0][1])
		results.append({
			"code": "QC-10", "name": "累计流失占比处于合理区间",
			"status": "pass" if 0.15 <= ratio <= 0.75 else "warn",
			"detail": f"累计流失 {int(churn[0][0])} / {int(churn[0][1])} = {ratio:.1%}",
			"count": 0,
		})

	return results


def summary(results: list[dict]) -> dict:
	return {
		"total": len(results),
		"passed": sum(1 for r in results if r["status"] == "pass"),
		"warned": sum(1 for r in results if r["status"] == "warn"),
		"failed": sum(1 for r in results if r["status"] == "fail"),
	}
