/* 格式化工具：数字、金额、百分比、日期、脱敏。
 * 约定：所有数字用千分位；金额超过 1 万自动转"万/亿"；缺失值统一显示"–"。 */
window.user_growth = window.user_growth || {};
(function () {
	const EMPTY = "–";

	function number(value, digits) {
		if (value === null || value === undefined || value === "") return EMPTY;
		const num = Number(value);
		if (Number.isNaN(num)) return EMPTY;
		return num.toLocaleString("zh-CN", {
			minimumFractionDigits: digits || 0,
			maximumFractionDigits: digits || 0,
		});
	}

	function money(value) {
		if (value === null || value === undefined || value === "") return EMPTY;
		const num = Number(value);
		if (Number.isNaN(num)) return EMPTY;
		const abs = Math.abs(num);
		if (abs >= 100000000) return (num / 100000000).toFixed(2) + " 亿";
		if (abs >= 10000) return (num / 10000).toFixed(2) + " 万";
		return number(num, 0);
	}

	function moneyUnit(value) {
		const abs = Math.abs(Number(value) || 0);
		if (abs >= 100000000) return "元（亿）";
		if (abs >= 10000) return "元（万）";
		return "元";
	}

	function pct(value, digits) {
		if (value === null || value === undefined || value === "") return EMPTY;
		const num = Number(value);
		if (Number.isNaN(num)) return EMPTY;
		return num.toFixed(digits === undefined ? 1 : digits) + "%";
	}

	function delta(value) {
		if (value === null || value === undefined || value === "") {
			return { text: EMPTY, direction: "flat", className: "ug-delta--flat" };
		}
		const num = Number(value);
		if (Number.isNaN(num) || num === 0) {
			return { text: "0.0%", direction: "flat", className: "ug-delta--flat" };
		}
		const up = num > 0;
		return {
			text: (up ? "+" : "") + num.toFixed(1) + "%",
			direction: up ? "up" : "down",
			// 语义由调用方决定：新增上升是好事，流失上升是坏事
			className: up ? "ug-delta--up" : "ug-delta--down",
			arrow: up ? "▲" : "▼",
		};
	}

	function signed(value, digits) {
		if (value === null || value === undefined || value === "") return EMPTY;
		const num = Number(value);
		if (Number.isNaN(num)) return EMPTY;
		return (num > 0 ? "+" : "") + number(num, digits);
	}

	function date(value) {
		if (!value) return EMPTY;
		return String(value).slice(0, 10);
	}

	function time(value) {
		if (!value) return EMPTY;
		const text = String(value);
		const match = text.match(/(\d{2}:\d{2}:\d{2})/);
		return match ? match[1] : text.slice(11, 19);
	}

	function maskName(name) {
		const text = String(name || "").trim();
		if (!text) return EMPTY;
		if (text.length <= 2) return text[0] + "*";
		return text.slice(0, 2) + "*".repeat(Math.min(text.length - 2, 4));
	}

	function days(value) {
		if (value === null || value === undefined || value === "") return EMPTY;
		const num = Number(value);
		if (Number.isNaN(num)) return EMPTY;
		if (num < 0) return "已过期 " + Math.abs(num) + " 天";
		if (num === 0) return "今天到期";
		return num + " 天";
	}

	window.user_growth.format = {
		EMPTY: EMPTY,
		number: number,
		money: money,
		moneyUnit: moneyUnit,
		pct: pct,
		delta: delta,
		signed: signed,
		date: date,
		time: time,
		maskName: maskName,
		days: days,
	};
})();

