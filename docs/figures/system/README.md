# 系统结构与开发依赖框图

主要结构浏览入口已换成[交互设计工作台](../../../web/design/index.html)，按SerDes→一级模块→子模块展开，并在模块下保存模型、参数、迭代与证据。以下静态图保留为参考；后续以模块边界和局部改进组织开发。

详细资料入口：[模块状态与边界](../../overview/development_map.md)。静态图的框号与该页状态表对应；颜色表示当时的工作结构/迭代状态，不表示验收通过。交互工作台使用独立的模块层次与归属颜色。

| 框图 | 内容 | 可编辑图源 |
|---|---|---|
| [交互工作台预览](design_workspace.png) | 自上而下的模块浏览、边界、模型参数和迭代面板 | [HTML/CSS/JS](../../../web/design/README.md) |
| [时钟／偏置／TX](clock_tx_blocks.png) | PLL不同修订、参考分配、TX数据入口与v3候选 | [DOT](clock_tx_blocks.dot) |
| [RX／校准](rx_blocks.png) | 当前物理deser16路线、理想锚点、生产/冒烟参数、缺失CDC | [DOT](rx_blocks.dot) |
| [开发依赖](closure_workflow.png) | 先约束/边界、再当前变体PVT、动态/统计与系统实现 | [DOT](closure_workflow.dot) |

重新渲染（仓库根目录，Graphviz；PNG与SVG分别生成）：

```bash
dot -Tpng -Gdpi=130 docs/figures/system/clock_tx_blocks.dot -o docs/figures/system/clock_tx_blocks.png
dot -Tsvg docs/figures/system/clock_tx_blocks.dot -o docs/figures/system/clock_tx_blocks.svg
```

其余两张使用各自同名 `.dot`。日期仅用于核对记录和数据快照，图按结构/用途命名。
