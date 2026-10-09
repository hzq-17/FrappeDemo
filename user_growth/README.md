# 用户增长分析（user_growth）

Frappe v15 自定义应用，包含三项交付物：

| # | 交付物 | 类型 | 位置 |
| --- | --- | --- | --- |
| 1 | 用户服务开通 / 流失信息单据（含 mock 数据） | DocType | `user_growth/growth_analytics/doctype/user_service_record/` |
| 2 | 用户增长与流失分析报表 | Report | `user_growth/growth_analytics/report/user_growth_analysis/` |
| 3 | 用户增长数据大屏 | Page | `user_growth/growth_analytics/page/growth_dashboard/` |

## 快速开始（在 bench 环境中）

```bash
# 1. 安装应用
bench --site growth.local install-app user_growth

# 2. 构建前端资源
bench build --app user_growth

# 3. 生成演示数据（幂等；已存在的数据会自动跳过）
bash /workspace/tools/seed.sh

# 4. 启动（开发者模式下修改代码无需重启）
bench start
```

访问：

- 单据：`/app/user-service-record`
- 报表：`/app/query-report/用户增长与流失分析`
- 大屏：`/app/growth-dashboard`（`?full=1` 直接进入沉浸模式）

## 常用命令

> 注意：`bench execute user_growth.xxx` 在本版 bench 下不可用——该命令用 `eval`
> 求值，命名空间里只有 `frappe` 根模块。下面统一用"带站点上下文的脚本"入口。

```bash
# 重新生成数据（先清理旧的"模拟数据"，不影响手工录入的数据）
bash /workspace/tools/seed.sh            # 默认 24 个月
MONTHS=12 RESET=1 bash /workspace/tools/seed.sh

# 调整随机种子（保证可复现）
SEED=20260909 bash /workspace/tools/seed.sh

# 数据质量自检
bash /workspace/tools/quality_check.sh

# 单元测试（校验规则、时间桶、指标恒等式）
bench --site growth.local run-tests --app user_growth

# 导出大屏数据快照 + 生成截图（离线视觉验证）
bash /workspace/tools/preview.sh

# HTTP 冒烟测试（登录 / 大屏接口 / 报表接口 / 口径一致性 / 静态资源 / 路由）
bash /workspace/tools/verify_http.sh
```

## 代码结构（为什么这样分层）

```
user_growth/user_growth/
├── analytics/       ← 口径层：指标的唯一实现（报表与大屏共用，杜绝"两处各写一套 SQL"）
│   ├── constants.py    枚举字典（字段选项、图表图例都从这里取）
│   ├── rules.py        派生规则与校验规则（纯函数，可单独单测）
│   ├── periods.py      时间粒度与时间桶（连续、无重叠、日历对齐）
│   └── metrics.py      指标计算（期间计数 + 时点存量 + 分布 + 榜单）
├── api/              ← 编排层：白名单接口（权限校验 + 缓存 + 参数校验）
├── seed/             ← 数据准备：参数化生成、幂等写入、质量自检
├── growth_analytics/ ← Frappe 模块（doctype / report / page / workspace）
├── public/           ← 前端资源（CSS + 零依赖 SVG 图表 + 大屏脚本）
└── tests/            ← 单元测试
```

## 指标口径（摘要）

- 在服用户：`开通日期 <= 时点 < 流失日期`（区间重叠法，流失当天视为已不在服）
- 新增 / 流失：开通日期 / 流失日期落在统计区间内
- 净增长 = 新增 − 流失；期末在服 = 期初在服 + 新增 − 流失（已用单测锁定）
- 流失率 = 流失数 ÷ 分母（分母可选「期初在服」或「平均在服」，界面显式标注）
- MRR = 合同金额 ÷ 计费月数；免费套餐为 0
- 报表与大屏共用同一实现，因此两处数字必然一致

## 设计文档

仓库 `docs/` 目录：需求分析、可行性分析、详细设计。
