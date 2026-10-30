# CML 差分对与电流舵

先确定尾电流、负载、输入共模和器件工作区。

状态：已有电阻负载差分延迟单元原型（spice/cml_delay_resistive.spice），已用于 VCO。
本目录的独立 DC、切换、带宽表征仍待完成。接口草案见 [architecture.md](../../../docs/architecture.md)。

另有可选时钟缓冲 spice/cml_buffer.spice：单级非反相差分接口，wn=12 µm、nf=4，
尾管总宽 12 µm、长 0.5 µm，负载 600 Ω。端口为 inp、inn、outp、outn、vbias、vdd、vss。
它依赖 cml_delay_resistive.spice；负载电阻暂为理想器件。
已在 VCO→CML buffer→时钟接收器链路中验证约 2 GHz，单级功耗约 0.855 mW，
输出差分峰峰值约 522 mV。该结果是时钟缓冲测试，不是 4 Gb/s PRBS 数据缓冲验证。
当前单接收器/相的默认链路直接使用接收器内部输入缓冲，详见
[联调报告](../../../docs/cml_clock_receiver_results.md)。

spice/ 保存晶体管或无源实现，behavioral/ 保存行为模型，schematic/ 保存原理图，layout/ 保存版图，tb/ 保存测试。

| 测试项 | 层次 | 收集指标 |
|---|---|---|
| [dc](tb/dc/case.toml) | block | transfer_curve, output_common_mode, differential_swing, tail_current, power |
| [switching](tb/switching/case.toml) | block | propagation_delay, rise_time, fall_time, differential_swing, duty_cycle, power |
| [bandwidth](tb/bandwidth/case.toml) | block | differential_gain, bandwidth |

结果：`results/analog/common/cml_buffer/<case>/<run_id>/`。规格和具体测试台尚待填写，以上不是已通过的验证。
