# 可编辑原理图

**2026-10-29 工作修订：** 下列 29 页 Xschem/PDF 是历史导出，CML 分频内部偏置和尺寸已更新，不能将其视为当前工作网表的一致视图。当前锁存器、时钟移位与偏置的阅读图见 [新版三页 PDF](../schematics/lowov_review/cml_latch_review.pdf)，区别和候选方案见 [结构调研](cml_latch_topology_review.md)。新版是单独核对命名连接的矢量图，尚未同步回 Xschem 库。

第一批为 Xschem 分层电路图，共 29 个子电路、230 个实例。
保留现有 SPICE 的器件尺寸、总宽 W、nf、扩散面积/周长表达式和端口顺序。
已有电路仍以 `spice/` 为依据，原理图是可编辑的对应视图；本次没有改变已有模块的设计参数。

先看 [29 页矢量 PDF](../schematics/pll_schematics.pdf)，或直接打开
[PLL 核心](../../analog/pll/top/schematic/pll_balanced_core.sch)。
静态预览可缩放 SVG；每张图的同名 PNG 保存在 `docs/schematics/png/`。

| 电路 | Xschem | SVG | PDF 页 |
|---|---|---|---:|
| PLL 核心及反馈连接 | [pll_balanced_core.sch](../../analog/pll/top/schematic/pll_balanced_core.sch) | [预览](../schematics/svg/pll_balanced_core.svg) | 1 |
| 四相抽出、接收器与三条有偏置 dummy | [pll_clock_frontend_balanced.sch](../../analog/pll/top/schematic/pll_clock_frontend_balanced.sch) | [预览](../schematics/svg/pll_clock_frontend_balanced.svg) | 2 |
| 四级差分 VCO | [pll_vco_ring4.sch](../../analog/pll/vco/schematic/pll_vco_ring4.sch) | [预览](../schematics/svg/pll_vco_ring4.svg) | 3 |
| CML 延迟单元晶体管电路 | [serdes_cml_delay.sch](../../analog/common/cml_buffer/schematic/serdes_cml_delay.sch) | [预览](../schematics/svg/serdes_cml_delay.svg) | 4 |
| 1:2:4 电容阵列 / 单元 | [cap bank](../../analog/pll/vco/schematic/pll_vco_cap_bank.sch)、[cap unit](../../analog/pll/vco/schematic/pll_vco_cap_unit.sch) | [阵列](../schematics/svg/pll_vco_cap_bank.svg)、[单元](../schematics/svg/pll_vco_cap_unit.svg) | 5–6 |
| CML buffer | [serdes_cml_buffer.sch](../../analog/common/cml_buffer/schematic/serdes_cml_buffer.sch) | [预览](../schematics/svg/serdes_cml_buffer.svg) | 7 |
| CML→CMOS 接收器 | [serdes_cml_to_cmos.sch](../../analog/common/cml_to_cmos/schematic/serdes_cml_to_cmos.sch) | [预览](../schematics/svg/serdes_cml_to_cmos.svg) | 8 |
| 接收器差分增益级 / 时钟恢复级 | [diff to SE](../../analog/common/cml_to_cmos/schematic/serdes_rx_diff_to_se.sch)、[clock restorer](../../analog/common/cml_to_cmos/schematic/serdes_rx_clock_restorer.sch) | [增益级](../schematics/svg/serdes_rx_diff_to_se.svg)、[恢复级](../schematics/svg/serdes_rx_clock_restorer.svg) | 9–10 |
| CML ÷8 / ÷2 / latch | [÷8](../../analog/pll/divider/schematic/pll_cml_prescaler8.sch)、[÷2](../../analog/pll/divider/schematic/pll_cml_div2.sch)、[latch](../../analog/pll/divider/schematic/pll_cml_latch.sch) | [÷8](../schematics/svg/pll_cml_prescaler8.svg) | 11–13 |
| PFD | [pll_pfd.sch](../../analog/pll/pfd/schematic/pll_pfd.sch) | [预览](../schematics/svg/pll_pfd.svg) | 14 |
| CP | [pll_cp.sch](../../analog/pll/cp/schematic/pll_cp.sch) | [预览](../schematics/svg/pll_cp.svg) | 15 |
| LF | [pll_loop_filter.sch](../../analog/pll/loop_filter/schematic/pll_loop_filter.sch) | [预览](../schematics/svg/pll_loop_filter.svg) | 16 |

其余页为 CMOS 门、传输门、DFF/latch 和 MOS 适配器，可从父图继续进入。
完整的文件、端口与参数清单见 [manifest.json](../schematics/manifest.json)。
同一张图内相同名称的网络电气相连，不同层次的同名网络通过明确端口连接。
部分复杂逻辑采用局部网络标签；PLL 反馈路径和关键模拟堆叠同时画出导线。

## 打开和编辑

当前安装 Xschem 2.8.1，项目配置为根目录 `xschemrc`。从项目根运行：

```bash
xschem --rcfile ./xschemrc analog/pll/top/schematic/pll_balanced_core.sch
```

选中子电路按 `e` 进入原理图，`i` 进入符号，`Ctrl+e` 返回。
`schematic_lib/serdes/` 是指向各模块 `.sch/.sym` 的相对符号链接，避免复制两份电路，
也兼容旧版 Xschem 的单层库名查找方式。原文件仍保存在各模块 `schematic/`。

项目移动后可用 `SERDES_PROJECT_ROOT` 指定新根目录；`SERDES_SCHEMATIC_OUTPUT` 可指定导出目录。
这两个变量均只影响本项目配置，不修改用户全局配置或 PDK。

## 导出与一致性

从 [pll_schematic_library.sch](../../analog/pll/top/schematic/pll_schematic_library.sch) 导出完整层次。
它是导出入口，只有一个 PLL 核心实例，不是仿真激励台。
旧版 Xschem 把当前顶层声明写成注释，因此从该入口导出可让实际 PLL 核心作为带参数默认值的 `.subckt` 输出。

```bash
mkdir -p results/schematics/manual
SERDES_SCHEMATIC_OUTPUT="$PWD/results/schematics/manual" \
  xschem -x -r -q -s -n --rcfile ./xschemrc \
  analog/pll/top/schematic/pll_schematic_library.sch
```

首轮生成的可包含库为 [pll_cells.spice](../schematics/pll_cells.spice)，已去掉导出入口的顶层实例与 `.end`。
加载此库时仍需单独加载 SKY130 的对应 corner 和 ngspice 初始化配置。
它是本次导出快照，后续编辑原理图不会自动同步该文件，也不会自动更新原有 `spice/` 源文件。

核对结果：

- [equivalence.json](../schematics/equivalence.json)：29 个子电路、230 个实例的端口顺序、连接、模型、默认值及实例有效参数一致；显式默认参数和 `m=1` 已归一化。
- [geometry_check.json](../schematics/geometry_check.json)：检查全部图中导线端点、重叠、标签和端口的异名接触，未发现冲突；内部交叉但无端点连接的导线允许跨越。
- `results/schematics/<run_id>/` 保存完整导出、日志、原始 SVG、来源快照与 SHA256。最新路径见 [latest_run.txt](../schematics/latest_run.txt)。

这些是原理图与 SPICE 的连接检查，不是版图 LVS，也不是新一轮电气/PVT/噪声验证。
生成过程使用临时内联操作，没有新增 Python 执行或分析脚本。

## PLL 核心与测试夹具

新增两个可复用连接单元：`clock_frontend_balanced.spice` 和 `pll_balanced_core.spice`，
由此前已运行的集成夹具提取连接，核心供电合并为 `vdd`，保守 dummy 保留独立 `vdd_dummy`。
它们的原理图导出与各自 SPICE 一致，但没有以新顶层重新做瞬态资格验证。

预充参考、预充传输门、启动扰动和理想偏置源留在测试台，不画进该 PLL 核心。
核心仍接外部 `vbn/vbp/vbias`，LF 仍为理想 R/C；三条完整有偏置 dummy 也仍是较高功耗的对称参考。
多相全速 CMOS 输出供未来自由分频，反馈路径则维持独立 CML ÷8。

关于预充：混合视图直接设定 LF 两个电容的初始电压，原生电路夹具的 DC 工作点也已把 LF 置于预充状态。
20 ns 后释放预充/复位只定义闭环接管时刻，尚未验证真实上电时 20 ns 能把全部滤波电容充到目标值。
后续的捕获时间同时受 LF 极点/零点、环路增益和初始频差、相差影响。

电气结果及尚未完成的真实 PLL 锁定边界见 [PLL 首轮调试](pll_first_debug.md)。
