# TX 有效字保护 RTL review

**接受为独立控制器实现，模拟数据/标签与线驱动blank的接入仍未完成。** 时钟高初态不会被当作预热；至少一个真实下降沿后才允许新捕获。A/B标签分别随正、负沿前进，禁用不会抢先清掉旧B半字。

Terra仅修改RTL、自检bench及交付说明，ngspice配额0。集成者逐项审查组合直通、下降沿许可、上升沿A/下降沿B、异步复位与排空语义，并独立运行参数1/2/3/5，共149项断言。没有新增数据寄存拍；空泡给IDLE_WORD，标签为无效。输入已在PHY域，CDC及clock_good发生器不在此实现中。

一次兼容返工：Verilator/Icarus接受的`COUNT_WIDTH'(...)`常量在本机Yosys0.9解析失败。Terra改用整数常量再位选，行为不变。失败归档`results/digital/tx/ingress_control/20261106T210157Z`保留；修改后`20261106T210244Z`的149项断言、lint及通用结构检查全部通过。

当前v3完整TX采用自然位序，不插旧r2 remap。guard数据与标签波形回放已接候选，但标准单元初步映射暴露SS时序不足，见[时序可行性](../deliveries/tx-ingress-timing.md)；真实标签路径和线驱动blank仍需实现。若复用旧r2已寄存remap，须另行对齐data/valid。停钟/立即abort不能由本控制器独自完成，不将RTL通过转为模拟/PVT/STA通过。
