# CML→CMOS 时钟接收器

> **当前修订**：PLL r3 中的 `serdes_cml_to_cmos_pvt_candidate`，用于每条抽出支路的全速 2 GHz CMOS 和 250 MHz 反馈（[网表](../../analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice)）。
> **关键数字**：250 MHz 反馈转换 45/45；全速 2 GHz 转换 44/45。
> **主要缺口**：SS/1.65 V/−40 °C 全速转换失败（原生 VCO 下四相全部失效）。PLL 不依赖全速时钟，但 RX 的 pair 对齐和 RTL 桥依赖。

## 电路

```mermaid
flowchart LR
  IN[高共模 CML] --> SF[LVT 源跟随器] --> AMP[两路反向差分转单端]
  AMP --> INV[预驱动反相器] --> RAW[互补原始时钟]
  RAW --> SR[上升沿脉冲 → NAND SR 恢复] --> OUT[延时匹配 → CMOS 输出]
```

| 部分 | 参数 |
|---|---|
| 源跟随器 | LVT W = 20 µm；下拉 W = 2 µm、L = 0.5 µm，接全局 `vbias` |
| 差分转单端（两路，输入互换） | LVT 输入对 W = 6 µm；PMOS 镜负载 W = 8 µm；尾管 W = 8 µm（v0.1 为 6 µm） |
| 预驱动反相器 | NMOS W = 1.8 µm（v0.1 为 1 µm）、PMOS W = 3.6 µm |
| 输出 | 反相器 Wn/Wp = 4/12 µm，再经状态恢复级 |

恢复级有记忆：输入停钟时保持状态，不保证静态输入到输出的直流逻辑关系；没有复位或无毛刺门控。RX 数据读出使用另一个无记忆的静态版本 [cml_to_cmos_data.spice](../../analog/common/cml_to_cmos/spice/cml_to_cmos_data.spice)，见 [RX PI 与采样](rx_pi_sampler.md)。

## 已验证结果

### v0.1 接收器，1.8 V 单模块（2 GHz、400 mVpp、共模 1.632 V、每路 20 fF）

| 工况 | 占空比 | 上升 10–90% | 下降 90–10% | 功耗 |
|---|---:|---:|---:|---:|
| TT / 27 °C | 49.77% | 45.6 ps | 27.9 ps | 3.47 mW |
| SS / 27 °C | 50.11% | 62.8 ps | 33.2 ps | 3.36 mW |
| FF / 27 °C | 49.58% | 35.8 ps | 24.4 ps | 3.49 mW |
| SF / 27 °C | 49.02% | 58.9 ps | 28.0 ps | 3.63 mW |
| FS / 27 °C | 50.60% | 40.6 ps | 30.1 ps | 3.20 mW |

来源：[接收器记录](../history/cml_clock_receiver_results.md)。

### 修整与低压边界

SS/1.65 V/85 °C 下原接收器的增益节点仍在摆动，但预驱动 `bp` 最低约 0.744 V、后级只到约 0.722 V，无法翻转；加大尾管与预驱动 NMOS 后 `bp` 摆到约 0.095–1.517 V，时钟恢复。功耗代价约 3.494 → 3.732 mW（TT、2 GHz，+6.8%）。

在该修整版上做的 SS/1.65 V 温度扫描（特定激励：300 mVpp 经 buffer、共模 VDD − 0.15 V），冷端边界落在 (−13, −12] °C。原版在 1.70 V 时的边界在 (47, 48] °C。来源：[修整记录](../history/pll_pvt_refinement.md)。

### r3 中的 SS 冷角缺口

| 条件 | 结果 |
|---|---|
| 标准源 300/350/400/450 mVpp → buffer 输出约 460/501/530/549 mVpp | 只有 549 mVpp 时两路全速 CMOS 都工作 |
| 原生 VCO 码 5（VCO 约 416 mVpp、buffer 后约 537 mVpp） | CML 分频和反馈正常，四相全速 CMOS 全部失效 |
| 原生 VCO 码 6（频率较低） | 曾有正常 CMOS 输出 |

所以这是转换器的速度/幅度/共模问题，不是 VCO 停振或分频丢失。来源：[r3 记录](../history/pll_buffered_pvt.md)。

### 谁依赖全速输出

- PLL 反馈只用 ÷8 后的 250 MHz CMOS，不受影响。
- RX 的 [rx_cmos_pair_align.spice](../../analog/rx/sampler/spice/rx_cmos_pair_align.spice) 把恢复的 EDGE 时钟转成约 2 GHz CMOS 再对齐样本；实时 RTL 桥每 500 ps 读一次 pair。若以后改为 CML 整字保持、低速再转 CMOS，这个依赖可以去掉。见 [尺寸与优先级](../history/divider_size_and_clock_priority.md)。

### 全速 SS 冷角修复候选（2026-10-31）

bench：300 mVpp 源（共模 VDD − 0.15 V）经真实抽出 buffer 和 r3 prescaler 负载后进入转换器，与 r3 的 45 条件测试边界一致（[bench](../../analog/common/cml_to_cmos/tb/fullrate_pvt/run.py)）。

**根因。** SS/1.65 V/−40 °C 下，增益级输出 `ap` 最高只到约 1.09 V（TT 下约 1.67 V），预驱动输出 `bp` 只能降到约 0.95 V，后级不翻转。输入加到 550 mVpp 也只降到 0.67 V。问题出在差分转单端级 PMOS 镜像负载的上拉：冷端 PMOS 阈值高、镜像节点慢。这一级输出的直流中心又随 PVT 变化，而后级反相器的翻转点是固定的。

| 变体 | 结果 |
|---|---|
| 只加宽负载，或只降低预驱动翻转点 | SS 冷角仍失败 |
| 负载 W16 + 尾管 W12 + 预驱动 NMOS 3.6 µm | 修好 SS 冷角，但 **SS 热角失败**（上沿不够） |
| **"big"：输入对 W10、负载 W16、尾管 W16、预驱动 NMOS 3.6 µm** | **45/45**，占空比 0.477–0.511，转换器功耗 2.6–6.2 mW（TT 约 4.8 mW，比原候选多约 1 mW） |
| 交流耦合 + 自偏置反相器（[cml_to_cmos_acsb](../../analog/common/cml_to_cmos/spice/cml_to_cmos_acsb.spice)） | TT/FF 正常、功耗约 1 mW；SS 冷热都失败：1.65 V 慢工艺下反相器在翻转点几乎没有增益。未采用 |

幅度余量：源降到 200 mVpp 时，"big" 在 SS 冷、FS 热、SF 冷角仍通过，SS 热角（输入 277 mVpp）失败；SS 热角正常输入约 390 mVpp。

## 适用范围

- 边界温度是确定性仿真在特定激励下的局部结果，不是带噪声/失配的额定值。
- 1.95 V 冷角 CMOS 输出峰值约 2.022–2.026 V，器件端电压未核对。
- 偏置为理想参考；无提取寄生。

## 待解决

- 用原生 VCO 复验 "big" 的 SS 冷角，替换进 r3 前端后重跑分频/反馈 45 条件（[问题清单](../status/open_issues.md) I-04）；SS 热角幅度余量约 110 mV。
- 1.95 V 过冲与器件端电压（I-11）。
- 恢复级复位/无毛刺门控（随 I-01 的分频同步方案一起考虑）。
