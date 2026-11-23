# 下一版与延后候选（Phase 2+）

本页记录**不纳入当前 4 Gb/s Zero-CML 初稿发布**、留待后续迭代推进的拓展方向。当前主线状态见 [current.md](current.md)，顶层集成队列见 [prelayout_plan.md](prelayout_plan.md)。

| 方向 | 工程目标与现状 | 纳入主线条件 |
|---|---|---|
| **5 Gb/s（200 ps UI）提速与 Sub-1 ps PLL** | 探索性源码与初步仿真已隔离保存在本地分支 `exp/5g-stretch`（含 2.5 GHz 三架构 VCO 对比、Sub-1 ps 稳压 CMOS 环振 v2、5 GHz LC-VCO + ÷2 方案、5 Gb/s PI/解串摸底） | 完成 4 Gb/s 顶层片级整合后，在独立分支补齐 LC-PLL 闭环锁相与 5 Gb/s 端到端链路签核再评估合入 |
| **800 mVpp 高摆幅 TX 选项** | 需采用 P-over-N SST + NMOS 输入 / PMOS 调整管子稳压器以满足 1.65 V 低压角裕量（常规 N-over-N 在 1.65 V 下受限） | 明确长距离/高损耗信道需求与功耗/面积预算后再启用 |
| **1.5 V 低纹波独立供电域** | 将 VCO 或 VCO + CP/LF 独立至 1.5 V 域，进一步压缩供电敏感度（历史分析见 [pll_supply_variants.md](../design/pll_supply_variants.md)） | 当前 HV18 `v2_cur` 方案在片级 PDN 联合仿真中出现余量不足时触发 |
| **更强信道（C3 10 dB+）与编码/加扰** | 评估 8b/10b、64b/66b 或 DFE/多抽头 FFE 均衡（信道定义见 [channel_model.md](../design/channel_model.md)） | 所有者确认协议层编码与目标信道门槛后启动 |

*历史快照保留在 [next_iteration_snapshot_20261110.md](../history/next_iteration_snapshot_20261110.md)。*
