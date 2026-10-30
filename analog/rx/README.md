# RX开发入口

先做输入终端/共模接口和线性CTLE，再做真实采样器，最后接CDR和解串。已有CTLE、四相采样、PI、静态CMOS读出和公共pair对齐；数字CDR与16位串转并已做实际RTL/行为plant闭环，整机物理收口待完成。

- `input/`：两只50 Ω到外部vcm，替换原测试夹具的终端；真实共模参考/缓冲尚未实现。
- `ctle/`：LVT差分输入、两个镜像电流sink、源极R/C退化，四档实际MOS开关电容。
- `sampler/`：真实CML四相采样、静态CMOS读出与真实公共时钟pair重定时；完整16UI降速/数字映射时序待完成。
- `pi/`：真实MOS相位选择/电流加权插值与两对差分时钟输出；外部控制码测试，尚无硬件译码/重定时。
- `cdr/`：模拟顶层预留；实际RTL数字CDR与串转并在digital/rx，TX PLL锁定不代表RX已恢复时钟。
- `top/`：已有真实TX驱动器/PCB/RX加载联合测试，源边界在TX隔离buffer输入；实际采样器/CDR顶层仍待设计。

接口、证据和下一步见[RX前端首版](../../docs/history/rx_frontend_first_design.md)。

真实加载与裁剪边界对照见[TX—PCB—RX联调](../../docs/history/rx_loaded_link.md)。

固定4Gb/s多端口的PLL共享、PI补偿频差与下一步实现见[CDR架构选择](../../docs/history/rx_cdr_architecture.md)。

采样器、真实PI/CTLE加载及RTL交接轨迹回放见[当前结果](../../docs/history/rx_sampler_control.md)。

后续CMOS判决读出、实际RTL长时CDR闭环和16位字流见[闭环结果](../../docs/history/rx_cdr_closed_loop.md)。
