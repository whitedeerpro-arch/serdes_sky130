# 结果索引

现行采用状态与验证边界统一从[当前状态](../../docs/status/current.md)进入。本目录登记入库的签核台账、物理审计收据、4G 基线证据与历史退役清单。条目中的 `tracked` 表示仓库内追踪文件，`local_results` 表示对应本机 `results/` 运行目录（大波形管理见[本机归档说明](../README.md#本机波形软链接)）。

## 5.0 Gb/s 双速演进与全片物理审计（2026-11-26）

| 台账 | 覆盖范围 |
|---|---|
| [5G 双速签核台账（2026-11-26）](serdes_5g_signoff_20261126.json) | 8/8 模拟单元真 CPEX/RCX（LC-VCO、A/B 分频、HV18 Kelvin LDO、TX VDRV LDO、TX SST v5、W3 CTLE、5G Slicer、PI v3、RX 5G 顶层）、32-bit 数字宏 `v4p1`、紧缩 5G 混合去耦瓦片与 Plan-C `serdes_5g_top_pdk` 层级签核 |
| [4G / 5G 片级物理审计（2026-11-26）](chip_physical_audit_20261126.json) | 4G `full_v8` 与 5G Plan-C `v4p1` 只读提取连通性、隔离门控、金属 stub、局部密度与接口布线长度审计 |

## 4.0 Gb/s 基线与片级集成证据

| 台账 | 覆盖范围 |
|---|---|
| [v1.0 子系统证据索引](v1_0_subsystem_evidence.json) | 4G `v1.0` 发布基线各子系统（PLL v4、HV18 `v2_cur`、BIAS v2、TX SST v4.3、RX CMOS v2.2、数字 v3.1、Channel）固定摘要的路径与 SHA-256 |
| [片级集成证据索引（2026-11-24）](chip_integration_20261124.json) | `v1.0` 发布后的 PLL v4.2 短窗、模拟链路联调、加固 SAFF ÷8 候选与顶层装配收据 |
| [后续 PPA 与升级复核（2026-11-24）](ppa_upgrade_review_20261124.json) | `full_v3`、数字 03:00 GDS 与 4/5 Gb/s STA 对照，及模拟电源、PLL 模型与 TX 位序复核 |
| [FIFO 固定存储宽度复核（2026-11-24）](fifo_fixed_storage_width_20261124.json) | 数字 v3.1 异步 FIFO 固定 16 槽位宽边界复核 |
| [数字 v3.3 收口与 full_v8 复核（2026-11-25）](digital_v3p3_audit_20261125.json) | `full_v8` 的 v3.2 导入身份、v3.3 慢角路径、CDC 回放及 CDR 压力结果 |
| [有源器件排布复核（2026-11-25）](active_placement_review_20261125.json) | `full_v8` 与 5G 候选的无栅带几何、片级偏置/时钟端点及局部 CPEX |

## PLL r6 专项与阶段版图复核收据

- **r6 环振与闭环**：[r6 主线复核](r6_mainline_review.json) · [r6 锁定确认](r6_lock_confirmation.json) · [r6 波形映射审计](r6_map_wave_audit.json) · [电容融合](capacitor_fusion.json) · [电容阵优化](vco_bank_optimization.json) · [开关分配](vco_switch_allocation.json)
- **r6 阶段版图审阅（2026-11-15 / 11-17）**：[r6 版图汇总](pll_layout_r6.json) · [验收记录](pll_layout_acceptance_20261115.json) · [VCO 审阅](pll_layout_review_vco_20261115.json) · [LF 审阅](pll_layout_review_lf_20261115.json) · [PFD 审阅](pll_layout_review_pfd_20261115.json) · [待复核（CMOS](pll_pending_cmos_review_20261117.json) / [LF](pll_pending_lf_review_20261117.json) / [Receiver）](pll_pending_receiver_review_20261117.json)

## 波形归档与历史退役清单

| 清单 | 范围 |
|---|---|
| [2026-11-24 历史参考副本](retired_gemini_duplicate_references_20261124.json) | 旧 BIAS / HV18 版图来件的七份同内容参考网表，记录各自规范 SPICE 源路径 |
| [2026-11-24 历史图别名](retired_legacy_figure_alias_20261124.json) | r6 CML 图撤出源码区后保存的失效别名原始链接及 Git 身份 |
| [2026-11-23 发布前退役](retired_pre_release_20261123.json) | 旧 P&R v2、旧 LDO / Bias / PLL 版图变体与松散物理产物，归档位于 `/opt/serdes_archive/retired_20261123/` |
| [2026-11-22 数字 P&R v1](retired_pnr_v1_20261122.json) | v3.1 之前的数字 P&R 参考 |
| [2026-11-20 旧版本](retired_legacy_vars_20261120.json) · [旧分频器](retired_divider_vars_20261120.json) | 淘汰的 SPICE 变体、测试台与物理变体 |
| [2026-11-17 旧版图套件](retired_layout_suites_20261117.json) · [PLL 顶层草案](retired_pll_top_20261117.json) | 旧生成链、预览与未采用的顶层草案 |

各退役记录给出原路径、归档路径、字节数及 SHA-256。需要取用时从归档复制到独立的 `results/` 目录并核对哈希；带 `source_commit` 的条目可在包含该提交的历史分支上检查 Git 源路径。所有清单可用[退役校验命令](../../verification/maintenance/README.md)核对。
