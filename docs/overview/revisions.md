# 版本与基线

> 当前工作组合（2026-11-13）：PLL r6/5bit带寄生VCO＋quiet k4 core及标准单元PFD；TX r2树＋v3/extra5/WT16R240＋预驱120Ω/尾W60/输出W192；RX ac_trim/c2/120f＋deser16/W40及宿主字路径；偏置带隙/恒I·R/分配/B2，供电HV18 r4。已有r5原生TX接口与PLL预充闭环继续作为明确边界的证据，改动后按受影响接口承接。配置首部指向当前组合，旧基线有独立字段，不再把候选更新藏在旧版本号下。

## 基线政策

- 源码、文档、配置和小数据由git管理，`results/`只留磁盘（索引入库）。当前推进基准为`baseline-prelayout-20261113`；上次交接标签`baseline-handover-20261030`保留作历史，不再作为当前组合入口。
- 每个模块的当前修订记录在 `config/*_working_revision.toml`，内容包括源文件、关键参数和状态。改电路时更新对应文件，不覆盖旧单元：新单元用新文件/子电路名，旧单元保留给依赖它的模块和历史证据。
- 改动后在关键工况上重跑该模块的回归，再扩展到 45 条件。建议的关键工况取自历史上暴露问题的点：TT/1.8 V/27 °C、SS/1.65 V/−40 °C、SS/1.65 V/85 °C、FS/1.65 V/85 °C、FS/1.65 V/−40 °C（分频尾管余量），以及 FF/FS/1.95 V/−40 °C（CMOS 过冲）。
- v0.1 曾以"冻结"形式发布，但之后分频器、VCO、转换器等都继续修改，冻结并未真正约束开发。保留其目录与哈希清单作为历史证据，不再新建冻结版本。

## 修订线

| 模块组 | 当前修订 | 配置 | 上一版 |
|---|---|---|---|
| PLL 时钟前端（VCO、抽出、分频、反馈转换） | r6/5bit；31半单元、显式寄生、长负载对；135条件工作图已生成；轻dummy前端按新边界验证 | [pll_working_revision.toml](../../config/pll_working_revision.toml) | r5/4bit前端；与TX同deck的8个完整静态压力点；r4接收器/原有分频局部结果 |
| PFD/CP/LF/启动 | r6 quiet core：标准单元延迟复位PFD、k4转向CP、LF4.13kΩ/18pF、5bit搜索RTL | [pll_working_revision.toml](../../config/pll_working_revision.toml)、[环路](../design/pll_loop.md) | r5分层闭环135点与4条件×hv/ext共8条原生预充锁定；CP/分频局部统计保留 |
| TX 时钟分发、串化器、输出级 | v3/extra5/WT16R240＋r2树＋预驱120Ω/尾W60/输出W192；完整动态MOS45点；原生接口证据另列 | [tx_working_revision.toml](../../config/tx_working_revision.toml) | `baseline_revision`保留r2旧基线；原生r5与TX已联合，r6按接口差异承接 |
| PLL 安静供电 | HV18 r4；静态引脚、6bit修调、参考/尾偏置RC；本地网格及8条r5原生预充闭环 | [ldo_working_revision.toml](../../config/ldo_working_revision.toml) | r1–r3动态供电开关 |
| RX 前端、PI、采样、读出、CDR | ac_trim/c2、PI120f、deser16/W40；行为与物理闭环范围不同 | [rx_working_revision.toml](../../config/rx_working_revision.toml)；旧夹具/参数见rx_frontend、rx_cdr配置 | stock、ac、旧pair读出 |
| 偏置/带隙/参考缓冲 | 恒I·R＋5bit r_ref修调、模块电流拷贝、去耦、B2 | [bias_working_revision.toml](../../config/bias_working_revision.toml) | 理想电流参考 |
| 信道模型 | RLC16 + 合成 PCB 族 | [channel_family.toml](../../config/channel_family.toml) | — |

### PLL 源文件与修订关系

当前是[clock_frontend_r6q.spice](../../analog/pll/top/spice/clock_frontend_r6q.spice)＋[vco_ring4_r6.spice](../../analog/pll/vco/spice/vco_ring4_r6.spice)，完整环路为[pll_core_r6k4q.spice](../../analog/pll/top/spice/pll_core_r6k4q.spice)。r5/4bit与下面r3文件保留历史边界；未改动单元的局部结果继续按原输入/负载使用，受影响的源、加载、码表和噪声另验。

| 单元 | 文件 |
|---|---|
| 原生时钟前端（四路抽出、三路供电 dummy） | [clock_frontend_lowov.spice](../../analog/pll/top/spice/clock_frontend_lowov.spice) |
| VCO | [vco_ring4_pvt_candidate.spice](../../analog/pll/vco/spice/vco_ring4_pvt_candidate.spice) |
| 时钟接收器（全速与反馈） | [cml_to_cmos_pvt_candidate.spice](../../analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice) |
| ÷8 prescaler（含级间 buffer、本地偏置） | [cml_prescaler8.spice](../../analog/pll/divider/spice/cml_prescaler8.spice)、[cml_div2.spice](../../analog/pll/divider/spice/cml_div2.spice)、[cml_latch.spice](../../analog/pll/divider/spice/cml_latch.spice) |
| PFD / CP / LF | [pfd_cmos.spice](../../analog/pll/pfd/spice/pfd_cmos.spice)、[charge_pump.spice](../../analog/pll/cp/spice/charge_pump.spice)、[passive_rc_precharge.spice](../../analog/pll/loop_filter/spice/passive_rc_precharge.spice) |
| 物理 LF 候选（未采用） | [passive_rc_pdk_candidate.spice](../../analog/pll/loop_filter/spice/passive_rc_pdk_candidate.spice) |
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

- PLL→TX已经有r5原生同deck联合调试；另有回放动态及当前完整TX理想2GHz的MOS45点。r6改变VCO、负载/相位和前端dummy，需针对这些接口差异回归，不将联合工作重记为从未做过，见[TX时钟分发](../design/tx_clock_distribution.md)。
- RX 的 PI 锚点是理想相关的 2 GHz 多相源，没有接原生 PLL。
- PLL已有r5/k4行为VCO分层135点及4条件×hv/ext共8条原生预充锁定；r6沿用未改动单元的局部证据，承接当前环路和启动。预充锁定与从零启动分别记录。

## v0.1 历史基线

2026-10-28 发布：PLL（250 MHz 参考、÷8、50 µA CP、6.5 kΩ/40 pF/2 pF LF）、双节点预充与启动监督、匹配抽出与时钟分发、16:1 CML 串化器（末级锁存器尾管 24 µm、每端 200 Ω）。快照与逐文件哈希在 [releases/v0.1-design-freeze-20261028](../../releases/v0.1-design-freeze-20261028/README.md)，说明见 [历史记录](../history/design_freeze_v0p1.md)。依赖它的共享旧单元保持原样。
