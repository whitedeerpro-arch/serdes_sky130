# 版图任务单（给辅助画版图的 agent）

由 Claude 派发和验收。背景与约束见[版图起步](first_batch.md)，Magic 操作见[速查](magic_quickstart.md)。**一次只做一个任务，按顺序做；做完在文末状态表更新自己那一行，然后停下等验收。**

DeepSeek等执行者的入门课见[DS-01工作单](training/DS-01-inverter.md)和[配图教材](deepseek_training.md)。该课只操作独立教学副本，不替代下面T1/T2等生产任务的范围、参考或验收。

## 规则（每个任务都适用）

1. **判定只看检查器。** 运行
   ```bash
   uv run python verification/layout/check.py <layout目录> <cell> --ref <参考网表>
   ```
   通过的唯一标准：退出码 0，且输出里 `DRC_TOTAL 0`、`LVS_MATCH True`、`LVS_PROPERTY_ERRORS False`、`LVS_DISCONNECTED none`（最后一条 2026-11-11 加入：netgen 在端口标签落在孤立图形上时仍报匹配）。README 和状态表里写结论时，**原样贴完整输出，保留这四项**。不要写“DRC 净”“LVS 通过”之类的话而不贴原文。
2. **不改检查器的判定部分**（`check.py` 里的 `drc()` 和退出码）。觉得它有问题，写在状态表“问题”栏，等 Claude 处理。
3. **器件生成：** 新脚本用 `magic::gencell sky130::<器件名> <cell名> w … l … nf …`。不要直接调 `sky130::*_draw`；**任何生成器调用之前都不要执行 `units microns`**（2026-11-11 的反相器练习就是这样把阱和保护环画小了：PMOS 扩散在 N 阱外，46 个 DRC 错误）。每个器件单元先单独过 DRC：只允许 `met1.6`（栅接触短头未连线时的金属1 面积）。
4. **只改修版图板块的文件：** `analog/<模块>/layout/`、`verification/layout/`（检查器判定部分除外）、`docs/layout/` 下你自己建的文件。不改 `analog/*/spice/`、`config/`、`docs/design/`、`results/` 里已有的东西。参考网表和本任务单由 Claude 提供或修改。
5. **临时文件** 放 `/tmp` 或各 `layout/work/`，不要放仓库根目录（现在根目录的 `tmp_layout_test/` 请移到 `analog/pll/loop_filter/layout/work/` 或删除；根目录的 `hs_pam_engineerofthepeople_invlayout.jpg` 是所有者的，不要动）。
6. **ngspice 名额：** 全机最多 4 个，Claude 和 Codex 各常用 2 个。跑之前看 `pgrep -x ngspice | wc -l`，小于 4 才跑，且你一次只跑 1 个。magic、netgen、klayout 不受限。
7. **不确定就停。** 规则看不懂、约束冲突、改动会碰到第 4 条以外的文件，都写进状态表“问题”栏，不要猜着做下去。
8. **器件值不归版图定。** 参考网表里的阻值、电容值、W/L/nf 由 Claude 给（下面“器件值”表）。DRC 逼你换器件类型或尺寸时，停下来在“问题”栏写清楚，等 Claude 给新值；**不要为了让 LVS 通过去改参考网表的值**，也不要用公式自己推阻值。电阻类型（高阻/通用多晶）是设计决定，不能换。
9. **先读[版图手册](cookbook.md)**：规则数值、套路、流程和交付前自检都在那里。

## 器件值（Claude 给定，ngspice 实测 TT 27 °C，2026-11-11）

固定宽度高阻多晶 = 头部电阻 + 斜率 × L：0.69 µm 宽 417 Ω + 485 Ω/µm，1.41 µm 宽 268 Ω + 227 Ω/µm，2.85 µm 宽 138 Ω + 112 Ω/µm，5.73 µm 宽 69 Ω + 56 Ω/µm（长 L 时斜率略升，1.41 宽在 16–18 µm 处 230 Ω/µm）。**没有 779.8 Ω 的地板**，`high_po_notes.md` 第 1、2 节的公式是误读模型卡，作废。

| 用途 | 器件 | 实测 | 原仿真用值 |
|---|---|---:|---:|
| 环路滤波 Rz | `res_high_po_1p41 l=16.82` | 4125 Ω | 4126 Ω |
| 尾线滤波 31.25 kΩ 单元（32 只串联） | `res_high_po_1p41 l=134.73` | 31.25 kΩ | 31.27 kΩ |
| VCO 延迟级负载（r6，每侧两只并联） | `res_high_po_2p85 l=4.77` × 2 | 每只约 676 Ω，并联约 338 Ω | — |
| CML 负载 600 Ω（首级 buffer、预分频锁存器） | `res_high_po_2p85 l=4.22` | 611 Ω | 611 Ω |

CML 负载必须是高阻多晶（与带隙 r_ref 同类型，恒摆幅偏置靠这一点），不用通用多晶。

## T1　环路滤波器修到 DRC 0、LVS 无属性错误

现状（Claude 用修好的检查器复查，2026-11-11）：`DRC_TOTAL 255`，`LVS_MATCH True`，`LVS_PROPERTY_ERRORS True`。README 里的“DRC 净”是旧检查器的假通过（它没有等 DRC 跑完就计数），要改掉。

错误按规则（框数，多的在前）和修改方向：

| 规则 | 含义 | 方向 |
|---|---|---|
| met4.2 | 金属4 间距 < 0.3 µm | z 的 m4 母线和各 MIM 上极板引出之间留 ≥ 0.3 µm；m4 最小宽度 0.3 µm |
| capm.11 | MIM 上极板（capm）到无关 m3 < 1.34 µm | 不属于该电容下极板的 m3（电源轨、信号）离 capm 边 ≥ 1.34 µm；下极板接电源时直接把轨并到下极板上，或把电源改走 m4/m5 |
| via.1a | via1 太小 | via1 画成 ≥ 0.26 µm 方块（含规则要求的 m1/m2 包边） |
| met1.6 | 金属1 面积 < 0.083 µm² | 栅接触短头连上走线，或把 m1 补到面积 |
| met1.5 | mcon 的金属1 包边不足 | mcon 一个方向的 m1 包边 ≥ 0.06 µm |
| met3.3c / met3.2 / met3.3d | 金属3 间距 | m3 间距 ≥ 0.3 µm；靠近宽 m3 时 ≥ 0.4 µm |
| mcon.1 | mcon 宽度 < 0.17 µm | mcon 画成 0.17 µm 方块 |
| rpm.1 | 电阻的 RPM 标记宽度 < 1.27 µm | 不要在 Rz 上方涂/擦其他层；先单独检查 Rz 器件单元 |

步骤：
1. 改 `build_pll_loop_filter_k4.py`（在生成脚本里改，不手改 flatten 后的 `.mag`），重新生成。
2. LVS 属性错误：参考网表里 `Xrz` 写了 `w=0.69`，而 `res_high_po_0p69` 的宽度是器件本身固定的，提取结果没有 w 属性。在 `pll_loop_filter_k4_ref.spice` 里删掉 `w=0.69`（这一处你可以改）。
3. 跑检查器，直到退出码 0。
4. 重跑 `analog/pll/loop_filter/tb/impedance_pex/run.py`（1 个 ngspice），更新 README 的表；ctrl 走线电容仍要 ≤ 90 fF，z 对 vdd/vss 的额外寄生要列出来。
5. 可选，作为第二意见：`magic` 里 `gds write pll_loop_filter_k4.gds` 后运行
   `klayout -b -r $HOME/.volare/sky130A/libs.tech/klayout/drc/sky130A_mr.drc -rd input=pll_loop_filter_k4.gds -rd top_cell=pll_loop_filter_k4 -rd report=klayout_drc.lyrdb`，在 README 里写出错误数。

验收：贴检查器三行原文，加上新的阻抗表和 ctrl/z 寄生。

## T2　反相器重画成标准堆叠形式（练手单元，也是以后逻辑小单元的模板）

`analog/common/layout_practice/inv_practice.mag` 的两个器件是坏的（见规则 3），而且只是两个未连接的器件横向并排，不是反相器。要求：

- 新 cell `inv_std`，参考网表沿用 `inv_practice_ref.spice` 的电路（nfet W4 / pfet W8，L 0.15），端口 `d g vdd vss`，子电路名改成 `inv_std`。
- 形状按所有者给的图（仓库根目录 jpg）：**PMOS 在上、NMOS 在下；一根竖直多晶栅同时穿过两管；两管漏极用 m1 竖条连成输出；PMOS 源接上方 VDD 的 m1 横轨，NMOS 源接下方 GND 的 m1 横轨；N 阱包住 PMOS，N 阱接触放在 VDD 轨下，P 衬底接触放在 GND 轨下。**
- 这种共用栅的形状用 paint 直接画（poly 跨过 diff 时 magic 自动识别成晶体管），不用生成器。
- 在 README 写出单元宽 × 高。
- 修 `make_practice.py`：删掉 `units microns`，或者改用 `magic::gencell`；修完旧的 `inv_practice.mag` 要能过器件单独 DRC。

验收：检查器三行原文；单元尺寸。

## 验收（Claude，2026-11-11）

- **T1：版图通过，阻值要改。** 独立复查 `DRC_TOTAL 0`、`LVS_MATCH True`、`LVS_PROPERTY_ERRORS False`。换成 1.41 µm 宽是对的（0.69 的生成器单元自己违反 rpm.1，好发现），但 `l=16.22` 按错的公式算，实测只有 3.99 kΩ（低 3.4%）。改成上表的 `l=16.82`，参考网表和版图一起改，重跑检查器和 `impedance_pex`，README 里“4.51 kΩ”改正。
- **T2：通过。** 改进练习见 T2b。
- **自己往前做的草稿（尾线滤波、VCO 三个子块、PFD 选项）：** 先停。尾线滤波单元长度按上表改为 134.73 µm；VCO 子块的负载按上表改成 2.85 µm 宽；改完各跑检查器，状态写“草稿”。PFD 等 Claude 用标准单元网表重做 PFD＋CP 仿真后再定。

**第二轮验收（Claude，2026-11-11）：T1 复交通过**（`Xrz` 为 `res_high_po_1p41 l=16.82`，检查器四行全过）；**T2b 通过**（`inv_std2` 检查器四行全过，D 端口已修）。

## T2b　反相器改进练习（练套路）

在 `inv_std` 的基础上做 `inv_std2`，电路不变（nfet W4、pfet W8）：
1. 源漏接触排满整个宽度（[手册](cookbook.md) 第 2 节“接触排满”）；
2. PMOS 折成 2 指（`w=8 nf=2`，两端为源），NMOS 也折 2 指（`w=4 nf=2`），让单元变矮；
3. 参考网表 `inv_std2_ref.spice` 写成 `nf=2`（这是练习，器件值不变，允许你写）。

验收：检查器三行；单元宽 × 高，与 `inv_std` 的 5.85 × 16.15 µm 对比；每个源漏的接触数。

## T3　VCO 核心（r6，2026-11-12 重新下发；此前的 T3 全部作废）

**为什么重发：** 旧 VCO（r5）在原理图上量程刚好够，每个相位节点只容得下约 8 fF 版图寄生，而真实版图约 20 fF。电路已改成 r6：把版图寄生写进原理图，重新定了尺寸。**旧尺寸的单元（2.52 × 2.68 的 MIM、400 Ω 单只负载、W 4.5 变容管、15 单元阵列）都不再用。**

**参考网表**（Claude 写，`analog/pll/vco/layout/`，器件值不许改）：

| 单元 | 文件 | 器件 |
|---|---|---|
| 电容半单元 | `pll_vco_cap_unit_ref.spice` | MIM **2.0 × 2.0 µm**；开关 nfet W **1.5** L 0.15，**两指（各 0.75）共用漏极** |
| 电容阵列 | `pll_vco_cap_bank_ref.spice` | **31 个**半单元，按 1 : 2 : 4 : 8 : 16 接 b0..b4 |
| 延迟级 | `pll_vco_delay_stage_ref.spice` | 输入对 lvt W 40（8 指 × 5）；尾管 W **25.2**（4 指 × 6.3）L 0.5；**每侧负载两只 `res_high_po_2p85 l=4.77` 并联**（共 4 只） |
| 变容管 | `pll_vco_varactor_ref.spice` | **4 个独立的指，每指 W 5.2 / L 0.5** |
| 首级 buffer | `serdes_cml_buffer_ref.spice` | 不变（你已画的可用） |
| 整体 | `pll_vco_core_ref.spice` | `pll_vco_ring4_r6`（4 级环＋8 变容管＋8 阵列）和 `pll_vco_core`（环＋4 个 buffer） |

**LVS 查不出来、必须照做的要求：**
1. **MIM 方向：上极板（capm）接相位节点 `node`，下极板（met3）接开关漏极 `plate`。** 核对：`*_lvs.spice` 里 MIM 那行第一个引脚必须是 `node`；README 里贴出这一行。
2. **下极板不绕线。** 开关紧贴 MIM 下极板的一边，via2 直接从下极板 m3 的边上下到开关漏极。下极板 m3 只保留 MIM＋0.14 包边＋一个放通孔的小凸台，周围不走 vss 或别的金属。capm.11 的 1.34 µm 只限制**无关**的 m3，下极板自己的 m3 不受它限制。不留浮空的 m3。
3. **开关两指共用漏极**：漏极在两指中间，源极在两侧接 vss。
4. **变容管 4 个独立的指**，不是一个宽指。栅（poly）接 `node`，N 阱接 `vctrl`，衬底 vss。
5. **负载电阻每侧两只，不许合成一只短的**：短电阻在工艺角上偏差 ±20.7%，两只长的并联只有 ±14.7%，这是量程的一部分。两只并排、同方向，一端共同接 vdd，另一端共同接输出。

**寄生预算（硬约束）：**
- **电容半单元**（交付前自检，用下面的 deck）：断开 ≤ **1.7 fF**，接通 **9.9 ± 0.4 fF**（原理图单元已含寄生估计：断开 1.54、接通 9.90）。
- **每个相位节点的连线**（环内互连、延迟级输出走线、到阵列/变容管/buffer 的线，不含单元内部）：≤ **12 fF**，目标 8–10 fF。8 个节点要对称，差别 ≤ 0.5 fF。
- `vctrl` 线屏蔽，不与相位线平行。

自检 deck（`<model_library>` 的取法见[手册](cookbook.md)第 4 节）：

```
cap unit check
.lib "<model_library>" tt
.include "pll_vco_cap_unit_pex.spice"
Ven en 0 0
Vn n 0 1.3 ac 1
X1 n <按你提取网表的引脚顺序> pll_vco_cap_unit
Rdc <plate 网络名> 0 10Meg
.control
op
print v(<plate 网络名>)
ac lin 1 2e9 2e9
print -imag(i(vn))/(2*pi*2e9)
alter Ven dc=1.8
ac lin 1 2e9 2e9
print -imag(i(vn))/(2*pi*2e9)
.endc
.end
```
（`Rdc` 用 10 MΩ：下极板几乎悬空，用更大的电阻时工作点会停在 0.6–1.1 V 的随便哪个值，结电容偏小、结果不算。`print v(...)` 必须约等于 0 V。）

**顺序：** `cap_unit`（过检查器＋自检）→ `varactor` → `delay_stage`（负载改成每侧两只）→ `cap_bank`（31 单元）→ `pll_vco_ring4_r6` → `pll_vco_core`。每一级在 README 里列出相位节点的提取电容（对地、对 vdd、对相邻节点分开写）。**每做完一级停下，在状态表里写结果，等验收再做下一级。**

**你 03:36 那版电容单元的问题（供对照）：** 方向和当时的尺寸都对，但下极板从 MIM 右边绕出 7.8 µm 再折回开关（下极板 m3 16.8 µm²，是 MIM 的 2.5 倍），外加两块浮空 m3、单指开关；断开电容 4.51 fF，是原理图的两倍多。上面第 2、3 条就是针对它。

## T4　PFD（标准单元，正式下发，2026-11-11；**2026-11-12 加一个延迟单元**）

**电路已定：用标准单元，单元名 `pll_pfd_sc_dly`。** 网表 `analog/pll/pfd/spice/pfd_sc.spice`。11-11 版（无延迟）在失配 MC 里有 5% 样本卡死（复位环路太短，只比 `dfrtp_1` 的 removal 约束长 2–20%），复位环路里加一个 `dlygate4sd1_1` 后 200 样本无卡死（结论见 [PLL 环路](../design/pll_loop.md)）。
- 单元：`dfrtp_1` ×2、`nand2_1`、`inv_1` ×2、**`dlygate4sd1_1` ×1**（接在第二个 `inv_1` 之后、`and2_1` 之前）、`and2_1`、输出每路 `inv_4` → `inv_8`。共 11 个逻辑单元，不加任何电容。
- 参考网表：`analog/pll/pfd/layout/pll_pfd_sc_ref.spice`（已更新为 `pll_pfd_sc_dly`；层次，`.include` 库的 SPICE）。检查器能否直接做层次比对先试；不行就把问题写进状态表，等 Claude 处理，不要改成平面网表绕过。
- 你 11-11 的草稿（`build_pll_pfd.py`、`pll_pfd.mag`，5 个单元摆一排）作废，按下面第 1 条重新按行摆。

要求：
1. **按标准单元行摆**：行高 2.72 µm，电源轨首尾对接；一行放不下就两行，上下翻转共用轨；每 ≤ 15 µm 一个 `sky130_fd_sc_hd__tapvpwrvgnd_1`，空位用 `decap`/`fill`（[手册](cookbook.md) 第 2 节）。你之前 54 处 LU.2/LU.3 就是缺 tap。
2. **UP、DN 两路对称**：两个 DFF 镜像摆放，`up`、`dn` 引出到单元边的走线等长（它们去 CP 的开关驱动，失配直接变成静态相差）。
3. PFD 的 vdd 单独引脚（宿主域，可能改接，见 first_batch 2.3）。
4. 提取后列出 `up`、`dn`、`clear_b` 的寄生电容；`up` 与 `dn` 相差 ≤ 0.5 fF。

验收：检查器四行；面积；上面第 4 条的电容表。

## T3 以后（等 Claude 给参考网表再开始）

| 任务 | 前提 |
|---|---|
| 尾线滤波 `serdes_pll_bias_lowpass_slow_r4` | **草稿已按器件表改完**（等 Claude 确认参考网表）：`analog/common/ldo/layout/`，1.41 µm 宽 / **L=134.73 µm × 32 只**（每只 31.253 kΩ，链 1.0001 MΩ）+ 16 个 MIM，DRC 0、LVS 匹配；提取版 −3 dB **9.65 kHz**（同器件原理图 9.70、设计原理图 9.80；对同器件 100 kHz 内最大偏差 0.056 dB），面积 0.0344 mm²。详见其 [layout README](../../analog/common/ldo/layout/README.md) |
| VCO＋四个首级 buffer | Claude 给出参考网表（CML 负载 400/600 Ω 用 2.85 µm 宽高阻，见 [high_po_notes](high_po_notes.md) §4）。相位节点寄生预算见 first_batch.md 3.3，是硬约束；走线标定与预算用法见 [vco_phase_budget](vco_phase_budget.md)（0.4 µm m2 约 0.082 fF/µm） | **已做三块（等参考网表确认）**：`pll_vco_delay_stage`（677 µm²，4.4 fF/节点，负载 `res_high_po_2p85 l=2.44`）、`serdes_cml_buffer`（714 µm²，3.6 fF/节点，`l=4.22`）、`pll_vco_cap_unit`（109 µm²），都是 DRC 0 / LVS 匹配，见 [vco/layout README](../../analog/pll/vco/layout/README.md)。电容阵列总线、变容管（手画版已验证）、四级环未完成 |
| PFD | **已定为标准单元，见 T4**。版图侧数据见 [pfd_options](pfd_options.md)：标准单元 2 DFF + 6 门 ≈ 65 µm²、单行约 20 × 5 µm，代价是复位脉宽改由单元延迟定、LVS 改层次比对 |

写参考网表前请看 [high_po_notes](high_po_notes.md)（固定宽度高阻的生成器 DRC 实测）：0.35/0.69 µm 的生成器单元单独就不干净，只有 1.41/2.85 可用；400/600 Ω 直接一只 2.85 µm 宽单元（`l=2.44/4.22`），**不需要并联**——“779.8 Ω 地板”是误读，文件顶部已作废。高阻是 3 端器件（`r0 r1 b`），参考网表里电阻实例要用 `X… vss …` 写，体端接 vss。

## 状态

| 任务 | 状态 | 检查器原文（DRC_TOTAL / LVS_MATCH / LVS_PROPERTY_ERRORS） | 问题 |
|---|---|---|---|
| T1 | **验收通过**（复交，Rz `l=16.82`） | `DRC_TOTAL 0`；`LVS_MATCH True  LVS_PROPERTY_ERRORS False`；检查器退出码 0；KLayout 独立 DRC 0 条；Rz 改后 `impedance_pex` 重跑：10 MHz 提取/原理图比值 **0.998**（改前 0.966），最大偏差 1.78 dB → 1.59 dB（1 kHz 仍是 MIM 边缘重复计数） | 1) Rz 用 `res_high_po_1p41`（0.69 的生成器单元单独就违反 rpm.1），长度按验收意见改成 **`l=16.82`**（4125 Ω，ngspice 实测 TT 27 °C）；参考网表 `Xrz` 与版图同步改，`w` 已删。2) Rz 的体接触不再单独下引：它是 p 衬底、已由 nfet 体抽头接 vss，单独下引会在 vss 总线留 0.125 µm 的 met2.2。3) 根目录 `tmp_layout_test/` 已移到 `analog/pll/loop_filter/layout/work/`（规则 5）。 |
| T2 | **验收通过** | `DRC_TOTAL 0`；`LVS_MATCH True  LVS_PROPERTY_ERRORS False`；检查器退出码 0。单元 5.85 × 16.15 µm | 1) 手画版 `inv_std` 用 paint 脚本（`analog/common/layout_practice/build_inv_std.py`），未用器件生成器。2) `make_practice.py` 的 `units microns` 已移到摆位阶段（生成器调用前不再改单位）；`inv_practice.mag` 重新生成后器件单独 DRC 只剩每个器件 6 个 met1.6。3) 单元偏高是因为 W8 的 PMOS 沟道宽 8 µm；若要压高度需要把 PMOS 折指，参考网表也要跟着改。 |
| T2b | **验收通过**（Codex 的 D 端口复核已修） | `DRC_TOTAL 0`；`LVS_MATCH True  LVS_PROPERTY_ERRORS False`；检查器退出码 0；`inverter_audit.py` → `status: pass` | 1) **D 端口**：原版标签打在孤立 m1 岛上（提取网表四个指都接 `a_430_320#`，netgen 报 `disconnected node: d` 却仍匹配）；已把 `d` 移到 P/N 之间真实共漏 m1 条（y=4.6），重建后审计 `d` 被 X0.D / X1.S / X2.S / X3.D 使用，输出结面积 N 1.7 / P 3.4 µm²。2) `inv_std2` 5.10 × 10.55 µm，比 `inv_std` 的 5.85 × 16.15 µm **矮 5.6 µm（35%）**，宽度也窄 0.75 µm。3) 源漏接触排满：PMOS 每侧 2 排 × 4 个、NMOS 每侧 2 排 × 3 个，全单元扩散接触 **28 个**（`inv_std` 只有 4 个）。4) 折指后两指共用中间漏极，栅用顶部 poly 总线连到左侧焊盘；参考网表按 T2b 要求写 `nf=2`，器件值未变（w=4 / w=8，l=0.15）。5) 踩到并修掉的：`viali` 是 li→m1 接触（不是 mcon）；接触排离栅要留 0.15（licon.11 要 0.055）；栅焊盘不能落在 vdd 轨上（会把栅和 vdd 短起来）；n+ 抽头不能压在栅总线下（会被 magic 认成变容管）。6) 另做改进版 `inv_std3`（Claude 折指 VAR 的中间引栅 + 加宽 m1）：5.10 × 10.70 µm / 54.6 µm²，DRC 0 / LVS 匹配 / 审计 pass；C(vdd,g) 0.701→0.454 fF、C(g,d) 0.101→0.142 fF（栅侧合计 −26 %），但 C(d) 1.346→1.503 fF（加宽金属的代价），详见 [layout_practice README](../../analog/common/layout_practice/README.md)。 |
| T3 | **r6 重新下发**（见 T3）：从电容半单元开始，一级一级做 | Claude 复核你 14:33–14:41 留在磁盘上的版本（2026-11-12 17:30）：均**未通过**，见右 | **延迟级 `pll_vco_delay_stage`**：① 每侧只有一只 `l=4.77` 负载，要求**两只并联**（参考网表里是 Xrp1/Xrp2、Xrn1/Xrn2）；② 提取网表的端口里没有 `vbias`，四个尾管的栅被提取到 `vss` 上（`X10 vss vss tail vss …`）——栅线没打 `vbias` 标签或和 vss 短了，这样 LVS 不可能匹配；③ `outp`/`outn` 对 vss 的提取电容 2.76 / 2.46 fF，差 0.3 fF，两侧走线要镜像（目标差 ≤ 0.1 fF）。**变容管 `pll_vco_varactor`**：器件对（4 指 × 5.2/0.5）。① 提取里有两个浮空网络 `a_1712_290#`、`a_344_290#`：N 阱里的 N+ 接触条没有用金属接到 `vctrl`。阱里**每一条** N+ 接触都要接 `vctrl`（它们是变容管的阱端，悬空会让串联电阻变大、Q 变差，LVS 不报）；改完提取网表里不应再有 `FLOATING`。② `node` 对 `vctrl` 的走线耦合 3.84 fF，占相位节点 12 fF 预算的三分之一：在 README 里写清它来自哪几段金属（栅引线跨阱的部分、与 vctrl 条平行的部分），目标 ≤ 2 fF。**顺序提醒**：先把电容半单元做完并自检（T3 的 deck），它数量最多、最影响结果。 |
| T4 | **先做**（PFD 标准单元 `pll_pfd_sc_dly`，见 T4） | | |

## T2b补充复核：外部D端口（Codex，2026-11-11）

捕获的构建器SHA前缀`60f15d70df6a7ed2`、参考`18f0bbed2236d76b`中，D标签在孤立M1上；提取声明`d`但MOS只接内部`a_430_320#`，netgen有`disconnected node: d`而仍报匹配。因此原三字段是必要条件，T2b还须补查外部端口使用，不能只据绿色LVS验收该快照。

**已执行（2026-11-11）**：生成脚本里删掉孤立 m1 岛，`d` 标签移到两管之间的共漏 m1 条（`x=2.575, y=4.6`），重建后原检查器仍为 `DRC_TOTAL 0` / `LVS_MATCH True` / `LVS_PROPERTY_ERRORS False`（退出码 0），`inverter_audit.py analog/common/layout_practice/inv_std2_lvs.spice --cell inv_std2` 返回 `status: pass`；保持 W4/W8、L0.15、nf2 及参考不变。该审计仅用于平坦反相器，非通用LVS替代。

[DS-02复核单](training/DS-02-folding-review.md)与[折指/中间G/加宽M1/保护环VAR](inverter_folding_var.md)已有独立教学副本。后者DRC/LVS和外部端口均通过；没有覆盖或合入执行者当前的生产草稿。这里的结论只指上述捕获身份，后来修订需按新提取结果复核。

## 修复版独立复核（Codex，2026-11-12）

已捕获inv_std2/3当前.mag、参考和构建器到隔离副本，重跑完整DRC、提取、LVS及四端/总宽审计，均通过；执行者目录没有改写。inv_std2构建器SHA前缀`736f8f6e97b698f4`，inv_std3为`92da1979231a269d`，完整身份和日志见[复核数据](../data/layout_inverter_producer_review.json)。两者W4/W8、L0.15和真实D端口均正确；显式栅侧C由0.80203→0.59616fF，D侧由1.34614→1.50302fF，与当前README一致。该表不含MOS内部结/重叠电容，也未验证延迟/电流容量。

下一阶段沿用T3/T4参考与敏感节点预算；小阻值实现由设计侧另行规划。[固定宽负载卡](../design/fixed_load_resistors.md)中的50/120/240Ω并联方案仍未采用，不要自行替换T3的400/600Ω器件或更新参考网表。
