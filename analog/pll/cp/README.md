# CP 电荷泵

UP 向滤波器注入电荷，DN 抽取电荷；固定输出夹具与真实滤波器测试分开。

已有 SKY130 晶体管级原型：`spice/charge_pump.spice` 的 `pll_cp up dn out vbn vbp vdd vss`。
长沟道电流镜配串联开关，外部独立 N/P 参考暂取 50 µA；参考电路本身尚未实现。
UP 驱动做了 TT、1.3 V 下的名义脉宽补偿，不能视为跨 PVT 或输出范围的匹配保证。
源端开关替代方案保留为探索，未被选为当前原型。
实现、净电荷与边界见 [PFD/CP/LF 记录](../../../docs/pfd_cp_lf_results.md)。

spice/ 保存晶体管或无源实现，behavioral/ 保存行为模型，schematic/ 保存原理图，layout/ 保存版图，tb/ 保存测试。

| 测试项 | 层次 | 收集指标 |
|---|---|---|
| [dc](tb/dc/case.toml) | block | source_current, sink_current, current_mismatch, compliance_range, leakage |
| [switching](tb/switching/case.toml) | block | source_charge, sink_charge, net_charge, charge_injection, settling_time |
| [mismatch](tb/mismatch/case.toml) | block | current_mismatch_distribution, net_charge_distribution |

DC 测试在本模块，实际开关电荷测试在 `pll/top/tb/pfd_cp/`；独立 switching 与统计 mismatch 计划尚待完成。
结果：`results/analog/pll/cp/<case>/<run_id>/` 和 `results/analog/pll/top/pfd_cp/`，最终规格仍为 ungraded。
