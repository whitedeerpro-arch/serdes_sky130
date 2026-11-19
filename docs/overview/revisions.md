# 版本与基线

> 当前组合、采用状态与验证边界见[current.md](../status/current.md)，本页只维护修订关系和源文件导航。执行顺序见[计划](../status/prelayout_plan.md)。

## 基线政策

- 源码、文档、配置和小数据由git管理，`results/`只留磁盘（索引入库）。当前推进基准为`baseline-prelayout-20261113`；上次交接标签`baseline-handover-20261030`保留作历史，不再作为当前组合入口。
- 每个模块的当前修订记录在 `config/*_working_revision.toml`，内容包括源文件、关键参数和历史身份；项目级验证汇总链接current.md。改电路时更新对应文件，不覆盖旧单元：新单元用新文件/子电路名，旧单元保留给依赖它的模块和历史证据。
- 改动后在关键工况上重跑该模块的回归，再扩展到 45 条件。建议的关键工况取自历史上暴露问题的点：TT/1.8 V/27 °C、SS/1.65 V/−40 °C、SS/1.65 V/85 °C、FS/1.65 V/85 °C、FS/1.65 V/−40 °C（分频尾管余量），以及 FF/FS/1.95 V/−40 °C（CMOS 过冲）。
- v0.1 曾以"冻结"形式发布，但之后分频器、VCO、转换器等都继续修改，冻结并未真正约束开发。保留其目录与哈希清单作为历史证据，不再新建冻结版本。

## 修订线

| 模块组 | 工作修订 / 设计入口 | 历史修订如何使用 |
|---|---|---|
| PLL前端与环路 | [pll_working_revision.toml](../../config/pll_working_revision.toml)、[环路](../design/pll_loop.md) | r5/4bit与更早版本按实际输入/负载保留；不得转为r6码表、噪声或原生闭环资格 |
| TX分发/入口/树/驱动 | [tx_working_revision.toml](../../config/tx_working_revision.toml)、[完整TX](../design/tx_parallel_serializer.md) | baseline_revision保留r2；各源边界分别继承；候选局部完成不自动改采用组合 |
| PLL供电 | [ldo_working_revision.toml](../../config/ldo_working_revision.toml)、[LDO r4](../design/ldo_r4.md) | r1–r3动态供电开关是历史方案 |
| RX前端/PI/采样/读出/数字 | [rx_working_revision.toml](../../config/rx_working_revision.toml) | stock/ac/旧pair与mutable include记录按原边界，不追认为当前W40读出资格 |
| Bias/带隙/参考缓冲 | [bias_working_revision.toml](../../config/bias_working_revision.toml)、[Bias](../design/bias.md) | 理想参考、候选定宽参考串及生产参考分别标识 |
| Channel | [channel_family.toml](../../config/channel_family.toml)、[信道](../design/channel_model.md) | 合成模型与真实板线/封装提取分别标识 |

### PLL 源文件与修订关系

当前是[clock_frontend_r6q.spice](../../analog/pll/top/spice/clock_frontend_r6q.spice)＋[vco_ring4_r6.spice](../../analog/pll/vco/spice/vco_ring4_r6.spice)，完整环路为[pll_core_r6k4q.spice](../../analog/pll/top/spice/pll_core_r6k4q.spice)。r5/4bit与下面r3文件保留历史边界；未改动单元的局部结果继续按原输入/负载使用，受影响的源、加载、码表和噪声另验。

| 单元 | 文件 |
|---|---|
| 原生时钟前端（四路抽出、三路供电 dummy） | clock_frontend_lowov.spice (`../../analog/pll/top/spice/clock_frontend_lowov.spice`, retired in `retired_legacy_vars_20261120.json`) |
| VCO | vco_ring4_pvt_candidate.spice (`../../analog/pll/vco/spice/vco_ring4_pvt_candidate.spice`, retired in `retired_legacy_vars_20261120.json`) |
| 时钟接收器（全速与反馈） | [cml_to_cmos_pvt_candidate.spice](../../analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice) |
| ÷8 prescaler（含级间 buffer、本地偏置） | [cml_prescaler8.spice](../../analog/pll/divider/spice/cml_prescaler8.spice)、[cml_div2.spice](../../analog/pll/divider/spice/cml_div2.spice)、[cml_latch.spice](../../analog/pll/divider/spice/cml_latch.spice) |
| PFD / CP / LF | [pfd_cmos.spice](../../analog/pll/pfd/spice/pfd_cmos.spice)、[charge_pump.spice](../../analog/pll/cp/spice/charge_pump.spice)、[passive_rc_precharge.spice](../../analog/pll/loop_filter/spice/passive_rc_precharge.spice) |
| 物理 LF 候选（未采用） | passive_rc_pdk_candidate.spice (`../../analog/pll/loop_filter/spice/passive_rc_pdk_candidate.spice`, retired in `retired_legacy_vars_20261120.json`) |
| 启动监督 RTL | [pll_startup_supervisor.sv](../../digital/pll/rtl/pll_startup_supervisor.sv) |

### TX r2 源文件

| 单元 | 文件 |
|---|---|
| 串化器 | [serializer16_retimed_lowov.spice](../../analog/tx/serializer/spice/serializer16_retimed_lowov.spice) |
| 低过驱动逻辑单元与偏置 | [cml_lowov_cells.spice](../../analog/common/cml_mux/spice/cml_lowov_cells.spice) |
| 时钟分发 | [cml_clock_distribution_tx_lowov.spice](../../analog/tx/clock_distribution/spice/cml_clock_distribution_tx_lowov.spice) |
| 输出级 | [cml_line_driver_lowvt_enable.spice](../../analog/tx/output_driver/spice/cml_line_driver_lowvt_enable.spice) |
| P-LVT 适配器 | [sky130_pfet_lvt.spice](../../analog/common/devices/spice/sky130_pfet_lvt.spice) |

### RX 工作结构源文件

| 单元 | 文件 |
|---|---|
| 端接 / CTLE | [rx_input_termination.spice](../../analog/rx/input/spice/rx_input_termination.spice)、[rx_ctle_rc.spice](../../analog/rx/ctle/spice/rx_ctle_rc.spice) |
| PI | [pi_rotator.spice](../../analog/rx/pi/spice/pi_rotator.spice) 及同目录单元 |
| 采样与修调 | [rx_half_rate_samples_ac.spice](../../analog/rx/sampler/spice/rx_half_rate_samples_ac.spice)、[rx_offset_trim.spice](../../analog/rx/sampler/spice/rx_offset_trim.spice)；窗口用ac_trim，读出/校准用ac_trim_rk |
| 物理读出 | [rx_readout_demux2.spice](../../analog/rx/sampler/spice/rx_readout_demux2.spice)、[rx_readout_deser16.spice](../../analog/rx/sampler/spice/rx_readout_deser16.spice)；旧pair只作历史/对照 |
| 数字 | [digital/rx/rtl](../../digital/rx/rtl/) |

## 修订之间的依赖

PLL→TX已有开环原生静态、回放动态与理想源动态三种边界，具体驱动及覆盖统一见[current.md](../status/current.md#3-tx-被什么时钟驱动过)。改变VCO、dummy、负载或供电域后，按源/负载差异检查受影响接口。RX理想锚点不自动变成原生锚点；PLL预充锁定不自动变成从零启动。

采用新修订时列继承、需重校与作废的边界；未改CP/分频等单元的局部结果继续保留。具体流程见[工作流](../status/workflow.md)和[PVT继承规则](../verification/pvt_coverage.md)。本页整理前的修订/数字表留在[历史快照](../history/revisions_snapshot_20261113.md)。

## v0.1 历史基线

2026-10-28 发布：PLL（250 MHz 参考、÷8、50 µA CP、6.5 kΩ/40 pF/2 pF LF）、双节点预充与启动监督、匹配抽出与时钟分发、16:1 CML 串化器（末级锁存器尾管 24 µm、每端 200 Ω）。快照与逐文件哈希在 [releases/v0.1-design-freeze-20261028](../../releases/v0.1-design-freeze-20261028/README.md)，说明见 [历史记录](../history/design_freeze_v0p1.md)。依赖它的共享旧单元保持原样。
