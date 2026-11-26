# 演进笔记与关键改动备忘

这份小笔记随手记下本项目从早期原型一路收敛到现行双速 **4/5 Gb/s Plan-C** 架构过程中最值得记住的几次路线切换和踩坑经验。完整历史过程文件已退出工作树，若需逐日溯源或回放旧电路，直接查 Git 历史（`v1.0` 标签 `10fdcad` 与 2026-11-26 整理前全量快照 `b10e989`）。

## 路线怎么走过来的

1. **阶段 0 — 早期全 CML 原型（2026-10 末 `v0.1`）**
   - 最早整条链路都是全 CML（CML 16:1 串化器、CML 时钟分发、CML 线驱动、CML RX PI/采样、三叠层 CML ÷8、Ring VCO `r1–r5`、HV18 LDO `r1–r4`、BIAS v1）。
   - **为什么换掉**：CML 在 SKY130A 1.8 V 工艺下功耗和静态电流过大（全链路逼近 100 mW+）、低电压冷角（1.65 V −40 °C）叠层裕量吃紧，且版图面积与偏置分发复杂度高。

2. **阶段 1 — 4.0 Gb/s CMOS/SST + 环振 PLL v4（2026-11 中下旬 `v1.0` / `full_v8`）**
   - **TX 切到 CMOS/SST（`v4.3`→`v4.5`）**：16:4 CMOS 串化 + 四相 N-over-N 28-slice SST 驱动（自带 2-tap FFE 与片上 `VDRV` LDO），面积/功耗大幅下降且焊盘眼图在 45 PVT 全角通过。
   - **RX 切到纯 CMOS 架构（`v2.2`→`v2.3`）**：100 Ω 端接 + CTLE + 2 GHz 64 码纯 CMOS PI + 四分之一速 Double-Tail 采样器 + 8→32 解串，摆脱 CML 尾电流。
   - **PLL 升级到 v4**：四级环振 `r6` + BIAS v2 PTAT（`28/66`，跨三温单码覆盖）+ 带 1/4 副本主动伺服的 `CP v4` + 6-site 融合 MIM 环路滤波器 + 标准单元 `PFD sc_dly` + `r5` CML→CMOS + SAFF-TSPC ÷8；供电与偏置升级到 `HV18 LDO v2_cur` + `BIAS v2`。
   - **数字顶层**：从零散多宏收拢为统一精简宏 `serdes_digital_top_v3`（`v3.1/v3.2`），完成 4G 核心装配 `full_v8`（Magic `DRC=0`）。

3. **阶段 2 — 5.0 Gb/s 双速（4/5 Gb/s）Plan-C（2026-11-24..26 现行主线）**
   - **为什么升级 LC-VCO 与分频**：5.0 Gb/s 线速下 2.5 GHz 环振在 SKY130A 慢热角频率与相噪裕量触顶，改为 **5.0 GHz 八边形片上电感 LC-VCO + 正交 ÷2**（`lc_vco_5g_oct_pdk`，全角公共调谐交集 `4.469–5.350 GHz`、125 °C 冻码通过），配 **双速 A/B 分频 ÷8/÷10**（`div_ab_5g_v2_pdk`，50/50 冷角 MC 全过、M5=0%）原生兼容 4G 与 5G。
   - **模拟全套 5G 加固**：HV18 LDO 增加 Kelvin 远端感测（`v2_cur_kelvin_pdk`，等效输出阻抗 `-92.9%`）；TX SST 升 `v5_pdk`（4/5 Gb/s 16/16 真 CPEX 全过）；RX 切到 **W3 紧凑 M4+M2 叠层电感分流峰化 CTLE + 4→8 I/Q CMOS PI v3 + 1:1 直插 5G Double-Tail 采样器**，合装 `rx_top_5g_pdk`（`DRC=0 / FP=0 / DC & Open LVS=MATCH`）。
   - **数字降频 32-bit 与端口协同**：早期 24-bit 字节齿轮箱与 20-bit/312.5 MHz 方案在 1.65 V 冷角综合/时序代价过高，最终收敛为 **32-bit 双速降频顶层 `serdes_digital_top_v4`**（125/156.25 MHz 字域），并按片顶方位重排西边 33-bit RX 端口得瘦身版 **`v4p1`**（`385.9 × 353.6 µm`，`-7.2%`，RX 33-bit 0 交叉，6 角 OCV 全 MET）。
   - **Plan-C 全片装配与工具沉淀**：新增多层曼哈顿自动绕线（`route_manhattan.py`）、退火布局规划（`floorplan_opt.py`）与紧缩 5G 混合去耦瓦片（Direct + `121 Ω` Damped + HV33，`20.8 × 17.2 µm`），完成 `serdes_5g_top_pdk`（`936 × 650 µm = 0.6084 mm²`，131 块去耦 `147.03 pF`，Magic `DRC=0`，`ext2spice lvs` 28/28 连通 + 41/41 隔离）。

## 几个容易重踩的实用经验

- **层级 LVS 一定要跑真 `ext2spice`**：仅靠顶层 Python 几何连通检查容易漏掉顶层 M4/M5 走线压到宏内同层电源/信号金属的隐蔽短路（5G Plan-C 通过真实层级提取抓出并修清了 4 处跨宏隐蔽短路，4G `full_v8` 亦据此查出了 `icml` 与 `VSS` 短接）。
- **SKY130A 失配与高阻多晶硅噪声坑**：`g5v0d10v5` HV MOS 的 `vth0_slope=0`、`cap_mim_m3_1` 的 `mf` 不乘名义电容、`xhigh_po` 行为电阻热噪声在 ngspice 47 中严重偏低，详细数值留存在 [统计方法](../verification/statistics.md)。
- **4G/5G 现行边界统一看**：[当前状态](current.md)、[片级版图与实装复核](../layout/chip_floorplan_20261123.md) 与 [执行计划（含首片 DFT 与流片验收顺序）](prelayout_plan.md)。
