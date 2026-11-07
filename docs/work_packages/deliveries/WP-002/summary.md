# WP-002 事实摘要

提取完成；9 项检查通过、5 项未评级，无失败或缺失。完整输入哈希、带行号的连接表、16 行选择表与检查见 [evidence.json](evidence.json)。这是源代码事实和静态计算，不是模拟时序或设计签核。

- [串化树](../../../../analog/tx/serializer/spice/serializer16_retimed_lowov.spice)四级实例数为 8/4/2/1。按 `sp>sn` 选 B、`sp<sn` 选 A 的理想非反相约定，静态选择 `s250,s500,s1g,s2g` 作为二进制数依次得到 d0…d15，各一次。该表把末级仅在计算中视为理想 MUX，不含锁存历史、延迟或模拟动态，不能证明动态位映射。
- [末级单元](../../../../analog/common/cml_mux/spice/cml_lowov_cells.spice#L65)的 Xla 以 sap/san、Xlb 以 sbn/sbp 分别接 track/hold；选择支路接锁存输出。跟随器的动态延迟和建立保持时间未测。末级重定时锁存器不是并行字入口寄存器。
- 所检查的 [测试台](../../../../analog/tx/serializer/tb/native_clock/tb_native_tx_ngspice.cir.in)数据路径为 d0…d15 → Xconv0…15 → Xtree，没有字入口寄存器。转换器输入由总宽 12 µm 的 LVT NFET 栅和 2/4 µm CMOS 反相器输入栅加载，沟道长均为 0.15 µm；有效输入电容未知。可复用的 [静态 CMOS DFF](../../../../analog/common/devices/spice/cmos_dff_reset.spice#L18)端口为 d、clk、rst_b、q、vdd、vss，正沿触发、异步低有效清零。
- 旧 [native 数据激励](../../../../analog/tx/serializer/tb/native_clock/run.py#L170)使用 13 个字，首个时间中心从满足 settle 的 **src250 输入下降沿加 78.3 ps** 开始，再按 16 个实测 UI 外推；字 0 在 t=0 设置，其后变化位采用中心前后各 10 ps、总宽 20 ps 的斜坡。它不是逐次跟随串化器 c250 下降沿。 [r5_v3](../../../../analog/tx/serializer/tb/native_clock/r5_v3.py#L156)只传入 `[0.0]`，因此仅保持静态首字，未定义动态入口延迟、参考沿或更新窗。
