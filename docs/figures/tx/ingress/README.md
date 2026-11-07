# TX 字入口图

| 图 | 回答的问题 | 范围 |
|---|---|---|
| [单元加载延迟](tx_ingress_loaded_delay.png) | 精简/复位DFF在实际转换器/MUX负载下差多少？ | 6压力×2静态选择状态，120次捕获；理想时钟 |
| [跨字分组保持](tx_staggered_hold_timing.png) | 新h变化时，B组是否仍保持旧字？ | 实际接收/缓冲驱动16位bank，TT原始波形；完整bank另测6压力 |
| [关闭竞争边界](tx_launch_hold_aperture.png) | 数据提前多少会串入新字？正常到达在哪里？ | 固定电压回放，6压力×2事件形状；164平移点；无源阻抗/MC/噪声 |
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

图名按对象与用途命名，UTC运行身份在对应数据索引中。当前结论见[完整字入口](../../../design/tx_word_capture.md)、[关闭切片](../../../design/tx_launch_hold.md)。图脚本与来源哈希放在各自小数据中，`.svg`可用于导出。
