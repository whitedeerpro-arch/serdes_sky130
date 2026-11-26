# 模块设计文档索引（`docs/design/`）

项目级采用状态与验证数字唯一汇总见 [current.md](../status/current.md)，片级版图与 PDN 规划见 [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md)，修订线与源码身份见 [revisions.md](../overview/revisions.md)。固定证据台账见 [v1.0 证据目录](../../results/catalog/v1_0_subsystem_evidence.json) 与 [5G 签核台账](../../results/catalog/serdes_5g_signoff_20261126.json)。

本目录按 **5.0 Gb/s 双速（4/5 Gb/s）Plan-C 演进路线** 与 **4.0 Gb/s 环振主线（v1.0 基线与共享模拟子系统）** 组织现行模块设计依据。

---

## 一、5.0 Gb/s 双速 Plan-C 演进路线（2026-11-26 签核）

在完整保留 4 Gb/s `v1.0` 基线的前提下，独立演进的 5.0 Gb/s 双速（4/5 Gb/s）子系统均已完成真 CPEX/RCX 签核与 Plan-C 全片装配签核（详见 [5G 签核台账](../../results/catalog/serdes_5g_signoff_20261126.json)）：

| 子系统 | 5G 隔离变体 / 物理入口 | 对应设计文档与源码入口 |
|---|---|---|
| **5G 八边形 LC-VCO** | `lc_vco_5g_oct_pdk`（4.469–5.350 GHz 公共交集、125 °C 冻码 PASS） | [PLL 环路](pll_loop.md) · [analog/pll/vco_5g](../../analog/pll/vco_5g/README.md) · [verify_lc_vco_oct_cpex.py](../../analog/pll/vco_5g/tb/verify_lc_vco_oct_cpex.py) |
| **5G 双速 A/B 分频器** | `div_ab_5g_v2_pdk`（`÷8 / ÷10` 12/12 + 50/50 冷角 MC） | [反馈 A 与精准分频 B](pll_feedback_data_dividers.md) · [analog/pll/divider](../../analog/pll/divider/README.md) |
| **供电与偏置加固** | `v2_cur_kelvin_pdk`（HV18 Kelvin）· `v4p5_pdk`（TX VDRV LDO） | [HV18 LDO v2/v2_cur/Kelvin](ldo_v2.md) · [BIAS v2](bias_v2.md) · [analog/ldo](../../analog/ldo/README.md) |
| **5G TX SST 顶层** | `tx/sst/layout/variants/v5_pdk`（CPEX 16/16 5G+4G PASS） | [TX SST v4/v5](tx_sst_v4.md) · [analog/tx](../../analog/tx/README.md) |
| **5G RX 集成顶层** | `rx_top_5g_pdk`（`W3 CTLE` + `slicer_5g_pdk` + `v5g_4ph_v3_pdk`） | [CMOS RX v2/5G](rx_cmos_v2.md) · [analog/rx](../../analog/rx/README.md) |
| **5G 32-bit 数字顶层 `v4p1`** | `hd_pnr_v4p1_5g_coopt`（6 角 ±5% OCV 全 MET、RX 33-bit 零交叉） | [数字顶层 v3/v4p1](digital_top_v3.md) · [digital/README.md](../../digital/README.md) |
| **Plan-C 全片装配** | `serdes_5g_top_pdk`（`936 × 650 µm`，DRC=0，层级提取 28/28 & 41/41） | [片级版图报告第 9 节](../layout/chip_floorplan_20261123.md#9-50-gbs-plan-c-全片物理装配与层级签核2026-11-26) · [analog/layout](../../analog/layout/README.md) |

---

## 二、4.0 Gb/s 环振主线与共享子系统文档

| 子系统 | 设计文档 | 源码与验证入口 |
|---|---|---|
| **PLL 环路架构** | [PLL 环路（PFD / CP v4 / 融合 LF k4 / 启动与供电）](pll_loop.md) | [analog/pll](../../analog/pll/README.md) · [analog/pll/top](../../analog/pll/top/README.md) |
| **4G 环振 VCO** | [VCO r6 + BIAS v2 PTAT `28/66` 温补码窗](pll_vco_r6_ptat.md) · [r6 `sym9_clean` CPEX 与相噪/抖动](pll_vco_r6_perf.md) | [analog/pll/vco](../../analog/pll/vco/README.md) |
| **电荷泵与环路滤波器** | [CP v4 / v4.1 副本主动伺服匹配](pll_cp_v4.md) | [analog/pll/cp](../../analog/pll/cp/README.md) · [analog/pll/loop_filter](../../analog/pll/loop_filter/README.md) · [analog/pll/pfd](../../analog/pll/pfd/README.md) |
| **分频与时钟接收** | [SAFF-TSPC 重定时 ÷8 预分频器](pll_tspc_reclock_divider.md) · [PLL 反馈 A 与精准分频 B](pll_feedback_data_dividers.md) · [CML→CMOS 时钟接收器](clock_receiver.md) | [analog/pll/divider](../../analog/pll/divider/README.md) · [analog/common/cml_to_cmos](../../analog/common/cml_to_cmos/README.md) |
| **电源与偏置** | [HV18 LDO v2 / v2_cur / Kelvin](ldo_v2.md) · [BIAS v2 折叠共栅带隙与统一宏](bias_v2.md) | [analog/ldo](../../analog/ldo/README.md) · [analog/bias](../../analog/bias/README.md) |
| **发送端（TX）** | [TX SST v4（含 5G v5 演进入口）](tx_sst_v4.md) | [analog/tx](../../analog/tx/README.md) |
| **接收端（RX）** | [CMOS RX v2（含 5G 顶层与 CTLE 演进）](rx_cmos_v2.md) | [analog/rx](../../analog/rx/README.md) |
| **数字顶层** | [统一精简数字顶层 v3.1（含 5G 32-bit v4p1 入口）](digital_top_v3.md) | [digital/README.md](../../digital/README.md) |
| **信道与辅助监测** | [RLC16 与合成 PCB 信道族 C0–C5](channel_model.md) · [慢速模拟/数字监测工具包](monitor.md) | [verification/models/channel](../../verification/models/channel/) · [analog/common/monitor](../../analog/common/monitor/README.md) |
