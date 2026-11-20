# PLL ÷8 版图入口

本目录按接口族分别保留最近 2 个可用版图变体（旧版 `variants/pdk/`、中间未布线 `variants/sync2_pdk/` 及失败候选 `variants/cmos_sync_2g_pdk/` 已于 2026-11-20 归档退役，见 [divider_retirement_20261120.md](../../../../docs/history/divider_retirement_20261120.md)）。主线 CML 布局与寄生后审阅见 [review.md](review.md)，不以生成时 DRC/LVS 摘要替代电气验收。

## 当前保留变体

| 家族 | 目录 / 变体 | 生成器 | 状态与定位 |
|---|---|---|---|
| **CML（11 端口）Var 1** | [variants/review_clean/](variants/review_clean/README.md) | [build_prescaler8_pdk.py](build_prescaler8_pdk.py) + `clean_field_poly.py` | 撤除浮空 field-poly 的 r3 双翼 CML ÷8 与轻 dummy 候选；`LAYOUT-PLL-DIV-RC-01` 原全量 RC 疑点继续暂停 |
| **CML（11 端口）Var 2** | [variants/sync2_routed/](variants/sync2_routed/README.md) | [build_sync_prescaler8_pdk.py](build_sync_prescaler8_pdk.py)、[route_sync2_blocks.py](route_sync2_blocks.py)、[route_sync2_top.py](route_sync2_top.py) | 2-Stack 同步 CML ÷8 布线候选（[pll_pending_review_20261117.md](../../../../docs/layout/pll_pending_review_20261117.md) 标注尚未完成电气身份验收） |
| **CMOS/TSPC（10 端口）Var 1** | [variants/cmos_2g_pdk/](variants/cmos_2g_pdk/README.md) | [build_cmos_prescaler8_2g_pdk.py](build_cmos_prescaler8_2g_pdk.py) | 级联 C²MOS 纹波 ÷8 基线版图，供 `r5_pdk` 联合验收与对照 |
| **CMOS/TSPC（10 端口）Var 2** | [variants/saff_reclock_2g_pdk/](variants/saff_reclock_2g_pdk/README.md) | [build_saff_reclock_prescaler8_2g_pdk.py](build_saff_reclock_prescaler8_2g_pdk.py) | **v2 交错紧邻 SAFF-TSPC 重定时 ÷8**（`1,705.31 µm²`，DRC=0 / LVS=MATCH，45 角 CPEX 45/45 功能通过、44/45 `< 30 ps`，`RCX_BOTH` 5/5，`fs_v1650_t85_mm` 200/200 MC 通过；`ss_v1650_t-40_mm` `Xtg2` 边界见 [设计报告](../../../../docs/design/pll_tspc_reclock_divider.md)） |

其余文件：`plan/` 保存早期摆位/通道规划（尺寸以选定 `.mag` 为准）；[build_divider_pdk.py](build_divider_pdk.py) 为旧叶单元原型脚本；[layout_pex/run.py](../tb/layout_pex/run.py) 为 2 GHz 实际 buffer + CML ÷8 + 提取接收器联合台；固定证据索引见 [pll_layout_review_divider_20261115.json](../../../../results/catalog/pll_layout_review_divider_20261115.json)。
