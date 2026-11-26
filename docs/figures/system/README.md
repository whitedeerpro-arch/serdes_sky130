# 系统结构、片级规划与顶层协同仿真图集

[返回图目录](../README.md) · [当前状态](../../status/current.md) · [模块地图](../../overview/development_map.md)

主要交互式浏览入口为 [设计工作台](../../../web/design/index.html)（说明见 [web/design/README.md](../../../web/design/README.md)）。本目录保留静态架构参考框图、开发工作流图、片级规划图与 4G/5G 顶层全链协同仿真结果图：

| 图表 | 内容与用途 | 补充文件 |
|---|---|---|
| [design_workspace.png](design_workspace.png) | 交互式设计工作台界面预览（模块拓扑、参数与证据面板） | [web/design/README.md](../../../web/design/README.md) |
| [serdes_chip_floorplan_20261123.png](serdes_chip_floorplan_20261123.png) | 4G `v1.0` 片级宏摆位与 12 组阻尼去耦规划总图（`845.4 × 601.4 µm`） | [片级版图报告](../../layout/chip_floorplan_20261123.md) |
| [serdes_4g_top_cosim_20261123.png](serdes_4g_top_cosim_20261123.png) | 4.0 Gb/s 同源 PLL→TX→`C2_loss6`→RX 顶层模拟短窗联调波形 | [verify_4g_full_chain.py](../../../verification/top_cosim/verify_4g_full_chain.py) |
| [serdes_5g_top_cosim_20261124.png](serdes_5g_top_cosim_20261124.png) | 5.0 Gb/s 顶层全链协同仿真眼图与波形 | [verify_5g_full_chain.py](../../../verification/top_cosim/verify_5g_full_chain.py) |
| [clock_tx_blocks.svg](clock_tx_blocks.svg) | 时钟 / 偏置 / TX 模块关系参考框图（历史架构视图） | — |
| [rx_blocks.svg](rx_blocks.svg) | RX / CDR / 校准模块关系参考框图（历史架构视图） | — |
| [closure_workflow.png](closure_workflow.png) | 开发与验证收口依赖流程（约束 → PVT → 动态/统计 → 物理签核） | [SVG](closure_workflow.svg) · [DOT](closure_workflow.dot) |

如需修改并重新渲染 `closure_workflow`（仓库根目录，Graphviz）：

```bash
dot -Tpng -Gdpi=130 docs/figures/system/closure_workflow.dot -o docs/figures/system/closure_workflow.png
dot -Tsvg docs/figures/system/closure_workflow.dot -o docs/figures/system/closure_workflow.svg
```
