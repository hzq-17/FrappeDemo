#!/usr/bin/env bash
# 校验"真实 Desk 页面"能否正常渲染（不同于 tools/preview 的离线预览）。
#
# 走的是浏览器同一条服务端路径：frappe.desk.desk_page.get() → Page.load_assets()，
# 因此能抓住"页面骨架缺失/模板被转义破坏/挂载点不匹配"这类白屏问题。
#
#   docker compose exec bench bash -lc "/workspace/tools/verify_page.sh"
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
SITE="${SITE:-${SITE_NAME:-growth.local}}"
PAGE="${PAGE:-growth-dashboard}"

cd "${BENCH_DIR}/sites"
"${BENCH_DIR}/env/bin/python" - "${SITE}" "${PAGE}" <<'PY'
import os
import subprocess
import sys

import frappe
from frappe.modules import get_module_path, scrub

site, page_name = sys.argv[1], sys.argv[2]
frappe.init(site=site, sites_path=os.getcwd())
frappe.connect()

from frappe.desk import desk_page

docs = desk_page.get(page_name)          # 与浏览器同一个入口
script = docs.get("script") or ""
page = frappe.get_doc("Page", page_name)

print(f"页面 {page.name}｜标题 {page.title}｜标准页 {page.standard}｜可见角色 {[r.role for r in page.roles]}")
print(f"服务端返回的页面脚本长度 = {len(script)}")

problems = []

# 1. 页面脚本必须注册到 frappe.pages，并且 HTML 模板必须先于脚本被注册
if "frappe.pages" not in script or page_name not in script:
    problems.append("页面脚本没有注册 frappe.pages['<page>']（on_page_load 不会触发）")
if "frappe.templates" not in script or "growth_dashboard" not in script:
    problems.append("页面 HTML 模板没有注册（缺 growth_dashboard.html）")
elif script.index("frappe.templates") > script.index("frappe.pages"):
    problems.append("HTML 模板注册在页面脚本之后，模板会取不到")

# 2. 骨架必须提供脚本要挂载的容器 id
if "ug-root" not in script:
    problems.append("页面骨架里没有 #ug-root 挂载点（脚本会无处渲染）")

# 3. 页面目录下的 .html 不能包含单引号（框架把它塞进单引号 JS 字符串）
page_dir = os.path.join(get_module_path(page.module), "page", scrub(page.name))
html_files = [f for f in os.listdir(page_dir) if f.endswith(".html")] if os.path.isdir(page_dir) else []
if not html_files:
    problems.append(f"页面目录缺少 .html 骨架文件：{page_dir}")
for name in html_files:
    content = open(os.path.join(page_dir, name), encoding="utf-8").read()
    if "'" in content:
        problems.append(f"{name} 含单引号：会被拼坏成非法 JS 字符串，导致整页白屏")

# 4. 服务端拼好的脚本必须是合法 JS（用 node 做纯语法校验）
syntax_file = "/tmp/ug_page_script.js"
with open(syntax_file, "w", encoding="utf-8") as handle:
    handle.write(script)
result = subprocess.run(["node", "--check", syntax_file], capture_output=True, text=True)
if result.returncode != 0:
    problems.append("服务端拼装的页面脚本语法错误：\n" + (result.stderr or "").strip()[:600])

# 5. 页面依赖的前端资源必须在资源清单里（否则脚本无法加载大屏模块）
import json

assets = json.load(open(os.path.join(os.getcwd(), "assets", "assets.json"), encoding="utf-8"))
if "user_growth.bundle.js" not in assets:
    problems.append("assets.json 里没有 user_growth.bundle.js（hooks 的 app_include_js 未生效或未构建）")

if problems:
    print("FAILED:")
    for item in problems:
        print("  -", item)
    sys.exit(1)

print("  -> 页面骨架、模板注册顺序、挂载点、脚本语法、资源清单 全部正常")
print("  -> 浏览器打开 /app/growth-dashboard 应能正常渲染（如仍空白请硬刷新 Ctrl+Shift+R）")
frappe.destroy()
PY
