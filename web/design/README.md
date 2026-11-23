# SerDes 设计工作台

按 **SerDes → TX / Bias / RX / PLL / Channel → 子模块** 浏览设计。每个模块承载输入输出边界、模型规划、参数依据、迭代和证据。PLL 概览保留已完成的顶层集成；近期电路改进挂在相应模块的迭代记录下。

![工作台预览](../../docs/figures/system/design_workspace.png)

## 打开

可直接打开 [index.html](index.html) 浏览已有结构和资料索引；不需要构建或安装前端依赖。

需要在页面中保存迭代、内嵌阅读文档和图片时，在仓库根目录运行：

```bash
uv run python -m serdes_flow.design_viewer --open
```

地址为 `http://127.0.0.1:8765`，可用 `--port` 更换端口。服务仅监听本机。

画布：单击查看模块，双击或点击「模块 ↗」下钻；拖动平移，按钮或 Ctrl+滚轮缩放；「上层」和面包屑返回父级。目录和搜索可直接定位子模块。画布连线表示归属，信号、时钟、负载与假设在「边界」页。

「证据」可直接预览模块波形与版图。点击图可查看原图，点「查看验证边界」可读激励、负载、修订和结论。搜索支持图名，例如 `SAFF-TSPC` 或 `r6 TT`。总览提供当前状态与执行计划入口。

## 数据与归属

| 内容 | 位置 | 维护方式 |
|---|---|---|
| 模块层次、结构摘要、模型规划与资料引用 | [design_catalog.json](../../config/design_catalog.json) | 每个模块用稳定 ID 和父级归属维护。引用表首项指向 current.md；`figures` 登记图、简短适用范围和原报告路径 |
| 采用状态、验证数字与实际驱动边界 | [current.md](../../docs/status/current.md) | 项目级唯一汇总；不在目录数据另抄一份数字 |
| 新增迭代 | `docs/design/iterations/<模块id>/<UTC>_<随机id>.json` | 页面「添加迭代」追加独立记录；保留已有记录 |
| 静态浏览数据 | [catalog.js](catalog.js) | 派生数据，运行下面的导出命令更新 |
| 前端 | [index.html](index.html)、[style.css](style.css)、[app.js](app.js) | 原生 HTML/CSS/JS，无 CDN、框架或包管理依赖 |
| 本地资料与记录服务 | [design_viewer.py](../../src/serdes_flow/design_viewer.py) | Python 标准库；仓库文件读取与模块记录保存 |

```bash
uv run python -m serdes_flow.design_viewer --export
```

每次迭代可填写问题、模型规划、参数/电路修改、验证边界与结论，并附加已有仓库资料路径。阶段为规划、模型、电路、验证或结论。静态浏览模式可导出同格式 JSON；将其以唯一文件名放入对应模块目录后，重新导出即可纳入目录。

新增记录不会自动改变工作修订或宣布某项验证通过。采纳一次改进时，继续更新该模块设计文档、current.md与 `*_working_revision.toml` 的采用参数；结果波形仍按项目约定留在 `results/`。工作台目录保留结构摘要和证据入口，不按“最新运行”隐式切换依据；验证数字直接查 current.md。

## 接手

先从模块的「边界」和「模型与参数」了解问题，再读迭代中的电路、脚本和测量资料。具体参数改进归属叶级模块；跨模块结构决策可归属 PLL、RX 或 TX 等父模块。PLL 的阵列粗码接口与自动搜索控制器分开表示，已有 PLL 集成与后续局部回归分开记录。

测试：`uv run pytest -q tests/test_design_viewer.py`。测试记录使用临时目录；实际前端保存的记录进入仓库文档目录。
