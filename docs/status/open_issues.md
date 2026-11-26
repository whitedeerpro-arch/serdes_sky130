# 问题登记与关闭条件

编号稳定，关闭时保留结论、日期和证据。**本表记录尚未关闭的工程风险，不是执行队列**；任务排序见 [prelayout_plan.md](prelayout_plan.md)，当前验证数字统一见 [current.md](current.md)。

---

## 1. 当前 4 Gb/s NRZ SerDes 开放项（顶层集成与良率）

| 编号 | 未关闭问题 / 关闭条件 | 关联模块与文档 |
|---|---|---|
| **I-TOP-01** | **片级顶层互连与 Padring/ESD 拼接**。复核 2 GHz 八相引脚顺序、TX 正交 ÷2 极性、RX 数据/边沿的 32 位接线及 PI 控制回接。合入北侧去耦接地移线，收口装配数字宏的 SS 建立时序并绑定最终 GLS。提交顶层金属、电源环、Padring/ESD、去耦宏及片级 DRC/LVS/IR-drop 验证 | [片级规划](../layout/chip_floorplan_20261123.md) · [装配证据](current.md#4-发布后的片级集成证据) |
| **I-TOP-02** | **采用反馈链的 PLL 与全链联调**。复核 `r5` + SAFF-TSPC ÷8 的预充捕获与带载锁定，覆盖从零上电自动粗搜，并用实际 RX 解串字回馈生产 RTL CDR/FIFO。验收范围含 PLL ready、预充、PFD 复位和 CP 使能的数模连接。承接原 I-07/I-08/I-21 | [当前状态](current.md) |
| **I-TOP-03** | **SAFF-TSPC ÷8 极冷低压失配良率**。原版的 `Xtg2` 瓶颈已由静态 XOR 与平衡负载候选承接。保留冷角迟启动样本身份，补候选提取后失配与逐边沿验证；通过后再决定顶层采用 | [分频器设计](../design/pll_tspc_reclock_divider.md) · [当前复核结果](current.md#4-发布后的片级集成证据) |
| **I-TOP-04** | **RX CPEX 扩角与 CP/TX 微修电气回归**。补齐 MOS45 CPEX，冻结 CP v4.1、TX `V_drv` 泄放微修的版图和提取身份，复核受影响的模拟与链路工况 | [RX](../design/rx_cmos_v2.md)、[CP](../design/pll_cp_v4.md)、[TX](../design/tx_sst_v4.md) |
| **I-TOP-05** | **系统噪声、BER 与实际信道边界**。将采用的时钟、供电网络、封装、板线和采样路径纳入同一抖动与误码预算，并复核门槛与适用工况 | [规格](../overview/spec.md)、[信道](../design/channel_model.md) |

---

## 2. 早期历史编号处置汇总（`I-01` – `I-35`）

早期面向全 CML 路线登记的问题编号（详细原文保留在 [open_issues_snapshot_20261113.md](../history/open_issues_snapshot_20261113.md)）按最新 4 Gb/s 签核结果归类如下：

| 类别 | 编号 | 处置结论 | 证据入口 |
|---|---|---|---|
| **旧结构被替代** | `I-01, I-06, I-10, I-17, I-19, I-27` | TX/RX 主线已采用 CMOS/SST。原三叠层 CML ÷8 的 RC 疑点 `LAYOUT-PLL-DIV-RC-01` 保留于历史路径，片级反馈由 I-TOP-02/03 承接 | [TX](../design/tx_sst_v4.md)、[÷8](../design/pll_tspc_reclock_divider.md) |
| **由数字 v3.1 和 RX v2.2 在模块边界验证** | `I-15, I-16, I-18` | STA、RTL 与 SDF 回归按各自时钟和驱动边界继承。跨宏路径由 I-TOP-01/02 承接 | [数字顶层](../design/digital_top_v3.md)、[RX](../design/rx_cmos_v2.md) |
| **由 PLL v4、VCO PTAT、BIAS v2、LDO v2_cur 提供局部证据** | `I-04, I-05, I-09, I-12, I-13, I-32, I-34` | 保留已验证的物理宏、原生固定码锁定和相噪模型。系统噪声与实际负载由 I-TOP-02/05 承接 | [PLL/VCO](../design/pll_vco_r6_perf.md)、[BIAS](../design/bias_v2.md)、[LDO](../design/ldo_v2.md) |
| **承接至片级集成阶段** | `I-02, I-03, I-07, I-08, I-11, I-14, I-20, I-21, I-23, I-28, I-29, I-30, I-33, I-35` | 跨宏寄生、封装、原生时钟联调、冷启动、后仿和信道覆盖由上表 I-TOP-01/02/04/05 跟踪 | [执行计划](prelayout_plan.md) |
| **长期维护项** | `I-22, I-24, I-31` | Xschem 仍为早期 CML 导出快照（权威以 `spice/` 为准，见 [schematics.md](../history/schematics.md)）；新台继续遵循边界登记与默认冒烟约束 | [methods.md](../verification/methods.md) |
