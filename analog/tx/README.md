# 发送端

先建立 [16:1 电流舵串化器](serializer/README.md)。
PLL/时钟、并行字捕获、串化树和外部线驱动器分开验证，再进行真实负载联调。

后续先补[输出驱动](output_driver/README.md)与通道接口，再进入RX；边界及编码开销见[链路推进路线](../../docs/history/tx_output_stage_and_link_plan.md)。
