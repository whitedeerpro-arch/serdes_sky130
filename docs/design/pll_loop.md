# PLL 环路：PFD、CP、LF、预充与启动监督

> **当前修订**：v0.1 电路（PFD、50 µA CP、6.5 kΩ/40 pF/2 pF LF、双节点预充、启动监督 RTL），在 r3 工况下复测。物理 LF 候选尚未采用。
> **关键数字**：PFD→CP 45/45 工况电荷方向正确，有效电荷增益 53.3–59.8 µA；4 个选定工况 × 3 种初值的分层闭环均锁定；线性估计 UGB 3.0–4.4 MHz、相位裕度 63–65°。
> **主要缺口**：r3 原生 PLL 只接回 48 ns，没有持续锁定与从零捕获；LF 的 RC 极限角没有接入闭环；SS 低压高 Vctrl 处 CP 上拉电流不足。
> **待改（PLL 收口，I-32）**：VCO r5 候选和抖动预算要求环路改为 k = 4，LF 电容分接 VDD 和地。下面的电路和数字还是 50 µA、40 pF、2 pF、全接地。

## 电路

| 单元 | 实现 | 关键参数 |
|---|---|---|
| PFD [pfd_cmos.spice](../../analog/pll/pfd/spice/pfd_cmos.spice) | 静态 CMOS 上升沿三态 PFD：两个 D=1 的 DFF，主从锁存都异步清零；UP/DN 同时置位后经 NAND 与两级反相器延迟产生公共清零 | 复位延迟节点各 5 fF（理想）；零相差附近保留公共短脉冲 |
| CP [charge_pump.spice](../../analog/pll/cp/spice/charge_pump.spice) | 长沟道电流镜 + 输出串联开关 | N 镜 W/L = 5/1 µm、P 镜 W/L = 20/1 µm（4 指）；开关 N/P = 2/4 µm；UP 驱动 NFET 0.5/0.88、PFET 2/0.15 µm（TT/1.3 V 附近的名义补偿）；外部理想 N/P 参考各 50 µA |
| 可禁用 CP [charge_pump_enabled.spice](../../analog/pll/cp/spice/charge_pump_enabled.spice) | 实际 CMOS AND 门控 UP/DN | 用于启动序列 |
| LF [passive_rc_precharge.spice](../../analog/pll/loop_filter/spice/passive_rc_precharge.spice) | 二阶无源：Cf = 2 pF 并 (Rz = 6.5 kΩ 串 Ci = 40 pF)；ctrl 与积分节点 z 各一个 CMOS 传输门预充 | 预充门 ctrl 4/8 µm、z 16/32 µm；R/C 为理想元件 |
| 物理 LF 候选 [passive_rc_pdk_candidate.spice](../../analog/pll/loop_filter/spice/passive_rc_pdk_candidate.spice) | `res_high_po_0p69`（W 0.69、L 12.44 µm）；42 个约 1 pF 的 `cap_mim_m3_1`（边长 22.1965 µm），40 个作 Ci、2 个作 Cf | 板面积约 0.0207 mm²（不含间距布线） |
| 启动监督 [pll_startup_supervisor.sv](../../digital/pll/rtl/pll_startup_supervisor.sv) | 参考时钟域状态机 | 预充 128 周期 → 断开 2 周期 → PFD 运行 2 周期 → 开 CP → ACQUIRE/TRACK/FAULT |

UP 高有效、注入电荷；VCO Kvco 为正，反馈偏慢时 Vctrl 上升，方向一致。

### 启动序列

```mermaid
flowchart LR
 I[IDLE] --> W[等待 bias/pre_ref 有效] --> P[双节点预充 128 周期]
 P --> G[关预充，死区 2 周期] --> F[PFD 运行，CP 仍关 2 周期] --> A[CP 开启：ACQUIRE]
 A -->|连续好窗| T[TRACK / locked]
 T -->|连续坏窗，保留 LF 状态| A
 A -->|超时或范围故障| X[FAULT：CP 关闭]
```

250 MHz 下 128 周期 = 512 ns。监督器的 `quality_valid/frequency_good/phase_good` 是外部接口，频率/细相位测量前端尚未实现。

## 已验证结果

### CP 与 PFD→CP（r3 工况，45 条件）

| 项目 | 结果 |
|---|---|
| CP DC 输出扫描 | 45 条件完成 |
| 真实 PFD→CP，−200/0/+200 ps，250 MHz、Vout = 1.2 V | 45/45 净电荷方向正确且单调 |
| 有效电荷增益（两端割线） | 53.31–59.84 µA |
| 线性插值零电荷相位 | −79.4 到 +93.1 ps |
| SS/1.65 V/85 °C、Vctrl = 1.4 V 的 UP/DN | 40.8 / 49.3 µA |

三个相位点不足以证明无死区。零相差残余电荷在闭环中表现为静态相位偏移。来源：[环路 PVT](../history/pll_loop_pvt.md)、[CP 边界](../history/pll_pfd_cp_lf_next.md)。

TT/27 °C 名义点（v0.1）：Vout = 1.3 V 时 UP/DN = 48.5/49.9 µA；两者都在 50 µA ± 5% 内的输出区间约 0.36–1.42 V。来源：[CP/LF 原型](../history/pfd_cp_lf_results.md)。

### 分层闭环（r3 选定工况）

真实 MOS PFD/CP + 理想 LF 或 PDK LF，接同工况实测的三点分段线性 VCO→÷8 模型。两颗 LF 电容预置到目标 ±40 mV。下表是最终持续合格区间的起点（还需再观察 0.32 µs 确认）：

| 工况 | 码 / 目标 Vctrl | 理想 LF 低起点 | 理想 LF 高起点 | PDK LF 低起点 |
|---|---|---:|---:|---:|
| TT / 1.8 V / 27 °C | 5 / 1.1792 V | 0.386 µs | 0.802 µs | 0.354 µs |
| SS / 1.65 V / −40 °C | 5 / 1.1093 V | 0.514 µs | 0.802 µs | 0.514 µs |
| SS / 1.65 V / 85 °C | 6 / 1.2912 V | 0.706 µs | 0.962 µs | 0.674 µs |
| FS / 1.65 V / 85 °C | 5 / 1.1132 V | 0.450 µs | 0.802 µs | 0.450 µs |

SS 热角高起点在原 1.2 µs 记录中未通过，延长到 2 µs 后通过；电路和阈值未改。来源：[环路 PVT](../history/pll_loop_pvt.md)、[数据](../data/pll_loop_pvt.json)。

### 环路线性模型

| 模型 | UGB | 相位裕度 | 闭环 −3 dB | 峰化 |
|---|---:|---:|---:|---:|
| v0.1 TT（Kvco 464.55 MHz/V，50 µA） | 2.856 MHz | 65.4° | 4.228 MHz | 1.33 dB |
| r3 四工况（同角 Kvco、1.2 V 处 CP 电荷割线） | 3.0–4.4 MHz | 63–65° | — | — |

三阶 Type-II：Z(s) = (1 + sRCi) / [s(Cp + sRCiCf)]，Cp = Ci + Cf。模型不含反馈链延迟、采样 PFD、CP 有限输出电阻和 VCO 控制端负载。来源：[跟踪研判](../history/pll_tracking_assessment.md)。

### 按抖动预算选的环路（r5 候选 VCO，未实现）

k 是相对 v0.1 的缩放：Icp 50 µA × k，Ci 40 pF / k，Cf 2 pF / k，Rz 6.5 kΩ 不变。七工况的线性结果（标称环路值，不含 Rz 随电阻角的变化）：

| k | Icp | Ci / Cf | UGB | PM | PLL rms（最差） | CDR 后 14.07σ（最差） |
|---:|---:|---|---:|---:|---:|---:|
| 1 | 50 µA | 40 / 2 pF | 4.3–5.7 MHz | 56–60° | 5.69 ps | 0.563 UI |
| 2 | 100 µA | 20 / 1 pF | 8.5–11.4 MHz | 52–57° | 3.78 ps | 0.425 UI |
| **4** | **200 µA** | **10 / 0.5 pF** | **17–23 MHz** | **44–51°** | **2.75 ps** | **0.323 UI** |
| 6 | 300 µA | 6.7 / 0.33 pF | 26–34 MHz | 36–45° | 2.43 ps | 0.284 UI |
| 8 | 400 µA | 5 / 0.25 pF | 34–45 MHz | 27–39° | 2.43 ps | 0.270 UI |

- k = 4 是当前噪声/面积候选：k 再大抖动改善很少（底噪和 CP 开始抬头），PM 掉得快；k = 1 不满足 0.50 UI 门槛（[规格](../overview/spec.md#抖动与相位噪声预算)），但 k = 2 的 0.425 UI 已满足该模型门槛。实际 CP/LF 收口前比较 k = 2/3/4 的稳定性、捕获、杂散与面积；k = 4 的 Ci 10 pF 约是原来面积的 1/4。七工况的延迟/RC 敏感性复算见[设计耦合评估](../history/design_coupling_review_20261106.md)；模型已有 2 ns PFD 延迟。
- Kvco 比 r3 大 2–4 倍，PM 最差只有 44°，而且 R hh 下 Rz 更大。收口时 Rz、Cf 按角重定，不照搬缩放值。
- 参考杂散手算（k = 4、Kvco 924 MHz/V、UP/DN 失配 5 %）：Cf 上约 8.9 mV 的窄脉冲，基波约 0.9 mV，相位偏移约 0.0033 rad，折合约 0.002 UI 峰峰。B2 关断漏电 186 nA 的影响更小。都没有仿真。
- 电容分接：Ci、Cf 都按约 0.7 : 0.3 分接 VDD 和地，见 [VCO 电源灵敏度](pll_vco.md#电源灵敏度r5-候选)。

### 预充

| 观察量 | 原单点预充 | 双节点预充 |
|---|---:|---:|
| 两状态建立到 1.40 V ± 1 mV（500 Ω 参考源） | 2868 ns | 204.6 ns |
| 参考源峰值电流 | 0.521 mA | 2.619 mA |

上表是普通 CMOS 门和 500 Ω 理想参考源（TT），释放 1 ns 后 ctrl 扰动约 +1.04 mV。来源：[启动优化](../history/pll_startup_optimization.md)。

片内缓冲 [B2](bias.md#lf-预充缓冲-b2)：尾电流 300 µA，到 10 mV ≤ 360 ns，45 条件 × 电阻角。预充门因此改为普通 NMOS + LVT PMOS（原门在 SS / SF 1.65 V −40 °C 有死区），释放扰动变为 1 ns 后 +1.7…+2.3 mV（1.1 V 目标）；关断漏电最差 186 nA。闭环未复验。

### 原生接回

- **v0.1，TT。** 预充 LF 并对齐参考相位后，原生 PLL 满足持续判据：最后 512 UI 频差 +1.6 ppm，展开相差跨度 0.0008 UI。这是近锁初始化，不是上电捕获。来源：[实际时钟分发](../history/physical_clock_distribution_results.md)。
- **r3，TT。** 预充开关 40 ns 断开、48 ns 释放 PFD，观察到 96 ns；反馈相差从约 1.206 ns 降到约 168 ps。48 ns 不满足 320 ns 保持判据。

### 物理 LF 角

| 条件 | R | Ci | Cf |
|---|---:|---:|---:|
| tt / 27 °C | 6.508 kΩ | 40.00 pF | 2.000 pF |
| ll / 27 °C | 5.508 kΩ | 35.21 pF | 1.761 pF |
| hh / 27 °C | 7.508 kΩ | 44.93 pF | 2.246 pF |
| tt / −40 °C | 6.332 kΩ | 40.00 pF | 2.000 pF |
| tt / 85 °C | 6.714 kΩ | 40.00 pF | 2.000 pF |

MIM 模型的温度系数为 0。来源：[首轮 PVT](../history/pll_pvt_first_results.md)。

## 适用范围

- 分层闭环用实测 VCO 曲线模型，不含 VCO 噪声、控制端负载、分频状态和传播延迟。
- LF 电容预偏置在目标附近；不是从零充电或全频段捕获。
- 偏置参考为理想 50 µA/0.85 mA；PDK LF 用典型无源段。
- 锁定是无噪声工程判据，不是抖动签核。

## 待解决

- r3 原生持续锁定与从零捕获（[问题清单](../status/open_issues.md) I-08）。
- CP 高 Vctrl 处 UP/DN 失配与输出窗口（I-12）。
- LF RC 极限角接入闭环；决定是否采用物理 LF（I-13）。
- 启动测量前端、片内预充参考、看门狗、自动粗搜（I-21）。
- 按上面的预算改环路值、LF 分接，闭环重验证（I-32）；核实带内底噪和 CP 占空比（I-05）。
