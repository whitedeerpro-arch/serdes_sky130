# 系统结构与开发依赖框图

主要结构浏览入口已换成[交互设计工作台](../../../web/design/index.html)，按SerDes→一级模块→子模块展开，并在模块下保存模型、参数、迭代与证据。以下静态图保留为参考；后续以模块边界和局部改进组织开发。

静态图的框号与[模块地图](../../overview/development_map.md)对应，信号和控制关系用箭头表示。验证边界与数字统一见[当前状态](../../status/current.md)。工作台的画布展示模块归属，证据面板提供图表与报告。

| 框图 | 内容 | 可编辑图源 |
|---|---|---|
| [交互工作台预览](design_workspace.png) | PLL 分频子模块的后仿波形、版图和报告入口 | [HTML/CSS/JS](../../../web/design/README.md) |
| [时钟／偏置／TX](clock_tx_blocks.png) | r6q PLL、偏置与预充、v3 选择时钟和 TX 信号路径 | [DOT](clock_tx_blocks.dot) |
| [RX／校准](rx_blocks.png) | 采样、W40 物理读出、CDR 与宿主异步 FIFO | [DOT](rx_blocks.dot) |
| [开发依赖](closure_workflow.png) | 先约束/边界、再当前变体PVT、动态/统计与系统实现 | [DOT](closure_workflow.dot) |

重新渲染（仓库根目录，Graphviz；PNG与SVG分别生成）：

```bash
dot -Tpng -Gdpi=130 docs/figures/system/clock_tx_blocks.dot -o docs/figures/system/clock_tx_blocks.png
dot -Tsvg docs/figures/system/clock_tx_blocks.dot -o docs/figures/system/clock_tx_blocks.svg
```

其余两张使用各自同名 `.dot`。日期仅用于核对记录和数据快照，图按结构/用途命名。
