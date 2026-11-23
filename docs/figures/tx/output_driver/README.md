# TX输出驱动

[返回图目录](../../README.md)

本专题的图按用途与局部适用范围列出；当前设计版本由原报告及阶段/冻结清单判定。

| 图组 | 用途 | 适用范围／来源 |
|---|---|---|
| serializer_output_stage_integration_ui [PNG](serializer_output_stage_integration_ui.png) / [SVG](serializer_output_stage_integration_ui.png) | 接口表征 | 首版线驱动、端接/损耗夹具及实际输入加载；不是全链路RX/CDR；[报告](../../../history/tx_output_stage_and_link_plan.md) |
| tx_line_driver_channel_eyes_ui [PNG](tx_line_driver_channel_eyes_ui.png) / [SVG](tx_line_driver_channel_eyes_ui.png) | 接口表征 | 首版线驱动、端接/损耗夹具及实际输入加载；不是全链路RX/CDR；[报告](../../../history/tx_output_stage_and_link_plan.md) |
| tx_output_driver_ddj [PNG](tx_output_driver_ddj.png) | 散布归因与尺寸图 | 单级输出级+完整TX外围，FS 1.65 V 85 °C；串化器输出回放（边界 `tx_extra5_serializer_output_v1`）只用于时序；`verification/plotting/tx_output_driver_ddj.py` 从 [数据](../../../data/tx_output_driver_ddj.json) 重画；[报告](../../../design/tx_output_driver.md#串化器到焊盘的散布增量2026-11-08) |
