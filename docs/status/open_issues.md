# 待解决问题

> 编号稳定，关闭时保留条目并写明结论与日期。阶段：P2 正确性修复，P3 PVT 补全，P4 相位噪声与抖动，P5 RX PVT 与数字实现。优先级按对"45 条件满足规格"的影响排序。

## 高优先级

| 编号 | 问题 | 证据 | 阶段 |
|---|---|---|---|
| I-01 | **分频器没有确定性状态。** 每个 ÷2 上电有两种状态；TX 的 250 MHz/500 MHz/1 GHz 分别取自支路 0/2/3 的独立 prescaler，相对相位取决于启动。r3 一次 TT 启动中 1 GHz 差半个周期（约 2 UI），对调 P/N 只对这次有效；÷8 另有整周期粗相位。多相间隔不等距（0.50/0.75/0.50 UI）继承自抽出极性。需要确定性复位/多相同步，或启动后相位检测与纠正。 | [TX 时钟分发](../design/tx_clock_distribution.md)、[分频器](../design/pll_divider.md) | P2 |
| I-02 | **CML 负载全为理想电阻，PVT 只覆盖 MOS 角。** 摆幅（I·R）和共模（VDD − I·R/2）直接受电阻工艺角和温漂影响，而这正压在 1.65 V 堆叠余量上。全项目只有 LF 候选用了 PDK 电阻。CTLE、PI 混合电容、TX 微调电容同样是理想元件。 | 各设计文档"适用范围" | P3 |
| I-03 | **参考电流理想，没有基准。** 0.85 mA、50 µA 参考都是理想源；LF 预充参考/缓冲（约 2.6 mA 峰值）、RX 共模参考/缓冲未设计。PVT 结果不含参考自身变化。 | [偏置](../design/bias.md) | P3 |
| I-04 | **SS/1.65 V/−40 °C 全速 CML→CMOS 失败。** 原生 VCO 下四相全部失效；标准源只有 buffer 输出约 549 mVpp 时才工作。PLL 不依赖，但 RX pair 对齐和 RTL 桥依赖约 2 GHz CMOS。 | [时钟接收器](../design/clock_receiver.md) | P2 |
| I-05 | **相位噪声方法未建立，没有抖动预算。** 无 VCO 相噪、PLL 噪声合成、带宽选择、TX 输出抖动预算。 | [规格](../overview/spec.md#抖动与相位噪声预算待推导p4) | P4 |
| I-06 | **TX r2 长码型散布接近门槛。** FS/1.65 V/85 °C 的 1024 bit 记录：串化器 0.1149 UI、焊盘 0.1425 UI、远端 0.1469 UI；同工况 128 bit 为 0.0953 UI。128 bit 网格低估码型相关散布，需要长码型复验和改进余量。 | [TX 串化器](../design/tx_serializer.md) | P3 |
| I-07 | **r3 原生时钟未接入 TX r2，trim 未重标。** TX r2 全部验证用 v0.1 TT 边沿记录；r3 源下 500 MHz/2 GHz 相对字时钟的位置都变了。依赖 I-01。 | [TX 时钟分发](../design/tx_clock_distribution.md) | P2 |
| I-08 | **PLL r3 没有原生持续锁定和从零捕获。** 原生 r3 只接回 48 ns（TT），闭环 PVT 是分层模型且 LF 预置。 | [PLL 环路](../design/pll_loop.md) | P3 |
| I-14 | **RX 全链没有 PVT。** 端接、CTLE、PI、采样、读出都只有 TT；C3/C4/C5 信道未覆盖。 | [RX 前端](../design/rx_frontend.md)、[RX PI 与采样](../design/rx_pi_sampler.md) | P5 |

## 中优先级

| 编号 | 问题 | 证据 | 阶段 |
|---|---|---|---|
| I-09 | VCO 45 条件 × 全码调谐映射与相邻码重叠未做；TT 码 4/5 在 1.1–1.55 V 窄窗下有约 31.4 MHz 间隙。 | [VCO](../design/pll_vco.md) | P3 |
| I-10 | FS/1.65 V/−40 °C 分频首级/第二级 master 尾管平均 VDS − VDSAT 约 −5/−4 mV（r3）；r2 时约 63% 采样点低于饱和判据。功能正常但无裕量；修补困难时考虑减少堆叠的结构。 | [分频器](../design/pll_divider.md) | P3 |
| I-11 | 1.95 V 条件 CMOS 上冲（FF/FS 冷角峰值约 2.022–2.026 V），15 个 1.95 V 条件都有；器件端电压未核对。 | [时钟接收器](../design/clock_receiver.md) | P3 |
| I-12 | CP 高 Vctrl 处 UP/DN 失配：SS/1.65 V/85 °C、1.4 V 时 40.8/49.3 µA；PFD→CP 零电荷相位 −79.4 … +93.1 ps；三点不足以证明无死区。 | [PLL 环路](../design/pll_loop.md) | P3 |
| I-13 | LF RC 极限角未接入闭环；物理 LF 候选（poly + MIM）未决定是否采用。 | [PLL 环路](../design/pll_loop.md) | P3 |
| I-15 | RX 物理 16 UI 降速 / CML 整字保持 bank 未实现；系统时钟域 FIFO/CDC 未设计。 | [RX 数字](../design/rx_cdr_digital.md)、[字收集方案](../history/rx_cml_word_capture_plan.md) | P5 |
| I-16 | 数字 RTL 没有综合映射和 STA（yosys 0.9，无 OpenSTA）。 | [RX 数字](../design/rx_cdr_digital.md) | P5 |
| I-17 | 400 mVpp 的适用节点未定义。VCO 节点：r2 回接 TT 约 360、SS 85 °C 约 310 mVpp；分频 tap 最低约 227 mVpp；功能筛查线 150 mVpp。 | [规格](../overview/spec.md#待确认) | P3 |
| I-19 | TX 没有并行字捕获寄存器，输入字按已知时刻激励；早期试验中提前 1 UI 更新就出错。 | [TX 串化器](../design/tx_serializer.md) | P2 |
| I-20 | 链路级眼图门槛未定义。75 mV 只约束串化器节点；TX r2 接 C2 时远端最小裕量 54.81 mV（FS/1.65 V/85 °C）。需要定义 RX 输入或 CTLE 后的门槛。 | [信道模型](../design/channel_model.md) | P5 |
| I-21 | PLL 启动：频率/细相位测量前端、片内预充参考、看门狗、自动粗搜未实现。 | [PLL 环路](../design/pll_loop.md) | P3 |
| I-23 | RX 鉴相零点：CMOS 读出后零点在码 4–8 之间，与 CML 符号判读的码 4 不同；孔径偏移未校准（压力测试中峰值相位误差约 0.138 UI）。 | [RX PI 与采样](../design/rx_pi_sampler.md) | P5 |
| I-27 | TX 串化器内部节点码型相关 ISI 明显（孤立位峰值远低于长连码），远端经输出级限幅后才干净；内部带宽仍是限制。 | [TX 串化器](../design/tx_serializer.md) | P3 |
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
