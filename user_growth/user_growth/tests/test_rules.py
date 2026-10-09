"""派生规则与校验规则的单测（纯逻辑，不依赖数据库）。"""

import unittest
from datetime import date, timedelta

from user_growth.analytics import rules


class TestDeriveRules(unittest.TestCase):
	def test_mrr_divides_by_billing_months(self):
		self.assertEqual(rules.compute_mrr("专业版", "年付", 3588), 299.0)
		self.assertEqual(rules.compute_mrr("企业版", "月付", 899), 899.0)
		self.assertEqual(rules.compute_mrr("专业版", "季付", 897), 299.0)
		self.assertEqual(rules.compute_mrr("免费试用", "免费", 1000), 0.0)

	def test_plan_tier_and_paid_flag(self):
		self.assertEqual(rules.plan_tier("免费试用"), "免费版")
		self.assertEqual(rules.plan_tier("旗舰版"), "高端版")
		self.assertFalse(rules.is_paid("免费试用"))
		self.assertTrue(rules.is_paid("基础版"))

	def test_lifecycle_days(self):
		today = date(2026, 10, 9)
		self.assertEqual(rules.compute_lifecycle_days(date(2026, 1, 9), None, today), 273)
		self.assertEqual(rules.compute_lifecycle_days(date(2026, 1, 9), date(2026, 3, 10), today), 60)
		self.assertEqual(rules.compute_lifecycle_days(None, None, today), None)

	def test_status_machine_priority(self):
		today = date(2026, 10, 9)
		self.assertEqual(
			rules.compute_status({"activation_date": "2026-01-01", "churn_date": "2026-06-01"}, today),
			"已流失",
		)
		self.assertEqual(
			rules.compute_status({"activation_date": "2026-10-01", "service_start_date": "2026-11-01"}, today),
			"待生效",
		)
		self.assertEqual(
			rules.compute_status({"activation_date": "2026-01-01", "is_paused": 1}, today),
			"已暂停",
		)
		self.assertEqual(
			rules.compute_status({"activation_date": "2025-01-01", "expiry_date": "2026-01-01"}, today),
			"已到期",
		)
		self.assertEqual(rules.compute_status({"activation_date": "2026-09-01"}, today), "服务中")

	def test_risk_level_thresholds(self):
		self.assertEqual(rules.compute_risk_level(90), "低")
		self.assertEqual(rules.compute_risk_level(80), "低")
		self.assertEqual(rules.compute_risk_level(70), "中")
		self.assertEqual(rules.compute_risk_level(59.9), "高")

	def test_derive_sets_winback_flags(self):
		row = rules.derive({
			"plan": "专业版",
			"billing_cycle": "年付",
			"contract_amount": 3588,
			"lifecycle_seq": 2,
			"activation_date": "2026-01-01",
			"province": "广东",
			"health_score": 75,
		}, date(2026, 10, 9))
		self.assertEqual(row["is_winback"], 1)
		self.assertEqual(row["is_new_customer"], 0)
		self.assertEqual(row["region"], "华南")
		self.assertEqual(row["risk_level"], "中")
		self.assertEqual(row["status"], "服务中")


class TestValidationRules(unittest.TestCase):
	def base(self, **overrides):
		payload = {
			"plan": "专业版",
			"billing_cycle": "年付",
			"contract_amount": 3588,
			"activation_date": "2026-01-01",
			"lifecycle_seq": 1,
			"health_score": 80,
		}
		payload.update(overrides)
		return payload

	def codes(self, payload):
		return [issue["fieldname"] for issue in rules.error_messages(
			rules.validate_rules(payload, date(2026, 10, 9))
		)]

	def test_future_activation_is_rejected(self):
		self.assertIn("activation_date", self.codes(self.base(activation_date="2026-12-01")))

	def test_churn_before_activation_is_rejected(self):
		self.assertIn("churn_date", self.codes(self.base(
			churn_date="2025-12-01", churn_type="主动流失", churn_reason_category="价格因素",
		)))

	def test_churn_requires_type_and_reason(self):
		codes = self.codes(self.base(churn_date="2026-05-01"))
		self.assertIn("churn_type", codes)
		self.assertIn("churn_reason_category", codes)

	def test_competitor_required_for_competitor_reason(self):
		codes = self.codes(self.base(
			churn_date="2026-05-01", churn_type="主动流失", churn_reason_category="竞品替换",
		))
		self.assertIn("competitor", codes)

	def test_free_plan_rejects_amount(self):
		codes = self.codes(self.base(
			plan="免费试用", billing_cycle="免费", contract_amount=100,
		))
		self.assertIn("contract_amount", codes)

	def test_paid_plan_requires_billing_cycle(self):
		codes = self.codes(self.base(billing_cycle=None))
		self.assertIn("billing_cycle", codes)

	def test_ranges_are_validated(self):
		codes = self.codes(self.base(discount_percent=120, health_score=180))
		self.assertIn("discount_percent", codes)
		self.assertIn("health_score", codes)

	def test_first_activation_must_equal_activation_for_first_lifecycle(self):
		codes = self.codes(self.base(first_activation_date="2025-01-01"))
		self.assertIn("first_activation_date", codes)

	def test_missing_health_score_is_only_a_warning(self):
		payload = self.base(health_score=None)
		payload.pop("health_score")
		warnings = rules.warning_messages(rules.validate_rules(payload, date(2026, 10, 9)))
		self.assertTrue(any(item["fieldname"] == "health_score" for item in warnings))
		self.assertEqual(self.codes(payload), [])

	def test_valid_payload_has_no_errors(self):
		self.assertEqual(self.codes(self.base()), [])


class TestToDate(unittest.TestCase):
	def test_parses_common_formats(self):
		self.assertEqual(rules.to_date("2026-10-09"), date(2026, 10, 9))
		self.assertEqual(rules.to_date("2026-10-09 13:22:01"), date(2026, 10, 9))
		self.assertEqual(rules.to_date(date(2026, 10, 9)), date(2026, 10, 9))
		self.assertIsNone(rules.to_date(""))
		self.assertIsNone(rules.to_date(None))

