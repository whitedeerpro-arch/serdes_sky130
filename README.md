# Simple SerDes

SKY130、1.8 V、4 Gb/s NRZ SerDes：250 MHz 参考 → 2 GHz 四级 CML 环振 PLL → 16:1 CML 串化 → 100 Ω 线驱动；RX 为端接/CTLE → PI → 四相半速采样 → 数字 CDR → 16 位解串。

接手先读 [AGENTS.md](AGENTS.md)，然后按下面三项进入工作：

| 需要知道 | 入口 |
|---|---|
| 当前采用什么、已验证到哪里 | [当前状态与实际驱动边界](docs/status/current.md) |
| 接下来做什么、完成标准和依赖 | [执行计划](docs/status/prelayout_plan.md)、[项目完成目标](docs/status/serdes_completion_goal.md) |
| 如何工作、资料归哪里 | [项目工作流](docs/status/workflow.md)、[完整文档导航](docs/README.md) |

技术主线以 [Fable 的架构决定](docs/status/architecture_decisions.md)为准。当前模块的采用与验证数字统一维护在 current.md；源码、参数和历史证据分别保留身份。近期主线是 r6 原生闭环，随后由锁定的 PLL 在同一 deck 驱动完整 TX 动态数据；物理实现与寄生校准支撑这条主线。

## 规格与架构

45 个 MOS/VDD/温度条件全部满足功能与规格；仅允许高低温下 4 Gb/s BER 按既定政策处理。功能、PVT、噪声/抖动优先于 PPA。门槛、测量节点与预算见[规格](docs/overview/spec.md)，连接及时钟域见[架构](docs/overview/architecture.md)。

**[打开交互设计工作台](web/design/index.html)**，按 SerDes → TX / Bias / RX / PLL / Channel → 子模块浏览边界、模型、设计资料和迭代。模块索引见[模块地图](docs/overview/development_map.md)。

![模块设计工作台](docs/figures/system/design_workspace.png)

## 常用入口

| 内容 | 位置 |
|---|---|
| 模块设计与工作修订 | [模块地图](docs/overview/development_map.md)、[版本与基线](docs/overview/revisions.md) |
| PLL 物理实现 | [PLL r6 版图](docs/layout/pll_r6.md)、[版图独立审阅](docs/layout/README.md)、[版图工具](analog/layout/README.md) |
| 执行/接手与具体任务 | [协作登记](docs/work_packages/collaboration.md)、[工作包](docs/work_packages/README.md) |
| 风险与历史 | [稳定问题编号](docs/status/open_issues.md)、[历史记录](docs/history/index.md)、[变更日志](docs/status/changelog.md) |
| 验证与测量 | [方法](docs/verification/methods.md)、[测量约定](docs/verification/measurement_conventions.md)、[统计](docs/verification/statistics.md)、[PVT覆盖口径](docs/verification/pvt_coverage.md) |
| 图与结果 | [图目录](docs/figures/README.md)、[小数据](docs/data/)、[结果与归档](results/README.md) |

## 环境与常用命令

```bash
uv sync
uv run python -m serdes_flow.design_viewer --open
uv run python -m serdes_flow.work_packages list
uv run pytest -q tests/test_doc_links.py tests/test_design_viewer.py tests/test_work_packages.py
```

工作台[使用说明](web/design/README.md)。ngspice 使用 `/opt/ngspice47/bin/ngspice`，其余路径见 [pdk.toml](config/pdk.toml)、[tools.toml](config/tools.toml)及 AGENTS.md。新 campaign 遵循实际终点检查、逐条件续跑和全机并发限制；方法细节集中在验证文档。
