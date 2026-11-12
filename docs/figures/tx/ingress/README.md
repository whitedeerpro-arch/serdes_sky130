# TX 字入口图

| 图 | 回答的问题 | 范围 |
|---|---|---|
| [单元加载延迟](tx_ingress_loaded_delay.png) | 精简/复位DFF在实际转换器/MUX负载下差多少？ | 6压力×2静态选择状态，120次捕获；理想时钟 |
| [跨字分组保持](tx_staggered_hold_timing.png) | 新h变化时，B组是否仍保持旧字？ | 实际接收/缓冲驱动16位bank，TT原始波形；完整bank另测6压力 |
| [关闭竞争边界](tx_launch_hold_aperture.png) | 数据提前多少会串入新字？正常到达在哪里？ | 固定电压回放，6压力×2事件形状；164平移点；无源阻抗/MC/噪声 |
| [45条件完整TX](tx_full_pvt45.png) | extra5时钟＋输出级候选在45个MOS条件下串化器/焊盘裕量与散布如何？ | 理想2GHz输入、真实偏置/PDK R tt，256 bit载荷；远端为比较；[数据](../../../data/tx_full_pvt45.json) |
| [完整TX三处眼图](tx_parallel_serializer_eye.png) | 实际字捕获接入v3、完整树和驱动后，位序/眼图如何？ | 理想2GHz输入、真实偏置/PDK R tt，256 bit载荷；已测条件见[设计](../../../design/tx_parallel_serializer.md) |
| [guard映射时序可行性](tx_ingress_timing_feasibility.png) | 加强驱动或加buffer能解决当前时序预算么？ | 四个HD库、10fF、四个映射对照；假定接口预算，非45 PVT；SS仍有负setup裕量 |
| [末级边界框图](tx_final_retime_boundary.png) | 首级半字与末级偶/奇保持怎样区分，2G在哪改？ | 端口/局部跟随器/加载与候选中间级位置；非验收波形 |
| [末级允许窗](tx_final_retime_window.png) | 后移关闭是否能恢复FS受检事件？ | 四基线＋20平移；两条件两事件理想电压回放 |
| [实际缓冲级数](tx_final_clock_stage_comparison.png) | 真实额外中间级带来多少延迟及保持改善？ | extra1/2/3局部数学复制，先校准原级；完整TX候选另行验证 |
| [输出尾宽/负载比较](tx_final_clock_output_sizing.png) | c2g减幅后是否保留时序与输出？ | extra3固定，24/300、18/240、16/240；TT/FS各两事件；局部未评分 |
| [各层CML摆幅图](tx_cml_amplitude_map.png) | 超过400mVpp的节点分布在哪些模块？ | 完整120ns来源的40–100ns观察；数据下限不评分；[尺寸边界](../../../design/tx_cml_amplitude.md) |
| [输出尺寸完整TX对照](tx_clock_output_full_confirmation.png) | 缩摆幅是否保住完整字流和眼图？ | TT/FS、extra3、WT24/R300与16/R240；新候选FS散布失败，不采用 |
| [最差字内部波形](tx_clock_output_edge_detail.png) | 新旧尺寸的g3、本地关闭、保持和输出分别怎样变？ | FS实际B沿对齐；slot8有新输入交越，slot14沿用slot12，不能混用事件 |
| [减幅后相位扫描](tx_reduced_phase_window.png) | 在当前减幅边界上后移选择时钟能否恢复散布？ | TT/FS、原样校准后12点、word18八位；+20ps开始局部满足，非完整TX/实际延迟单元验证 |
| [减幅下实际缓冲级](tx_native_reduced_clock.png) | 实际extra4/5能否实现所需延迟并保住减幅？ | TT/FS的r2g录制切片；extra3原样校准；extra5局部恢复；后续完整MOS45点见上 |
| [Xe2单轴尺寸卡](tx_buffer_local.png) | 减尾宽和减R各怎样改变幅度与时序？ | TT/FS实际加载切片校准，单改仍超幅；八位合同 |
| [Xe2联合尺寸卡](tx_buffer_joint.png) | 两项合用的模型预测是否成立？ | 338/316mVpp、模型残差<0.3mV；下一Xe3仍超幅 |
| [沿链减幅与时序](tx_buffer_cascade.png) | 相邻级一起减幅会累积成什么？ | 五级FS虽八位零错，69.75mV/0.212UI失败、不采用；[报告](../../../design/tx_buffer_cascade.md) |
| [均匀尾宽14/14.4](tx_buffer_sizing.png) | 保留更多增益能恢复FS时序么？ | TT/FS局部八位；FS散布仍失败 |
| [保留增益比较](tx_buffer_gain_search.png) | 尾宽15/R320与15.6/R300的取舍如何？ | 两点均未满足FS局部散布 |
| [分级尾宽](tx_buffer_taper.png) | 首级限幅、后级保留增益是否有局部交集？ | 两候选八位窗满足；完整回接仍失败 |
| [局部尺寸约束交叠](tx_buffer_tradeoff.png) | 均匀与分级方案落在什么可行区？ | TT幅度/FS八位时序的局部观察；不是45点资格 |
| [尺寸模型缺口](tx_buffer_sizing_gap.png) | 局部幅度模型漏掉了哪些完整链路约束？ | 完整FS焊盘散布失败、SS冷内部超幅；两端逐位传播与[联合规划合同](../../../design/tx_buffer_sizing.md) |
| [动态模型留出误差](tx_buffer_dynamic_model.png) | 单级拟合能否连续预测四级幅度和延迟？ | TT/FS e0–e3，四组留出profile；重末级/共模尚缺，非尺寸资格 |
| [重末级输入管宽](tx_buffer_heavy.png) | WN增加带来的gm、前级负担、延迟、余量和功耗如何取舍？ | TT/FS，Xe4 WN24/32/40、冻结旧generic R/driver强输入卡；无新尺寸采用，弱输入/独立共模仍缺 |
| [实际负载弱输入与共模](tx_loaded_clock.png) | 两角的幅度、传播、共模和局部功耗如何随输入/电阻实现变化？ | FS热/SS冷，四输入×三种R，Xe3/e4/Xout与当前driver负载；24分支仅局部时钟通过；[报告](../../../design/tx_loaded_clock.md) |
| [实际负载模型留出误差](tx_loaded_clock_model.png) | 差分和共模分开拟合后能否预测组合点及三级连续推演？ | FS/SS留出最大沿误差3.13/0.91ps，SS电压误差36.13mV；12/18拟合触边，不能选尺寸 |
| [后级实际共模激励](tx_loaded_cm_excitation.png) | 入口−25mV实际在Xe4和Xout留下多少独立刺激？ | 两角/三R的原样及弱输入配对；后级均值约+0.22mV及近零，非各级独立扫描 |
| [后级直接共模响应](tx_direct_stage_cm.png) | 直接给Xe4或Xout输入−25mV时，实际加载的幅度/延迟如何变？ | 两角/三R，零偏基线校准；18/18局部时钟通过，幅度变化≤0.717mV，非AC PSRR或实际移位器 |
| [FS](tx_loaded_cm_fs_waveforms.png) / [SS](tx_loaded_cm_ss_waveforms.png) 留出波形 | 电压误差和交越误差是否同时改善？ | 旧组合留出、fixed_long末级；SS交越误差抵消伴随更大电压误差，未改模型 |
| [末级消费方基线](tx_retime_demand_baseline.png) | 保留当前driver/整个载荷后，切片是否复现完整TX？ | FS/SS两角，单端<0.94mV、绝对沿<0.19ps；自然映射正确 |
| [FS相位与幅度需求](tx_retime_demand_fs_surface.png) | 两端门槛能否由同一个时钟输入满足？ | 八点/256bit，+20ps×1.1点满足但焊盘仅0.74ps余量；物理尺寸未选 |
| [SS需求对照](tx_retime_demand_ss_surface.png) | 强条件可以同步提高时钟幅度么？ | 八点眼图/位序均满足；红叉仅表示424mVpp越过旧幅度筛查，上界复核中 |
| [最差边沿与数据历史](tx_retime_demand_events.png) | 最早与最晚转换都来自新g3数据么？ | FS bit212沿用偶分支值，bit296为新值；关闭间隔非setup门限 |
| [供电与相对时序筛选](tx_relative_timing_screen.png) | 同位号的关闭−数据到达随三档电压如何变化？ | 45条旧波形、每组三电压64个新事件；最大相邻0.1108ps/mV在FS冷；非AC PSRR/建立保持资格 |

图名按对象与用途命名，UTC运行身份在对应数据索引中。当前结论见[完整字入口](../../../design/tx_word_capture.md)、[关闭切片](../../../design/tx_launch_hold.md)。图脚本与来源哈希放在各自小数据中，`.svg`可用于导出。
