# 架构与接口

> **2026-11-26 收敛架构**：主推 **5.0 Gb/s 双速（4/5 Gb/s）LC-PLL + CMOS/SST SerDes（`serdes_5g_top_pdk`，Plan-C）**，由 5 GHz 八边形 LC-VCO+正交 ÷2、双速 A/B 分频（÷8/÷10）、HV18 Kelvin LDO + BIAS v2、CMOS/SST TX `v5`、W3 峰化 CTLE + `4→8` I/Q PI v3 + 5G Double-Tail RX 及 32-bit 降频双速数字顶层 `v4p1` 组成；同时保留 **4.0 Gb/s 无电感环振基线（`v1.0` / `full_v8`）** 作无电感参照。

当前采用状态与实测验证边界统一见 **[current.md](../status/current.md)**，片级物理装配与 2026-11-26 实装复核见 **[chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md)**，模块设计入口见 **[docs/design/README.md](../design/README.md)**。

---

## 1. 主推 5.0 Gb/s 双速（4/5 Gb/s）Plan-C 系统总览与时钟域

![5G SerDes Plan-C 全片物理架构与实装版图（Magic DRC = 0）](../figures/layout/serdes_5g_top_pdk_20261126.png)

| 时钟域 | 5 Gb/s 模式（UI = 200 ps） | 4 Gb/s 模式（UI = 250 ps） | 来源与驱动边界 |
|---|---|---|---|
| **参考时钟 (`ref_clk`)** | `250 MHz` / `4.0 ns` | `250 MHz` / `4.0 ns` | 外部参考，驱动 `pll_pfd_sc_dly` 与 `pll_control_top`（内部同步 ÷4 至 `62.5 MHz` 监督粗搜/启动） |
| **LC-VCO 与首级 I/Q** | `5.0 GHz` 振荡 → `2.5 GHz` 四相 I/Q | `4.0 GHz` 振荡 → `2.0 GHz` 四相 I/Q | 八边形 LC-VCO + 正交 ÷2（`lc_vco_5g_oct_pdk`），经 `5G I/Q 时钟组宏`（2× `r5` CML→CMOS + 侧置偏置）输出满摆幅 CMOS I/Q |
| **PLL 反馈 (`fb_clk`)** | `250 MHz`（`2.5 GHz ÷ 10`） | `250 MHz`（`2.0 GHz ÷ 8`） | 双速 A/B 反馈分频器 `div_ab_5g_v2_pdk` 回接 `pll_pfd_sc_dly` |
| **TX 4 相与字时钟** | `1.25 GHz` 四相 / `312.5 MHz` 16-bit 边界 → `156.25 MHz` 内部 32-bit | `1.0 GHz` 四相 / `250 MHz` 16-bit 边界 → `125 MHz` 内部 32-bit | `tx_qdiv2_5g` 将 CMOS I/Q 转为四分之一速四相，驱动 `TX SST v5` 16:4 串化器并回传 `tx_word_clk` 至数字 `v4p1` |
| **RX 恢复 8 相与字时钟** | `1.25 GHz` 八相 / `312.5 MHz` 16-bit 边界 → `156.25 MHz` 内部 32-bit | `1.0 GHz` 八相 / `250 MHz` 16-bit 边界 → `125 MHz` 内部 32-bit | `4→8` I/Q CMOS PI v3 + 8 相正交 ÷2 驱动 8 路 5G Double-Tail 采样器（4 Data + 4 Edge）与解串器；经 33-bit 零交叉总线进数字 `v4p1` 对齐、32-UI BBPD CDR 与异步 FIFO |
| **宿主时钟 (`host_clk`)** | `160 MHz × 32-bit`（峰值 `5.12 Gb/s`） | `160 MHz × 32-bit`（弹性降速） | 外部异步宿主域，经 `8×32` 格雷码异步 FIFO 与线侧时钟域解耦，在 SKY130A 1.65 V 冷角下彻底闭合 6 角 ±5% OCV 时序 |

---

## 2. 5.0 Gb/s Plan-C 关键信号链结构

### 2.1 LC-PLL、双速分频与安静供电
- **环路组成**：`pll_pfd_sc_dly` → 200 µA 宽摆幅电荷泵 `CP v4` → 6 站点堆叠 MIM 融合二阶无源滤波器 `LF v2`（`Rz = 4.13 kΩ, Ci = 18 pF`）→ 八边形 LC-VCO + 正交 ÷2（`lc_vco_5g_oct_pdk`，中心化尾管、4-bit MIM 粗调 + LVT 变容管，跨 `125 °C` 单码冻锁）→ 侧置偏置 5G I/Q 时钟组宏（`clk_host_5g`）→ 双速 A/B 分频器 `div_ab_5g_v2_pdk`（÷8/÷10）。
- **供电与偏置**：HV18 Native-NMOS Kelvin 回流 LDO（`v2_cur_kelvin_pdk`，负载侧取样电阻降 `-92.9%`）提供独立安静供电轨 `VDD_Q`；`BIAS v2` 提供 `Vbg / Vcm / Ibias` 全片偏置分配；全片共 8 组紧缩 Direct/Damped/HV33 混合去耦阵（131 块瓦片、`147.03 pF` 顶层 + 宏内置共 `~331 pF`）与双 P+ 衬底隔离沟。

### 2.2 TX CMOS/SST v5（16:1，4/5 Gb/s）
- **前端串化与切片驱动**：全静态 CMOS 16:4 多路选择树 + 四相交错重定时，驱动 28 个并联 N-over-N 源端串联端接（SST）切片（23 Main + 5 Post-1 FFE），由压紧加固版 `1.8 V → 0.44 V` `V_drv` 子稳压器（`v4p5_pdk` / `v5_pdk`）供电，消除冷角直通并直接匹配 `100 Ω` 差分阻抗与 `400 mVpp` 标称摆幅；在 Plan-C 中 `R270_MX` 摆放、正南直出 `TX_PAD_P/N`。

### 2.3 RX CMOS 5G（1:16，4/5 Gb/s）
- **模拟前端**：片上 `100 Ω` 差分端接 + `W3` 紧凑电感峰化 CTLE（`M4+M2` 0% M5 紧凑 12 匝电感 `8.20 nH`，覆盖 `C2` 无 FFE 与 `C3+FFE` 5 Gb/s 损耗），在 Plan-C 中正东直出 `RX_IN_P/N`（与 TX 正南出线呈 90° 正交）。
- **时钟、采样与解串**：`4→8` 电阻线性化八相前级 + 2.5 GHz 64 码纯 CMOS PI v3（混合 PMOS `qdiv2` + 自愈 XNOR 注入防 180° 歧义）→ 8 路 1:1 直插 5G Double-Tail 采样器（`slicer_5g_pdk`，6-bit 失调修调覆盖 `≥ 8σ`）→ 8→32 解串器。
- **端口协同数字顶层 `v4p1`**：`serdes_digital_top_v4` 南侧 33-bit RX 数据/边沿/时钟引脚与 `rx_top_5g` 北口 1:1 零交叉对齐，内部完成 16↔32 打包、字对齐、32-UI 二阶 BBPD CDR（`±300 ppm`）及 `8×32` 异步 FIFO 跨时钟出口。

---

## 3. 4.0 Gb/s 无电感环振基线（`v1.0` / `full_v8`）差异摘要

为无电感工艺与面积对照保留的 4 Gb/s 环振基线（`845.4 × 601.4 µm = 0.5084 mm²`）与 5G Plan-C 的核心差异如下（详见 [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md)）：
- **时钟源**：2 GHz 四级差分 CML 环振 `r6` + PTAT `28/66`（`sym9_clean`）+ `bias_filter_r4` 慢尾滤波 + 4× `r5` CML→CMOS + `SAFF-TSPC ÷8`（VCO 上升过零八相顺序：`0°: d0 · 45°: −d1 · 90°: d2 · 135°: −d3 · 180°: −d0 · 225°: d1 · 270°: −d2 · 315°: d3`）；
- **TX / RX / Digital**：TX SST `v4.3`、无电感 RC 退化 CTLE + 2 GHz 8 相直接输入 CMOS PI 的 RX `v2.2`、以及 `16-bit × 250 MHz` 宿主域数字顶层 `serdes_digital_top_v3`（v3.1/v3.2）。

![4 Gb/s 无电感环振基线片级规划图](../figures/system/serdes_chip_floorplan_20261123.png)

---

## 4. 目录所有权与工程约定

| 目录 | 职责 |
|---|---|
| `analog/pll/` | 5G LC-VCO（`vco_5g/`）、4G 环振（`vco/`）、双速 A/B 与 SAFF-TSPC 分频（`divider/`）、`cp/`、`loop_filter/`、`pfd/`、`coarse/`、`top/` |
| `analog/tx/sst/` | 发送端 CMOS/SST 主线（5G `v5_pdk`、4G `v4_pdk` / `v4p4_pdk` / `v4p5_pdk`） |
| `analog/rx/cmos_rx/` | 接收端 CMOS 主线（5G `rx_top_5g_pdk` 含 W3 CTLE / PI v3 / slicer 5G，及 4G `v2_pdk` / `v2p3_pdk`） |
| `analog/ldo/` | HV18 安静供电 LDO（`v2_cur_kelvin_pdk`、`v2_cur_pdk` 与 `bias_filter_r4`） |
| `analog/bias/` | 带隙参考、FC-OTA、缓冲与偏置分配（`BIAS v2`） |
| `analog/common/` | 跨模块底层原语（`cml_to_cmos/` `r5`、`devices/`、`monitor/`） |
| `analog/layout/` | 公共 SKY130A Magic PDK 版图绘图内核（`scripts/layout_core.py`） |
| `digital/pnr/` | 5G 32-bit 双速顶层 `rtl_v4_32b/`（`v4p1`）与 4G 顶层 `rtl_v3/`、OpenROAD P&R 流程与签核目录 |
| `src/serdes_flow/` | 仿真编排、PVT/MC、眼图/抖动分析、SKY130 $g_m/I_D$ 与贝叶斯/Pareto 优化库 |
| `verification/` | PCB 信道 `.s4p` 模型（`C0–C5`）、5G/4G 片顶装配器、`route_manhattan` / `floorplan_opt`、PDN 稳定性与绘图 |

每个活跃模拟模块仅按需包含 `spice/`（权威网表）、`tb/<case>/`（独立测试台）与 `layout/`（PDK 生成器与签核摘要）；DUT 只放电路与参数，电源/激励/负载/测量统一在测试台。编码（8b/10b、64b/66b）与加扰未纳入当前原始线速首版。
