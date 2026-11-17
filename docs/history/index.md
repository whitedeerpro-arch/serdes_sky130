# 实验记录（历史）

- [旧版图总览与生成链清退（2026-11-17）](legacy_layout_retirement_20261117.md)：失效图表、生成脚本和 LDO/Bias 原交付声明的证据、依赖边界与追溯方式。

- [仓库文件维护（2026-11-17）](repository_maintenance_20261117.md)：运行产物归档、失效草案退役、共享资源去重、导航与可复现路径维护，不改变电路采用或验收资格。

- [工作流与文档整理（2026-11-13）](workflow_reorganization_20261113.md)：入口职责、执行里程碑、完整旧计划/状态/协作日志快照及核对范围。当前项目采用/验证看[current.md](../status/current.md)，工程任务看[执行计划](../status/prelayout_plan.md)。

- [VCO共同码三温覆盖补齐](vco_fixed_code_coverage.md)：12点补测将原42组补为45组静态可达，阵列未增位，闭环和动态接管另行验证。

- [末级建立时间与选择时钟改进](tx_final_retime_characterization.md)：原样校准→时移→实际缓冲→完整TT/FS眼图回归；保留数值失败和局限。

- [字入口接完整TX与控制时序](tx_parallel_integration.md)：TT通过，FS热角失败集中半字边界；guard映射SS时序不足，给出下一次局部观测节点与固定激励。

- [r5时钟前端冷角分层诊断](pll_cold_convergence.md)：FF/1.95V/−40°C的ll/hh，偏置就绪初值下四支路原生功能检查；DC仍开，初值边界与失败对照均保留。

这里保存按时间写下的实验与评估记录。10-27 至 10-30 的原始记录迁入时保持正文原样，只修正了相对链接；后续评估继续按日期追加。当前设计以 [design](../design/) 下的文档为准；这些记录保留测试边界、失败对照和中间推理，需要细节时再读。

最新：[时钟链路补图与原生结果恢复（11-06）](clocking_progress_20261106.md)，含 7 组图、r5＋TX v3 的 8 个完整静态工况、测量修复及续跑入口。

注意：

- `docs/data/*.json` 和各 campaign 中的证据清单记录的是**移动前的路径**（`docs/<name>.md`），作为历史哈希证据保持不变。按文件名在本目录查找即可。
- 正文中的"当前""最新""冻结"等说法以写作当天为准，可能已经过时。冲突处理见 [待解决问题](../status/open_issues.md#文档整理时发现的冲突已按最新记录处理)。

| 日期 | 记录 | 一句话结论 | 现行文档 / 状态 |
|---|---|---|---|
| 11-06 | [design_coupling_review_20261106.md](design_coupling_review_20261106.md) | 三批设计结论：RX ÷2/TX 时序优先，VCO 相邻码核验，PLL/bias 耦合与约束口径 | [VCO](../design/pll_vco.md)、[PLL 环路](../design/pll_loop.md)、[RX](../design/rx_pi_sampler.md) |
| 11-05 | [workflow_review_20261105.md](workflow_review_20261105.md) | MC 内存实测、读出扫描收敛成本、共同续跑与输入身份、分层架构改进顺序 | [统计方法](../verification/statistics.md)、[验证方法](../verification/methods.md) |
| 10-27 | [verification.md](verification.md) | 分层测试、结果路径、执行与判定分离 | [verification/methods](../verification/methods.md) |
| 10-27 | [architecture.md](architecture.md) | 电路层次、目录所有权、接口草案 | [overview/architecture](../overview/architecture.md) |
| 10-27 | [serdes_clock_plan.md](serdes_clock_plan.md) | 4 Gb/s 目标、2:1 × 4 串化分配、四级环振方案 | [overview/architecture](../overview/architecture.md) |
| 10-27 | [vco_ring4_first_results.md](vco_ring4_first_results.md) | 环振首版 TT 2.008 GHz、415 mVpp；八相顺序；变容管 Q 低 | [design/pll_vco](../design/pll_vco.md) |
| 10-27 | [cml_clock_receiver_results.md](cml_clock_receiver_results.md) | 带状态恢复的 CML→CMOS 时钟接收器，1.8 V 五个 MOS 角正常 | [design/clock_receiver](../design/clock_receiver.md) |
| 10-27 | [cml_divider_results.md](cml_divider_results.md) | 早期全 CML 二进制链与 1–16 整数反馈原型 | 已被 [design/pll_divider](../design/pll_divider.md) 取代 |
| 10-27 | [hybrid_divider_results.md](hybrid_divider_results.md) | CML ÷8 后接 250 MHz CMOS 分频；该位置后被修正 | 历史 |
| 10-27 | [pfd_cmos_results.md](pfd_cmos_results.md) | 静态 CMOS PFD，250/500 MHz 接口正常 | [design/pll_loop](../design/pll_loop.md) |
| 10-27 | [pfd_cp_lf_results.md](pfd_cp_lf_results.md) | 50 µA CP、二阶 LF；PFD+CP 电荷单调，零相差 +0.033 fC | [design/pll_loop](../design/pll_loop.md) |
| 10-27 | [pll_first_debug.md](pll_first_debug.md) | 混合视图捕获约 0.8–1.0 µs；原生抽出与三路供电 dummy | [design/pll_loop](../design/pll_loop.md) |
| 10-27 | [pll_precharge_capture.md](pll_precharge_capture.md) | LF 冷态预充约 2.67 µs；带载 Kvco 464.55 MHz/V；预充后原生捕获 | [design/pll_loop](../design/pll_loop.md) |
| 10-27 | [serializer16_first_results.md](serializer16_first_results.md) | 16:1 CML 串化树首轮，理想时钟下零错误 | 已被 [design/tx_serializer](../design/tx_serializer.md) 取代 |
| 10-28 | [clock_domain_clarification.md](clock_domain_clarification.md) | 自由 CMOS 分频接多相 CML 转换后的 2 GHz 时钟，不在 ÷8 之后 | [overview/architecture](../overview/architecture.md) |
| 10-28 | [vco_coarse_calibration.md](vco_coarse_calibration.md) | 相邻码重叠要求、逐次 ±1 搜索、温度计译码 | [design/pll_vco](../design/pll_vco.md) |
| 10-28 | [cmos_select_trial.md](cmos_select_trial.md) | 理想 CMOS 选择未优于 CML 选择，方向停止 | 历史 |
| 10-28 | [pll_clock_replay_results.md](pll_clock_replay_results.md) | 冻结 PLL 抽头电压回放驱动串化器，1024 bit 零错误 | 已被实际分发取代 |
| 10-28 | [physical_clock_distribution_results.md](physical_clock_distribution_results.md) | 原生 PLL + 实际 CML 分发，1024 bit 零错误，散布 0.162 UI | [design/tx_clock_distribution](../design/tx_clock_distribution.md) |
| 10-28 | [clock_overlay_results.md](clock_overlay_results.md) | 2 GHz 时钟过零散布约 0.0074 UI，远小于数据散布 0.162 UI | 诊断，仍有效 |
| 10-28 | [pll_multiphase_clock_overlay.md](pll_multiphase_clock_overlay.md) | 多相时钟 250 ps 时基套叠（仅绘图） | 历史 |
| 10-28 | [eye_fold_ui_sweep.md](eye_fold_ui_sweep.md) | 眼图折叠 UI 微调（仅绘图） | 历史 |
| 10-28 | [serializer_timing_root_cause.md](serializer_timing_root_cause.md) | 数据散布根因：末级锁存器跟踪/恢复与上游到达耦合；分频间隔不等距来自抽出极性 | [design/tx_serializer](../design/tx_serializer.md) |
| 10-28 | [pll_tracking_assessment.md](pll_tracking_assessment.md) | 线性模型 UGB 2.86 MHz、PM 65°；带宽与稳定时间的区别 | [design/pll_loop](../design/pll_loop.md) |
| 10-28 | [pll_startup_optimization.md](pll_startup_optimization.md) | 双节点预充 LF 建立约快 14 倍；启动监督 RTL | [design/pll_loop](../design/pll_loop.md) |
| 10-28 | [design_freeze_v0p1.md](design_freeze_v0p1.md) | v0.1 冻结清单 | [overview/revisions](../overview/revisions.md) |
| 10-28 | [tx_output_stage_and_link_plan.md](tx_output_stage_and_link_plan.md) | 8 mA 源端端接输出级；FFE/RX/编码路线 | [design/tx_output_driver](../design/tx_output_driver.md) |
| 10-28 | [pcb_channel_family.md](pcb_channel_family.md) | 合成 PCB 族 C0–C5，C2 为设计起点 | [design/channel_model](../design/channel_model.md) |
| 10-28 | [tx_pcb_channel_integration.md](tx_pcb_channel_integration.md) | 真实 TX 接 C2 后眼高降约 59%，峰峰值只降约 7% | [design/channel_model](../design/channel_model.md) |
| 10-28 | [rx_frontend_first_design.md](rx_frontend_first_design.md) | 端接 + 四档 CTLE，C2 回放 EQ11 眼高 351 mV | [design/rx_frontend](../design/rx_frontend.md) |
| 10-28 | [rx_loaded_link.md](rx_loaded_link.md) | TX 隔离 buffer 之后全真实电路联调，截断误差 < 0.1 mV | [design/rx_frontend](../design/rx_frontend.md) |
| 10-28 | [rx_pi_first_design.md](rx_pi_first_design.md) | 64 码 PI，DNL ±0.13 LSB，回卷无毛刺 | [design/rx_pi_sampler](../design/rx_pi_sampler.md) |
| 10-29 | [rx_cdr_architecture.md](rx_cdr_architecture.md) | 共享 PLL + 每路 PI-CDR | [overview/architecture](../overview/architecture.md) |
| 10-29 | [rx_sampler_control.md](rx_sampler_control.md) | 四相 CML 采样、PI 交接与投票 RTL | [design/rx_pi_sampler](../design/rx_pi_sampler.md) |
| 10-29 | [rx_cdr_closed_loop.md](rx_cdr_closed_loop.md) | RTL CDR 10 组 100 µs 零错字；CMOS 读出与 pair 对齐；解串 | [design/rx_cdr_digital](../design/rx_cdr_digital.md) |
| 10-29 | [mixed_signal_cosim.md](mixed_signal_cosim.md) | Verilator ↔ ngspice 实时闭环 192 UI，5 字无误 | [design/rx_cdr_digital](../design/rx_cdr_digital.md) |
| 10-29 | [rx_cml_word_capture_plan.md](rx_cml_word_capture_plan.md) | CML 移位 + 整字保持 bank 的结构讨论 | 待实现（I-15） |
| 10-29 | [stage_review_20261029.md](stage_review_20261029.md) | 分层功能原型阶段收束；GTKWave 查看；结果归档 4.19 → 1.24 GB | 波形查看与归档说明仍有效 |
| 10-29 | [figure_organization.md](figure_organization.md) | 图按模块/专题搬迁的规则 | 图索引见 [figures/README](../figures/README.md) |
| 10-29 | [schematics.md](schematics.md) | 29 页 Xschem 原理图（历史导出，未同步 r2/r3） | 原理图入口 |
| 10-29 | [pvt_noise_plan.md](pvt_noise_plan.md) | 先 PVT 功能筛查再相噪；45 条件矩阵与 pilot | [overview/spec](../overview/spec.md)、[verification/pvt_coverage](../verification/pvt_coverage.md)；开头状态已过时 |
| 10-29 | [pll_pvt_first_results.md](pll_pvt_first_results.md) | 9 个 pilot；SF 覆盖与 SS 热角读出缺口；物理 poly/MIM LF | [design/pll_loop](../design/pll_loop.md)；部分被 r2/r3 取代 |
| 10-29 | [pll_pvt_refinement.md](pll_pvt_refinement.md) | VCO 电容加大、接收器前级加宽（成为 r3 的 VCO/接收器） | [design/pll_vco](../design/pll_vco.md)、[design/clock_receiver](../design/clock_receiver.md) |
| 10-29 | [cml_divider_ss_diagnosis.md](cml_divider_ss_diagnosis.md) | SS 分频失效根因是尾管压差；低过驱动宽尾管恢复 | [design/pll_divider](../design/pll_divider.md) |
| 10-29 | [pll_lowov_pvt.md](pll_lowov_pvt.md) | PLL r2：分频/反馈 45/45，全速 CMOS 44/45 | 已被 r3 取代 |
| 10-29 | [cml_latch_topology_review.md](cml_latch_topology_review.md) | 锁存器失效机制与文献结构调研 | [design/pll_divider](../design/pll_divider.md) |
| 10-29 | [cml_latch_topology_experiments.md](cml_latch_topology_experiments.md) | 结构探索：保留静态 CML，加级间 buffer | [design/pll_divider](../design/pll_divider.md) |
| 10-29 | [serdes_bias_inventory.md](serdes_bias_inventory.md) | buffer 增幅不增余量；偏置清单；需要主参考 | [design/bias](../design/bias.md) |
| 10-30 | [pll_buffered_pvt.md](pll_buffered_pvt.md) | PLL r3：级间 buffer，45 条件分频/反馈正确，原生 4 工况约 2 GHz | 当前修订证据 |
| 10-30 | [pll_pfd_cp_lf_next.md](pll_pfd_cp_lf_next.md) | CP 高 Vctrl 处上拉不足；PFD/CP/LF 推进顺序 | [design/pll_loop](../design/pll_loop.md) |
| 10-30 | [divider_size_and_clock_priority.md](divider_size_and_clock_priority.md) | r3 栅面积 693 µm²/链；全速 CMOS 对 PLL 可暂缓、RX 仍依赖 | [design/pll_divider](../design/pll_divider.md) |
| 10-30 | [pll_loop_pvt.md](pll_loop_pvt.md) | CP/PFD 45 条件；4 工况 × 3 初值分层闭环锁定 | 当前修订证据 |
| 10-30 | [tx_pvt.md](tx_pvt.md) | v0.1 TX 45 条件：串化器草案 36/45；尾管余量与使能接管问题 | 已被 TX r2 取代；定位证据仍有效 |
| 10-30 | [tx_clock_phase_audit.md](tx_clock_phase_audit.md) | r3 时钟下 TX 抽头相位改变，1 GHz 差约 2 UI | [design/tx_clock_distribution](../design/tx_clock_distribution.md) |
| 10-30 | [tx_optimization.md](tx_optimization.md) | TX r2：草案 36/45 → 45/45，输出级启动 45/45（脚本生成的报告） | 当前修订证据 |
| 10-31 | [tx_single_chain_clock_exploration.md](tx_single_chain_clock_exploration.md) | 单链 + VCO 相位打拍可消除分频状态不确定，但状态错误本身只造成位重排，故未采用；记录打拍器尺寸、负载、竞争与大 trim 的教训 | 探索，未采用 |
| 11-05 | [i05_phase_noise.md](i05_phase_noise.md) | ISF + 线性 PLL + CDR 模型；VCO 节点损耗是低摆幅主因，r5 候选后 k = 4 时余量约 0.41 UI；LF 电容约 0.7 : 0.3 分接 VDD 和地 | [spec](../overview/spec.md#抖动与相位噪声预算)、[design/pll_vco](../design/pll_vco.md) |
