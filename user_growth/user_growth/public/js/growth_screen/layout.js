/* 大屏布局：按 1920×1080 的设计稿构建 DOM，并把数据渲染进各面板。
 *
 * 几何（逻辑像素，来自设计文档 9.2 的尺寸分配）：
 *   外边距 24 | 顶栏 76 | 间距 20 | KPI 148 | 间距 20 | 中部 372 | 间距 20 | 底部 316 | 间距 20 | 状态栏 40 | 外边距 24 = 1080
 */
window.user_growth = window.user_growth || {};
(function () {
	const F = window.user_growth.format;
	const charts = window.user_growth.charts;
	const THEME = charts.theme;

	const CANVAS_W = 1920;
	const CANVAS_H = 1080;
	const PAD = 24;
	const GAP = 20;
	const HEADER_H = 76;
	const KPI_H = 148;
	const MID_H = 372;
	const BOTTOM_H = 316;
	const FOOTER_H = 40;
	const CONTENT_W = CANVAS_W - PAD * 2;
	const PANEL_HEAD = 36;
	const PANEL_PAD = 20;

	const RANGES = [
		{ value: "近7天", label: "近 7 天" },
		{ value: "近30天", label: "近 30 天" },
		{ value: "近90天", label: "近 90 天" },
		{ value: "本月", label: "本月" },
		{ value: "本季度", label: "本季度" },
		{ value: "近12个月", label: "近 12 个月" },
	];
	const GRANULARITIES = ["日", "周", "月"];

	function h(tag, className, content) {
		const element = document.createElement(tag);
		if (className) element.className = className;
		if (content !== undefined && content !== null) element.textContent = content;
		return element;
	}

	function panel(title, hint, role) {
		const article = h("article", "ug-panel");
		article.setAttribute("data-panel", role);
		const header = h("div", "ug-panel__head");
		header.appendChild(h("span", "ug-panel__bar"));
		header.appendChild(h("h2", "ug-panel__title", title));
		if (hint) header.appendChild(h("span", "ug-panel__hint", hint));
		article.appendChild(header);
		const body = h("div", "ug-panel__body");
		article.appendChild(body);
		article.body = body;
		return article;
	}

	function build(root) {
		root.innerHTML = "";
		root.setAttribute("data-state", "loading");

		const stage = h("div", "ug-stage");
		const canvas = h("div", "ug-canvas");
		stage.appendChild(canvas);
		root.appendChild(stage);

		// ---------------- 顶栏 ----------------
		const header = h("header", "ug-header");
		const brand = h("div", "ug-header__brand");
		brand.appendChild(h("span", "ug-header__logo", "UG"));
		const brandText = h("div", "ug-header__text");
		brandText.appendChild(h("h1", "ug-header__title", "用户增长实时大屏"));
		brandText.appendChild(h("p", "ug-header__sub", "开通 · 续费 · 流失 · 收入"));
		brand.appendChild(brandText);
		header.appendChild(brand);

		const controls = h("div", "ug-header__controls");
		const rangeSelect = h("select", "ug-select");
		RANGES.forEach(function (item) {
			const option = h("option", null, item.label);
			option.value = item.value;
			rangeSelect.appendChild(option);
		});
		rangeSelect.value = "近30天";
		controls.appendChild(wrap("时间范围", rangeSelect));

		const granGroup = h("div", "ug-seg");
		const granButtons = {};
		GRANULARITIES.forEach(function (value) {
			const button = h("button", "ug-seg__item", value);
			button.type = "button";
			button.setAttribute("data-value", value);
			granGroup.appendChild(button);
			granButtons[value] = button;
		});
		granButtons["日"].classList.add("is-active");
		controls.appendChild(wrap("粒度", granGroup));

		const refreshButton = h("button", "ug-btn", "刷新");
		refreshButton.type = "button";
		controls.appendChild(refreshButton);

		const autoLabel = h("label", "ug-switch");
		const autoInput = document.createElement("input");
		autoInput.type = "checkbox";
		autoInput.checked = true;
		autoLabel.appendChild(autoInput);
		autoLabel.appendChild(h("span", null, "自动刷新"));
		controls.appendChild(autoLabel);

		const updatedAt = h("span", "ug-updated", "最后更新 --:--:--");
		controls.appendChild(updatedAt);

		const immersiveButton = h("button", "ug-btn ug-btn--ghost", "沉浸模式");
		immersiveButton.type = "button";
		controls.appendChild(immersiveButton);

		header.appendChild(controls);
		canvas.appendChild(header);

		// ---------------- KPI ----------------
		const kpiRow = h("section", "ug-kpi");
		canvas.appendChild(kpiRow);

		// ---------------- 中部 ----------------
		const mid = h("section", "ug-mid");
		const trendPanel = panel("用户增长趋势", "柱：新增 / 流失　线：期末在服", "trend");
		mid.appendChild(trendPanel);
		const regionPanel = panel("用户地域分布", "点击大区可下钻", "region");
		mid.appendChild(regionPanel);
		canvas.appendChild(mid);

		// ---------------- 底部 ----------------
		const bottom = h("section", "ug-bottom");
		const channelPanel = panel("渠道结构", "按期末在服用户数占比", "channel");
		bottom.appendChild(channelPanel);
		const churnPanel = panel("流失原因分布", "含流失收入损失", "churn");
		bottom.appendChild(churnPanel);
		const topPanel = panel("重点客户与实时动态", "按「MRR × 风险」排序", "top");
		bottom.appendChild(topPanel);
		canvas.appendChild(bottom);

		// ---------------- 状态栏 ----------------
		const footer = h("footer", "ug-footer");
		const caliber = h("span", "ug-footer__caliber", "口径加载中…");
		const runtime = h("span", "ug-footer__runtime", "");
		footer.appendChild(caliber);
		footer.appendChild(runtime);
		canvas.appendChild(footer);

		// 尺寸断言：保证各区块加起来正好是设计稿的 1080（防止后续加东西时悄悄错位）
		const totalHeight = PAD * 2 + HEADER_H + GAP * 4 + KPI_H + MID_H + BOTTOM_H + FOOTER_H;
		if (totalHeight !== CANVAS_H) {
			console.warn("[user_growth] 布局高度与设计稿不一致：", totalHeight, "应为", CANVAS_H);
		}

		// 面板内容区 = 面板宽度 - 左右内边距；底部三列等分（2 个 20px 间距）
		const bottomPanelWidth = (CONTENT_W - GAP * 2) / 3;
		const trendBodyWidth = 1232 - PANEL_PAD * 2;
		const regionBodyWidth = 620 - PANEL_PAD * 2;
		const bodyWidth = bottomPanelWidth - PANEL_PAD * 2;
		const midBodyHeight = MID_H - PANEL_HEAD - PANEL_PAD * 2;
		const bottomBodyHeight = BOTTOM_H - PANEL_HEAD - PANEL_PAD * 2;
		const refs = {
			root: root,
			stage: stage,
			canvas: canvas,
			canvasWidth: CANVAS_W,
			canvasHeight: CANVAS_H,
			rangeSelect: rangeSelect,
			granButtons: granButtons,
			refreshButton: refreshButton,
			autoInput: autoInput,
			updatedAt: updatedAt,
			immersiveButton: immersiveButton,
			kpiRow: kpiRow,
			panels: {
				// 高度留 4px 余量：flex 取整可能让 296 变成 294.5，避免最后几像素被裁切
				trend: { node: trendPanel, body: trendPanel.body, width: trendBodyWidth, height: midBodyHeight - 4 },
				region: { node: regionPanel, body: regionPanel.body, width: regionBodyWidth, height: midBodyHeight - 4 },
				channel: { node: channelPanel, body: channelPanel.body, width: bodyWidth, height: bottomBodyHeight - 4 },
				churn: { node: churnPanel, body: churnPanel.body, width: bodyWidth, height: bottomBodyHeight - 4 },
				top: { node: topPanel, body: topPanel.body, width: bodyWidth, height: bottomBodyHeight - 4 },
			},
			footer: { caliber: caliber, runtime: runtime },
			breadcrumb: null,
		};
		return refs;
	}

	function wrap(labelText, control) {
		const box = h("div", "ug-field");
		box.appendChild(h("span", "ug-field__label", labelText));
		box.appendChild(control);
		return box;
	}

	/* ------------------------------------------------------------------
	 * KPI 卡片
	 * ------------------------------------------------------------------ */
	function renderKpi(refs, kpi, trend) {
		refs.kpiRow.innerHTML = "";
		const cards = [
			{
				key: "active",
				label: "在服用户数",
				value: F.number(kpi.active_users),
				unit: "户",
				delta: kpi.active_users_delta,
				polarity: "positive",
				hint: "期初 " + F.number(kpi.active_users_begin),
				spark: trend ? trend.active : null,
				color: THEME.accent,
			},
			{
				key: "new",
				label: "本期新增",
				value: F.number(kpi.new_users),
				unit: "户",
				delta: kpi.new_users_delta,
				polarity: "positive",
				hint: "新客 " + F.number(kpi.new_users_new) + " · 唤回 " + F.number(kpi.new_users_winback),
				color: THEME.growth,
			},
			{
				key: "churned",
				label: "本期流失",
				value: F.number(kpi.churned_users),
				unit: "户",
				delta: kpi.churned_users_delta,
				polarity: "negative",
				hint: "流失 MRR " + F.money(kpi.mrr_churned),
				color: THEME.churn,
			},
			{
				key: "net",
				label: "净增长",
				value: F.signed(kpi.net_growth),
				unit: "户",
				delta: kpi.net_growth_delta,
				polarity: "positive",
				hint: "流失率 " + F.pct(kpi.churn_rate, 2),
				spark: trend ? trend.net : null,
				color: THEME.success,
			},
			{
				key: "mrr",
				label: "净 MRR 变化",
				value: F.money(kpi.mrr_net),
				unit: F.moneyUnit(kpi.mrr_net),
				delta: kpi.mrr_net_delta,
				polarity: "positive",
				hint: "期末在服 MRR " + F.money(kpi.mrr_active),
				color: THEME.violet,
			},
			{
				key: "life",
				label: "平均生命周期",
				value: F.number(kpi.avg_lifecycle_days, 1),
				unit: "天",
				delta: null,
				polarity: "positive",
				hint: "ARPU " + F.money(kpi.arpu) + " · LTV≈" + F.money(kpi.ltv_estimate),
				color: THEME.sky,
			},
		];

		cards.forEach(function (card) {
			const node = h("div", "ug-kpi__card");
			node.setAttribute("data-kpi", card.key);
			const top = h("div", "ug-kpi__top");
			top.appendChild(h("span", "ug-kpi__label", card.label));
			if (card.delta !== null && card.delta !== undefined) {
				const delta = F.delta(card.delta);
				const good = card.polarity === "negative" ? delta.direction === "down" : delta.direction === "up";
				const cls = delta.direction === "flat" ? "ug-delta--flat" : good ? "ug-delta--good" : "ug-delta--bad";
				const badge = h("span", "ug-delta " + cls);
				badge.appendChild(h("i", "ug-delta__arrow", delta.arrow || "•"));
				badge.appendChild(h("span", null, delta.text));
				top.appendChild(badge);
			}
			node.appendChild(top);
			const value = h("div", "ug-kpi__value");
			value.appendChild(h("span", "ug-kpi__number", card.value));
			value.appendChild(h("span", "ug-kpi__unit", card.unit));
			node.appendChild(value);
			const bottom = h("div", "ug-kpi__bottom");
			bottom.appendChild(h("span", "ug-kpi__hint", card.hint));
			if (card.spark && card.spark.length > 1) {
				const sparkBox = h("span", "ug-kpi__spark");
				bottom.appendChild(sparkBox);
				charts.sparkline(sparkBox, { values: card.spark, width: 96, height: 26, color: card.color });
			}
			node.appendChild(bottom);
			refs.kpiRow.appendChild(node);
		});
	}

	/* ------------------------------------------------------------------
	 * 趋势（柱 + 线）
	 * ------------------------------------------------------------------ */
	function renderTrend(refs, trend) {
		const panel = refs.panels.trend;
		charts.combo(panel.body, {
			labels: trend.labels,
			bars: [
				{ name: "新增用户", values: trend.new, color: THEME.growth },
				{ name: "流失用户", values: trend.churned, color: THEME.churn },
			],
			line: { name: "期末在服", values: trend.active, color: THEME.accent },
			width: panel.width,
			height: panel.height,
			emptyText: "当前时间范围内没有数据，请切换时间范围",
		});
	}

	/* ------------------------------------------------------------------
	 * 地域分布：左侧大区排行 + 右侧省份 Top
	 * ------------------------------------------------------------------ */
	function renderRegion(refs, distribution, options) {
		const panel = refs.panels.region;
		panel.body.innerHTML = "";
		const regions = (distribution.region || []).slice(0, 8);
		const provinces = (distribution.province || []).slice(0, 6);

		const left = h("div", "ug-region__col ug-region__col--bars");
		const leftWidth = Math.round(panel.width * 0.56);
		panel.body.appendChild(left);
		charts.hbars(left, {
			items: regions.map(function (row) {
				return {
					label: row.label,
					value: row.active,
					display: F.number(row.active) + "  (" + F.pct(row.share, 1) + ")",
					extra: F.pct(row.share, 1),
					raw: row.label,
				};
			}),
			width: leftWidth,
			rowHeight: 27,
			labelWidth: 46,
			valueWidth: 92,
			valueName: "在服用户",
			onClick: options.onRegionClick,
			emptyText: "暂无地域数据",
		});

		const right = h("div", "ug-region__col ug-region__col--list");
		panel.body.appendChild(right);
		const listTitle = h("div", "ug-subhead", "省份 Top " + provinces.length);
		right.appendChild(listTitle);
		const list = h("ul", "ug-rank");
		provinceRows(provinces).forEach(function (row) {
			list.appendChild(row);
		});
		right.appendChild(list);
	}

	function provinceRows(provinces) {
		return provinces.map(function (row, index) {
			const item = h("li", "ug-rank__item");
			item.appendChild(h("span", "ug-rank__index", String(index + 1)));
			item.appendChild(h("span", "ug-rank__name", row.label));
			const stats = h("span", "ug-rank__stats");
			stats.appendChild(h("b", null, F.number(row.active)));
			stats.appendChild(h("em", null, "+" + F.number(row.new)));
			item.appendChild(stats);
			return item;
		});
	}

	/* ------------------------------------------------------------------
	 * 渠道结构：环形图 + 图例
	 * ------------------------------------------------------------------ */
	function renderChannel(refs, rows) {
		const panel = refs.panels.channel;
		panel.body.innerHTML = "";
		if (!rows || !rows.length) {
			charts.donut(panel.body, { items: [], size: 180, emptyText: "暂无渠道数据" });
			return;
		}
		const top = rows.slice(0, 6);
		const rest = rows.slice(6);
		const items = top.map(function (row, index) {
			return {
				label: row.label,
				value: row.active,
				color: charts.palette(index),
			};
		});
		if (rest.length) {
			items.push({
				label: "其他",
				value: rest.reduce(function (acc, row) { return acc + row.active; }, 0),
				color: THEME.muted,
			});
		}
		const total = items.reduce(function (acc, item) { return acc + item.value; }, 0);
		const donutBox = h("div", "ug-donut");
		panel.body.appendChild(donutBox);
		charts.donut(donutBox, {
			items: items,
			size: 170,
			thickness: 24,
			centerValue: F.number(total),
			centerLabel: "在服用户",
			valueName: "在服用户",
		});
		const legend = h("ul", "ug-legend");
		items.forEach(function (item) {
			const li = h("li", "ug-legend__item");
			const dot = h("span", "ug-legend__dot");
			dot.style.background = item.color;
			li.appendChild(dot);
			li.appendChild(h("span", "ug-legend__name", item.label));
			li.appendChild(h("span", "ug-legend__value", F.number(item.value)));
			li.appendChild(h("span", "ug-legend__share",
				F.pct(total ? (item.value / total) * 100 : 0, 1)));
			legend.appendChild(li);
		});
		panel.body.appendChild(legend);
	}

	/* ------------------------------------------------------------------
	 * 流失原因
	 * ------------------------------------------------------------------ */
	function renderChurn(refs, rows) {
		const panel = refs.panels.churn;
		if (!rows || !rows.length) {
			charts.hbars(panel.body, { items: [], width: panel.width, emptyText: "本期没有流失记录" });
			return;
		}
		const top = rows.slice(0, 6);
		const rest = rows.slice(6);
		const items = top.map(function (row, index) {
			return {
				label: row.label,
				value: row.count,
				display: row.count + " 户 · " + F.pct(row.share, 0),
				color: [THEME.churn, "#FB923C", THEME.warning, THEME.violet, THEME.sky, "#6F7E99"][index % 6],
				extra: F.money(row.mrr) + " 元",
			};
		});
		if (rest.length) {
			items.push({
				label: "其他原因",
				value: rest.reduce(function (acc, row) { return acc + row.count; }, 0),
				display: rest.reduce(function (acc, row) { return acc + row.count; }, 0) + " 户",
				color: "#94A3B8",
			});
		}
		charts.hbars(panel.body, {
			items: items,
			width: panel.width,
			rowHeight: 30,
			labelWidth: 84,
			valueWidth: 108,
			color: THEME.churn,
			valueName: "流失用户",
			extraName: "流失 MRR",
		});
	}

	/* ------------------------------------------------------------------
	 * 重点客户 + 实时动态
	 * ------------------------------------------------------------------ */
	function renderTop(refs, accounts, events) {
		const panel = refs.panels.top;
		panel.body.innerHTML = "";
		panel.body.appendChild(h("div", "ug-subhead", "重点客户（高 MRR × 高流失风险）"));
		const list = h("ul", "ug-accounts");
		(accounts || []).forEach(function (row) {
			const item = h("li", "ug-accounts__item");
			const main = h("div", "ug-accounts__main");
			main.appendChild(h("span", "ug-accounts__name", row.user_name));
			main.appendChild(h("span", "ug-accounts__meta",
				row.plan + " · " + row.region + (row.province ? "/" + row.province : "")));
			item.appendChild(main);
			const risk = h("span", "ug-risk ug-risk--" + riskKey(row.risk_level));
			risk.textContent = row.risk_level || "中";
			item.appendChild(risk);
			const money = h("div", "ug-accounts__money");
			money.appendChild(h("b", null, F.money(row.mrr)));
			money.appendChild(h("em", null, "健康分 " + row.health_score +
				(row.days_to_expiry !== null && row.days_to_expiry !== undefined
					? " · " + F.days(row.days_to_expiry) : "")));
			item.appendChild(money);
			list.appendChild(item);
		});
		if (!accounts || !accounts.length) {
			list.appendChild(h("li", "ug-empty", "当前没有需要关注的客户"));
		}
		panel.body.appendChild(list);

		panel.body.appendChild(h("div", "ug-subhead ug-subhead--gap", "实时动态"));
		const feed = h("ul", "ug-feed");
		(events || []).slice(0, 4).forEach(function (row) {
			const item = h("li", "ug-feed__item");
			const kind = h("span", "ug-feed__kind ug-feed__kind--" + (row.kind === "流失" ? "churn" : "new"), row.kind);
			item.appendChild(kind);
			item.appendChild(h("span", "ug-feed__name", row.user_name));
			item.appendChild(h("span", "ug-feed__meta", row.plan + " · " + row.region));
			item.appendChild(h("span", "ug-feed__date", F.date(row.date).slice(5)));
			feed.appendChild(item);
		});
		if (!events || !events.length) {
			feed.appendChild(h("li", "ug-empty", "今天还没有新的事件"));
		}
		panel.body.appendChild(feed);
	}

	function riskKey(level) {
		if (level === "高") return "high";
		if (level === "低") return "low";
		return "mid";
	}

	/* ------------------------------------------------------------------
	 * 状态
	 * ------------------------------------------------------------------ */
	function setState(refs, state) {
		refs.root.setAttribute("data-state", state);
	}

	function setPanelError(refs, name, message) {
		const panel = refs.panels[name];
		if (!panel) return;
		panel.body.innerHTML = "";
		const box = h("div", "ug-panel-error");
		box.appendChild(h("span", "ug-panel-error__icon", "!"));
		box.appendChild(h("span", null, message || "该面板数据加载失败"));
		const retry = h("button", "ug-btn ug-btn--small", "重试");
		retry.type = "button";
		retry.addEventListener("click", function () {
			if (refs.onRetry) refs.onRetry(name);
		});
		box.appendChild(retry);
		panel.body.appendChild(box);
	}

	function setUpdatedAt(refs, text) {
		refs.updatedAt.textContent = "最后更新 " + text;
	}

	function setFooter(refs, caliber, runtimeText) {
		const parts = [];
		if (caliber) {
			parts.push("在服口径：" + caliber.active_users);
			parts.push("流失率分母：" + caliber.churn_rate_denominator);
			parts.push("时区：" + caliber.timezone);
			parts.push("时间桶：" + caliber.granularity);
		}
		refs.footer.caliber.textContent = parts.join("　·　");
		refs.footer.runtime.textContent = runtimeText || "";
	}

	function setBreadcrumb(refs, region, onReset) {
		if (refs.breadcrumb) {
			refs.breadcrumb.remove();
			refs.breadcrumb = null;
		}
		if (!region) return;
		const bar = h("div", "ug-breadcrumb");
		bar.appendChild(h("span", "ug-breadcrumb__label", "已下钻"));
		bar.appendChild(h("b", null, region));
		const reset = h("button", "ug-btn ug-btn--small ug-btn--ghost", "返回全国");
		reset.type = "button";
		reset.addEventListener("click", onReset);
		bar.appendChild(reset);
		refs.canvas.insertBefore(bar, refs.kpiRow);
		refs.breadcrumb = bar;
	}

	window.user_growth.layout = {
		build: build,
		renderKpi: renderKpi,
		renderTrend: renderTrend,
		renderRegion: renderRegion,
		renderChannel: renderChannel,
		renderChurn: renderChurn,
		renderTop: renderTop,
		setState: setState,
		setPanelError: setPanelError,
		setUpdatedAt: setUpdatedAt,
		setFooter: setFooter,
		setBreadcrumb: setBreadcrumb,
		constants: { CANVAS_W: CANVAS_W, CANVAS_H: CANVAS_H, RANGES: RANGES, GRANULARITIES: GRANULARITIES },
	};
})();
