# SerDes 项目完成目标

完成 SKY130A、1.8 V 双速 **4/5 Gb/s NRZ SerDes**（主推 5G Plan-C LC-PLL 路线，保留 4G 无电感环振基线对照）的可实现电路设计、物理实现与流片前可复核验证。项目关闭以以下交付条件为准；完成一次文档整理、单个宏或阶段装配不代表流片签核完成。

## 本版范围与约束

采用范围以[当前状态](current.md)、[版本与基线](../overview/revisions.md)和 [架构决定](architecture_decisions.md)为准。当前 5G Plan-C 与 4G `full_v8` 已完成独立宏签核与核心物理装配；收口阶段按实际分频、供电、Pad/ESD、封装及 TX/RX 负载验收。延后拓展项见[下一版候选](next_iteration.md)。

规格以[规格文档](../overview/spec.md)为准：45 个 MOS PVT 条件全部必须满足功能与适用门槛，按机理补无源角、真实偏置/负载、失配、噪声与版图寄生；唯一允许缩水的是高低温额定线速的 BER。PPA 排在功能、PVT、噪声之后。遇到中等难度的局部修补同时准备替代结构对照，由 Fable 判断是否采用，不自建冲突主线。

## 交付与关闭条件

| 交付 | 完成标准 | 证据位置 |
|---|---|---|
| 采用的实现 | SPICE/RTL、端口、配置与模块说明一致；5G 主线与 4G 对照基线身份清晰 | [版本与基线](../overview/revisions.md)、[主线工作修订](../../config/mainline_working_revision.toml)与标签 |
| 功能与时序 | 5G/4G 按适用场景通过 MOS45 与多角 ±5% OCV STA；串化器/焊盘、位映射、分频/锁定和数据域接口按各自判据成立 | [current.md](current.md) 链接完整运行与台账；失败、未完成与未测单列 |
| 原生接口与冷启动 | 锁定 PLL→动态 TX、RX 原生锚点、ready/粗搜/捕获、掉锁重获、实际失配校准、生产参数 CDR/FIFO 与宿主 CDC 有可复核验证 | 模块/顶层联调、带延时 SDF GLS 与模型校准 |
| 噪声与统计 | 实际尺寸、码、供电、封装与负载下的相噪、RJ/DJ、PDN 噪声、失配 MC 与系统预算一致 | 噪声/统计报告及 [规格预算](../overview/spec.md#抖动与相位噪声预算)；PDK 盲区显式保留 |
| 物理与流片签核 | 完整 Pad Map / ESD / 供电顺序 ERC、全片 Netgen LVS、工艺 DRC/密度/填充/天线、同版静态 IR/EM 与动态供电、填充后敏感网 PEX 与首片 DFT 入口闭环 | [片级报告](../layout/chip_floorplan_20261123.md)、[流片验收顺序](prelayout_plan.md#4-流片前验收顺序) |
| 设计收束 | 受影响角点与接口回归完成，优化 PPA，采用网表与交付版图一致，开放问题按编号关闭或明确边界 | [current.md](current.md)、[open_issues.md](open_issues.md) 与 `results/catalog/` |

## 执行与接手

近期只从[执行计划](prelayout_plan.md)领取下一项，[工作流](workflow.md)规定最小实验、退出条件与状态更新。[协作页](../work_packages/collaboration.md)登记实际文件范围与仿真资源，不在目标页写临时进程或个人队列。长时行为先用模型，再用局部/接口实验校准；整机从零启动长晶体管仿真不作为每步前置条件。
