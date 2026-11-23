# 模块地图与设计入口

按 **SerDes → PLL / LDO / Bias / TX / RX / Digital / Channel** 组织。**当前采用组合与验证数字统一见 [current.md](../status/current.md)**，片级版图与 PDN 规划见 [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md)，完整架构与时钟域见 [architecture.md](architecture.md)。

也可通过 **[交互设计工作台](../../web/design/index.html)**（[使用说明](../../web/design/README.md)）按树形结构浏览模块边界、模型推导与历史证据。

---

## 1. 当前 4 Gb/s Zero-CML 主线模块导航

| 模块 | 源码目录 | 权威设计文档 | 签核物理版图 |
|---|---|---|---|
| **PLL v4 闭环 & VCO r6 PTAT** | [`analog/pll/`](../../analog/pll/README.md) | [pll_vco_r6_perf.md](../design/pll_vco_r6_perf.md) · [pll_vco_r6_ptat.md](../design/pll_vco_r6_ptat.md) · [pll_loop.md](../design/pll_loop.md) | [`sym9_clean`](../../analog/pll/vco/layout/variants/sym9_clean/README.md) · [`ptat_bias_pdk`](../../analog/pll/vco/layout/variants/ptat_bias_pdk/README.md) |
| **PLL CP v4 & 融合 LF v2** | `analog/pll/cp/`, `loop_filter/` | [pll_cp_v4.md](../design/pll_cp_v4.md) · [pll_loop.md](../design/pll_loop.md) | [`cp/v4_pdk`](../../analog/pll/cp/layout/variants/v4_pdk/README.md) · [`lf/fused_pdk`](../../analog/pll/loop_filter/layout/variants/fused_pdk/README.md) |
| **PLL PFD / SAFF-TSPC ÷8 / `r5` Rx** | `analog/pll/{pfd,divider}/`, `analog/common/cml_to_cmos/` | [pll_tspc_reclock_divider.md](../design/pll_tspc_reclock_divider.md) · [clock_receiver.md](../design/clock_receiver.md) | [`pfd/pdk`](../../analog/pll/pfd/layout/variants/pdk/README.md) · [`saff_reclock_2g_pdk`](../../analog/pll/divider/layout/variants/saff_reclock_2g_pdk/README.md) · [`r5_pdk`](../../analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md) |
| **HV18 LDO v2_cur** | [`analog/ldo/`](../../analog/ldo/README.md) | [ldo_v2.md](../design/ldo_v2.md) | [`ldo/v2_cur_pdk`](../../analog/ldo/layout/variants/v2_cur_pdk/README.md) · [`bias_filter_r4_pdk`](../../analog/ldo/layout/variants/bias_filter_r4_pdk/README.md) |
| **BIAS v2** | [`analog/bias/`](../../analog/bias/README.md) | [bias_v2.md](../design/bias_v2.md) | [`bias/v2_pdk`](../../analog/bias/layout/variants/v2_pdk/README.md) |
| **TX Zero-CML SST v4.3** | [`analog/tx/sst/`](../../analog/tx/README.md) | [tx_sst_v4.md](../design/tx_sst_v4.md) | [`tx/sst/v4_pdk`](../../analog/tx/sst/layout/variants/v4_pdk/README.md) |
| **RX Zero-CML CMOS v2.2** | [`analog/rx/cmos_rx/`](../../analog/rx/README.md) | [rx_cmos_v2.md](../design/rx_cmos_v2.md) | [`rx/cmos_rx/v2_pdk`](../../analog/rx/cmos_rx/layout/variants/v2_pdk/README.md) |
| **Digital Top v3.1** | [`digital/pnr/rtl_v3/`](../../digital/README.md) | [digital_top_v3.md](../design/digital_top_v3.md) | [`hd_pnr_v3_unified`](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/summary.json) |
| **Channel & Verification** | `verification/models/channel/`, `src/serdes_flow/` | [channel_model.md](../design/channel_model.md) · [optimization_toolkit.md](../verification/optimization_toolkit.md) | [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md) |

---

## 2. 模块开发与验证闭环流程

![模块边界、模型规划和局部迭代](../figures/system/closure_workflow.png)

执行协议见 [workflow.md](../status/workflow.md)：器件/版图可实现性与寄生 → 模型/$g_m/I_D$ 参数规划 → 局部校准与压力点 → 受影响接口与全角回归。配置入口见 [revisions.md](revisions.md)，工作修订文件位于 `config/*_working_revision.toml`。

---

## 3. 历史 CML 逐框导航（B / C / T / R / X 溯源）

早期全 CML 架构框图（[clock_tx_blocks.png](../figures/system/clock_tx_blocks.png)、[rx_blocks.png](../figures/system/rx_blocks.png)）及各子专题推导保留在 `docs/design/` 第二节，供追溯物理器件建模、电阻/电容约束与历史取舍：

- **偏置与供电专题**：[Bias v1](../design/bias.md) · [共享电容](../design/bias_cap_review.md) · [物理参考卡](../design/physical_reference_card.md) · [LDO r4/减容](../design/ldo_r4.md) · [监控](../design/monitor.md) · [功耗审计](../design/power_audit.md)
- **时钟与 CML 分频专题**：[VCO r6](../design/pll_vco.md) · [粗码窗口](../design/pll_coarse_windows.md) · [CML ÷8](../design/pll_divider.md) · [CP 窗口](../design/pll_cp_window.md) · [纹波预算](../design/pll_ripple_budget.md)
- **历史 CML TX 专题**：[完整入口](../design/tx_parallel_serializer.md) · [末级重定时](../design/tx_final_retime.md) · [时钟分发](../design/tx_clock_distribution.md) · [输出级](../design/tx_output_driver.md) · [定宽电阻](../design/fixed_load_resistors.md)
- **历史 CML RX 专题**：[前端](../design/rx_frontend.md) · [PI/采样](../design/rx_pi_sampler.md) · [数字 CDR](../design/rx_cdr_digital.md) · [宿主 CDC](../design/rx_host_cdc.md)
- **历史快照**：[2026-11-13 整理前快照](../history/development_map_snapshot_20261113.md) · [Xschem 历史原理图](../history/schematics.md)
