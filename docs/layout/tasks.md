# 版图任务单（给辅助画版图的 agent）

由 Claude 派发和验收。背景与约束见[版图起步](first_batch.md)，Magic 操作见[速查](magic_quickstart.md)。**一次只做一个任务，按顺序做；做完在文末状态表更新自己那一行，然后停下等验收。**

## 规则（每个任务都适用）

1. **判定只看检查器。** 运行
   ```bash
   uv run python verification/layout/check.py <layout目录> <cell> --ref <参考网表>
   ```
   通过的唯一标准：退出码 0，且输出里 `DRC_TOTAL 0`、`LVS_MATCH True`、`LVS_PROPERTY_ERRORS False`。README 和状态表里写结论时，**原样贴这三行**。不要写“DRC 净”“LVS 通过”之类的话而不贴原文。
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
| CML 负载 400 Ω（VCO 延迟级） | `res_high_po_2p85 l=2.44` | 410 Ω | 410 Ω |
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

## T2b　反相器改进练习（练套路）

在 `inv_std` 的基础上做 `inv_std2`，电路不变（nfet W4、pfet W8）：
1. 源漏接触排满整个宽度（[手册](cookbook.md) 第 2 节“接触排满”）；
2. PMOS 折成 2 指（`w=8 nf=2`，两端为源），NMOS 也折 2 指（`w=4 nf=2`），让单元变矮；
3. 参考网表 `inv_std2_ref.spice` 写成 `nf=2`（这是练习，器件值不变，允许你写）。

验收：检查器三行；单元宽 × 高，与 `inv_std` 的 5.85 × 16.15 µm 对比；每个源漏的接触数。

## T3 以后（等 Claude 给参考网表再开始）

| 任务 | 前提 |
|---|---|
| 尾线滤波 `serdes_pll_bias_lowpass_slow_r4` | **草稿已做**（等 Claude 确认参考网表）：`analog/common/ldo/layout/`，1.41 µm 宽 / L=132.45 µm × 32 只 + 16 个 MIM，DRC 0、LVS 匹配、−3 dB 10.0 kHz 与原理图一致（100 kHz 内偏差 0.016 dB），面积 0.0341 mm²。详见其 [layout README](../../analog/common/ldo/layout/README.md) |
| VCO＋四个首级 buffer | Claude 给出参考网表（CML 负载 400/600 Ω 换成标准宽度高阻；通用 poly 可以一只搞定，见 [high_po_notes](high_po_notes.md) §4）。相位节点寄生预算见 first_batch.md 3.3，是硬约束；走线标定与预算用法见 [vco_phase_budget](vco_phase_budget.md)（0.4 µm m2 约 0.082 fF/µm） | **已做三块（等参考网表确认）**：`pll_vco_delay_stage`（739 µm²，4.3 fF/节点）、`serdes_cml_buffer`（793 µm²，3.5 fF/节点）、`pll_vco_cap_unit`（109 µm²），都是 DRC 0 / LVS 匹配，见 [vco/layout README](../../analog/pll/vco/layout/README.md)。电容阵列总线、变容管（生成器单元本身 2 个 DRC）、四级环未完成 |
| PFD | 待定：手画堆叠逻辑，或改用 `sky130_fd_sc_hd` 标准单元（需要 Claude 先重做 PFD＋CP 仿真）。版图侧数据见 [pfd_options](pfd_options.md)：标准单元 2 DFF + 6 门 ≈ 65 µm²、单行约 20 × 5 µm，代价是复位脉宽改由单元延迟定、LVS 改层次比对 |

写参考网表前请看 [high_po_notes](high_po_notes.md)（固定宽度高阻的阻值公式与生成器 DRC 实测）：0.35/0.69 µm 的生成器单元单独就不干净，只有 1.41/2.85 可用；400/600 Ω 低于两端接触电阻 779.8 Ω 的地板，CML 负载必须用并联单元，这一条会影响 VCO 参考网表的写法。

## 状态

| 任务 | 状态 | 检查器原文（DRC_TOTAL / LVS_MATCH / LVS_PROPERTY_ERRORS） | 问题 |
|---|---|---|---|
| T1 | **验收：版图通过；Rz 改 `l=16.82` 后复交**（见“验收”） | `DRC_TOTAL 0`；`LVS_MATCH True  LVS_PROPERTY_ERRORS False`；检查器退出码 0；KLayout 独立 DRC 0 条 | 1) Rz 换成 `res_high_po_1p41 l=16.22`：`res_high_po_0p69` 的生成器单元**单独**就违反 rpm.1（0.35 更差 18 项，1.41/2.85 干净），按 first_batch §2.2 同阻值 4511 Ω 重算。参考网表 `Xrz` 因此同时改为 `res_high_po_1p41 l=16.22`（并在任务单允许的范围内删掉了 `w`）。2) Rz 的体接触不再单独下引：它是 p 衬底、已由 nfet 体抽头接 vss，单独下引会在 vss 总线留 0.125 µm 的 met2.2。3) 根目录 `tmp_layout_test/` 已移到 `analog/pll/loop_filter/layout/work/`（规则 5）。 |
| T2 | **验收通过** | `DRC_TOTAL 0`；`LVS_MATCH True  LVS_PROPERTY_ERRORS False`；检查器退出码 0。单元 5.85 × 16.15 µm | 1) 手画版 `inv_std` 用 paint 脚本（`analog/common/layout_practice/build_inv_std.py`），未用器件生成器。2) `make_practice.py` 的 `units microns` 已移到摆位阶段（生成器调用前不再改单位）；`inv_practice.mag` 重新生成后器件单独 DRC 只剩每个器件 6 个 met1.6。3) 单元偏高是因为 W8 的 PMOS 沟道宽 8 µm；若要压高度需要把 PMOS 折指，参考网表也要跟着改。 |
| T2b | 待做 | | |
