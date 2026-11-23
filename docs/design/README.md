# 模块设计文档索引（`docs/design/`）

项目级采用状态与验证数字唯一汇总见 [current.md](../status/current.md)，片级版图与 PDN 规划见 [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md)，修订线与源码身份见 [revisions.md](../overview/revisions.md)。

本目录按 **当前 4 Gb/s Zero-CML 发布主线** 与 **历史 CML 演进与专题参考** 清晰分组，便于快速定位现行设计依据并保留完整设计演进追溯。

---

## 一、当前 4 Gb/s Zero-CML 发布主线（Active Release）

### 1. PLL v4 与时钟子系统
- **VCO r6 + PTAT 偏置与相噪/抖动标定**：[pll_vco_r6_ptat.md](pll_vco_r6_ptat.md)（融合 BIAS v2 PTAT 尾流温补，45/45 跨三温单码）· [pll_vco_r6_perf.md](pll_vco_r6_perf.md)（`28/66` + `sym9_clean` CPEX 八相正交误差 `≤ 0.76 ps`、相噪与 PLL v4 抖动 `1.91 ps` TT / `2.29 ps` 最差）· [pll_vco.md](pll_vco.md)（r6 5-bit 31 单元环振核心与量程基础）
- **电荷泵与环路滤波器**：[pll_cp_v4.md](pll_cp_v4.md)（1/4 副本主动伺服 + 宽摆幅 PDK 签核 `v4_pdk`；v4.1 `up_wn=4.0` 进一步降毛刺至 −60 dBc）· [pll_loop.md](pll_loop.md)（PFD、环路稳定性、锁定检测与相位窗）
- **反馈分频器与时钟接收**：[pll_tspc_reclock_divider.md](pll_tspc_reclock_divider.md)（Equalized Nikolic SAFF-TSPC 重定时 ÷8，`saff_reclock_2g_pdk`）· [clock_receiver.md](clock_receiver.md)（`r5_pdk` 全速 CML→CMOS 转换与 250 MHz 反馈接收）

### 2. 电源与偏置子系统（LDO & BIAS）
- **HV18 LDO v2_cur**：[ldo_v2.md](ldo_v2.md)（Native-NMOS 安静供电域 `v2_cur_pdk`，`27,826 µm²`，满/轻载稳定性与 RCX 签核）
- **带隙与全局偏置 BIAS v2**：[bias_v2.md](bias_v2.md)（单级 FC-OTA + 真 CMOS `ref_pbuf` + 集成 `bias_top` `v2_pdk`，全 PVT/MC/RCX 签核）

### 3. TX Zero-CML SST 发送端（v4.3）
- **16:1 串化 + 4 相 N-over-N SST + 2-tap FFE**：[tx_sst_v4.md](tx_sst_v4.md)（`v4_pdk`，`34,026 µm²`，DRC=0/LVS=MATCH，22/22 RCX 后仿通过 `C2_loss6`）

### 4. RX Zero-CML CMOS 接收端（v2.2）
- **端接/CTLE + 2 GHz 64 码纯 CMOS PI + 四分之一速 Double-Tail 采样 + 8→32 解串**：[rx_cmos_v2.md](rx_cmos_v2.md)（`v2_pdk`，`47,932 µm²`，45/45 原理图端到端 + 3/3 CPEX 后仿 0 错码，PI 64 码 TT CPEX `|INL| = 0.0177 UI`）

### 5. 统一精简数字顶层宏（v3.1）
- **多速率数字顶层 P&R + 3 角 OpenRCX STA + 4 模式 VCS SDF GLS**：[digital_top_v3.md](digital_top_v3.md)（`103,932 µm²`，4,932 单元，6 时钟域全 MET，122,608 SVA 0 失败，`±300 ppm` 闭环 CDR）

### 6. 信道与监控
- **PCB 信道家族（C0–C5）**：[channel_model.md](channel_model.md)
- **辅助监测电路**：[monitor.md](monitor.md)

---

## 二、历史 CML 演进与设计推导参考（Legacy CML & Studies）

以下文档保留从早期全 CML 架构向 4 Gb/s Zero-CML 架构演进过程中的器件物理校准、尺寸模型、局部实验与边界教训，均以原始修订身份留存：

- **PLL 历史研究与早期分频/供电方案**：[r6_lock_confirmation.md](r6_lock_confirmation.md) · [r6_mainline_review.md](r6_mainline_review.md) · [r6_map_audit.md](r6_map_audit.md) · [vco_bank_optimization.md](vco_bank_optimization.md) · [pll_coarse_windows.md](pll_coarse_windows.md) · [pll_cp_window.md](pll_cp_window.md) · [pll_divider.md](pll_divider.md)（早期 r3 CML ÷8）· [pll_sync_prescaler8.md](pll_sync_prescaler8.md)（2-Stack 同步 CML ÷8）· [ref_amp.md](ref_amp.md) · [pll_ripple_budget.md](pll_ripple_budget.md) · [pll_supply_options.md](pll_supply_options.md) · [pll_supply_variants.md](pll_supply_variants.md) · [pll_timing_supply_review.md](pll_timing_supply_review.md)
- **Bias & LDO 早期版本与减容推导**：[bias.md](bias.md) · [bias_cap_review.md](bias_cap_review.md) · [physical_reference_card.md](physical_reference_card.md) · [ldo.md](ldo.md) · [ldo_r4.md](ldo_r4.md) · [ldo_smallcap.md](ldo_smallcap.md) · [ldo_cap_area.md](ldo_cap_area.md)
- **早期 CML TX 系列（v3/extra5 串化、重定时与时钟树模型）**：[tx_parallel_serializer.md](tx_parallel_serializer.md) · [tx_final_retime.md](tx_final_retime.md) · [tx_clock_distribution.md](tx_clock_distribution.md) · [tx_serializer.md](tx_serializer.md) · [tx_output_driver.md](tx_output_driver.md) · [tx_ingress.md](tx_ingress.md) · [tx_word_capture.md](tx_word_capture.md) · [tx_launch_hold.md](tx_launch_hold.md) · [tx_buffer_sizing.md](tx_buffer_sizing.md) · [tx_buffer_local.md](tx_buffer_local.md) · [tx_buffer_cascade.md](tx_buffer_cascade.md) · [tx_buffer_heavy.md](tx_buffer_heavy.md) · [tx_cml_amplitude.md](tx_cml_amplitude.md) · [tx_coupling_state.md](tx_coupling_state.md) · [tx_loaded_clock.md](tx_loaded_clock.md) · [tx_physical_load_card.md](tx_physical_load_card.md) · [tx_relative_timing_screen.md](tx_relative_timing_screen.md) · [tx_retime_demand.md](tx_retime_demand.md)
- **早期 CML RX 与数字接口演进**：[rx_frontend.md](rx_frontend.md) · [rx_pi_sampler.md](rx_pi_sampler.md) · [rx_cdr_digital.md](rx_cdr_digital.md) · [rx_cold_convergence.md](rx_cold_convergence.md) · [rx_word_host_timing.md](rx_word_host_timing.md) · [rx_host_cdc.md](rx_host_cdc.md)
- **公共器件、电阻与功耗研究**：[cml_swing_target.md](cml_swing_target.md) · [fixed_load_resistors.md](fixed_load_resistors.md) · [fixed_poly_ac_overlay.md](fixed_poly_ac_overlay.md) · [wide_load_planning.md](wide_load_planning.md) · [power_audit.md](power_audit.md)
