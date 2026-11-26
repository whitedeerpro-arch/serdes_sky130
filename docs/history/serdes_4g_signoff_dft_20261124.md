# 4 Gb/s 片级签核和首片测试性复核

2026-11-24。`v1.0` 的子系统签核证据继续有效。合入后续宏的 `full_v5` 取得核心装配 DRC 收据。首片流片仍需完成顶层供电、控制、焊盘与 ESD，随后在同一版 GDS 上验收全片 LVS、寄生和电气边界。测试性宜在定 pad map 时一起设计，首片优先做可读状态、独立激励和板级误码测试。正式扫描链的范围由生产测试目标决定。[项目状态](../status/current.md) · [片级关闭条件](../status/open_issues.md)

## 已核对的版图证据

`full_v5` 的 `magic_top.log` 为 `TOP_DRC_TOTAL 0`。装配摘要列出 20 个宏、208 块去耦、101 条受查信号无开短路、8 个互异电源网根（含 VSS）和 12 组接通的去耦。用 KLayout 读取合并 GDS，根单元有 12 个标签，分别是 TX/RX 差分端 4 个及电源和地 8 个。四条高速线止于片边 M5 矩形。根层实例为功能宏和去耦阵列，完整的 pad/ESD 尚待实装。[装配摘要](../../results/layout/chip_top_20261123/full_v5/summary.json) · [Magic 日志](../../results/layout/chip_top_20261123/full_v5/magic_top.log) · [装配生成器](../../verification/layout/build_chip_top_pdk.py)

- `PFD.ref/rst_b`、数字 `ref_clk/rst_n/arst_n` 与 `cp_en/pfd_rst_b` 未纳入 101 条清单。按 MAG 的实例变换将这些宏端口标记投影到顶层，所在金属层均未见与标记重叠的顶层走线。数字 `VPWR/VGND` 各 8 个标记，以及抽查的 CP/TX/RX 供电、地标记也未命中。对照点 `LDO.vin/quiet` 和 `VCO.vdd_q` 均命中。该几何抽查只查标记区域，完整导电路径和器件端子仍由层次 LVS 判定。[装配 MAG](../../results/layout/chip_top_20261123/full_v5/serdes_4g_top_pdk.mag) · [数字宏接口](../../digital/pnr/rtl_v3/serdes_digital_top_v3.sv)
- 供电和控制端口宜从顶层参考网表生成全端子矩阵，逐项标明功能连线、测试连线或有意端接。顶层参考网表同时明确 `VDD_Q` 由片上 LDO 驱动，片边接口承担的供电、旁路和测量功能，以及独立 3.3 V/1.8 V 电源顺序。该矩阵可用于 LVS 后逐项定位遗漏。[I-TOP-01/02](../status/open_issues.md#1-当前-4-gbs-nrz-serdes-开放项顶层集成与良率)

GDS SHA-256 `fbac5a9e26d3a6c9af4c637051a93895a38b68f76f42af80b044884acc869909`。MAG SHA-256 `178c5aaf79ab0d0f9b5aff136057da0b5253afe0624bd1732171f5b38a9f8ba4`。

## IR/EM 修正与剩余验证

`full_v4` 的加宽环、LDO→VCO 直供和多孔阵列已进入 `full_v5`。静态报告用 `build_domain_specs()` 中的坐标、宽度、源端和分摊电流解节点网络。优化模型中 `VDD_Q` 从 190.2 mV 降至 10.53 mV，过孔/金属 DC EM 最大利用率 71.9%。这些读数用于比较拓扑，最终压降取决于实装几何、端子连通、边界与负载。[静态模型](../../verification/layout/analyze_chip_ir_em.py) · [IR/EM 报告](../../results/layout/chip_top_20261123/ir_em_audit_20261124/summary.json)

| 抽查点 | 静态优化模型 | `full_v5` 顶层几何 |
|---|---|---|
| `VDD_Q` 直供主干 | 16 µm M5 并 12 µm M4 | `x=342 µm` 的 14 µm M5 主干，在 `y=350 µm` 处无对应并联 M4。VCO 分支含 24 孔 via4 阵列 |
| `VDD_HV33` 入口 | 支路用 30 孔 via4 | 北侧 VSS 下穿在 `y=598/634 µm` 各有 25 孔 via4，沿供电路径先后经过 |
| `VDD_A` 时钟负载主干 | 12 µm M5 并 10 µm M4 | 北环已加宽至 12 µm M5。`x=355 µm, y=460 µm` 的内侧去耦干道只测得 3 µm M4，时钟宏供电需逐端核对 |

沿 LDO `quiet` 至 VCO `vdd_q` 的正轨，用实际线段中心线估算。M5 `18.4 µm / 12 µm`、`256.74 / 14`、`63.7 / 12` 三段，接 24 孔 via4 与 M4 约 `8.6 / 11`。沿用模型 `0.036/0.056 Ω/□`、`0.89 Ω/孔` 及 VCO 峰值份额 `22.5 mA × 0.92`，得到约 `0.99 Ω` 和 **20.4 mV**，高于模型的 15 mV 预算。这是单支路近似，交接形状、阵列分流、内部金属、回流及负载同时性由提取重算。第一步可只提取 LDO、VCO、CP 的供电和回流网络并保留各过孔，再用相同电流边界解释差异。[顶层 MAG](../../results/layout/chip_top_20261123/full_v5/serdes_4g_top_pdk.mag)

现有 PDN 稳定性台还已覆盖封装电感代理、去耦阻尼和数字脉冲。用实装 pad/键合线、每域瓦片和回流 RC 更新模型后，先注入上电、TX 训练切 PRBS、数字忙闲切换和 RX 重获锁的电流，量 VCO 端 `VDD_Q−VSS`、LDO 压差和环路抖动，其他域按端点压降和过孔电流验收。[现有动态 PDN 台](../../verification/stability/verify_supply_stability.py) · [静态 IR 方法参考](https://openroad.readthedocs.io/en/latest/main/openroad/psm/README.html)

## 首片 DFT 建议

| 硅上要定位的阶段 | 最小测试入口与验收 |
|---|---|
| 上电、参考和 PLL | 保留参考时钟、复位、PLL 启停。用低速接口读 `pll_locked/state_id/fault_code` 和 VCO 粗码。通过独立缓冲读出分频时钟，区分参考未到、反馈无边沿和有反馈但未锁。接口的读写和复位以 PLL 失锁时仍可用为验收条件 |
| TX 独立发射 | 在现有 16 位字域选择固定图样、训练字和 PRBS7/31，或定义可持续供数的外部 BERT 路径。用实际 TX pad、板线与仪器观察摆幅、眼图和位序 |
| RX 独立接收 | 外部 BERT 从 RX pad 注入数据和可控 ppm。通过快照读 `rx_cdr_locked`、PI 码、`rx_aligned`、`host_error` 以及累计有效位、误码、失锁和溢出。检查器须注明观测点，在失锁期间显式记事件。额定 BER 用全路径观测点验收 |
| 整链和数字定位 | 板上回环覆盖 TX/RX pad、ESD、封装与互连。同源回环后用独立时钟验证频偏跟踪。现有 FIFO 可做功能性的写满、读空、位序和跨复位测试 |

现有 RTL 已有多数状态和启停信号，需通过片级读出路径接出。PRBS 出现在测试台。可先定一个可在失锁时工作的低速寄存器通道，优先复用可用的管理接口。若片上做 BER 统计，至少 42 位有效位计数可容纳额定测试窗口，并用一致的跨域快照读出。4 Gb/s 下零误码要累计约 `3×10¹² bit`，约 12.5 分钟，单侧 95% 上界才接近 `10⁻¹²`。训练及失锁事件另行记录。[数字宏接口](../../digital/pnr/rtl_v3/serdes_digital_top_v3.sv) · [链路规格](../overview/spec.md)

首片可测性应随 pad map 收口。若面向量产或有数字故障覆盖率目标，再在综合和布局早期加 scan/ATPG，明确各域的移位与捕获时钟、复位、模拟输出安全状态和测试模式 STA。当前标准单元映射流程可从 scan FF 和工具能力验证起步。JTAG 视测试接口和板级边界扫描要求选用。当前 FIFO 以标准单元实现，有 SRAM 宏时再按存储工艺与量产覆盖率考虑 MBIST。[数字实现流程](../../digital/pnr/run_pnr.py) · [OpenROAD DFT](https://openroad.readthedocs.io/en/latest/main/openroad/dft/README.html)

## 流片前建议的验收顺序

1. 在同一张 pad map 锁定供电、地、功能、测试和封装。完成 ESD、供电顺序、掉电倒灌和 3.3 V/1.8 V 器件应力 ERC。选择高速 I/O 保护时，把电容和返回路径放回 TX/RX 信道模型。[SKY130 I/O](https://skywater-pdk.readthedocs.io/en/main/contents/libraries/sky130_fd_io/docs/user_guide.html)
2. 对最终 GDS 执行全片 LVS、工艺要求的 DRC/密度/填充/天线检查，并留存填充后提取收据。数字 STA/GLS 绑定数字宏实际版本，跨宏时钟和数据使用最终寄生。优先查参考、复位、供电和 ready/enable，再查高频八相、字时钟和 32 位 RX 回接。[SKY130 天线规则](https://skywater-pdk.readthedocs.io/en/main/rules/antenna.html) · [片级问题登记](../status/open_issues.md)
3. 基于同一提取版本签静态 IR/EM 和动态供电，先复测 VDD_Q 与关键压力角。用实际 ÷8 和数字控制做冷启动、掉锁重获和时钟停止/重来，再回归受改宏、封装信道、相噪和抖动。按已有 I-TOP 收据逐项承接，45 个 PVT 功能门槛及实验室 BER 按规格记录。[PVT 覆盖约定](../verification/pvt_coverage.md) · [片级关闭条件](../status/open_issues.md)
