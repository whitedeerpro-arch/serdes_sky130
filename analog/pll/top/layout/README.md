# PLL 顶层版图入口

**当前没有有效的完整摆位方案，也没有当前 r6 完整布线宏及其提取网表。** [总审阅](../../../../docs/layout/pll_review_20261115.md)连接各子模块结论；CP、LDO 和 Bias 不在这次审阅范围。

依赖错误 `pll_vco_ring4_r6_pdk` 大环与四个外置 buffer 的规划脚本、坐标表和图片已撤销，不能再用于面积估算、走线或提取。逐文件记录见[撤销清单](../../../../results/catalog/obsolete_vco_large_ring_20261115.json)。原先的超长反馈路径和空白属于被撤销草案，不转移到现行方案。

后续须围绕 [sym9 内嵌四缓冲候选](../../vco/layout/variants/sym9_clean/README.md)、[÷8 清理候选](../../divider/layout/variants/review_clean/README.md)和[反馈接收器](../../../common/cml_to_cmos/layout/README.md)重新规划，核对端口映射、真实负载、三路轻 dummy、控制线与电源回流。子模块通过不代表整核性能通过。

根目录 `pll_core_r6k4q.mag` / `.tcl` 是更早导入的历史草案，未获当前 r6 整核资格。颜色不证明衬底隔离、护环或独立地已实现。
