# 增长大屏 · 离线预览

这个目录用于**在没有 Frappe 会话的情况下**验证大屏的视觉效果（布局、配色、图表、字号）。
它复用与正式页面完全相同的前端资源：

- `user_growth/user_growth/public/css/growth_screen.css`
- `user_growth/user_growth/public/js/growth_screen/*.js`

唯一的差别是把 `frappe.call` 换成了读取 `dashboard.json` 快照的垫片。

## 用法

1. 在容器内导出真实数据快照（命令会写入本目录的 `dashboard.json`）：

   ```bash
   docker compose exec bench bash -lc \
     "bench --site growth.local execute user_growth.seed.runner.dump_preview_snapshot"
   ```

2. 起一个静态服务（浏览器不允许 `file://` 下 fetch 本地 json）：

   ```bash
   cd /workspace && python3 -m http.server 8899
   ```

   然后访问 http://localhost:8899/tools/preview/

3. 生成截图（容器内已安装 headless chromium）：

   ```bash
   docker compose exec bench bash -lc "SIZE=1920x1080 /workspace/tools/screenshot.sh"
   ```

   输出：`tools/preview/screenshot-1920x1080.png`（也支持 4K：`SIZE=3840x2160`）。

