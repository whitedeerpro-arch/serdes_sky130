# 监测单元（模拟）

慢速监测用的小模拟积木：连续时间比较器、电流×电阻门限梯（对地 / 对电源）、16:1 抽头选择、窗口比较器、VBE 温度感测。
通用件，不含使用方常数：门限由码和电流决定，电流来自偏置分配的拷贝（[bias_dist](../bias/spice/bias_dist.spice) 的 `serdes_bias_pcopy`）。
数字配套见 [digital/common](../../../digital/common/README.md)，整体说明与表征结果见 [监测工具包](../../../docs/design/monitor.md)。

| 单元 | 端口 | 说明 |
|---|---|---|
| `serdes_cmp` | inp inn out ib vdd vss | inp > inn 时 out = 1（CMOS）；ib 为灌入的偏置电流（标称 2.5 µA，一指拷贝）；静态约 2·ib |
| `serdes_vref_gnd` | iin out vdd vss | out = I(iin)·(r0 + code·rstep)，对地；high_po，与 r_ref 同类 → 比值稳定 |
| `serdes_vref_vdd` | iin out vdd vss | out = vdd − I(iin)·(r0 + code·rstep)；NMOS 镜像灌电流 |
| `serdes_tap_mux16` | t0..t15 out vdd vss | 传输门 16:1，静态 code（行为译码） |
| `serdes_window_cmp` | in vlo vhi hi lo ibh ibl vdd vss | hi = in > vhi，lo = in < vlo |
| `serdes_tsense_vbe` | out vss | out = VBE + I·rs，I 由外部拷贝灌入；约 −1.8 mV/K |

实现：[spice/monitor.spice](spice/monitor.spice)。测试：[cmp_dc](tb/cmp_dc/run.py)（45 条件 × 输入共模的翻转点）、
[cmp_mc](tb/cmp_mc/run.py)（局部失配失调）、[tsense_dc](tb/tsense_dc/run.py)（MOS 角 × 电阻角 × VDD 的各码翻转温度）。
结果在 `results/analog/common/monitor/<case>/<run_id>/`。
