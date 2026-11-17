# 旧版图总览与生成链清退（2026-11-17）

`ldo_bias_tx_master_overview` 是过期的整包排布草图，不能代表当前电路或通过检查的物理实现。本轮沿其生成与引用链撤下 **七个旧生成器、六张总览**，共 4,055,666 字节；LDO/Bias 两份旧交付说明替换为模块入口。现行共享绘图库、模块候选、电路参数及原始审计输入保留。

## 判定依据与处理

| 产物 | 审查发现 | 处理 |
|---|---|---|
| `ldo_bias_tx_master_overview.png`、`ldo_bias_tx_wired_overview.png` | master 的 LDO 面积标题硬编码为 0.0053 mm²，标注 5 V/native 功率阵列及 100 pF；代码调用通用 `draw_comb_mos`，仅选择普通/LVT MOS 标记，没有对应 HV/native 构造。wired 为同批导入的另一张无现行生成入口总览，也无独立验证身份 | 两图和整包生成入口退役，不用重画图掩盖器件实现缺口 |
| `vco_lf_v2_shrink_overview.png`、`pll_final_pfd_gilbert_cp_top.png` | 描述旧的 VCO/LF 与完整 PLL 草案；PFD 以同一互补 MOS 阵列标注 DFF/NAND/AND，不能证明等价。`build_pfd_and_pll_top.py` 仍会生成已退役的 `pll_core_r6k4q` | 五个相互依赖的旧共享 suite 脚本整链撤下，避免恢复错误顶层 |
| `ldo_layout_suite_overview.png`、`bias_layout_suite_overview.png` 及模块 suite 生成器 | LDO 脚本借用 Bias 的 `draw_interdigitated_mos_row`，该函数只在普通/LVT 标记间切换，却宣称已实现 5 V/native。旧 README 还宣称“生产级”、满载压降及梯度消除，未给对应资格证据 | 两图、两个 suite 入口退役；原 README 留精确副本，现行 README 指向设计、采用状态与独立 PDK 迭代 |

已有[独立提取](../../results/catalog/layout_gemini_review.json)对旧 LDO 根层几何给出实质反例：HV18 核心提取为普通 1.8 V MOS，32 颗 MIM 两端同网，911 个 DRC 错误区域；慢尾滤波器 16 颗 MIM 两端同网。这些结果支持撤销旧交付的实现声明，不能外推为后续 PDK 候选全部无效。Bias 旧说明缺少验收证据，本轮没有新跑 Bias 提取或性能仿真。

## 保留边界

- `analog/layout/scripts/layout_core.py` 仍被 PLL 版图绘图与 PDK MIM 预览使用，保留原位。对 Python 导入做 AST 排查，七个退役模块的导入消费者都在本次退役集合内，没有发现集合外消费者。
- 根层历史 MAG/TCL/参考网表仍供导入审计，部分还被后续几何构造明确引用；不按“旧”字或图片失效连带删除。历史导入清单的 40 个 MAG 仍可读取。
- LDO/Bias 后续候选、CP、工作修订和未审阅研究保持原身份。各模块采用资格与旧 divider RC 暂停状态不变。
- Bias 模块根 README 的“待设计”和测试台待填写占位文字已过期，改为指向实际设计文档与采用状态；早期三项测试表明确为模板。
- 面积粗估页已明确限定为历史 deck 估算；不能把它或旧总览的面积换成当前物理面积。本轮不修改其历史数值。

## 文件与路径追溯

[退役清单](../../results/catalog/retired_layout_suites_20261117.json)记录每个旧路径、归档路径、字节数、SHA256、源 Git 提交、两份 README 原件及共享库快照。全部原件先复制到 `results/maintenance/legacy_layout_retirement/20261117/`、核对哈希并写清单，再从现行位置撤下。`analog/layout/import.json` 保持导入时原文，历史来源不随清扫改写。

本地 `results/` 不推 Git；异机需要查看旧原件时，使用清单的 `source_commit` 和 `former_path`，执行 `git show <source_commit>:<former_path>` 并核对 SHA256。恢复到独立结果目录查看，不恢复到现行源码位置。共享绘图库在原位的路径不变，现行图表工具无需迁移或增加路径注册系统。

维护审计新增检查退役清单中的原路径是否重新出现，包括被忽略的文件和断开的软链接。自动归档命令仍只处理运行产物，不自动清除重新出现的退役源码。

完整工作区 350 项测试通过，最终文档/工作台/工作包 18 项检查通过。原有 347 个未提交文件逐字节保持一致，570 份 PLL 证据 SHA256 一致，40 个历史导入 MAG 可读。现行 517 个 Python 文件的静态导入排查没有发现退役模块引用；四个现行绘图/PDK 模块成功加载，并用保留的绘图库从实际 MAG 生成独立预览。退役原件同时与归档和源 Git 提交逐字节核对。

维护审计返回运行产物 0、退役路径恢复 0；隔离目录中验证了重新生成文件、断链软链接及越界路径拒绝。机器记录见退役清单的 `validation`。本轮没有启动电路仿真，收尾仍有原来的 347 个文件等待按模块分别审阅。
