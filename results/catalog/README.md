# 结果索引

现行采用和验证边界从[当前状态](../../docs/status/current.md)进入。[v1.0 子系统证据索引](v1_0_subsystem_evidence.json)和[片级集成证据索引](chip_integration_20261124.json)登记固定摘要的路径、SHA-256 与边界。条目的 `tracked` 表示仓库内文件，`local_results` 表示需要该次运行归档的文件。软链接波形见[本机归档说明](../README.md#本机波形软链接)和[2026-11-20 归档清单](waveform_archive_20261120.json)。

[后续 PPA 与升级复核](ppa_upgrade_review_20261124.json)固定 `full_v3`、数字 03:00 GDS 与 4/5 Gb/s STA 对照，同时登记模拟电源、PLL 模型以及 TX 位序复核。

[数字 v3.3 收口与 full_v8 复核](digital_v3p3_audit_20261125.json)固定 `full_v8` 的 v3.2 导入身份、v3.3 慢角路径、同域训练入口候选、CDC 回放及 CDR 功能压力结果。

[有源器件排布复核](active_placement_review_20261125.json)固定 `full_v8` 与独立 5G 候选的无栅带几何、片级偏置和时钟端点及局部 CPEX。

## 退役索引

| 清单 | 范围 |
|---|---|
| [2026-11-24 历史参考副本](retired_gemini_duplicate_references_20261124.json) | 旧 BIAS / HV18 版图来件的七份同内容参考网表，记录各自规范 SPICE 源路径 |
| [2026-11-24 历史图别名](retired_legacy_figure_alias_20261124.json) | r6 CML 图已撤出源码区，保存失效别名的原始链接内容及 Git 身份 |
| [2026-11-23 发布前退役](retired_pre_release_20261123.json) | 旧 P&R v2、旧 LDO / Bias / PLL 版图变体与松散物理产物，归档位于 `/opt/serdes_archive/retired_20261123/` |
| [2026-11-22 数字 P&R v1](retired_pnr_v1_20261122.json) | v3.1 之前的数字 P&R 参考 |
| [2026-11-20 旧版本](retired_legacy_vars_20261120.json) · [旧分频器](retired_divider_vars_20261120.json) | 淘汰的 SPICE 变体、测试台与物理变体 |
| [2026-11-17 旧版图套件](retired_layout_suites_20261117.json) · [PLL 顶层草案](retired_pll_top_20261117.json) | 旧生成链、预览与未采用的顶层草案 |

各条记录给出原路径、归档路径、字节数及 SHA-256。需要取用时从归档复制到独立的 `results/` 目录并核对哈希。带 `source_commit` 的条目可在包含该提交的历史分支上检查 Git 源路径。所有清单可用[退役校验命令](../../verification/maintenance/README.md)核对。

## 2026-10-29 阶段归档索引

以下 550 个运行目录来自该次归档快照，`execution_status` 记录运行状态。

| 模块／实验 | 运行数 | 引用证据 | 失败／未完成 | 归档原始量 / MB |
|---|---:|---:|---:|---:|
| analog/common | 1 | 1 | 0 | 0.00 |
| analog/common/cml_mux/cmos_select | 4 | 0 | 1 | 5.64 |
| analog/common/cml_mux/functional | 2 | 0 | 0 | 2.40 |
| analog/common/cml_to_cmos/dc_transfer | 1 | 0 | 0 | 0.00 |
| analog/common/cml_to_cmos/functional | 31 | 1 | 0 | 95.24 |
| analog/common/cml_to_cmos/input_range | 9 | 0 | 0 | 28.02 |
| analog/common/cml_to_cmos/reverse_loading | 4 | 0 | 0 | 12.75 |
| analog/pll | 1 | 1 | 0 | 0.00 |
| analog/pll/cp/dc | 5 | 0 | 0 | 0.00 |
| analog/pll/divider/cmos_functional | 8 | 0 | 0 | 24.79 |
| analog/pll/divider/functional | 72 | 0 | 0 | 458.71 |
| analog/pll/divider/logic_truth | 4 | 0 | 3 | 2.74 |
| analog/pll/loop_filter/impedance | 1 | 0 | 0 | 0.00 |
| analog/pll/loop_filter/precharge | 2 | 0 | 0 | 0.00 |
| analog/pll/loop_filter/startup_optimization | 2 | 2 | 0 | 4.52 |
| analog/pll/loop_filter/transient | 1 | 0 | 0 | 0.00 |
| analog/pll/pfd/dead_zone | 8 | 0 | 0 | 71.38 |
| analog/pll/pfd/functional | 22 | 0 | 0 | 138.36 |
| analog/pll/top | 1 | 1 | 0 | 0.00 |
| analog/pll/top/acquisition | 17 | 0 | 5 | 162.00 |
| analog/pll/top/clock_harvest | 2 | 1 | 0 | 848.59 |
| analog/pll/top/divider_pfd | 5 | 0 | 3 | 7.27 |
| analog/pll/top/hybrid_divider_pfd | 3 | 0 | 1 | 9.59 |
| analog/pll/top/pfd_cp | 17 | 0 | 2 | 40.25 |
| analog/pll/top/pfd_cp_lf | 6 | 0 | 3 | 15.61 |
| analog/pll/top/precharged_capture | 9 | 2 | 2 | 587.08 |
| analog/pll/top/startup_optimization | 2 | 1 | 1 | 62.40 |
| analog/pll/top/vco_divider | 7 | 0 | 7 | 0.00 |
| analog/pll/top/vco_receiver | 8 | 2 | 0 | 18.35 |
| analog/pll/vco/sensitivity | 1 | 0 | 0 | 1.29 |
| analog/pll/vco/startup | 6 | 2 | 1 | 12.10 |
| analog/pll/vco/tuning | 11 | 0 | 0 | 14.22 |
| analog/pll/vco/varactor_cv | 1 | 0 | 0 | 0.00 |
| analog/rx/ctle/ac_dc | 16 | 16 | 0 | 0.00 |
| analog/rx/ctle/channel_replay | 4 | 4 | 0 | 86.42 |
| analog/rx/pi/rotation | 75 | 64 | 0 | 0.00 |
| analog/rx/pi/rotation_dynamic | 2 | 2 | 0 | 6.95 |
| analog/rx/pi/sector | 63 | 9 | 0 | 0.00 |
| analog/rx/pi/sector_dynamic | 2 | 2 | 0 | 5.79 |
| analog/rx/sampler/cmos_aligned_final | 3 | 0 | 0 | 11.82 |
| analog/rx/sampler/cmos_aligned_selected | 3 | 3 | 0 | 11.82 |
| analog/rx/sampler/cmos_readout | 6 | 3 | 0 | 21.28 |
| analog/rx/sampler/functional | 7 | 7 | 0 | 13.81 |
| analog/rx/sampler/pi_loaded | 3 | 3 | 0 | 5.92 |
| analog/rx/sampler/rtl_pi_wrap | 2 | 2 | 0 | 5.07 |
| analog/rx/top/loaded_link | 7 | 3 | 3 | 44.81 |
| analog/rx/top/pcb_samples | 5 | 1 | 4 | 4.54 |
| analog/tx/clock_distribution/calibration | 4 | 0 | 0 | 14.22 |
| analog/tx/output_driver/integration | 2 | 2 | 0 | 22.60 |
| analog/tx/output_driver/pcb_channel | 3 | 3 | 0 | 64.66 |
| analog/tx/output_driver/terminated | 6 | 4 | 2 | 40.13 |
| analog/tx/serializer/cmos_select | 4 | 0 | 2 | 14.80 |
| analog/tx/serializer/functional | 9 | 0 | 0 | 110.65 |
| analog/tx/serializer/physical_clock | 5 | 1 | 0 | 264.00 |
| analog/tx/serializer/pll_clock_replay | 3 | 3 | 0 | 385.94 |
| analog/tx/serializer/pll_clock_replay_compact | 2 | 0 | 2 | 11.57 |
| analog/tx/serializer/timing_diagnosis | 4 | 4 | 0 | 242.59 |
| digital/rx/cdr_closed_loop | 18 | 10 | 0 | 0.00 |
| digital/rx/pi_commutator | 3 | 3 | 0 | 0.00 |
| infrastructure/stimuli | 6 | 0 | 0 | 0.00 |
| schematics | 3 | 0 | 0 | 5.22 |
| verification/mixed_signal | 5 | 2 | 0 | 4.37 |
| verification/streaming | 1 | 1 | 0 | 0.00 |

逐运行状态见 [experiments.tsv](experiments.tsv) / [experiments.json](experiments.json)。原始运行路径保留小文件，压缩大文件通过 [artifacts.tsv](artifacts.tsv) 查找；恢复工具为 verification/results/artifact.sh。大PWL输入在归档中有备份，同时保留原路径副本。
