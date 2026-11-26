# 版本与基线

项目级采用状态及验证边界见[当前状态](../status/current.md)。5G Plan-C 固定台账见 [serdes_5g_signoff_20261126.json](../../results/catalog/serdes_5g_signoff_20261126.json) 与 [chip_physical_audit_20261126.json](../../results/catalog/chip_physical_audit_20261126.json)；4G `v1.0` 机器可读入口见 [主线工作修订](../../config/mainline_working_revision.toml) 与 [v1_0_subsystem_evidence.json](../../results/catalog/v1_0_subsystem_evidence.json)。

---

## 1. 主推 5.0 Gb/s 双速（Plan-C `serdes_5g_top_pdk`，2026-11-26）权威源码入口

| 子系统 | 权威网表 / RTL / 脚本源码 | 已签核 PDK 版图目录 | 设计与签核入口 |
|---|---|---|---|
| **5G 全片 Plan-C 装配** | [`build_chip_top_5g_pdk.py`](../../verification/layout/build_chip_top_5g_pdk.py) · [`decap_5g_tiles.py`](../../verification/layout/decap_5g_tiles.py) | `results/layout/chip_top_5g_20261126/plan_v4p1/`（`55.43 MB` GDS） | [片级报告第 9–10 节](../layout/chip_floorplan_20261123.md#9-50-gbs-plan-c-全片物理装配与层级签核2026-11-26) |
| **5G 八边形 LC-VCO + ÷2** | [`lc_5g_div2_oct_pdk.spice`](../../analog/pll/vco_5g/spice/lc_5g_div2_oct_pdk.spice) | [`lc_vco_5g_oct_pdk`](../../analog/pll/vco_5g/layout/variants/lc_vco_5g_oct_pdk/summary.json) · [`ind_oct_2n5_pdk`](../../analog/pll/vco_5g/layout/variants/ind_oct_2n5_pdk/summary.json) | [5G 签核台账](../../results/catalog/serdes_5g_signoff_20261126.json) |
| **5G 双速 A/B 分频器** | [`pll_div_ab_5g_v2.spice`](../../analog/pll/divider/spice/pll_div_ab_5g_v2.spice) | [`div_ab_5g_v2_pdk`](../../analog/pll/divider/layout/variants/div_ab_5g_v2_pdk/summary.json) | [pll_feedback_data_dividers.md](../design/pll_feedback_data_dividers.md) |
| **PLL CP / LF / PFD / `r5`** | [`charge_pump_steer_v4.spice`](../../analog/pll/cp/spice/charge_pump_steer_v4.spice)、[`passive_rc_pdk_k4.spice`](../../analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice)、[`pfd_sc.spice`](../../analog/pll/pfd/spice/pfd_sc.spice)、[`cml_to_cmos_r5.spice`](../../analog/common/cml_to_cmos/spice/cml_to_cmos_r5.spice) | [`cp/v4_pdk`](../../analog/pll/cp/layout/variants/v4_pdk/README.md) · [`lf/fused_pdk`](../../analog/pll/loop_filter/layout/variants/fused_pdk/README.md) · [`pfd/pdk`](../../analog/pll/pfd/layout/variants/pdk/README.md) · [`r5_pdk`](../../analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md) | [pll_cp_v4.md](../design/pll_cp_v4.md)、[clock_receiver.md](../design/clock_receiver.md) |
| **HV18 Kelvin LDO & BIAS v2** | [`pll_supply_hv18_v2_cur.spice`](../../analog/ldo/spice/pll_supply_hv18_v2_cur.spice)、[`bias_v2.spice`](../../analog/bias/spice/bias_v2.spice) | [`v2_cur_kelvin_pdk`](../../analog/ldo/layout/variants/v2_cur_kelvin_pdk/README.md) · [`bias/v2_pdk`](../../analog/bias/layout/variants/v2_pdk/README.md) | [ldo_v2.md](../design/ldo_v2.md)、[bias_v2.md](../design/bias_v2.md) |
| **5G TX CMOS/SST v5** | [`tx_sst_top_5g.spice`](../../analog/tx/sst/spice/tx_sst_top_5g.spice)、[`tx_sst_serializer16_5g.spice`](../../analog/tx/sst/spice/tx_sst_serializer16_5g.spice)、[`tx_sst_driver_5g.spice`](../../analog/tx/sst/spice/tx_sst_driver_5g.spice) | [`tx/sst/v5_pdk`](../../analog/tx/sst/layout/variants/v5_pdk/summary.json) · [`v4p5_pdk`](../../analog/tx/sst/layout/variants/v4p5_pdk/summary.json) | [tx_sst_v4.md](../design/tx_sst_v4.md) |
| **5G RX CMOS 顶层** | [`rx_cmos_top_5g_pdk.spice`](../../analog/rx/cmos_rx/spice/rx_cmos_top_5g_pdk.spice)、[`rx_ctle_shunt_5g_pdk.spice`](../../analog/rx/cmos_rx/spice/rx_ctle_shunt_5g_pdk.spice)、[`rx_pi_4ph_iq_5g_v3.spice`](../../analog/rx/cmos_rx/spice/rx_pi_4ph_iq_5g_v3.spice)、[`rx_dt_sampler_5g.spice`](../../analog/rx/cmos_rx/spice/rx_dt_sampler_5g.spice) | [`rx_top_5g_pdk`](../../analog/rx/cmos_rx/layout/variants/rx_top_5g_pdk/summary.json) · [`ctle_shunt_5g_w3_pdk`](../../analog/rx/cmos_rx/layout/variants/ctle_shunt_5g_w3_pdk/summary.json) · [`v5g_4ph_v3_pdk`](../../analog/rx/cmos_rx/layout/variants/v5g_4ph_v3_pdk/summary.json) · [`slicer_5g_pdk`](../../analog/rx/cmos_rx/layout/variants/slicer_5g_pdk/summary.json) | [rx_cmos_v2.md](../design/rx_cmos_v2.md) |
| **5G 32-bit 数字顶层 `v4p1`** | [`serdes_digital_top_v4.sv`](../../digital/pnr/rtl_v4_32b/serdes_digital_top_v4.sv) · [`run_v4p1_5g_coopt_pnr.py`](../../digital/pnr/run_v4p1_5g_coopt_pnr.py) | [`hd_pnr_v4p1_5g_coopt`](../../digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/summary.json) | [5G 签核台账](../../results/catalog/serdes_5g_signoff_20261126.json) |
| **PCB 信道家族（C0–C5）** | [`config/channel_family.toml`](../../config/channel_family.toml)、`verification/models/channel/pcb_family/*.s4p` | — | [channel_model.md](../design/channel_model.md) |

---

## 2. 4.0 Gb/s 无电感环振对照基线（`v1.0` / `full_v8`）源码入口

| 子系统 | 权威网表 / RTL 源码 | 已签核 PDK 版图目录 | 设计文档 |
|---|---|---|---|
| **PLL v4 闭环台** | [`pll_top_r6_v4_upgrade.spice`](../../analog/pll/top/spice/pll_top_r6_v4_upgrade.spice)、[`clock_frontend_r6q.spice`](../../analog/pll/top/spice/clock_frontend_r6q.spice)、[`pll_top_r6_v4p2_saff.spice`](../../analog/pll/top/spice/pll_top_r6_v4p2_saff.spice) | 原理图闭环与片级候选入口 | [pll_vco_r6_perf.md](../design/pll_vco_r6_perf.md) |
| **VCO r6 + PTAT** | [`vco_ring4_r6.spice`](../../analog/pll/vco/spice/vco_ring4_r6.spice)、[`vco_ptat_bias.spice`](../../analog/pll/vco/spice/vco_ptat_bias.spice) | [`sym9_clean`](../../analog/pll/vco/layout/variants/sym9_clean/README.md) · [`ptat_bias_pdk`](../../analog/pll/vco/layout/variants/ptat_bias_pdk/README.md) | [pll_vco_r6_ptat.md](../design/pll_vco_r6_ptat.md) |
| **SAFF-TSPC ÷8** | [`tspc_reclock_prescaler8_2g.spice`](../../analog/pll/divider/spice/tspc_reclock_prescaler8_2g.spice)、[`tspc_reclock_prescaler8_2g_v2_cand.spice`](../../analog/pll/divider/spice/tspc_reclock_prescaler8_2g_v2_cand.spice) | [`saff_reclock_2g_pdk`](../../analog/pll/divider/layout/variants/saff_reclock_2g_pdk/README.md) · [`saff_reclock_2g_v2_pdk`](../../analog/pll/divider/layout/variants/saff_reclock_2g_v2_pdk/summary.json) | [pll_tspc_reclock_divider.md](../design/pll_tspc_reclock_divider.md) |
| **HV18 LDO v2_cur** | [`pll_supply_hv18_v2_cur.spice`](../../analog/ldo/spice/pll_supply_hv18_v2_cur.spice)、[`pll_bias_filter_r4.spice`](../../analog/ldo/spice/pll_bias_filter_r4.spice) | [`v2_cur_pdk`](../../analog/ldo/layout/variants/v2_cur_pdk/README.md) · [`bias_filter_r4_pdk`](../../analog/ldo/layout/variants/bias_filter_r4_pdk/README.md) | [ldo_v2.md](../design/ldo_v2.md) |
| **TX SST v4.3 / RX CMOS v2.2** | [`tx_sst_top.spice`](../../analog/tx/sst/spice/tx_sst_top.spice)、[`rx_cmos_top.spice`](../../analog/rx/cmos_rx/spice/rx_cmos_top.spice) | [`tx/sst/v4_pdk`](../../analog/tx/sst/layout/variants/v4_pdk/README.md) · [`rx/cmos_rx/v2_pdk`](../../analog/rx/cmos_rx/layout/variants/v2_pdk/README.md) | [tx_sst_v4.md](../design/tx_sst_v4.md)、[rx_cmos_v2.md](../design/rx_cmos_v2.md) |
| **Digital Top v3.1 / v3.2** | [`serdes_digital_top_v3.sv`](../../digital/pnr/rtl_v3/serdes_digital_top_v3.sv) | [`hd_pnr_v3_unified`](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/summary.json) · [`hd_pnr_v3p2_cmos_rx`](../../digital/pnr/variants/hd_pnr_v3p2_cmos_rx/serdes_digital_top_v3/summary.json) | [digital_top_v3.md](../design/digital_top_v3.md) |

---

## 3. 版本演进与历史追溯策略

- **隔离变体目录**：每次架构或加固演进采用独立变体目录（如 `v5_pdk`、`rx_top_5g_pdk`、`hd_pnr_v4p1_5g_coopt`），不覆写已签核基线。
- **已退役物理产物存证**：淘汰的中间版图变体均已带 SHA-256 存证归档至盘外，清单见 [`results/catalog/README.md`](../../results/catalog/README.md#波形归档与历史退役清单)（含 [`retired_pre_release_20261123.json`](../../results/catalog/retired_pre_release_20261123.json)、[`retired_legacy_vars_20261120.json`](../../results/catalog/retired_legacy_vars_20261120.json) 与 [`retired_divider_vars_20261120.json`](../../results/catalog/retired_divider_vars_20261120.json)）。
- **历史基线在 git 历史中追溯**：早期全 CML 版图前基线（`baseline-prelayout-20261113`）、历史原型冻结（`v0.1-design-freeze-20261028`）以及 2026-11-26 整理前的过程快照，均已从工作树精简并完整保留在 git 历史（标签 `v1.0` 与提交 `b10e989`）。
