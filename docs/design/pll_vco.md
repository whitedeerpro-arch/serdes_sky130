# VCO：四级差分 CML 环振

> **当前修订**：PLL r3 中的 `pll_vco_ring4_pvt_candidate`（[网表](../../analog/pll/vco/spice/vco_ring4_pvt_candidate.spice)，[配置](../../config/pll_working_revision.toml)）。
> **关键数字**：4 个选定工况的原生回接都能调到约 2 GHz（1.9906–2.0129 GHz，开环固定 Vctrl）；TT 码 5 局部 Kvco 约 495 MHz/V。
> **主要缺口**：45 条件粗细调映射未做；VCO 节点摆幅低于 400 mVpp 目标；相位噪声未测；运行中切码未验证。

## 电路

四个电阻负载 CML 反相延迟单元成环，偶数级环路中有一次差分交叉，保证直流负反馈。四路差分输出给出八个极性（顺序见 [架构](../overview/architecture.md#vco-八相顺序)）。粗调为每节点 3 bit 电容阵列，细调为累积型变容管；码增大 → 电容增大 → 频率降低，Kvco 为正。

| 部分 | 参数 |
|---|---|
| 延迟单元 [serdes_cml_delay](../../analog/common/cml_buffer/spice/cml_delay_resistive.spice) | 输入对 LVT W = 40 µm、8 指、L = 0.15 µm；尾管 W = 20 µm、4 指、L = 0.5 µm；负载每端 400 Ω（理想电阻） |
| 变容管 | 每节点 `sky130_fd_pr__cap_var_lvt` W/L = 18/0.5 µm，栅接振荡节点，阱接 Vctrl |
| 粗调阵列 [cap_bank_3b](../../analog/pll/vco/spice/cap_bank_3b.spice) | 7 个相同 MIM 单元 2.35 × 5 µm（约 25.9 fF），分组 1:2:4；底板接 NMOS 开关 W = 1 µm |
| 固定电容 | 每节点一颗 2.5 × 2.5 µm MIM（约 14.1 fF） |
| 偏置 | 外部理想 0.85 mA 注入 W/L = 20/0.5 µm、nf = 4 的 NMOS 二极管 |

与 v0.1 相比，r3 的 VCO 只改了电容：变容管 15 → 18 µm，粗调单元 2 × 5 → 2.35 × 5 µm，新增固定 MIM；电流和延迟单元不变。目的是让慢端工况（SF 低压热角）也能覆盖 2 GHz。

### 抽出与负载

每路差分输出接一个 `serdes_cml_buffer`，再接一个全速 CML→CMOS 接收器和一条 ÷8 prescaler。支路 0 是真实反馈，支路 1–3 是带偏置的供电 dummy，负载完全相同，保证八相负载对称。每根线另有 0.5 fF 残余布线电容。见 [clock_frontend_lowov.spice](../../analog/pll/top/spice/clock_frontend_lowov.spice)。

## 已验证结果

### r3 原生回接（固定理想 Vctrl，开环）

| 工况 | 码 / Vctrl | VCO 频率 | 三级分频 / 反馈 | 四相全速 CMOS |
|---|---|---:|---|---|
| TT / 1.8 V / 27 °C | 5 / 1.205 V | 2.0129 GHz | 正常 | 正常 |
| SS / 1.65 V / 85 °C | 6 / 1.320 V | 2.0121 GHz | 正常 | 正常 |
| FS / 1.65 V / 85 °C | 5 / 1.100 V | 1.9906 GHz | 正常 | 正常 |
| SS / 1.65 V / −40 °C | 5 / 1.112 V | 2.0019 GHz | 正常 | **失败** |

来源：[r3 记录](../history/pll_buffered_pvt.md)、[数据](../data/pll_buffered_pvt.json)。SS 冷角原用码 6 时在 1.32/1.55 V 只有约 1.936/1.970 GHz，改用码 5 后达到 2 GHz，没有再改尺寸。

### 调谐覆盖（r3 VCO 候选，5 个选定工况）

| 工况 | 码 | 已测频率区间 |
|---|---:|---:|
| TT / 1.80 V / 27 °C | 5 | 1.949–2.153 GHz |
| SF / 1.80 V / 27 °C | 7 | 1.905–2.020 GHz |
| SF / 1.65 V / 85 °C | 7 | 1.992–2.076 GHz |
| FS / 1.95 V / −40 °C | 4 | 1.850–2.045 GHz |
| SS / 1.65 V / 85 °C | 6 | 1.904–2.034 GHz |

TT 码 4/5 有约 88.7 MHz 的已测重叠；若两码都只用 1.1–1.55 V，会留下约 31.4 MHz 的间隙，所以细调范围不能过早缩窄。局部 Kvco（1.1–1.3 V 割线）：TT 码 5 约 495 MHz/V，SF 低压热角约 245 MHz/V。来源：[VCO/接收器修整](../history/pll_pvt_refinement.md)。

### 早期特性（v0.1 几何，TT）

| 项目 | 数值 |
|---|---:|
| 名义点（码 7、Vctrl 1.48 V、每端 20 fF 代理） | 2.0083 GHz、415 mVpp |
| 核心功耗（不含参考支路） | 6.06 mW |
| 八相间隔 | 约 62.24 ps |
| 变容管小信号 Q（1.0 / 1.4 / 1.8 V） | 2.76 / 2.91 / 23.3 |

变容管在常用偏置下 Q 很低，对摆幅、功耗和相噪都有影响，P4 需要重新评估。来源：[首轮结果](../history/vco_ring4_first_results.md)。

### 节点摆幅

r2 原生回接时 VCO 节点差分摆幅：TT 约 360 mVpp、SS 1.65 V/85 °C 约 310 mVpp、FS 1.65 V/85 °C 码 6 约 316 mVpp；r3 SS 冷角约 416 mVpp。抽出 buffer 后通常更大（例如 TT 约 504 mVpp）。来源：[r2 记录](../history/pll_lowov_pvt.md)、[r3 记录](../history/pll_buffered_pvt.md)。

## 粗细调交接策略

计划的首次捕获：Vctrl 固定在可用范围中部，按频差逐次 ±1 改码（太快 +1、太慢 −1），进入目标窗口后交给 PLL 细调；锁定后冻结粗码。背景再校准需要 Vctrl 迟滞门限、越界确认次数、切码后最短保持时间、端点"范围不足"状态。当前 1:2:4 二进制分组在 011 → 100 时切换三组开关，要想每次只切一个单元需改为温度计译码。控制器尚未实现。详见 [粗调校准](../history/vco_coarse_calibration.md)。

## 适用范围

- 结果是固定理想 Vctrl 的开环工作点，频差不是 PLL 锁定误差。
- 负载电阻为理想名义值，偏置参考为理想电流源；PVT 只覆盖 MOS 角。
- 无相位噪声、失配、版图寄生；八相间隔来自匹配原理图。
- 启动使用已建立的直流偏置和有限扰动，不代表上电启动。

## 待解决

- 45 条件 × 全码的调谐映射与相邻码重叠（[问题清单](../status/open_issues.md) I-09）。
- VCO 节点摆幅（TT 约 360、SS 85 °C 约 310 mVpp）是否足够，由 P4 相噪预算判定（400 mVpp 是上界，不是下限；I-17 已关闭）。
- 相位噪声方法与跨工况相噪（I-05）。
- 粗调控制器、温度计译码、无扰切码（I-18）。
- 用 PDK 电阻替换理想负载后的频率/摆幅（I-02）。
