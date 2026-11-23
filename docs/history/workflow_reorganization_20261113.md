# 工作流与文档整理（2026-11-13）

本轮完成项目管理结构与文档入口整理。工程主线继续沿用Fable的决定；本记录不声明SerDes电路已完成，也不把管理任务的goal完成状态转为项目设计通过。

## 发现与处理

| 影响推进的问题 | 处理 |
|---|---|
| 当前数字在README、模块地图、计划、PVT表和工作台多处维护 | current.md负责项目级采用/验证汇总；其他入口链接；模块仍保存详细结论与边界 |
| 完成目标与架构接口仍写旧4bit，执行计划重复旧分频疑点 | 目标/接口对齐r6/5bit；计划按既有验证顺序定义M1–M6、依赖、最小动作及退出条件；旧计划归档 |
| 问题表、工作包、协作日志各自看起来都是主队列 | 执行顺序只在计划；问题表管理稳定风险编号和关闭条件；WP管理有边界交付；协作页管理实际文件/资源/接手 |
| 协作页混入固定2+2配额、旧个人队列和大量临时状态 | 长期流程与短资源登记分开，按全机≤4统一协调；完整旧日志归档，不推断旧进程已经退出 |
| 工作台手工摘要中的数量/失败状态会漂移 | 37个节点保留层次、边界、模型与设计资料；摘要改为结构职责，第一资料入口统一为current.md；重新导出静态目录 |
| 旧设计恰当性、MC/Bias目标、下一版候选仍像当前入口 | 原文保留历史，旧路径改为明确转接；下一版只存候选，不发布当前供电容限 |
| TX汇总混用了不同测量批次 | 完整MOS45数据FS行serializer为103.137781…mV，修正current.md原102.7mV为103.1mV；早期三压力点102.73mV原分析保留 |
| 数字未映射、旧面积估计等容易被误读为当前全局结论 | 当前状态补宿主映射/STA来源，问题表改为实际待闭合项；面积页标注固定历史deck边界 |

文档导航见[docs/README](../README.md)，操作协议见[工作流](../status/workflow.md)，工程下一动作见[执行计划](../status/prelayout_plan.md)。新增任务模板复用既有WP状态和evidence/review机制，没有新建任务数据库。

## 历史保留

以下快照在覆盖入口前从实际工作区读取，包含当时未提交的文档内容；每份Markdown首部留原路径与SHA256，仅为迁移调整相对链接。它们不作为当前调度依据。

| 原入口 | 整理前快照 |
|---|---|
| 模块地图 | [development_map](development_map_snapshot_20261113.md) |
| 当前状态 | [current](current_snapshot_20261113.md) |
| 执行计划 | [prelayout_plan](prelayout_plan_snapshot_20261113.md) |
| 设计恰当性 | [design_readiness](design_readiness_snapshot_20261113.md) |
| 完成目标 | [completion_goal](completion_goal_snapshot_20261113.md) |
| MC/Bias阶段目标 | [goal_mc_bias](goal_mc_bias_20261103.md) |
| 下一版原计划 | [next_iteration](next_iteration_snapshot_20261110.md) |
| PVT逐变体表与旧TX网格 | [pvt_coverage](pvt_coverage_snapshot_20261113.md) |
| 协作约定与日志 | [collaboration](collaboration_20261109_20261113.md) |
| 问题表 | [open_issues](open_issues_snapshot_20261113.md) |
| 版本关系 | [revisions](revisions_snapshot_20261113.md) |
| 工作台原目录数据 | [完整JSON副本](design_catalog_before_workflow_20261113.json)；逐字节保留，字段中的“当前”仅指迁移前 |

原历史正文、发布基线、仿真输出、证据哈希与采用电路没有改写；旧入口路径继续可访问。已有工作区中的布局/电路/工具改动和删除保持原状，没有代为清理、提交或恢复。`pll_coarse_windows.md`只补历史适用范围提示，保留原有未提交分析。

## 核对范围与限制

核对了现有架构决定、规格、入口文档、工作修订与目录；按实际SPICE确认r6 VCO的b0…b4及core的cfg0…cfg4。TX数字直接读取已有小数据，未重新分析全部历史raw；前端辅助脉冲与从零启动的资格区分保留。新增/重排的计划是待执行约定，不表示相应电路任务已派发或已通过。

本轮0次ngspice，无新campaign；机器配置只补当前状态入口注释，解析后的选择与参数保持相同。工作包索引和交付状态未修改，旧WP-007的running字段不被当作实时进程或r6噪声资格。

核对命令与最终结果：

| 核对 | 结果 |
|---|---|
| 全仓Markdown相对路径、工作台资料、工作包协议 | `uv run pytest -q tests/test_doc_links.py tests/test_design_viewer.py tests/test_work_packages.py`：18通过 |
| 工作台静态导出与原边界/模型保留 | `uv run python -m serdes_flow.design_viewer --export`完成；37节点的id/parent/name/subtitle/boundary/planning/iterations与整理前相同，原资料引用全部保留；静态导出与入口对齐 |
| 问题编号、配置参数和新入口锚点 | 33个I编号完整保留；5份工作修订补注释前后TOML解析结果相同；所检查当前入口的13个Markdown标题锚点全部可解析 |
| diff空白检查 | `git diff --check`通过；未代为暂存或提交混合工作区 |

验收只覆盖本次文档/工作流改动。接下来由计划M1-LOOP接续工程工作；领取时重新核对current.md、实际campaign、文件改动与实时资源。
