#!/usr/bin/env bash
# 在容器内生成 / 重建演示数据
#
#   docker compose exec bench bash -lc "/workspace/tools/seed.sh"
#   docker compose exec bench bash -lc "MONTHS=12 RESET=1 /workspace/tools/seed.sh"
#
# 说明：不使用 `bench execute user_growth.xxx`，因为该命令的 eval 只认识 frappe 根模块；
# 这里显式起一个带站点上下文的 Python 进程，行为最可预期。
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
SITE="${SITE:-${SITE_NAME:-growth.local}}"
MONTHS="${MONTHS:-24}"
RESET="${RESET:-0}"
SEED="${SEED:-20260101}"

cd "${BENCH_DIR}"

"${BENCH_DIR}/env/bin/python" - <<PY
import os

import frappe

# 说明：frappe 的日志句柄用相对路径 "../logs" 打开，因此工作目录必须与
# bench 命令一致（bench 实际运行在 <bench>/sites 下），否则会报
# FileNotFoundError: /home/frappe/logs/database.log
os.chdir("${BENCH_DIR}/sites")
frappe.init(site="${SITE}", sites_path="${BENCH_DIR}/sites")
frappe.connect()

from user_growth.seed import runner

result = runner.run(months=int("${MONTHS}"), reset=bool(int("${RESET}")), seed=int("${SEED}"))
print("演示数据就绪：", result["report"])
frappe.destroy()
PY
