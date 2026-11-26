# 项目文档入口

接手顺序：仓库 [AGENTS.md](../AGENTS.md) → [当前状态](status/current.md) → [执行计划](status/prelayout_plan.md) → 对应模块。先明确本轮要消除的设计未知，再读所需证据。

## 每类信息只维护一处

| 要回答的问题 | 权威入口 | 更新时机 |
|---|---|---|
| 最终要完成什么、什么算完成 | [项目完成目标](status/serdes_completion_goal.md) | 范围或验收政策改变 |
| 必须满足什么规格 | [规格与 PVT 政策](overview/spec.md) | 所有者确认规格变化 |
| 为什么选这条技术路线 | [架构与接口](overview/architecture.md)、[架构决定](status/architecture_decisions.md) | Fable 采纳技术决定 |
| 当前采用什么、实际上验证到哪里 | [当前状态](status/current.md) | 接受新结果或采用修订后；包含边界与证据链接 |
| 接下来做什么、首片 DFT 与流片验收顺序 | [执行计划](status/prelayout_plan.md) | 一个任务交付、遇到阻塞或主线调整后 |
| 模块在哪里、该找哪份设计说明 | [模块地图](overview/development_map.md)、[工作台](../web/design/index.html) | 模块或资料归属改变 |
| 该电路的原理、约束、取舍和局部证据 | [模块设计索引](design/README.md)；物理实现见 [版图入口](layout/README.md) | 该模块的一次迭代产生可复核结果 |
| 采用的源码路径、面积与证据索引 | [版本与基线](overview/revisions.md)、[芯片面积](overview/area.md)、[5G 签核台账](../results/catalog/serdes_5g_signoff_20261126.json)、[主线工作修订](../config/mainline_working_revision.toml) | 电路或参数被采用时 |
| 本轮如何执行、如何判断与接手 | [工作流](status/workflow.md)、[验证方法](verification/methods.md)、[测量定义](verification/measurement_conventions.md) | 方法或接口约定变化 |
| 谁正在改什么、可用仿真名额与交接 | [协作与接手](work_packages/collaboration.md) | 开工、资源交接或停止时 |
| 某问题为什么仍未关闭 | [问题登记](status/open_issues.md) | 问题边界或关闭依据改变；编号保留 |
| 延后或下一代候选项 | [下一版候选](status/next_iteration.md) | 范围升降级时 |
| 历史路线怎么演进过来的、有哪些踩坑经验 | [演进笔记与改动备忘](status/evolution_notes.md) | 路线大切换或阶段收口时随手补记 |
| 图、指标和原始/退役结果索引 | [图目录](figures/README.md)、[小数据](data/)、[结果索引](../results/catalog/README.md) | 发布结果或退役产物时 |

“当前数字唯一”指项目级的采用状态和验证汇总；模块文档仍保留支撑它的详细分析、参数推导和按修订标识的测量记录。规格中的门槛、配置中的机器参数不因汇总去重而删除。发生冲突时先核对实际 deck、输入身份、完整波形和测量口径，再修正当前状态；不能按文件时间选结论。

## 目录边界

- `overview/`：规格、架构、面积、模块导航与版本基线；
- `status/`：完成目标、当前状态、执行计划（含首片 DFT 与流片验收顺序）、架构决定、工作流、问题登记与下一版候选；
- `design/`：活跃模块设计说明与局部边界；
- `layout/`：片级与宏级物理实现、2026-11-26 实装复核及模拟版图准则；
- `verification/`：测量定义、PVT/MC 统计、尺寸流程与 $g_m/I_D$ 优化工具；
- `work_packages/`：当前协作登记与仿真资源交接（[collaboration.md](work_packages/collaboration.md)）；
- `figures/`、`data/`：跟踪的签核图表与小数据。

历史演进日志、早期全 CML 阶段快照与 `v0.1` 冻结目录不再保留在工作树中，完整追溯保存在 git 历史（标签 `v1.0` 与提交 `b10e989`）。新增文档先选归属；能够更新已有模块入口时不另建“最新状态”。
