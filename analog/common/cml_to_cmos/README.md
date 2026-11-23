# CML → CMOS

用于 VCO 连续差分时钟的接收器：LVT 源跟随输入缓冲、双路差分电平转换、边沿驱动时钟恢复和 CMOS 输出驱动。

状态：已有晶体管级原型及实际 VCO 联调。结果、波形和使用边界见 [设计报告](../../../docs/history/cml_clock_receiver_results.md)。
输入/输出约定见 [spec.toml](spec.toml)。输出恢复级有状态，不用于静态数据转换。

spice/ 保存晶体管或无源实现，behavioral/ 保存行为模型，schematic/ 保存原理图，layout/ 保存版图，tb/ 保存测试。

| 测试项 | 层次 | 收集指标 |
|---|---|---|
| [functional](tb/functional/case.toml) | block | logic_levels, propagation_delay, rise_time, fall_time, duty_cycle, power |
| [input_range](tb/input_range/case.toml) | block | minimum_input_swing, common_mode_range, maximum_verified_rate |
| [dc_transfer](tb/dc_transfer/case.toml) | block | 连续时间前端的静态极性和门限 |
| [reverse_loading](tb/reverse_loading/case.toml) | block | 有限源阻抗下的负载反灌检查 |

端口顺序：inp、inn、outp、outn、vbias、vdd、vss。vbias 接标准 NMOS 电流镜偏置，
本轮用 20 µm / 0.5 µm、nf=4 的二极管器件和 0.85 mA 外部参考产生。
依赖 devices/spice/sky130_primitives.spice 与 SKY130 模型库；DUT 无理想比较器或行为增益块。

当前目标点：1.8 V，输入共模约 1.632 V、差分峰峰值 400 mV、2 GHz，每路 CMOS 输出 20 fF。
固定电压下已做 tt/ss/ff/sf/fs，另做 TT 125°C；不是完整 PVT、失配、提取或噪声验证。
最终版本的最小摆幅和连续共模范围尚未闭合；不要用早期探索版本的数据作为当前电路边界。

源跟随器本身就是输入缓冲，但有非零 Cgs/Cgd 和偏置/电源耦合。
当前建议每个 VCO 差分对直接接一个接收器。多 CML 负载或长走线时再评估独立 CML buffer；
CMOS 端负载较重时，在转换器之后配置 CMOS 时钟树。

时钟恢复级依靠互补输入的交替上升沿，启动/停钟期间输出可能保持旧状态。
输出有效性应结合 VCO 稳定或 PLL 锁定指示；这里没有复位端或无毛刺时钟门控保证。
时钟周期内过零时差按 modulo-T 记录，不是无歧义的因果传播延迟。

结果：`results/analog/common/cml_to_cmos/<case>/<run_id>/`，VCO 联调在
`results/analog/pll/top/vco_receiver/<run_id>/`。最终版本用 DUT SHA256 与探索版本区分。
所有设计判定仍为 ungraded，内部工程检查不代替用户签定的规格。
# 静态数据接口补充

spice/cml_to_cmos_data.spice为支持DC0/1与长同码的数据接收器，复用source follower、镜像差分级和两级反相器；不经过时钟边沿恢复器。已在真实PI/CTLE/采样器之后表征，结果及350/425 ps读出窗口见[RX闭环/接口记录](../../../docs/history/rx_cdr_closed_loop.md)。原clock receiver仍用于时钟，不能互换两者的时序验收。

