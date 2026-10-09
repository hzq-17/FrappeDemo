# Frappe 自定义应用：用户服务开通 / 流失管理与增长分析

一个用 Docker 一键跑起来的 Frappe v15 自定义应用（`user_growth`），交付三件事：

1. **单据**：用户服务开通 / 流失信息（DocType，含 24 个月 mock 数据）
2. **报表**：用户增长与流失分析（Script Report，支持筛选、分组透视、图表、导出）
3. **页面**：用户增长数据大屏（Page，全屏投屏、自动刷新、多分辨率适配）

配套文档在 [`docs/`](docs/)：需求分析、可行性分析、详细设计。

---

## 一、环境要求

| 项 | 要求 |
| --- | --- |
| Docker | Docker Desktop（Linux 容器）+ Docker Compose v2 |
| 内存 | 建议 ≥ 8GB 可用（MariaDB + Redis + bench） |
| 磁盘 | 首次构建约需 8~12GB（含系统包、Python/Node 依赖） |
| 网络 | 首次构建需要联网拉取依赖；镜像内已包含全部运行时，构建完成后可**断网演示** |

> Frappe 官方不支持 Windows 原生运行，因此本项目通过 Docker 承载；
> Windows 上请确保 Docker Desktop 使用 WSL2 后端并已启动。

## 二、一键启动

```bash
# 1. 准备环境变量（首次）
cp .env.example .env        # 本机已提供可直接使用的 .env

# 2. 构建镜像并启动全部服务（首次约 10~25 分钟，取决于网络）
docker compose up -d --build

# 3. 跟踪启动日志（首次会创建站点、安装应用、生成 8000 条演示数据）
docker compose logs -f bench
```

看到 `启动 bench：web=http://localhost:8000` 后即可访问：

| 交付物 | 地址 |
| --- | --- |
| 增长大屏 | http://localhost:8000/app/growth-dashboard （加 `?full=1` 直接沉浸模式） |
| 增长报表 | http://localhost:8000/app/query-report/用户增长与流失分析 |
| 服务单据 | http://localhost:8000/app/user-service-record |

默认账号：`Administrator` / `admin`（可用 `.env` 中的 `ADMIN_PASSWORD` 修改）。

## 三、网络受限环境的处理（本项目实测路径）

本机（中国大陆网络 + 本机代理 127.0.0.1:7897）实测：Docker Hub、GitHub、npm 官方源不可直连，
PyPI 与国内镜像站可用。`.env` 中已按此配置：

| 变量 | 作用 | 本机取值 |
| --- | --- | --- |
| `BASE_IMAGE` / `MARIADB_IMAGE` / `REDIS_IMAGE` | 基础镜像来源 | `docker.m.daocloud.io/library/...` |
| `APT_MIRROR` | Debian 软件源 | `mirrors.tuna.tsinghua.edu.cn` |
| `PIP_INDEX_URL` | Python 包源 | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `NPM_REGISTRY` | Node 包源 | `https://registry.npmmirror.com` |
| `BUILD_HTTP_PROXY` / `BUILD_HTTPS_PROXY` | **仅用于构建期 `git clone` frappe 源码** | `http://host.docker.internal:7897` |

> 关键细节：这两个代理变量**故意不叫** `HTTP_PROXY`/`HTTPS_PROXY`。
> Docker/BuildKit 会把同名的参数当作"预定义代理参数"注入到**每一个**构建步骤，
> 导致 apt/pip 也走代理而变慢（实测 apt 下载从 30MB/min 掉到 3MB/min）。
> 改成自定义名字后，只有 `git clone` 走代理，其余走国内镜像直连。

如果换到能直连 GitHub 的网络，把这两个变量留空即可；`docker.m.daocloud.io` 前缀也可换回官方镜像名。

## 四、日常使用

```bash
docker compose ps                      # 查看服务状态
docker compose logs -f bench           # 跟踪 bench 日志
docker compose restart bench           # 重启（幂等，不会重复建站/重复灌数据）
docker compose exec bench bash         # 进入容器
docker compose down                    # 停止（保留数据卷）
docker compose down -v                 # 停止并删除数据（站点与数据库一起清空）
```

容器内常用命令：

```bash
cd /home/frappe/frappe-bench

# 数据：重新生成（先清理旧的模拟数据，不影响手工录入的数据）
bash /workspace/tools/seed.sh                 # 幂等；MONTHS=12 RESET=1 可调

# 数据质量自检（10 项断言：日期合法性、枚举受控、生命周期不重叠、趋势合理性…）
bash /workspace/tools/quality_check.sh

# 单元测试
bench --site growth.local run-tests --app user_growth

# 前端资源重建（改了 CSS/JS 后；开发者模式下 bench watch 通常会自动重建）
bench build --app user_growth
```

## 五、自动化验证（无需人工点页面）

四段验证脚本覆盖"数据 → 接口 → 口径 → 视觉"四层，全部在容器内执行、不依赖人工操作。

```bash
# 1. 数据质量自检（10 项断言）
docker compose exec bench bash -lc "/workspace/tools/quality_check.sh"

# 2. 接口冒烟 + 报表与大屏口径一致性
docker compose exec bench bash -lc "/workspace/tools/verify_http.sh"

# 3. 大屏渲染与布局自检（headless chromium；含溢出/裁切/滚动条检查）
docker compose exec bench bash -lc "/workspace/tools/verify_preview.sh"
docker compose exec bench bash -lc "SIZE=3840x2160 /workspace/tools/verify_preview.sh"

# 4. Desk 页面白屏自检（页面骨架 / 模板注册顺序 / 挂载点 / 脚本语法 / 资源清单）
docker compose exec bench bash -lc "/workspace/tools/verify_page.sh"

# 5. 浏览器级渲染"真实页面脚本"（headless chromium，断言 6 KPI / 5 面板 / 6 图表）
docker compose exec bench bash -lc "/workspace/tools/verify_desk_page.sh"

# 6. 导出数据快照并生成截图（1920×1080 与 4K）
docker compose exec bench bash -lc "/workspace/tools/preview.sh"

# 7. 缓存与粒度矩阵（切粒度不再变空：8 范围 × 5 粒度 + 缓存命名空间隔离）
docker compose exec bench bash -lc "/workspace/tools/verify_cache.sh"
docker compose exec bench bash -lc "/workspace/tools/verify_trend_matrix.sh"
```

截图产物在 `tools/preview/screenshot-1920x1080.png` 与 `screenshot-3840x2160.png`。
离线预览页（`tools/preview/index.html`）复用与正式页面完全相同的前端资源，
只把 `frappe.call` 换成读取 JSON 快照的垫片，因此截图可直接用于视觉核对。

实测结果（本机 Docker 环境）：

| 项目 | 结果 |
| --- | --- |
| 演示数据 | 7,855 条 / 24 个月 / 质量自检 10 项全通过 |
| 单元测试 | 51 项全部通过 |
| 大屏接口 | HTTP 200，0.29s |
| 报表接口 | HTTP 200，0.18s，16 列 × 12 行 |
| 报表 vs 大屏 | 同一区间：新增 1396=1396、流失 731=731、期末在服 4838=4838 |
| 大屏布局 | 1920 与 4K 下均无溢出、无裁切、无滚动条 |
| Desk 页面 | 页面骨架 / 模板注册顺序 / 挂载点 / 脚本语法 / 资源清单 全部通过；headless 渲染真实页面脚本得到 6 KPI / 5 面板 / 6 图表 |

## 六、仓库结构

```
.
├── docker-compose.yml          # mariadb + redis(cache/queue) + bench
├── docker/
│   ├── Dockerfile              # Debian bookworm + bench + frappe v15
│   └── entrypoint.sh           # 幂等启动：建站 → 装应用 → 构建资源 → 灌数据 → 启动
├── user_growth/                # 自定义应用（挂载进容器，改完即生效）
│   └── user_growth/
│       ├── analytics/          # ★ 口径层：指标唯一实现
│       ├── api/                # 白名单接口（大屏取数）
│       ├── seed/               # mock 数据生成 + 质量自检
│       ├── growth_analytics/   # doctype / report / page / workspace
│       ├── public/             # CSS + 零依赖 SVG 图表 + 大屏脚本
│       └── tests/              # 单元测试
├── tools/                      # 离线预览页 + 截图脚本
└── docs/                       # 需求分析 / 可行性分析 / 详细设计
```

## 七、常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `docker compose up` 卡在拉取镜像 | Docker Hub 不可达：改用 `.env` 里的国内镜像前缀 |
| 构建时 `git clone` 失败 | GitHub 不可达：设置 `BUILD_HTTP_PROXY`/`BUILD_HTTPS_PROXY` 指向本机代理 |
| 浏览器打开显示 `site not found` | 请在容器内执行 `bench --site growth.local set-config host_name http://localhost:8000`，或直接用 `localhost` 访问（entrypoint 已建立站点别名） |
| 大屏白屏、控制台报 404 | 前端资源未构建：`bench build --app user_growth`（页面脚本本身有兜底加载逻辑） |
| 大屏空白且控制台无报错 | 页面骨架来自 `page/growth_dashboard/growth_dashboard.html`（框架会注册成 JS 模板）；该文件缺失或含 ASCII 单引号都会直接白屏 —— 用 `tools/verify_page.sh` 一条命令定位 |
| 报表表头下面多出一行输入框 | 那是 `frappe-datatable` 的行内筛选行（框架默认 `inlineFilters: true`）；本项目已在报表 JS 的 `get_datatable_options` 里关掉，硬刷新即可 |
| 大屏 404 或资源 404（文件名带 hash） | `bench build` 产物带内容 hash，必须通过 `assets.json` 解析；本项目已在 `hooks.py` 用 `app_include_js` 声明逻辑名，改完 hooks 后需重启容器 |
| `bench execute user_growth.xxx` 报 `NameError: user_growth` | 该命令用 `eval` 求值，只认识 `frappe` 根模块；改用 `bash /workspace/tools/seed.sh` 等脚本入口 |
| 大屏无数据 | 未生成数据或时间范围内无数据：执行 seed 或切换时间范围 |
| 报表与大屏数字不一致 | 两者共用同一实现；请确认筛选条件（时间范围、粒度、口径）完全一致 |
| 修改代码不生效 | 开发者模式已开启，但前端资源需要重建：`bench build --app user_growth`；后端改动会自动重载 |

## 八、设计要点（为什么这么做）

1. **一张单据承载完整生命周期**：一行 = 一个客户的一段服务（开通 → 流失），
   期末在服数就是一个条件表达式，而不是累计去重；唤回用户通过"生命周期序号"表达，
   既不丢业务事实，也不牺牲查询性能。
2. **口径只有一处实现**：`analytics/metrics.py` 同时服务报表与大屏。
   「报表说新增 812、大屏说 806」这类事故在这套结构下不可能发生。
3. **存量用日增量递推精确还原**：`在服(d) = 在服(d-1) + 当日新增 − 当日流失`，
   一次基准查询即可精确算出每一天的在服数与日均在服（不是近似），
   因此"平均在服"口径也可以精确提供。
4. **零依赖前端**：大屏的图表是自绘 SVG（约 300 行），换来的是完全离线可用、
   视觉令牌可控、无第三方许可与版本风险。
5. **数据可讲出结论**：mock 数据带季节性、渠道质量差异、套餐分层与唤回行为，
   不是均匀随机数，因此演示时能支撑"数据 → 结论"的完整叙事。
