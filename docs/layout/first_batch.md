# 版图起步：第一批模块指南

**结论：第一批画 PLL 环路滤波器、尾线滤波、VCO＋四个首级 buffer、PFD，以及焊盘/ESD 规划；偏置参考要先把行为元件换成实际器件再画。预分频、各类接收器、CP、LDO、TX 时钟链与输出级、RX 暂不画（原因见“暂不画”）。顺序：先用环路滤波器打通 DRC → LVS → 提取 → 回到 ngspice 测试台的流程，再画 VCO 并做提取后仿真，回灌码表。**

本文写给所有者和辅助画版图的 agent。电路尺寸以文中列出的网表为准，本文只摘要；网表与本文冲突时以网表为准。2026-11-11 写成，设计处于半定型（[下一版迭代候选](../status/next_iteration.md)）。

## 1. 环境

| 项目 | 位置 / 命令 |
|---|---|
| PDK | `PDK_ROOT=/home/host/.volare`，`$PDK_ROOT/sky130A`（`config/pdk.toml`） |
| magic | `magic -rcfile $PDK_ROOT/sky130A/libs.tech/magic/sky130A.magicrc` |
| KLayout 0.30.12 | DRC 规则 `$PDK_ROOT/sky130A/libs.tech/klayout/drc/sky130A_mr.drc`；PCell 在 `libs.tech/klayout/pymacros` |
| netgen（LVS） | `netgen -batch lvs "layout.spice <cell>" "ref.spice <cell>" $PDK_ROOT/sky130A/libs.tech/netgen/sky130A_setup.tcl lvs.out` |
| IO 焊盘 | `$PDK_ROOT/sky130A/libs.ref/sky130_fd_io/mag/`：`sky130_ef_io__analog_pad`、`analog_esd_pad`、`analog_minesd_pad`、`analog_noesd_pad` |
| 仿真 | `/opt/ngspice47/bin/ngspice`；测试台见各模块 `tb/`，`uv run python …` |
| 不可用 | OpenROAD 未装，数字模块（CDR、PLL 控制、串化控制等 RTL）暂不能自动布局布线 |

器件一律用 PDK 生成器生成（magic `Devices` 菜单 / `magic::gencell sky130::<device>`，或 KLayout PCell），保证 LVS 能识别。

magic 常用：
```
drc style drc(full); drc check; drc count; drc why      # DRC
extract all; ext2spice lvs; ext2spice -o <cell>_lvs.spice  # LVS 用网表
extract all; ext2spice cthresh 0; ext2spice -o <cell>_pex.spice   # 带寄生电容
```
需要电阻寄生时用 `extresist`（先 `extract all`、`ext2sim labels on; ext2sim`、`extresist tolerance 10; extresist`，再 `ext2spice extresist on`）。

## 2. 通用约定

### 2.1 器件映射

项目网表用薄包装（`analog/common/devices/spice/sky130_primitives.spice` 等）。**w 是总宽，nf 是指数，单位 µm。**

| 网表里 | PDK 器件 |
|---|---|
| `serdes_nfet` | `sky130_fd_pr__nfet_01v8` |
| `serdes_nfet_lvt` | `sky130_fd_pr__nfet_01v8_lvt` |
| `serdes_pfet` | `sky130_fd_pr__pfet_01v8` |
| `serdes_pfet_lvt` | `sky130_fd_pr__pfet_01v8_lvt` |
| `sky130_fd_pr__cap_mim_m3_1 w l` | MIM（met3 下极板、capm/met4 上极板），约 2 fF/µm²；22.1965 µm 方块约 1 pF |
| `sky130_fd_pr__cap_var_lvt` | 累积型变容管 |
| `sky130_fd_pr__res_high_po_*` | P+ 高阻多晶 |
| `sky130_fd_pr__pnp_05v5_W3p40L3p40` | 带隙 PNP |

### 2.2 先要做的事：版图参考网表（第 0 步）

现有网表是仿真视图，有几类元件不能直接拿来做 LVS：

| 仿真里的东西 | 版图里怎么处理 |
|---|---|
| 理想电阻 `R…`（CML 负载 400/600 Ω 等） | 仿真时由 `serdes_flow.rcorner.to_pdk` 换成 `res_high_po`，宽 w = max(1, ceil(1012/R)) µm（如 2、3 µm）。**这些不是 PDK 的标准宽度**（high_po 只有 0.35/0.69/1.41/2.85/5.73 µm）。版图前要改用标准宽度、按 PDK 模型重算长度，并核对阻值 |
| `serdes_ldo_res` 的 w=1 µm 高阻（尾线滤波的 31.25 kΩ 单元） | 同上，改为标准宽度（如 0.69 或 1.41 µm） |
| 理想电容 `C…`（如 PFD 复位延迟 5 fF、带隙 Cc 6 pF、cvgi 2 pF、cvbg 5 pF、CML 偏置 cdec 5 pF、前端每根线 0.5 fF） | 0.5 fF 线电容和 20 fF 负载代理只用于仿真，版图删去，由提取替代；其余换成 MIM 或 MOS 电容 |
| `Rdc … 1T`（电容阵列浮动节点直流路径） | 仅为仿真收敛，版图删去 |
| B 源（带隙修调码 `Bg0..Bg4`） | 换成实际修调位引脚 |
| `Vlink cp_in ctrl 0` | 版图里是同一节点 |

参考网表由 Claude 生成并校核（放在各模块 `layout/` 下，子电路名和引脚顺序与仿真网表相同，以便提取网表直接替换回测试台）。画版图前先拿这份网表。

### 2.3 供电域与引脚

当前采用的分域（`analog/pll/top/spice/pll_core_r5k4q.spice`）：

| 域 | 内容 |
|---|---|
| quiet `vdd_q` | VCO、四个首级 buffer、CP、环路滤波器（含接 VDD 的 12 个 MIM）、码驱动、CP vbp 二极管 |
| host `vdd` | PFD、预分频、反馈与全速接收器、偏置参考与其电流拷贝 |
| 地 `vss` | 公共地 |

- quiet 与 host 在版图上是两张独立的电源网，只在 LDO / 引脚处汇合；不要在块内短接。
- HV 配置下 quiet 引脚外加电容 ≤ 100 pF（LDO r4 稳定性）；**片上接 quiet 的电容（LF 的 12 pF 等）也是 LDO 的负载，不要自行在 quiet 上加去耦**，要加时先与 LDO 核对。
- PFD 与预分频所在的域可能调整（见“暂不画”里的宿主 Kd 问题）：PFD 画成独立电源引脚的单元，便于改接。
- 每个模拟块外围放衬底接触环（P+ 接 vss），NMOS 与 PMOS 区之间留阱接触；高阻节点（z、ctrl、vbias_q）四周加地屏蔽。

### 2.4 金属层建议

met1/met2 单元内连接；met3 是 MIM 下极板，也走局部信号；met4 是 MIM 上极板引出，也走电源；met5 走全局电源。敏感模拟节点不要从 2 GHz 相位线或数字线下方/上方平行长距离经过。

### 2.5 文件放置

```
analog/<模块>/layout/<cell>.mag / .gds       版图
analog/<模块>/layout/<cell>_ref.spice        参考网表（第 0 步）
analog/<模块>/layout/<cell>_lvs.spice        提取（LVS）
analog/<模块>/layout/<cell>_pex.spice        提取（寄生）
analog/<模块>/layout/README.md               DRC/LVS 结果、面积、与本文约束的对照
```
提取后仿真的运行结果按惯例写入 `results/`，只追加。

## 3. 逐模块

### 3.1 环路滤波器 `pll_loop_filter_k4`（流程试点）

网表：`analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice`（子电路 `pll_loop_filter_k4`；同文件的 `_h13`、`_s7`、`k8c` 是未采用的候选，不画）；传输门 `pll_lf_tgate_lvt` 在 `passive_rc_precharge.spice`。

引脚：`cp_in ctrl z pre_ref pre_en vdd vss`（`cp_in` 与 `ctrl` 同一节点；`vdd` 接 quiet）。

| 器件 | 数量 / 尺寸 |
|---|---|
| Rz | `res_high_po_0p69`，L 7.594 µm（约 4.13 kΩ，TT 27 °C），ctrl–z |
| Ci | 18 个 MIM 22.1965 × 22.1965 µm（约 1 pF）：12 个 z–vdd，6 个 z–vss。每个单元单独实例（PDK 的 mf 不放大电容） |
| 预充门 | ctrl 侧 nfet W4 + pfet_lvt W8；z 侧 nfet W8 + pfet_lvt W16（L 取默认：nfet 0.15，pfet_lvt 0.35） |
| 反相器 | nfet W4 / pfet W8，产生 pre_b |

约束：
- MIM **上极板接 z，下极板（met3）接 vdd 或 vss**：下极板对衬底的寄生落在电源/地之间，不挂到 z 上。
- 12/6 分接是电源抑制的设计量（[PLL 环路](../design/pll_loop.md)）：z 对 vdd、vss 的额外寄生尽量对称，避免 z 走线贴着某一条电源长距离平行。
- ctrl 节点（接 CP 输出与 VCO 控制端）：环路设计在实测 CP＋预充门约 50 fF 之外按 150 fF 留量（PM 约 50°），所以 **ctrl 走线电容 ≤ 约 90 fF**；LF 紧挨 VCO 和 CP 放置，ctrl 加地屏蔽。
- z 节点：电容不敏感，但对漏电敏感（预充门关断漏电已有约 186 nA 最差估计），扩散面积保持最小，不要加额外器件。
- 面积参考：旧 42 个 MIM 方案约 0.0207 mm²；本单元 18 个 MIM 约 0.009 mm² 加间距。

验收：DRC 净；LVS 与参考网表一致；提取后 Rz、Ci、ctrl/z 对地与对 vdd 的寄生电容列表；用 `analog/pll/loop_filter/tb/impedance` 测试台换入提取网表，阻抗曲线与原理图对比。

### 3.2 尾线滤波 `serdes_pll_bias_lowpass_slow_r4`

网表：`analog/common/ldo/spice/pll_bias_filter_r4.spice`，无源单元在 `analog/common/ldo/spice/ldo_passives.spice`（这两份是 Codex 的 LDO 文件，只读）。

引脚：`original filtered vss`。original 接 PLL 本地 CML 二极管之后的 vbias；filtered 即 vbias_q，只接 VCO 与四个首级 buffer 的尾管栅极。

| 器件 | 数量 / 尺寸 |
|---|---|
| R | 1 MΩ：32 个 31.25 kΩ high_po 单元串联（仿真里 w 1 µm、每个 L 约 97 µm；版图改标准宽度，见 2.2） |
| C | 16 pF：16 个 22.1965 µm MIM，filtered–vss |

约束：
- filtered 是 1 MΩ 后的高阻节点，−3 dB 约 7–10 kHz：远离 2 GHz 相位线和 host 电源；四周地屏蔽；到各尾管栅的走线短。
- MIM 上极板接 filtered，下极板接 vss。
- 本地 CML 二极管与 PMOS 电流拷贝留在 original 一侧（拷贝在 host 域，二极管 nfet W5/L0.5 加 5 pF 去耦，见 `analog/common/bias/spice/bias_dist.spice` 的 `serdes_bias_cml`），不要接到 filtered。

### 3.3 VCO `pll_vco_ring4_4b` 与四个首级 buffer

网表：`analog/pll/vco/spice/vco_ring4_4b.spice`；延迟单元 `analog/common/cml_buffer/spice/cml_delay_resistive.spice`（`serdes_cml_delay`）；电容阵列 `analog/pll/vco/spice/cap_bank_4b.spice` 与 `cap_bank_3b.spice`（单元 `pll_vco_cap_unit`）；buffer `analog/common/cml_buffer/spice/cml_buffer.spice`。在 `analog/pll/top/spice/clock_frontend_r5q.spice` 里以默认参数实例化，VCO 与 buffer 都在 quiet，尾管栅接 vbias_q。

VCO 引脚：`q0p q0n q1p q1n q2p q2n q3p q3n vctrl b0 b1 b2 b3 vbias vdd vss`。

| 部分 | 每个 | 数量 |
|---|---|---|
| 延迟级 | 输入对 nfet_01v8_lvt W40（总）L0.15 nf8 ×2；尾管 nfet_01v8 W20 L0.5 nf4；负载电阻 400 Ω ×2（ideal → high_po，见 2.2） | 4 级成环（第 0 级输入接第 3 级反相输出） |
| 变容管 | `cap_var_lvt` w4.5 l0.5 vm4；**栅接相位节点，阱接 vctrl**，衬底 vss | 每个相位节点 1 个，共 8 个 |
| 电容阵列 | 每个相位节点 15 个半单元：MIM 2.35 × 2.5 µm 串开关 nfet_01v8 W2.5 L0.15 到地；按 1:2:4:8 分给 b0..b3 | 8 × 15 = 120 个 |
| 首级 buffer | 输入对 nfet_01v8_lvt W12 L0.15 nf4 ×2；尾管 W12 L0.5 nf4；负载 600 Ω ×2 | 每相一对，共 4 个 |

约束：
- **8 个相位节点完全对称**：同样的器件、同样的走线长度与邻居。四相间隔来自匹配原理图，版图不对称直接变成相位误差（RX 采样和 TX 都用这些相位）。推荐把 4 级排成一行再折回（或 2×2 环形），使每级到下一级的连线等长；每级 p/n 两侧镜像。
- **相位节点寄生电容预算（关键）**：4 bit 码＋Vctrl 窗口的调谐量程“刚好够，没有富余”（[VCO](../design/pll_vco.md)）。慢端 FS 85 °C hh 已用到码 0，快端 SF 1.65 V −40 °C ll 用到码 15、Vctrl 只比窗口下限高 7 mV。版图寄生是固定附加电容，使频率整体变慢：
  - 快端反而受益（寄生越多越容易落入窗口）；
  - 慢端受限：粗估慢端还剩约 7–10 % 频率余量，对应**每个相位节点比原理图多出的电容约 ≤ 15 fF**（按节点总电容约 230 fF 估算，未经提取验证）。
  - 原理图已含器件的估计结电容和每节点 0.5 fF 线电容；目标把版图新增控制在 5–10 fF/节点。超出时要回调阵列或负载，必须尽早知道。
- vctrl 连 8 个变容管的阱，是环路控制节点（VCO 自身 0.2–0.7 pF 已计入）：走线加屏蔽，不与相位线平行。
- 码线 b0..b3 是静态线（码驱动在 quiet 域），可以走长，但不要跨相位节点。
- buffer 输出（b0p/b0n…）跨到 host 域的接收器与预分频：四路差分对等长、等负载；三条 dummy 支路的负载与真实反馈支路相同（这是对称的来源）。
- 电源：vdd_q 走宽，四级共用一条对称的电源/地梳；尾管栅线 vbias_q 来自尾线滤波，单点进入后对称分配。

验收（提取后，按原测试台）：
1. 调谐曲线：`analog/pll/vco/tb/tuning` 换入提取网表，至少跑慢端 FS 1.95 V / 1.65 V 85 °C hh 码 0 与快端 SF 1.65 V −40 °C ll 码 15，确认 2 GHz 仍落在 Vctrl 窗口 [0.90 V, VDD − 0.44 V] 内。
2. 四相间隔、摆幅（原理图 365–529 mVpp）、相噪（`tb/phase_noise`）。
3. 结果用于重做码表（`config/pll_code_table.json`）与粗码窗口，这一步由 Claude 做。

### 3.4 PFD `pll_pfd`

网表：`analog/pll/pfd/spice/pfd_cmos.spice`；DFF `analog/pll/pfd/spice/cmos_dff_reset.spice` → `analog/common/devices/spice/cmos_dff_reset.spice`；门 `analog/common/devices/spice/cmos_logic.spice`。

引脚：`ref fb rst_b up dn vdd vss`。静态 CMOS：两个带异步清零的 DFF、NAND、两级反相器复位延迟（Cd1、Cd2 各 5 fF 理想电容）、AND 产生 clear_b；输出 UP/DN 各两级反相器（末级 nfet W4 / pfet W8）。

约束：
- UP 与 DN 两条路径镜像对称，到 CP 输入的走线等长：失配直接变成静态相差。
- 复位延迟的 5 fF：用 MOS 电容或布线实现，提取后核对复位脉宽（原理图 UP/DN 窄脉冲宽度见 [PLL 环路](../design/pll_loop.md)）。
- 放在 CP 旁边；电源单独引脚（见 2.3）。

### 3.5 偏置参考 `serdes_bias_ref`（需先完成第 0 步）

网表：`analog/common/bias/spice/bandgap.spice`（`serdes_bandgap`、`serdes_bg_amp`、`serdes_bg_ota`）、`analog/common/bias/spice/bias_dist.spice`（`serdes_bias_ref`、拷贝 `serdes_bias_pcopy`、模块端二极管）。

仿真网表里有行为元件：修调码 B 源、理想 Rz 20 kΩ、Cc 6 pF、cvgi 2 pF、cvbg 5 pF。先由第 0 步换成实际器件和修调引脚，再画。

约束（拓扑稳定，匹配敏感）：
- PNP：Q1 1 个、Q2 8 个（m=8）、Q3 1 个，按 3×3 共质心排（Q1 居中或按对称轴放），外围一圈 dummy。
- 电阻 R1、R2、Rs、r_ref 及修调串：同宽度、同方向、交叉排列，加 dummy；r_ref 与 CML 负载同类型（恒摆幅偏置依赖这一点）。
- PMOS 源 Xm1..Xm5（pfet_lvt W24 L8）与 Mv（W24 L4 nf4）：共质心；电流拷贝单元为 pfet_lvt W6 L4 的指，各模块的拷贝放在模块本地（分发的是电流，不是栅压）。
- vgi 是全局栅线：屏蔽，远离数字和时钟线。

### 3.6 焊盘与 ESD 规划

- 可以先确定焊盘框：TX 输出 2 个、RX 输入 2 个、参考时钟、quiet 引脚（HV 配置）、HV 输入、各电源/地。
- 模拟焊盘用 `sky130_ef_io__analog_pad` 系列；按引脚选 ESD 强弱（高速 TX/RX 先比较 `analog_minesd_pad` 与 `analog_esd_pad` 的电容）。
- 目的：用实际焊盘＋ESD 电容替换 TX 输出现在的 200 fF 代理（`analog/tx/output_driver/tb/ddj`），以及给出封装/键合的实际模型。这会影响 TX 输出带宽和摆幅取舍。

## 4. 暂不画

| 模块 | 原因 |
|---|---|
| 预分频 `pll_cml_prescaler8`、反馈/全速接收器 | 2026-11-11 发现宿主电源经它们的延迟（Kd，SS 1.65 V −40 °C 约 2.1 ps/mV）主导供电纹波容限，可能改结构或换域；I-10 低压冷角尾管余量也未收 |
| CP `pll_cp_steer` | I-12 窗口与门限失配尾部未收 |
| LDO r4 | 若环内单元移到 quiet，负载范围要从 10 mA 扩大，可能改 |
| TX buffer 链、输出级 | I-17 尺寸在调；焊盘 400 mVpp 定义与 800 mVpp 选项未定 |
| RX（PI、采样器、CDR） | 校准与动态在做 |
| 数字（RTL） | 无 OpenROAD |
| 顶层布局 | 等 quiet/host 分域定案；可先按面积出草图 |

## 5. 验收与回灌

1. DRC：magic `drc(full)` 与 KLayout `sky130A_mr.drc` 都净。
2. LVS：netgen 对第 0 步参考网表一致（器件参数在容差内）。
3. 提取网表保留原子电路名与引脚顺序，测试台只换 include，跑上面每块列出的测试。提取后结果与原理图结果并列记录，不覆盖原结果。
4. 每块在 `layout/README.md` 写：面积、DRC/LVS 状态、关键节点寄生电容（相位节点、ctrl、z、vbias_q）、与本文预算的对照。

## 6. 依据

[PLL 环路](../design/pll_loop.md)（环路、LF、供电分域与 LDO 接入）、[VCO](../design/pll_vco.md)（调谐量程、电容阵列选择）、[偏置](../design/bias.md)、[LDO r4](../design/ldo_r4.md)（quiet 引脚电容约束）、[TX 输出级](../design/tx_output_driver.md)（焊盘代理）、[问题表](../status/open_issues.md)。
