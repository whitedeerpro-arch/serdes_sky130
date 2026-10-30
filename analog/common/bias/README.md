# 偏置与电流参考

先表征电流、顺从范围、启动及失配，再供其他电路复用。

状态：待设计。接口草案见 [架构](../../../docs/overview/architecture.md)。

spice/ 保存晶体管或无源实现，behavioral/ 保存行为模型，schematic/ 保存原理图，layout/ 保存版图，tb/ 保存测试。

| 测试项 | 层次 | 收集指标 |
|---|---|---|
| [dc](tb/dc/case.toml) | block | reference_current, compliance_range, output_resistance, power |
| [startup](tb/startup/case.toml) | block | startup_time, steady_current, startup_success |
| [mismatch](tb/mismatch/case.toml) | block | current_spread, branch_mismatch |

结果：`results/analog/common/bias/<case>/<run_id>/`。规格和具体测试台尚待填写，以上不是已通过的验证。
