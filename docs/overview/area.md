# 芯片面积汇总（实测版图签核）

> **权威实测数据**：以下全部宏尺寸均直接读取自 SKY130A 已签核（`Magic DRC = 0` / `Netgen LVS = MATCH`）的真实 `.mag` 与 `.def` 外框；完整摆位坐标、引脚对齐与阻尼 PDN 填充方案见 **[chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md)**（生成脚本：[plan_chip_floorplan.py](../../verification/layout/plan_chip_floorplan.py)）。

---

## 1. 4 Gb/s NRZ SerDes 实测片级面积（`0.5084 mm²` 核心）

片级规划核心外框 **`845.4 × 601.4 µm = 508,424 µm²（0.5084 mm²）`**，21 个功能宏合计 `302,393 µm²`（`59.5%`），空腔部署 12 块阻尼 MIM1+MIM2 PDN 去耦阵（`109,500 µm²` / `761.0 pF`），总物理填充率 **`81.0%`**，**`0.0 µm²` 重叠**，全片总片上电容 **`957.9 pF`**。

| 子系统 | 包含已签核宏 | 宏数量 | 实测面积 (`µm²`) | 占核心比 | 版图入口 |
|---|---|---:|---:|---:|---|
| **Digital Top v3.1** | `serdes_digital_top_v3`（PLL Ctrl + TX Ingress + RX Align/FIFO + BBPD CDR） | 1 | `103,932` | `20.4%` | [digital_top_v3.md](../design/digital_top_v3.md) |
| **RX CMOS/SST v2.2** | `serdes_rx_cmos_top_pdk` + 独立 8 相分频/PI/采样/解串一体化宏 | 1 (+ 复用) | `47,932` | `9.4%` | [rx/cmos_rx/v2_pdk](../../analog/rx/cmos_rx/layout/variants/v2_pdk/README.md) |
| **TX CMOS/SST SST v4.3** | `serdes_tx_sst_top_pdk`（16:4 串化 + 28-slice SST + `0.44 V` LDO） | 1 | `34,026` | `6.7%` | [tx/sst/v4_pdk](../../analog/tx/sst/layout/variants/v4_pdk/README.md) |
| **PLL v4 模拟核** | VCO `sym9_clean` + PTAT 偏置 + CP v4 + 融合 LF v2 + PFD + SAFF-TSPC ÷8 + `r5` CML→CMOS 等 | 9 | `32,684` | `6.4%` | [docs/layout/README.md](../layout/README.md) |
| **HV18 LDO v2_cur** | `serdes_pll_supply_hv18_v2_cur_pdk` + VCO 慢尾偏置滤波 `bias_filter_r4` | 2 | `29,859` | `5.9%` | [ldo/v2_cur_pdk](../../analog/ldo/layout/variants/v2_cur_pdk/README.md) |
| **BIAS v2** | `serdes_bias_top_v2_pdk` + 本地 `cml`/`cp`/`ctle` 偏置拷贝宏 | 4 | `28,274` | `5.6%` | [bias/v2_pdk](../../analog/bias/layout/variants/v2_pdk/README.md) |
| **其余辅助/扇出宏** | 时钟扇出 / 本地复制缓冲与对齐预留宏 | 3 | `25,686` | `5.1%` | [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md) |
| **功能宏合计** | 全部 21 个独立签核宏 | **21** | **`302,393`** | **`59.5%`** | — |
| **阻尼 PDN 去耦阵** | 12 块 MIM1+MIM2 + 串联阻尼电阻（`761.0 pF`, `R_eq = 1.51 Ω`） | 12 | `109,500` | `21.5%` | [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md) |
| **走线通道与隔离沟** | 2 GHz 时钟通道、安静模拟保护沟与电源总线 | — | `96,531` | `19.0%` | — |
| **芯片核心总计** | **`845.4 × 601.4 µm`**（不含外圈 Padring / ESD） | — | **`508,424`** (`0.5084 mm²`) | **`100.0%`** | — |

---

## 2. 历史参考：早期版图前 CML 粗估（2026-11-07）

早期未画版图前对旧全 CML 架构（r5 PLL + CML TX + 11-03 CML RX，不含数字宏、LDO、阻尼 PDN 与布线通道）的脚本粗估合计约 `0.28 mm²` 有源 + `0.036 mm²` MIM（≈ `0.31 mm²`，原始数据 [area_estimate.json](../data/area_estimate.json)，脚本 [area_estimate.py](../../verification/analysis/area_estimate.py)）。切换到 CMOS/SST TX & RX 主线架构并完成真实版图后，TX 仅 `0.034 mm²`、RX 仅 `0.048 mm²`、全套数字 Top 仅 `0.104 mm²`，含全部 LDO/Bias/PDN 去耦与布线通道的整片核心控制在 `0.508 mm²`。
