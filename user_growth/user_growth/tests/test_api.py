"""大屏接口层测试：缓存命名空间、返回结构。

这里的第一个用例是对一个真实事故的回归：
整包接口与趋势接口曾经共用同一个缓存键——同一次筛选下先取整包（被缓存），
再取趋势时趋势接口命中了整包载荷，前端拿到没有 labels 的 dashboard 数据，
于是"切回日粒度后趋势图没有数据"（只在缓存有效期内、顺序恰好时复现）。
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from user_growth.api import growth_screen
from user_growth.analytics import metrics


class TestScreenApiCache(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.filters = {"preset": "近30天", "granularity": metrics.SCREEN_GRANULARITY}

	def test_trend_payload_is_not_masked_by_dashboard_cache(self):
		dashboard = growth_screen.get_dashboard_data(filters=self.filters)
		trend = growth_screen.get_trend_series(filters=self.filters)

		self.assertEqual(dashboard["code"], 0)
		self.assertEqual(trend["code"], 0)
		self.assertIn("trend", dashboard["data"])

		data = trend["data"]
		self.assertIn("labels", data, "趋势接口返回结构不对：很可能命中了别的接口的缓存")
		self.assertNotIn("active_users", data, "趋势接口返回了整包 dashboard 载荷（缓存串用）")
		self.assertTrue(data["labels"], "趋势接口返回了空数据")
		self.assertEqual(len(data["labels"]), len(data["new"]))

	def test_kpi_payload_is_not_masked_by_dashboard_cache(self):
		growth_screen.get_dashboard_data(filters=self.filters)
		kpi = growth_screen.get_kpi_summary(filters=self.filters)

		data = kpi["data"]
		self.assertIn("active_users", data, "KPI 接口返回结构不对：很可能命中了别的接口的缓存")
		self.assertIn("new_users", data)
		self.assertIn("churn_rate", data)

	def test_different_granularity_yields_different_trend(self):
		daily = growth_screen.get_trend_series(
			filters={"preset": "近30天", "granularity": "日"}
		)["data"]
		weekly = growth_screen.get_trend_series(
			filters={"preset": "近30天", "granularity": "周"}
		)["data"]
		self.assertGreater(len(daily["labels"]), len(weekly["labels"]))
		self.assertEqual(sum(daily["new"]), sum(weekly["new"]), "换粒度不应改变总量")

	def test_guest_is_rejected(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			growth_screen.get_dashboard_data(filters=self.filters)


class TestReportTableOptions(FrappeTestCase):
	"""报表表格的呈现配置（frppe-datatable 默认会渲染一些多余的元素）。"""

	def test_inline_filter_row_is_disabled(self):
		"""表头下方的「行内筛选行」必须关掉：报表顶部已有筛选栏，多一行只是噪音。"""
		import os

		from frappe.modules import get_module_path

		path = os.path.join(
			get_module_path("Growth Analytics"),
			"report", "用户增长与流失分析", "用户增长与流失分析.js",
		)
		content = open(path, encoding="utf-8").read()
		self.assertIn("inlineFilters: false", content)
		self.assertIn("get_datatable_options", content)
