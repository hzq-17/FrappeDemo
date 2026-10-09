/* 后端接口封装：统一走 frappe.call，筛选条件以 JSON 字符串传递，避免数组序列化歧义。 */
window.user_growth = window.user_growth || {};
(function () {
	const METHOD = {
		dashboard: "user_growth.api.growth_screen.get_dashboard_data",
		kpi: "user_growth.api.growth_screen.get_kpi_summary",
		trend: "user_growth.api.growth_screen.get_trend_series",
		region: "user_growth.api.growth_screen.get_region_breakdown",
		events: "user_growth.api.growth_screen.get_event_feed",
		options: "user_growth.api.common.get_filter_options",
	};

	function call(method, args) {
		return new Promise(function (resolve, reject) {
			frappe.call({
				method: method,
				args: args || {},
				callback: function (response) {
					resolve(response && response.message);
				},
				error: function (error) {
					reject(normalize_error(error));
				},
			});
		});
	}

	// 把服务端异常映射成前端可展示的错误码/文案（与设计文档的错误码表一一对应）
	function normalize_error(error) {
		const excType = (error && (error.exc_type || (error.responseJSON || {}).exc_type)) || "";
		const message =
			(error && error.message) ||
			((error || {}).responseJSON && error.responseJSON._server_messages) ||
			"请求失败";
		let code = 500;
		let text = "数据加载失败，请稍后重试";
		if (excType.indexOf("PermissionError") >= 0) {
			code = 403;
			text = "当前账号没有查看增长数据的权限";
		} else if (excType.indexOf("ValidationError") >= 0) {
			code = 412;
			text = "筛选条件不合法，请调整后重试";
		} else if (excType.indexOf("TimeoutError") >= 0 || excType.indexOf("QueryTimeout") >= 0) {
			code = 504;
			text = "查询范围过大，请缩小时间范围或切换更粗的时间粒度";
		} else if (typeof message === "string" && message.indexOf("Frappe") === -1) {
			text = message;
		}
		return { code: code, message: text, raw: error };
	}

	function encode(filters) {
		return JSON.stringify(filters || {});
	}

	window.user_growth.api = {
		call: call,
		dashboard: function (filters) {
			return call(METHOD.dashboard, { filters: encode(filters) });
		},
		kpi: function (filters) {
			return call(METHOD.kpi, { filters: encode(filters) });
		},
		trend: function (filters) {
			return call(METHOD.trend, { filters: encode(filters) });
		},
		region: function (filters, region) {
			return call(METHOD.region, { filters: encode(filters), region: region });
		},
		events: function (filters, limit) {
			return call(METHOD.events, { filters: encode(filters), limit: limit || 12 });
		},
		options: function () {
			return call(METHOD.options, {});
		},
	};
})();

