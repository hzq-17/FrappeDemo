#!/usr/bin/env bash
# 浏览器级验证"真实 Desk 页面"（不是离线预览）：
#   1. 用 desk_page.get() 拼出真实页面脚本（HTML 模板 + 页面 JS）并落盘
#   2. 用 headless chromium 打开 desk-page.html（加载真实脚本 + 真实 bundle）
#   3. 断言页面确实渲染出了 KPI / 面板 / 图表，且没有停在"正在加载"
#
#   docker compose exec bench bash -lc "/workspace/tools/verify_desk_page.sh"
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
SITE="${SITE:-${SITE_NAME:-growth.local}}"
PAGE="${PAGE:-growth-dashboard}"
PORT="${PORT:-8902}"
OUT_SCRIPT="/workspace/tools/preview/page_script.js"
WORK="$(mktemp -d)"

echo "== 1. 导出服务端拼装的页面脚本 =="
cd "${BENCH_DIR}/sites"
"${BENCH_DIR}/env/bin/python" - "${SITE}" "${PAGE}" "${OUT_SCRIPT}" <<'PY'
import os
import sys

import frappe

site, page_name, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
frappe.init(site=site, sites_path=os.getcwd())
frappe.connect()
from frappe.desk import desk_page

docs = desk_page.get(page_name)
script = docs.get("script") or ""
with open(out_path, "w", encoding="utf-8") as handle:
    handle.write(script)
print(f"  已写入 {out_path}（{len(script)} 字符）")
frappe.destroy()
PY

echo "== 2. headless 渲染真实页面脚本 =="
cd /workspace
python3 -m http.server "${PORT}" >/dev/null 2>&1 &
SERVER_PID=$!
trap 'kill ${SERVER_PID} 2>/dev/null || true; rm -rf "${WORK}"' EXIT
sleep 1.5

chromium --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage \
	--window-size=1920,1080 --virtual-time-budget=9000 --dump-dom \
	"http://localhost:${PORT}/tools/preview/desk-page.html" > "${WORK}/dom.html" 2>/dev/null || true

python3 - "${WORK}/dom.html" <<'PY'
import json
import re
import sys

html = open(sys.argv[1], encoding="utf-8").read()
match = re.search(r'id="ug-page-diagnostics"[^>]*>([^<]+)<', html)
if not match:
	print("  FAILED: 没有拿到页面诊断信息（脚本可能抛异常导致 DOM 未生成）")
	print("  DOM 片段:", html[-500:])
	sys.exit(1)

data = json.loads(match.group(1))
print("  " + json.dumps(data, ensure_ascii=False))

problems = []
if not data["hasMountPoint"]:
	problems.append("页面骨架里没有 #ug-root（模板没被渲染出来）")
if data["kpiCards"] != 6:
	problems.append(f"KPI 卡片数量应为 6，实际 {data['kpiCards']}")
if data["panels"] != 5:
	problems.append(f"面板数量应为 5，实际 {data['panels']}")
if data["svgCount"] < 5:
	problems.append(f"图表数量过少：{data['svgCount']}")
if data["emptyRoot"]:
	problems.append("页面还停留在“正在加载增长数据…”（脚本没有接管渲染）")
if data["explicitError"]:
	problems.append("页面出现错误提示（资源加载失败 / 脚本异常）")
if data["canvasWidth"] < 300:
	problems.append("画布没有正常渲染出宽度")

if problems:
	print("FAILED:")
	for item in problems:
		print("  -", item)
	sys.exit(1)
print("  -> 真实页面脚本 + 模板 + 前端模块 渲染通过（浏览器打开不应再白屏）")
PY
