# 图目录：按用途阅读

PNG/SVG 为同一组的不同格式。图片已按模块／专题搬迁；本页整理阅读顺序和适用范围。[组织说明](../history/figure_organization.md)和[旧新路径映射](../data/figure_relocation_20261029.json)保留设计继承与溯源。

## 先看当前主线

- [VCO bank局部Pareto研究](layout/vco_bank_optimization.png)：实测叶目录、旧码包络与研究筛选条件，来源及适用边界见[优化研究](../design/vco_bank_optimization.md)。不表示完整环振或良率前沿。

- **[交互设计工作台](../../web/design/index.html)**：SerDes→TX/Bias/RX/PLL/Channel→子模块，边界、模型规划、迭代与证据挂在模块下；[本地运行与保存](../../web/design/README.md)。[静态图与预览](system/README.md)保留参考。
- **[TX入口与完整链路](tx/ingress/README.md)**：单元/分组保持/关闭竞争、完整TX的TT与FS对照眼图、guard映射时序可行性；FS失败与SS时序不足均保留。
- **[11-06 时钟链路图集](clocking/README.md)**：7 组新图，覆盖 VCO 135 条件选码/Kvco、3/4 bit 控制范围、CP 窗口、÷2 可行区、r5＋TX v3 原生联合仿真与计数波形；[来源与复现](../history/clocking_progress_20261106.md)。
- [当前模块设计](../design/)与[修订表](../overview/revisions.md)决定现行版本；[v0.1 PLL/TX 基线](../history/design_freeze_v0p1.md)保留历史参数与证据。
- [当前RX阶段结论](../history/stage_review_20261029.md)：按分层范围阅读，不能把局部窗口当作整个链路。
- [RX前端](../history/rx_frontend_first_design.md) → [加载边界](../history/rx_loaded_link.md) → [PI/采样](../history/rx_sampler_control.md) → [CDR/串并](../history/rx_cdr_closed_loop.md) → [实时数模接口](../history/mixed_signal_cosim.md)。这是一条开发阅读路线，后项不覆盖前项的全部工况。
- [串化器溯源](../history/serializer_timing_root_cause.md)解释最终末级驱动选型；较早1024bit物理时钟眼图仍使用旧锁存参数。

- [PLL首轮PVT与无源映射](../history/pll_pvt_first_results.md)：包含调谐/接口缺口，尚未通过全PVT签核。

## 如何读下面的分组

文件按模块/专题归属；用途另列。专项研究不自动次要，早期局部表征也不自动失效。标为“原理说明”的图不能当作电路验收。既有图的范围、当前/历史路径、报告、case 和继承边见[历史机器索引](../data/figure_catalog.json)；11-06 新增图见[本轮索引](../../results/catalog/clocking_progress_20261106.json)。

## 公共电平转换

当前目录：[common/level_conversion](common/level_conversion/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| cml_clock_receiver_waveforms [PNG](common/level_conversion/cml_clock_receiver_waveforms.png) / [SVG](common/level_conversion/cml_clock_receiver_waveforms.svg) | 接口表征 | 时钟接收器及VCO/分频接口；不能用作静态数据转换验收；[报告](../history/cml_clock_receiver_results.md) |

## VCO

当前目录：[clocking/vco](clocking/vco/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| vco_ring4_tt_tuning [PNG](clocking/vco/vco_ring4_tt_tuning.png) / [SVG](clocking/vco/vco_ring4_tt_tuning.svg) | 单元表征 | 早期四级环振固定偏置/调谐表征；最终参数以冻结版本为准；[报告](../history/vco_ring4_first_results.md) |
| vco_ring4_tt_waveforms [PNG](clocking/vco/vco_ring4_tt_waveforms.png) / [SVG](clocking/vco/vco_ring4_tt_waveforms.svg) | 单元表征 | 早期四级环振固定偏置/调谐表征；最终参数以冻结版本为准；[报告](../history/vco_ring4_first_results.md) |

## 分频架构探索

当前目录：[clocking/dividers](clocking/dividers/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| cml_divider_waveforms [PNG](clocking/dividers/cml_divider_waveforms.png) / [SVG](clocking/dividers/cml_divider_waveforms.svg) | 演进记录 | 早期全CML整数分频/四级链；当前默认只使用三级÷8；[报告](../history/cml_divider_results.md) |
| hybrid_divider_waveforms [PNG](clocking/dividers/hybrid_divider_waveforms.png) / [SVG](clocking/dividers/hybrid_divider_waveforms.svg) | 演进记录 | 历史250MHz后级CMOS分频实验；不代表已确认的2GHz自由分频域；[报告](../history/hybrid_divider_results.md) |

## 时钟抽出与分发

当前目录：[clocking/distribution](clocking/distribution/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| physical_clock_distribution_ui [PNG](clocking/distribution/physical_clock_distribution_ui.png) / [SVG](clocking/distribution/physical_clock_distribution_ui.svg) | 局部联调 | 实际相位微调/扇出缓冲及旧锁存参数1024bit记录；不替代冻结版256bit证据；[报告](../history/physical_clock_distribution_results.md) |
| pll_replay_clock_phases_ui [PNG](clocking/distribution/pll_replay_clock_phases_ui.png) / [SVG](clocking/distribution/pll_replay_clock_phases_ui.svg) | 演进记录 | 历史PLL时钟回放及串化比较；含源理想化/记录处理边界；[报告](../history/pll_clock_replay_results.md) |
| vco_receiver_eight_phases [PNG](clocking/distribution/vco_receiver_eight_phases.png) / [SVG](clocking/distribution/vco_receiver_eight_phases.svg) | 接口表征 | 时钟接收器及VCO/分频接口；不能用作静态数据转换验收；[报告](../history/cml_clock_receiver_results.md) |

## PLL/PFD/CP/LF搭建

当前目录：[clocking/pll/core](clocking/pll/core/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| pfd_cmos_transfer [PNG](clocking/pll/core/pfd_cmos_transfer.png) / [SVG](clocking/pll/core/pfd_cmos_transfer.svg) | 单元表征 | PFD脉宽与接口，不独立证明CP电荷或PLL捕获；[报告](../history/pfd_cmos_results.md) |
| pfd_cmos_waveforms [PNG](clocking/pll/core/pfd_cmos_waveforms.png) / [SVG](clocking/pll/core/pfd_cmos_waveforms.svg) | 单元表征 | PFD脉宽与接口，不独立证明CP电荷或PLL捕获；[报告](../history/pfd_cmos_results.md) |
| pfd_cp_charge [PNG](clocking/pll/core/pfd_cp_charge.png) / [SVG](clocking/pll/core/pfd_cp_charge.svg) | 局部联调 | PFD/CP/LF开环电荷与滤波响应；[报告](../history/pfd_cp_lf_results.md) |
| pfd_cp_lf_response [PNG](clocking/pll/core/pfd_cp_lf_response.png) / [SVG](clocking/pll/core/pfd_cp_lf_response.svg) | 局部联调 | PFD/CP/LF开环电荷与滤波响应；[报告](../history/pfd_cp_lf_results.md) |
| pll_balanced_extraction [PNG](clocking/pll/core/pll_balanced_extraction.png) / [SVG](clocking/pll/core/pll_balanced_extraction.svg) | 演进记录 | 首轮PLL调试，多种实现视图；逐图回到原报告判断范围；[报告](../history/pll_first_debug.md) |
| pll_mixed_acquisition [PNG](clocking/pll/core/pll_mixed_acquisition.png) / [SVG](clocking/pll/core/pll_mixed_acquisition.svg) | 演进记录 | 首轮PLL调试，多种实现视图；逐图回到原报告判断范围；[报告](../history/pll_first_debug.md) |
| pll_transistor_first_response [PNG](clocking/pll/core/pll_transistor_first_response.png) / [SVG](clocking/pll/core/pll_transistor_first_response.svg) | 演进记录 | 首轮PLL调试，多种实现视图；逐图回到原报告判断范围；[报告](../history/pll_first_debug.md) |

## PLL预充与启动

当前目录：[clocking/pll/startup](clocking/pll/startup/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| lf_cold_precharge [PNG](clocking/pll/startup/lf_cold_precharge.png) / [SVG](clocking/pll/startup/lf_cold_precharge.svg) | 演进记录 | 预充及捕获/频率阶跃的分层记录；后续双节点启动见startup报告；[报告](../history/pll_precharge_capture.md) |
| pll_native_precharged_capture_ui [PNG](clocking/pll/startup/pll_native_precharged_capture_ui.png) / [SVG](clocking/pll/startup/pll_native_precharged_capture_ui.svg) | 演进记录 | 预充及捕获/频率阶跃的分层记录；后续双节点启动见startup报告；[报告](../history/pll_precharge_capture.md) |
| pll_precharged_mixed_capture [PNG](clocking/pll/startup/pll_precharged_mixed_capture.png) / [SVG](clocking/pll/startup/pll_precharged_mixed_capture.svg) | 演进记录 | 预充及捕获/频率阶跃的分层记录；后续双节点启动见startup报告；[报告](../history/pll_precharge_capture.md) |
| pll_precharged_tracking [PNG](clocking/pll/startup/pll_precharged_tracking.png) / [SVG](clocking/pll/startup/pll_precharged_tracking.svg) | 演进记录 | 预充及捕获/频率阶跃的分层记录；后续双节点启动见startup报告；[报告](../history/pll_precharge_capture.md) |
| pll_startup_mixed_handoff_ui [PNG](clocking/pll/startup/pll_startup_mixed_handoff_ui.png) / [SVG](clocking/pll/startup/pll_startup_mixed_handoff_ui.svg) | 阶段/设计依据 | 双节点预充/混合启动与RTL监督器分层证据；原生扩展冷启动尚未验收；[报告](../history/pll_startup_optimization.md) |
| pll_startup_precharge_optimization_ui [PNG](clocking/pll/startup/pll_startup_precharge_optimization_ui.png) / [SVG](clocking/pll/startup/pll_startup_precharge_optimization_ui.svg) | 阶段/设计依据 | 双节点预充/混合启动与RTL监督器分层证据；原生扩展冷启动尚未验收；[报告](../history/pll_startup_optimization.md) |

## PLL跟踪研判

当前目录：[clocking/pll/tracking](clocking/pll/tracking/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| pll_tracking_assessment [PNG](clocking/pll/tracking/pll_tracking_assessment.png) / [SVG](clocking/pll/tracking/pll_tracking_assessment.svg) | 工程估算 | SciPy局部线性模型及已有波形分析；不是器件噪声或实测闭环AC注入；[报告](../history/pll_tracking_assessment.md) |

## 串化器设计演进

当前目录：[tx/serializer](tx/serializer/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| serializer16_2ui_eye [PNG](tx/serializer/serializer16_2ui_eye.png) / [SVG](tx/serializer/serializer16_2ui_eye.svg) | 演进记录 | 理想时钟下组合树/重定时首轮比较；不是最终末级参数验收；[报告](../history/serializer16_first_results.md) |
| serializer16_edge_phase_ui [PNG](tx/serializer/serializer16_edge_phase_ui.png) / [SVG](tx/serializer/serializer16_edge_phase_ui.svg) | 演进记录 | 理想时钟下组合树/重定时首轮比较；不是最终末级参数验收；[报告](../history/serializer16_first_results.md) |
| serializer16_first_waveforms [PNG](tx/serializer/serializer16_first_waveforms.png) / [SVG](tx/serializer/serializer16_first_waveforms.svg) | 演进记录 | 旧 PNG 与 2ui_eye 字节相同，PNG 保留为兼容别名；SVG 独立保留，不作当前验收依据 |
| serializer16_physical_clock_2ui [PNG](tx/serializer/serializer16_physical_clock_2ui.png) / [SVG](tx/serializer/serializer16_physical_clock_2ui.svg) | 局部联调 | 实际相位微调/扇出缓冲及旧锁存参数1024bit记录；不替代冻结版256bit证据；[报告](../history/physical_clock_distribution_results.md) |
| serializer16_pll_replay_2ui [PNG](tx/serializer/serializer16_pll_replay_2ui.png) / [SVG](tx/serializer/serializer16_pll_replay_2ui.svg) | 演进记录 | 历史PLL时钟回放及串化比较；含源理想化/记录处理边界；[报告](../history/pll_clock_replay_results.md) |
| serializer16_power [PNG](tx/serializer/serializer16_power.png) / [SVG](tx/serializer/serializer16_power.svg) | 演进记录 | 理想时钟下组合树/重定时首轮比较；不是最终末级参数验收；[报告](../history/serializer16_first_results.md) |
| serializer16_retimed_2ui_eye [PNG](tx/serializer/serializer16_retimed_2ui_eye.png) / [SVG](tx/serializer/serializer16_retimed_2ui_eye.svg) | 演进记录 | 理想时钟下组合树/重定时首轮比较；不是最终末级参数验收；[报告](../history/serializer16_first_results.md) |
| serializer16_retimed_boundary_ui [PNG](tx/serializer/serializer16_retimed_boundary_ui.png) / [SVG](tx/serializer/serializer16_retimed_boundary_ui.svg) | 演进记录 | 理想时钟下组合树/重定时首轮比较；不是最终末级参数验收；[报告](../history/serializer16_first_results.md) |
| serializer16_waveforms_ui [PNG](tx/serializer/serializer16_waveforms_ui.png) / [SVG](tx/serializer/serializer16_waveforms_ui.svg) | 演进记录 | 理想时钟下组合树/重定时首轮比较；不是最终末级参数验收；[报告](../history/serializer16_first_results.md) |

## TX输出驱动

当前目录：[tx/output_driver](tx/output_driver/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| serializer_output_stage_integration_ui [PNG](tx/output_driver/serializer_output_stage_integration_ui.png) / [SVG](tx/output_driver/serializer_output_stage_integration_ui.svg) | 接口表征 | 首版线驱动、端接/损耗夹具及实际输入加载；不是全链路RX/CDR；[报告](../history/tx_output_stage_and_link_plan.md) |
| tx_line_driver_channel_eyes_ui [PNG](tx/output_driver/tx_line_driver_channel_eyes_ui.png) / [SVG](tx/output_driver/tx_line_driver_channel_eyes_ui.svg) | 接口表征 | 首版线驱动、端接/损耗夹具及实际输入加载；不是全链路RX/CDR；[报告](../history/tx_output_stage_and_link_plan.md) |

## 信道模型与TX/PCB实验

当前目录：[channel/characterization](channel/characterization/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| pcb_channel_family_frequency [PNG](channel/characterization/pcb_channel_family_frequency.png) / [SVG](channel/characterization/pcb_channel_family_frequency.svg) | 模型表征 | 合成100Ω PCB通道族；不是具体PCB实测；[报告](../history/pcb_channel_family.md) |
| pcb_channel_family_pulses_ui [PNG](channel/characterization/pcb_channel_family_pulses_ui.png) / [SVG](channel/characterization/pcb_channel_family_pulses_ui.svg) | 模型表征 | 合成100Ω PCB通道族；不是具体PCB实测；[报告](../history/pcb_channel_family.md) |
| tx_pcb_channel_2ui [PNG](channel/characterization/tx_pcb_channel_2ui.png) / [SVG](channel/characterization/tx_pcb_channel_2ui.svg) | 局部联调 | 实际TX驱动合成PCB；没有完整RX/CDR；[报告](../history/tx_pcb_channel_integration.md) |
| tx_pcb_channel_effects_ui [PNG](channel/characterization/tx_pcb_channel_effects_ui.png) / [SVG](channel/characterization/tx_pcb_channel_effects_ui.svg) | 局部联调 | 实际TX驱动合成PCB；没有完整RX/CDR；[报告](../history/tx_pcb_channel_integration.md) |

## ISI/均衡原理说明

当前目录：[channel/explanations](channel/explanations/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| channel_equalization_pulse_shaping [PNG](channel/explanations/channel_equalization_pulse_shaping.png) / [SVG](channel/explanations/channel_equalization_pulse_shaping.svg) | 原理说明 | ISI/均衡/理想升余弦解释；不是TX通过实际PCB后的结果；[报告](../history/pcb_channel_family.md) |

## RX输入/CTLE

当前目录：[rx/frontend](rx/frontend/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| rx_ctle_c2_replay_2ui [PNG](rx/frontend/rx_ctle_c2_replay_2ui.png) / [SVG](rx/frontend/rx_ctle_c2_replay_2ui.svg) | 单元表征 | CTLE DC/AC与保存通道电压回放；完整加载由后续实验补充；[报告](../history/rx_frontend_first_design.md) |
| rx_ctle_characterization [PNG](rx/frontend/rx_ctle_characterization.png) / [SVG](rx/frontend/rx_ctle_characterization.svg) | 单元表征 | CTLE DC/AC与保存通道电压回放；完整加载由后续实验补充；[报告](../history/rx_frontend_first_design.md) |
| rx_loaded_link_2ui [PNG](rx/frontend/rx_loaded_link_2ui.png) / [SVG](rx/frontend/rx_loaded_link_2ui.svg) | 局部联调 | 切点在TX隔离buffer输入，真实驱动/通道/RX加载，不含被切去的串化器/PLL；[报告](../history/rx_loaded_link.md) |
| rx_loaded_link_boundary_ui [PNG](rx/frontend/rx_loaded_link_boundary_ui.png) / [SVG](rx/frontend/rx_loaded_link_boundary_ui.svg) | 局部联调 | 切点在TX隔离buffer输入，真实驱动/通道/RX加载，不含被切去的串化器/PLL；[报告](../history/rx_loaded_link.md) |

## RX相位插值

当前目录：[rx/pi](rx/pi/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| rx_pi_outputs [PNG](rx/pi/rx_pi_outputs.png) | 单元表征 | PI静态64码与规定跨圈窗口；无全局CDR闭环；[报告](../history/rx_pi_first_design.md) |
| rx_pi_phase64 [PNG](rx/pi/rx_pi_phase64.png) | 单元表征 | PI静态64码与规定跨圈窗口；无全局CDR闭环；[报告](../history/rx_pi_first_design.md) |
| rx_pi_wrap_2ui [PNG](rx/pi/rx_pi_wrap_2ui.png) | 单元表征 | PI静态64码与规定跨圈窗口；无全局CDR闭环；[报告](../history/rx_pi_first_design.md) |

## 采样、CMOS读出与pair对齐

当前目录：[rx/sampler](rx/sampler/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| rx_cmos_readout_alignment [PNG](rx/sampler/rx_cmos_readout_alignment.png) | 阶段/设计依据 | 真实静态CMOS读出与公共pair重定时短窗；不是物理16UI降速；[报告](../history/rx_cdr_closed_loop.md) |
| rx_pcb_cmos_readout [PNG](rx/sampler/rx_pcb_cmos_readout.png) | 阶段/设计依据 | 实际24ns加载窗口80bit及3字逻辑回放；未闭合实时CDR反馈；[报告](../history/rx_cdr_closed_loop.md) |
| rx_sampler_pi_loaded [PNG](rx/sampler/rx_sampler_pi_loaded.png) | 局部联调 | PI/CTLE/采样加载和控制轨迹回放；尚非实时反馈；[报告](../history/rx_sampler_control.md) |
| rx_sampler_rtl_pi_wrap [PNG](rx/sampler/rx_sampler_rtl_pi_wrap.png) | 局部联调 | PI/CTLE/采样加载和控制轨迹回放；尚非实时反馈；[报告](../history/rx_sampler_control.md) |

## CDR/串并功能

当前目录：[rx/cdr](rx/cdr/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| rx_cdr_tracking_ui [PNG](rx/cdr/rx_cdr_tracking_ui.png) | 阶段/设计依据 | 长时实际RTL/行为plant跟踪与独立MOS读出/加载窗口；不是全晶体管长时整机；[报告](../history/rx_cdr_closed_loop.md) |

## 实时数模接口

当前目录：[verification/mixed_signal](verification/mixed_signal/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| mixed_signal_boundary [PNG](verification/mixed_signal/mixed_signal_boundary.png) | 阶段/设计依据 | 192UI实时反馈，理想锚点/NRZ源、行为16UI打包；不代表长时锁定或全TX/PCB；[报告](../history/mixed_signal_cosim.md) |
| mixed_signal_feedback [PNG](verification/mixed_signal/mixed_signal_feedback.png) | 阶段/设计依据 | 192UI实时反馈，理想锚点/NRZ源、行为16UI打包；不代表长时锁定或全TX/PCB；[报告](../history/mixed_signal_cosim.md) |

## CMOS驱动替代方案

当前目录：[studies/cmos_select](studies/cmos_select/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| mux2_cmos_select_transient [PNG](studies/cmos_select/mux2_cmos_select_transient.png) / [SVG](studies/cmos_select/mux2_cmos_select_transient.svg) | 未选替代方案 | CMOS驱动换流选择的替代方案比较；未选作当前CML方案；[报告](../history/cmos_select_trial.md) |
| serializer16_cmos_select_comparison [PNG](studies/cmos_select/serializer16_cmos_select_comparison.png) / [SVG](studies/cmos_select/serializer16_cmos_select_comparison.svg) | 未选替代方案 | CMOS驱动换流选择的替代方案比较；未选作当前CML方案；[报告](../history/cmos_select_trial.md) |

## 时钟叠图/相位间隔诊断

当前目录：[studies/clock_timing](studies/clock_timing/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| clock_2g_edge_zoom_ui [PNG](studies/clock_timing/clock_2g_edge_zoom_ui.png) / [SVG](studies/clock_timing/clock_2g_edge_zoom_ui.svg) | 专项诊断 | 同一物理时钟记录的周期/过零叠图；没有新增SPICE，不等于随机抖动测量；[报告](../history/clock_overlay_results.md) |
| clock_cycle_overlays_ui [PNG](studies/clock_timing/clock_cycle_overlays_ui.png) / [SVG](studies/clock_timing/clock_cycle_overlays_ui.svg) | 专项诊断 | 同一物理时钟记录的周期/过零叠图；没有新增SPICE，不等于随机抖动测量；[报告](../history/clock_overlay_results.md) |
| multirate_clock_design_edge_overlay [PNG](studies/clock_timing/multirate_clock_design_edge_overlay.png) / [SVG](studies/clock_timing/multirate_clock_design_edge_overlay.svg) | 专项诊断 | 多频多相时钟叠图及设计对齐；原始节点不自动等间距；[报告](../history/pll_multiphase_clock_overlay.md) |
| pll_eight_phase_design_aligned_eye [PNG](studies/clock_timing/pll_eight_phase_design_aligned_eye.png) / [SVG](studies/clock_timing/pll_eight_phase_design_aligned_eye.svg) | 专项诊断 | 多频多相时钟叠图及设计对齐；原始节点不自动等间距；[报告](../history/pll_multiphase_clock_overlay.md) |
| pll_multiphase_250ps_fold [PNG](studies/clock_timing/pll_multiphase_250ps_fold.png) / [SVG](studies/clock_timing/pll_multiphase_250ps_fold.svg) | 专项诊断 | 多频多相时钟叠图及设计对齐；原始节点不自动等间距；[报告](../history/pll_multiphase_clock_overlay.md) |

## 眼图折叠方法

当前目录：[studies/eye_folding](studies/eye_folding/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| serializer16_fold_ui_comparison [PNG](studies/eye_folding/serializer16_fold_ui_comparison.png) / [SVG](studies/eye_folding/serializer16_fold_ui_comparison.svg) | 专项诊断 | 改变折叠基准的plot层诊断；不改变电路或实际位误差；[报告](../history/eye_fold_ui_sweep.md) |

## 串化器逐级时序溯源

当前目录：[studies/serializer_timing](studies/serializer_timing/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| divider_phase_spacing_audit [PNG](studies/serializer_timing/divider_phase_spacing_audit.png) / [SVG](studies/serializer_timing/divider_phase_spacing_audit.svg) | 专项诊断 | 相位接法与末级锁存跟踪/恢复的局部溯源；驱动比较支撑后续选型；[报告](../history/serializer_timing_root_cause.md) |
| serializer_latch_drive_probe_2ui [PNG](studies/serializer_timing/serializer_latch_drive_probe_2ui.png) / [SVG](studies/serializer_timing/serializer_latch_drive_probe_2ui.svg) | 专项诊断 | 相位接法与末级锁存跟踪/恢复的局部溯源；驱动比较支撑后续选型；[报告](../history/serializer_timing_root_cause.md) |
| serializer_timing_root_cause [PNG](studies/serializer_timing/serializer_timing_root_cause.png) / [SVG](studies/serializer_timing/serializer_timing_root_cause.svg) | 专项诊断 | 相位接法与末级锁存跟踪/恢复的局部溯源；驱动比较支撑后续选型；[报告](../history/serializer_timing_root_cause.md) |

## PLL PVT与物理滤波器（首轮）

当前目录：[clocking/pll/pvt](clocking/pll/pvt/README.md)。

| 图组 | 用途 | 适用范围／报告 |
|---|---|---|
| pll_pvt_frequency_coverage [PNG](clocking/pll/pvt/pll_pvt_frequency_coverage.png) / [SVG](clocking/pll/pvt/pll_pvt_frequency_coverage.svg) | 单元表征 | 九环境开环调谐与固定控制点，非闭环锁频或全PVT签核；[报告](../history/pll_pvt_first_results.md) |
| pll_lf_poly_mim_corners [PNG](clocking/pll/pvt/pll_lf_poly_mim_corners.png) / [SVG](clocking/pll/pvt/pll_lf_poly_mim_corners.svg) | 模型表征 | 七个独立RC/温度条件及滤波器阻抗，不含完整版图寄生；[报告](../history/pll_pvt_first_results.md) |
| pll_pvt_loop_filter_comparison [PNG](clocking/pll/pvt/pll_pvt_loop_filter_comparison.png) / [SVG](clocking/pll/pvt/pll_pvt_loop_filter_comparison.svg) | 局部联调 | 仅TT实际PFD/CP与理想/物理LF对照，行为VCO/理想分频；[报告](../history/pll_pvt_first_results.md) |
| pll_pvt_clock_interface_failure [PNG](clocking/pll/pvt/pll_pvt_clock_interface_failure.png) / [SVG](clocking/pll/pvt/pll_pvt_clock_interface_failure.svg) | 专项诊断 | SS低压热角VCO与buffer保持差分活动，CMOS读出缺失；局部接口证据；[报告](../history/pll_pvt_first_results.md) |

## 演进关系示例

[方案文档](../history/figure_organization.md)的串化器演进图区分了电路修改、源边界替换与纯波形再分析。每张图的旧数值/原始哈希保留；当前结论回到冻结或阶段清单判定。

## VCO与时钟接收器的PVT修整候选

目录：[clocking/pll/pvt_refinement](clocking/pll/pvt_refinement/README.md)。[完整报告](../history/pll_pvt_refinement.md)。原冻结版本未替换；SS CML分频链仍有独立失效。

- [pvt_vco_tuning_margin](clocking/pll/pvt_refinement/pvt_vco_tuning_margin.png)：VCO尺寸/节点MIM扫描及五环境2GHz覆盖；TT相邻码局部重叠；非全码/全角签核。
- [pvt_receiver_internal_margin](clocking/pll/pvt_refinement/pvt_receiver_internal_margin.png)：SS低压热角转换器内部动态裕量：原版与独立候选比较。
- [pvt_receiver_temperature_boundary](clocking/pll/pvt_refinement/pvt_receiver_temperature_boundary.png)：SS电压/温度条件边界；8ns初筛与32ns临界复查分开；非产品温度额定值。
- [pvt_ss_divider_isolation](clocking/pll/pvt_refinement/pvt_ss_divider_isolation.png)：转换器已恢复，但SS低压热角CML ÷2摆幅不足、÷4/÷8失效；非PLL通过。

## PLL 低过驱动工作修订

[专题入口](clocking/pll/pvt_lowov/README.md)包含45条件功能矩阵、FS共模修正、SS实际VCO回接。标准边界分频/反馈45/45，全速CMOS44/45；实际FS角2GHz回接尚未资格验证。见[完整报告](../history/pll_lowov_pvt.md)。

## 锁存器拓扑与负载探索

[专题](clocking/dividers/topology_exploration/README.md)比较独立共模、两层CML、folded、PMOS负载和动态CMOS，另有数据DFF及级间buffer回放。仅为探索，见[报告](../history/cml_latch_topology_experiments.md)。

## 工作版r3：级间buffer与PVT

[专题](clocking/pll/pvt_buffered/README.md)包含45条件复测、真实VCO回接和CP输出窗口初探，见[报告](../history/pll_buffered_pvt.md)。冻结v0.1证据与工作r3范围分开。

## PLL PFD/CP/LF 选角闭环

目录：[clocking/pll/loop_pvt](clocking/pll/loop_pvt/README.md)。同角实测 VCO 模型与真实控制电路的局部跟踪，原生接回另列；见 [报告](../history/pll_loop_pvt.md)。

## TX PVT 与输出使能定位

目录：[tx/pvt](tx/pvt/README.md)。45工况加载链与独立输出级、使能启动对照和选角6dB PCB；见 [报告](../history/tx_pvt.md)。

## r3分频buffer相位与半UI显示

[相位/奇偶位核对](clocking/distribution/buffered_phase_review/README.md)单列r3原生时钟和真实TX静态负载；PVT眼图仅平移显示，不改变原始分析。见 [报告](../history/tx_clock_phase_audit.md)。
