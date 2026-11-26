# 模块设计文档索引（`docs/design/`）

项目级采用状态与验证数字唯一汇总见 [current.md](../status/current.md)，片级版图与 PDN 规划见 [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md)，修订线与源码身份见 [revisions.md](../overview/revisions.md)。

本目录按 **当前 4 Gb/s 发布主线（CMOS/SST TX & RX + 2 GHz 环振 PLL）** 与 **历史 CML 演进与专题参考** 清晰分组，便于快速定位现行设计依据并保留完整设计演进追溯。

---

## 一、4 Gb/s 发布主线

| 子系统 | 设计与证据入口 |
|---|---|
| PLL v4 | [r6/PTAT 码窗](pll_vco_r6_ptat.md) · [相噪与闭环边界](pll_vco_r6_perf.md) · [CP v4/v4.1](pll_cp_v4.md) · [SAFF-TSPC ÷8](pll_tspc_reclock_divider.md) · [时钟接收器](clock_receiver.md) |
| 电源与偏置 | [HV18 LDO v2/v2_cur](ldo_v2.md) · [BIAS v2](bias_v2.md) |
| 发送端 | [TX SST v4.3](tx_sst_v4.md) |
| 接收端 | [CMOS RX v2.2](rx_cmos_v2.md) |
| 数字 | [统一数字顶层 v3.1](digital_top_v3.md) |
| 信道与监控 | [合成 PCB 信道族](channel_model.md) · [辅助监测](monitor.md) |

## 二、历史 CML 演进与设计推导参考（Legacy CML & Studies）

以下文档保留从早期全 CML 架构向 4 Gb/s CMOS/SST TX & RX 主线架构演进过程中的器件物理校准、尺寸模型、局部实验与边界教训，均以原始修订身份留存：

- **PLL 历史研究与早期分频/供电方案**：[r6_lock_confirmation.md](r6_lock_confirmation.md) · [r6_mainline_review.md](r6_mainline_review.md) · [r6_map_audit.md](r6_map_audit.md) · [vco_bank_optimization.md](vco_bank_optimization.md) · [pll_coarse_windows.md](pll_coarse_windows.md) · [pll_cp_window.md](pll_cp_window.md) · [pll_divider.md](pll_divider.md)（早期 r3 CML ÷8）· [pll_sync_prescaler8.md](pll_sync_prescaler8.md)（2-Stack 同步 CML ÷8）· [ref_amp.md](ref_amp.md) · [pll_ripple_budget.md](pll_ripple_budget.md) · [pll_supply_options.md](pll_supply_options.md) · [pll_supply_variants.md](pll_supply_variants.md) · [pll_timing_supply_review.md](pll_timing_supply_review.md)
- **Bias & LDO 早期版本与减容推导**：[bias.md](bias.md) · [bias_cap_review.md](bias_cap_review.md) · [physical_reference_card.md](physical_reference_card.md) · [ldo.md](ldo.md) · [ldo_r4.md](ldo_r4.md) · [ldo_smallcap.md](ldo_smallcap.md) · [ldo_cap_area.md](ldo_cap_area.md)
- **早期 CML TX 系列（v3/extra5 串化、重定时与时钟树模型）**：[tx_parallel_serializer.md](tx_parallel_serializer.md) · [tx_final_retime.md](tx_final_retime.md) · [tx_clock_distribution.md](tx_clock_distribution.md) · [tx_serializer.md](tx_serializer.md) · [tx_output_driver.md](tx_output_driver.md) · [tx_ingress.md](tx_ingress.md) · [tx_word_capture.md](tx_word_capture.md) · [tx_launch_hold.md](tx_launch_hold.md) · [tx_buffer_sizing.md](tx_buffer_sizing.md) · [tx_buffer_local.md](tx_buffer_local.md) · [tx_buffer_cascade.md](tx_buffer_cascade.md) · [tx_buffer_heavy.md](tx_buffer_heavy.md) · [tx_cml_amplitude.md](tx_cml_amplitude.md) · [tx_coupling_state.md](tx_coupling_state.md) · [tx_loaded_clock.md](tx_loaded_clock.md) · [tx_physical_load_card.md](tx_physical_load_card.md) · [tx_relative_timing_screen.md](tx_relative_timing_screen.md) · [tx_retime_demand.md](tx_retime_demand.md)
- **早期 CML RX 与数字接口演进**：[rx_frontend.md](rx_frontend.md) · [rx_pi_sampler.md](rx_pi_sampler.md) · [rx_cdr_digital.md](rx_cdr_digital.md) · [rx_cold_convergence.md](rx_cold_convergence.md) · [rx_word_host_timing.md](rx_word_host_timing.md) · [rx_host_cdc.md](rx_host_cdc.md)
- **公共器件、电阻与功耗研究**：[cml_swing_target.md](cml_swing_target.md) · [fixed_load_resistors.md](fixed_load_resistors.md) · [fixed_poly_ac_overlay.md](fixed_poly_ac_overlay.md) · [wide_load_planning.md](wide_load_planning.md) · [power_audit.md](power_audit.md)
