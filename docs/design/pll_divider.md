# CML ÷8 prescaler（r3）

> **当前修订**：PLL r3 `pll_cml_prescaler8`——三级低过驱动 CML ÷2，÷2→÷4、÷4→÷8 之间各加一个 CML buffer（[网表](../../analog/pll/divider/spice/cml_prescaler8.spice)，[配置](../../config/pll_working_revision.toml)）。
> **关键数字**：真实偏置 + PDK 电阻，45 条件 × hh / ll：÷2 / ÷4 / ÷8 与 250 MHz 反馈全部正确，最低 258 / 342 / 377 mVpp（第一级保持管 W 40，后两级 W 80；原来全 W 80 时第一级最低 156 mVpp）。
> **主要缺口**：分频器没有确定性复位，TX 取用的多相抽头来自不同支路的独立 prescaler；FS/1.65 V/−40 °C 首级尾管处于饱和边界（VDS − VDSAT ≈ −5 mV）。

## 电路

```mermaid
flowchart LR
  IN[抽出 buffer 输出 2 GHz] --> D2[÷2] --> B1[CML buffer] --> D4[÷2] --> B2[CML buffer] --> D8[÷2]
  D2 --> T2[q2 抽头 1 GHz]
  D4 --> T4[q4 抽头 500 MHz]
  D8 --> T8[q8 抽头 250 MHz → 反馈接收器]
  BIAS[本地低过驱动偏置镜] -.-> D2 & D4 & D8
```

每个 ÷2 是主从两只静态 CML 锁存器，反相输出回授。锁存器为三层 NMOS 堆叠：数据/再生对、时钟转向对、尾管。时钟先经 LVT 源跟随器降共模，再驱动下层转向对；每级输出共模由本级负载重建（约 VDD − I·R/2），不会沿链累减。

| 部分 | 参数 |
|---|---|
| 锁存器 [cml_latch](../../analog/pll/divider/spice/cml_latch.spice) | 数据 W = 20 µm、保持 W = 40 µm（第一级）/ 80 µm（后两级）、时钟 W = 64 µm（均 LVT，4 指）；负载每端 600 Ω |
| 尾管 | 普通 NMOS，总宽 72 µm、24 指、L = 0.5 µm，接本地 `vbias_logic` |
| 时钟源跟随器 | LVT W = 80 µm、4 指；下拉 W = 4 µm、L = 0.5 µm，接全局 `vbias` |
| 本地偏置 [pll_cml_tail_bias](../../analog/pll/divider/spice/cml_div2.spice) | 复制全局参考约 1/6，经 PMOS 镜注入 W/L = 20/0.5 µm、nf = 4 的 NMOS 二极管；每条 prescaler 一份 |
| 级间 buffer | `serdes_cml_buffer`：输入 W = 24 µm、尾 W = 12 µm、负载 600 Ω，接全局 `vbias` |

外部端口和分频比与 v0.1 相同。四条支路（一条真实反馈、三条供电 dummy）结构完全相同。

### 为什么是这个结构

1. **低过驱动宽尾管（r2）。** SS/1.65 V/85 °C 下原 W12 尾管的 VDS 约 0.208 V，而 VDSAT 约 0.378 V，实际尾电流只有约 0.313 mA（名义 0.51 mA），÷4 起丢失。单独提高 Vbias 会同时提高 VDSAT，无法恢复。把尾管加宽 6 倍并把参考电流降到约 1/6，名义电流不变而 VDSAT 降到约 0.175 V，三级分频恢复。见 [SS 诊断](../history/cml_divider_ss_diagnosis.md)。
2. **加宽源跟随器（r2）。** FS/1.65 V/85 °C 下源跟随后的时钟共模只有约 0.804 V，首级尾管平均余量约 −0.4 mV，÷8 无摆幅；源跟随器 40 → 80 µm 后共模约 0.838 V、余量约 +25.6 mV。见 [r2 记录](../history/pll_lowov_pvt.md)。
3. **级间 buffer（r3）。** FS 热角真实 VCO 波形偏弱（buffer 后约 301 mVpp）时，r2 的 ÷4 基本无摆幅；中间加一个真实 CML buffer 后 ÷4 恢复到约 318 mVpp。buffer 恢复的是时钟幅度，不是堆叠余量——SS 测点中加 buffer 后后级尾管平均余量反而略降。见 [结构探索](../history/cml_latch_topology_experiments.md)、[偏置与 buffer](../history/serdes_bias_inventory.md)。

## 已验证结果

### 保持管和自激频率（2026-11-06）

**结论：保持管决定自激频率 f_SO，f_SO 决定 ÷2 能工作的输入频率范围。第一级输出 1 GHz，要 f_SO 不低于约 1 GHz，所以用 W 40；慢级要压住自激，保持 W 80。**

[div2_map/run.py](../../analog/pll/divider/tb/div2_map/run.py)：单个 ÷2，时钟直接加在门极，扫共模和摆幅，一个点十几秒。任何时钟接口都是图上一点，判断它不用跑全链。这张图预测全链探针的结果误差 ≤ 5 mVpp（读出 ÷2，W 80：76/74、148/143、265/267 mVpp；W 40：297/293）。

f_SO（GHz，时钟共模 1.05 V，无时钟输入）：

| 保持管 W | FS 1.65 V 85 °C hh | SS 1.65 V 85 °C hh | TT 1.8 V 27 °C | FF 1.95 V −40 °C ll |
|---:|---:|---:|---:|---:|
| 40 | 1.40 | 1.45 | 1.90 | 2.45 |
| 60 | 1.05 | 1.10 | 1.45 | 1.80 |
| 80 | 0.80 | 0.85 | 1.10 | 1.40 |
| 120 | 0.60 | 0.60 | 0.80 | 1.00 |

FS、SS 热角 W 40 的自激只有几十 mV 以下，频率读数要打折扣。W 80 在 TT 正好 1.1 GHz，到 FS 热 hh 掉到 0.8 GHz，所以只在 hh 下出问题：hh 电阻大、电流小（I·R 不变），节点 RC 变慢。

第一级输出（mVpp，FS 1.65 V 85 °C hh，RX 负载，时钟 0.85 V、215 mVpp，即现有跟随器的工作点）：W 120 不分频，W 80 74，W 60 251，W 40 293，W 20 267。数据管 W 10–30 影响很小。尾管不是主因：共模从 0.85 抬到 1.27 V，尾电流只多 8 %，0.85 V 时 VDS − VDSAT 还有 +65 mV。

慢级要的最小时钟摆幅（mVpp，门极正弦，共模 1.05 V，所测档位中分频正确的最低值；实际时钟是方波沿，正弦偏保守）：

| 保持管 W | 输入 1 GHz：FF 冷 ll / TT / FS 热 hh | 输入 500 MHz：FF 冷 ll / TT / FS 热 hh |
|---:|---:|---:|
| 40 | 150 / 215 / 215 | 215 / 300 / 300 |
| 80 | 100 / 150 / 150 | 150 / 215 / 215 |
| 120 | 100 / 100 / 100 | 100 / 150 / 215 |

后两级实际门极时钟最低 352 / 421 mVpp（[rcorner.py](../../analog/pll/divider/tb/pvt/rcorner.py)，45 × hh / ll），约为所需的 2 倍。

**W 80 的来历。** 2026-10-27 从 W 20 → 28 → 40 → 80 迭代而来，当时规划了 VCO 低到 400 MHz 的模式。W 40 在 400 MHz 正弦输入、TT 125 °C 下自激（÷2 输出 599 MHz，比输入还快），W 80 正确；2 GHz 下两者都正确。那时是理想 R，只验证了 TT 附近的离散点。现在 VCO 固定在 2 GHz 附近，第一级不再需要慢输入能力。

**同步计数器不受这个矛盾限制。** TX 的 `serdes_tx_sync_counter8` 三个触发器都吃 2 GHz 时钟，没有慢级，保持管 W 20。

![W20 单元在时钟共模与摆幅平面上的可行区](../figures/clocking/dividers/div2_w20_clock_feasible_region.png)

这组 W20、2 GHz、PLL 型负载的离散扫描同时标出输出摆幅与过零数：FF 冷 ll 在 150 mVpp 输入下虽有输出摆幅，翻转仍异常；215 mVpp 是该组扫描的可用参考点。它不替代 W40 的 RX ÷2 或完整同步计数器验证。[来源和范围](../history/clocking_progress_20261106.md)。

### 真实偏置 + PDK 电阻 45 条件（2026-11-06）

[rcorner.py](../../analog/pll/divider/tb/pvt/rcorner.py)：标准输入（300 mVpp，比 r5 VCO 的实际摆幅小），每 tap 5 fF。全 W 80 时 hh 下第一级最低 156 mVpp，全 W 40 时第三级自激余量不必要地变小，所以只改第一级。

| 45 条件最低（mVpp） | hh | ll |
|---|---:|---:|
| 第一级门极时钟 | 209 | 240 |
| 第二级门极时钟 | 359 | 352 |
| 第三级门极时钟 | 436 | 421 |
| ÷2 输出 | 269 | 258 |
| ÷4 输出 | 351 | 342 |
| ÷8 输出 | 399 | 377 |

分频和反馈频率全部正确。尾节点最低 0.089 / 0.074 V（FS 1.65 V −40 °C，I-10）。

### 标准输入 45 条件（r3，理想 R，全 W 80）

输入为差分 300 mVpp、共模 VDD − 0.15 V 的 2 GHz 正弦，经真实上游 buffer；每 tap 每端 5 fF，CMOS 输出每端 20 fF；每条件 64 ns，分析 32–64 ns。

| 项目 | 结果 |
|---|---|
| ÷2/÷4/÷8 稳态周期与幅度 | 45/45 |
| 250 MHz 反馈 CMOS | 45/45 |
| 全速 2 GHz CMOS（接收器） | 44/45，SS/1.65 V/−40 °C 失败，见 [时钟接收器](clock_receiver.md) |
| 最小 CML tap 差分摆幅 | 约 227 mVpp |
| 相对 r2 每条完整支路功耗增量 | 1.44–1.98 mW（不含外部参考） |

来源：[r3 记录](../history/pll_buffered_pvt.md)、[数据](../data/pll_buffered_pvt.json)。原生 VCO 回接见 [VCO](pll_vco.md)。

### 尺寸

| 版本（三级 ÷8） | MOS 实例 | 总栅面积 ΣWL | 电阻 |
|---|---:|---:|---:|
| v0.1 | 54 | 379.2 µm² | 12 |
| r2 | 58 | 666.9 µm² | 12 |
| r3 | 64 | 693.3 µm² | 16 |

相对 v0.1 增加的约 314 µm² 中，尾管加宽占 180、本地参考镜 71.7、源跟随器 36、级间 buffer 26.4 µm²。ΣWL 不含电阻、井、间距和布线，不是版图面积。来源：[尺寸评估](../history/divider_size_and_clock_priority.md)。

## 分频状态与相位

- **没有确定性复位。** 每个 ÷2 上电后有两种状态，各支路 prescaler 的状态彼此独立。TX 时钟分发从不同支路取抽头（250 MHz 取支路 0 的 ÷8，500 MHz 取支路 2 的 ÷4，1 GHz 取支路 3 的 ÷2），所以抽头之间的相对相位取决于启动状态。r3 的一次 TT 启动中 1 GHz 相对目标差了半个周期（约 2 UI）。见 [TX 时钟分发](tx_clock_distribution.md)。
- **多相间隔不等距。** 同极性核对时，÷2 四支路间隔约 0.50/0.75/0.50/2.25 UI，继承自抽出 buffer 的相位极性（b0 → b2 → b1 → b3），不是分频器延迟差。见 [串化时序溯源](../history/serializer_timing_root_cause.md)。

## 结构备选

在 TT 调参、5 个工况、2 GHz 下比较过的候选（细节见 [结构探索](../history/cml_latch_topology_experiments.md)）：

| 候选 | 观察 |
|---|---|
| 当前静态 CML（r2/r3） | 5/5 工况分频；任意数据 DFF 0/120 错误 |
| 独立时钟共模静态 CML | 单元 5/5，但 AC 耦合接口在级联中失效，需与 buffer 同时评估 |
| 两层去尾源 CML | 固定偏置 1/5；角上重调偏置后全部可分频——需要 replica 偏置 |
| folded MCML | 重调后可分频，但热角摆幅约 176–185 mVpp，功耗不低 |
| PMOS 电阻式负载 | 4/5，可调；但作数据锁存时 SS 冷/热角各有 33/32 个错误 |
| C²MOS / TSPC 动态 CMOS | 理想 CMOS 时钟下 5/5；接真实转换器后 SS 冷角失败 |

## 适用范围

- 标准输入是理想正弦经真实 buffer；原生 VCO 驱动只验证了 4 个选定工况。
- 负载电阻为理想名义值；全局参考为理想 0.85 mA，本地镜为真实 MOS。
- 功能筛查门槛 150 mVpp 是瞬态探索线，不是最终 CML 输入规格。
- 无噪声、失配、版图寄生；没有验证电源爬升或偏置使能瞬态。

## 待解决

- 确定性复位或多相同步（[问题清单](../status/open_issues.md) I-01）。
- FS/1.65 V/−40 °C 首级/第二级尾管平均余量约 −5/−4 mV（r2 时约 63% 采样点低于饱和判据）（I-10）。中等难度以上可考虑减少堆叠的结构。
- 接 r5 VCO 的原生前端和闭环还没跑（I-32）；上面是标准输入。
- Xschem 原理图未同步（I-22）；当前阅读图见 [cml_latch_review.pdf](../schematics/lowov_review/cml_latch_review.pdf)。
