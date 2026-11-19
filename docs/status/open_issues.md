# 问题登记与关闭条件

编号稳定，关闭时保留结论、日期和证据。**本表记录设计风险，不是执行队列**；优先级和领取顺序只看[执行计划](prelayout_plan.md)，采用与验证数字只看[current.md](current.md)。旧P2/P3/P4/P5是历史阶段分类，不再与本轮M里程碑混用。

本次整理前的详细复述、旧阶段与冲突表保留在[历史快照](../history/open_issues_snapshot_20261113.md)。局部通过、功能失败、数值未完成、未测按原边界保留；此处没有把已验证单元整体重新打开。

## 原生PLL与TX主线

| 编号 | 未关闭的问题 / 关闭条件 | 证据与模块入口 |
|---|---|---|
| I-01 | 当前v3的字/时钟共同纪元、guard/blank及复位启动协议。旧r2启动置换解法按历史保留，不列为当前路径必经项 | [时钟分发](../design/tx_clock_distribution.md)、[字捕获](../design/tx_word_capture.md) |
| I-07 | 当前锁定PLL驱动完整TX动态数据与源/负载差异。按同deck动态、眼图、位映射和实际加载证明；已有r5开环静态及回放不重新记为未做 | [时钟分发](../design/tx_clock_distribution.md)、[源边界](current.md#3-tx-被什么时钟驱动过) |
| I-08 | r6 plant/PFD下的原生闭环、实际启动与控制接入。继承已有顶层/旧预充闭环，按新接口验证 | [环路](../design/pll_loop.md) |
| I-09 | r6工作图低频估计/内插的独立校准、当前噪声/失配和背景调码。逐温可达与跨三温共同码分开判定 | [VCO](../design/pll_vco.md)、[读取审计](../design/r6_map_audit.md) |
| I-12 | CP/门限联合失配尾部、实际ctrl−z纹波、比较/决策与VCO窗口联合余量。静态pilot不等于生产统计资格 | [CP窗口](../design/pll_cp_window.md)、[环路](../design/pll_loop.md) |
| I-13 | 实体LF与r6控制端导纳、电源分接、B2实际加载/捕获。保留已实现LF及旧闭环证据 | [环路](../design/pll_loop.md) |
| I-17 | 内部摆幅目标/上界适用性、换向/共模/器件余量、应力和时序。先模型和消费方需求；不只凭偏离400mV淘汰，也不以眼图通过关闭器件风险 | [幅度依据](../design/cml_swing_target.md)、[需求卡](../design/tx_retime_demand.md)、[尺寸约束](../design/tx_buffer_sizing.md) |
| I-19 | 已实现字入口的物理guard/标签/blank、建立保持与噪声失配。RTL波形回放不替代物理控制时序 | [完整入口](../design/tx_parallel_serializer.md)、[字捕获](../design/tx_word_capture.md) |
| I-32 | r6源/反馈/负载、物理寄生、码表/窗口、噪声与启动的一致性。新候选被采用前列明证据继承和失效边界；矩形bank融合/缩开关的局部Q与Con反例见[复核](../layout/capacitor_fusion.md) | [VCO](../design/pll_vco.md)、[环路](../design/pll_loop.md)、[PLL版图](../layout/pll_r6.md) |

## 共用边界、规格与物理风险

| 编号 | 未关闭的问题 / 关闭条件 | 证据与模块入口 |
|---|---|---|
| I-02 | 实体定宽R/MIM与通用PDK卡的角偏差/寄生/参考跟踪；按真实器件承接各模块，不能把已接真实无源重记为首次接入 | [固定负载](../design/fixed_load_resistors.md)、[宽电阻](../design/wide_load_planning.md)、[AC模型修正](../design/fixed_poly_ac_overlay.md) |
| I-03 | 实际vcm加载、参考ready、同时加载和共享扰动/去耦。带隙/分配已有，不能列为重新设计参考 | [Bias](../design/bias.md) |
| I-05 | 当前r6器件噪声/失配、实际参考/反馈/分发/供电路径与系统抖动预算。控制导纳已作TT局部校准；变容rg缺少热噪声标志已用局部副本修正，DC噪声/AC及短环振对照通过，仍需周期噪声折算与完整预算。旧r5模型不直接转移，MC不替代噪声 | [规格预算](../overview/spec.md#抖动与相位噪声预算)、[当前审计](../design/r6_lock_confirmation.md)、[VCO](../design/pll_vco.md) |
| I-06 | 当前采用链的长码型散布与剩余余量；旧r2长窗揭示的码型敏感度作为压力选择依据 | [串化器](../design/tx_serializer.md)、[末级重定时](../design/tx_final_retime.md) |
| I-10 | FS低压冷分频尾管饱和余量及可能的低堆叠结构对照；功能正常不能代替余量依据 | [分频器](../design/pll_divider.md) |
| I-11 | 高压CMOS过冲的逐器件端电压/应力；按实际接收器版本核对 | [接收器](../design/clock_receiver.md) |
| I-18 | 当前5bit VCO码与4bit门限梯的实际驱动、译码动态、停止/切码与跨供电域时序；RTL回归不替代物理接口 | [粗码窗口](../design/pll_coarse_windows.md)、[数字PLL](../../digital/pll/README.md) |
| I-20 | 远端或CTLE后的链路门槛与目标信道定义。现有串化器/焊盘门槛保持；远端比较量不自动通过或推翻它们 | [信道](../design/channel_model.md)、[规格](../overview/spec.md) |
| I-21 | ready→预充/粗搜→捕获→训练的实际从零启动，含停钟/越界/超时恢复 | [环路](../design/pll_loop.md)、[监测](../design/monitor.md) |
| I-27 | 当前内部ISI/带宽与末级下垂，优化须同时保持时序和器件余量，避免独立缩R | [串化器](../design/tx_serializer.md)、[需求卡](../design/tx_retime_demand.md) |
| I-29 | 真实焊盘/ESD/封装、电源/回流、供电抑制及使能/AC耦合状态；FFE为未采用扩展 | [输出级](../design/tx_output_driver.md)、[耦合状态](../design/tx_coupling_state.md)、[物理负载](../design/tx_physical_load_card.md) |
| I-31 | 既有边界登记/负载签名/默认冒烟已建立；剩余旧脚本的显式身份和变体接入。不得用“最新一次”寻找生产边界 | [边界管理](../verification/methods.md#边界条件管理) |
| I-35 | 单PLL/相对双PLL、峰值/峰峰值、CDR前后供电抖动口径，以及实际参考/偏置/环外路径的相关性与动态校准；LDO减容候选承接实际PLL负载/快卸载与相关噪声预算 | [定时与供电复核](../design/pll_timing_supply_review.md)、[预算口径](../design/pll_ripple_budget.md)、[TX时序筛选](../design/tx_relative_timing_screen.md)、[LDO减容](../design/ldo_smallcap.md) |

## RX与宿主接口（后续释放）

本轮维持已有RX边界，后续按计划M5逐项释放；这是执行排序，不减少最终交付义务。

| 编号 | 未关闭的问题 / 关闭条件 | 证据与模块入口 |
|---|---|---|
| I-14 | 当前W40真实偏置/RC读出网格、实际失配两边沿校准、生产CDR动态及原生锚点；旧mutable include资格不转移 | [PI/采样](../design/rx_pi_sampler.md)、[冷角](../design/rx_cold_convergence.md) |
| I-15 | 已实现deser16及map→align→FIFO的物理cosim、频偏容量/溢出/重训恢复、实际时序与CDC | [RX数字](../design/rx_cdr_digital.md)、[宿主CDC](../design/rx_host_cdc.md) |
| I-16 | 宿主HD映射后SS时序、CDR/校准工艺时序与物理CDC。已有映射/TT时序不重记为完全未做 | [宿主字时序](../design/rx_word_host_timing.md)、[RX数字](../design/rx_cdr_digital.md) |
| I-23 | 读出后鉴相零点、孔径偏移与控制路径延迟的校准 | [PI/采样](../design/rx_pi_sampler.md) |
| I-28 | CTLE实际vcm/端接加载与启动、真实偏置/RC下增益/零极点、目标信道与档位策略；是否CMFB由余量决定 | [前端](../design/rx_frontend.md)、[Bias](../design/bias.md) |
| I-30 | 原生PLL多相锚点、PI输入间距/斜率/负载与共享扇出；理想相关源不代表原生源 | [PI/采样](../design/rx_pi_sampler.md) |
| I-33 | 当前W40全网格、原生锚点/动态和真实启动；保留冷角软DC短窗恢复与原W80失败的各自边界 | [冷角](../design/rx_cold_convergence.md)、[PI/采样](../design/rx_pi_sampler.md) |

## 历史修复与维护项

| 编号 | 状态与处置 | 证据 |
|---|---|---|
| I-04 | 已解决，2026-10-31：r4修复全速接收SS冷角上拉/翻转；热角余量与高压应力分别留在I-11及接收器文档 | [接收器](../design/clock_receiver.md#r4全速-ss-冷角修复2026-10-31) |
| I-34 | 已解决，2026-11-09：公共冒烟逐段截短tran并检查每个声明输出存在/非空，保留单/多段与缺失输出回归 | [spice.py](../../src/serdes_flow/spice.py)、[回归](../../tests/test_spice_smoke.py) |
| I-22 | 维护项：Xschem为历史导出；交付原理图须同步采用网表，不能以旧截图定尺寸 | [原理图记录](../history/schematics.md) |
| I-24 | 维护项：旧前端注释含迁移前文档路径；历史发布快照保持原样，新改代码时修正适用注释 | [旧记录](../history/open_issues_snapshot_20261113.md) |

## 文档整理时发现的冲突（已按最新记录处理）

原冲突表保留在[整理前快照](../history/open_issues_snapshot_20261113.md)。本次重点纠正4bit目标与r6/5bit主线、旧分频短窗疑点与带辅助启动结果、固定2+2名额与全机统一调度、数字未映射与已有宿主映射证据的混用。历史中的“当前”只指写作时，不覆盖current.md；本次核对范围见[整理记录](../history/workflow_reorganization_20261113.md)。
