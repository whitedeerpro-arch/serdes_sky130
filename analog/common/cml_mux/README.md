# CML 电流舵选择器

`spice/cml_mux2.spice` 是非反相 2:1 原型：`sp > sn` 选择 B，反之选择 A。
数据为高共模 CML，选择端经本地 LVT 源跟随器平移共模，再控制电流转向。
输出共模由本级负载和尾电流建立；级联时仍需测量输入范围、幅度和时序。

首轮默认单元在 2 GHz 选择下检查 4 Gb/s 输出，并作为 16:1 树的基础。
原型使用理想电阻、外部偏置和明确的片内负载，尚未形成带通道的线驱动器。
当前比较结果及 2 UI 眼图见 [16:1 首轮结果](../../../docs/history/serializer16_first_results.md)。

`cml_data_latch.spice` 为真实差分跟踪/保持锁存；`cml_latched_mux2.spice` 在末级2:1选择器前对两路数据交替保持。
建立时间和选择相位仍需验证，不能仅靠增加锁存器保证正确。

`cml_mux2_cmos_select.spice` 是直接互补CMOS选择的独立试验版本，去掉本地选择端跟随器，保留公共尾源。
同尺寸/尾源/负载下的对照见[CMOS选择试验](../../../docs/history/cmos_select_trial.md)，没有替换原候选。
