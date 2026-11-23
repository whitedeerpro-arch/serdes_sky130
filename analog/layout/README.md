# 版图入口

当前采用状态见[项目当前状态](../../docs/status/current.md)，PLL 审阅见[版图文档入口](../../docs/layout/README.md)。模块几何放在各自的 `layout/`；本目录保留共用绘图库和历史交付来源。生成/检查输出放 `results/layout/`，不在源码目录提取。

## Gemini 来件合并

2026-11-13 已将 `analog_ldo_optimized/analog/` 合并进本仓库 `analog/`，并删除原来的重复目录。已有源码逐文件相同，没有覆盖电路改动；嵌套 `to merge` 包中的相同文件只保留模块内一份。导入时六个共用 Python 文件归入 `scripts/`，四张总览归入 `overviews/`。旧 DS 已撤下文件的重复副本只归档，没有恢复到工作目录。

来件来自不能使用 Magic、只能看到少量本地内容的 Web 环境，按排布草案吸收。下面的物理检查定位实现缺口；排布本身的优点、取舍和后续方案见[PLL 排布评估](../../docs/layout/pll_r6.md)。

原始包在 `/opt/serdes_archive/layout_imports/20261113T080522Z/gemini_original.tar.gz`，删除前核对了归档和合并目标。[导入清单](import.json)记录实际去向；原始逐文件清单在同目录 `merge.json`。图中的外观、命名或原说明里的“生产级”不代表验收通过。

该清单记录的是导入时位置。已失效的完整 PLL 草案随后移入[退役归档](../../results/catalog/retired_pll_top_20261117.json)，初始审计按哈希读取原件；VCO 目录的重复 CML buffer 种子改为指向 `common/cml_buffer/layout/` 的相对链接。现行候选仍从模块 README 进入，不从历史来件恢复覆盖。

2026-11-17 已撤下七个旧 suite/打包生成器和六张总览，包括 `ldo_bias_tx_master_overview`。它们使用通用 MOS 绘图、硬编码面积和未验证的器件/等价声明；运行整包还会重新生成已否决的 PLL 顶层。原件与 SHA256 见[退役清单](../../results/catalog/retired_layout_suites_20261117.json)，判断依据和恢复方法见[审查记录](../../docs/history/legacy_layout_retirement_20261117.md)。旧模块 README 的原文也已归档，不再作为现行物理指标。

`scripts/layout_core.py` 仍是当前 PDK 阵列预览和 PLL 绘图工具的公共依赖，继续维护。保留的原始 MAG/TCL/参考网表用于导入审计及明确引用它们的几何种子；禁止从历史整包恢复覆盖现行候选。各模块入口区分历史种子、PDK 迭代与验收证据。

## 首轮独立复核（2026-11-13）

来件 40 个 `.mag` 均只有内部 label，没有 Magic `port` 声明。六个叶单元的实际检查如下；数字为 full-rule DRC 的错误区域数，各规则区域会重叠，不能与规则列表逐项相加。

| 单元 | DRC 区域 | 主要发现 |
|---|---:|---|
| LDO MIM16 | 122 | 电容接触包围、相邻 M3 间距不合规；无导出端口 |
| LDO 参考电阻 | 522 | 接触/通孔不合规；提取为定宽 `high_po_1p41`，不等于当前通用 high_po 参考的几何 |
| 慢尾线滤波器 | 635 | 16 颗 MIM 均提取成 `filtered filtered`，两端短接；另有接触/间距问题 |
| HV18 LDO 核心 | 911 | 提取为普通 1.8 V MOS，未得到设计要求的 HV/native 器件；大量节点短接，32 颗提取 MIM 均两端同网 |
| VCO 变容器 | 6 | 四颗 `cap_var_lvt` 的内部器件网络匹配，是可局部修补的候选；仍有 poly/tap 间距错误及零导出端口 |
| VCO 电容半单元 | 53 | MIM 提取为 2.8×2.8 µm，当前参考为 2×2 µm；开关尺寸/连接也不匹配 |

因此不能将这些候选直接替换当前原理图。PFD 生成器还用同一个互补 MOS 阵列函数标注 DFF/NAND/AND，没有实现对应标准单元的内部网络；其“等价”声明不能接受。后续优先核对器件与连接，再做紧凑排布。

检查器已补上零导出端口拒绝：Netgen 对无端口、但内部 label 可匹配的变容器也会报告器件网络匹配；这不足以作为可接入层次电路的 LVS 通过。

复核快照、提取网表和日志由[结果索引](../../results/catalog/layout_gemini_review.json)定位。复现：

```bash
uv run python verification/layout/review_gemini.py --output-dir results/layout/gemini_review/new_run
```

## 本轮绘制

新增[LDO v2_cur PDK](../ldo/layout/variants/v2_cur_pdk/README.md)，作为独立迭代保留，未覆盖 Gemini 原候选。当前优先目标已转为[PLL 模拟核版图](../../docs/layout/pll_r6.md)，从真实半单元/变容器的实现与寄生校准推进；HV/native LDO 器件作为后续独立模块。各模块均以当前电路为准，不通过改参考网表迁就几何。
