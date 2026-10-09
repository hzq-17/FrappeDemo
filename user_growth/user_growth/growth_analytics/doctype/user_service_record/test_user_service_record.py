"""用户服务记录：控制器层测试（校验规则、派生字段、状态流转）。"""

from datetime import date, timedelta

import frappe
from frappe.tests.utils import FrappeTestCase


def base_doc(**overrides) -> dict:
	today = date.today()
	payload = {
		"doctype": "User Service Record",
		"user_id": f"TEST-{frappe.generate_hash(length=8)}",
		"user_name": "测试客户",
		"user_type": "企业",
		"segment": "中小",
		"country": "中国",
		"province": "江苏",
		"city": "南京",
		"acquisition_channel": "官网直销",
		"plan": "专业版",
		"billing_cycle": "年付",
		"contract_amount": 3588,
		"seats": 5,
		"activation_date": today - timedelta(days=120),
		"expiry_date": today + timedelta(days=245),
		"health_score": 88,
		"data_source": "手工录入",
	}
	payload.update(overrides)
	# 去掉值为 None 的覆盖项，便于"未填写"场景
	return {key: value for key, value in payload.items() if value is not None}


class TestUserServiceRecord(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_region_is_derived_from_province(self):
		doc = frappe.get_doc(base_doc(province="广东")).insert()
		self.assertEqual(doc.region, "华南")

	def test_mrr_and_tier_are_derived(self):
		doc = frappe.get_doc(base_doc(plan="专业版", billing_cycle="年付",
		                              contract_amount=3588)).insert()
		self.assertEqual(doc.mrr, 299)
		self.assertEqual(doc.plan_tier, "标准版")
		self.assertEqual(doc.is_paid, 1)

	def test_free_plan_has_no_amount(self):
		doc = frappe.get_doc(base_doc(plan="免费试用", billing_cycle="免费",
		                              contract_amount=0, discount_percent=0)).insert()
		self.assertEqual(doc.mrr, 0)
		self.assertEqual(doc.is_paid, 0)
		self.assertEqual(doc.is_new_customer, 1)

	def test_churn_requires_reason(self):
		payload = base_doc()
		payload["churn_date"] = date.today() - timedelta(days=1)
		payload.pop("expiry_date")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(payload).insert()

	def test_churn_before_activation_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				base_doc(
					activation_date=date.today() - timedelta(days=10),
					churn_date=date.today() - timedelta(days=30),
					churn_type="主动流失",
					churn_reason_category="价格因素",
				)
			).insert()

	def test_future_activation_date_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(base_doc(activation_date=date.today() + timedelta(days=1))).insert()

	def test_duplicate_lifecycle_seq_is_rejected(self):
		user_id = f"TEST-{frappe.generate_hash(length=8)}"
		frappe.get_doc(base_doc(user_id=user_id)).insert()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(base_doc(user_id=user_id)).insert()

	def test_overlapping_lifecycle_is_rejected(self):
		user_id = f"TEST-{frappe.generate_hash(length=8)}"
		today = date.today()
		frappe.get_doc(
			base_doc(
				user_id=user_id,
				activation_date=today - timedelta(days=200),
				churn_date=today - timedelta(days=100),
				churn_type="主动流失",
				churn_reason_category="价格因素",
			)
		).insert()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				base_doc(
					user_id=user_id,
					lifecycle_seq=2,
					activation_date=today - timedelta(days=150),
					previous_churn_date=today - timedelta(days=100),
				)
			).insert()

	def test_winback_lifecycle_is_allowed_after_churn(self):
		user_id = f"TEST-{frappe.generate_hash(length=8)}"
		today = date.today()
		frappe.get_doc(
			base_doc(
				user_id=user_id,
				activation_date=today - timedelta(days=400),
				churn_date=today - timedelta(days=200),
				churn_type="主动流失",
				churn_reason_category="价格因素",
			)
		).insert()
		doc = frappe.get_doc(
			base_doc(
				user_id=user_id,
				lifecycle_seq=2,
				activation_date=today - timedelta(days=100),
				previous_churn_date=today - timedelta(days=200),
			)
		).insert()
		self.assertEqual(doc.is_winback, 1)
		self.assertEqual(doc.is_new_customer, 0)
		self.assertEqual(doc.first_activation_date, today - timedelta(days=400))

	def test_status_flows_to_churned(self):
		doc = frappe.get_doc(
			base_doc(
				activation_date=date.today() - timedelta(days=300),
				churn_date=date.today() - timedelta(days=10),
				churn_type="主动流失",
				churn_reason_category="竞品替换",
				competitor="竞品A",
			)
		).insert()
		self.assertEqual(doc.status, "已流失")
		self.assertEqual(doc.lifecycle_days, 290)

	def test_competitor_is_required_for_competitor_reason(self):
		payload = base_doc(
			activation_date=date.today() - timedelta(days=100),
			churn_date=date.today() - timedelta(days=5),
			churn_type="主动流失",
			churn_reason_category="竞品替换",
		)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(payload).insert()

	def test_health_score_drives_risk_level(self):
		doc = frappe.get_doc(base_doc(health_score=55)).insert()
		self.assertEqual(doc.risk_level, "高")
