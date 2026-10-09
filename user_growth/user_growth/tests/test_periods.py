"""时间桶的连续性、对齐与同比映射单测。"""

import unittest
from datetime import date, timedelta

from user_growth.analytics import periods


class TestBuckets(unittest.TestCase):
	def test_buckets_cover_range_without_gap_or_overlap(self):
		start, end = date(2026, 1, 15), date(2026, 4, 10)
		for granularity in periods.GRANULARITIES:
			buckets = periods.build_buckets(start, end, granularity)
			self.assertGreater(len(buckets), 0, granularity)
			self.assertEqual(buckets[0]["start"], start, granularity)
			self.assertEqual(buckets[-1]["end"], end, granularity)
			covered = 0
			for index, bucket in enumerate(buckets):
				covered += (bucket["end"] - bucket["start"]).days + 1
				if index:
					self.assertEqual(
						bucket["start"], buckets[index - 1]["end"] + timedelta(days=1), granularity
					)
			self.assertEqual(covered, (end - start).days + 1, granularity)

	def test_bucket_keys_are_aligned_to_calendar(self):
		buckets = periods.build_buckets(date(2026, 1, 15), date(2026, 3, 2), "月")
		self.assertEqual([b["key"] for b in buckets], ["2026-01", "2026-02", "2026-03"])
		buckets = periods.build_buckets(date(2026, 1, 15), date(2026, 8, 2), "季度")
		self.assertEqual([b["key"] for b in buckets], ["2026-Q1", "2026-Q2", "2026-Q3"])

	def test_week_buckets_start_on_monday(self):
		buckets = periods.build_buckets(date(2026, 1, 1), date(2026, 1, 31), "周")
		for bucket in buckets:
			monday = periods.to_date(bucket["key"])
			self.assertEqual(monday.weekday(), 0)

	def test_bucket_count_guard(self):
		with self.assertRaises(ValueError):
			periods.build_buckets(date(2020, 1, 1), date(2026, 1, 1), "日")


class TestRanges(unittest.TestCase):
	def test_preset_ranges(self):
		ref = date(2026, 10, 9)
		self.assertEqual(periods.resolve_range("近7天", ref=ref), (date(2026, 10, 3), ref))
		self.assertEqual(periods.resolve_range("本月", ref=ref), (date(2026, 10, 1), ref))
		self.assertEqual(periods.resolve_range("上月", ref=ref), (date(2026, 9, 1), date(2026, 9, 30)))
		self.assertEqual(periods.resolve_range("本季度", ref=ref), (date(2026, 10, 1), ref))
		self.assertEqual(periods.resolve_range("今年", ref=ref), (date(2026, 1, 1), ref))
		self.assertEqual(
			periods.resolve_range("近12个月", ref=ref), (date(2025, 11, 1), ref)
		)

	def test_custom_range_swaps_when_reversed(self):
		self.assertEqual(
			periods.resolve_range("自定义", "2026-03-01", "2026-01-01"),
			(date(2026, 1, 1), date(2026, 3, 1)),
		)

	def test_previous_range_length_matches(self):
		start, end = date(2026, 9, 1), date(2026, 9, 30)
		prev_start, prev_end = periods.previous_range(start, end)
		self.assertEqual((prev_end - prev_start).days, (end - start).days)
		self.assertEqual(prev_end, start - timedelta(days=1))

	def test_shift_year_back_key(self):
		self.assertEqual(periods.shift_year_back_key("2026-10", "月"), "2025-10")
		self.assertEqual(periods.shift_year_back_key("2026-Q4", "季度"), "2025-Q4")
		self.assertEqual(periods.shift_year_back_key("2026", "年"), "2025")
		self.assertEqual(periods.shift_year_back_key("2026-10-09", "日"), "2025-10-09")
		self.assertEqual(periods.shift_year_back_key("2024-02-29", "日"), "2023-02-28")

	def test_extended_start_is_before_range(self):
		for granularity in periods.GRANULARITIES:
			value = periods.extended_start(date(2026, 10, 9), granularity)
			self.assertLess(value, date(2026, 10, 9), granularity)

