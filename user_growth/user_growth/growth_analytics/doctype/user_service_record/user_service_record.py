"""用户服务记录：控制器（校验 + 派生 + 状态机）。

设计原则：规则与派生逻辑都在 user_growth.analytics.rules 里（纯函数、可单测），
控制器只负责"取当前上下文 + 抛错 + 提示"，因此生成器写入的数据与手工录入的数据
遵守完全相同的口径。
"""

from datetime import date

import frappe
from frappe import _
from frappe.model.document import Document

from user_growth.analytics import constants as C
from user_growth.analytics import rules

MAX_DATE = date(9999, 12, 31)


class UserServiceRecord(Document):
	# ------------------------------------------------------------------
	# 生命周期回调
	# ------------------------------------------------------------------
	def before_insert(self):
		self.assign_defaults()

	def validate(self):
		self.assign_defaults()
		self.apply_derived_fields()
		self.check_pure_rules()
		self.check_uniqueness()
		self.check_lifecycle_overlap()
		self.show_warnings()

	# ------------------------------------------------------------------
	# 默认值
	# ------------------------------------------------------------------
	def assign_defaults(self):
		if not self.lifecycle_seq:
			self.lifecycle_seq = 1
		# 大区始终由省份推导（字段本身是只读的，Frappe 会给 Select 填默认首选项）
		if self.province:
			self.region = C.region_of(self.province)
		# 首次开通日期：首段生命周期取本次开通日期；唤回段继承同一客户最早的那一次开通
		if int(self.lifecycle_seq or 1) == 1:
			self.first_activation_date = self.activation_date
		elif not self.first_activation_date:
			self.first_activation_date = self._earliest_activation() or self.activation_date
		if not self.currency:
			self.currency = "CNY"
		if self.plan == C.FREE_PLAN:
			self.billing_cycle = "免费"
			self.contract_amount = 0
			self.discount_percent = 0
		elif self.billing_cycle == "免费":
			# 付费套餐不允许停留在"免费"计费周期
			self.billing_cycle = "月付"

	def _earliest_activation(self):
		"""同一客户更早生命周期里最早的开通日期。"""
		if not self.user_id:
			return None
		rows = frappe.db.sql(
			"""
			SELECT MIN(activation_date) AS first_date
			FROM `tabUser Service Record`
			WHERE user_id = %(user_id)s AND lifecycle_seq < %(seq)s
			""",
			{"user_id": self.user_id, "seq": int(self.lifecycle_seq or 1)},
			as_dict=True,
		)
		return rows[0].first_date if rows and rows[0].first_date else None

	# ------------------------------------------------------------------
	# 派生字段
	# ------------------------------------------------------------------
	def apply_derived_fields(self):
		values = rules.derive(self.as_dict())
		for fieldname, value in values.items():
			if self.meta.has_field(fieldname):
				self.set(fieldname, value)

	# ------------------------------------------------------------------
	# 校验
	# ------------------------------------------------------------------
	def check_pure_rules(self):
		issues = rules.error_messages(rules.validate_rules(self.as_dict()))
		if not issues:
			return
		lines = []
		for issue in issues:
			label = issue["fieldname"]
			try:
				label = self.meta.get_label(issue["fieldname"])
			except Exception:
				pass
			lines.append(f"{label}：{issue['message']}")
		frappe.throw(
			"<br>".join(f"· {line}" for line in lines),
			frappe.ValidationError,
			title=_("数据校验未通过"),
		)

	def check_uniqueness(self):
		"""RB-08：同一用户 + 生命周期序号唯一。"""
		filters = {
			"user_id": self.user_id,
			"lifecycle_seq": int(self.lifecycle_seq or 1),
		}
		if self.name:
			filters["name"] = ["!=", self.name]
		if frappe.db.exists(self.doctype, filters):
			frappe.throw(
				_("用户 {0} 已存在第 {1} 段生命周期记录，请检查是否重复录入").format(
					self.user_id, self.lifecycle_seq
				),
				frappe.ValidationError,
			)

	def check_lifecycle_overlap(self):
		"""RB-11：同一用户的多段生命周期时间段不得重叠。"""
		if not (self.user_id and self.activation_date):
			return
		my_end = rules.to_date(self.churn_date) or MAX_DATE
		others = frappe.db.sql(
			"""
			SELECT name, activation_date, churn_date
			FROM `tabUser Service Record`
			WHERE user_id = %(user_id)s
			  AND name != %(name)s
			  AND activation_date < %(my_end)s
			  AND (churn_date IS NULL OR churn_date > %(my_start)s)
			LIMIT 3
			""",
			{"user_id": self.user_id, "name": self.name or "",
			 "my_end": my_end, "my_start": self.activation_date},
			as_dict=True,
		)
		if others:
			detail = "；".join(
				_("{0}（{1} ~ {2}）").format(
					row.name, row.activation_date, row.churn_date or _("在服中")
				)
				for row in others
			)
			frappe.throw(
				_("该用户的服务时间与已有记录重叠：{0}").format(detail),
				frappe.ValidationError,
			)

	def show_warnings(self):
		issues = rules.warning_messages(rules.validate_rules(self.as_dict()))
		if int(self.lifecycle_seq or 1) > 1 and not self._has_previous_lifecycle():
			issues.append({
				"fieldname": "lifecycle_seq",
				"message": _("未找到该用户更早的已流失记录，请确认唤回数据是否完整"),
			})
		for issue in issues:
			frappe.msgprint(issue["message"], indicator="orange", alert=True)

	def _has_previous_lifecycle(self) -> bool:
		return bool(
			frappe.db.exists(
				self.doctype,
				{
					"user_id": self.user_id,
					"lifecycle_seq": ["<", int(self.lifecycle_seq or 1)],
					"churn_date": ["is", "set"],
				},
			)
		)
