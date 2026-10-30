# 共享激励检查

从项目根目录启动 tb_stimuli_ngspice.cir / tb_stimuli_xyce.cir。
只检查激励和引擎语法，不加载 PDK，不证明 CML/PLL DUT 已工作。
PFD/CP 源已实例化并检查基础时序，更完整的边界随后在模块测试中验证。

预期：CMOS 高电平 1.8 V，差分极值 ±0.4 V，共模 1.2 V，周期 10 ns，斜坡终值 1.0 V。
另检查参考到反馈延迟 1 ns、UP/DN 的 50% 脉宽各 550 ps、UP 到 DN 延迟 5 ns，共十项。
命令及归档方式见 [verification.md](../../docs/verification.md)。
