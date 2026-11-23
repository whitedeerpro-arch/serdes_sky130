# PLL/PFD/CP/LF搭建

[返回图目录](../../../README.md)

本专题的图按用途与局部适用范围列出；当前设计版本由原报告及阶段/冻结清单判定。

| 图组 | 用途 | 适用范围／来源 |
|---|---|---|
| pfd_cmos_transfer [PNG](pfd_cmos_transfer.png) / [SVG](pfd_cmos_transfer.png) | 单元表征 | PFD脉宽与接口，不独立证明CP电荷或PLL捕获；[报告](../../../../history/pfd_cmos_results.md) |
| pfd_cmos_waveforms [PNG](pfd_cmos_waveforms.png) / [SVG](pfd_cmos_waveforms.png) | 单元表征 | PFD脉宽与接口，不独立证明CP电荷或PLL捕获；[报告](../../../../history/pfd_cmos_results.md) |
| pfd_cp_charge [PNG](pfd_cp_charge.png) / [SVG](pfd_cp_charge.png) | 局部联调 | PFD/CP/LF开环电荷与滤波响应；[报告](../../../../history/pfd_cp_lf_results.md) |
| pfd_cp_lf_response [PNG](pfd_cp_lf_response.png) / [SVG](pfd_cp_lf_response.png) | 局部联调 | PFD/CP/LF开环电荷与滤波响应；[报告](../../../../history/pfd_cp_lf_results.md) |
| pll_balanced_extraction [PNG](pll_balanced_extraction.png) / [SVG](pll_balanced_extraction.png) | 演进记录 | 首轮PLL调试，多种实现视图；逐图回到原报告判断范围；[报告](../../../../history/pll_first_debug.md) |
| pll_mixed_acquisition [PNG](pll_mixed_acquisition.png) / [SVG](pll_mixed_acquisition.png) | 演进记录 | 首轮PLL调试，多种实现视图；逐图回到原报告判断范围；[报告](../../../../history/pll_first_debug.md) |
| pll_transistor_first_response [PNG](pll_transistor_first_response.png) / [SVG](pll_transistor_first_response.png) | 演进记录 | 首轮PLL调试，多种实现视图；逐图回到原报告判断范围；[报告](../../../../history/pll_first_debug.md) |
| [宿主延迟及预算口径](pll_timing_supply_review.png) | 路径分拆与单位复核 | 7个局部DC工况的原始Kd复算；单PLL峰值/峰峰值和双PLL相对量分开；[报告](../../../../design/pll_timing_supply_review.md) |
| [参考副本的残余导数](pll_reference_replica_review.png) | 改进候选比较 | 7点×4负载原始交越独立复算；宿主导数减小，偏置项仍开；未作供电容限签核；[报告](../../../../design/pll_timing_supply_review.md#参考副本已看到的改进及剩余限制) |
