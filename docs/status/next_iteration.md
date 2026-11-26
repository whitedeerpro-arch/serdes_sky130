# 下一版与延后候选（Phase 2+）

本页记录**不纳入当前 4 Gb/s NRZ SerDes 初稿发布**、留待后续迭代推进的拓展方向。当前主线状态见 [current.md](current.md)，顶层集成队列见 [prelayout_plan.md](prelayout_plan.md)。

| 方向 | 工程目标与现状 | 纳入主线条件 |
|---|---|---|
| **5 Gb/s（200 ps UI）与亚皮秒 PLL** | 分支 `exp/5g-stretch` 有 TX、PI 和 VCO 局部探索。首轮字接口草案采用 250 MHz 参考与 ÷10，保留单路 16:4 TX，可用 20→16 转换接 250 MHz 主机。LC 低抖动估算、八相接口和环路面积见[PPA 与升级复核](../history/ppa_upgrade_review_20261124.md) | 补充 PI 慢角、实际电感/滤波寄生、÷10 带载闭环及 5 Gb/s 字域，按同一版做链路验收。[TX 发射管理草案](../design/tx_5g_word_interface.md) |
| **800 mVpp 高摆幅 TX 选项** | 需采用 P-over-N SST + NMOS 输入 / PMOS 调整管子稳压器以满足 1.65 V 低压角裕量（常规 N-over-N 在 1.65 V 下受限） | 明确长距离/高损耗信道需求与功耗/面积预算后再启用 |
| **1.5 V 低纹波独立供电域** | 将 VCO 或 VCO + CP/LF 独立至 1.5 V 域，进一步压缩供电敏感度（历史分析见 [pll_supply_variants.md](../design/pll_supply_variants.md)） | 当前 HV18 `v2_cur` 方案在片级 PDN 联合仿真中出现余量不足时触发 |
| **更强信道（C3 10 dB+）与编码/加扰** | 评估 8b/10b、64b/66b 或 DFE/多抽头 FFE 均衡（信道定义见 [channel_model.md](../design/channel_model.md)） | 所有者确认协议层编码与目标信道门槛后启动 |

*历史快照保留在 [next_iteration_snapshot_20261110.md](../history/next_iteration_snapshot_20261110.md)。*

对称主机接口的 24-bit 拼包、恢复时钟选择及跨域检查见 [TX/RX 的 24-bit 并行接口](../design/serdes_24bit_interface.md)。

5 Gb/s 的反馈 ÷10 与数据时钟 ÷2、÷4、÷8 分工见 [PLL 反馈 A 与精准分频 B](../design/pll_feedback_data_dividers.md)。
