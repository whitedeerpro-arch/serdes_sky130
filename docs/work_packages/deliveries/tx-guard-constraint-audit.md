# TX guard：输出延迟约束与内部窗口复核

归档 SDC 中 A/B 标签的 `set_output_delay -max 1.3` 被 OpenSTA 作为外部输出延迟扣除，**不是允许 guard 内部使用 1.3 ns**。在理想 4 ns 字时钟、相邻反向沿相隔 2 ns、setup 不确定度 0.05 ns 的该模型下，它留给内部路径的时间是 `2−1.3−0.05 = 0.65 ns`。这一 SDC 假设下报告的负 slack 是真实工具结果；当前证据不足以判断 1.3 ns 是否是正确的物理外部接口合同，也不能将某个替代数值直接当作通过。

## 归档路径的实际算式

以下均为 `results/digital/tx/ingress_timing/20261107T052206Z/` 中 baseline、SS −40 °C、1.60 V、每输出 10 fF 的路径；clock 网络为理想，数字 ns。`-clock_fall` 指输出约束参考的捕获沿，不改变触发器自身的 launch 极性。

| 路径 | launch → capture | 到达时间 | 约束 required time | slack |
|---|---|---:|---:|---:|
| A 寄存器 → `a_valid` | 上升 0 → 下降 2 | 0.83671 | `2−0.05−1.3 = 0.65000` | −0.18671 |
| B 寄存器 → `b_valid` | 下降 2 → 上升 4 | 2.93807 | `4−0.05−1.3 = 2.65000` | −0.28807 |
| ready 寄存器 → `capture_valid` 输出 | 下降 2 → 上升 4 | 4.02753 | `4−0.05−0.5 = 3.45000` | −0.57753 |
| ready 寄存器 → A 寄存器 D | 下降 2 → 上升 4 | 4.02967 | `4−0.05−0.24365 = 3.70635` | −0.32332 |

最后一行是模块**内部寄存器到寄存器**路径：0.24365 ns 是该路径下 Liberty 建立时间，不是 `set_output_delay`。即使重新定义 `capture_valid` 输出的外部延迟，这条内部路径仍按捕获 A 寄存器的实际库 setup 检查。最差 `capture_valid` 端口路径自身的组合延迟为 `4.02753−2 = 2.02753 ns`；仅作算术边界，在其他条件及 0.05 ns 不确定度不变、假设外部 setup 为零的情况下，它仍比 1.95 ns 内部窗口长约 0.07753 ns。这不是修改约束或签核结论。

`capture_data*`、`capture_valid`、`word_ready` 的 max output delay 都是 0.5 ns；对于上述下降沿发射、下一上升沿捕获的端口路径，内部窗口是 `2−0.5−0.05 = 1.45 ns`，不是内部允许 0.5 ns。0.5 ns 作为外部数据路径与接收端 setup 等效预算是暂定假设；`capture_data` 连到模拟字捕获输入，而 `capture_valid` 既作为模块输出也作为内部 A 寄存器输入，其外部消费者尚未确定，不能据名称断言两个端口有相同真实接收端。`word_ready` 是接口输出且模块内部直接反馈，不能仅凭其端口延迟推导内部反馈路径。min output delay 与 hold 检查另有定义，不能跟随 max 数值机械地改写。

## 1.3 ns 来源与实际语义

[字捕获文档](../../design/tx_word_capture.md)中的 1173–1176 ps 是特定 SS 1.65 V −40 °C 测试里**理想 CML 上升沿到 CMOS bank 时钟交越**的传播时间，包含接收器和缓冲；它不是已提取的 A/B 标签接收端 setup 或标签输出的外部数据路径延迟。它可能与 CML 选择沿、数字 guard 参考时钟之间的相位/偏斜有关，但必须先明确参考点、各实际时钟沿和对应接收器，才能决定该传播延迟的符号和归属；不能直接将它加 0.1 ns 当作已验证的 `set_output_delay`，也不能只凭该数断言现有 SDC 一定保守或一定错误。

[RTL 接口说明](../../../digital/tx/README.md)明确：`capture_valid = word_ready && in_valid`，有效数据由模拟入口 DFF 在字时钟上升沿捕获；A 标签在该上升沿采接受标记，B 标签在随后下降沿采 A，禁用时旧 B 可排空。完整 TX 现有测试把标签作为 RTL 事件回放，尚未接物理标签接收器。因此需要分别确定 A/B 标签真正的消费对象、同一字的接收沿或有效窗口、源与接收时钟相对延迟、跨域/缓冲/连线和消费者 setup/hold；在此之前这份 STA 只能说“在给定暂定接口约束下不满足”，无法给出真实接口 pass/fail。

## 可复核的约束建立方式

先以真实字捕获及半字标签消费语义画时间图，明确 `word_clk` 对应的物理时钟节点，分别标出 A/B launch、下游接收沿或电平敏感窗口，以及捕获数据/valid 的同字关系。用实际下游时钟到达与数据路径、接收单元 setup/hold 和不确定度构造对应 generated/virtual clock 与 max/min 约束，并独立验证反向沿和 hold；有真实库/提取模型时优先将接收端纳入联合 STA 或经实际边界波形做电路验证。禁止只移动时钟沿或套 multicycle 来消除负 slack，除非同字捕获、半字排空和 hold 语义均有证据支持。

若单纯把“内部最多 1.3 ns”作为**待验证的另一种假设**，对这些相邻反向沿和 0.05 ns 不确定度，等效的 max output delay 数值为 `2−0.05−1.3 = 0.65 ns`；这只是同一参考平面下的算术换算，不能代替下游合同，也不确定 hold/min 或物理时钟偏斜。它不会自动解决上表的内部 ready→A 寄存器负 slack。应重新生成并独立检查 setup、hold、端点覆盖及实际功耗/负载；在接口未定和四库/1.60 V、理想时钟、未提取模拟 setup/寄生的限制下，任何结果都保持 ungraded。

## 证据

- 归档 [SDC](../../../results/digital/tx/ingress_timing/20261107T052206Z/execution/baseline_ss_n40C_1v60_10ff.sdc)，SHA-256 `89434003149632eb67a29ab58092ee04ef3a71dfdb31be98d033704c397cc9e8`；[路径报告](../../../results/digital/tx/ingress_timing/20261107T052206Z/baseline_ss_n40C_1v60_10ff.log)，SHA-256 `6c13076074ff4ea06767c2d6157858dd21f32f706206f39e74f4305c14cf7111`。
- 映射网表 `execution/mapped.v` SHA-256 `c32888bd3abd63b7ce7dcc556b77c756f3e6360592fd7cc147fc5c591ed80caf`；[SDC 生成脚本](../../../verification/digital/tx_ingress_timing.py) SHA-256 `e575fd8d917624d41d14eae109fdd9670f8ea54a924cf1c0ff1fc9b8101d5968`；[RTL](../../../digital/tx/rtl/tx_ingress_control.sv) SHA-256 `d68cd2d803fda6c2f83a46e62a29ad84b56b783c2ce1e01312bc6ac3a129c3a0`。
- 本次只读已归档报告和电路/RTL，没有运行新仿真或修改原有 SDC、RTL 与结论。
