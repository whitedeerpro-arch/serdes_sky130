# LDO 版图入口

本目录根层的 `serdes_*.mag`、`.tcl` 和 `*_ref.spice` 是历史 Gemini 来件。首轮独立提取发现旧 HV18 核心得到普通 1.8 V MOS，32 颗 MIM 两端同网，full-rule DRC 为 911 个区域；旧慢滤波器的 16 颗 MIM 也两端短接。证据见[首轮复核索引](../../../../results/catalog/layout_gemini_review.json)。旧 README 的“生产级”、5 V/native 器件和压降声明不成立。

旧 `build_ldo_suite.py` 与 `ldo_layout_suite_overview.png` 已退役，原 README 同时归档。[退役清单](../../../../results/catalog/retired_layout_suites_20261117.json)保留文件身份，[审查记录](../../../../docs/history/legacy_layout_retirement_20261117.md)说明原因与恢复方法。根层几何保留作审计输入，非当前推荐版图。

[PDK MIM 阵列](variants/mim_pdk/README.md)是单独生成并检查的迭代，其资格不能转移给旧整包或整个 LDO。其他后续候选放在 `variants/`，按各自证据审阅。当前电路与边界见[LDO 设计](../../../../docs/design/ldo_r4.md)，采用状态见[当前状态](../../../../docs/status/current.md)；本轮没有重跑或重新验收 LDO。
