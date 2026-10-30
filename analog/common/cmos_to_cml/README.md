# CMOS → CML

明确输入逻辑电平、偏置和差分输出负载。

已有静态数据转换原型 `spice/cmos_to_cml_data.spice`，用于串化夹具中的250MHz并行输入。
当前完成指定集成向量测试；独立输入范围和负载表征仍待完成。
结果见 [16:1串化器](../../../docs/history/serializer16_first_results.md)，接口见 [架构](../../../docs/overview/architecture.md)。

spice/ 保存晶体管或无源实现，behavioral/ 保存行为模型，schematic/ 保存原理图，layout/ 保存版图，tb/ 保存测试。

| 测试项 | 层次 | 收集指标 |
|---|---|---|
| [functional](tb/functional/case.toml) | block | differential_swing, output_common_mode, propagation_delay, duty_cycle, power |
| [load_range](tb/load_range/case.toml) | block | swing_vs_load, delay_vs_load, maximum_verified_rate |

结果：`results/analog/common/cmos_to_cml/<case>/<run_id>/`。规格和具体测试台尚待填写，以上不是已通过的验证。
