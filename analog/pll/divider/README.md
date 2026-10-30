# 反馈分频器

当前定义以 [时钟域修正](../../../docs/history/clock_domain_clarification.md) 为准：默认反馈 CML ÷8；
自由 CMOS 分频另接多相 CML 转换后的最高 2 GHz CMOS 时钟。
下面的 250 MHz CMOS 后级实现和结果属于已有实验，不能作为 2 GHz 自由分频的时序证明。

此前实验路径是 **三级固定 CML ÷8 → CML/CMOS 接收器 → 250 MHz CMOS M=1–16**，默认 M=1。
2 GHz 输入时，CML 保留 1 GHz、500 MHz、250 MHz 抽头；默认反馈走 250 MHz，
不再使用全速 CML 可编程计数器，也没有默认活动的第四级 CML ÷16。
当前结果见 [混合分频记录](../../../docs/history/hybrid_divider_results.md)，
之前的全 CML 探索保留在 [历史记录](../../../docs/history/cml_divider_results.md)。

| 实现 | 用途 |
|---|---|
| spice/cml_latch.spice、cml_dff.spice | 主从锁存器、通用 CML DFF；下层时钟对之前有本地源跟随电平移位 |
| spice/cml_div2.spice | Q 反相回授的 ÷2，可观察主锁存器输出 mp/mn |
| spice/cml_prescaler8.spice | 当前固定三级 CML 前端，保留 /2、/4、/8 抽头 |
| spice/cmos_divider_programmable.spice | 当前 CMOS M=1–16 后级；组合逻辑可独立做真值表检查 |
| common/devices/spice/cmos_dff_reset.spice | 与 PFD 共享的静态 CMOS 复位锁存器/DFF |
| spice/cml_binary_chain.spice | 历史四级 /2、/4、/8、/16 探索，保留复现 |
| spice/cml_logic.spice、cml_divider_programmable.spice | 历史全 CML 整数计数器，已退出当前基准路径 |

CMOS 配置 m3…m0 编码 M−1，0000=/1，0011=/4，1111=/16；只在 rst_b 低且有足够稳定时间时修改。
`tick` 为给边沿 PFD 的每 M 周期一次脉冲；`clk_out` 是注册的分频时钟，偶数 M 近 50%，
奇数 M>1 高 ceil(M/2) 周期、低 floor(M/2) 周期。M=1 时两个输出均旁路，并关闭计数器时钟。
复位释放先在输入低电平锁存使能；复位断言可截断正在进行的脉冲，期间时钟/数据无效。
尚未实现动态无毛刺切比、全 CML 确定相位复位或字对齐。

若 CMOS 级进入反馈，总分频为 8M，不是任意总整数；若只是派生辅助时钟，则不必进入 PLL 反馈。
同一个 250 MHz 参考下增加反馈 M 会提高所需 VCO 频率，不能单独用来降低线速。
500 MHz 参考在最高 2 GHz VCO 下需要另选 ÷4 抽头，默认 ÷8 路径无法满足。

spice/ 保存晶体管或无源实现，behavioral/ 保存行为模型，schematic/ 保存原理图，layout/ 保存版图，tb/ 保存测试。

| 测试项 | 层次 | 收集指标 |
|---|---|---|
| [functional](tb/functional/case.toml) | block | division_ratio, output_frequency, duty_cycle, reset_recovery, power |
| [input_range](tb/input_range/case.toml) | block | maximum_verified_input_frequency, minimum_input_swing, input_common_mode_range |
| [logic_truth](tb/logic_truth/case.toml) | block | 16 配置 ×16 状态的 next-state / zero / half-period 译码 |

测试台中的 @...@ 标记按 [测试约定](../../../docs/verification/methods.md) 替换，使用 ngspice 47。
MHz 在 SPICE 中写作 `Meg`；`M` 表示 milli。具体参数和输入快照保存在每个运行目录。
结果：`results/analog/pll/divider/<case>/<run_id>/`，最终规格判定仍为 ungraded。
