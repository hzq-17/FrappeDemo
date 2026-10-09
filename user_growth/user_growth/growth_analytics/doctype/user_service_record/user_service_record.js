// 用户服务记录：表单与列表交互
// 设计要点：
//   * 派生字段只读，状态用颜色指示器表达，减少"看数字猜状态"；
//   * 省份 -> 大区的映射来自后端，避免前后端两套口径；
//   * 常用动作（标记流失 / 标记唤回 / 生成演示数据）做成按钮，减少手工改字段。

frappe.ui.form.on("User Service Record", {
	onload(frm) {
		frm.set_query("account_owner", () => ({ filters: { enabled: 1 } }));
		frm.set_query("winback_owner", () => ({ filters: { enabled: 1 } }));
	},

	refresh(frm) {
		const colors = {
			待生效: "blue",
			服务中: "green",
			已暂停: "orange",
			已到期: "gray",
			已流失: "red",
		};
		if (frm.doc.status) {
			frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		}

		if (!frm.is_new()) {
			frm.add_custom_button(__("查看增长大屏"), () => {
				frappe.set_route("growth-dashboard");
			});

			frm.add_custom_button(__("查看同客户全部生命周期"), () => {
				frappe.set_route("List", "User Service Record", {
					user_id: frm.doc.user_id,
				});
			});
		}

		if (!frm.is_new() && !frm.doc.churn_date && frm.doc.status !== "已流失") {
			frm.add_custom_button(
				__("标记流失"),
				() => {
					frappe.prompt(
						[
							{
								fieldname: "churn_date",
								label: __("流失日期"),
								fieldtype: "Date",
								default: frappe.datetime.get_today(),
								reqd: 1,
							},
							{
								fieldname: "churn_reason_category",
								label: __("流失原因分类"),
								fieldtype: "Select",
								options: [
									"价格因素", "功能不满足", "需求变化", "服务体验",
									"竞品替换", "试用结束", "预算削减", "公司经营", "其他",
								],
								reqd: 1,
							},
						],
						(values) => {
							frm.set_value("churn_date", values.churn_date);
							frm.set_value("churn_reason_category", values.churn_reason_category);
							frm.save();
						},
						__("登记流失"),
						__("确认")
					);
				},
				__("操作")
			);
		}

		if (!frm.is_new() && frm.doc.lifecycle_seq === 1) {
			frm.add_custom_button(
				__("标记为唤回（第 2 段生命周期）"),
				() => {
					frappe.confirm(
						__("该客户将在原记录基础上追加一段唤回生命周期，是否继续？"),
						() => {
							frm.set_value("lifecycle_seq", 2);
							frm.set_value("previous_churn_date", frm.doc.churn_date);
							frm.set_value("churn_date", null);
							frm.set_value("churn_reason_category", null);
							frm.set_value("churn_type", null);
							frm.set_value("acquisition_channel", "老客推荐");
							frm.save();
						}
					);
				},
				__("操作")
			);
		}

		if (frappe.user.has_role("System Manager")) {
			frm.add_custom_button(
				__("生成演示数据"),
				() => {
					frappe.confirm(
						__("将生成 24 个月的模拟数据（已存在的数据会自动跳过），是否继续？"),
						() => {
							frappe.dom.freeze(__("正在生成，请稍候…"));
							frappe.call({
								method: "user_growth.api.common.generate_demo_data",
								args: { months: 24, reset: 0 },
								always: () => frappe.dom.unfreeze(),
								callback: (r) => {
									if (r.message) {
										frappe.msgprint({
											title: __("生成完成"),
											indicator: "green",
											message: __(
												"生成 {0} 条，写入 {1} 条，跳过 {2} 条"
											).format(
												r.message.generated,
												r.message.inserted,
												r.message.skipped
											),
										});
										frm.reload_doc();
									}
								},
							});
						}
					);
				},
				__("工具")
			);
		}

		if (!frm.is_new() && frm.doc.health_score !== undefined && frm.doc.health_score < 60) {
			frm.dashboard.add_comment(
				__("该客户健康分 {0}，属于高流失风险，建议尽快跟进。", [frm.doc.health_score]),
				"red",
				true
			);
		}
	},

	province(frm) {
		if (!frm.doc.province) {
			return;
		}
		frappe.call({
			method: "user_growth.api.common.get_region_for_province",
			args: { province: frm.doc.province },
			callback: (r) => {
				if (r.message && r.message.region) {
					frm.set_value("region", r.message.region);
				}
			},
		});
	},

	plan(frm) {
		if (frm.doc.plan === "免费试用") {
			frm.set_value("billing_cycle", "免费");
			frm.set_value("contract_amount", 0);
			frm.set_value("discount_percent", 0);
		} else if (frm.doc.billing_cycle === "免费" || !frm.doc.billing_cycle) {
			frm.set_value("billing_cycle", "月付");
		}
	},

	churn_date(frm) {
		if (frm.doc.churn_date && !frm.doc.churn_type) {
			frm.set_intro(
				__("已登记流失：请补充流失类型与流失原因分类，这两项是流失分析的基础数据。"),
				"orange"
			);
		}
	},
});

frappe.listview_settings["User Service Record"] = {
	add_fields: ["status", "plan", "region", "mrr", "activation_date", "churn_date"],
	hide_name_column: false,
	onload(listview) {
		listview.page.add_inner_button(__("打开增长大屏"), () => {
			frappe.set_route("growth-dashboard");
		});
		listview.page.add_inner_button(__("用户增长与流失分析"), () => {
			frappe.set_route("query-report", "用户增长与流失分析");
		});
	},
	get_indicator(doc) {
		const colors = {
			待生效: "blue",
			服务中: "green",
			已暂停: "orange",
			已到期: "gray",
			已流失: "red",
		};
		return [__(doc.status || "服务中"), colors[doc.status] || "gray", "status,=," + (doc.status || "")];
	},
};

