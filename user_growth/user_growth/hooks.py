app_name = "user_growth"
app_title = "用户增长分析"
app_publisher = "Frappe Demo"
app_description = "用户服务开通/流失信息管理与增长分析（单据 + 报表 + 大屏）"
app_email = "demo@example.com"
app_license = "mit"
app_version = "1.0.0"

# ---------------------------------------------------------------------------
# 安装钩子
#   安装应用后自动准备一批演示数据（24 个月、约 8000 条，幂等）。
#   失败不会中断安装，可随时手动重跑：
#     bench --site <site> execute user_growth.seed.runner.run_cli
#   如需跳过：bench --site <site> set-config user_growth_skip_demo_data 1
# ---------------------------------------------------------------------------
after_install = "user_growth.seed.runner.after_install"

# ---------------------------------------------------------------------------
# 静态资源
#   大屏前端模块以 bundle 方式打包（public/js/user_growth.bundle.js，约 53KB/未压缩）。
#   Frappe 会给 bundle 产物加上内容 hash，因此必须通过 manifest 引用，
#   最稳妥的方式就是在 hooks 里声明（框架自动解析成 /assets/.../xxx.bundle.<hash>.js）。
#   该 bundle 只做命名空间挂载，不做任何渲染，注入到 Desk 页面开销可忽略。
# ---------------------------------------------------------------------------
app_include_js = "user_growth.bundle.js"

# ---------------------------------------------------------------------------
# 权限（行级）扩展位：按大区隔离数据范围时在此挂 permission_query_conditions
# ---------------------------------------------------------------------------
