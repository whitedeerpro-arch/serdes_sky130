# TX 输出级（r2）

> **当前修订**：TX r2 `serdes_tx_cml_line_driver_lowvt_enable`（[网表](../../analog/tx/output_driver/spice/cml_line_driver_lowvt_enable.spice)，[配置](../../config/tx_working_revision.toml)）。相对 v0.1 只改了尾偏置使能传输门。
> **关键数字**：45 条件从禁用初态启动全部正常；使能后最晚 2.413 ns 尾偏置进入 1% 误差带；启用线电流 7.51–8.02 mA，关闭残流 ≤ 1.15 nA。
> **主要缺口**：焊盘/封装/ESD 为代理参数；无 FFE；电源与回流理想。

## 电路

```mermaid
flowchart LR
 S[串化器输出] --> I[隔离 buffer] --> P[预驱动] --> D[输出差分对 / 源端 2 × 50 Ω]
 D --> PAD[焊盘 / 封装] --> AC[AC 耦合] --> CH[100 Ω 信道] --> T[远端 50 Ω/端，0.9 V]
```

| 部分 | 参数 |
|---|---|
| 隔离 buffer | W = 12 µm、尾 12 µm、600 Ω |
| 预驱动 | W = 48 µm、尾 48 µm、150 Ω；独立电源 `vdd_pre` |
| 输出对 | LVT W = 256 µm、16 指 |
| 尾管 | W = 172 µm、L = 0.5 µm、16 指（约 8 mA） |
| 源端 | 两只 50 Ω 上拉到 `vdd_out` |
| 使能门（r2） | N-LVT W2/L0.15 + P-LVT W32/L0.35（4 指，井接 VDD）；关断时下拉 W1 |

双端端接时每端交流负载约 25 Ω，Vdiff,pp ≈ 2 × I_tail × 25 Ω，400 mVpp 约需 8 mA。`tx_en` 低时关闭线尾电流（预驱动不掉电），给 AC 耦合链路提供对称的直流起始状态。

**为什么改使能门。** v0.1 的传输门在 SS/1.65 V/−40 °C 下给尾管栅极充电过慢：30 ns 约 0.817 V、90 ns 约 0.922 V（目标约 1.060 V），96 ns 内未进入 1% 误差带，远端最小裕量只有 31.78 mV。理想钳位定位后恢复到 151 mV。r2 改用低阈值 N/P 传输门（比较 Wp = 16/32/64 µm，选 32 µm），不强制钳位。另有两个未采用的候选：[独立井偏置开关](../../analog/tx/output_driver/spice/cml_line_driver_biaswell_candidate.spice)、[源端 footer](../../analog/tx/output_driver/spice/cml_line_driver_footer_candidate.spice)。来源：[TX PVT](../history/tx_pvt.md)。

## 已验证结果

### r2 独立输出级与 DC（45 条件）

| 项目 | 结果 |
|---|---|
| 从禁用直流态启动，4 ns 使能，256 bit | 45/45 功能 |
| 尾偏置进入 1% 误差带（最晚） | 6.413 ns（使能后 2.413 ns）；SS 冷角约 2.107 ns |
| 启用直流线电流 | 7.51–8.02 mA |
| 关闭残流 | ≤ 1.15 nA（预驱动仍耗电） |

来源：[TX r2 记录](../history/tx_optimization.md)、[数据](../data/tx_optimization.json)。

### 名义特性（v0.1 输出核心，TT，理想 400 mVpp 输入）

| 夹具 | 远端差分峰峰值 | 最小位中心裕量 | 边沿散布 | 错误 |
|---|---:|---:|---:|---:|
| 匹配信道 | 399.3 mV | 194.9 mV | 0.0053 UI | 0/256 |
| RC 损耗示例 | 351.0 mV | 168.7 mV | 0.0083 UI | 0/256 |

稳态功耗：预驱动约 4.82 mW + 线输出约 14.10 mW ≈ 18.92 mW，独立偏置参考另 1.53 mW。输入每端有效电容约 17.49 fF（2 GHz，平衡 1.68 V 工作点）。来源：[输出级与链路路线](../history/tx_output_stage_and_link_plan.md)。

### 接 PCB

v0.1 串化器 + 输出级接 C2 6 dB 时，远端采样眼高比近无损下降约 59%，总峰峰值只降约 7%——总摆幅不能代替采样裕量。r2 在 4 个选定工况接 C2 全部零错误，最小远端裕量 54.81 mV（FS/1.65 V/85 °C），见 [TX 串化器](tx_serializer.md)、[信道模型](channel_model.md)。

## 适用范围

- 焊盘 200 fF、封装 0.5 nH、AC 每端 10 nF、远端偏置 0.9 V 都是探索参数，不是提取或真实 ESD 单元。
- 电源理想；未测电源阻抗、回流电感、PSRR 和偏置反向扰动。
- 400 mVpp 是目标幅度，PVT 幅度容差尚未定义。

## 待解决

- 焊盘/ESD/封装模型，供电与回流（[问题清单](../status/open_issues.md) I-29）。
- FFE（主抽头 + 一后游抽头的预留方向）在确定信道和 RX 眼图需求后再定。
- 链路级远端/CTLE 后眼图门槛（I-20）。
