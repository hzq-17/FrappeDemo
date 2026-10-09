#!/usr/bin/env bash
# 生成大屏离线预览数据并截图（在容器内执行）
#
#   docker compose exec bench bash -lc "/workspace/tools/preview.sh"
#   docker compose exec bench bash -lc "PRESET=\"近 7 天\" /workspace/tools/preview.sh"
#
# 产出：
#   tools/preview/dashboard.json              真实接口数据快照
#   tools/preview/screenshot-1920x1080.png    大屏截图（1920 基准分辨率）
#   tools/preview/screenshot-3840x2160.png    大屏截图（4K）
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
SITE="${SITE:-${SITE_NAME:-growth.local}}"
PRESET="${PRESET:-近30天}"

echo "== 1. 导出大屏数据快照 =="
cd "${BENCH_DIR}/sites"
"${BENCH_DIR}/env/bin/python" - <<PY
import frappe

frappe.init(site="${SITE}", sites_path="${BENCH_DIR}/sites")
frappe.connect()

from user_growth.seed import runner

print(runner.dump_preview_snapshot("/workspace/tools/preview/dashboard.json", preset="${PRESET}")["path"])
frappe.destroy()
PY

echo "== 2. 生成截图 =="
SIZE=1920x1080 /workspace/tools/screenshot.sh
SIZE=3840x2160 /workspace/tools/screenshot.sh

ls -la /workspace/tools/preview/*.png
