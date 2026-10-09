#!/usr/bin/env bash
# 在容器内运行数据质量自检（10 项断言）
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
SITE="${SITE:-${SITE_NAME:-growth.local}}"

cd "${BENCH_DIR}"

"${BENCH_DIR}/env/bin/python" - <<PY
import os

import frappe

os.chdir("${BENCH_DIR}/sites")
frappe.init(site="${SITE}", sites_path="${BENCH_DIR}/sites")
frappe.connect()

from user_growth.seed import quality_check

results = quality_check.run()
print("自检结果：", quality_check.summary(results))
for row in results:
    print(f"[{row['status'].upper():4}] {row['code']} {row['name']}：{row['detail']}")
frappe.destroy()
PY
