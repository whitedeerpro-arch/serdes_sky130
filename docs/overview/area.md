# 芯片面积汇总（实测版图签核）

本页汇总 2026-11-26 两条物理实现线的实测版图外框面积，数据均直接读取本机签核 `.mag` 与 `.def` 几何边界。片级摆位、去耦配置与 2026-11-26 实装复核详见 [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md)。

---

## 1. 主推设计：5.0 Gb/s 双速 Plan-C（`serdes_5g_top_pdk`）实测面积

核心尺寸 **`936.0 × 650.0 µm = 608,400.0 µm²（0.6084 mm²，AR = 1.44）`**（较 Plan A `0.778 mm²` 缩减 `-21.8%`），数据源见 [build_chip_top_5g_pdk.py](../../verification/layout/build_chip_top_5g_pdk.py) 与 [serdes_5g_signoff_20261126.json](../../results/catalog/serdes_5g_signoff_20261126.json)：

| 供电域 | 实例名 | 签核单元名 | 摆放后 `W × H` (µm) | 面积 (µm²) | 顶层去耦瓦片 / 电容 |
|---|---|---|---:|---:|---:|
| `vdd_hv33` | `ldo_kelvin` | `serdes_pll_supply_hv18_v2_cur_pdk` | `312.52 × 121.42` | `37,946.18` | 12 HV33 (`7.46 pF`) |
| `vdd_q` | `lc_vco_oct` | `vco5g_lc_div2_oct_pdk` | `372.50 × 266.00` | `99,085.00` | 24 Direct (`30.36 pF`) |
| `vdd_q` | `lf_k4` | `pll_loop_filter_k4_fused_pdk` | `98.34 × 64.90` | `6,382.27` | 同域共享 |
| `vdd_q` | `cp_v4` | `pll_cp_steer_v4_pdk` | `58.98 × 43.70` | `2,577.43` | 同域共享 |
| `vdd_q` | `pfd` | `pll_pfd_sc_dly_pdk` | `25.25 × 5.94` | `149.99` | 同域共享 |
| `vdd_q` | `bias_cp` | `serdes_bias_cp_v2_pdk` | `8.89 × 11.58` | `102.95` | 同域共享 |
| `vdd_bias` | `bias_top_v2` | `serdes_bias_top_v2_pdk` | `176.53 × 152.26` | `26,878.46` | 6 Direct (`7.59 pF`) |
| `vdd_a` | `clk_host_5g` | `serdes_5g_cml_clock_host` | `91.96 × 65.89` | `6,059.24` | 12 Direct + 12 Damped (`27.78 pF`) |
| `vdd_a` | `div_ab_5g_v2` | `pll_div_ab_5g_v2_pdk` | `23.00 × 160.42` | `3,689.66` | 同域共享 |
| `vdd_a` | `tx_qdiv2_5g` | `serdes_rx_qdiv2_8ph_5g_pdk` | `17.97 × 137.60` | `2,472.67` | 同域共享 |
| `vdd_tx` | `tx_sst_v5` | `serdes_tx_sst_top_pdk` | `169.58 × 256.80` | `43,548.14` | 8 Direct + 7 Damped (`17.47 pF`) |
| `vdd_rx` | `rx_top_5g` | `serdes_rx_cmos_top_5g_pdk` | `312.10 × 199.40` | `62,232.74` | 11 Direct + 11 Damped (`25.46 pF`) |
| `vdd_d` | `digital_v4` | `serdes_digital_top_v4` (`v4p1`) | `385.90 × 353.60` | `136,454.24` | 7 Direct + 21 Damped (`30.91 pF`，另宏内置 `88.93 pF`) |
| **有源宏合计（13 宏）** | — | **7 供电域** | — | **`427,578.96`**（`70.3%`） | — |
| **紧缩去耦阵（8 组）** | 131 块瓦片 | `20.8 × 17.2 µm`（68 Direct / 51 Damped / 12 HV33） | — | **`66,474.00`**（`10.9%`） | 顶层 **`147.03 pF`**（含宏内置约 `331 pF`） |
| **核心外框合计** | `serdes_5g_top_pdk` | 含双 P+ 隔离沟、电源环与通道 | **`936.0 × 650.0`** | **`608,400.00`**（`0.6084 mm²`） | 宏 + 去耦总填充 **`81.2%`** |

---

## 2. 无电感对照基线：4.0 Gb/s 环振（`v1.0` / `full_v8`）规划外框

核心尺寸 **`845.4 × 601.4 µm = 508,423.6 µm²（0.5084 mm²，AR = 1.41）`**，按规划供电域汇总如下：

| 供电域 | 功能实例 | 数量 | 外框面积 (µm²) |
|---|---|---:|---:|
| `vdd_hv33` | HV18 LDO `v2_cur` | 1 | `37,958.68` |
| `vdd_q` | 环振 `r6`、尾偏置慢滤波、LF、CP、CP 偏置 | 5 | `28,068.51` |
| `vdd_bias` | BIAS v2、VCO PTAT 和本地 CML 偏置 | 3 | `37,805.02` |
| `vdd_a` | 四组 `r5` 接收器、SAFF-TSPC ÷8、PFD 和时钟偏置 | 7 | `9,631.46` |
| `vdd_tx` | TX SST 顶层 (`v4.3`) 和 TX 正交 ÷2 | 2 | `37,041.03` |
| `vdd_rx` | CMOS RX 顶层 (`v2.2`) 和 CTLE 偏置 | 2 | `47,955.91` |
| `vdd_d` | 数字顶层 `v3.1` | 1 | `103,931.94` |
| **功能实例合计** | | **21** | **`302,392.55`**（`59.5%`） |

`full_v8` 实装装配含 20 颗合并功能宏与 12 组共 208 块混合去耦瓦片（`8.0 µm` 极板，`245.2 pF`）；两版均不含外圈 Padring/ESD，Padring 面积随 I-TOP-01 锁定。
