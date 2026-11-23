# 图表目录（`docs/figures/`）

所有跟踪图表均为优化后的 PNG 格式（矢量 `.svg` 副本按 `.gitignore` 策略仅留本地磁盘）。交互式按模块浏览请打开 **[设计工作台](../../web/design/index.html)**。

---

## 一、当前 4 Gb/s NRZ SerDes 初稿签核核心图表

| 图表 | 模块与内容 | 对应报告 |
|---|---|---|
| [serdes_chip_floorplan_20261123.png](system/serdes_chip_floorplan_20261123.png) | **片级规划**：`845.4 × 601.4 µm (0.5084 mm²)` 21 宏 + 12 阻尼 PDN 阵真实尺寸总图 | [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md) |
| [pll_v4_closed_loop_20261123.png](clocking/pll_v4_closed_loop_20261123.png) | **PLL v4 闭环**：7/7 PVT 锁相收敛、LDO 安静轨、`Vctrl` 与杂散签核波形 | [current.md](../status/current.md) |
| [vco_r6_ptat_perf_20261123.png](clocking/vco_r6_ptat_perf_20261123.png) | **VCO r6 + PTAT**：`sym9_clean` CPEX 八相正交误差、相噪谱与 PLL v4 抖动预算 | [pll_vco_r6_perf.md](../design/pll_vco_r6_perf.md) |
| [tx_sst_v4_eyes.png](tx/tx_sst_v4_eyes.png) | **TX CMOS/SST SST v4**：4 Gb/s 焊盘与 `C2_loss6` 远端 FFE 均衡眼图 | [tx_sst_v4.md](../design/tx_sst_v4.md) |
| [rx_cmos_v2_signoff.png](rx/rx_cmos_v2_signoff.png) | **RX CMOS/SST CMOS v2**：端到端 CTLE/PI/Double-Tail/解串签核眼图与 PI INL | [rx_cmos_v2.md](../design/rx_cmos_v2.md) |
| [stability_pdn_20261123.png](verification/stability_pdn_20261123.png) | **PDN 稳定性**：片级去耦阻抗与串联阻尼谐振抑制验证 | [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md) |
| [serdes_digital_top_v3.png](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/serdes_digital_top_v3.png) | **Digital Top v3.1**：`338.1 × 307.4 µm` 统一精简数字宏最终版图 | [digital_top_v3.md](../design/digital_top_v3.md) |
| [serdes_tx_sst_top_pdk.png](../../analog/tx/sst/layout/variants/v4_pdk/serdes_tx_sst_top_pdk.png) · [serdes_rx_cmos_top_pdk.png](../../analog/rx/cmos_rx/layout/variants/v2_pdk/serdes_rx_cmos_top_pdk.png) | **TX / RX 物理版图**：CMOS/SST SST v4.3 与 CMOS RX v2.2 顶层宏预览 | [docs/layout/README.md](../layout/README.md) |
| [serdes_pll_supply_hv18_v2_cur_pdk.png](../../analog/ldo/layout/variants/v2_cur_pdk/serdes_pll_supply_hv18_v2_cur_pdk.png) · [serdes_bias_top_v2_pdk.png](../../analog/bias/layout/variants/v2_pdk/serdes_bias_top_v2_pdk.png) | **LDO & BIAS 物理版图**：HV18 LDO `v2_cur` 与 BIAS v2 顶层宏预览 | [ldo_v2.md](../design/ldo_v2.md)、[bias_v2.md](../design/bias_v2.md) |

---

## 二、专题与历史演进图集目录

早期全 CML 演进、单元表征、信道模型与专项诊断图表按模块归档在以下子目录（各目录内含独立 `README.md`）：

| 目录 | 涵盖内容 |
|---|---|
| [`system/`](system/README.md) | 系统架构参考框图、设计工作台截图与片级规划图 |
| [`clocking/`](clocking/README.md) | PLL/VCO/分频器/时钟分发 135 条件调谐、PVT、预充与抖动研究图集 |
| [`tx/`](tx/) | TX SST 签核眼图 + 历史 CML 串化器、字入口、时钟树与输出驱动 PVT 图集 |
| [`rx/`](rx/) | RX CMOS v2 签核图 + 历史 CTLE、PI、采样器与 CDR 跟踪图集 |
| [`channel/`](channel/characterization/README.md) | `C0–C5` PCB 信道频响、脉冲响应与均衡原理图 |
| [`common/`](common/level_conversion/README.md) | 电平转换、Bias 电容与 LDO 早期表征图 |
| [`layout/`](layout/) | VCO 电容融合、r6 电容阵与早期物理寄生对比图 |
| [`verification/`](verification/mixed_signal/README.md) | PDN 稳定性、数模混合接口与实时反馈验证图 |
| [`studies/`](studies/clock_timing/README.md) | 早期多相时钟叠图、眼图折叠、串化时序溯源与 CMOS 选择对比专项 |

*历史图片迁移映射与机器索引保留在 [figure_organization.md](../history/figure_organization.md) 与 [figure_catalog.json](../data/figure_catalog.json)。*
