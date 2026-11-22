# 模块设计文档索引（`docs/design/`）

项目级采用状态与验证数字唯一汇总见 [current.md](../status/current.md)，执行队列见 [prelayout_plan.md](../status/prelayout_plan.md)，修订线与源文件见 [revisions.md](../overview/revisions.md)。本目录保存各模块原理、尺寸推导、边界与局部验证记录。

## PLL 与时钟
- **核心与环路**：[pll_loop.md](pll_loop.md) · [r6_lock_confirmation.md](r6_lock_confirmation.md) · [r6_mainline_review.md](r6_mainline_review.md) · [pll_cp_window.md](pll_cp_window.md) · [pll_cp_v4.md](pll_cp_v4.md)（1/4 副本主动伺服 + 宽摆幅 PDK 候选）· [pll_coarse_windows.md](pll_coarse_windows.md)
- **VCO 与电容阵列**：[pll_vco.md](pll_vco.md) · [pll_vco_r6_ptat.md](pll_vco_r6_ptat.md)（融合 BIAS v2 PTAT 尾流温补，45/45 跨三温单码候选）· [r6_map_audit.md](r6_map_audit.md) · [vco_bank_optimization.md](vco_bank_optimization.md)
- **分频器与时钟接收**：[pll_divider.md](pll_divider.md)（主线 r3 CML ÷8）· [pll_sync_prescaler8.md](pll_sync_prescaler8.md)（2-Stack 同步 CML 候选）· [pll_tspc_reclock_divider.md](pll_tspc_reclock_divider.md)（纯 CMOS Equalized Nikolic SAFF-TSPC 重定时候选）· [clock_receiver.md](clock_receiver.md)（CML→CMOS）· [ref_amp.md](ref_amp.md)
- **供电与纹波预算**：[pll_ripple_budget.md](pll_ripple_budget.md) · [pll_supply_options.md](pll_supply_options.md) · [pll_supply_variants.md](pll_supply_variants.md) · [pll_timing_supply_review.md](pll_timing_supply_review.md)

## Bias、LDO 与监控
- **带隙与偏置**：[bias.md](bias.md) · [bias_cap_review.md](bias_cap_review.md) · [bias_v2.md](bias_v2.md)（单级 FC-OTA + 真 CMOS `ref_pbuf` + 集成 `bias_top` 候选）· [physical_reference_card.md](physical_reference_card.md) · [monitor.md](monitor.md)
- **LDO（HV18 r4、减容与 v2 重构候选）**：[ldo_r4.md](ldo_r4.md) · [ldo_smallcap.md](ldo_smallcap.md) · [ldo_cap_area.md](ldo_cap_area.md) · [ldo_v2.md](ldo_v2.md) · [ldo.md](ldo.md)

## TX（字入口、时钟分发、串化与线驱动）
- **整链与主入口**：[tx_parallel_serializer.md](tx_parallel_serializer.md) · [tx_final_retime.md](tx_final_retime.md) · [tx_sst_v4.md](tx_sst_v4.md)（去 CML 四相 N-over-N SST 独立候选）· [tx_clock_distribution.md](tx_clock_distribution.md) · [tx_serializer.md](tx_serializer.md) · [tx_output_driver.md](tx_output_driver.md)
- **字入口与保持时序**：[tx_ingress.md](tx_ingress.md) · [tx_word_capture.md](tx_word_capture.md) · [tx_launch_hold.md](tx_launch_hold.md)
- **缓冲与负载专题**：[tx_buffer_sizing.md](tx_buffer_sizing.md) · [tx_buffer_local.md](tx_buffer_local.md) · [tx_buffer_cascade.md](tx_buffer_cascade.md) · [tx_buffer_heavy.md](tx_buffer_heavy.md) · [tx_cml_amplitude.md](tx_cml_amplitude.md) · [tx_coupling_state.md](tx_coupling_state.md) · [tx_loaded_clock.md](tx_loaded_clock.md) · [tx_physical_load_card.md](tx_physical_load_card.md) · [tx_relative_timing_screen.md](tx_relative_timing_screen.md) · [tx_retime_demand.md](tx_retime_demand.md)

## RX 与信道
- **前端、PI、采样与数字**：[rx_frontend.md](rx_frontend.md) · [rx_pi_sampler.md](rx_pi_sampler.md) · [rx_cmos_v2.md](rx_cmos_v2.md)（去 CML 四分之一速 Double-Tail + 2 GHz CMOS PI + 纯 CMOS 解串，45/45 端到端独立候选）· [rx_cdr_digital.md](rx_cdr_digital.md) · [rx_cold_convergence.md](rx_cold_convergence.md) · [rx_word_host_timing.md](rx_word_host_timing.md) · [rx_host_cdc.md](rx_host_cdc.md)
- **信道**：[channel_model.md](channel_model.md)

## 公共器件与跨模块专题
- [digital_top_v3.md](digital_top_v3.md)（统一精简 SKY130A 数字顶层宏 P&R 与 3 角 OpenRCX/DRC/LVS 签核）· [cml_swing_target.md](cml_swing_target.md) · [fixed_load_resistors.md](fixed_load_resistors.md) · [fixed_poly_ac_overlay.md](fixed_poly_ac_overlay.md) · [wide_load_planning.md](wide_load_planning.md) · [power_audit.md](power_audit.md)
