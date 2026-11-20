# 当前状态（唯一入口）

**这一页是项目级采用状态和验证数字的唯一汇总。** README、模块地图、计划和工作台引用本页；模块设计文档保留详细结论与实际边界，工作修订保留机器参数和历史身份。规则见[架构决定](architecture_decisions.md)第10条与[文档职责](../README.md)。采用候选前先更新模块证据，接受后同步本页；执行队列见[计划](prelayout_plan.md)。

基准组合：本地标签 `baseline-prelayout-20261113`（PLL r6、TX v3/extra5＋当前驱动、RX ac_trim/c2/W40＋宿主字路径、Bias/B2、HV18 r4）。更新于 2026-11-13。

## 1. 一句话状态

已有模块结果在**各自的边界**上满足相应门槛，仍有局部缺口；当前尚缺**锁定PLL驱动当前完整TX动态数据**的同deck证据。TX已有理想2GHz源下45/45，原生VCO源的静态计数与录波回放另列。下一阶段按执行计划把这几段在同一个deck里接起来，第4节报告证据就绪情况。

## 2. 模块

“驱动/边界”一栏写的是这条证据**实际**用了什么输入，读数时以它为准。模块名链接设计/实现来源；固定数据和运行身份沿来源文档追溯。表中未测不等于功能失败，局部通过不等于该模块所有场景通过。

| 模块 | 当前修订 | 驱动 / 边界 | 结果 | 没覆盖的 |
|---|---|---|---|---|
| [VCO](../design/pll_vco.md) | r6：5 bit/31 个 2×2 µm 半单元（含版图寄生）、每节点 12 fF 连线余量、负载 2×`2p85 l=4.77`、尾 W25.2、变容 4×5.2 | 开环、真实偏置、定宽电阻卡，ring＋4 buffer，135 条件（45×tt/hh/ll） | 量程两端最差 +8.2%（FS 1.65 V 85 °C hh）/ +8.6%（SF 1.65 V −40 °C ll）；窗口内可用码 ≥ 2（中位 4）；窗口/LSB ≥ 2.25；Kvco 242–1025 MHz/V；摆幅 349–562 mVpp；45 组MOS/VDD/RC条件中36组有一个码覆盖 −40…85 °C | 闭环压力角；相噪/失配资格（已有TT八样本频散初筛，r5 的数不转移）；模型锁点抽检 |
| [÷8 预分频＋反馈接收](../design/pll_divider.md) | r3 结构，首级保持 W40、后级 W80 | 理想 2 GHz 输入，真实偏置，hh/ll 各 45；6 压力点 MC；r6 前端 FS 1.65 V 85 °C hh 1.95–2.18 GHz | 全部正确分频；MC 1048 样本，摆幅均值−kσ 最低 188 mV；r6 量程顶端 2.18 GHz 正确 ÷8，÷8 输出 429 mVpp | FF 冷失配工作点不收敛 |
| [时钟前端](../../analog/pll/top/tb/frontend_r6/run.py) | r6q：去掉 4 个全速 CMOS 接收器，支路 1–3 换成只含输入级的轻 dummy | 开环、同一电源，5 个角对比完整 dummy | 宿主电流 23–35 → 4.8–8.2 mA；VCO 八相偏差两者都 ±0.02 ps | buffer 输出相位差 1–5 ps（dummy 偏轻，配重校准待跑） |
| [PFD](../design/pll_loop.md) | 标准单元 `pll_pfd_sc_dly`（复位环路多一级 `dlygate4sd1_1`） | PFD＋转向 CP，近零相位扫描 | 无死区；失配 MC SF/SS 冷各 100 样本 0 卡死，静态相差上界 239/256 ps | 原生闭环 |
| [CP / LF](../design/pll_loop.md) | 转向 CP 200 µA（k=4）；LF Rz 4.13 kΩ、Ci 18 pF | CP：DC 135 点、MC 3×200；LF：行为 VCO 闭环 135 点锁定 | CP 净电荷 σ 1.7–1.9 fC | 按 r6 的 Kvco 242–1025 MHz/V 复核相位裕度（r5 设计用 286–1125） |
| [锁定检测](../design/pll_loop.md#锁定检测相位窗口2026-11-10) | `pll_phase_window` | 新 PFD 驱动，45 条件 | 门限 225–750 ps，45/45 单调；门限/静态相差上界 ≥ 2.7 | — |
| [PLL 闭环](../design/pll_loop.md) | `pll_core_r6k4q`（r6 前端＋新 PFD＋CP＋LF，quiet 域） | r6 TT/ext、码9、预充＋分频kick，800 ns完整。r5原生/HV18历史按原版本保留 | 末200 ns平均1.999999143 GHz（−0.43 ppm）；工程合同保持480 ns通过本TT点 | r6压力角/加载后持续锁定；实际参考路径与从零启动；[续做](../design/r6_lock_confirmation.md) |
| [PLL 供电](../design/ldo_r4.md) | HV18 r4（静态配置、6 bit 修调、尾线 1 MΩ/16 pF） | 本地 DC 1215 / AC 255 条 | 100 pF 端点最差 PM 65.07° | 宿主域定时路径（见参考输入）；从零启动、UVLO |
| [参考输入](../design/pll_timing_supply_review.md) | 未定 | 开环 Kd（宿主纹波 → 相位） | 理想互补副本残差 −0.06…−0.20 ps/mV；真实焊盘缓冲单端驱动最差 −0.90 ps/mV（FS 1.65 V −40 °C） | 互补驱动变体待跑；与 0.05 UI 预算的折算 |
| [TX 字入口＋分发＋串化＋驱动](../design/tx_final_retime.md) | v3/extra5，末级 WN32/WT16/R240，r2 树，预驱 120 Ω/尾 W60/输出 W192 | **理想 2 GHz 源**，真实偏置，通用 PDK R tt，256 bit | 45/45 过门槛；最差 FS 1.65 V 85 °C：串化器 103.1 mV / 0.115 UI，焊盘 136.0 mV / 0.138 UI | 原生时钟下的动态数据（第 3 节）；电阻角；内部幅度 I-17 |
| [RX](../design/rx_pi_sampler.md) | ac_trim/c2，PI 120 fF，deser16/W40，map→align→FIFO | 理想 PI 锚点、C2 信道；读出压力点 | 无读出窗口 135 条件最差 0.8125 UI；FS/FF 冷 hh 读出零错 | 原生锚点；真实失配下 SAR；SS 宿主时序；本轮不推进 |
| [偏置](../design/bias.md) | 带隙＋恒 I·R、5 bit 修调、本地拷贝、B2 | 135 条件上电 | 摆幅代理 407–426 mV；分配 MC 200×三温 | 系统级 ready/启动 |

## 3. TX 被什么时钟驱动过

| 时钟源 | 数据 | 覆盖 | 结论 | 证据 |
|---|---|---|---|---|
| 理想 2 GHz 源 | 动态，256 bit | 完整 TX，45 MOS 条件 | 45/45 | [tx_final_retime](../design/tx_final_retime.md) |
| r4 原生前端录波回放（VCO 开环、固定 Vctrl，抽头理想化后作 PWL 源） | 动态 | v3 分发＋串化器，15 个 V/T 点 | 15/15 按位序满足；FS 热散布 0.140 UI 最紧 | [tx_clock_distribution](../design/tx_clock_distribution.md) |
| r5 原生前端与 TX 同一 deck（VCO 开环、固定 Vctrl） | **静态** | v3 计数器＋串化器＋驱动，10 压力点 | 8 点连续计数；FF 1.95 V −40 °C hh/ll 未完成 | 同上，“r5 / 4 bit 原生联合仿真” |
| **锁定的PLL→当前完整TX组合** | 动态 | — | **尚无对应收录证据** | — |
| r6闭环→TX（捕获阶段，尚非持续锁定） | **静态全零** | TT/ext，120 ns探索接口卡 | 37次计数采样步进均正确；不计动态眼图或加载后持续锁定 | [续做](../design/r6_lock_confirmation.md) |

前三类实际时钟证据继续保留，不能笼统称为“TX没用过实际时钟”；它们也不证明当前完整组合已在锁定PLL下传输动态数据。回放不含TX输入对抽头的负载回馈，开环VCO不覆盖闭环调制/CP纹波，静态数据不提供动态眼图。历史中的“原生PLL＋TX”标题须回到实际deck确认开环/闭环与数据模式。

## 4. 主线证据就绪情况

| 计划节点 | 当前证据状态 | 来源 |
|---|---|---|
| M1前置：量程内反馈分频 | FS热hh在启动脉冲辅助下2.18GHz正确分频；不证明真实上电 | [前端台](../../analog/pll/top/tb/frontend_r6/run.py)、第5节 |
| M1：r6原生闭环 | TT/ext的800 ns完整，保持480 ns；本点工程锁定成立，可承接TT带载验证，压力角仍缺 | [续做](../design/r6_lock_confirmation.md)、[固定输入runner](../../analog/pll/top/tb/native_r6/campaign.py) |
| M2：锁定r6→完整动态TX | 已有r6静态短加载，动态同deck仍缺；已有不同源边界见第3节 | [TX分发](../design/tx_clock_distribution.md) |
| M3/M4：接口扩角与r6噪声统计 | 当前版对应原生接口/预算未闭合，未改单元局部结果按第2节边界继承 | [规格预算](../overview/spec.md)、[PLL环路](../design/pll_loop.md) |

先后顺序、最小实验、压力点、退出条件与暂缓范围统一在[执行计划](prelayout_plan.md)。本表只报告证据就绪情况。

## 5. 当前已知风险

- FS热hh短窗分频停滞已在带启动辅助的边界恢复（2026-11-13）：无噪声CML锁存器可能停在对称工作点10–20ns；加入20µA×40ps启动脉冲后，1.95–2.18GHz正确分频。[原生台](../../analog/pll/top/tb/native_r6/run.py)显式保留该辅助。这个结果解除该工作态短窗的分频疑点；实际复位/失配/噪声下的自启动仍须单独验证，不能由辅助脉冲证明从零上电。
- FF 1.95 V −40 °C 的完整前端工作点不收敛（精简前端正常）。
- TX 内部 CML 幅度超 400 mV 的适用性（I-17）未关闭。
- 版图：已完成 Gemini 40 份原稿全量审计并迁移 14 个叶单元（7 个 Bias/OTA、1 个 PLL 分频锁存器、5 个 PLL VCO r6 叶单元及 LDO MIM16/50/100 阵列）至 full-rule DRC 0、LVS 通过且端口完整导出的 PDK 原语版本；按层次版图截图（`docs/figures/layout/`）及无仿真基础寄生参数提取已整理，分布金属 RC 与宏级电气回灌尚待完成。[Gemini 迁移与寄生汇总](../layout/gemini_migration_summary.md)、[PLL r6 版图推进](../layout/pll_r6.md)、[版图入口](../../analog/layout/README.md)。
- PLL版图目标：按 `pll_core_r6k4q` 完成模拟核。半单元、四指变容器及31颗MIM/5 bit共底板候选均通过full-rule DRC/LVS/端口/器件数检查。共底板bank为51.07×18.61 µm，TT局部AC的32码单调。回灌开环ring＋四30fF buffer、真实偏置/定宽卡：按12fF连线预算分账的两端2.199/1.827 GHz；仅bank回灌、延迟级与buffer仍为原理图时，完整额外12fF压力下的FS热hh/码0与SF冷ll/码31在三档电源共6点均覆盖2 GHz，最小名义频率余量6.96%，未计局部随机失配；漂移满足原规则。此前2.17 fF及1.933 GHz等结论受Magic电容节点错移影响已撤回，原记录保留；两条工具导出路径已修复并补回归。候选尚缺全角窗口/切码动态/失配，原理图参数未改。[推进与边界](../layout/pll_r6.md)。

## 6. 其他模块与本次核对

- 2026-11-15电容融合：同bit/同节点的物理合并、实际9块矩形规划、开关宽度与Q/Coff/Con的局部复核见[记录](../layout/capacitor_fusion.md)。新增按实际选码分配Ron的等总宽局部对照：小位优先有慢角小码收益，但受SS/ll大码损耗约束，未采用。物理参考与映射独立生成，未更换采用原理图、版图或全角/噪声资格；规划图目标不能当成测量值。

- 2026-11-15 bank优化抽象：确定性工艺角与局部统计/校准分层、目标和ε预算、S/α旋钮见[研究](../design/vco_bank_optimization.md)。已有叶数据有限穷举560组；全开C保留98%且最小步长不低于原对照的研究切片有4个不劣点，给出31.5µm总宽候选；没有新环振、重新校准或MC资格，未采用参数。

- 2026-11-14 BG电容复核：共享参考保持13pF（6＋5＋2）；11pF/Cc4/Rz30k候选完成五边界×两负载AC，四段物理Rz核心PM最低64.23°；两方案共12次受检启动到达各自工作点，30条DC噪声谱偏置核对完成。TT分配夹具Vbg积分噪声约424→435µVrms，阶跃峰26→19mV；尚无面积收益或完整PVT/MC/PEX资格，未改采用参数。旧版图Rz四段端头使阻值较LVS合并长度高约6%，已作为具体支路反馈，非撤销旧模块功能结果。[设计与适用边界](../design/bias_cap_review.md)、[固定证据](../../results/catalog/bias_cap_review.json)。

- 2026-11-14 LDO减容：`b32_h2`本体70pF、核心50pF；1215DC/255AC全部满足既有局部规划门槛，输出1.775953–1.814801V、20MHz最差36.77dB、PM最小76.72°。核心full-rule DRC0/LVS/端口通过，面积0.087021→0.062096mm²（−28.64%），并有核心电容PEX压力点、三工况启动/噪声和人工阶跃记录。[减容设计](../design/ldo_smallcap.md)、[数据](../data/ldo_smallcap.json)。作为下一轮LDO版图候选，未接当前PLL；±4mA/1ns人工阶跃FS峰1.984V，不接受该快卸载边界，真实PLL负载/关断与宏PEX及抖动预算须承接；旧r4原生锁定仍按原修订保留。
- 2026-11-14 70pF失配首轮：完整PDK条件局部MC，TT/FS热ll各16颗，逐颗27°C选码后保码检查，DC及10mA AC均过本轮门槛；TT输出1.79725–1.80276V、FS热1.80240–1.81309V，最低PSRR36.63dB/PM75.89°。固定名义码分别仅8/16、12/16处于±2%，保留逐颗6位修调。首样本独立重跑标量/完整AC谱复现；仅小样本原理图初筛，非完整失配/良率资格，PNP与g5直接Vth随机模型盲点、全PVT/PEX/启动/实际PLL仍未覆盖。[方法与边界](../design/ldo_smallcap.md#局部失配首轮2026-11-14)、[身份索引](../../results/catalog/ldo_smallcap_mismatch.json)。

- 2026-11-14 LDO电容第二轮：8pF隔离栅PEX33.55dB失败；12pF的2×6核心DRC0/LVS通过，压力点35.06dB但当前包围面积未降。等值70pF叠层核心39,774.73µm²，较同代单层52,395.57µm²降24.1%；自身1215DC/255AC通过、6核心PEX点最低35.93dB/PM75.03°，三工况启动/噪声接近原70pF，MC TT/FS热各8颗经逐颗修调均过本轮门槛。外围1MΩ/16pF叠层物理候选6,226.62µm²（−39.8%），三组被动PEX小卡截止频率变化约0.1%。均未接实际PLL或替换当前采用宏；完整宏PEX/分布RC/噪声统计与原快卸载边界保留。[电容与面积](../design/ldo_cap_area.md)、[固定证据](../../results/catalog/ldo_cap_area.json)。

- Channel采用与待定链路门槛见[信道设计](../design/channel_model.md)，I-20仍开；现有远端比较值不等同串化器/焊盘门槛。
- RX宿主map→align→FIFO已有两种SKY130 HD映射/STA；优化后TT本域4ns满足，两个SS库角仍负裕量，库点不等于MOS45。见[宿主字时序](../design/rx_word_host_timing.md)。物理CDC、实际cosim与频偏容量政策仍开，本轮RX不扩任务。
- 本次TX数字核对：上述完整45点最差值采用[tx_full_pvt45.json](../data/tx_full_pvt45.json)的FS行serializer `margin_mv=103.137781…`；早期三压力点102.73mV保留在[原分析](../design/tx_final_retime.md)，两者不混用。

2026-11-13工作流整理只核对文档、配置/目录和既有小数据，未重跑仿真，也未重新签核本表的全部历史波形。工作修订中历史状态字段按对应修订解释，不反向覆盖本页；整理范围见[记录](../history/workflow_reorganization_20261113.md)。

## PLL 版图独立审阅（2026-11-15）

局部版图与电容 PEX 的范围及固定证据见 [审阅汇总](../layout/pll_review_20261115.md)：PFD 七个局部点、VCO 两个量程端点、÷8/反馈的 TT 与 FS 热角、LF 七个局部 AC/短预充点分别记录，不构成整核或全 PVT/噪声资格。浮空 field-poly 以独立候选清理，未切换采用电路参数。

÷8 全量原生 RC 的异常标注 `LAYOUT-PLL-DIV-RC-01`，**疑点待版图核查，该仿真分支暂停**；5744 个是离散寄生网段，实体 PDK 电阻为 16 个，提取语义和简化收敛未验证，不能直接判实际版图失败。完整 PLL 布线与可靠耦合 RC 尚未完成。LDO、Bias、CP 不在本次版图审阅范围。

[LF、divider、VCO 与 CML→CMOS 的阶段验收](../layout/pll_acceptance_20261115.md)接受六份局部几何交付；电气资格保持报告所列边界。错误大环及其依赖顶层规划已撤销，未切换电路工作修订。

2026-11-17 [待提交工作复核](../layout/pll_pending_review_20261117.md)：新版 LF 已重建并通过局部预充筛查；r4/r5 全速转换及 CMOS ÷8 为独立候选，未切换 PLL 采用参数。r5 冷角原生 RC 功能失败保持 changes requested，旧无源角标签与运行时 include 身份缺口已明确，旧三叠层 divider 全量 RC 继续暂停。

2026-11-20 候选迭代与仓库整理（均未切换现行采用工作修订）：
- **纯 CMOS / TSPC 2 GHz ÷8 预分频器候选（`pll_saff_reclock_prescaler8_2g` v7 + `v2` 交错版图）**：`1,705.31 µm²`，full-rule DRC=0 / Netgen LVS=MATCH / 0 浮空 poly；原理图 45/45 通过（max skew `12.14 ps`），宿主 `Kd` 较纹波 CMOS 降 `2.3–2.85×`；后仿 45 角 CPEX **45/45 功能通过、44/45 `< 30 ps`**（中位 `4.28 ps`，仅 `ss_v1650_t-40` 为 `45.61 ps`），双向原生 `RCX_BOTH` 5/5 通过；200 样本 CPEX MC 在 `fs_v1650_t85_mm` **200/200 通过**，在 `ss_v1650_t-40_mm` 为 `168/200` 正常分频（瓶颈定位到 `Xtg2` 极寒低压传输门死区）。见 [pll_tspc_reclock_divider.md](../design/pll_tspc_reclock_divider.md)。
- **PLL CP v3 与 LF v2 物理重构**：CP v3（`2,175.50 µm²`，−58.0%，ABBA 共质心、biased dummies、`out` CPEX −31.6%）与 LF v2（`6,382.27 µm²`，−7.4% vs v1 / −48.6% vs 18-MIM，开关与 `Rz` 复用 Col-1 VSS MIM 下方、`ctrl` CPEX −41.4%）均通过 full-rule DRC=0 / LVS=MATCH / RCX 器件保留检查；按 r6 `Kvco = 242–1025 MHz/V` 的解析环路相位裕度复核 TT 为 `58.1°–63.8°`（`UGB < fref/10`）。
- **历史版本清退**：按每设计家族仅保留现行及最近 2–3 个 Var 原则完成两批归档（v0.1–r4 73 个文件见 [legacy_vars_retirement_20261120.md](../history/legacy_vars_retirement_20261120.md)；分频器旧版与失败候选见 [divider_retirement_20261120.md](../history/divider_retirement_20261120.md)）。
