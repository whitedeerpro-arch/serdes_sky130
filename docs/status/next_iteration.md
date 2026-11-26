# 下一版与延后候选（Phase 2+）

本页记录**不纳入当前 2026-11-26 双速 4/5 Gb/s Plan-C 首片流片收口**、留待后续迭代推进的拓展方向。

> **注**：原延后项 **5.0 Gb/s（200 ps UI）双速 LC-PLL + 32-bit 降频数字顶层 `v4p1` + Plan-C 全片物理装配**已于 2026-11-26 升级为主推设计并完成核心签核，状态统一维护在 [current.md](current.md) 与 [5G 签核台账](../../results/catalog/serdes_5g_signoff_20261126.json)；流片前收口队列见 [prelayout_plan.md](prelayout_plan.md)。

| 方向 | 工程目标与现状 | 纳入主线条件 |
|---|---|---|
| **5G PI `pi4_diff_rec` 混合 PMOS 升级与端口二次压紧** | `PI v3` 已将冷角 MC 锁相/偏斜提升至 `20/24 < 30 ps`（零翻转/零停振），剩余 4 样本尾差已定量归因于未改动的 `pi4_diff_rec` SVT-PMOS；同时数字→PI 24 线尚有约 `0.97 mm` 绕行余量 | 首片收口或下一版迭代中需将冷角 MC 进一步拉满至 `24/24 < 30 ps` 及缩减 PI 控制布线偏斜时启用 |
| **800 mVpp 高摆幅 TX 选项** | 需采用 P-over-N SST + NMOS 输入 / PMOS 调整管子稳压器以满足 1.65 V 低压角裕量（常规 N-over-N 在 1.65 V 下受限） | 明确长距离/高损耗信道需求与功耗/面积预算后再启用 |
| **1.5 V 低纹波独立供电域** | 将 VCO 或 VCO + CP/LF 独立至 1.5 V 域，进一步压缩供电敏感度 | 当前 HV18 Kelvin LDO（`v2_cur_kelvin_pdk`）在实装片级 PDN 联合仿真中出现余量不足时触发 |
| **更强损耗信道（C3 10 dB+ / C4–C5）与编码/均衡** | 评估 8b/10b、64b/66b、轻量 FEC 或 DFE / 多抽头 FFE 均衡（信道族定义见 [channel_model.md](../design/channel_model.md)） | 所有者确认协议层编码与目标信道门槛后启动 |
| **量产 DFT 扩展（Scan/ATPG、JTAG、MBIST）** | 首片已规划最小可定位测试入口（见 [prelayout_plan.md](prelayout_plan.md#首片-dft-最小测试入口)）；若转量产再引入全扫描链、边界扫描及（若用 SRAM）MBIST | 明确量产故障覆盖率目标或更换 FIFO 存储实现时启动 |

双速反馈 A（÷8/÷10）与精准数据分频 B 的架构拆分依据见 [PLL 反馈 A 与精准分频 B](../design/pll_feedback_data_dividers.md)。
