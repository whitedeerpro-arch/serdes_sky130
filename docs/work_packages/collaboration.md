# 协作、资源与接手

长期执行规则见[工作流](../status/workflow.md)，技术决定见[架构决定](../status/architecture_decisions.md)，任务顺序与流片验收顺序只在[执行计划](../status/prelayout_plan.md)维护。本页只登记当前活跃开工范围、仿真资源和短交接。技术主线归 Fable；Codex 承接工作组织、基础设施、局部实现和复核。

## 开工与共享工作区

开工先读 [current.md](../status/current.md)、[执行计划](../status/prelayout_plan.md)、对应模块、最近协作记录和 `git status --short`。在本页写具体文件/任务范围再改共享文件；没有永久模块禁区。未提交改动先核对归属，不能代为清理或提交；只暂存自己审阅过的路径/段落，不 `git add -A`，不 reset/stash/checkout 他人进行中文件。提交前检查 cached diff；不得把 HEAD 当成与脏工作区相同的输入。

跨执行器交付按[工作流](../status/workflow.md)执行，必须给定输入身份和可编辑范围，结果由集成者独立复核。是否派发子 agent 以当前会话的明确授权为准。

## 仿真资源

全机 `ngspice ≤ 4`。依[架构决定](../status/architecture_decisions.md)由集成者按主线分配，撤销旧固定 2+2 叙述。开跑前同时查登记和实时进程；`pgrep -x ngspice | wc -l` 只反映当时占用，不能代替互相登记，也不能假定日志里“已归还”仍有效。内存/MC 按[实测规则](../verification/statistics.md#执行续跑与成本)。

一次登记包含：任务/执行者、具体可写文件、campaign 与输入身份、worker、时限/终点、启动/暂停/归还状态、续跑命令与下一步。临时借用先说明，不抢占或终止他人的进程；没有记录为仍有效的明确配额就先与集成者协调。

## 活跃登记与交付（2026-11-26）

- 5G 非凸轮廓与端口数据回代整片试排。实装模拟层次、131 块瓦片与护沟通过摆位 DRC，包含 QDiv2 与 TX 外接矩形重叠的实例。顶层布线与电气边界见试排收据。无 ngspice 名额占用。[对照与结果](../layout/chip_floorplan_20261123.md#13-非凸形状回代整片试排)

- 5G 13 宏非凸形状和原生端口复核完成。保留独立多边形、凹位嵌放和改口验证。实装 LC 父层护环短接有源电源，M4 跨越副本通过局部 DRC 与层级连通，采用与带载复核随 I-TOP-01。无 ngspice 名额占用。[非凸形状与端口](../layout/chip_floorplan_20261123.md#12-各宏的非凸轮廓与端口迁移)

- 5G 竖置 LC 与长条 hard macro 试排完成。两个候选以真实模拟层次、131 块瓦片和护沟通过摆位 DRC。东置接收器限制来自 I/Q 路径，本地接收器增加西区占位。独立 LDO 窄 MIM 阵列保留器件尺寸及数量，通过 DRC/LVS。无 ngspice 名额占用。[试排及边界](../layout/chip_floorplan_20261123.md#11-竖置-lc-vco-与长条宏试排)

*2026-11-26 之前的历史交接、阶段工作包与早期资源登记已归档至 git 历史（提交 `b10e989` 与标签 `v1.0`）。*

- 2026-11-26 / Codex / 4G `full_v8` 与 5G Plan C 只读物理复核完成。Magic 提取与 GDS 直尾筛查均已收据化。顶层参考和复位等接口的逐端封闭、4G 时钟偏置短接、5G PI 端口重排及加载后的 I/Q 相位由各自片顶任务承接。无仿真名额占用。[复核报告](../layout/chip_floorplan_20261123.md#10-实装金属与分析缺口复核2026-11-26) · [输入哈希和复算记录](../../results/catalog/chip_physical_audit_20261126.json)

- 2026-11-26 / Antigravity / **5.0 Gb/s 全套模拟加固收口 + 端口协同数字 `v4p1` + 5G Plan-C 全片物理装配与层级签核交付（全部 `ngspice` 已归还，实时 `0 NG`，零触碰 `v1.0` 与 Codex 文件）**（[5G 签核台账](../../results/catalog/serdes_5g_signoff_20261126.json) · [Plan-C 全片报告](../layout/chip_floorplan_20261123.md#9-50-gbs-plan-c-全片物理装配与层级签核2026-11-26)）：
  - **1. 5G 模拟最后三项加固全面签核（均独立隔离变体目录，均已逐张目检 PNG）**：
    - **5G 1:1 直插 Double-Tail 采样器 `slicer_5g_pdk`**（`analog/rx/cmos_rx/layout/variants/slicer_5g_pdk/` · `results/analog/rx/slicer_5g_hardening_20261125/summary.json`）：`29.60 × 31.54 µm`（与 4G 1:1 框/13 端口全吻合，`DRC=0 / FP=0 / LVS=MATCH / M5=0%`）；真 CPEX **6/6 角 PASS**（`99–259 ps @ ±10 mV`、迟滞 `0.00–0.50 mV`、`C_in` 较 4G 降 `4.4–10.4%`）；**250/250（100% 未截断）`_mm` MC**（`σ_Vos = 6.09–6.77 mV`, `3σ ≤ 20.30 mV`, 6-bit 修调覆盖 `≥ 8.05σ`）；
    - **5G TX SST 顶层 `v5_pdk`**（`analog/tx/sst/layout/variants/v5_pdk/` · `results/analog/tx/tx_sst_5g_v5_20261125/summary.json`）：`256.80 × 169.58 µm`（5/5 PDK 单元全 `DRC=0 / FP=0 / LVS=MATCH / 38/38 端口 / rc_dev_ok=True`）；真 Magic CPEX **16/16 PASS**（12/12 5G + 4/4 4G，边沿散布 `0.006–0.145 UI ≤ 0.15 UI`，`Vdrv_rip = 3.6–44.3 mVpp`，彻底根除 `SS/SF -40°C` 212–282 mVpp 切片直通，眼裕量 `100.1–226.7 mV`）；
    - **5G `4→8` I/Q CMOS PI 冷角加固版 `v5g_4ph_v3_pdk`**（`analog/rx/cmos_rx/layout/variants/v5g_4ph_v3_pdk/` · `results/layout/rx_cmos_5g/pi_4ph_v3/signoff_summary.json`）：仅加固 `qdiv2`（混合 PMOS 消除冷角过驱动断崖 + 单向 2-FET `N_LVT` 注入器 + 居中 `Xdet1`），`173.38 × 72.72 µm`（1:1 外框与 43/43 端口吻合，`DRC=0 / FP=0 / LVS=MATCH / M5=0%`，保留 `x=46.2/156.0` 宽 M4 无障碍通道）；真 CPEX **6/6 标称角（24/24 码×复位）`ALL_OK=True`**（`3.00–10.66 ps`、单调、Hi-Z `≤ 4.5 mV`）；24 样本冷角 `ss_mm 1.65 V -40 °C` MC：**`0/24` 180° 翻转（原 3/24）、`0/24` 停振（原 1/24，`min_swing=106.45%`）、`22/24` 0° 锁定、`20/24 < 30 ps`（较 `v2` 提升 `2×`、严格门控 `1/24 → 20/24`）**，并定量归因剩余 4 样本尾差源于未改动的 `v2` `pi4_diff_rec` SVT-PMOS 冷角偏斜（`±20 ps`）；
    - **5G RX 顶层热插全签核**（`analog/rx/cmos_rx/layout/variants/rx_top_5g_pdk/summary.json`）：合入 `v5g_4ph_v3_pdk + slicer_5g_pdk + W3 CTLE` → `312.10 × 199.40 µm (62,232.7 µm²)`、**`DRC=0 / FP=0 / DC-LVS=MATCH / Open-LVS=MATCH / 72 & 74 端口全齐`**、`ctle_p/n = 57.29 / 57.54 fF`（`0.24 fF` 差分均衡）。
  - **2. 紧缩 5G 混合去耦瓦片与端口协同数字顶层 `v4p1`（0 NG）**：
    - `verification/layout/decap_5g_tiles.py`：紧缩 `20.8 × 17.2 µm = 357.8 µm²`（较 4G 缩 `-12.6%` / 电容密度 `+14.5%`）、`L=2.0 µm` 5 指低 ESR MOS + `8×8 µm` 叠层 `MIM1+MIM2`（Direct `1.265 pF` / Damped `1.05 pF + 121 Ω res_high_po_5p73` / HV33 `0.622 pF`），三单元及平铺 `2×2` 棋盘格全 **`Magic DRC = 0`**；
    - `digital/pnr/run_v4p1_5g_coopt_pnr.py` → `digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/`：**`385.90 × 353.60 µm = 136,454 µm²`（面积 `-7.2%`、`Util = 75.0%`、`WL = 191.3 mm`、内置 `88.9 pF` decap）**，6 角 ±5% OCV 5G & 4G 时序全 MET（`setup ≥ +0.059 ns / hold ≥ +0.073 ns`），CDC `26/26 sync1 fanout=1`，**`Magic DRC = 0`、`Netgen LVS = MATCH`**，33 位 RX 端口与 `rx_top_5g` 北口 1:1 零交叉对齐。
  - **3. 5G 全片 Plan-C 物理装配、合并 GDSII 与真实层级防短路签核（0 NG）**（`verification/layout/build_chip_top_5g_pdk.py` · `verification/layout/plot_chip_top_5g_pdk.py` · `results/layout/chip_top_5g_20261126/plan_v4p1/summary.json`）：
    - **规格与布局**：`936 × 650 µm = 0.6084 mm²`（较 Plan A `-21.8%`、`AR = 1.44`），13 颗真实签核 5G 宏密度 **`70.3%`**，8 组紧缩 Direct/Damped/HV33 去耦阵 **`10.9%`**（131 块瓦片 = **`147.03 pF`** 顶层 + 宏内置共 `~331 pF`），双 P+ 衬底隔离沟槽 + 7 域独立 M5 电源环 + 闭环 14 µm M5 VSS 环，TX 正南 `TX_PAD_P/N` ⊥ RX 正东 `RX_IN_P/N` 90° 正交；
    - **多层次布线实测**：RX 33-bit 数据/边沿/时钟 **`0` 交叉**（`max_dx = 0.23 µm`、`937 µm`、`2L M4` 直连）；TX 17-bit `1,659 µm`；2.5G CML `VCO→Host` 镜像绕避偏置 `99.5 µm` 均长；`LF→VCO vctrl` `49.8 µm`；24-bit RX PI 控制 `3L` 解耦 `M2/M3/M4` 实绘；
    - **全套签核收据**：Python 预审 `99/99` 信号 `0` 开 `0` 短 / `8/8` 域 / `28/28` 宏电源地 / `8/8` 去耦阵 / `0` 顶层间距违例；**Magic 全规则 `DRC_TOTAL = 0 (0 rules)`**；合并 GDSII **`55.43 MB`**（`serdes_5g_top_pdk.gds` SHA-256 `4ca91bbd21b8…`、`.mag` SHA-256 `1332d300d985…`）；**Magic 真实层级 `extract all; ext2spice lvs` 门控 `hier_audit_ok = True`（`conn = 28/28`, `diff = 41/41`）**，证明全部 8 供电域严格独立、Codex `icml_vs_vss` 门控通过、`vctrl / fb250 / clkp/n / RX_IN_P/N / TX_PAD_P/N` 全无隐蔽宏内短路；深/浅色 240-DPI 真硅层渲染图已生成并目检通过。`ngspice = 0`。
