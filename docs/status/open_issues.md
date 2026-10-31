# 待解决问题

> 编号稳定，关闭时保留条目并写明结论与日期。阶段：P2 正确性修复，P3 PVT 补全，P4 相位噪声与抖动，P5 RX PVT 与数字实现。优先级按对"45 条件满足规格"的影响排序。

## 高优先级

| 编号 | 问题 | 证据 | 阶段 |
|---|---|---|---|
| I-01 | **分频器启动状态不确定：解法已验证，待接入。** 相对 250 MHz 字时钟，500 MHz（支路 2 ÷4）有 4 种、1 GHz（支路 3 ÷2）有 2 种启动状态。8 种状态都只造成字内固定的位对重排，眼图完好，置换在 6 个压力工况、3 个观测节点上一致。解法：启动时用 3 bit 检测器读状态（48/48 码值正确且静态，最小采样余量 162 ps），CMOS 侧 `tx_word_remap` 预先逆置换；调序后 TT/SS 热/FS 热 × 8 状态全部满足规格，FS 热角 1024 bit 最差 0.127 UI。剩余：接 r3 原生前端时确定"码→状态"锚点（随 I-07）；检测器接入启动监督 RTL；用后关断。 | [TX 时钟分发](../design/tx_clock_distribution.md#启动状态与调序) | P2 |
| I-02 | **CML 负载全为理想电阻，PVT 只覆盖 MOS 角。** 摆幅（I·R）和共模（VDD − I·R/2）直接受电阻工艺角和温漂影响，而这正压在 1.65 V 堆叠余量上。全项目只有 LF 候选用了 PDK 电阻。CTLE、PI 混合电容、TX 微调电容同样是理想元件。 | 各设计文档"适用范围" | P3 |
| I-03 | **参考电流理想，没有基准。** 0.85 mA、50 µA 参考都是理想源；LF 预充参考/缓冲（约 2.6 mA 峰值）、RX 共模参考/缓冲未设计。PVT 结果不含参考自身变化。 | [偏置](../design/bias.md) | P3 |
| I-04 | ~~全速 CML→CMOS SS 冷角失败。~~ **已解决 2026-10-31（PLL r4）**：根因是差分转单端级 PMOS 镜像负载上拉不足；r4 接收器标准边界 45/45，原生 VCO 5 个工作点四路全部正常（含 SS/1.65 V/−40 °C）。遗留：SS 热角幅度余量约 110 mV。 | [时钟接收器](../design/clock_receiver.md#r4全速-ss-冷角修复2026-10-31) | — |
| I-05 | **相位噪声方法未建立，没有抖动预算。** 无 VCO 相噪、PLL 噪声合成、带宽选择、TX 输出抖动预算。 | [规格](../overview/spec.md#抖动与相位噪声预算待推导p4) | P4 |
| I-06 | **TX r2 长码型散布接近门槛。** FS/1.65 V/85 °C 的 1024 bit 记录：串化器 0.1149 UI、焊盘 0.1425 UI、远端 0.1469 UI；同工况 128 bit 为 0.0953 UI。128 bit 网格低估码型相关散布，需要长码型复验和改进余量。调序方案下 8 个启动状态在 FS 热角 1024 bit 的最差散布为 0.127 UI（500 MHz 滞后奇数个 VCO 周期的状态）。 | [TX 串化器](../design/tx_serializer.md) | P3 |
| I-07 | **原生 PLL 时钟接 TX：r2 在源端漂移和弱抽头下不成立；v1 分发在 4 个原生点上修好。** PLL r4 原生前端 + TX r2 联合仿真：TT 正常（眼图 152.8 mV，检测码直接对应实测置换表），SS 冷（7.1 mV）和 SS 热（0.188 UI）失败。把理想边沿放到原生位置即可复现失败，所以相对位置错位是主因；但输入本身也变差了：SS 热角串化器处 1 GHz 时钟 301 mVpp（理想源 441）、过零斜率 1.06 mV/ps（理想源 2.64），500 MHz 379 mVpp；SS 冷角 1 GHz 斜率为理想源的 55%。r2 的 45 条件扫描用的是同一份理想 TT 时钟源（400 mVpp、20 ps 边沿）和理想 CMOS 数据源。原生时钟相对 r2 标定位置偏 0.17–0.79 UI，且随工况漂移（2 GHz 相对 250 MHz 在 TT 和热角间差约 0.4 UI）；热角单轴窗口为 500 MHz −0.5~+0.1、1 GHz ±0.25、2 GHz −0.1~+0.3 UI。统一对中后 FS 热角仍不达标（0.209 UI）。r2 的 45/45 只在固定 TT 时钟下成立。录制回放拆分后：SS 冷角只是位置；热角是时钟质量（位置对准时 FS 热仍 75 mV / 0.258 UI）。分发 v1（500M/1G 加一级高增益 buffer、去 RC trim，+1.3 mA）+ 每路一个固定延迟（2G 再晚 0.2 UI），4 个原生点最差 125.4 mV / 0.072 UI。位置漂移正比于各路分频级数之差（每级 25–40 ps，全 PVT 约 85 ps）。加入 FF 1.95 V −40 °C 原生点后固定设置失效：2G 晚 0.88 UI、位序改变；5 点剩余误差跨度 500M/1G/2G 0.22/0.55/0.92 UI。需要重新打拍，使各路 VCO 之后的分频级数相同。 | [TX 时钟分发](../design/tx_clock_distribution.md#原生-pll-r4-时钟) | P2 |
| I-31 | **边界条件（上游录制/理想化波形作为下游激励）没有管理。** 回放脚本按"最新一次录制""最新一次 target"隐式查找，新录制会悄悄改变后续结果；录制时的上游修订、工作点、下游负载（例如 TX 分发输入级）没有作为条件记录，下游改了输入级（v1 把 500M/1G 第一级 400 → 600 Ω，v2 加打拍）也不会让旧录制失效；理想 TT 时钟记录在 45 个条件下复用而结论没有标注。另外 bench 模板直接引用 DUT 内部节点名（`xclocks.a250p` 等）和显式 `.save` 列表，换 DUT 变体时整批仿真在最后写文件时失败（本轮浪费 6–14 分钟各一次），缺少开跑前的短冒烟检查。**已建（2026-10-31）**：登记表 + `serdes_flow.boundary`（按 id 引用、负载签名检查）+ `run_many` 默认冒烟；PLL r4 抽头的 r2 负载录制和理想 TT 记录已登记，`clock_replay`/`retime` 已接入。剩余：v1/v2 输入级下重新录制；旧脚本（clock_states、swing_trial、waveform_view）接入。 | [验证方法](../verification/methods.md#边界条件管理) | P2 |
| I-08 | **PLL r3 没有原生持续锁定和从零捕获。** 原生 r3 只接回 48 ns（TT），闭环 PVT 是分层模型且 LF 预置。 | [PLL 环路](../design/pll_loop.md) | P3 |
| I-14 | **RX 全链没有 PVT。** 端接、CTLE、PI、采样、读出都只有 TT；C3/C4/C5 信道未覆盖。 | [RX 前端](../design/rx_frontend.md)、[RX PI 与采样](../design/rx_pi_sampler.md) | P5 |

## 中优先级

| 编号 | 问题 | 证据 | 阶段 |
|---|---|---|---|
| I-09 | VCO 45 条件 × 全码调谐映射与相邻码重叠未做；TT 码 4/5 在 1.1–1.55 V 窄窗下有约 31.4 MHz 间隙。 | [VCO](../design/pll_vco.md) | P3 |
| I-10 | FS/1.65 V/−40 °C 分频首级/第二级 master 尾管平均 VDS − VDSAT 约 −5/−4 mV（r3）；r2 时约 63% 采样点低于饱和判据。功能正常但无裕量；修补困难时考虑减少堆叠的结构。 | [分频器](../design/pll_divider.md) | P3 |
| I-11 | 1.95 V 条件 CMOS 上冲（FF/FS 冷角峰值约 2.022–2.026 V），15 个 1.95 V 条件都有；器件端电压未核对。r4 接收器最高约 2.049 V（SS/1.95 V/−40 °C）。 | [时钟接收器](../design/clock_receiver.md) | P3 |
| I-12 | CP 高 Vctrl 处 UP/DN 失配：SS/1.65 V/85 °C、1.4 V 时 40.8/49.3 µA；PFD→CP 零电荷相位 −79.4 … +93.1 ps；三点不足以证明无死区。 | [PLL 环路](../design/pll_loop.md) | P3 |
| I-13 | LF RC 极限角未接入闭环；物理 LF 候选（poly + MIM）未决定是否采用。 | [PLL 环路](../design/pll_loop.md) | P3 |
| I-15 | RX 物理 16 UI 降速 / CML 整字保持 bank 未实现；系统时钟域 FIFO/CDC 未设计。 | [RX 数字](../design/rx_cdr_digital.md)、[字收集方案](../history/rx_cml_word_capture_plan.md) | P5 |
| I-16 | 数字 RTL 没有综合映射和 STA（yosys 0.9，无 OpenSTA）。 | [RX 数字](../design/rx_cdr_digital.md) | P5 |
| I-17 | ~~400 mVpp 的适用节点未定义。~~ **已关闭 2026-10-31**：400 mVpp 是上界与驱动目标；内部 CML 硬下限 150 mVpp、设计目标 ≥ 200 mVpp；VCO 摆幅归 P4 相噪预算（见 I-05）。 | [规格](../overview/spec.md#已确认的取舍2026-10-31) | — |
| I-19 | TX 没有并行字捕获寄存器，输入字按已知时刻激励；早期试验中提前 1 UI 更新就出错。 | [TX 串化器](../design/tx_serializer.md) | P2 |
| I-20 | 链路级眼图门槛未定义。75 mV 只约束串化器节点；TX r2 接 C2 时远端最小裕量 54.81 mV（FS/1.65 V/85 °C）。需要定义 RX 输入或 CTLE 后的门槛。 | [信道模型](../design/channel_model.md) | P5 |
| I-21 | PLL 启动：频率/细相位测量前端、片内预充参考、看门狗、自动粗搜未实现。 | [PLL 环路](../design/pll_loop.md) | P3 |
| I-23 | RX 鉴相零点：CMOS 读出后零点在码 4–8 之间，与 CML 符号判读的码 4 不同；孔径偏移未校准（压力测试中峰值相位误差约 0.138 UI）。 | [RX PI 与采样](../design/rx_pi_sampler.md) | P5 |
| I-27 | TX 串化器内部节点码型相关 ISI 明显（孤立位峰值远低于长连码），远端经输出级限幅后才干净；内部带宽仍是限制。2026-10-31 补测：孤立位/长连码中心电平比 r2 0.82、v0.1 0.80，ISI 没有变差；r2 末级比特中心前下垂约 18 mV，与下一比特和摆幅无关。降低末级负载（400→330→270 Ω）裕量近比例下降、尾管余量不变，末级摆幅不宜降低。 | [TX 串化器](../design/tx_serializer.md) | P3 |
| I-28 | CTLE：0.8 V 共模时源极约 0.153 V（回放最低 0.123 V），尾 sink 余量小；无 CMFB；默认 EQ 码与自适应未定。 | [RX 前端](../design/rx_frontend.md) | P5 |

## 低优先级

| 编号 | 问题 | 证据 | 阶段 |
|---|---|---|---|
| I-18 | VCO 粗调控制器、温度计译码、无扰切码未实现。 | [VCO](../design/pll_vco.md) | P3 |
| I-22 | Xschem 原理图是历史导出，未同步 r2/r3/TX r2；当前以 SPICE 为准。 | [原理图记录](../history/schematics.md) | — |
| I-24 | 三个 PLL 前端 SPICE 文件的注释仍引用旧路径 `docs/pll_first_debug.md`（现为 `docs/history/pll_first_debug.md`），v0.1 发布快照中也有同样引用；按约定未改源码。 | `analog/pll/top/spice/clock_frontend_*.spice` | — |
| I-29 | TX 输出级焊盘/ESD/封装为代理参数；电源、回流、PSRR 未建模；FFE 未实现。 | [TX 输出级](../design/tx_output_driver.md) | P5 |
| I-30 | RX PI 锚点是理想源，没有接原生 PLL 八相；共享 PLL 能支持多少路 PI 扇出未验证。 | [RX PI 与采样](../design/rx_pi_sampler.md) | P5 |

## 文档整理时发现的冲突（已按最新记录处理）

| 旧说法 | 来源 | 现行结论 |
|---|---|---|
| 当前工作版本是低过驱动 r2 | `pvt_noise_plan.md` 开头 | r3（级间 buffer）是当前版本，见 `pll_buffered_pvt.md`（2026-10-30） |
| 反馈改为 CML ÷8 后接 CMOS M = 1–16 | `cml_divider_results.md` 开头 | 自由 CMOS 分频接多相 CML 转换后的最高 2 GHz 时钟，不在 ÷8 之后（`clock_domain_clarification.md`、`architecture.md`） |
| TX 串化器只有 36/45 满足草案 | 旧 README、`tx_pvt.md` | TX r2 为 45/45（`tx_optimization.md`，2026-10-30） |
| FS 低压热角 2 GHz 原生回接未资格验证 | `pll_lowov_pvt.md`（r2） | r3 码 5、1.100 V 时 1.9906 GHz 回接正常（`pll_buffered_pvt.md`） |
| SS 低压热角反馈读出失效 | `pll_pvt_first_results.md` | r2/r3 中 SS 热角反馈正常；当前缺口在 SS 冷角全速转换 |
| TT 局部 Kvco 423 / 464.55 / 495 MHz/V | 首轮 / v0.1 带载拟合 / r3 修整 | 分别对应不同几何、负载、粗码和电压区间，不是矛盾；使用时注明口径 |
