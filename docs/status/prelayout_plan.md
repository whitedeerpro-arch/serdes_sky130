# 执行计划与里程碑

**阶段状态（2026-11-24）**：`v1.0` 保留独立宏验证与片级规划。片级布线修复、模拟联调短窗以及新版反馈和分频候选证据见[当前状态](current.md#4-发布后的片级集成证据)。

---

## 1. 当前主线与路线图

```mermaid
flowchart LR
    S1["第一阶段：4G SerDes 初稿\n21 宏 DRC/LVS + 模块后仿（已完成）"] --> S2["第二阶段：顶层片级整合\nPadring/ESD + 顶层布线 + RCX"]
    S2 --> S3["第三阶段：整机联合验证\n锁定 PLL → TX → PCB → RX → CDR"]
    S3 --> S4["第四阶段：全角与良率加固\nRX 45 角 CPEX + ÷8 冷角 MC"]
    S4 -.-> S5["延后拓展（独立分支）\n5 Gb/s / 800 mVpp（exp/5g-stretch）"]
```

---

## 2. 下一阶段可执行队列（顶层集成与加固）

| 顺序 / 任务 | 目标与最小动作 | 退出条件 | 关联项 |
|---|---|---|---|
| **1 / TOP-SYNC** | CP v4.1 与 TX `V_drv` 子稳压器泄放微修已完成本机几何复核。固定交付身份与提取输入，复核微修改变的 CP 关断边沿、TX 轻载稳定性和焊盘眼图 | 带身份的 `review_cell.py --rc` 收据和受影响工况电气回归可独立复核 | [pll_cp_v4.md](../design/pll_cp_v4.md)、[tx_sst_v4.md](../design/tx_sst_v4.md) |
| **2 / TOP-ROUTE** | 合入独立复核的北侧去耦接地移线。以同一版数字 RTL、PnR 和装配 GDS 收口慢角时序及 GLS。补控制/偏置/宏供电、Padring/ESD，复核分域去耦与实载八相时钟 | 最终顶层 Magic 全规则 `DRC = 0`、Netgen `LVS = MATCH`，2 GHz 钟树偏斜 `< 5 ps`，提交 RCX 与静态 IR drop | [片级装配](../layout/chip_floorplan_20261123.md) |
| **3 / TOP-COSIM** | 在已通过短窗功能筛查的 `r5` + SAFF-TSPC ÷8 反馈候选上补持续判锁；接动态 TX、`C2_loss6`、独立 RX 时基和数字 CDR/FIFO，并回灌顶层互连提取 | 典型角与压力角 PLL 带载保持锁定、端到端功能与位映射正确、CDR 正常跟踪，记录预充捕获和从零启动的各自结果 | [当前状态](current.md) |
| **4 / YIELD-HARDEN** | RX v2.2 CPEX 扩至 MOS45；加固 ÷8 按原样本身份复核冷角启动，补候选提取后失配；更新电源域噪声与联调后的抖动预算 | RX MOS45 全部满足适用门槛。÷8 冷角提交完整 CPEX MC 样本和失效分布，按已有偏斜/功能门槛复核 | [RX](../design/rx_cmos_v2.md)、[÷8](../design/pll_tspc_reclock_divider.md)、[PVT](../verification/pvt_coverage.md) |

---

## 3. 已完成与历史里程碑记录（2026-11-13 — 2026-11-23）

早期 CML 的 M0–M6 队列见[阶段快照](../history/prelayout_plan_snapshot_20261113.md)。已复核的独立宏结果保留在[当前状态](current.md)，待集成的接口由本页队列承接。5 Gb/s、800 mVpp 与 1.5 V 域登记在[下一版](next_iteration.md)。
