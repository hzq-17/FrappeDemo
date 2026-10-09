/* 零依赖 SVG 图表：柱线组合图、横向条形、环形图、迷你趋势线。
 *
 * 为什么自己画而不用图表库：
 *   1. 大屏需要完全离线可用（内网/断网演示），不能依赖 CDN；
 *   2. 视觉规范（配色、字号、间距）需要与设计令牌严格一致，第三方库的主题覆盖成本更高；
 *   3. 只用到 4 种图形，自绘约 300 行即可完全掌控渲染与性能（图表实例可复用、可整体销毁）。
 * 所有尺寸使用"逻辑像素"（基准画布 1920×1080），由外层容器统一缩放。
 */
window.user_growth = window.user_growth || {};
(function () {
	const NS = "http://www.w3.org/2000/svg";
	const FONT = '"Noto Sans SC","Microsoft YaHei",system-ui,-apple-system,sans-serif';
	const GRID = "rgba(91,107,136,0.18)";
	const AXIS_TEXT = "#5F6E88";

	// 图表语义色：与 growth_screen.css 的 :root 令牌保持一致（改配色只需改这两处）
	const THEME = {
		accent: "#3D5AFE",   // 存量 / 主序列
		growth: "#0891B2",   // 新增 / 增长（青）
		churn: "#F97316",    // 流失 / 风险（橙）
		success: "#059669",  // 正向变化
		warning: "#D97706",  // 预警
		violet: "#7C3AED",
		sky: "#0284C7",
		muted: "#94A3B8",
	};

	function node(name, attrs, content) {
		const element = document.createElementNS(NS, name);
		Object.keys(attrs || {}).forEach(function (key) {
			element.setAttribute(key, attrs[key]);
		});
		if (content !== undefined && content !== null) {
			element.textContent = content;
		}
		return element;
	}

	function text(x, y, content, options) {
		const opts = options || {};
		return node(
			"text",
			{
				x: x,
				y: y,
				fill: opts.fill || AXIS_TEXT,
				"font-size": opts.size || 13,
				"font-family": FONT,
				"font-weight": opts.weight || 400,
				"text-anchor": opts.anchor || "start",
				"dominant-baseline": opts.baseline || "middle",
				"font-variant-numeric": "tabular-nums",
			},
			content
		);
	}

	function niceCeil(value) {
		if (!value || value <= 0) return 1;
		const exponent = Math.pow(10, Math.floor(Math.log10(value)));
		const fraction = value / exponent;
		let nice = 10;
		if (fraction <= 1) nice = 1;
		else if (fraction <= 2) nice = 2;
		else if (fraction <= 2.5) nice = 2.5;
		else if (fraction <= 5) nice = 5;
		return nice * exponent;
	}

	function empty(host, width, height, message) {
		host.innerHTML = "";
		const svg = node("svg", { width: width, height: height, viewBox: "0 0 " + width + " " + height });
		svg.appendChild(text(width / 2, height / 2, message || "暂无数据", {
			anchor: "middle", size: 15, fill: "#5F6E88",
		}));
		host.appendChild(svg);
		return svg;
	}

	/* ------------------------------------------------------------------
	 * 柱线组合图：柱 = 新增 / 流失，线 = 期末在服
	 * ------------------------------------------------------------------ */
	function combo(host, options) {
		const opts = options || {};
		const labels = opts.labels || [];
		const bars = opts.bars || [];
		const line = opts.line || null;
		const width = opts.width || 900;
		const height = opts.height || 300;

		if (!labels.length) return empty(host, width, height, opts.emptyText);

		host.innerHTML = "";
		const pad = { top: 34, right: line ? 64 : 24, bottom: 30, left: 58 };
		const innerW = width - pad.left - pad.right;
		const innerH = height - pad.top - pad.bottom;

		const barMax = niceCeil(
			bars.reduce(function (acc, series) {
				return Math.max(acc, Math.max.apply(null, series.values.concat([0])));
			}, 0)
		);
		const lineMax = line
			? niceCeil(Math.max.apply(null, line.values.concat([0])))
			: barMax;

		const svg = node("svg", { width: width, height: height, viewBox: "0 0 " + width + " " + height });
		const step = innerW / labels.length;
		const groupW = Math.min(step * 0.68, 42);
		const barW = bars.length ? Math.max(groupW / bars.length - 2, 4) : 0;

		// 网格与左轴
		for (let i = 0; i <= 4; i++) {
			const y = pad.top + (innerH / 4) * i;
			svg.appendChild(node("line", {
				x1: pad.left, x2: pad.left + innerW, y1: y, y2: y, stroke: GRID, "stroke-width": 1,
			}));
			svg.appendChild(text(pad.left - 10, y, format_axis(barMax * (4 - i) / 4), {
				anchor: "end", size: 12,
			}));
		}

		// 右轴（期末在服）
		if (line) {
			for (let i = 0; i <= 4; i++) {
				const y = pad.top + (innerH / 4) * i;
				svg.appendChild(text(pad.left + innerW + 10, y, format_axis(lineMax * (4 - i) / 4), {
				anchor: "start", size: 12, fill: line.color || "#3D5AFE",
				}));
			}
		}

		// 柱
		labels.forEach(function (label, index) {
			const center = pad.left + step * index + step / 2;
			const groupLeft = center - (barW * bars.length + 2 * (bars.length - 1)) / 2;
			bars.forEach(function (series, seriesIndex) {
				const value = Number(series.values[index] || 0);
				const barHeight = barMax ? (value / barMax) * innerH : 0;
				const x = groupLeft + seriesIndex * (barW + 2);
				const rect = node("rect", {
					x: x,
					y: pad.top + innerH - barHeight,
					width: barW,
					height: Math.max(barHeight, value > 0 ? 2 : 0),
					rx: 2,
					fill: series.color,
					opacity: 0.92,
				});
				attach_tooltip(host, rect, label, [
					{ name: series.name, value: format_int(value), color: series.color },
					line ? { name: line.name, value: format_int(line.values[index]), color: line.color } : null,
				].filter(Boolean));
				svg.appendChild(rect);
			});
		});

		// 折线
		if (line) {
			const points = labels.map(function (label, index) {
				const x = pad.left + step * index + step / 2;
				const y = pad.top + innerH - (lineMax ? (Number(line.values[index] || 0) / lineMax) * innerH : 0);
				return { x: x, y: y };
			});
			svg.appendChild(node("polyline", {
				points: points.map(function (p) { return p.x + "," + p.y; }).join(" "),
				fill: "none",
				stroke: line.color,
				"stroke-width": 2.5,
				"stroke-linejoin": "round",
				"stroke-linecap": "round",
			}));
			points.forEach(function (point, index) {
				const dot = node("circle", {
					cx: point.x, cy: point.y, r: 3.5, fill: "#FFFFFF",
					stroke: line.color, "stroke-width": 2,
				});
				attach_tooltip(host, dot, labels[index], [
					{ name: line.name, value: format_int(line.values[index]), color: line.color },
					bars[0] ? { name: bars[0].name, value: format_int(bars[0].values[index]), color: bars[0].color } : null,
					bars[1] ? { name: bars[1].name, value: format_int(bars[1].values[index]), color: bars[1].color } : null,
				].filter(Boolean));
				svg.appendChild(dot);
			});
		}

		// X 轴标签（数据点多时抽稀，避免文字重叠）
		const labelStep = Math.ceil(labels.length / 14);
		labels.forEach(function (label, index) {
			if (index % labelStep !== 0 && index !== labels.length - 1) return;
			svg.appendChild(text(pad.left + step * index + step / 2, height - 12, label, {
				anchor: "middle", size: 12,
			}));
		});

		host.appendChild(svg);
		return svg;
	}

	/* ------------------------------------------------------------------
	 * 横向条形：地域 / 流失原因等排名类数据
	 * ------------------------------------------------------------------ */
	function hbars(host, options) {
		const opts = options || {};
		const items = opts.items || [];
		const width = opts.width || 420;
		const rowHeight = opts.rowHeight || 30;
		const labelWidth = opts.labelWidth || 84;
		const valueWidth = opts.valueWidth || 78;
		if (!items.length) return empty(host, width, rowHeight * 3, opts.emptyText);

		host.innerHTML = "";
		const height = items.length * rowHeight + 6;
		const max = opts.max || Math.max.apply(null, items.map(function (item) {
			return Number(item.value || 0);
		}).concat([1]));
		const svg = node("svg", { width: width, height: height, viewBox: "0 0 " + width + " " + height });
		const trackX = labelWidth + 8;
		const trackW = Math.max(width - trackX - valueWidth, 40);

		items.forEach(function (item, index) {
			const y = index * rowHeight + 6;
			const value = Number(item.value || 0);
			const barW = max ? Math.max((value / max) * trackW, value > 0 ? 3 : 0) : 0;
			svg.appendChild(text(0, y + rowHeight / 2 - 2, item.label, {
				size: opts.labelSize || 13, fill: "#16233F",
			}));
			svg.appendChild(node("rect", {
				x: trackX, y: y + 5, width: trackW, height: 12, rx: 6,
				fill: "rgba(91,107,136,0.10)",
			}));
			const bar = node("rect", {
				x: trackX, y: y + 5, width: barW, height: 12, rx: 6,
			fill: item.color || opts.color || "#0891B2", opacity: 0.95,
			});
			if (opts.onClick) {
				bar.style.cursor = "pointer";
				bar.addEventListener("click", function () { opts.onClick(item); });
			}
			attach_tooltip(host, bar, item.label, [
				{ name: opts.valueName || "数值", value: format_int(value), color: item.color || opts.color },
				item.extra ? { name: opts.extraName || "占比", value: item.extra } : null,
			].filter(Boolean));
			svg.appendChild(bar);
			svg.appendChild(text(width - 4, y + rowHeight / 2 - 2, item.display || format_int(value), {
				anchor: "end", size: 13, fill: "#16233F", weight: 500,
			}));
		});

		host.appendChild(svg);
		return svg;
	}

	/* ------------------------------------------------------------------
	 * 环形图（渠道 / 套餐结构）
	 * ------------------------------------------------------------------ */
	function donut(host, options) {
		const opts = options || {};
		const items = opts.items || [];
		const size = opts.size || 200;
		const thickness = opts.thickness || 26;
		if (!items.length) return empty(host, size, size, opts.emptyText);

		host.innerHTML = "";
		const svg = node("svg", { width: size, height: size, viewBox: "0 0 " + size + " " + size });
		const cx = size / 2;
		const cy = size / 2;
		const radius = (size - thickness) / 2 - 4;
		const total = items.reduce(function (acc, item) { return acc + Number(item.value || 0); }, 0) || 1;
		let angle = -Math.PI / 2;

		items.forEach(function (item, index) {
			const ratio = Number(item.value || 0) / total;
			const sweep = ratio * Math.PI * 2;
			const color = item.color || palette(index);
			if (ratio <= 0) return;
			if (ratio >= 0.9999) {
				svg.appendChild(node("circle", {
					cx: cx, cy: cy, r: radius, fill: "none", stroke: color,
					"stroke-width": thickness,
				}));
				return;
			}
			const x1 = cx + radius * Math.cos(angle);
			const y1 = cy + radius * Math.sin(angle);
			const end = angle + sweep;
			const x2 = cx + radius * Math.cos(end);
			const y2 = cy + radius * Math.sin(end);
			const arc = node("path", {
				d: "M " + x1 + " " + y1 + " A " + radius + " " + radius + " 0 " +
					(sweep > Math.PI ? 1 : 0) + " 1 " + x2 + " " + y2,
				fill: "none", stroke: color, "stroke-width": thickness, "stroke-linecap": "butt",
			});
			attach_tooltip(host, arc, item.label, [
				{ name: opts.valueName || "数量", value: format_int(item.value), color: color },
				{ name: "占比", value: (ratio * 100).toFixed(1) + "%", color: color },
			]);
			svg.appendChild(arc);
			angle = end;
		});

		svg.appendChild(text(cx, cy - 8, opts.centerValue !== undefined ? opts.centerValue : format_int(total), {
			anchor: "middle", size: 26, fill: "#16233F", weight: 700,
		}));
		svg.appendChild(text(cx, cy + 18, opts.centerLabel || "合计", {
			anchor: "middle", size: 12,
		}));
		host.appendChild(svg);
		return svg;
	}

	/* ------------------------------------------------------------------
	 * 迷你趋势线（KPI 卡片）
	 * ------------------------------------------------------------------ */
	function sparkline(host, options) {
		const opts = options || {};
		const values = opts.values || [];
		const width = opts.width || 120;
		const height = opts.height || 34;
		host.innerHTML = "";
		if (values.length < 2) return null;
		const max = Math.max.apply(null, values);
		const min = Math.min.apply(null, values);
		const span = max - min || 1;
		const step = width / (values.length - 1);
		const points = values.map(function (value, index) {
			const x = index * step;
			const y = height - 3 - ((value - min) / span) * (height - 8);
			return x + "," + y;
		});
		const svg = node("svg", { width: width, height: height, viewBox: "0 0 " + width + " " + height });
		svg.appendChild(node("polyline", {
			points: points.join(" "),
			fill: "none",
			stroke: opts.color || "#0891B2",
			"stroke-width": 2,
			"stroke-linecap": "round",
			"stroke-linejoin": "round",
		}));
		host.appendChild(svg);
		return svg;
	}

	/* ------------------------------------------------------------------
	 * 工具
	 * ------------------------------------------------------------------ */
	function attach_tooltip(host, element, title, rows) {
		host.style.position = host.style.position || "relative";
		element.addEventListener("mouseenter", function (event) {
			const tip = document.createElement("div");
			tip.className = "ug-tooltip";
			const head = document.createElement("div");
			head.className = "ug-tooltip__title";
			head.textContent = title;
			tip.appendChild(head);
			rows.forEach(function (row) {
				const line = document.createElement("div");
				line.className = "ug-tooltip__row";
				const dot = document.createElement("span");
				dot.className = "ug-tooltip__dot";
				dot.style.background = row.color || "#94A3B8";
				const name = document.createElement("span");
				name.className = "ug-tooltip__name";
				name.textContent = row.name;
				const value = document.createElement("span");
				value.className = "ug-tooltip__value";
				value.textContent = row.value;
				line.appendChild(dot);
				line.appendChild(name);
				line.appendChild(value);
				tip.appendChild(line);
			});
			host.appendChild(tip);
			const box = host.getBoundingClientRect();
			const x = (event.clientX || box.left) - box.left;
			const y = (event.clientY || box.top) - box.top;
			tip.style.left = Math.max(8, Math.min(x + 12, box.width - 170)) + "px";
			tip.style.top = Math.max(8, y - 10) + "px";
		});
		element.addEventListener("mouseleave", function () {
			host.querySelectorAll(".ug-tooltip").forEach(function (tip) { tip.remove(); });
		});
	}

	function format_int(value) {
		const num = Number(value || 0);
		return num.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
	}

	function format_axis(value) {
		const num = Number(value || 0);
		if (num >= 100000000) return (num / 100000000).toFixed(1) + "亿";
		if (num >= 10000) return (num / 10000).toFixed(1) + "万";
		if (num >= 1000) return (num / 1000).toFixed(1) + "k";
		return String(Math.round(num));
	}

	function palette(index) {
		const colors = ["#3D5AFE", "#0891B2", "#F97316", "#059669", "#7C3AED",
			"#0284C7", "#D97706", "#E11D48", "#4D7C0F"];
		return colors[index % colors.length];
	}

	window.user_growth.charts = {
		theme: THEME,
		combo: combo,
		hbars: hbars,
		donut: donut,
		sparkline: sparkline,
		palette: palette,
		niceCeil: niceCeil,
	};
})();
