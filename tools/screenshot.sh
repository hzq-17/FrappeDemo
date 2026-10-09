#!/usr/bin/env bash
# 在容器内对大屏（离线预览页）截图，用于视觉验证。
#   SIZE=1920x1080 tools/screenshot.sh
#   SIZE=3840x2160 tools/screenshot.sh
set -euo pipefail

SIZE="${SIZE:-1920x1080}"
WIDTH="${SIZE%x*}"
HEIGHT="${SIZE#*x}"
PORT="${PORT:-8899}"
OUT="/workspace/tools/preview/screenshot-${SIZE}.png"

if ! command -v chromium >/dev/null 2>&1; then
	echo "未安装 chromium（构建镜像时 INSTALL_BROWSER=0？）" >&2
	exit 1
fi

cd /workspace
python3 -m http.server "${PORT}" >/dev/null 2>&1 &
SERVER_PID=$!
trap 'kill ${SERVER_PID} 2>/dev/null || true' EXIT
sleep 1.5

chromium \
	--headless=new \
	--no-sandbox \
	--disable-gpu \
	--disable-dev-shm-usage \
	--hide-scrollbars \
	--force-device-scale-factor=1 \
	--window-size="${WIDTH},${HEIGHT}" \
	--virtual-time-budget=8000 \
	--screenshot="${OUT}" \
	"http://localhost:${PORT}/tools/preview/" >/dev/null 2>&1

echo "已生成截图：${OUT}"

