"""演示数据的执行入口：幂等、可重置、带自检报告。

用法：
    bench --site <site> execute user_growth.seed.runner.run_cli
    bench --site <site> execute user_growth.seed.runner.run_cli --kwargs "{'months': 24, 'reset': 1}"
"""

import json
from datetime import date

import frappe
from frappe.utils import now

from user_growth.analytics import rules
from user_growth.seed import generator, quality_check

DOCTYPE = "User Service Record"
TABLE = "tabUser Service Record"
BATCH_SIZE = 500

# Frappe 建表时数值型字段是 NOT NULL，批量写入前必须把 None 归零
NUMERIC_TYPES = ("Int", "Long Int", "Float", "Currency", "Percent", "Check", "Duration")

# 批量写入的字段（与 DocType 字段一一对应）
FIELDS = [
	"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
	"naming_series",
	"user_id", "user_name", "user_type", "segment", "industry",
	"country", "province", "city", "region",
	"acquisition_channel", "source_detail", "campaign", "partner_name", "is_paid_acquisition",
	"plan", "plan_tier", "billing_cycle", "seats", "currency", "list_price",
	"discount_percent", "contract_amount", "mrr", "is_paid", "auto_renew",
	"lifecycle_seq", "first_activation_date", "activation_date", "service_start_date",
	"last_renewal_date", "expiry_date", "churn_date", "is_paused",
	"lifecycle_days", "days_to_expiry",
	"status", "is_new_customer", "is_winback", "previous_churn_date",
	"churn_type", "churn_reason_category", "churn_reason", "competitor",
	"is_recoverable", "health_score", "risk_level", "winback_owner", "winback_note",
	"ticket_ref", "account_owner", "data_source", "source_batch", "remark", "attachment",
]


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------
def _existing_keys() -> set:
	rows = frappe.db.sql(
		f"SELECT user_id, lifecycle_seq FROM `{TABLE}`", as_dict=True
	)
	return {(str(r.user_id), int(r.lifecycle_seq or 1)) for r in rows}


def _numeric_fieldnames() -> set:
	"""从元数据里取出所有数值型字段，用于把 None 归零（避免 NOT NULL 报错）。"""
	try:
		meta = frappe.get_meta(DOCTYPE)
	except Exception:
		return set()
	return {field.fieldname for field in meta.fields if field.fieldtype in NUMERIC_TYPES}


def _reset(batch: str | None = None) -> int:
	"""只清理"模拟数据"，避免误删真实业务数据。"""
	if batch:
		frappe.db.sql(
			f"DELETE FROM `{TABLE}` WHERE data_source = %s AND source_batch = %s",
			("模拟数据", batch),
		)
	else:
		frappe.db.sql(f"DELETE FROM `{TABLE}` WHERE data_source = %s", ("模拟数据",))
	frappe.db.commit()
	frappe.clear_cache(doctype=DOCTYPE)
	return 1


def _insert(records: list[dict]) -> int:
	if not records:
		return 0
	columns = ", ".join(f"`{field}`" for field in FIELDS)
	inserted = 0
	for start in range(0, len(records), BATCH_SIZE):
		chunk = records[start:start + BATCH_SIZE]
		placeholders = ", ".join(
			"(" + ", ".join(["%s"] * len(FIELDS)) + ")" for _ in chunk
		)
		values = []
		for record in chunk:
			for field in FIELDS:
				values.append(record.get(field))
		frappe.db.sql(f"INSERT INTO `{TABLE}` ({columns}) VALUES {placeholders}", values)
		frappe.db.commit()
		inserted += len(chunk)
	return inserted


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(months: int = 24, seed: int = 20260101, ref: str | date | None = None,
        reset: bool = False, batch: str | None = None, verbose: bool = True) -> dict:
	"""生成并写入演示数据（幂等：已存在的 user_id + 生命周期序号 会被跳过）。"""
	months = int(months or 24)
	seed = int(seed or 20260101)
	ref_date = rules.to_date(ref) or date.today()
	batch = batch or f"seed-{seed}-{months}m"

	if isinstance(reset, str):
		reset = reset.lower() in ("1", "true", "yes")

	if reset:
		deleted = _reset()
		if verbose:
			frappe.msgprint("已清理历史的模拟数据", indicator="orange", alert=True)

	records = generator.generate(months=months, seed=seed, ref=ref_date)
	existing = _existing_keys()
	numeric_fields = _numeric_fieldnames()

	prepared = []
	stamp = now()
	for record in records:
		key = (str(record["user_id"]), int(record["lifecycle_seq"] or 1))
		if key in existing:
			continue
		record.setdefault("churn_type", None)
		for fieldname in numeric_fields:
			if record.get(fieldname) is None:
				record[fieldname] = 0
		row = dict(record)
		row.update({
			"naming_series": "USR-.YYYY.-",
			"owner": "Administrator",
			"creation": stamp,
			"modified": stamp,
			"modified_by": "Administrator",
			"docstatus": 0,
			"idx": 0,
			"source_batch": batch,
			"ticket_ref": None,
			"winback_owner": None,
			"remark": None,
			"attachment": None,
		})
		prepared.append(row)

	inserted = _insert(prepared)
	frappe.clear_cache(doctype=DOCTYPE)

	checks = quality_check.run()
	report = {
		"generated": len(records),
		"inserted": inserted,
		"skipped": len(records) - inserted,
		"batch": batch,
		"months": months,
		"seed": seed,
		"quality": quality_check.summary(checks),
	}

	if verbose:
		_print_report(report, checks)
	return {"report": report, "checks": checks}


def _print_report(report: dict, checks: list[dict]) -> None:
	print("=" * 72)
	print("user_growth 演示数据生成完成")
	print(f"  生成 {report['generated']} 条 / 写入 {report['inserted']} 条 / 跳过 {report['skipped']} 条")
	print(f"  时间跨度 {report['months']} 个月，随机种子 {report['seed']}，批次 {report['batch']}")
	print(f"  质量自检：{report['quality']}")
	print("-" * 72)
	for check in checks:
		flag = {"pass": "OK  ", "warn": "WARN", "fail": "FAIL"}[check["status"]]
		print(f"  [{flag}] {check['code']} {check['name']}：{check['detail']}")
	print("=" * 72)


def run_cli(**kwargs) -> dict:
	"""命令行入口：bench execute user_growth.seed.runner.run_cli --kwargs "{...}" """
	allowed = {"months", "seed", "ref", "reset", "batch", "verbose"}
	params = {key: value for key, value in kwargs.items() if key in allowed}
	result = run(**params)
	return result["report"]


def after_install():
	"""安装应用后自动准备演示数据；失败不影响安装。"""
	if frappe.conf.get("user_growth_skip_demo_data"):
		return
	try:
		run(verbose=False)
	except Exception:
		frappe.log_error(
			title="user_growth: 安装后生成演示数据失败",
			message=frappe.get_traceback(),
		)


def dump_preview_snapshot(path: str = "/workspace/tools/preview/dashboard.json",
                          preset: str = "近30天") -> dict:
	"""导出大屏数据快照，供离线预览页（tools/preview）做视觉验证。"""
	from user_growth.api import growth_screen
	from user_growth.analytics import metrics

	filters = metrics.normalize_filters(
		{"preset": preset}, default_granularity=metrics.SCREEN_GRANULARITY
	)
	payload = growth_screen.build_dashboard_payload(filters, limit=8)
	envelope = growth_screen._envelope(payload, filters, False)
	with open(path, "w", encoding="utf-8") as handle:
		json.dump(envelope, handle, ensure_ascii=False, default=str, indent=2)
	return {"path": path, "kpi": payload["kpi"]}
