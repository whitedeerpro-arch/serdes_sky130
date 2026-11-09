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

### 门限梯与窗口检测（PLL 实例，135 条件）

PLL 的 [pll_vctrl_window](../../analog/pll/coarse/spice/vctrl_window.spice)：对地梯 0.80–1.10 V（20 mV 一档，运行码 5 = 0.900 V），对电源梯 VDD − 0.32…0.77 V（30 mV 一档，运行码 3 = VDD − 0.410 V），各 2 指拷贝（约 5 µA）。45 条件 × 电阻 tt/ll/hh 全部功能正确（门限内两输出都低，低于 vlo 50 mV 时 lo = 1，高于 vhi 50 mV 时 hi = 1）。

| 门限 | 对设计值的系统误差 | 主要来源 |
|---|---|---|
| vlo（0.900 V） | −14.4 … +3.2 mV | 拷贝电流随 VDD（1.65 V 最低）；电阻角只差约 2 mV |
| vhi（VDD − 0.410 V） | −9.8 … +0.4 mV | NMOS 灌电流镜两管 Vds 不同（1.95 V 偏大） |

**局部失配比系统误差大：vlo σ 23–31 mV、VDD − vhi σ 13–16 mV（5 个压力点各 105 样本，k·σ 分别 83–117 / 47–56 mV）。** 门限是 I·R：MC 里带隙未修调（vbg σ 2.2 %），2 指 LVT 拷贝匹配差，两项按全额进入（相对误差约 2.8 % / 3.4 %）。修调去掉带隙项后估计仍有约 2 %（拷贝）。对 PLL 的影响见[上电选码](pll_vco.md#门限误差的影响)：按芯片随机抽取时影响很小，约束来自上门限尾部越过 CP 上沿。测试台 [window_mc](../../analog/pll/coarse/tb/window_mc/run.py)，结果 `results/analog/pll/coarse/window_mc/20261109T055255Z`：40 样本/块在第 21 个样本撞上 3 GB 上限（约 140 MB/样本），按样本回收（`--analyse`），默认块改为 8。

对地梯原来顶到 1.30 V，1.65 V 时 PMOS 拷贝只剩 0.35 V，vlo 偏 −24 mV；顶端降到 1.10 V 后为上表。检测器自身电流（上门限串 + 两比较器）8.6–12 µA，另加 6 指拷贝 15 µA。工作点测法（z = 1.1 V 及门限外 ±50 mV），比较器自身的系统失调见上节（< 1 mV）。测试台 [window_dc](../../analog/pll/coarse/tb/window_dc/run.py)，结果 `results/analog/pll/coarse/window_dc/20261109T052834Z`。

### 温度感测 `serdes_tsense_vbe`

VBE + I·rs（rs 38 kΩ，10 µA）对同类 10 µA 拷贝的 I·R 梯（r0 95 kΩ，rstep 1.867 kΩ）。斜率 −1.66…−1.72 mV/K，一码约 10.6 K。45 组（MOS × 电阻 × VDD）上每码翻转温度的系统散布约 13 K（±6.5 K）：MOS 角 ±2.8 K（PNP 的 VBE 角）、VDD ±2.3 K（拷贝余量）、电阻角 ±1.4 K。码 15 的中位翻转温度是 −35 °C，量程偏热，需下移（r0 ≈ 100.6 kΩ、rstep ≈ 1.57 kΩ 覆盖约 −45…95 °C）。测试台 [tsense_dc](../../analog/common/monitor/tb/tsense_dc/run.py)，结果 `results/analog/common/monitor/tsense_dc/20261109T053634Z`。

随机部分：4 样本试跑 σ 8–11 K（MC 进行中）。原因是 VBE 与 vbg / r_ref 派生的参考比较，带隙本身的失配（vbg σ 2.2 %，未修调）和两路 LVT 拷贝的失配（pfet_lvt A_VT ≈ 20 mV·µm）都按 1 V 量级全额进入；PTAT 方案同样受这两项限制（约 2 %，≈ 6 K）。做到 1–2 K 需要室温一点修调或斩波。PLL 用途只要粗分档：[上电选码模型](pll_vco.md#上电选码的实现2026-11-09模型待补点数据复核)显示 ±30 K 误差仍保留大部分好处，所以先不修调。

（进行中：比较器、门限、温度感测的局部失配 MC。）

## 适用范围

- 原理图级、无版图寄生；PNP 模型没有失配项，温度感测的随机部分只含 MOS 与电阻。
- 门限码译码为行为模型；码切换瞬态未表征。
