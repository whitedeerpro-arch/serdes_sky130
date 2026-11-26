# 图表目录（`docs/figures/`）

本目录汇总 5.0 Gb/s 双速 Plan-C 演进路线、4.0 Gb/s `v1.0` / `full_v8` 签核基线、ISSCC 风格电路切片示意图与专题表征图表。交互式按模块浏览请打开 **[设计工作台](../../web/design/index.html)**。

---

## 一、5.0 Gb/s 双速 Plan-C 签核核心图表（2026-11-26）

| 图表 | 模块与内容 | 对应报告 / 证据 |
|---|---|---|
| [serdes_5g_top_pdk_20261126_light.png](layout/serdes_5g_top_pdk_20261126_light.png) · [深色版](layout/serdes_5g_top_pdk_20261126.png) | **5G Plan-C 全片物理装配（浅色首选）**：`936 × 650 µm (0.6084 mm²)`，13 宏 + 131 去耦 + 加固 M5 PDN，`DRC=0` | [片级版图报告第 9 节](../layout/chip_floorplan_20261123.md#9-50-gbs-plan-c-全片物理装配与层级签核2026-11-26) · [5G 台账](../../results/catalog/serdes_5g_signoff_20261126.json) |
| [serdes_5g_ir_em_20261126.png](layout/serdes_5g_ir_em_20261126.png) | **5G Plan-C 实装几何 2D IR Drop & DC EM 签核**：**8/8 域 IR 与 110 °C EM 全通过**（`VSS ≤ 13.8 mV`） | [analyze_chip_5g_ir_em.py](../../verification/layout/analyze_chip_5g_ir_em.py) |
| [serdes_5g_tt_eyes_20261126.png](system/serdes_5g_tt_eyes_20261126.png) | **5G / 4G 双速 TT 真 CPEX 端到端眼图与均衡**：`TX v5_pdk → C2_loss6 → W3 CTLE` + `slicer_5g` 250× MC | [plot_5g_tt_eyes_20261126.py](../../verification/plotting/plot_5g_tt_eyes_20261126.py) |
| [serdes_5g_16ui_waveforms_20261126.png](system/serdes_5g_16ui_waveforms_20261126.png) | **5G 16-UI 真 CPEX 时域波形对比**：`1010111000100010` 三级对齐波形（`FFE=3` vs `FFE=0`）+ `V_drv` 纹波 | [plot_5g_16ui_waveforms_20261126.py](../../verification/plotting/plot_5g_16ui_waveforms_20261126.py) |
| [serdes_5g_ldo_bias_pdn_20261126.png](verification/serdes_5g_ldo_bias_pdn_20261126.png) | **供电/偏置与 131 瓦片 PDN 稳定性**：HV18 Kelvin RCX、TX `V_drv` `v4p5` CPEX、BIAS v2 温漂/Bode、5G PDN 反谐振 | [verify_5g_stability_suite.py](../../verification/stability/verify_5g_stability_suite.py) |
| [serdes_5g_lcpll_stability_20261126.png](clocking/serdes_5g_lcpll_stability_20261126.png) | **5G 八边形 LC-VCO 与 Type-II LC-PLL 环路稳定性**：调谐窗、原装 `LF k4` 欠阻尼复核 vs 推荐重调及相噪抖动 | [verify_5g_stability_suite.py](../../verification/stability/verify_5g_stability_suite.py) |
| [serdes_5g_vco_pll_char_20261126.png](clocking/serdes_5g_vco_pll_char_20261126.png) | **5G LC-VCO 16 码重叠、`K_vdd` 与闭环 LC-PLL 真瞬态**：48/48 CPEX 无死区、推频与原装/重调锁相杂散实测 | [verify_lc_vco_full_char.py](../../analog/pll/vco_5g/tb/verify_lc_vco_full_char.py) |
| [serdes_5g_digital_v4p1_20261126.png](system/serdes_5g_digital_v4p1_20261126.png) | **5G 数字顶层 `v4p1` 综合表征**：OpenROAD 真实布局、6 角 OCV STA、RTL `±300 ppm` 闭环 CDR 与 PLL 粗搜 FSM | [plot_digital_v4p1_20261126.py](../../verification/plotting/plot_digital_v4p1_20261126.py) |
| [serdes_5g_chip_top_v4p1_20261126.png](layout/serdes_5g_chip_top_v4p1_20261126.png) | **5G Plan-C 端口协同规划**：`v4p1` 32-bit 数字宏与东侧 RX 33-bit 零交叉总线对齐 | [片级版图报告第 9 节](../layout/chip_floorplan_20261123.md#9-50-gbs-plan-c-全片物理装配与层级签核2026-11-26) |
| [vco5g_inductor_sq_oct_fig8_20261124.png](layout/vco5g_inductor_sq_oct_fig8_20261124.png) | **5G LC-VCO 电感拓扑对比**：方形 / 八边形 / 8 字形电感几何与 Q/耦合比较 | [analog/pll/vco_5g](../../analog/pll/vco_5g/README.md) |
| [serdes_5g_top_cosim_20261124.png](system/serdes_5g_top_cosim_20261124.png) | **5G 顶层全链协同仿真**：5.0 Gb/s 发射、信道与接收眼图及锁相波形 | [5G 台账](../../results/catalog/serdes_5g_signoff_20261126.json) |
| [vco5g_lc_div2_oct_pdk.png](../../analog/pll/vco_5g/layout/variants/lc_vco_5g_oct_pdk/vco5g_lc_div2_oct_pdk.png) · [pll_div_ab_5g_v2_pdk.png](../../analog/pll/divider/layout/variants/div_ab_5g_v2_pdk/pll_div_ab_5g_v2_pdk.png) | **5G 时钟核版图**：八边形 LC-VCO（`lc_vco_5g_oct_pdk`）与双速 A/B 分频器（`div_ab_5g_v2_pdk`） | [pll_loop.md](../design/pll_loop.md) · [pll_feedback_data_dividers.md](../design/pll_feedback_data_dividers.md) |
| [serdes_tx_sst_top_pdk.png (v5)](../../analog/tx/sst/layout/variants/v5_pdk/serdes_tx_sst_top_pdk.png) · [serdes_rx_cmos_top_5g_pdk.png](../../analog/rx/cmos_rx/layout/variants/rx_top_5g_pdk/serdes_rx_cmos_top_5g_pdk.png) | **5G TX / RX 顶层版图**：TX SST `v5_pdk` 与 5G RX 集成顶层 `rx_top_5g_pdk` | [tx_sst_v4.md](../design/tx_sst_v4.md) · [rx_cmos_v2.md](../design/rx_cmos_v2.md) |
| [serdes_digital_top_v4.png (v4p1)](../../digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/serdes_digital_top_v4.png) · [v2_cur_kelvin_pdk.png](../../analog/ldo/layout/variants/v2_cur_kelvin_pdk/serdes_pll_supply_hv18_v2_cur_pdk.png) | **5G 数字宏与电源加固**：32-bit `v4p1` 数字宏与 HV18 Kelvin 加固 LDO | [digital_top_v3.md](../design/digital_top_v3.md) · [ldo_v2.md](../design/ldo_v2.md) |

---

## 二、4.0 Gb/s `v1.0` / `full_v8` 签核核心图表

| 图表 | 模块与内容 | 对应报告 |
|---|---|---|
| [serdes_4g_top_pdk_v8_20261124.png](layout/serdes_4g_top_pdk_v8_20261124.png) · [浅色版](layout/serdes_4g_top_pdk_v8_20261124_light.png) | **4G `full_v8` 片级核心装配**：Magic 全规则 `DRC=0` 核心布线总图 | [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md) |
| [serdes_4g_ir_em_analysis_20261124.png](layout/serdes_4g_ir_em_analysis_20261124.png) | **4G IR / EM 电源网分析**：片级供电干线压降与电流密度评估 | [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md) |
| [serdes_chip_floorplan_20261123.png](system/serdes_chip_floorplan_20261123.png) · [serdes_4g_top_cosim_20261123.png](system/serdes_4g_top_cosim_20261123.png) | **4G 片级规划与全链协同仿真**：`845.4 × 601.4 µm` 21 宏规划与模拟顶层短窗联调 | [current.md](../status/current.md) |
| [pll_v4_closed_loop_20261123.png](clocking/pll_v4_closed_loop_20261123.png) | **PLL v4 闭环**：7/7 PVT 锁相收敛、LDO 安静轨、`Vctrl` 与杂散签核波形 | [pll_loop.md](../design/pll_loop.md) |
| [vco_r6_ptat_perf_20261123.png](clocking/vco_r6_ptat_perf_20261123.png) | **VCO r6 + PTAT**：`sym9_clean` CPEX 八相正交误差、相噪谱与 PLL v4 抖动预算 | [pll_vco_r6_perf.md](../design/pll_vco_r6_perf.md) |
| [tspc_reclock_multiangle.png](clocking/dividers/tspc_reclock_multiangle.png) · [saff_reclock_v2_waveforms.png](clocking/dividers/saff_reclock_v2_waveforms.png) | **SAFF-TSPC ÷8**：四架构多角度对比与 `v2` 双端原生 RCX 波形 | [pll_tspc_reclock_divider.md](../design/pll_tspc_reclock_divider.md) |
| [tx_sst_v4_eyes.png](tx/tx_sst_v4_eyes.png) | **TX SST v4.3**：4 Gb/s 焊盘与 `C2_loss6` 远端 2-tap FFE 均衡眼图 | [tx_sst_v4.md](../design/tx_sst_v4.md) |
| [rx_cmos_v2_signoff.png](rx/rx_cmos_v2_signoff.png) | **RX CMOS v2.2**：端到端 CTLE / PI / Double-Tail / 解串签核眼图与 PI INL | [rx_cmos_v2.md](../design/rx_cmos_v2.md) |
| [stability_pdn_20261123.png](verification/stability_pdn_20261123.png) | **PDN 稳定性**：片级去耦阻抗与串联阻尼谐振抑制验证 | [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md) |
| [serdes_digital_top_v3.png](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/serdes_digital_top_v3.png) | **Digital Top v3.1**：`338.1 × 307.4 µm` 统一精简数字宏版图 | [digital_top_v3.md](../design/digital_top_v3.md) |
| [serdes_tx_sst_top_pdk.png (v4)](../../analog/tx/sst/layout/variants/v4_pdk/serdes_tx_sst_top_pdk.png) · [serdes_rx_cmos_top_pdk.png (v2)](../../analog/rx/cmos_rx/layout/variants/v2_pdk/serdes_rx_cmos_top_pdk.png) | **4G TX / RX 物理版图**：TX SST `v4_pdk` 与 CMOS RX `v2_pdk` 顶层预览 | [docs/layout/README.md](../layout/README.md) |
| [serdes_pll_supply_hv18_v2_cur_pdk.png](../../analog/ldo/layout/variants/v2_cur_pdk/serdes_pll_supply_hv18_v2_cur_pdk.png) · [serdes_bias_top_v2_pdk.png](../../analog/bias/layout/variants/v2_pdk/serdes_bias_top_v2_pdk.png) | **LDO & BIAS 物理版图**：HV18 LDO `v2_cur` 与 BIAS v2 顶层预览 | [ldo_v2.md](../design/ldo_v2.md) · [bias_v2.md](../design/bias_v2.md) |

---

## 三、ISSCC 风格叠层切片原理图与专题子目录

| 目录 / 文件 | 涵盖内容 |
|---|---|
| [`schematics/`](schematics/) | ISSCC 风格叠层切片原理图：[TX SST](schematics/tx_sst_stacked_slices.png) · [RX PI](schematics/rx_pi_stacked_slices.png) |
| [`system/`](system/README.md) | 工作台截图、片级规划、4G/5G 顶层联调、5G TT 眼图与数字 `v4p1` 表征 |
| [`layout/`](layout/) | 5G Plan-C 全片版图/IR-EM、4G `full_v8`/IR-EM 与 5G LC-VCO 电感对比图 |
| [`clocking/`](clocking/) | 5G LC-PLL 环路稳定性、PLL v4 闭环、VCO r6/PTAT 与 SAFF-TSPC ÷8 波形 |
| [`tx/`](tx/) | TX SST v4 签核眼图 |
| [`rx/`](rx/) · [`rx/pi/`](rx/pi/README.md) | RX CMOS v2 签核图、CMOS PI 原理与内部边沿图 |
| [`channel/characterization/`](channel/characterization/README.md) | 共享 `C0–C5` 合成 PCB 信道频响与单位脉冲响应 |
| [`verification/`](verification/) | 5G 供电/偏置/PDN 稳定性总图与 4G PDN 稳定性验证图 |
