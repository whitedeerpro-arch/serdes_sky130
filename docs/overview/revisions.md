# 版本与基线

项目级采用状态及验证边界见[当前状态](../status/current.md)。[主线工作修订](../../config/mainline_working_revision.toml)维护各模块的机器可读源码入口，[发布证据索引](../../results/catalog/v1_0_subsystem_evidence.json)固定可查结果。以下是源码与历史基线的对应关系。

---

## 1. 当前 4 Gb/s 发布主线（CMOS/SST TX & RX + 2 GHz 环振 PLL）源码入口

| 子系统 | 权威网表 / RTL 源码 | 已签核 PDK 版图目录 | 设计文档 |
|---|---|---|---|
| **PLL v4 闭环台** | [`pll_top_r6_v4_upgrade.spice`](../../analog/pll/top/spice/pll_top_r6_v4_upgrade.spice) 与 [`clock_frontend_r6q.spice`](../../analog/pll/top/spice/clock_frontend_r6q.spice) | CML 反馈闭环的原理图入口。片级反馈单元见下方 | [pll_vco_r6_perf.md](../design/pll_vco_r6_perf.md) |
| **VCO r6 + PTAT** | [`vco_ring4_r6.spice`](../../analog/pll/vco/spice/vco_ring4_r6.spice)、[`vco_ptat_bias.spice`](../../analog/pll/vco/spice/vco_ptat_bias.spice) | [`sym9_clean`](../../analog/pll/vco/layout/variants/sym9_clean/README.md) · [`ptat_bias_pdk`](../../analog/pll/vco/layout/variants/ptat_bias_pdk/README.md) | [pll_vco_r6_ptat.md](../design/pll_vco_r6_ptat.md) |
| **CP v4 / v4.1 & LF v2** | [`charge_pump_steer_v4.spice`](../../analog/pll/cp/spice/charge_pump_steer_v4.spice)（v4.1 微修 [`charge_pump_steer_v4p1_cand.spice`](../../analog/pll/cp/spice/charge_pump_steer_v4p1_cand.spice)）、[`passive_rc_pdk_k4.spice`](../../analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice) | [`cp/v4_pdk`](../../analog/pll/cp/layout/variants/v4_pdk/README.md) · [`lf/fused_pdk`](../../analog/pll/loop_filter/layout/variants/fused_pdk/README.md) | [pll_cp_v4.md](../design/pll_cp_v4.md) |
| **PFD / ÷8 / `r5` 接收器** | [`pfd_sc.spice`](../../analog/pll/pfd/spice/pfd_sc.spice)、[`tspc_reclock_prescaler8_2g.spice`](../../analog/pll/divider/spice/tspc_reclock_prescaler8_2g.spice)、[`cml_to_cmos_r5.spice`](../../analog/common/cml_to_cmos/spice/cml_to_cmos_r5.spice) | [`pfd/pdk`](../../analog/pll/pfd/layout/variants/pdk/README.md) · [`saff_reclock_2g_pdk`](../../analog/pll/divider/layout/variants/saff_reclock_2g_pdk/README.md) · [`r5_pdk`](../../analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md) | [pll_tspc_reclock_divider.md](../design/pll_tspc_reclock_divider.md)、[clock_receiver.md](../design/clock_receiver.md) |
| **HV18 LDO v2_cur** | [`pll_supply_hv18_v2_cur.spice`](../../analog/ldo/spice/pll_supply_hv18_v2_cur.spice) | [`ldo/v2_cur_pdk`](../../analog/ldo/layout/variants/v2_cur_pdk/README.md) · [`bias_filter_r4_pdk`](../../analog/ldo/layout/variants/bias_filter_r4_pdk/README.md) | [ldo_v2.md](../design/ldo_v2.md) |
| **BIAS v2** | [`bias_v2.spice`](../../analog/bias/spice/bias_v2.spice) | [`bias/v2_pdk`](../../analog/bias/layout/variants/v2_pdk/README.md) | [bias_v2.md](../design/bias_v2.md) |
| **TX CMOS/SST SST v4.3** | [`analog/tx/sst/spice/`](../../analog/tx/sst/spice/) | [`tx/sst/v4_pdk`](../../analog/tx/sst/layout/variants/v4_pdk/README.md) | [tx_sst_v4.md](../design/tx_sst_v4.md) |
| **RX CMOS/SST CMOS v2.2** | [`analog/rx/cmos_rx/spice/`](../../analog/rx/cmos_rx/spice/) | [`rx/cmos_rx/v2_pdk`](../../analog/rx/cmos_rx/layout/variants/v2_pdk/README.md) | [rx_cmos_v2.md](../design/rx_cmos_v2.md) |
| **Digital Top v3.1** | [`digital/pnr/rtl_v3/serdes_digital_top_v3.sv`](../../digital/pnr/rtl_v3/serdes_digital_top_v3.sv) | [`hd_pnr_v3_unified`](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/summary.json) | [digital_top_v3.md](../design/digital_top_v3.md) |
| **PCB 信道家族（C0–C5）** | [`config/channel_family.toml`](../../config/channel_family.toml)、`verification/models/channel/pcb_family/*.s4p` | — | [channel_model.md](../design/channel_model.md) |

---

## 2. 版本与演进策略

- 新架构使用独立文件或目录。单模块 `config/*_working_revision.toml` 和 `config/design_release.toml` 保留原有字段和历史身份，供旧测试和发布记录读取。
- **已退役旧版物理产物归档**：过时的中间版图变体（`hd_pnr_v2`、LDO `r4/smallcap/mim/v2_pdk`、BIAS v1 `pdk`、CP v3 `pdk`、LF v1 `pdk`、Divider `cmos_2g/sync2`、VCO `r6_pdk` 等）均已带 SHA-256 存证归档至盘外，详见 [`retired_pre_release_20261123.json`](../../results/catalog/retired_pre_release_20261123.json)、[`retired_legacy_vars_20261120.json`](../../results/catalog/retired_legacy_vars_20261120.json) 与 [`retired_divider_vars_20261120.json`](../../results/catalog/retired_divider_vars_20261120.json)。
- **5 Gb/s 拓展探索分支**：超额目标探索（5G 环振/LC-PLL 与 5 Gb/s 链路摸底）隔离保存在本地分支 `exp/5g-stretch`，不混入 4 Gb/s 发布主线 `main`。

---

## 3. 历史基线参考

- **`baseline-prelayout-20261113`**（历史全 CML 版图前基线）：PLL `pll_core_r6k4q` + CML ÷8、TX `v3/extra5`（[`serializer16_retimed_lowov.spice`](../../analog/tx/serializer/spice/serializer16_retimed_lowov.spice) + [`cml_line_driver_lowvt_enable.spice`](../../analog/tx/output_driver/spice/cml_line_driver_lowvt_enable.spice)）、RX `ac_trim/c2/W40`（[`rx_half_rate_samples_ac.spice`](../../analog/rx/sampler/spice/rx_half_rate_samples_ac.spice)）、HV18 LDO `r4` 与 Bias v1。详见 [历史快照](../history/revisions_snapshot_20261113.md)。
- **`v0.1-design-freeze-20261028`**（早期原型冻结基线）：快照与逐文件哈希保留在 [releases/v0.1-design-freeze-20261028](../../releases/v0.1-design-freeze-20261028/README.md)，说明见 [历史记录](../history/design_freeze_v0p1.md)。
