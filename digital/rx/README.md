# RX数字前级原型

主架构采用半速四相采样、Alexander/bang-bang鉴相、逐路数字相位/频率跟踪。已有交接、投票、Q16二阶跟踪、训练字对齐与16位串转并RTL。长时闭环使用行为采样/时钟plant，物理整机收口尚未完成。

pi_step_commutator接受ctrl_clk域的valid/ready与advance方向，只支持±1码。温度计fine_b每次最多改变一个单元，select_a/b为寄存器onehot。细调到端点后等待GUARD_CYCLES再切空闲相位，或先准备零电流支路并等待后再加权。done表示所有交接/建立完成；applied表示相位步进已经发生，两者在某些边界不是同一周期。不接受busy期间未握手的脉冲，不提供请求队列。

默认控制250 MHz、GUARD_CYCLES=1给4 ns保护时间。参数必须≥1；控制周期乘保护周期必须大于模拟端点恢复/锚点建立时间。reset仅用于RX离线状态；使能前需保证偏置/时钟稳定。该模块不是异步请求同步器或物理安全边沿重定时器，也没有证明标准单元在250 MHz完成时序收敛。

bbpd_window_vote接受**已降速、重定时并按时间排序**的16个数据样本和16个边沿样本，bit0最早。edge[k]位于data[k-1]和data[k]之间，首项前一个数据由previous_data提供。相邻数据相等时不投票；有跳变时edge等于后一个数据则时钟偏晚，投+1使PI超前，等于前一个则投-1。输出[-16,16]和跳变数。16 UI恰为4 ns；前面的物理解复用、CML→CMOS与对齐电路尚未实现，不能直接把四路2 GHz输出接到本模块。

验证包含3种GUARD下各390次正反向步进、全扇区/回卷/方向反转，单元fine更新与空闲支路不变式；投票有符号极值、互抵、无跳变、跨窗口首样本及invalid bundle。另将真实模拟采样输出数值判读后形成投票向量，验证方向一致。已做Verilator lint与Yosys proc/opt/check；不代表综合映射或时序签核。

RTL输出轨迹截取后驱动真实MOS PI/采样器的正反向短窗，端口20 ps斜率为夹具假设，物理控制驱动器/重定时未实现。

cdr_phase_frequency实现频率积分和相位债务，按实际applied/done反馈执行±1码；rx_cdr_loop连接投票器、滤波器与交接器。控制运行在恢复字域，标称250 MHz。无跳变时保持频率预测，超时清质量标志；range_limited需要离线复位后重新捕获。参数、质量迟滞和10组长时结果见[闭环记录](../../docs/history/rx_cdr_closed_loop.md)。

rx_deserializer16消费已重定时的顺序pair，bit0较早。重复4个可编程b5e3训练字确定字边界，16位输出bit0仍最早。数据连续移位，不能用瞬时locked静默丢弃pair；word_valid是恢复pair时钟域的使能，不是异步系统时钟。2 GHz库映射、训练比较路径与时钟树尚无STA结果；公共系统接口需要单独时序/CDC。

rx_word_map把物理读出（analog/rx/sampler/spice/rx_readout_deser16.spice，8通道×4级=32位，字时钟w）按结构决定的位映射排成时间顺序的16数据+16边沿，edge[0]与previous_data取自上一字，直接接投票器。rx_word_align16在{上一字,本字}中按训练字0xb5e3找字边界（同一偏移连续4次），输出比输入晚一字。tb_rx_word_path覆盖16种窗口起点、早/晚边沿和训练→payload切换。

tb_rx_cdr_closed_loop用既有PI实测曲线驱动行为采样事件，运行实际RTL，100 µs检查多圈、频偏、时延、确定抖动、同码和字流。它不包含真实晶体管/PCB/PLL长闭环。tb_rx_deserializer16覆盖16种bit偏移，tb_cdr_status检查保持、超时、恢复与限幅。失败探索快照保留在results，最终批次由结果文档指定。

结果入口：[采样器与PI控制](../../docs/history/rx_sampler_control.md)。
