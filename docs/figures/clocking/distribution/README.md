# 时钟抽出与分发

[返回图目录](../../README.md)

本专题的图按用途与局部适用范围列出；当前设计版本由原报告及阶段/冻结清单判定。

| 图组 | 用途 | 适用范围／来源 |
|---|---|---|
| physical_clock_distribution_ui [PNG](physical_clock_distribution_ui.png) / [SVG](physical_clock_distribution_ui.svg) | 局部联调 | 实际相位微调/扇出缓冲及旧锁存参数1024bit记录；不替代冻结版256bit证据；[报告](../../../physical_clock_distribution_results.md) |
| pll_replay_clock_phases_ui [PNG](pll_replay_clock_phases_ui.png) / [SVG](pll_replay_clock_phases_ui.svg) | 演进记录 | 历史PLL时钟回放及串化比较；含源理想化/记录处理边界；[报告](../../../pll_clock_replay_results.md) |
| vco_receiver_eight_phases [PNG](vco_receiver_eight_phases.png) / [SVG](vco_receiver_eight_phases.svg) | 接口表征 | 时钟接收器及VCO/分频接口；不能用作静态数据转换验收；[报告](../../../cml_clock_receiver_results.md) |
