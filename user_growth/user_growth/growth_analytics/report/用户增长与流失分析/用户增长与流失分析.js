// 用户增长与流失分析：筛选器 + 条件格式 + 图表 + 口径说明
// 路径：report/用户增长与流失分析/用户增长与流失分析.js（目录名必须与报表名一致）

frappe.query_reports["用户增长与流失分析"] = {
	filters: [
		{
			fieldname: "preset",
			label: __("快捷区间"),
			fieldtype: "Select",
			options: ["近7天", "近30天", "近90天", "本月", "上月", "本季度", "今年", "近12个月", "自定义"],
			default: "近12个月",
			on_change: function (report) {
				const value = report.get_filter_value("preset");
				if (!value || value === "自定义") {
					return;
				}
				const today = frappe.datetime.get_today();
				const span = {
					近7天: ["add_days", 6],
					近30天: ["add_days", 29],
					近90天: ["add_days", 89],
					近12个月: ["add_months", 11],
				}[value];
				if (span) {
					report.set_filter_value("to_date", today);
					report.set_filter_value("from_date", frappe.datetime[span[0]](today, -span[1]));
				}
				report.refresh();
			},
		},
		{
			fieldname: "from_date",
			label: __("起始日期"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -11),
		},
		{
			fieldname: "to_date",
			label: __("结束日期"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "granularity",
			label: __("粒度"),
			fieldtype: "Select",
			options: ["日", "周", "月", "季度", "年"],
			default: "月",
			reqd: 1,
		},
		{
			fieldname: "group_by",
			label: __("分组"),
			fieldtype: "Select",
			options: ["", "region", "province", "acquisition_channel", "plan",
				"user_type", "segment", "billing_cycle", "churn_reason_category"],
			default: "",
		},
		{
			fieldname: "region",
			label: __("大区"),
			fieldtype: "MultiSelectList",
			get_data: () => list_options(["华东", "华北", "华南", "华中", "西南", "西北", "东北", "海外"]),
		},
		{
			fieldname: "acquisition_channel",
			label: __("渠道"),
			fieldtype: "MultiSelectList",
			get_data: () => list_options([
				"官网直销", "内容营销", "搜索广告", "信息流", "合作伙伴",
				"代理商", "线下活动", "老客推荐", "自然流量",
			]),
		},
		{
			fieldname: "plan",
			label: __("套餐"),
			fieldtype: "MultiSelectList",
			get_data: () => list_options([
				"免费试用", "基础版", "专业版", "企业版", "旗舰版", "定制版",
			]),
		},
		// 次要筛选：默认折叠，避免筛选栏挤成两三行
		{
			fieldname: "user_type",
			label: __("用户类型"),
			fieldtype: "MultiSelectList",
			get_data: () => list_options(["个人", "团队", "企业"]),
		},
		{
			fieldname: "is_paid",
			label: __("付费情况"),
			fieldtype: "Select",
			options: ["", "付费", "免费"],
			default: "",
		},
		{
			fieldname: "churn_rate_denominator",
			label: __("流失率口径"),
			fieldtype: "Select",
			options: ["期初在服", "平均在服"],
			default: "期初在服",
			reqd: 1,
		},
	],

	onload(report) {
		setup_advanced_filters(report);

		report.page.add_inner_button(__("指标口径说明"), () => {
			frappe.call({
				method: "user_growth.api.common.get_caliber_note",
				callback: (r) => {
					const note = r.message || {};
					const rows = Object.keys(note)
						.map((key) => `<li>${frappe.utils.escape_html(note[key])}</li>`)
						.join("");
					frappe.msgprint({
						title: __("指标口径说明"),
						indicator: "blue",
						message: `<ul style="padding-left:18px">${rows}</ul>`,
					});
				},
			});
		});
		report.page.add_inner_button(__("打开增长大屏"), () => {
			frappe.set_route("growth-dashboard");
		});
	},

	// 条件格式：负数标红、正数标绿；比率留空显示为短横线；合计行加粗
	formatter(value, row, column, data, default_formatter) {
		const signed_columns = ["net", "mrr_net", "mom", "yoy"];
		const optional_columns = ["mom", "yoy", "arpu_new"];
		let formatted = default_formatter(value, column, data);

		if (optional_columns.includes(column.fieldname) && (value === null || value === undefined)) {
			return '<span class="text-muted">—</span>';
		}
		if (signed_columns.includes(column.fieldname) && typeof value === "number" && value !== 0) {
			const good = value > 0;
			const color = good ? "#059669" : "#dc2626";
			const sign = column.fieldname === "net" || column.fieldname === "mrr_net"
				? (good ? "+" : "")
				: "";
			formatted = `<span style="color:${color}">${sign}${formatted}</span>`;
		}
		if (data && data.is_total) {
			formatted = `<b>${formatted}</b>`;
		}
		return formatted;
	},

	// 报表页工具栏的图表：柱=新增/流失，线=期末在服
	get_chart_data(columns, data) {
		const rows = (data || []).filter((row) => row && !row.is_total && row.label);
		if (!rows.length) {
			return null;
		}
		return {
			data: {
				labels: rows.map((row) => row.label),
				datasets: [
					{ name: __("新增用户"), values: rows.map((row) => row.new || 0), chartType: "bar" },
					{ name: __("流失用户"), values: rows.map((row) => row.churned || 0), chartType: "bar" },
					{ name: __("期末在服"), values: rows.map((row) => row.end || 0), chartType: "line" },
				],
			},
			type: "axis-mixed",
			colors: ["#0891B2", "#F97316", "#3D5AFE"],
			fieldtype: "Float",
		};
	},

	// 表头下面那行是 frappe-datatable 的「行内筛选行」（每个列头下挂一个输入框），
	// Frappe 报表默认开启；在 14 列、行数不多的分析报表里它只是噪音，
	// 而报表顶部已有完整筛选栏，因此这里显式关掉（想启用就把 inlineFilters 改回 true）。
	get_datatable_options(options) {
		return Object.assign(options, {
			inlineFilters: false,
			cellHeight: 34,
		});
	},
};

// 次要筛选默认收起，点「更多筛选」展开：让默认筛选栏只有一行
function setup_advanced_filters(report) {
	const advanced = ["user_type", "is_paid", "churn_rate_denominator"];
	let expanded = false;

	function toggle(show) {
		advanced.forEach((fieldname) => {
			const field = report.page.fields_dict && report.page.fields_dict[fieldname];
			if (field && field.$wrapper) {
				field.$wrapper.toggle(show);
			}
		});
	}

	toggle(false);
	report.page.add_inner_button(__("更多筛选"), () => {
		expanded = !expanded;
		toggle(expanded);
	});
}

function list_options(values) {
	return values.map((value) => ({ value: value, description: value }));
}
