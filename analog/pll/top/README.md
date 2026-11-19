# PLL 集成与闭环

行为级先验证架构，再在晶体管级及提取后复查；相邻模块集成与系统测试分开。

已有相邻模块原型、PFD/CP/LF 开环联调和混合视图闭环捕获；真实 VCO 加平衡 dummy 的反馈链已完成 TT 预充后持续工程判锁观察，LF 仍为理想 R/C。
新结果见 [LF预充与PLL捕获](../../../docs/history/pll_precharge_capture.md)，不代表 PVT、噪声或提取后签核。
新跑的近锁定原生PLL另保存所有VCO相位及CML slave/master分频节点，供[实际分发buffer联调](../../../docs/history/physical_clock_distribution_results.md)使用；该记录不重定义原来的捕获时间。
接口见 [架构](../../../docs/overview/architecture.md)，闭环分层结果见 [PLL 首轮调试](../../../docs/history/pll_first_debug.md)。
原理图从 [pll_balanced_core.sch](schematic/pll_balanced_core.sch) 进入，图册与导出方法见 [原理图说明](../../../docs/history/schematics.md)。

spice/ 保存晶体管或无源实现，behavioral/ 保存行为模型，schematic/ 保存原理图，layout/ 保存版图，tb/ 保存测试。

| 测试项 | 层次 | 收集指标 |
|---|---|---|
| [pfd_cp](tb/pfd_cp/case.toml) | integration | net_charge_vs_phase, source_sink_polarity, minimum_effective_pulse |
| [pfd_cp_lf](tb/pfd_cp_lf/case.toml) | integration | cycle_charge, control_voltage, ripple；不含 VCO 闭环 |
| vco_divider (`tb/vco_divider/case.toml`, retired in `retired_legacy_vars_20261120.json`) | integration | vco_frequency, feedback_frequency, division_ratio, interface_swing |
| acquisition (`tb/acquisition/case.toml`, retired in `retired_legacy_vars_20261120.json`) | system | lock_time, frequency_error, phase_error, cycle_slips, control_voltage, power |
| [tracking](tb/tracking/case.toml) | system | tracking_bandwidth, peaking, phase_margin, recovery_time |
| [jitter](tb/jitter/case.toml) | system | tie_rms, period_jitter_rms, cycle_to_cycle_jitter_rms, jitter_psd |
| [spurs](tb/spurs/case.toml) | system | reference_spur, harmonic_spurs, control_voltage_ripple |

结果：`results/analog/pll/top/<case>/<run_id>/`。状态以各 case.toml 和结果中的视图、条件为准，不能将测试目录存在解释为规格已通过。

双节点预充、CP使能与RTL接管监督候选见[启动优化](../../../docs/history/pll_startup_optimization.md)；旧核心保留，完整原生冷启动和测量前端待验证/实现。
