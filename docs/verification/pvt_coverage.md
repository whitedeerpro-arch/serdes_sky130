# PVT 覆盖口径与结果入口

**当前各模块的覆盖数字、实际驱动和缺测统一见[current.md](../status/current.md)。** 本页维护矩阵含义、继承规则和查询方法；具体版本签核台账见 [v1.0 证据目录](../../results/catalog/v1_0_subsystem_evidence.json) 与 [5G 签核台账](../../results/catalog/serdes_5g_signoff_20261126.json)。

## 矩阵与验证维度

| 维度 | 范围与解释 |
|---|---|
| MOS/VDD/温度 | 5工艺×3电压×3温度，共45；功能与适用规格全部要求满足 |
| 无源角 | 45×tt/hh/ll是135；hl/lh按失效机理补，不把3库段称完整RC包络 |
| 器件实现 | 理想R/C、通用PDK电阻、定宽实体R、MIM及提取寄生分别标明；切换库段不会让理想C自动成为真实MIM |
| 输入和负载 | 理想源/回放/开环原生/闭环原生、偏置来源、实际扇出/信道、供电域和接口负载绑定到结果 |
| 动态场景 | 静态计数、动态数据、PI回卷、校准、预充捕获、从零启动分别判定 |
| 统计和噪声 | MOS角不替代局部MC，相同样本数不保证配对身份；无噪声零错不等于BER或抖动预算通过 |
| 物理与数字 | DRC/LVS/端口、PEX回测、库映射/STA/CDC分别留证；不互相替代 |

规格与门槛见[spec.md](../overview/spec.md)，PVT 网格定义见 [`serdes_flow.corners`](../../src/serdes_flow/corners.py)，PLL 锁定验收合同见 [pll_lock_screen.toml](../../verification/contracts/pll_lock_screen.toml)。

## 覆盖如何记录和继承

每条证据绑定：DUT修订/源文件身份、实际激励与负载、MOS/VDD/温度/RC、偏置及供电配置、控制/数据模式、初始化方式、实际终点/测量窗、判据和原始数据路径。条件执行完整与设计通过分别记录；未测、功能失败、数值未完成、ungraded不能并入通过数。

采纳修订前列清受影响的源、负载、器件、参数和测量。保持身份与适用边界的单元证据可继承；例如VCO改变不自动作废未改CP/分频的标准输入局部结果，也不把它们升格为新原生源全角通过。历史mutable include没有快照时，不能凭当前源码追认当时的尺寸/无源实现。

窗口类先在压力角完整扫描，其余条件可查门槛两端/中心，明确完整扫描与门槛检查的差异。补点按工况身份覆盖原表，不累加summary行数；长campaign按条件检查真实终点续跑。具体方法见[验证方法](methods.md)、[统计](statistics.md)及[工作流](../status/workflow.md)。

## 证据查询

从 [current.md](../status/current.md) 对应模块进入设计文档与目录台账（[results/catalog](../../results/catalog/README.md)），再定位各模块测试台与 `results/` 中的 deck/log/raw/metrics。

4 Gb/s `v1.0` 的数字顶层映射、三角 STA 和 SDF 模式见[数字顶层 v3.1](../design/digital_top_v3.md)；5 Gb/s 双速 32-bit 端口协同数字顶层 `v4p1` 的 6 角 ±5% OCV STA 与 CDC 签核见 [5G 签核台账](../../results/catalog/serdes_5g_signoff_20261126.json)。
