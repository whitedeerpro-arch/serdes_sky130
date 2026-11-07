# 版本与基线

> 按模块维护工作修订与迭代：PLL完整顶层已有，近期推进r5/4 bit工作区与环路选参；TX为r2串化/驱动和v3选择时钟改进；RX为ac_trim/c2/120f＋deser16/W40；偏置为带隙/恒I·R/分配/B2。修订是解决角点和约束问题的迭代记录，归属稳定的模块层次。见[设计工作台](../../web/design/index.html)与[详细验证边界](development_map.md)。v0.1为历史基线。

## 基线政策

- 源码、文档、配置和小数据由 git 管理，`results/` 只留在磁盘（索引 `results/catalog/` 入库）。基线打 git 标签，当前为 `baseline-handover-20261030`。
- 每个模块的当前修订记录在 `config/*_working_revision.toml`，内容包括源文件、关键参数和状态。改电路时更新对应文件，不覆盖旧单元：新单元用新文件/子电路名，旧单元保留给依赖它的模块和历史证据。
- 改动后在关键工况上重跑该模块的回归，再扩展到 45 条件。建议的关键工况取自历史上暴露问题的点：TT/1.8 V/27 °C、SS/1.65 V/−40 °C、SS/1.65 V/85 °C、FS/1.65 V/85 °C、FS/1.65 V/−40 °C（分频尾管余量），以及 FF/FS/1.95 V/−40 °C（CMOS 过冲）。
- v0.1 曾以"冻结"形式发布，但之后分频器、VCO、转换器等都继续修改，冻结并未真正约束开发。保留其目录与哈希清单作为历史证据，不再新建冻结版本。

## 修订线

| 模块组 | 当前修订 | 配置 | 上一版 |
|---|---|---|---|
| PLL 时钟前端（VCO、抽出、分频、反馈转换） | r5 候选 `r5_candidate_20261105`（只改 VCO 节点无源件，闭环未重验证，I-32） | [pll_working_revision.toml](../../config/pll_working_revision.toml) | r4 `lowov_buffered_r4_20261031`（全速接收器） |
| PFD/CP/LF/启动 | v0.1 电路，r3 工况下复测 | [pll_startup.toml](../../config/pll_startup.toml)、[pll_loop_prototype.toml](../../config/pll_loop_prototype.toml) | — |
| TX 时钟分发、串化器、输出级 | r2 `tx_lowov_retimed_r2_20261030` | [tx_working_revision.toml](../../config/tx_working_revision.toml) | v0.1 |
| RX 前端、PI、采样、读出、CDR | ac_trim/c2、PI120f、deser16/W40；行为与物理闭环范围不同 | [rx_working_revision.toml](../../config/rx_working_revision.toml)；旧夹具/参数见rx_frontend、rx_cdr配置 | stock、ac、旧pair读出 |
| 偏置/带隙/参考缓冲 | 恒I·R＋5bit r_ref修调、模块电流拷贝、去耦、B2 | [bias_working_revision.toml](../../config/bias_working_revision.toml) | 理想电流参考 |
| 信道模型 | RLC16 + 合成 PCB 族 | [channel_family.toml](../../config/channel_family.toml) | — |

### PLL 源文件与修订关系

r5/4 bit原生候选为 [clock_frontend_r5.spice](../../analog/pll/top/spice/clock_frontend_r5.spice)＋[vco_ring4_4b.spice](../../analog/pll/vco/spice/vco_ring4_4b.spice)；全速接收器为r4。下面列出的r3文件保留其历史边界，不能仅凭同名VCO文件沿用旧码表或闭环结论。

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

- TX r2的45点基线使用v0.1 TT边沿理想化；r4原生接入暴露位置/质量问题。v3已有15点回放动态数据、r5原生8点静态计数，两者不能代替当前组合的全角动态资格，见[TX时钟分发](../design/tx_clock_distribution.md)。
- RX 的 PI 锚点是理想相关的 2 GHz 多相源，没有接原生 PLL。
- PLL r3 的闭环 PVT 是分层模型（实测 VCO 曲线 + 真实 PFD/CP），原生 r3 只做了 48 ns 接回。

## v0.1 历史基线

2026-10-28 发布：PLL（250 MHz 参考、÷8、50 µA CP、6.5 kΩ/40 pF/2 pF LF）、双节点预充与启动监督、匹配抽出与时钟分发、16:1 CML 串化器（末级锁存器尾管 24 µm、每端 200 Ω）。快照与逐文件哈希在 [releases/v0.1-design-freeze-20261028](../../releases/v0.1-design-freeze-20261028/README.md)，说明见 [历史记录](../history/design_freeze_v0p1.md)。依赖它的共享旧单元保持原样。
