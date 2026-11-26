# 数字 v3.3 时序收口复核

2026-11-25。4 Gb/s 的 `full_v8` 实际仍导入 v3.2。v3.3 的旧布线在慢角缺建立时间。已改 RTL 的新一轮 `1.65 V` 布线仍在进行，现有结果支持继续收口。独立复核同时定位了两个问题，分别是慢角真实时序违例和 CDC 脚本调用失败。[full_v8 导入脚本](../../results/layout/chip_top_20261123/full_v8/_import_digital.tcl) · [项目状态](../status/current.md)

## 受查版本

| 修订 | 证据与状态 |
|---|---|
| v3.2 装配宏 | GDS `c67104a76bfa…`，原三角 18/18，SS 热 `+14.5 ps`。SDF 四模式功能过，严格结果保留 TT/SS 的 3/1 条复位时序提示。当前仍是装配基线。 [物理摘要](../../results/digital/pnr_v3p2_signoff_met/serdes_digital_top_v3/summary.json) · [GLS](../../results/digital/gls_v3_2_final/summary.json) |
| v3.3 首轮布线 | `pnr_v3p3_20261124` 已产出 DEF 和 SPEF。原收据含 SS 热 `−0.973 ns`、SS 冷 `−2.561 ns`，TT/两快角通过；当次 CDC 报错。候选交付目录为空。 [冷角 STA](../../results/digital/pnr_v3p3_20261124/serdes_digital_top_v3/03_sta_ss_n40C_1v60.log) · [CDC 报错](../../results/digital/pnr_v3p3_20261124/serdes_digital_top_v3/03b_cdc_audit.log) |
| v3.3 最新工作副本 | RTL 快照通过数字顶层四子系统、PLL 全码粗搜、CDR ±300 ppm、16×16 FIFO 异步压力台。`pnr_v3p3_1v65_20261125` 已到布局后时序修复，`POST_SETUP_WNS` 记录 CDR `+0.868 ns`、host `+0.115 ns`、RX 字域 `−0.193 ns`，须再看详细布线后的提取。 [布局中间日志](../../results/digital/pnr_v3p3_1v65_20261125/serdes_digital_top_v3/02a_openroad_setup.log) · [RTL 运行](../../results/digital/audit_v3p3_20261125_543NRK/rtl/) |
| Antigravity 路线 A 最终收据 | 已完成 7 轮布线后 ECO。1.65 V 插值冷角 `setup/hold=−1.140/+0.087 ns`。最差 `rx_offset[3]`，CDR `−0.218 ns`，host `−0.488 ns`。TT 及两快角通过，SS 热角 setup `−0.896 ns`。综合输出未晋级物理交付。 [路线 A 摘要](../../results/digital/pnr_v3p3_1v65_20261125/serdes_digital_top_v3/summary.json) |

## 同口径逐项回放

两组已布线 DEF 各绑定自己的 max/min SPEF 和 SDC，保持四个字时钟和生成时钟频率。分别切换 `rx_phys` 发射边、Liberty 电压温度与 early/late `0.95/1.05`。其余时序约束相同，保留各版 SDC 设计规则设定。安装的 OpenROAD `f12e2f4` 支持本次所用单工况 `read_spef -max/-min`，与原三角使用一份角点 SPEF 分析 setup/hold 的口径有差别。数字器件以本地电源为评估边界。[回放脚本与日志](../../results/digital/audit_v3p3_20261125_543NRK/sta_replay/) · [输入哈希](../../results/digital/audit_v3p3_20261125_543NRK/sta_inputs.sha256) · [OpenSTA 命令说明](https://openroad.readthedocs.io/en/latest/main/openroad/sta/doc/ChangeLog.html)

| SS 条件 | `rx_phys` 发射边 | OCV | v3.2 setup / hold WNS（ns） | 旧 v3.3 setup / hold WNS（ns） |
|---|---|---|---:|---:|
| 100 °C / 1.60 V | 上升 | 关闭 | −0.023 / +0.204 | −0.779 / −1.123 |
| −40 °C / 1.60 V | 下降 | ±5% | −1.962 / −0.144 | −2.614 / +0.034 |
| −40 °C / 1.65 V 插值 | 下降 | 关闭 | −0.754 / +0.030 | −1.052 / +0.221 |
| −40 °C / 1.65 V 插值 | 下降 | ±5% | −0.996 / −0.065 | −1.452 / +0.077 |

- 旧 v3.3 已补上 `j0/j0b` 所需的下降沿约束，最差 `rx_phys` 输入路径在 1.65 V 插值角、OCV 下有 `+1.160 ns` 建立裕量。v3.2 在同样发射沿下最差为 `−0.996 ns`。RX 引脚合同应按实际 `wclk` 占空比、数据边沿、RCX 与输入负载确认。[解串时钟源](../../analog/rx/cmos_rx/spice/rx_cmos_deser16.spice) · [v3.2 下降沿](../../results/digital/audit_v3p3_20261125_543NRK/sta_replay/v32_ss_n40C_1v65_interp_fall.log)
- 旧 v3.3 在该角的首要瓶颈是 CDR 125 MHz 域内 `_7261_ → _7143_`。启动 FF 出 Q 后约十级门，数据路径含 `clk→Q` 约 8.36 ns，尚要留 setup 和时钟余量。其次是 RX 字域的 `rx_offset[2]` (`−1.260 ns`) 和 host 域 (`−1.249 ns`)。去掉 OCV 后仍约差 1 ns。当前 1.65 V 库从标准三个电压点插值，本次用于定位和比较。签核前需确认关键路径主要单元的 slew/load、时序检查弧，以及扣掉局部 IR/纹波后的最低电压。[旧 v3.3 详细路径](../../results/digital/audit_v3p3_20261125_543NRK/sta_replay/v33_ss_n40C_1v65_interp_fall.log) · [插值工具](../../verification/unit_checks/interp_sky130_ss_n40c_1v65.py)
- 原 CDC 流程在 Gray 路径读取 `arrival` 时中止，早于后续 DRC/LVS/导出。针对旧 DEF 用 `report_checks` 对每一位明确指定起止点，并重查一级至二级。FIFO 跟踪到的 15 个一级同步器均单扇出。写到读、读到写的 `clk→Q + data path` 位间差约 33/307 ps，二级 setup 最小 `+2.393 ns`。结果限于该 FIFO、该布线和该角。最终版要在同一 DEF 上覆盖其他同步器、复位释放及有效 MTBF 边界。[CDC 独立回放](../../results/digital/audit_v3p3_20261125_543NRK/cdc_fifo_audit.log) · [当前审计流程](../../digital/pnr/run_v3p3_clean_pnr.py)

## 收口判断

新实现首轮布线的 1.65 V 插值冷角复放中，RX 差分解串进来的 `rx_phys` 最差 setup 为 +2.158 ns。实际剩余缺口为状态口 `rx_offset[0]` −1.447 ns、训练入口 −0.958 ns、CDR 内部 −0.794 ns、host setup −0.486 ns 和全局 hold −0.119 ns。状态口给两周期后，最差变成训练入口 −0.958 ns。状态口能否用两周期取决于接收方的数据稳定及采样协议。训练入口最差含三个修 hold 的延时门，单个慢角延迟约 1.28–1.36 ns。[首轮布线与 RC](../../results/digital/audit_v3p3_20261125_543NRK/latest_first_route/ss_n40C_1v65_interp_fall.log) · [逐路径对照](../../results/digital/audit_v3p3_20261125_543NRK/latest_first_route/paths/ss_n40C_1v65_interp_fall.log)

在相同 DEF、RC 和 ±5% OCV 下，固定 CDR `_7176_ → _7190_` 的 `clk→Q + 数据路径` 在 TT 1.80 V 25 °C 为 3.935 ns，SS 1.60 V 100 °C 为 7.530 ns，SS 1.65 V −40 °C 插值为 7.963 ns，SS 1.60 V −40 °C 为 8.957 ns。最后一项相对 TT 慢 2.28 倍，相对同工艺、同电压的热角慢 19%，相对 1.65 V 插值冷角慢 12.5%。SS 低温和低过驱动下的阈值上升足以压过迁移率改善。各路径的细胞、负载和时钟差异仍需分别检查。1.60 V 作为压降/裕量压力线，规格判定须绑定数字单元本地最低电压及所用库。[定点时间分解](../../results/digital/audit_v3p3_20261125_543NRK/latest_first_route/paths/) · [低压 CMOS 温度反转](https://ziyang.eecs.umich.edu/~dickrp/talp/papers/dasdan-temperature.pdf)

同域训练入口候选将单个 `rx_training_q` 绑到已有 RX 首拍的短 CTS 支路。TX、PLL、两段 RX 纪元和 host 背压行为对照通过。后布线同口径 `rx_training_enable` 的 1.65 V 冷角 setup/hold 为 `+1.462/+1.104 ns`，对应基线 setup `−0.958 ns`。全局仍有状态口、CDR/host、hold 和天线门槛，候选冷角全局 setup/hold 为 `−1.061/−0.193 ns`。时序压力台中的 VCS 原入口因牌照不可达，Icarus 移植台由程序化断言检查仿真逻辑，不计作 SDF 收据。[训练入口布线后复跑](../../results/digital/audit_v3p3_20261125_543NRK/rx_training_ingress/paired_rc_sta/ss_n40C_1v65_interp_fall.log) · [候选 RTL](../../results/digital/audit_v3p3_20261125_543NRK/rx_training_ingress/rtl/serdes_digital_top_v3.sv)

两个 v3.3 版本的移植台均在原 +300 ppm 32 µs 窗口内未判锁。延长的基线探针报 38.43 µs 首锁，频偏反向后锁定，但最大误差 25.33 ps 超过台内 25 ps 门槛。相同台的 v3.2 工作副本过原门槛，+300 ppm 首锁 5.14 µs，反向 6.63 µs。只换老滤波器同样恢复，进一步定位到 v3.3 质量窗口新增的管线。两项质量标志 `q_age_snapshot/q_debt_snapshot` 与票数在同拍锁存后，训练入口组合版过原门槛，分别为 `4.13/7.76 µs`，最大误差 `22.06/22.98 ps`。断流、重获锁、限幅复位和禁用清零另测通过。另把 RX 数据驱动移至 `wclk` 下降沿后 650 ps，保持判锁/反向门槛，组合版 `5.16/6.63 µs`。以上是 RTL 证据。[v3.2 同台](../../results/digital/audit_v3p3_20261125_543NRK/rx_training_ingress/v32-procedural.log) · [质量窗口修补](../../results/digital/audit_v3p3_20261125_543NRK/quality_snapshot.patch) · [组合回归](../../results/digital/audit_v3p3_20261125_543NRK/rx_quality_combined/behavior.log) · [下降沿回归](../../results/digital/audit_v3p3_20261125_543NRK/gls_rx_launch_edge/behavior.log)

相位债精简对照中，直接饱和加法和分段加法均在可达债值域内用 SAT 证明与原组合更新等价。直接写法减少 CDR 子宏约 5.9% 映射面积，分段约 4.9%，两者的无寄生 STA 均损失裕量。分组进位与并行选择组合候选面积约少 0.5%，CDR 域无寄生 setup 仅改善约 56 ps。实际 CDR 路径追到 `s2_delta_q9[1]` 经过低 9 位进位到相位债高位。两种 host FIFO 预取寄存器收缩保持 16×16 压力台逐字一致，但无寄生 host WNS 从 `+0.682 ns` 降为 `+0.651/+0.452 ns`，暂存对照。写入门控删去受 `!training_enable` 隐含的 `!retraining`，全部 1024 种四态输入组合等价。[相位债对照](../../results/digital/audit_v3p3_20261125_543NRK/cdr_logic/) · [FIFO 对照](../../results/digital/audit_v3p3_20261125_543NRK/fifo_logic/) · [写入门控小测](../../results/digital/audit_v3p3_20261125_543NRK/rx_gate_simplification/equivalence.log)

CDC 的独立补丁收紧 Gray 每位起止点，要求两方向各 5 位、同步器 15 对和单扇出覆盖齐全。旧 DEF 和训练入口 DEF 在 1.65 V 插值冷角均复跑通过。路线 A 的双向 Gray 位 `clk→Q + 线延迟` 最大为 `1.115/1.135 ns`，混合 min/max RC 的保守展宽为 `0.354/0.312 ns`，源周期 4 ns。最终以同份 RTL、DEF/SPEF、GDS、SDF 对应的 STA/CDC、GLS、DRC/LVS 收口，再换片顶宏。[CDC 补丁和报告](../../results/digital/audit_v3p3_20261125_543NRK/cdc_flow_fix/) · [逐位极值](../../results/digital/audit_v3p3_20261125_543NRK/gray_bus_extrema/summary.json)

组合候选首轮详细布线的门网表在零延时通过与 RTL 相同的下降沿输入台，已导出 TT SDF，含 12,556 项 IOPATH、13,118 项 INTERCONNECT 和 1,428 项 TIMINGCHECK。VCS 牌照可达后需独立做注入延迟回归。首轮 TT setup/hold 通过，1.65 V 冷角全局 `−1.154/−0.565 ns`，尚有 10 条天线网，需配平后再重做物理验证。[门级功能收据](../../results/digital/audit_v3p3_20261125_543NRK/gate_and_sdf/gate_zero_delay.log) · [首轮冷角报告](../../results/digital/audit_v3p3_20261125_543NRK/rx_quality_combined/pnr/serdes_digital_top_v3/03_sta_ss_n40C_1v65_interp.log)

对组合候选只给 `rx_aligned/rx_offset` 两拍预算，做两轮重新布线 ECO 后 `Ant=0/DRT=0`，同一 1.65 V 插值冷角 min/max RC 为 `−0.930/+0.066 ns`，最差移至 `rx_word_online`。诊断中把 `rx_word_online` 也按两拍采样后，RX FIFO 写门控 `fifo_wv_m1 → mem[7]` 为 `−0.505 ns`，host FIFO 预取 `inflight_f1c[1] → rflo0_lo` 为 `−0.457 ns`，CDR 为 `+0.037 ns`。写门控 FF 的上游 setup 仅余 `+0.634 ns`，纯时钟提前可分配的净余量小。host 预取 FF 上游已 `−0.051 ns`，优先拆分使能路径和负载，保留原数据协议。ECO 版零延时门级回归复跑过。两拍只适用于接收方有明确采样协议的状态接口，未纳入主线约束。[ECO 冷角报告](../../results/digital/audit_v3p3_20261125_543NRK/status_contract_eco/final_paired/all_status.log) · [网表到 RTL 映射](../../results/digital/audit_v3p3_20261125_543NRK/status_contract_eco/net_mapping/critical_map.txt) · [ECO 门级功能](../../results/digital/audit_v3p3_20261125_543NRK/status_contract_eco/gate/behavior.log)

对 `full_v8` 合并 GDS 和 v3.2 独立 GDS 的同名数字子单元执行几何异或。边框一致，逐层 M2–M5 的异或面积均为零。1.44、1.60、1.76 V 冷角源库与 1.65 V 插值库的 1,842 个时序弧和 6,146 个表项按单元、引脚、边沿类型和条件逐项同序。该检查覆盖插值弧身份，定量精度仍按实际弧标定。[数字版图一致性](../../results/digital/audit_v3p3_20261125_543NRK/full_v8_geometry/compare.log) · [Liberty 弧身份](../../results/digital/audit_v3p3_20261125_543NRK/liberty_check/arc_identity.json)

4 Gb/s 的字域仍为 250 MHz，CDR 为已有同步 ÷2 的 125 MHz。5 Gb/s 若仍按 16 位字传输，312.5 MHz 的根时钟可生成 156.25 MHz，同一个同步时钟组内保留明确生成时钟及跨频路径。路线 A 只换 TX/RX 根时钟为 312.5 MHz 的估算，在 1.65 V 冷角、±5% OCV 下 CDR 域为 `−1.836 ns`，说明速度升级须单独收口。32-bit bridge 已有 4G/5G 功能小测及 DRC/LVS，原收据在 SS 热角仍报 `−2.521 ns`，瓶颈在 312.5 MHz `tx_clk`。[分频缩放对照](../../results/digital/audit_v3p3_20261125_543NRK/clock_scaling/ss_n40C_1v65_interp_fall.log) · [双速 bridge 摘要](../../digital/pnr/variants/hd_pnr_32b_dualrate/serdes_dualrate_32b_bridge/summary.json)

## FIFO 收口续查

两轮 ECO 的同一份 DEF 和带电源门网表生成 GDS `1005b5eb581c…`，Magic 全规则 DRC 0，Netgen LVS 唯一匹配。对同一 DEF 的冷角审计，FIFO 一、二级 15 对齐全，一级均单扇出，最小同步级间 setup `+2.537 ns`。两向 Gray 每位最大 `clk→Q + 线延迟` 为 `1.084/1.145 ns`，同 max RC 样本的位间差 `0.045/0.183 ns`。这些数值覆盖 FIFO 同步链，整宏同步链和 MTBF 仍需按最终输入核查。TT SDF 已按同一份 ECO 网表导出。VCS 重试在牌照连接阶段中断，带延时功能仍待跑。[物理验证](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/eco_physical/summary.json) · [FIFO CDC](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/eco_cdc/summary.json) · [VCS 运行日志](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/vcs_timed_probe/compile.log)

组合 ECO 的六角 STA 全部使用同一对 min/max SPEF、±5% OCV 和原时钟周期。状态两拍一栏同时放宽 `rx_aligned`、`rx_offset` 和 `rx_word_online`，只用于分辨剩余数据路径。[六角时序与输入哈希](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/eco_paired_corners_retry/summary.json)

| 条件 | 状态一拍 setup / hold（ns） | 状态两拍 setup / hold（ns） |
|---|---:|---:|
| TT 25 °C / 1.80 V | +0.842 / +0.104 | +1.244 / +0.104 |
| FF −40 °C / 1.95 V | +1.551 / +0.034 | +1.560 / +0.034 |
| FF 100 °C / 1.95 V | +1.544 / +0.037 | +1.544 / +0.037 |
| SS 100 °C / 1.60 V | −0.861 / +0.247 | −0.225 / +0.247 |
| SS −40 °C / 1.65 V 插值 | −1.318 / +0.066 | −0.505 / +0.066 |
| SS −40 °C / 1.60 V | −1.838 / −0.071 | −1.070 / −0.071 |

FIFO 的四个改写保持 16×16 存储和逐拍握手。差分台在两种停钟复位顺序下共比较 4,530 次写、4,490 次读。只翻转预取地址最低位时，子宏无寄生 host WNS 持平 `+0.682 ns`，面积约增 `0.49%`。把预取许可提前寄存能少约 `0.41%` 的子宏面积，host WNS 降至 `+0.248 ns`。把写行资格提前寄存使 `w_valid` 下游从三输入收窄到两输入，写域 WNS 同为 `+0.623 ns`，host WNS 降至 `+0.461 ns`，面积约增 `1.21%`。这四版留作比较。[逐拍台与候选](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/) · [原子宏无寄生 STA](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/clock_margin/baseline_no_wire.log)

写选通由 AND3 改为 NAND3 并交换 MUX 数据脚，256 个写位的组合等价覆盖代表单元全部 1,024 个四态输入。重新详细布线后，固定 `_8439_ → _9130_` 由 `−0.505` 提至 `−0.444 ns`，另一组 `_8440_ → _9180_` 从 `−0.422` 降至 `−0.711 ns`。后者的写选通单级仍缩短 `0.174 ns`，其余路径变化抵消了收益。该候选 `Ant=0/DRT=0`，状态一拍的全局 `−1.311/+0.059 ns`，状态两拍的全局 `−0.711/+0.059 ns`，host 最差 `−0.703 ns`。完整重布线会改变其他路径，复核结论以同版整体收据为准。[四态对照](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/write_polarity/truth.log) · [定点路径与冷角 STA](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/clock_margin/write_polarity_fixed_pairs.log) · [一拍回放](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/clock_margin/write_polarity_strict.log)

host 局部 CTS 的静态预算在原组合 ECO 上逐个核了 29 个寄存器。推迟 `_9232_` 捕获沿，单点有效偏移窗口约 `0.457–0.785 ns`。同在叶支路 8 的被查端点，在其他边沿固定时只有约 `0.294–0.329 ns` 的共同预算。`_8850_` 的入、出路径 setup 分别 `−0.099/−0.054 ns`，其局部偏移无法独自兼顾两端。另有一拍 `host_data` 端点违例。现阶段优先缩短组合通路，再复核 CTS 负载及所有相邻路径。[逐端点窗口](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/clock_margin/all_host_windows.log)

256 个 FIFO 写位的 `mux2 + dfxtp` 精确识别为单字节行选通控制的自保持结构，隔离映射成 `edfxtp_1`，保持原时钟、写入拍和存储深度。被替换单元面积 `8,822 → 7,687 µm²`，减少 `1,135 µm²`，约 `12.9%`，宏外框 `346.8×307.4 µm`。同版重布线冷角的最差写入端点为 `+0.488/+0.716 ns`，原最差定点由 `−0.505` 提至 `+0.571 ns`。全局一拍 `−1.299/+0.080 ns`，两拍诊断 `−0.947/+0.080 ns`，其中 host 预取仍差 `0.947 ns`。两组 host 预取门重排另作无寄生比较，四个定点的变化仅 `−26` 至 `+44 ps`，并行保留为比较样本。[写位映射与重布线](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/enabled_memory/) · [host 门重排](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/host_factored/factored.log)

`edfxtp_1` 重布线网表在原数据发射边的零延时 GLS 上通过 PLL、TX、两段 RX 加背压和 CDR ±300 ppm 回归，149,400 项程序化检查通过。Ant/DRT/Magic DRC 均为零，Netgen 唯一匹配。冷角电气限制继续保留。原组合 ECO 的最差 slew 为 `1.38 ns` 对 SDC `0.65 ns`，RX CTS 一支路负载约 `0.44 pF` 对全设计帽值 `0.085 pF`。带使能版最差 slew `1.42 ns`，同一支路约 `0.42 pF`。布线和 LVS 检查覆盖物理规则与连接，电气门槛仍需按驱动、拓扑和负载回查。[零延时门级](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/enabled_memory/routed_zero_delay.log) · [物理验证](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/enabled_memory/physical/summary.json) · [冷角电气检查](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/enabled_memory/route_sta_ss_n40C_1v65_interp.log)

整宏结构筛查在已审 FIFO 一、二级外，另由 RTL 名映射复核 16 对 PLL/RX/CDR/TX/host 的同步和复位链。原组合 ECO 的 16 对一级均通向唯一二级接收脚，`host_source_fault` 经在线清零门后进入二级，其 setup `+2.031 ns` 为最紧。FIFO 的 bundled data 另以真实网表从 256 个写存储 FF 到 32 个读银行一级 FF 检查时钟无关的 8 ns 诊断预算。该预算按写指针经过两级同步、许可寄存、首次读取的节拍留出一拍。冷角最差 `clk→Q + data + setup` 原版 `3.222 ns`，带使能版 `3.614 ns`。脚本只对实际存在的跨钟读出路径评分，签核约束仍按原时钟分组。[同步链定点](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/top_cdc_retry/run.log) · [读数据定点](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/bundled_data/run.log)

带使能版同一份 DEF 的 CDC 复跑中，FIFO 15 对级间最小 setup `+2.530 ns`，其余 16 对最小 `+2.063 ns`，所核一级无跨用途分叉。六角一拍约束下 TT/两快角的 setup/hold 为正，两个 1.60 V 压力角和 1.65 V 冷角仍有 setup 违例。1.60 V 冷角 hold 由原组合版 `−71 ps` 变为 `+2 ps`，接近门槛。带使能版 TT、SS 冷 1.65 V、FF 冷 SDF 均从同份 DEF 和配套 RC 导出，每份含 11,548 个 IOPATH、12,637 个 INTERCONNECT、1,428 个 TIMINGCHECK；TT 的 VCS 编译单独重试仍因牌照连接失败退出。[同步链复跑](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/enabled_memory/cdc/top.log) · [六角收据](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/enabled_memory/all_corners/summary.json) · [SDF 身份](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/enabled_memory/sdf/summary.json) · [VCS 牌照日志](../../results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/enabled_memory/sdf/vcs_compile_tt.log)

## 结构和面积复核

v3.3 为四个 250 MHz 根时钟的 16-bit 架构。PLL 管理和 CDR 滤波分别复用同步 ÷4/÷2，TX 在原字域直接处理输入，RX 对齐与 CDR 共用采样重排，RX 通过 16×16 异步 FIFO 交给 host。按组合候选的 `66,336 µm²` 综合总面积，RX 对齐加 host FIFO `31,319 µm²`（47.2%），CDR `23,175 µm²`（34.9%），PLL 控制 `8,088 µm²`（12.2%），TX 输入和采样重排合计 `1,614 µm²`（2.4%）。余量含顶层连接及映射胶合。[模块综合及布线面积计算](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/area_audit/summary.json)

按 DEF 实例的 LEF 外框求和，组合版剔除填充、tap 和去耦后的单元面积 `77,514 µm²`。命名的时钟缓冲、修 hold 和信号修复单元合计 `6,794 µm²`。带使能写位版的同口径面积降到 `76,380 µm²`，少 `1.46%`，宏外框仍为 `346.8 × 307.4 µm`。原组合版去耦单元占 `17,671 µm²`，带使能版占 `18,921 µm²`。要把省下的单元面积转换为更小外框，需要重新摆位、布线及核对供电、去耦和片顶 pin。当前片顶槽位按 `345.9 × 307.4 µm` 的 v3.2 导入。[同口径实体核算](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/area_audit/summary.json)

对齐训练的 16 路半字匹配在入第一级 FF 前合并，实测少 16 个 FF、RX/host 子宏少 `330 µm²`。无寄生字域 setup `+0.623 → +0.660 ns`，host `+0.682 → +0.651 ns`。差分台覆盖 16 个锁定偏移、3,755 个有效字，逐拍一致。CDR 投票流水可只复位五个阶段的有效位，数据在原 pair 出口靠有效位掩蔽。差分台覆盖 `29,776` 次逐拍/复位比较和 `9,286` 个有效 pair，输出完全一致。保持 voter 映射边界时，CDR 少 `908 µm²`，无寄生 250 MHz 域 setup `+0.911 → +1.135 ns`，125 MHz 域 `+1.383 → +1.379 ns`。全扁平映射的 125 MHz 域损失约 `0.440 ns`，需要保留映射边界再看布线。两个 RTL 变体一起跑过原下降沿数据、PLL/TX/RX 纪元和 CDR ±300 ppm。其面积和时序目前为综合结果，投票数据无效拍仍更新，需复查动态功耗。[对齐器逐拍差分](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/align_match_precombine/equiv.log) · [voter scoped STA](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/voter_valid_only_reset/lean.scoped.sta.log) · [组合 RTL](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/combined_area_rtl/behavior.log)

两组 host 预取地址的保持式重映射为 `D = U ? Q : !R`。32 个反馈数据位共用两组局部反相，去掉原选通 `NOR` 和各一级重复器，既有根时钟、有效态更新和延迟拍数沿用。重布线 cold host 最差 setup 从 `−0.947 ns` 到 `−0.580 ns`，新增单元面积约 `+6.3 µm²`。TT 和两快角过，冷角一拍全局 `−1.354/+0.077 ns`，RX 输出最高优先；最差 host 拆分为 `_8860_ → repeater1025 → _9224_`，适合再分 `U` 的物理负载。精确布线网表零延时回归过，31 对同步链复跑通过，`Ant=0/DRT=0/Magic DRC=0/Netgen LVS=MATCH`。原带使能版的 `rx_offset` 最差输出缺口 `0.862–0.915 ns`，入 D setup 仅 `0.393–0.421 ns`。单独提前 offset FF 会把缺口移入对齐器，需联查控制发射、输出驱动和 CTS。[host 六角](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/all_corners/summary.json) · [状态入出定点](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/status_paths.log) · [同版物理验证](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/physical/summary.json)

host 反馈版已从该布线导出 TT、SS 冷和 FF 冷三份 SDF。TT VCS 仍在牌照连接阶段退出。[SDF 哈希](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/sdf/summary.json) · [许可诊断](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/sdf/vcs_compile_tt.log)

独立 v4 双速宏将 host 接口增至 32 bit、160 MHz，线侧仍以 16 bit 在 250/312.5 MHz 工作。TX 和 RX 各有 8×32 FIFO，重逻辑走同步 125/156.25 MHz 域。v4 交付外框 `394.7 × 372.6 µm`、`147,065 µm²`，比 v3.3 外框大 `38.0%`。综合 `83,546 µm²` 中 TX 入口 `20,410 µm²`，v3.3 TX 入口 `838 µm²`。RX 拼包加 host 合计 `28,084 µm²`，比原 RX/host 少 `3,235 µm²`。因此 v4 后续面积优先检查新增 TX 弹性跨域及齿轮箱。[v4 原收据](../../digital/pnr/variants/hd_pnr_v4_32b/serdes_digital_top_v4/summary.json)

v4 TX 的实际扁平综合网表中，256 个存储 FF 为 `5,445 µm²`，每位的写入保持 MUX 为 `2,883 µm²`，8:1 读选择树 `1,802 µm²`，三者合计 `10,130 µm²`。已核灰码指针和上线状态的 20 个同步 FF 为 `526 µm²`，两域另 4 个复位同步 FF 为 `105 µm²`。保持 FIFO 层级并沿用同一映射库与 `abc -D 2200` 复综合，完整 FIFO `15,093 µm²`，外层 skid、启停和拆字合计 `5,430 µm²`。分层总数 `20,523 µm²`，比发布的扁平结果多 `0.56%`。按原写存储单元直接替成 `edfxtp_1` 估计节约 `641 µm²`，尚待 v4 同版时序实测。[v4 TX 面积分账](../../results/digital/tx32_area_breakdown_20261125_cdwh8f/summary.json)

v3.3 的 TX 接收端和字捕获端同属 `tx_word_clk`，A/B 有效位为同域流水。对 v4 独立 host 160 MHz 和 TX 半速 156.25 MHz，按每银行填满发布、读尽归还建模，两向各两级同步，host 连续有效且读端持续请求。扫描相位后，双槽各一字（64 bit）为 `2.02 Gb/s`，双银行各四字（256 bit）为 `3.68 Gb/s`。逐槽归还的五槽在该理想模型刚好连续五速，两向分别多一拍时需七槽。该对照用于估计所有权开销，真实 FIFO 深度还受注册 `ready`、突发、抖动和停钟复位约束。若 TX 输入可使用与串化器同源且相位有合同的半速时钟，可另核同步双缓冲/齿轮箱。[两级往返相位扫描](../../results/digital/tx_pingpong_study_20261125_O6hH0T/summary.json) · [额外级延迟敏感性](../../results/digital/tx_pingpong_study_20261125_O6hH0T/added_latency_summary.json)

v4 TX 的 2/4 深度试验只为各深度改读选择器，保留原灰码、注册 `ready`、预取和外层 skid。host 160 MHz 连续有效，两种线速各扫六个相位，所有已接受字最终都按序发出。2/4/8 深度在 4G 线速下有效载荷为 `1.28/2.56/4.00 Gb/s`，5G 线速下为 `1.44/2.87/5.00 Gb/s`。2/4 深度的六相均触发 `tx_underrun`，8 深度六相均无缺拍。全 TX 子块同库综合为 `10,844/14,149/20,410 µm²`。2 深度可省 `9,565 µm²`，但在现有独立时钟及控制协议下只适用于允许大量空闲码的短突发用途。[深度对照与可复现台](../../results/digital/tx_fifo_depth_study_20261125_yRIOQl/summary.json)

v4 的导出 DEF、普通/带电源网表和 GDS 与运行目录逐一同哈希。复跑原 `max SPEF` 单 RC 的 5G 1.65 V 插值冷角 R2R 最差 setup/hold 为 `+0.003/+0.059 ns`。同份 DEF 换成成对 max/min RC 后，4G 为 `+0.219/+0.049 ns`，5G 为 `−0.056/+0.049 ns`，最差在 156.25 MHz `rx_clk_div2` 域。此处只重放冷角，并保存 SDC 和 SPEF 身份供 Antigravity 复核。`full_v8` 导入仍指向 v3.2。[双速同版复核](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/v4_readonly/summary.json) · [单 RC 对照](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/v4_readonly/5g_cold_max_only.log)
