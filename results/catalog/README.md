# 结果索引

现行采用和验证边界从[当前状态](../../docs/status/current.md)进入，模块的固定运行与分析路径由本目录各专题 JSON 索引。软链接波形见[本机归档说明](../README.md#本机波形软链接)和[2026-11-20 归档清单](waveform_archive_20261120.json)。

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
