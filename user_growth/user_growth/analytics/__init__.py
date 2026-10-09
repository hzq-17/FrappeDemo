"""口径层：所有指标的唯一实现。

报表（report/user_growth_analysis）与大屏（api/growth_screen）都从这里取数，
保证"同一个指标只有一套算法"，避免报表与大屏数字对不上。

注意：这里不做 eager import，保证 constants / periods / rules 这些纯逻辑模块
可以在没有 Frappe 运行时的环境里被单独测试。
"""

__all__ = ["constants", "metrics", "periods", "rules"]
