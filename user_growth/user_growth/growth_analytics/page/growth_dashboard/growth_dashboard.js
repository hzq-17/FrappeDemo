// 增长大屏页面：加载前端资源并挂载大屏
//
// 资源加载顺序：
//   1) 优先使用 bench build 产出的 bundle（一次请求，体积最小）；
//   2) 若 bundle 尚未构建（404/超时），自动回退到按顺序加载单个源码文件，
//      保证"忘记执行 bench build"时页面依然可用（只是请求数变多）。

frappe.pages["growth-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("增长大屏"),
		single_column: true,
	});
	$(wrapper).find(".page-head").addClass("ug-page-head");

	// 页面骨架来自同目录的 growth_dashboard.html（框架在 load_assets 时注册为 JS 模板）
	render_page_shell(page);

	load_screen_assets(function (ok) {
		const root = wrapper.querySelector("#ug-root");
		if (!ok || !window.user_growth || !window.user_growth.screen) {
			if (root) {
				root.innerHTML =
					'<div style="padding:40px;color:#f97316;font-size:16px">' +
					"前端资源加载失败：请确认已执行 <code>bench build --app user_growth</code> 后刷新页面。" +
					"</div>";
			}
			return;
		}
		window.user_growth.screen.mount(root, {
			page: page,
			// 支持 /app/growth-dashboard?full=1 直接进入沉浸模式
			immersive: /(\?|&)full=1/.test(window.location.search),
		});
		if (window.user_growth.screen && /(\?|&)full=1/.test(window.location.search)) {
			window.user_growth.screen.setImmersive(true);
		}
	});
};

// 把页面骨架渲染进 page.main。
// 优先用框架注册的 HTML 模板；若模板缺失（例如别人删了 .html），退化为脚本内置骨架，
// 保证"任何时候都不会白屏"。
function render_page_shell(page) {
	const fallback =
		'<div class="ug-screen" id="ug-root" data-state="loading">' +
		'<div class="ug-stage"><div class="ug-canvas" ' +
		'style="align-items:center;justify-content:center;color:#5F6E88;font-size:18px">' +
		"正在加载增长数据…</div></div></div>";
	let html = fallback;
	try {
		if (frappe.templates && frappe.templates.growth_dashboard) {
			html = frappe.render_template("growth_dashboard", {});
		}
	} catch (error) {
		console.warn("[user_growth] 页面模板渲染失败，使用内置骨架", error);
	}
	$(page.main).html(html);
}

frappe.pages["growth-dashboard"].on_page_show = function (wrapper) {
	// 从其它页面切回大屏时，重新计算缩放（Desk 容器尺寸可能已变化）
	const screen = window.user_growth && window.user_growth.screen;
	if (screen && screen.refresh) {
		setTimeout(function () {
			window.dispatchEvent(new Event("resize"));
		}, 300);
	}
};

function load_screen_assets(callback) {
	const CSS = "/assets/user_growth/css/growth_screen.css";
	// 逻辑名（不是文件路径）：bench build 会给产物加内容 hash，
	// frappe.require → frappe.assets → frappe.boot.assets_json 会把它解析成真实路径。
	// 另外 hooks.py 里已声明 app_include_js，正常进入页面时命名空间已存在，这里只是兜底。
	const BUNDLE = "user_growth.bundle.js";
	let finished = false;

	function finish(ok) {
		if (!finished) {
			finished = true;
			callback(ok);
		}
	}

	inject_css(CSS);
	if (window.user_growth && window.user_growth.screen) {
		finish(true);
		return;
	}

	const timer = setTimeout(function () {
		if (!(window.user_growth && window.user_growth.screen)) {
			load_fallback(finish);
		}
	}, 2500);

	if (typeof frappe.require === "function") {
		try {
			frappe.require(BUNDLE, function () {
				clearTimeout(timer);
				if (window.user_growth && window.user_growth.screen) {
					finish(true);
				} else {
					load_fallback(finish);
				}
			});
			return;
		} catch (error) {
			clearTimeout(timer);
		}
	}
	load_fallback(finish);
}

function load_fallback(callback) {
	const files = ["format", "api", "charts", "layout", "screen"].map(function (name) {
		return "/assets/user_growth/js/growth_screen/" + name + ".js";
	});
	load_sequence(files, 0, function () {
		callback(!!(window.user_growth && window.user_growth.screen));
	});
}

function load_sequence(files, index, callback) {
	if (index >= files.length) {
		callback();
		return;
	}
	const script = document.createElement("script");
	script.src = files[index];
	script.onload = function () {
		load_sequence(files, index + 1, callback);
	};
	script.onerror = function () {
		load_sequence(files, index + 1, callback);
	};
	document.head.appendChild(script);
}

function inject_css(href) {
	if (document.querySelector('link[href="' + href + '"]')) {
		return;
	}
	const link = document.createElement("link");
	link.rel = "stylesheet";
	link.href = href;
	document.head.appendChild(link);
}
