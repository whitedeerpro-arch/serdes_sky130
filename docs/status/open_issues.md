# 问题登记与关闭条件

编号稳定，关闭时保留结论、日期和证据。**本表记录 2026-11-26 片级装配完成后尚未关闭的流片收口风险，不是执行队列**；任务排序与流片验收顺序见 [prelayout_plan.md](prelayout_plan.md)，当前验证数字统一见 [current.md](current.md)。

---

## 1. 当前开放项（5G Plan-C 与 4G `full_v8` 流片前收口）

| 编号 | 未关闭问题 / 关闭条件 | 关联模块与文档 |
|---|---|---|
| **I-TOP-01** | **片顶完整接口连接、4G `icml` 修复、Padring/ESD 与全片 LVS**。补齐 5G Plan-C 与 4G `full_v8` 尚未接入顶层的控制端口（PFD `ref/rst_b`、数字 `ref_clk`、LDO `enable`、LF `pre_en`、TX/RX `rst_n`、粗调/就绪与首片低速 DFT 入口）；修复 4G `full_v8` 中 `BIAS/icml` 与四路 `r5/vbias` 并入 `VSS` 的短接（5G Plan-C 已独立）；将层级隔离门控升级为预期连接表（核查端点存在、全网连通与显式 NC）；锁定同一张 Pad Map 合入 ESD/ERC，并通过独立片顶原理图全片 Netgen LVS | [实装复核](../layout/chip_floorplan_20261123.md#10-实装金属与分析缺口复核2026-11-26) · [流片验收顺序](prelayout_plan.md#4-流片前验收顺序) |
| **I-TOP-02** | **片级带载 RCX、5G 端口重排与跨宏串扰**。提取 5G CMOS I/Q 时钟树（`ip/in/qp/qn` 正负腿各差 `30.4 µm` 且扇出至 RX/TX/÷AB）、5G 数字→RX PI 24 线（当前绕行 `11.435 mm` vs 下界 `10.469 mm`）、4G 八相时钟树、`CP→LF→VCO` 与高阻偏置的分段 R/via/互容；在同时切换的数字与 TX 负载下验证偏置扰动、相位误差、PI 码到达偏斜与字边界时序 | [实装复核](../layout/chip_floorplan_20261123.md#优先重排的端口) · [审计台账](../../results/catalog/chip_physical_audit_20261126.json) |
| **I-TOP-03** | **同版静态 IR/EM、动态供电与工艺密度/天线/填充后提取**。按最终 GDS 实际电源环、过孔、地回流、封装与负载电流复算静态压降与瞬态 droop（优先复测 `VDD_Q` LDO→VCO 支路、RX 采样与 TX 突发），消除几何代理偏差；处理 4G M4/M5 与 5G M5 零覆盖窗口的工艺密度/CMP 填充及天线规则；将 5G LC-VCO 与 CTLE 电感周边填充/屏蔽纳入 EM 验证并做填充后敏感网 PEX | [IR/EM 复核](prelayout_plan.md#irem-修正与剩余验证) · [实装复核](../layout/chip_floorplan_20261123.md#片级还缺的分析) |
| **I-TOP-04** | **实际分频/控制下的全链冷启动联调与带延时 GLS**。使用实际反馈分频（5G `div_ab_5g_v2_pdk` / 4G 加固 SAFF-TSPC ÷8）与生产数字顶层（`v4p1` / `v3`）完成从零上电自动粗搜、预充捕获、掉锁重获、时钟停复与 TX→PCB→RX→CDR/FIFO 完整闭环，并在可用签核环境补齐 5G/4G 带延时 SDF 门级回归 | [当前状态](current.md) · [数字顶层](../design/digital_top_v3.md) |
| **I-TOP-05** | **局部极冷失配尾差与 4G 扩角收口**。收口 5G `PI v3` 在 `SS 1.65 V −40 °C` 24 样本 MC 中剩余 4 样本尾差（归因 `pi4_diff_rec` SVT-PMOS 冷角偏斜）；4G 参考基线补齐 RX v2.2 45 角全量 CPEX 及加固 SAFF-TSPC ÷8 提取后冷角 MC | [RX CMOS](../design/rx_cmos_v2.md) · [SAFF-TSPC ÷8](../design/pll_tspc_reclock_divider.md) |
| **I-TOP-06** | **系统抖动预算、实装封装信道与首片 DFT/BER 验收**。将最终采用的时钟、PDN、Pad/ESD、封装与 PCB S 参数纳入同一抖动与误码预算，完成 45 PVT 功能门槛核对，并随 Pad Map 固化首片 DFT 最小入口（含 ≥42-bit 有效位计数）与实验室 BER 验收口径 | [规格](../overview/spec.md) · [首片 DFT](prelayout_plan.md#首片-dft-最小测试入口) · [信道](../design/channel_model.md) |

I-TOP-01 同时承接 5G LC 父层护环跨有源 M3 VDD 的短接。合入修正后，应从片顶 `VDD_Q/VSS` 分别查到 LC 有源叶电源，从片顶 I/Q、调谐和粗码查到实际器件端，再用相同修订提取、复核带载与电感行为。[同版短接反例及局部修正](../../results/catalog/chip_macro_reformulation_20261126.json)

---

## 2. 早期历史编号归档说明（`I-01` – `I-35`）

早期面向全 CML 原型登记的 `I-01` – `I-35` 问题均已由 CMOS/SST TX & RX、5G LC-PLL/32-bit 数字宏演进替代、在模块边界闭合，或并入上表 `I-TOP-01` – `I-TOP-06` 跟踪；完整历史原文保留在 git 历史（标签 `v1.0` / 提交 `b10e989`）。
