# Bias 版图入口

本目录根层的 `serdes_*.mag`、`.tcl` 和 `*_ref.spice` 是历史 Gemini 来件。旧说明宣称已完整实现带隙、镜像及匹配指标，但缺少对应的独立验收，不能据此给当前电路授予物理或性能资格。

旧 `build_bandgap_suite.py` 与 `bias_layout_suite_overview.png` 已退役；原 README 的尺寸表、匹配和隔离声明也一并保留在[清单](../../../../results/catalog/retired_layout_suites_20261117.json)中。原因、依赖检查和追溯方法见[审查记录](../../../../docs/history/legacy_layout_retirement_20261117.md)。根层几何保留作审计输入，非当前推荐版图。

后续 PDK 迭代放在 `variants/`，候选目录存在不表示已被采用。当前电路与适用边界见[Bias 设计](../../../../docs/design/bias.md)，项目采用状态见[当前状态](../../../../docs/status/current.md)。本轮只整理旧产物，没有复核或改变新候选的资格。
