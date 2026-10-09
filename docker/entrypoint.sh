#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# user_growth 容器启动脚本（幂等，可反复执行）
#   1. 初始化 sites 目录（命名卷首次挂载为空时，用镜像内的种子目录填充）
#   2. 把宿主机挂载的 App 源码接入 bench
#   3. 写入数据库 / Redis 公共配置
#   4. 首次创建站点并开启开发者模式（调试模式）
#   5. 安装应用、构建前端资源、生成 mock 数据
#   6. 启动 bench 全部进程（web / socketio / scheduler / worker / watch）
# ---------------------------------------------------------------------------
set -euo pipefail

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
SITE_NAME="${SITE_NAME:-growth.local}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-admin}"
DB_HOST="${DB_HOST:-mariadb}"
DB_PORT="${DB_PORT:-3306}"
REDIS_CACHE="${REDIS_CACHE:-redis-cache}"
REDIS_QUEUE="${REDIS_QUEUE:-redis-queue}"
APP_NAME="user_growth"
APP_SRC="${APP_SRC:-/workspace/${APP_NAME}}"
SEED_DATA="${SEED_DATA:-1}"
SEED_MONTHS="${SEED_MONTHS:-24}"
SEED_RESET="${SEED_RESET:-0}"
SITES_SEED_DIR="/home/frappe/sites-seed"

log()  { printf '\n\033[1;36m[user_growth]\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m[user_growth][warn]\033[0m %s\n' "$*"; }

cd "$BENCH_DIR"

# --- 1. sites 目录 ---------------------------------------------------------
if [ ! -f "${BENCH_DIR}/sites/apps.txt" ]; then
	log "初始化 sites 目录（命名卷首次启动）"
	mkdir -p "${BENCH_DIR}/sites"
	cp -a "${SITES_SEED_DIR}/." "${BENCH_DIR}/sites/"
fi

# --- 2. 接入应用源码 -------------------------------------------------------
if [ -d "$APP_SRC" ]; then
	MODE="symlink"
	if ! touch "${APP_SRC}/.ug-write-probe" 2>/dev/null; then
		MODE="copy"
		warn "挂载目录不可写，改用拷贝模式（修改源码后需要重启容器生效）"
	else
		rm -f "${APP_SRC}/.ug-write-probe"
	fi

	if [ "$MODE" = "symlink" ]; then
		if [ -L "${BENCH_DIR}/apps/${APP_NAME}" ] || [ ! -e "${BENCH_DIR}/apps/${APP_NAME}" ]; then
			rm -rf "${BENCH_DIR}/apps/${APP_NAME}"
			ln -sfn "${APP_SRC}" "${BENCH_DIR}/apps/${APP_NAME}"
		fi
	else
		rm -rf "${BENCH_DIR}/apps/${APP_NAME}"
		mkdir -p "${BENCH_DIR}/apps/${APP_NAME}"
		cp -a "${APP_SRC}/." "${BENCH_DIR}/apps/${APP_NAME}/"
	fi
	log "应用源码就绪：apps/${APP_NAME}（${MODE} 模式）"

	# 把应用注册进 bench 的应用清单
	# （等价于 bench get-app 做的事：写入 sites/apps.txt，让框架加载 hooks.py）
	# 这里直接根据 apps/ 下的真实目录重建清单：既幂等，又能自动修复历史上被写坏的文件。
	APPS_FILE="${BENCH_DIR}/sites/apps.txt"
	APPS_TMP="$(mktemp)"
	for app_dir in "${BENCH_DIR}"/apps/*/; do
		candidate="$(basename "${app_dir}")"
		# 只收录"看起来像 Frappe 应用"的目录：包目录与目录同名
		[ -d "${app_dir}${candidate}" ] || continue
		echo "${candidate}" >> "${APPS_TMP}"
	done
	mv "${APPS_TMP}" "${APPS_FILE}"
	log "应用清单已同步：$(tr '\n' ' ' < "${APPS_FILE}")"

	# 让应用可以被 import
	# 挂载进来的应用不会经过 pip install -e，因此这里用 .pth 把应用目录加入 sys.path。
	# 相比在容器启动时跑一次 editable install，这种方式不依赖网络、瞬时完成且可预期。
	VENV_PY="${BENCH_DIR}/env/bin/python"
	if [ -x "${VENV_PY}" ]; then
		SITE_PACKAGES="$("${VENV_PY}" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
		echo "${BENCH_DIR}/apps/${APP_NAME}" > "${SITE_PACKAGES}/${APP_NAME}.pth"
	fi
else
	warn "未找到应用源码目录 ${APP_SRC}，跳过接入"
fi

# --- 3. 公共配置 -----------------------------------------------------------
log "写入数据库与 Redis 配置"
bench set-config -g db_host "${DB_HOST}" >/dev/null
bench set-config -g db_port "${DB_PORT}" >/dev/null
bench set-config -g redis_cache "redis://${REDIS_CACHE}:6379" >/dev/null
bench set-config -g redis_queue "redis://${REDIS_QUEUE}:6379" >/dev/null
bench set-config -g redis_socketio "redis://${REDIS_QUEUE}:6379" >/dev/null
bench set-config -g socketio_port 9000 >/dev/null
bench set-config -g serve_default_site true >/dev/null

# --- 4. 站点 ---------------------------------------------------------------
if [ ! -d "${BENCH_DIR}/sites/${SITE_NAME}" ]; then
	log "创建站点 ${SITE_NAME}"
	NEW_SITE_ARGS=("${SITE_NAME}"
		--db-host "${DB_HOST}" --db-port "${DB_PORT}"
		--mariadb-root-username root --mariadb-root-password "${DB_ROOT_PASSWORD}"
		--admin-password "${ADMIN_PASSWORD}")
	if bench new-site --help 2>&1 | grep -q -- '--no-mariadb-socket'; then
		NEW_SITE_ARGS+=(--no-mariadb-socket)
	fi
	bench new-site "${NEW_SITE_ARGS[@]}"
fi

# 站点别名：允许直接用 localhost / 127.0.0.1 访问，避免 "site not found"
for alias in localhost 127.0.0.1; do
	if [ ! -e "${BENCH_DIR}/sites/${alias}" ]; then
		ln -sfn "${SITE_NAME}" "${BENCH_DIR}/sites/${alias}"
	fi
done

bench use "${SITE_NAME}" >/dev/null
bench --site "${SITE_NAME}" set-config developer_mode 1 >/dev/null
bench --site "${SITE_NAME}" set-config mute_emails 1 >/dev/null
# 演示/开发容器：允许在站点上跑单元测试（bench --site ... run-tests）
bench --site "${SITE_NAME}" set-config allow_tests true >/dev/null
log "站点就绪：${SITE_NAME}（developer_mode=1，调试模式已开启；测试开关已允许）"

# 站点默认货币：报表里的金额列（Currency 类型）按货币格式化显示（如 ¥214,743）
if ! "${BENCH_DIR}/env/bin/python" - <<PY
import os

import frappe

os.chdir("${BENCH_DIR}/sites")
frappe.init(site="${SITE_NAME}", sites_path="${BENCH_DIR}/sites")
frappe.connect()
if not frappe.db.get_single_value("System Settings", "currency"):
    frappe.db.set_single_value("System Settings", "currency", "CNY")
    frappe.db.commit()
    frappe.clear_cache()
    print("已设置站点货币：CNY")
frappe.destroy()
PY
then
	warn "设置站点货币失败（不影响启动，可忽略）"
fi

# --- 5. 应用安装 / 资源构建 / 演示数据 -------------------------------------
if ! bench --site "${SITE_NAME}" list-apps 2>/dev/null | tr -d '\r' | grep -q "${APP_NAME}"; then
	log "安装应用 ${APP_NAME}"
	bench --site "${SITE_NAME}" install-app "${APP_NAME}"
fi

log "构建前端资源（bench build --app ${APP_NAME}）"
bench build --app "${APP_NAME}" >/dev/null

if [ "${SEED_DATA}" = "1" ]; then
	log "生成演示数据（幂等；SEED_MONTHS=${SEED_MONTHS} SEED_RESET=${SEED_RESET}）"
	# 说明：这里不用 `bench execute`，因为该命令在 eval 时只认识 frappe 根模块，
	# 传入 user_growth.xxx 会 NameError。直接起一个带站点上下文的 Python 进程最稳。
	if ! "${BENCH_DIR}/env/bin/python" - <<PY
import os

import frappe

os.chdir("${BENCH_DIR}/sites")
frappe.init(site="${SITE_NAME}", sites_path="${BENCH_DIR}/sites")
frappe.connect()

from user_growth.seed import runner

result = runner.run(months=int("${SEED_MONTHS}"), reset=bool(int("${SEED_RESET}")))
print("演示数据就绪：", result["report"])
frappe.destroy()
PY
	then
		warn "演示数据生成失败（不影响服务启动），可稍后执行 /workspace/tools/seed.sh 重试"
	fi
fi

# --- 6. 启动 ---------------------------------------------------------------
log "启动 bench：web=http://localhost:8000  socketio=:9000"
exec bench start
