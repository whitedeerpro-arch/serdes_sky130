# WP-004 交接

改动：`verification/work_packages/wp004_ingress_windows.py`、`tests/test_ingress_windows.py`、本目录 `evidence.json`、`summary.md`、`handoff.md`。脚本只生成 evidence，不重写输入 card。

已执行（退出码均为 0）：

- `uv run python verification/work_packages/wp004_ingress_windows.py --output docs/work_packages/deliveries/WP-004`
- `uv run pytest -q tests/test_ingress_windows.py`（3 passed，含实测浮点零余量及小于最小窗口 1e-6 ps 的回归）
- `uv run python -m serdes_flow.work_packages check WP-004`

未运行 ngspice、动态仿真或联网；未修改 DUT、共享库、中央索引或当前设计文档，未提交。请 reviewer 核对两个延迟字段的区间及单位、相位符号、端点 Sample 关系、输入哈希和缺失角限制。真实更新窗、字时钟电路与跨字行为仍待提供或验证；本交付不作架构采用结论。
