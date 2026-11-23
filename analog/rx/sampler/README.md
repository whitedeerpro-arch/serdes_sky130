# 半速四相CML采样器

每UI=250 ps。数据时钟2 GHz的正/负边沿分别采D0/D1，提前90°的边沿时钟正/负边沿分别采E0/E1。时间关系：上一D1→E0→D0→E1→D1，每段约125 ps。

真实电路由输入隔离buffer、两组共模下移source follower、四个主从CML DFF组成。依赖现有divider的锁存器原语，不改冻结版本。外部时钟高共模约1.65 V，经source follower下移至约0.95 V，再驱动堆叠锁存器时钟管。

- 输入buffer W24 µm、尾W12 µm、600 Ω。
- 每个DFF由两个真实CML latch组成，数据W16 µm、保持W48 µm、时钟W32 µm、尾W12 µm、600 Ω。
- 时钟移位每腿source follower W40 µm、sink W8 µm。
- 四对原始输出仍为CML数据；独立测试负载5 fF/腿。后续新增静态数据CML→CMOS与公共时钟pair对齐；物理16UI降速与整机晶体管闭环仍待完成。

输入数据隔离buffer会引入真实延迟；不能用外部理想时钟的几何125 ps位置直接视为最终采样中心。PI需要补偿数据与时钟路径的共同固定延迟，数字鉴相的时序定义基于已经对齐的真实样本。

两个SPICE模板为本次已运行夹具，替换工程路径/PDK/corner即可复现。functional模板包含确定PRBS7和理想时钟；pi_loaded模板包含真实PI、真实CTLE及20 fF参考CTLE，理想源位于CTLE输入，尚无PCB/原生PLL。所有R/C为名义理想元件，尚无PVT/噪声/失配测试。

结果：[采样器与PI控制](../../../docs/history/rx_sampler_control.md)。

静态数据转换器为common/cml_to_cmos/spice/cml_to_cmos_data.spice，保留DC状态；rx_cmos_pair_align.spice包含真实时钟接收/缓冲、四个CMOS DFF和E0延迟，两级反相器各20 fF。公共时钟选边沿相位的反极性，以配合实际转换与DFF关闭延迟；本方案只做了TT名义短窗，不能据此保证PVT下周期对应。

新增cmos_readout和cmos_aligned模板及[当前闭环/接口结果](../../../docs/history/rx_cdr_closed_loop.md)。数字CDR与串转并已做实际RTL长时闭环，采样/时钟plant为行为模型，不是整个模拟接收机闭环。
