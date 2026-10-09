"""指标计算的不变量测试。

不依赖具体数据量：即使站点里没有数据，这些恒等式也必须成立。
"""

from datetime import date, timedelta

from frappe.tests.utils import FrappeTestCase

from user_growth.analytics import constants as C
from user_growth.analytics import metrics, periods


class TestMetricsInvariants(FrappeTestCase):
	def filters(self, **overrides):
		payload = {"preset": "近12个月", "granularity": "月"}
		payload.update(overrides)
		return metrics.normalize_filters(payload)

	def test_series_stock_identity_holds_for_every_bucket(self):
		series = metrics.compute_series(self.filters())
		rows = series["rows"]
		self.assertGreater(len(rows), 0)
		for row in rows:
			self.assertEqual(
				row["end"], row["begin"] + row["new"] - row["churned"],
				f"时间桶 {row['key']} 的存量恒等式不成立",
			)
		# 可见区间内相邻时间桶首尾相接；第一个可见桶的期初 = 区间开始前一日
		visible = [row for row in rows if row["in_range"]]
		for previous, current in zip(visible, visible[1:]):
			self.assertEqual(current["begin"], previous["end"])
		self.assertEqual(visible[0]["begin"], metrics.compute_kpi(self.filters())["active_users_begin"])

	def test_net_growth_equals_active_change_over_period(self):
		filters = self.filters()
		kpi = metrics.compute_kpi(filters)
		series = metrics.compute_series(filters)
		visible = [row for row in series["rows"] if row["in_range"]]
		net_from_series = sum(row["net"] for row in visible)
		self.assertEqual(net_from_series, kpi["net_growth"])
		self.assertEqual(kpi["churned_users"], sum(row["churned"] for row in visible))
		self.assertEqual(kpi["new_users"], sum(row["new"] for row in visible))

	def test_distribution_sums_to_active_users(self):
		filters = self.filters()
		kpi = metrics.compute_kpi(filters)
		regions = metrics.compute_distribution(filters, "region")
		provinces = metrics.compute_distribution(filters, "province")
		channels = metrics.compute_distribution(filters, "acquisition_channel")
		for rows in (regions, provinces, channels):
			self.assertEqual(sum(row["active"] for row in rows), kpi["active_users"])

	def test_province_to_region_mapping_is_total(self):
		filters = self.filters()
		provinces = metrics.compute_distribution(filters, "province")
		regions = {row["key"]: row["active"] for row in metrics.compute_distribution(filters, "region")}
		expected = {}
		for row in provinces:
			region = C.region_of(row["key"])
			expected[region] = expected.get(region, 0) + row["active"]
		self.assertEqual(expected, regions)

	def test_global_granularity_keeps_totals(self):
		monthly = self.filters(granularity="月")
		yearly = self.filters(granularity="年")
		month_rows = [r for r in metrics.compute_series(monthly)["rows"] if r["in_range"]]
		year_rows = [r for r in metrics.compute_series(yearly)["rows"] if r["in_range"]]
		self.assertEqual(sum(r["new"] for r in month_rows), sum(r["new"] for r in year_rows))
		self.assertEqual(sum(r["churned"] for r in month_rows), sum(r["churned"] for r in year_rows))

	def test_filters_narrow_results(self):
		wide = metrics.compute_kpi(self.filters())
		narrow = metrics.compute_kpi(self.filters(region=["华东"]))
		self.assertLessEqual(narrow["active_users"], wide["active_users"])

	def test_invalid_filters_raise(self):
		import frappe

		with self.assertRaises(frappe.ValidationError):
			metrics.normalize_filters({"granularity": "半小时"})
		with self.assertRaises(frappe.ValidationError):
			metrics.normalize_filters({"group_by": "unknown_dimension"})
		with self.assertRaises(frappe.ValidationError):
			metrics.normalize_filters({"churn_rate_denominator": "随便"})

	def test_mask_name(self):
		self.assertEqual(metrics.mask_name("星辰科技"), "星辰**")
		self.assertEqual(metrics.mask_name("甲"), "甲*")
		self.assertEqual(metrics.mask_name(""), "")

	def test_kpi_payload_is_json_serializable(self):
		"""接口返回前会被 json.dumps 序列化，任何 date/datetime 泄漏都会导致 500。"""
		import json

		json.dumps(metrics.compute_kpi(self.filters()))
		json.dumps(metrics.compute_distribution(self.filters(), "region"))
		json.dumps(metrics.compute_churn_reasons(self.filters()))
		json.dumps(metrics.compute_top_accounts(self.filters(), 5))
		json.dumps(metrics.compute_event_feed(self.filters(), 5))
		json.dumps(metrics.compute_grouped_series(self.filters(), "region"))
		# 缓存键本身也要能序列化（区间起止是 date 对象，最容易踩坑）
		self.assertTrue(metrics.cache_key("prefix", self.filters()))

	def test_report_payload_is_json_serializable(self):
		import importlib
		import json

		# 报表目录名必须与报表名一致（Frappe 用报表名拼模块路径），这里用 importlib 避免
		# 在源码里写中文导入路径
		module = importlib.import_module(
			"user_growth.growth_analytics.report.用户增长与流失分析.用户增长与流失分析"
		)
		run_report = module.execute

		# 返回顺序：(columns, data, message, chart, report_summary, skip_total_row)
		columns, data, message, chart, summary, skip_total_row = run_report(
			{"preset": "近90天", "granularity": "月"}
		)
		self.assertTrue(columns)
		self.assertTrue(data)
		json.dumps({"columns": columns, "data": data, "message": message, "chart": chart})
		# 报表自带合计行，并关闭框架的盲求和合计行
		self.assertEqual(data[-1].get("label"), "合计")
		self.assertTrue(data[-1].get("is_total"))
		self.assertTrue(skip_total_row, "必须关闭框架合计行，否则会出现假合计")
		# 合计行必须自洽：期初 + 新增 − 流失 = 期末
		total = data[-1]
		self.assertEqual(total["end"], total["begin"] + total["new"] - total["churned"])
		# 列定义必须"按语义给类型"，否则表格会很难看
		types = {column["fieldname"]: (column["fieldtype"], column.get("precision"))
		         for column in columns}
		self.assertEqual(types["new"], ("Float", 0))
		self.assertEqual(types["churn_rate"], ("Percent", 2))
		self.assertEqual(types["mrr_net"][0], "Currency")
		self.assertLessEqual(sum(column.get("width", 0) for column in columns), 1400)

		grouped_columns, grouped_data = run_report(
			{"preset": "近90天", "granularity": "月", "group_by": "region"}
		)[:2]
		self.assertTrue(grouped_columns)
		self.assertTrue(grouped_data)
		json.dumps({"columns": grouped_columns, "data": grouped_data})

	def test_cache_key_is_stable_and_sensitive(self):
		first = metrics.cache_key("prefix", {"preset": "近30天", "granularity": "日"})
		second = metrics.cache_key("prefix", {"granularity": "日", "preset": "近30天"})
		other = metrics.cache_key("prefix", {"preset": "近7天", "granularity": "日"})
		self.assertEqual(first, second)
		self.assertNotEqual(first, other)


class TestTopAccountsAndFeed(FrappeTestCase):
	def test_top_accounts_respect_limit_and_mask(self):
		filters = metrics.normalize_filters({"preset": "近90天"}, default_granularity="日")
		rows = metrics.compute_top_accounts(filters, 5)
		self.assertLessEqual(len(rows), 5)
		for row in rows:
			self.assertIn("*", row["user_name"] or "*")
			self.assertTrue(row["risk_level"] in ("低", "中", "高"))

	def test_event_feed_is_sorted_desc(self):
		filters = metrics.normalize_filters({"preset": "近90天"}, default_granularity="日")
		rows = metrics.compute_event_feed(filters, 6)
		dates = [row["date"] for row in rows]
		self.assertEqual(dates, sorted(dates, reverse=True))
		for row in rows:
			self.assertIn(row["kind"], ("开通", "流失"))
