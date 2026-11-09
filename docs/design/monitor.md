# 监测工具包

> **状态**（2026-11-09）：通用慢速监测积木，模拟部分在 [analog/common/monitor](../../analog/common/monitor/README.md)，数字部分在 [digital/common](../../digital/common/README.md)。与具体模块解耦：只接电流、电压、时钟和参数，阈值、档数、窗口长度都是参数；使用方自己例化、给参数、写控制逻辑。第一个使用方是 PLL 粗码控制（I-18）。
> **已验证**：数字四件（频率计、同步器、持续性滤波、逐次逼近）Icarus 测试与 Verilator lint 通过。比较器、门限梯、窗口检测、温度感测的 PVT 与失配表征见下文各节。

## 组成

| 积木 | 层 | 作用 | 典型用途 |
|---|---|---|---|
| `serdes_cmp` | 模拟 | 连续时间比较器，两级 + CMOS 输出，偏置为一指带隙电流拷贝（2.5 µA） | 窗口检测、温度判档、任何慢量对门限 |
| `serdes_vref_gnd` / `serdes_vref_vdd` | 模拟 | I·R 门限梯，16 档抽头；对地或对电源 | 绝对门限（比值 vbg·R/r_ref，电阻角无关）；随 VDD 的门限 |
| `serdes_window_cmp` | 模拟 | 两个比较器组成窗口 | Vctrl 越界 |
| `serdes_tsense_vbe` | 模拟 | VBE + I·rs，约 −1.8 mV/K | 温度估计（配门限梯 + 比较器 + `mon_sar`） |
| `mon_freq_meter` | 数字 | 参考窗口内数被测时钟沿，±1；被测钟可停 | 已实现、留作通用件；PLL 不用：它和 PFD 用同一参考、同一分频输出，功能重叠，且要靠分频器正常工作才能测，与 PLL 自身互为前提 |
| `mon_sar` | 数字 | 逐次逼近门限码 | 温度码、任一慢电压的粗 ADC |
| `mon_persist` | 数字 | N 次连续一致才改变 | 比较器去抖、越界确认 |
| `mon_sync` | 数字 | 同步器 | 异步比较器输出进时钟域 |

组合方式（使用方负责）：

- **窗口检测** = `serdes_window_cmp` + 两条门限梯 + `mon_sync` + `mon_persist`。
- **温度估计** = `serdes_tsense_vbe` + `serdes_vref_gnd`（码由 `mon_sar` 驱动）+ `serdes_cmp`，输出 4 位温度码；码到温度的对应来自表征。
- **频率判断** = `mon_freq_meter`，阈值在使用方（PLL 粗码不用：三态 PFD 在码内本身就有频率牵引，跨码的判断由窗口检测看 Vctrl 是否被推到门限外完成）。

## 接口约定

- 模拟积木吃电流不吃栅压：偏置来自 [bias_dist](../../analog/common/bias/spice/bias_dist.spice) 的 `serdes_bias_pcopy`（一指 = vbg / r_ref / 4 ≈ 2.5 µA）。不改偏置模块内部（温度感测不从带隙核心环取 PTAT，避免给其环路加负载）。
- 比较器输出异步，进数字域先过 `mon_sync`；门控/ready 类信号还要过 `mon_persist`。
- 门限梯的码在本轮网表里是静态参数（行为译码）；数字驱动的动态码在混合仿真时接。
- 都是慢速件：比较器在 1 mV/µs 斜坡下的滞后约 2 mV，判决时间按 µs 计。

## 表征

### 比较器 `serdes_cmp`（45 条件，真实带隙偏置）

**输入 0.6 V 到 VDD − 0.40 V 内系统失调 −1.0…+0.3 mV；静态电流 2.2–2.7 µA（输出高时再加约 2.5 µA）。** 共模再往上，输入对的漏端（≈ VDD − |Vgs| of LVT 镜像）压近栅极，进线性区：

| VDD − Vcm | 系统失调（mV） | 最差 |
|---|---|---|
| ≥ 0.40 V | −1.00 … +0.31 | FS 85 °C（低共模端） |
| 0.35 V | −2.23 … +0.19 | SF 1.95 V −40 °C |
| 0.30 V | −8.31 … +0.20 | SF 1.8 V −40 °C |
| 0.25 V | −23.6 … +0.31 | SF 1.95 V −40 °C |

测法：inn = Vcm，inp = Vcm + ±30 mV 三角波（每沿 60 µs，1 mV/µs），上升、下降两次翻转的平均为静态失调，半差为滞后（延迟 × 斜率）。滞后 0.1–3.3 mV，即微小过驱下判决约数 µs。DC 扫描穿过约 10⁶ 的增益时 ngspice 卡在 gmin 步进（TT 1.8 V −40 °C 一点 4 min 无进展），所以不用 DC 扫。测试台 [cmp_trip](../../analog/common/monitor/tb/cmp_trip/run.py)，结果 `results/analog/common/monitor/cmp_trip/20261109T050358Z`（12 个共模 × 45 条件，跳过 Vcm > VDD − 0.15 V）。

（进行中：局部失配；门限梯与窗口检测 45 条件 × 电阻角；温度感测各码翻转温度。）

## 适用范围

- 原理图级、无版图寄生；PNP 模型没有失配项，温度感测的随机部分只含 MOS 与电阻。
- 门限码译码为行为模型；码切换瞬态未表征。
