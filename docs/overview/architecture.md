# 架构与接口

> **当前 4 Gb/s 主线架构（CMOS/SST TX & RX + 2 GHz 环振 PLL）**：共享 **2 GHz 八相 PLL v4** 驱动本地 **CMOS/SST SST 发送端（TX v4.3）** 与每路 **CMOS/SST CMOS 接收端（RX v2.2）**，全部控制/对齐/FIFO/CDR 逻辑整合在统一多速率数字顶层宏 **`serdes_digital_top_v3`（v3.1）** 中，由独立 **HV18 LDO（`v2_cur`）** 与 **BIAS v2** 提供干净电源与偏置。

当前采用状态与实测验证边界统一见 **[current.md](../status/current.md)**，片级物理整合见 **[chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md)**，模块文档见 **[docs/design/README.md](../design/README.md)**。

---

## 1. 系统总览与时钟域

![片级物理规划与子系统拓扑](../figures/system/serdes_chip_floorplan_20261123.png)

| 时钟域 | 频率 / 周期 | 来源 | 用途与驱动边界 |
|---|---|---|---|
| **参考时钟 (`ref_clk`)** | `250 MHz` / `4.0 ns` | 外部参考 | PLL PFD 参考输入及 `pll_control_top` 根时钟（内部同步 ÷4 至 `62.5 MHz` 驱动 5-bit 粗搜/启动监督） |
| **VCO 多相时钟** | `2 GHz`（八相 `45°` 间隔） | 四级环振 `r6` + PTAT `28/66`（`sym9_clean` CPEX） | 经 CML→CMOS 接收器供片级反馈、TX 前级正交 ÷2 及 RX 2 GHz CMOS PI |
| **PLL 反馈 (`fb_clk`)** | `250 MHz` / `4.0 ns` | `r5` CML→CMOS + SAFF-TSPC 重定时 ÷8 | 进入标准单元 PFD (`pll_pfd_sc_dly`) 与相位窗锁定检测 |
| **TX 字时钟 (`tx_word_clk`)** | `250 MHz` / `4.0 ns` | TX 前级正交 ÷2 将 2 GHz 转为 1 GHz 四相。SST 顶层进一步得到 500 MHz 和 250 MHz | 驱动 `tx_ingress_control` 16-bit 字捕获与 16:4 CMOS 串化器 |
| **RX 恢复 8 相时钟** | `1 GHz`（4 数据相 + 4 边沿相） | 2 GHz 64 码纯 CMOS PI + 8 相正交 ÷2 (`qdiv2`) | 驱动四分之一速 Double-Tail 动态 CMOS 采样器（4 Data + 4 Edge），连续调相跟踪每路远端 `±300 ppm` 频偏 |
| **RX 恢复字时钟 (`rx_word_clk`)** | `250 MHz` / `4.0 ns` | RX `deser16` 8→32 解串器输出 | 驱动共享 `rx_word_map`、`rx_word_align16`、异步 FIFO 写端；内部同步 ÷2 至 `125 MHz` (`cdr_clk_div2`) 驱动 2 阶 BBPD CDR |
| **宿主时钟 (`host_clk`)** | `250 MHz`（异步） | 外部系统域 | 异步 FIFO 读端（格雷码指针双拍同步 + 无条件预取保护） |

---

## 2. 关键信号链结构

### 2.1 PLL v4（250 MHz → 2 GHz 八相）

以下为片级集成目标。发布原理图闭环固定粗码并预充 LF，反馈仍经 `clock_frontend_r6q` 的 CML ÷8；相应验证覆盖见[当前状态](../status/current.md)。

- **VCO 八相顺序**（物理级号并非相位顺序，实测上升过零顺序 `d_k = q_kp − q_kn`，2 GHz 下相邻间隔 `62.5 ps = 0.25 UI`）：
  `0°: d0` · `45°: −d1` · `90°: d2` · `135°: −d3` · `180°: −d0` · `225°: d1` · `270°: −d2` · `315°: d3`
- **环路组成**：`pll_pfd_sc_dly` → 200 µA 主动伺服宽摆幅电荷泵 `CP v4/v4.1` → 6 站点堆叠 MIM1+MIM2 融合二阶无源滤波器 `LF v2`（`Rz = 4.13 kΩ, Ci = 18 pF`）→ `VCO r6`（5-bit / 31 单元电容阵 + BIAS v2 PTAT `28/66` 尾流温补）→ `r5` CML→CMOS + `SAFF-TSPC ÷8`。
- **安静供电域**：HV18 Native-NMOS LDO（`v2_cur`）提供独立安静供电轨 `quiet ≈ 1.79 V`，配 `1 MΩ / 16 pF` 慢 RC 滤波器（`bias_filter_r4`）隔离尾偏置噪声。

### 2.2 TX CMOS/SST SST v4.3（16:1，4 Gb/s）
- **前端串化**：全静态 CMOS 16:4 多路选择树及四相交错重定时，使用正交 ÷2 提供的 1 GHz 四相。
- **输出级**：28 个并联 N-over-N **源端串联端接（SST）** 切片（23 主抽头 Main + 5 后一拍均衡 Post-1 FFE），由片上 `1.8 V → 0.44 V` 子稳压器（`sst_vdrv_ldo_pdk`）供电，直接提供匹配 `100 Ω` 差分输出阻抗与 400 mVpp 摆幅，驱动 `C0–C5` PCB 信道。

### 2.3 RX CMOS/SST CMOS v2.2（1:16，4 Gb/s）
- **模拟前端**：片上 `100 Ω` 差分端接（至 BIAS `Vcm`）+ 4 档可调阻容退化 LVT CTLE。
- **时钟与采样**：2 GHz 64 码纯 CMOS 相位插值器（每码 `7.8125 ps = 0.03125 UI`，跨扇区连续回卷无毛刺）→ 8 相 1 GHz 正交分频 → 8 路四分之一速 **Double-Tail 动态 CMOS 采样器**（4 数据 + 4 边沿）→ 节距匹配的 8→32 静态 CMOS 解串器。
- **数字 CDR 与宿主出口**：`serdes_digital_top_v3` 内共享单个 `rx_word_map`，同时馈送二阶 Alexander BBPD CDR（125 MHz 域，跟踪 `±300 ppm` 频偏）与 16-bit 字对齐/异步 FIFO（250 MHz 域跨时钟出口）。

---

## 3. 目录所有权与工程约定

| 目录 | 职责 |
|---|---|
| `analog/pll/` | 2 GHz PLL v4（`vco/`、`cp/`、`loop_filter/`、`pfd/`、`divider/`、`coarse/`、`top/`） |
| `analog/tx/` | 发送端：主线 `sst/`（CMOS/SST SST v4.3）；历史 CML 保留在 `serializer/`、`output_driver/`、`clock_distribution/`、`input_register/` |
| `analog/rx/` | 接收端：主线 `cmos_rx/`（CMOS/SST CMOS v2.2）；历史 CML 保留在 `ctle/`、`pi/`、`sampler/`、`input/`、`top/` |
| `analog/ldo/` | HV18 安静供电 LDO（`v2_cur` 主线 + `bias_filter_r4` + 历史减容研究） |
| `analog/bias/` | 带隙参考、FC-OTA、缓冲与偏置分配（`BIAS v2` 主线 + v1 参考） |
| `analog/common/` | 跨模块底层原语（`cml_to_cmos/` `r5`、`devices/`、`monitor/`、CML 单元） |
| `analog/layout/` | 公共 SKY130A Magic PDK 版图绘图内核（`scripts/layout_core.py`） |
| `digital/` | 统一精简数字顶层 `pnr/rtl_v3/`、OpenROAD P&R 与 VCS SDF GLS 流程，及各子系统单元 RTL |
| `src/serdes_flow/` | 仿真编排、PVT/MC、眼图/抖动分析、SKY130 $g_m/I_D$ 与贝叶斯/Pareto 优化库 |
| `verification/` | PCB 信道 `.s4p` 模型（`C0–C5`）、片级版图规划与 DRC/LVS 独立审阅、PDN 稳定性与绘图 |

每个活跃模拟模块仅按需包含 `spice/`（权威网表）、`tb/<case>/`（独立测试台）与 `layout/`（PDK 生成器与签核摘要）；DUT 只放电路与参数，电源/激励/负载/测量统一在测试台。

> **历史 CML 参考框图**：早期全 CML 2:1 树与半速采样架构框图保留在 [clock_tx_blocks.png](../figures/system/clock_tx_blocks.png) 与 [rx_blocks.png](../figures/system/rx_blocks.png)，用于对比功耗、面积与架构演进（编码/8b10b/加扰未纳入当前 4 Gb/s 原始线速首版）。
