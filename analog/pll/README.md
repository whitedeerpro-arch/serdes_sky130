# PLL

PFD、CP、VCO、反馈分频器、环路滤波器和 top 集成。
模块测试在自身 tb/，跨模块和闭环测试在 top/tb/。
已建立四级差分 VCO、CML 分频器、静态 CMOS PFD 和接收器集成原型。反馈默认 2 GHz/8=250 MHz，
默认反馈为 CML 固定 ÷8；自由 CMOS 分频接多相 CML 转换后的最高 2 GHz CMOS 域，时序待验证。
锁定判据和闭环电路尚待实现。

top/tb/vco_receiver/ 已实现 VCO 与真实时钟接收器的联调，用来比较直接连接及额外 CML 缓冲。
它不包含 PFD、CP 或闭环 PLL。

top/tb/divider_pfd/ 使用理想差分时钟驱动真实分频器、接收器和 PFD，已验证默认 ÷8 与 ÷4 接口。
它不包含实际 VCO 或 CP，结果见 [PFD 测试记录](../../docs/pfd_cmos_results.md)。

此前 top/tb/hybrid_divider_pfd/ 实验为三级 CML ÷8，经接收器进入 250 MHz CMOS 后级与 PFD。
结果见 [混合分频记录](../../docs/hybrid_divider_results.md)。旧全 CML 可编程反馈保留为历史探索。
