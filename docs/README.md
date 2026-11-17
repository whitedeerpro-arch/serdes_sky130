# 项目文档入口

接手顺序：仓库 [AGENTS.md](../AGENTS.md) → [当前状态](status/current.md) → [执行计划](status/prelayout_plan.md) → 对应模块。先明确本轮要消除的设计未知，再读所需证据；不要求通读历史记录。

## 每类信息只维护一处

| 要回答的问题 | 权威入口 | 更新时机 |
|---|---|---|
| 最终要完成什么、什么算完成 | [项目完成目标](status/serdes_completion_goal.md) | 范围或验收政策改变 |
| 必须满足什么规格 | [规格](overview/spec.md) | 所有者确认规格变化 |
| 为什么选这条技术路线 | [架构与接口](overview/architecture.md)、[架构决定](status/architecture_decisions.md) | Fable 采纳技术决定 |
| 当前采用什么、实际上验证到哪里 | [当前状态](status/current.md) | 接受新结果或采用修订后；包含边界与证据链接 |
| 接下来做什么、先后依赖和退出条件 | [执行计划](status/prelayout_plan.md) | 一个任务交付、遇到阻塞或主线调整后 |
| 模块在哪里、该找哪份设计说明 | [模块地图](overview/development_map.md)、[工作台](../web/design/index.html) | 模块或资料归属改变 |
| 该电路的原理、约束、取舍和局部证据 | [模块设计文档](design/)；物理实现见 [layout](layout/) | 该模块的一次迭代产生可复核结果 |
| 采用的源码路径、机器参数和数据身份 | [工作修订配置](../config/)、SPICE/RTL | 电路/参数被采用时；不能仅因候选完成就切换 |
| 本轮如何执行、如何判断与接手 | [工作流](status/workflow.md)、[验证方法](verification/methods.md)、[测量定义](verification/measurement_conventions.md) | 方法或接口约定变化 |
| 谁正在改什么、可用仿真名额 | [协作与接手](work_packages/collaboration.md) | 开工、资源交接或停止时 |
| 一项有边界的任务如何交付和复核 | [工作包](work_packages/README.md)、[任务索引](../config/work_packages.json) | 领取、交付和审阅时 |
| 某问题为什么仍未关闭 | [问题编号](status/open_issues.md) | 问题边界或关闭依据改变；编号保留 |
| 过去做过什么、失败与撤回如何追溯 | [历史索引](history/index.md)、[变更日志](status/changelog.md) | 保存一次过程记录或重要变更 |
| 图、指标和原始结果从哪里来 | [图目录](figures/README.md)、[小数据](data/)、[结果索引](../results/catalog/README.md) | 发布结果时 |

“当前数字唯一”指项目级的采用状态和验证汇总；模块文档仍保留支撑它的详细分析、参数推导和按修订标识的测量记录。规格中的门槛、配置中的机器参数、历史数据不因汇总去重而删除。发生冲突时先核对实际 deck、输入身份、完整波形和测量口径，再修正当前状态；不能按文件时间选结论。

## 目录边界

`overview/` 管规格、架构、模块导航和版本关系；`status/` 管目标、当前证据、执行顺序与问题；`design/` 管模块设计；`layout/` 管物理实现；`verification/` 管测量和验证方法；`work_packages/` 管具体任务交付；`history/` 管过程与旧计划；`figures/`、`data/` 管可分享图表与小数据。新增文档先选归属；能够更新已有模块入口时不另建一个“最新状态”。

旧入口继续可访问：[设计恰当性](status/design_readiness.md)转到当前状态与计划；[MC/Bias 阶段目标](status/goal_mc_bias.md)转到历史；[下一版候选](status/next_iteration.md)只记录延后项。[本次整理记录](history/workflow_reorganization_20261113.md)说明迁移和核对范围。
