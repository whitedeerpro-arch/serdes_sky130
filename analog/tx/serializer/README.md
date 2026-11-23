# 16:1 电流舵串化器

原型为 8 + 4 + 2 + 1 个差分 2:1 CML 选择器组成的四级树。
输入字速率 250 MHz，目标输出 4 Gb/s，原型约定 d0 先出。
`spice/serializer16_tree.spice` 接收差分 CML 数据；测试夹具包含 16 个实际 CMOS→CML 输入单元。

第一级按 j 与 j+8 配对，随后按 j+4、j+2、偶/奇配对，不能简单把所有相邻位逐级合并后仍假定连续位序。
选择时钟分别为 250 MHz、500 MHz、1 GHz、2 GHz；当前夹具使用有明确相位偏移的理想相关 CML 时钟。

组合树保留为基准；`spice/serializer16_retimed.spice` 另有末级双CML锁存重定时变体。
并行字捕获寄存器和实际 PLL 时钟分发仍未完成，重定时结果见首轮记录。
首轮在指定数据更新时刻下验证位中心和边沿，不能外推到任意并行输入时序。
默认片内输出负载每端 20 fF；端接、封装、ESD 与通道驱动仍待定义。

结果与 2 UI 眼图见 [首轮记录](../../../docs/history/serializer16_first_results.md)，参数见 `config/serializer16.toml`。

`spice/serializer16_tree_cmos_select.spice` 另用理想互补CMOS时钟直接选择；同相时钟下的独立对照见[试验记录](../../../docs/history/cmos_select_trial.md)。

CMOS选择方向已停止，以上仅留历史。当前继续CML选择；原生PLL稳定记录经真实CML缓冲/分频后冻结回放的64字比较，见[PLL时钟回放](../../../docs/history/pll_clock_replay_results.md)。
冻结回放保留电平/边沿与相位，但不验证真实时钟源输出阻抗、串化器扇出反作用或硬件字对齐。

后续已加入源端理想化之后的8个实际CML分发buffer，采用固定原生相位/极性路由和电容微调，并在真实选择器扇出下跑完64字。
见[实际时钟分发结果](../../../docs/history/physical_clock_distribution_results.md)。输入字同步更新，捕获寄存器仍未加入；源端反作用与PVT仍需后续验证。

设计v0.1定稿选用末级A/B锁存器尾管24µm、每端200Ω，输出MUX仍12µm/400Ω。对应256bit实测0错、散布0.04192UI；上面的1024bit旧结果不作为新版验证。通过latch_tail_scale=1、latch_load_scale=1可恢复旧基准。冻结清单见config/design_release.toml和releases/v0.1-design-freeze-20261028。
