/* 大屏控制器：状态、取数、刷新、交互、分辨率适配。
 *
 * 刷新策略（来自设计文档 9.6 / 10.6）：
 *   首屏      → 一次 get_dashboard_data（全部面板一起到位，避免"面板陆续跳出"）
 *   定时(60s) → get_kpi_summary + get_trend_series（局部更新，数字滚动）
 *   切粒度    → 只刷新趋势与 KPI
 *   下钻      → 重新取全量（带区域筛选）
 * 页面切走后定时器会自动停止（tick 时检测 DOM 是否还在），避免内存泄漏。
 */
window.user_growth = window.user_growth || {};
(function () {
	const api = window.user_growth.api;
	const layout = window.user_growth.layout;
	const F = window.user_growth.format;

	const REFRESH_INTERVAL = 60000;
	const PLAYBACK_INTERVAL = 8000;
const PLAYBACK_SIZE = 3;

	let state = null;

	function mount(root, options) {
		if (!root) return;
		const refs = layout.build(root);
		state = {
			root: root,
			refs: refs,
			options: options || {},
			filters: { preset: "近30天", granularity: "日" },
			auto: true,
			drillRegion: null,
			timer: null,
			playbackTimer: null,
			accountOffset: 0,
			payload: null,
			scale: 1,
		};
		refs.onRetry = function () {
			refreshAll();
		};
		layout.setUpdatedAt(refs, "--:--:--");
		layout.setFooter(refs, null, "");
		bind();
		applyScale();
		window.addEventListener("resize", onResize);
		document.addEventListener("fullscreenchange", onFullscreenChange);
		refreshAll();
		startTimers();
	}

	/* ------------------------------------------------------------------ 交互 */
	function bind() {
		const refs = state.refs;

		refs.rangeSelect.addEventListener("change", function () {
			state.filters.preset = refs.rangeSelect.value;
			state.drillRegion = null;
			layout.setBreadcrumb(refs, null, resetDrill);
			refreshAll();
		});

		Object.keys(refs.granButtons).forEach(function (value) {
			refs.granButtons[value].addEventListener("click", function () {
				state.filters.granularity = value;
				Object.keys(refs.granButtons).forEach(function (key) {
					refs.granButtons[key].classList.toggle("is-active", key === value);
				});
				refreshIncremental();
			});
		});

		refs.refreshButton.addEventListener("click", function () {
			refreshAll();
		});

		refs.autoInput.addEventListener("change", function () {
			state.auto = refs.autoInput.checked;
			layout.setFooter(refs, state.caliber, state.auto ? "" : "已暂停自动刷新");
		});

		refs.immersiveButton.addEventListener("click", function () {
			setImmersive(!state.immersive);
		});

		document.addEventListener("keydown", onKeydown);
	}

	function onKeydown(event) {
		if (!state) return;
		const tag = (event.target && event.target.tagName) || "";
		if (["INPUT", "SELECT", "TEXTAREA"].indexOf(tag) >= 0) return;
		const key = event.key.toLowerCase();
		if (key === "f") {
			event.preventDefault();
			setImmersive(!state.immersive);
		} else if (key === "r") {
			event.preventDefault();
			refreshAll();
		} else if (event.code === "Space") {
			event.preventDefault();
			state.auto = !state.auto;
			state.refs.autoInput.checked = state.auto;
			layout.setFooter(state.refs, state.caliber, state.auto ? "" : "已暂停自动刷新");
		} else if (key === "escape" && state.immersive) {
			setImmersive(false);
		}
	}

	function resetDrill() {
		state.drillRegion = null;
		layout.setBreadcrumb(state.refs, null, resetDrill);
		refreshAll();
	}

	function drillRegion(region) {
		state.drillRegion = region;
		layout.setBreadcrumb(state.refs, region, resetDrill);
		refreshAll();
	}

	/* ------------------------------------------------------------ 沉浸模式 */
	function setImmersive(on) {
		state.immersive = !!on;
		document.body.classList.toggle("ug-immersive", state.immersive);
		state.refs.immersiveButton.textContent = state.immersive ? "退出沉浸" : "沉浸模式";
		applyScale();
		try {
			if (state.immersive && document.documentElement.requestFullscreen) {
				document.documentElement.requestFullscreen();
			} else if (!state.immersive && document.fullscreenElement && document.exitFullscreen) {
				document.exitFullscreen();
			}
		} catch (err) {
			/* 浏览器可能拒绝全屏（非用户手势），此时仅保留沉浸样式 */
		}
	}

	function onFullscreenChange() {
		if (!state) return;
		if (!document.fullscreenElement && state.immersive) {
			state.immersive = false;
			document.body.classList.remove("ug-immersive");
			state.refs.immersiveButton.textContent = "沉浸模式";
			applyScale();
		}
	}

	/* -------------------------------------------------------------- 尺寸适配 */
	function applyScale() {
		if (!state) return;
		const refs = state.refs;
		const rect = refs.stage.getBoundingClientRect();
		const width = rect.width || window.innerWidth;
		const height = rect.height || window.innerHeight;
		const scale = Math.min(width / layout.constants.CANVAS_W, height / layout.constants.CANVAS_H);
		const offsetX = Math.max((width - layout.constants.CANVAS_W * scale) / 2, 0);
		const offsetY = Math.max((height - layout.constants.CANVAS_H * scale) / 2, 0);
		refs.canvas.style.transform = "scale(" + scale + ")";
		refs.canvas.style.left = offsetX + "px";
		refs.canvas.style.top = offsetY + "px";
		state.scale = scale;
	}

	let resizeTimer = null;
	function onResize() {
		if (resizeTimer) clearTimeout(resizeTimer);
		resizeTimer = setTimeout(applyScale, 200);
	}

	/* ------------------------------------------------------------------ 取数 */
	function currentFilters() {
		const filters = {
			preset: state.filters.preset,
			granularity: state.filters.granularity,
		};
		if (state.drillRegion) filters.region = [state.drillRegion];
		return filters;
	}

	async function refreshAll() {
		if (!state) return;
		const refs = state.refs;
		layout.setState(refs, state.payload ? "ready" : "loading");
		try {
			const envelope = await api.dashboard(currentFilters());
			state.payload = envelope.data;
			state.caliber = envelope.caliber;
			render(envelope);
			layout.setState(refs, "ready");
		} catch (error) {
			renderError(error);
		}
	}

	async function refreshIncremental() {
		if (!state || !state.payload) return refreshAll();
		const refs = state.refs;
		const filters = currentFilters();
		try {
			const results = await Promise.all([api.kpi(filters), api.trend(filters)]);
			const kpiEnvelope = results[0] || {};
			const trendEnvelope = results[1] || {};
			state.payload.kpi = kpiEnvelope.data || state.payload.kpi;
			const trend = trendEnvelope.data || state.payload.trend;
			state.payload.trend = trend;
			layout.renderKpi(refs, state.payload.kpi, trend);
			layout.renderTrend(refs, trend);
			layout.setUpdatedAt(refs, F.time(kpiEnvelope.generated_at || trendEnvelope.generated_at));
			layout.setFooter(refs, kpiEnvelope.caliber || state.caliber, state.auto ? "" : "已暂停自动刷新");
		} catch (error) {
			layout.setPanelError(refs, "trend", (error && error.message) || "趋势数据刷新失败");
		}
	}

	/* ------------------------------------------------------------------ 渲染 */
	function render(envelope) {
		const refs = state.refs;
		const data = envelope.data || {};
		const trend = data.trend || { labels: [], new: [], churned: [], active: [], net: [] };
		state.caliber = envelope.caliber;
		state.accountOffset = 0;

		layout.renderKpi(refs, data.kpi || {}, trend);
		layout.renderTrend(refs, trend);
		layout.renderRegion(refs, data.distribution || {}, { onRegionClick: onRegionClick });
		layout.renderChannel(refs, (data.distribution || {}).channel || []);
		layout.renderChurn(refs, data.churn_reasons || []);
		renderTopWindow(data);
		layout.setUpdatedAt(refs, F.time(envelope.generated_at));
		layout.setFooter(
			refs,
			envelope.caliber,
			"缓存 " + (envelope.cached ? "命中" : "未命中") +
				"　·　自动刷新 " + (state.auto ? "开启（60 秒）" : "已暂停") +
				"　·　快捷键：F 全屏 / Space 暂停 / R 刷新"
		);
	}

	function onRegionClick(item) {
		const region = (item && (item.raw || item.label)) || null;
		if (region) drillRegion(region);
	}

	function renderTopWindow(data) {
		const accounts = data.top_accounts || [];
		const total = accounts.length;
		let windowed = accounts;
		if (total > PLAYBACK_SIZE) {
			const start = state.accountOffset % total;
			windowed = accounts.slice(start, start + PLAYBACK_SIZE);
			if (windowed.length < PLAYBACK_SIZE) {
				windowed = windowed.concat(accounts.slice(0, PLAYBACK_SIZE - windowed.length));
			}
		}
		layout.renderTop(state.refs, windowed, (data.events || []).slice(0, 4));
	}

	function renderError(error) {
		const refs = state.refs;
		const message = (error && error.message) || "数据加载失败";
		layout.setState(refs, "error");
		Object.keys(refs.panels).forEach(function (name) {
			layout.setPanelError(refs, name, message);
		});
		layout.setFooter(refs, state.caliber, "请求失败（错误码 " + ((error && error.code) || 500) + "）");
	}

	/* ------------------------------------------------------------------ 定时 */
	function startTimers() {
		stopTimers();
		state.timer = setInterval(tick, REFRESH_INTERVAL);
		state.playbackTimer = setInterval(playback, PLAYBACK_INTERVAL);
	}

	function stopTimers() {
		if (!state) return;
		if (state.timer) clearInterval(state.timer);
		if (state.playbackTimer) clearInterval(state.playbackTimer);
		state.timer = null;
		state.playbackTimer = null;
	}

	function tick() {
		if (!state) return;
		if (!document.body.contains(state.root)) {
			// 页面已切走：停止定时器，避免后台持续请求
			stopTimers();
			document.removeEventListener("keydown", onKeydown);
			window.removeEventListener("resize", onResize);
			return;
		}
		if (!state.auto || document.hidden) return;
		refreshIncremental();
	}

	function playback() {
		if (!state || !state.payload || document.hidden) return;
		const accounts = state.payload.top_accounts || [];
		if (accounts.length <= PLAYBACK_SIZE) return;
		state.accountOffset = (state.accountOffset + PLAYBACK_SIZE) % accounts.length;
		renderTopWindow(state.payload);
	}

	window.user_growth.screen = {
		mount: mount,
		refresh: refreshAll,
		setImmersive: setImmersive,
		destroy: function () {
			stopTimers();
			state = null;
		},
	};
})();
