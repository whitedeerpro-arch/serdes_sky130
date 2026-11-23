# 版图与物理实现入口（`docs/layout/`）

项目级采用状态统一见 [current.md](../status/current.md)，片级宏观摆位、引脚对齐与阻尼 PDN 方案见 [chip_floorplan_20261123.md](chip_floorplan_20261123.md)。

## 1. 当前 4 Gb/s Zero-CML 已签核物理宏清单

所有现行物理宏均由可复现的 Python / OpenROAD 脚本基于 SKY130A 官方 PDK 原语生成，独立通过 `Magic full-rule DRC = 0`、`Netgen LVS = MATCH`（零属性错、零悬空多晶、全端口导出）。重型二进制产物（`.mag` / `.gds` / `.def` / `_pg.v`）保留在本地磁盘并通过 GitHub Releases 分发，源码仓库保留生成器、LVS/PEX/RCX 摘要、参考网表与签核预览图。

| 子系统 | 签核目录 | 关键尺寸与签核摘要 |
|---|---|---|
| **片级整合规划** | [chip_floorplan_20261123.md](chip_floorplan_20261123.md) | `845.4 × 601.4 µm = 0.5084 mm²`（21 功能宏 + 12 阻尼 PDN 去耦阵，957.9 pF 总片上电容，0 重叠） |
| **数字顶层 v3.1** | [hd_pnr_v3_unified](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/summary.json) | `338.10 × 307.40 µm = 103,932 µm²`，4,932 单元，3 角 OpenRCX STA MET，4/4 VCS SDF GLS PASS |
| **TX SST v4.3** | [tx/sst/layout/variants/v4_pdk](../../analog/tx/sst/layout/variants/v4_pdk/README.md) | `231.50 × 146.98 µm = 34,026 µm²`，5/5 单元 DRC=0/LVS=MATCH，22/22 RCX 后仿通过 |
| **RX CMOS v2.2** | [rx/cmos_rx/layout/variants/v2_pdk](../../analog/rx/cmos_rx/layout/variants/v2_pdk/README.md) | `245.30 × 195.40 µm = 47,932 µm²`，8/8 单元 DRC=0/LVS=MATCH，3/3 CPEX 后仿 0 错码 |
| **PLL VCO r6 + PTAT** | [vco/layout/variants/sym9_clean](../../analog/pll/vco/layout/variants/sym9_clean/README.md) · [ptat_bias_pdk](../../analog/pll/vco/layout/variants/ptat_bias_pdk/README.md) | `sym9_clean` CPEX 八相正交误差 `≤ 0.76 ps`；独立 PTAT 尾偏置宏 DRC=0/LVS=MATCH |
| **PLL CP v4 & LF v2** | [cp/layout/variants/v4_pdk](../../analog/pll/cp/layout/variants/v4_pdk/README.md) · [loop_filter/layout/variants/fused_pdk](../../analog/pll/loop_filter/layout/variants/fused_pdk/README.md) | 主动伺服宽摆幅 CP v4 与 MIM1+MIM2 融合 LF v2，DRC=0/LVS=MATCH |
| **PLL PFD & SAFF-TSPC ÷8 & `r5` Rx** | [pfd/variants/pdk](../../analog/pll/pfd/layout/variants/pdk/README.md) · [saff_reclock_2g_pdk](../../analog/pll/divider/layout/variants/saff_reclock_2g_pdk/README.md) · [cml_to_cmos/r5_pdk](../../analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md) | `1,705 µm²` SAFF-TSPC ÷8 + `r5` 全速转换器 v6（CPEX 45/45、MC 200/200） |
| **LDO v2_cur & 慢滤波** | [ldo/layout/variants/v2_cur_pdk](../../analog/ldo/layout/variants/v2_cur_pdk/README.md) · [bias_filter_r4_pdk](../../analog/ldo/layout/variants/bias_filter_r4_pdk/README.md) | `27,826 µm²` HV18 LDO v2_cur 顶层 + `2,033 µm²` 1 MΩ/16 pF VCO 尾偏置慢滤波 |
| **BIAS v2** | [bias/layout/variants/v2_pdk](../../analog/bias/layout/variants/v2_pdk/README.md) | 带隙/FC-OTA/`ref_pbuf`/`bias_top` 全套 PDK 签核宏 |

## 2. 物理审阅记录与历史归档

- **工程约定**：模块的 `analog/.../layout/README.md` 为稳定入口；`variants/<身份>/` 存放独立参考、提取网表与签核摘要；运行日志、EXT、临时脚本及大波形留在追加式 `results/`。
- **阶段审阅与专题**：[PLL r6 版图推进](pll_r6.md) · [电容融合研究](capacitor_fusion.md) · [四模块阶段验收（2026-11-15）](pll_acceptance_20261115.md) · [PLL 独立审阅](pll_review_20261115.md) · [后续局部复核（2026-11-17）](pll_pending_review_20261117.md) · [Gemini 迁移汇总](gemini_migration_summary.md) · [版图公共工具](../../analog/layout/README.md)
- **已退役旧版版图归档**：旧版迭代变体（`hd_pnr_v2`、LDO `r4/smallcap/mim/v2_pdk`、BIAS v1 `pdk`、CP v3 `pdk`、LF v1 `pdk`、Divider `cmos_2g/sync2`、VCO `r6_pdk` 与早期松散 `.mag/.tcl`）已带 SHA-256 校验归档至 `/opt/serdes_archive/retired_20261123/`，清退清单见 [retired_pre_release_20261123.json](../../results/catalog/retired_pre_release_20261123.json) 及早期 [legacy_layout_retirement_20261117.md](../history/legacy_layout_retirement_20261117.md)。
