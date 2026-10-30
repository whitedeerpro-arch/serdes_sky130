# 信道模型

> **当前修订**：RLC16 近无损代理（TX PVT 默认负载）+ 合成 100 Ω 差分 PCB 族 C0–C5（[配置](../../config/channel_family.toml)，[模型目录](../../verification/models/channel/)）。
> **关键数字**：C2（2 GHz 处 6 dB）为 RX 设计起点，C3（10 dB）为挑战场景。
> **主要缺口**：合成模型，不是具体叠层/连接器提取；无串扰；链路级眼图门槛未定义。

## RLC16 代理

[diff_rlc16.spice](../../verification/models/channel/diff_rlc16.spice)：每端 R 总 0.05 Ω、L 总 12.5 nH、C 总 5 pF，分 16 段 π 网络，名义 50 Ω、延迟约 250 ps。用作 TX PVT 的近无损负载。早期理想 T 线在激励前时间步失败，已改用此被动代理。

## 合成 PCB 族

| 场景 | 用途 | 2 GHz 插入损耗 | 2 GHz 回波损耗 | 主线长度 |
|---|---|---:|---:|---:|
| C0_debug | 接线、极性、采样基线 | 0.20 dB | 40.83 dB | 1 cm |
| C1_loss3 | 温和损耗 | 3.00 dB | 44.03 dB | 15 cm |
| C2_loss6 | RX 设计起点 | 6.00 dB | 41.20 dB | 30 cm |
| C3_loss10 | 均衡与驱动挑战 | 10.00 dB | 40.91 dB | 50 cm |
| C4_stub | C2 中点加对称开路支路 | 11.99 dB | 10.05 dB | 30 cm 主线 |
| C5_skew | C2 两线 0.1 UI 偏斜 | 6.11 dB | 41.23 dB | 平均 30 cm |

每根线用分布式 Z(s)、Y(s)：三个串联 Rk‖Lk 近似导体损耗，三个并联串联 RC 支路近似介质弛豫。导出 S4P 与等效 SPICE（`pcb_family/*.s4p`、`*.spice`），并做过无源 AC 检查。长度只对本次选择的合成介质成立。

有限长度无均衡眼开口估计（±32 UI、接收端参考 400 mVpp，`0.4 × (h0 − Σ|hk|)`）：C1 约 288 mV、C2 约 174 mV、C3 约 41 mV、C4 约 70 mV、C5 约 168 mV。不含窗外拖尾、噪声、TX/封装/AC 耦合、孔径和时钟误差。来源：[PCB 信道族](../history/pcb_channel_family.md)、[数据](../data/pcb_channel_family_results.json)。

## 真实 TX 接 PCB（v0.1 TX，TT）

| 信道 | 远端总峰峰值 | 采样眼高 | 最小裕量 | 散布 | 错误 |
|---|---:|---:|---:|---:|---:|
| C0 | 392.4 mV | 377.0 mV | 187.9 mV | 0.069 UI | 0/256 |
| C2 | 366.3 mV | 155.1 mV | 76.6 mV | 0.212 UI | 0/256 |
| C3 | 348.4 mV | 54.0 mV | 25.8 mV | 0.488 UI | 0/256 |

串化器节点散布在三种信道下都约 0.042 UI，远端展宽主要来自信道 ISI，不要求为此重调 PLL。来源：[TX 接 PCB](../history/tx_pcb_channel_integration.md)。CTLE 之后的结果见 [RX 前端](rx_frontend.md)。

## 适用范围

- 不是具体 PCB、连接器或接口标准的模型；没有互耦串扰。
- C4 的支路（单程 0.4 UI、约 20.9 mm、入口 10 Ω）模拟较长分支，不是典型过孔残桩。
- 最终应由实际板线 S 参数或提取模型替换。

## 待解决

- 链路级（RX 输入或 CTLE 后）眼图门槛（[问题清单](../status/open_issues.md) I-20）。
- C3/C4/C5 下的 RX 均衡覆盖（I-14）。
