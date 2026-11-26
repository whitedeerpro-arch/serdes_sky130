# 芯片面积汇总（实测版图签核）

片级集成以[片级规划](../layout/chip_floorplan_20261123.md)的摆位外框为准，脚本读取本机 `.mag` 和 `.def`。模块自己的签核报告记录对应修订的局部边界。下表按规划使用的供电域汇总，可与规划的实例清单逐项核对。

## 1. 4 Gb/s 规划外框

| 供电域 | 功能实例 | 数量 | 外框面积 (µm²) |
|---|---|---:|---:|
| `vdd_hv33` | HV18 LDO v2_cur | 1 | 37,958.68 |
| `vdd_q` | 环振、尾偏置慢滤波、LF、CP、CP 偏置 | 5 | 28,068.51 |
| `vdd_bias` | BIAS v2、VCO PTAT 和本地 CML 偏置 | 3 | 37,805.02 |
| `vdd_a` | 四组 r5 接收器、SAFF-TSPC ÷8、PFD 和时钟偏置 | 7 | 9,631.46 |
| `vdd_tx` | TX SST 顶层和 TX 正交 ÷2 | 2 | 37,041.03 |
| `vdd_rx` | CMOS RX 顶层和 CTLE 偏置 | 2 | 47,955.91 |
| `vdd_d` | 数字顶层 v3.1 | 1 | 103,931.94 |
| **功能实例合计** | | **21** | **302,392.55** |

慢尾滤波的 `100.18 × 103.21 µm` 摆位包络来自当前 Magic 几何。TX 的 `231.50 × 146.98 µm` 记录属于 v4.3 基线。微修后本机独立审阅的 TX 顶层摆位外框为 `232.52 × 150.58 µm`。核心外框、去耦预留与 Padring 边界见[片级规划](../layout/chip_floorplan_20261123.md)。

## 2. 历史参考：早期版图前 CML 粗估（2026-11-07）

早期未画版图前对旧全 CML 架构（r5 PLL + CML TX + 11-03 CML RX，不含数字宏、LDO、阻尼 PDN 与布线通道）的脚本粗估合计约 `0.28 mm²` 有源 + `0.036 mm²` MIM（≈ `0.31 mm²`，原始数据 [area_estimate.json](../data/area_estimate.json)，脚本 [area_estimate.py](../../verification/analysis/area_estimate.py)）。切换到 CMOS/SST TX & RX 主线架构并完成真实版图后，TX 仅 `0.034 mm²`、RX 仅 `0.048 mm²`、全套数字 Top 仅 `0.104 mm²`，含全部 LDO/Bias/PDN 去耦与布线通道的整片核心控制在 `0.508 mm²`。
