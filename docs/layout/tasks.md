# 版图任务状态

旧DS绘制批次已撤下，不继续修补或复建。2026-11-13 新的 Gemini 来件已合并进 `analog/`，独立审查与本轮绘制见[版图入口](../../analog/layout/README.md)。当前采用状态见[项目当前状态](../status/current.md)，旧批次归档见[清理记录](batch_status.md)。

本轮已完成来件去重、生成器路径修复、六个叶单元复核与 LDO MIM 阵列绘制。后续先按当前 HV18 r4 SPICE 实现真实 HV/native 器件，检查端口、体端和电阻卡，再组装上层；Fable 的电路/验证主线继续有效。保留的`*_ref.spice`是设计侧参考，不代表已有可用版图；开画前须重新核对当前SPICE/工作修订。

检查工具保留在`verification/layout/`。DRC/LVS、端口连接、体端、器件值及适用PEX都需要独立复核；旧绿色日志不作为新交付的验收凭据。检查器通过也不替代电气功能或电流容量验证。

[教学练习](deepseek_training.md)使用独立seed，仅作练习材料，不是当前生产版图。
