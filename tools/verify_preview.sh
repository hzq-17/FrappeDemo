#!/usr/bin/env bash
# 大屏渲染自检：用 headless chromium 打开离线预览页，dump DOM 并断言
#   * 6 张 KPI 卡片、5 个面板、若干 SVG 图表都渲染出来了
#   * KPI 数字是真实数字而不是空值
#   * 没有出现面板级错误 / 整屏错误
#   * 底栏口径说明已写入
#
#   docker compose exec bench bash -lc "/workspace/tools/verify_preview.sh"
set -euo pipefail

PORT="${PORT:-8899}"
SIZE="${SIZE:-1920x1080}"
WIDTH="${SIZE%x*}"
HEIGHT="${SIZE#*x}"
WORK="$(mktemp -d)"
cd /workspace

python3 -m http.server "${PORT}" >/dev/null 2>&1 &
SERVER_PID=$!
trap 'kill ${SERVER_PID} 2>/dev/null || true; rm -rf "${WORK}"' EXIT
sleep 1.5

chromium --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage \
	--window-size="${WIDTH},${HEIGHT}" --virtual-time-budget=9000 --dump-dom \
	"http://localhost:${PORT}/tools/preview/" > "${WORK}/dom.html" 2>/dev/null || true

python3 - "${WORK}/dom.html" <<'PY'
import re
import sys

html = open(sys.argv[1], encoding="utf-8").read()


def count(pattern):
	return len(re.findall(pattern, html))


checks = {
	"KPI 卡片": count(r'class="ug-kpi__card"'),
	"面板": count(r'class="ug-panel"'),
	"SVG 图表": count(r"<svg"),
	"图例条目": count(r'class="ug-legend__item"'),
	"排名条目": count(r'class="ug-rank__item"'),
	"重点客户条目": count(r'class="ug-accounts__item"'),
	"动态事件条目": count(r'class="ug-feed__item"'),
	"趋势柱状元素": count(r"<rect"),
	"趋势折线元素": count(r"<polyline|<path"),
}

for name, value in checks.items():
	print(f"  {name}: {value}")

numbers = re.findall(r'class="ug-kpi__number">([^<]+)<', html)
print("  KPI 数值:", numbers)
labels = re.findall(r'class="ug-kpi__label">([^<]+)<', html)
print("  KPI 名称:", labels)
caliber = re.search(r'class="ug-footer__caliber">([^<]*)<', html)
print("  底部口径:", (caliber.group(1) if caliber else "<空>")[:90])

errors = []
if checks["KPI 卡片"] != 6:
	errors.append(f"KPI 卡片数量应为 6，实际 {checks['KPI 卡片']}")
if checks["面板"] != 5:
	errors.append(f"面板数量应为 5，实际 {checks['面板']}")
if checks["SVG 图表"] < 5:
	errors.append(f"SVG 图表过少：{checks['SVG 图表']}")
if checks["趋势柱状元素"] == 0 or checks["趋势折线元素"] == 0:
	errors.append("趋势图没有渲染出柱状/折线元素")
if len(numbers) != 6 or any(value.strip() in ("", "–") for value in numbers):
	errors.append(f"KPI 数值缺失：{numbers}")
if "ug-panel-error" in html:
	errors.append("存在面板级错误提示")
if 'data-state="error"' in html:
	errors.append("整屏处于错误状态")
if "数据加载失败" in html or "前端资源加载失败" in html:
	errors.append("页面出现加载失败提示")
if not caliber or "在服口径" not in caliber.group(1):
	errors.append("底部口径说明未写入")

if errors:
	print("FAILED:")
	for item in errors:
		print("  -", item)
	sys.exit(1)
	print("  -> 大屏渲染自检通过（结构、图表、数值、状态、口径说明均正常）")
PY

echo "== 布局自检（缩放、溢出、滚动条） =="
python3 - "${WORK}/dom.html" <<'PY'
import json
import re
import sys

html = open(sys.argv[1], encoding="utf-8").read()
match = re.search(r'id="ug-layout-diagnostics"[^>]*>([^<]+)<', html)
if not match:
	print("  FAILED: 没有拿到布局自检数据")
	sys.exit(1)

data = json.loads(match.group(1))
print("  " + json.dumps(data, ensure_ascii=False))

errors = []
if data["scale"] <= 0:
	errors.append("缩放比例异常")
if abs(data["canvasWidth"] - 1920 * data["scale"]) > 2:
	errors.append("画布宽度与缩放不匹配（可能没有等比缩放）")
if data["overflowElements"] > 0:
	errors.append(f"{data['overflowElements']} 个元素超出画布边界")
if data["documentHeight"] > data["viewport"][1] + 2:
	errors.append("出现纵向滚动条（设计目标是无滚动条）")
if data["svgCount"] < 5:
	errors.append("图表数量不足")
if data["clippedPanels"]:
	errors.append(f"面板内容被裁切：{data['clippedPanels']}")
weak = [item for item in data.get("contrast", []) if (item["ratio"] or 0) < item["min"]]
if weak:
	errors.append(f"文字对比度不足：{weak}")
background = data.get("backgroundLuminance", {})
if (background.get("screen") or 0) < 0.6:
	errors.append(f"页面底色不够亮（亮度 {background.get('screen')}），当前不是亮色主题")
if (background.get("panel") or 0) < 0.75:
	errors.append(f"面板底色不够亮（亮度 {background.get('panel')}）")

if errors:
	print("FAILED:")
	for item in errors:
		print("  -", item)
	sys.exit(1)
print("  -> 布局自检通过：等比缩放正常、无元素溢出、无滚动条")
PY
