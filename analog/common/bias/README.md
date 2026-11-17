# 偏置与电流参考

电路迭代、启动、顺从范围及失配的结论见 [Bias 设计](../../../docs/design/bias.md)，实际采用版本与验证边界见[项目当前状态](../../../docs/status/current.md)。本目录已有电路与测试记录，早期“待设计”的占位状态已过期；具体模块资格以证据为准。

物理实现从[版图入口](layout/README.md)进入，区分历史来件与后续 PDK 候选。旧整包总览与生成器已退役，不能作为当前版图验收依据。

spice/ 保存晶体管或无源实现，behavioral/ 保存行为模型，schematic/ 保存原理图，layout/ 保存版图，tb/ 保存测试。

| 测试项 | 层次 | 收集指标 |
|---|---|---|
| [dc](tb/dc/case.toml) | block | reference_current, compliance_range, output_resistance, power |
| [startup](tb/startup/case.toml) | block | startup_time, steady_current, startup_success |
| [mismatch](tb/mismatch/case.toml) | block | current_spread, branch_mismatch |

以上三项为早期测试模板，不是当前验证清单或已通过声明。具体 campaign、规格与结果入口由设计文档维护；运行结果保存在 `results/analog/common/bias/`。
