# 问题登记与关闭条件

编号稳定，关闭时保留结论、日期和证据。**本表记录尚未关闭的工程风险，不是执行队列**；任务排序见 [prelayout_plan.md](prelayout_plan.md)，当前验证数字统一见 [current.md](current.md)。

---

## 1. 当前 4 Gb/s Zero-CML 开放项（顶层集成与良率）

| 编号 | 未关闭问题 / 关闭条件 | 关联模块与文档 |
|---|---|---|
| **I-TOP-01** | **片级顶层互连与 Padring/ESD 拼接**：全部 21 个宏均已独立 DRC=0/LVS=MATCH 并完成 `0.5084 mm²` 规划，尚需完成顶层金属互连、电源环、ESD/Padring 与片级 DRC/LVS/IR-drop 验证 | [chip_floorplan_20261123.md](../layout/chip_floorplan_20261123.md) |
| **I-TOP-02** | **锁定 PLL → 动态 TX → PCB → RX → 数字 CDR 全链路同 deck 联调**：各子系统独立后仿均已通过，尚缺整机同源联合瞬态与从零上电自动粗搜全时序联合验证（承接原 I-07/I-08/I-21） | [current.md](current.md) |
| **I-TOP-03** | **SAFF-TSPC ÷8 极冷低压失配良率**：`SS 1.65 V −40 °C hh` 下 200 样本 CPEX MC 为 168/200 正常分频，故障集中于 `Xtg2` 路径；需加宽器件或降低局部寄生并重跑 MC | [pll_tspc_reclock_divider.md](../design/pll_tspc_reclock_divider.md) |
| **I-TOP-04** | **RX v2.2 45 角 CPEX 扩角与两项小修订版图同步**：RX v2.2 原理图已过 45/45、CPEX 已过 3/3 代表角（`TT`/`SS -40 °C`/`FF -40 °C`），尚需补齐剩余 42 角 CPEX 并同步 CP v4.1 / LDO 泄放微修至 `.mag` | [rx_cmos_v2.md](../design/rx_cmos_v2.md)、[pll_cp_v4.md](../design/pll_cp_v4.md)、[ldo_v2.md](../design/ldo_v2.md) |

---

## 2. 早期历史编号处置汇总（`I-01` – `I-35`）

早期面向全 CML 路线登记的问题编号（详细原文保留在 [open_issues_snapshot_20261113.md](../history/open_issues_snapshot_20261113.md)）按最新 4 Gb/s Zero-CML 签核结果归类如下：

| 类别 | 编号 | 处置结论 | 证据入口 |
|---|---|---|---|
| **已由 Zero-CML 架构解决 / 替代** | `I-01, I-06, I-10, I-17, I-19, I-27` | 弃用全 CML 16:1 串化树与三叠层 CML ÷8，改用静态 CMOS 16:4 + N-over-N SST（22/22 RCX）与 SAFF-TSPC ÷8（`LAYOUT-PLL-DIV-RC-01` 原 CML 分频 RC 疑点不再阻塞主线） | [tx_sst_v4.md](../design/tx_sst_v4.md)、[pll_tspc_reclock_divider.md](../design/pll_tspc_reclock_divider.md) |
| **已由数字 v3.1 & RX v2.2 闭合** | `I-15, I-16, I-18` | `serdes_digital_top_v3`（v3.1）已完成 3 角 OpenRCX STA（SS `+0.074 ns`、FF `+0.125 ns`）、DRC=0/LVS=MATCH 及 4/4 VCS SDF GLS（`0` 同步违例、122,608 SVA 全通过、`±300 ppm` 闭环 CDR、5-bit PLL 粗搜全寄存器防毛刺） | [digital_top_v3.md](../design/digital_top_v3.md)、[rx_cmos_v2.md](../design/rx_cmos_v2.md) |
| **已由 PLL v4 / VCO PTAT / BIAS v2 / LDO v2_cur 闭合** | `I-04, I-05, I-09, I-12, I-13, I-32, I-34` | VCO r6 + PTAT 45/45 跨三温单码、`sym9_clean` CPEX 八相误差 `≤ 0.76 ps`、PLL v4 7/7 闭环锁定且 RMS 抖动 `1.91/2.29 ps`（CDR 14.07σ 余量 41%）；CP v4/v4.1 + 融合 LF v2 + LDO v2_cur + BIAS v2 均已完成 PDK 版图签核 | [pll_vco_r6_perf.md](../design/pll_vco_r6_perf.md)、[bias_v2.md](../design/bias_v2.md)、[ldo_v2.md](../design/ldo_v2.md) |
| **承接至片级集成阶段（并入 I-TOP-01/02/04）** | `I-02, I-03, I-07, I-08, I-11, I-14, I-20, I-21, I-23, I-28, I-29, I-30, I-33, I-35` | 跨宏长线寄生、Pad/ESD 封装回流、真实锁定 PLL 锚点驱动 TX/RX 整机联调、从零上电全时序及 45 角全量后仿，统一由上表 `I-TOP-01..04` 跟踪闭合 | [prelayout_plan.md](prelayout_plan.md) |
| **长期维护项** | `I-22, I-24, I-31` | Xschem 仍为早期 CML 导出快照（权威以 `spice/` 为准，见 [schematics.md](../history/schematics.md)）；新台继续遵循边界登记与默认冒烟约束 | [methods.md](../verification/methods.md) |
