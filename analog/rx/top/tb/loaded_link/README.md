# 实际加载与后续判决

原tb_tx_channel_rx_ngspice.cir.in为无采样器的100 ns旧夹具，保留其原始证据和边界。

新增PI/采样器/CMOS公共时钟判决的短窗入口与记录见[RX闭环阶段](../../../../../docs/history/rx_cdr_closed_loop.md)。保留真实TX隔离/驱动、封装、AC耦合、C2 PCB、单套终端及CTLE；切点仍在TX真实隔离buffer之前。

复用旧训练结果时，trained_delay_ui是**边沿**延迟。位中心需加0.5 UI，然后才计入采样前buffer/时钟路径的固定偏移。physical_measurement_window_s是窗口边界，不能当作各位中心。

旧夹具已经记录过密集独立V源PWL的慢速问题，采用B源V=pwl(time,完整原始点表)保留相同连续分段线性函数。新记录同样使用B源，未压缩、延长或周期复制输入波形。暂停8 ns保存检查点后resume到完整24 ns，用于确认仿真进度；中止/诊断记录不列入通过结果。
