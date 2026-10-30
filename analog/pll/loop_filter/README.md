# 环路滤波器

当前初选无源双电容结构；元件值为候选，夹具注明 CP 源阻抗与 VCO 负载。

已有无源双电容原型：`spice/passive_rc.spice`，接口 `cp_in vctrl vss`，
输入并联 2 pF，并接 6.5 kΩ 串联 40 pF 到地。数值为理想 R/C 预算，尚未映射到工艺无源器件。
独立 AC/注入电荷测试及实际 PFD/CP 驱动测试见 [结果](../../../docs/pfd_cp_lf_results.md)。
平均模型的环路交越/相位裕量仅为初步估计，不代表真实 PLL 锁定或噪声已验证。
两个电容从冷态经实际传输门建立的时间及预充后的捕获见 [预充/捕获记录](../../../docs/pll_precharge_capture.md)。

spice/ 保存晶体管或无源实现，behavioral/ 保存行为模型，schematic/ 保存原理图，layout/ 保存版图，tb/ 保存测试。

| 测试项 | 层次 | 收集指标 |
|---|---|---|
| [impedance](tb/impedance/case.toml) | block | transimpedance, poles, zeros |
| [transient](tb/transient/case.toml) | block | control_voltage_step, ripple, settling_time |

结果：`results/analog/pll/loop_filter/<case>/<run_id>/`；实际驱动测试在 `pll/top/tb/pfd_cp_lf/`。
尚无工艺无源器件映射或完整 PLL 稳定性/噪声验证，最终规格仍为 ungraded。

新增passive_rc_precharge.spice直接预充ctrl/z两状态；同源阻抗比较及关断扰动见[启动优化](../../../docs/pll_startup_optimization.md)。
