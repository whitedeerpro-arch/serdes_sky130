# 协作、资源与接手

长期执行规则见[工作流](../status/workflow.md)，技术决定见[架构决定](../status/architecture_decisions.md)，任务顺序只在[执行计划](../status/prelayout_plan.md)维护。本页只登记实际开工范围、仿真资源和短交接。技术主线归Fable；Codex承接工作组织、基础设施、局部实现和复核。历史记录中的Claude署名与当时分工保留，不据旧署名另开技术路线。

## 开工与共享工作区

开工先读current.md、计划、对应模块、最近协作记录和`git status --short`。在本页写具体文件/任务范围再改共享文件；没有永久模块禁区。未提交改动先核对归属，不能代为清理或提交；只暂存自己审阅过的路径/段落，不`git add -A`，不reset/stash/checkout他人进行中文件。提交前检查cached diff；不得把HEAD当成与脏工作区相同的输入。

跨执行器交付用[工作包](README.md)，必须给定输入身份和可编辑范围，结果由集成者独立复核。是否派发子agent以当前会话的明确授权为准；保存可外发工作包不等于已经授权自动并行执行。

- 2026-11-25 / Codex / 4G 去耦释放、跨域摆位与 CML→CMOS 共轨试排。只读 `full_v8` 和现有瓦片 AC 数据，写独立 `results/layout/decap_release_*`、独立试验脚本、Codex 的宏摆位脚本和片级摆位文档对应小节。0 NG。
- 2026-11-25 / Codex / 供 Antigravity、Fable 接续 5G 片顶。4G `full_v8` 的层级 `.ext` 和 LVS SPICE 均显示 `bias_top_v2/icml`、`bias_cml_host/iin` 与四个 `cml2cmos_*/vbias` 并入 `VSS`。原层级门控未覆盖这组端点，发现记入 `docs/status/current.md` 的 `full_v8` 行。5G 构造已有独立 I/Q 共轨候选，侧置偏置版 `91.96 × 65.89 µm`、Magic DRC=0、Netgen LVS 一致，四个偏置端点同网且与两条供电轨分离。片顶连接偏置电流源后复用同一门控。Antigravity 的 PLL、RX 与 PI 活动目录仍由原执行者维护。[4G 偏置门控复核](../../results/layout/decap_release_20261125_fvy2da/as_built_bias_audit.json) · [5G 组宏复现及接入](../layout/chip_floorplan_20261123.md#5g-iq-时钟组宏)

## 仿真资源

全机ngspice≤4。依[架构决定第9条](../status/architecture_decisions.md)由集成者按主线分配，撤销旧固定2+2叙述。开跑前同时查登记和实时进程；`pgrep -x ngspice | wc -l`只反映当时占用，不能代替互相登记，也不能假定日志里“已归还”仍有效。内存/MC按[实测规则](../verification/statistics.md#执行续跑与成本)。

一次登记包含：任务/执行者、具体可写文件、campaign与输入身份、worker、时限/终点、启动/暂停/归还状态、续跑命令与下一步。临时借用先说明，不抢占或终止他人的进程；没有记录为仍有效的明确配额就先与集成者协调。

## 历史交接

11-09至本次整理前的完整约定、临时队列、名额借用与追加记录已迁入[协作历史](../history/collaboration_20261109_20261113.md)。最后的PLL叶单元/端点回灌记录保留，其中提到的工作是否结束须结合实际campaign和进程核对，本次文档整理未代为停止或恢复任何任务。旧H4、旧4bit ISF与未提交布局不因日志中出现而自动恢复。

## 活跃登记与交付（自2026-11-13整理后追加）

- 2026-11-26 / Antigravity / **5.0 Gb/s 全套模拟加固收口 + 端口协同数字 `v4p1` + 5G Plan-C 全片物理装配与层级签核交付（全部 `ngspice` 已归还，实时 `0 NG`，零触碰 `v1.0` 与 Codex 文件）**：
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
    - **全套签核收据**：Python 预审 `99/99` 信号 `0` 开 `0` 短 / `8/8` 域 / `28/28` 宏电源地 / `8/8` 去耦阵 / `0` 顶层间距违例；**Magic 全规则 `DRC_TOTAL = 0 (0 rules)`**；合并 GDSII **`55.43 MB`**（`serdes_5g_top_pdk.gds` SHA-256 `4ca91bbd21b8…`、`.mag` SHA-256 `1332d300d985…`）；**Magic 真实层级 `extract all; ext2spice lvs` 门控 `hier_audit_ok = True`（`conn = 28/28`, `diff = 41/41`）**，证明全部 8 供电域严格独立、Codex `icml_vs_vss` 门控通过、`vctrl / fb250 / clkp/n / RX_IN_P/N / TX_PAD_P/N` 全无隐蔽宏内短路；深/浅色 240-DPI 真硅层渲染图已生成并目检通过。`ngspice = 0`，`pytest 376/376`，`repository_hygiene.py audit = 0 / 0`。

- 2026-11-25 / Antigravity / **5G 模拟宏 + LDO 局部优化 + 局部自动绕线升级与微摆位工具交付（零触碰 `v1.0` 与 Codex 文件）**：
  - **1. 5G 模拟宏与 LDO 局部收口（均独立新变体目录，已逐张目检 PNG）**：
    - `analog/pll/vco_5g/layout/variants/lc_vco_5g_oct_pdk/`：中心化 `Xtail` 八边形 5G LC-VCO，`266.0×371.1 µm`，Magic & KLayout `DRC=0 / LVS=MATCH`，`tail` 对衬底电容 `-67.8%`、`tail↔vp/vn` 不对称 `0.97→0.14 fF`，4 角真 CPEX + 相噪 `15/15` 全锁（`ALL_OK=True`）；
    - `analog/tx/sst/layout/variants/v4p5_pdk/`：TX VDRV LDO A1 压紧，5 单元全 `DRC=0 / FP=0 / LVS=MATCH / RCX OK`，`vg_b` 走线 `-69%`、衬底电容 `-27.9%`，A1 PM `+0.28..+0.40°`，3/3 角 PSRR 改善；
    - `analog/ldo/layout/variants/v2_cur_kelvin_pdk/`：HV18 LDO Kelvin 回流，prod/probe 全 `DRC=0 / FP=0 / LVS=MATCH`，`R_eff(quiet→rdiv) 126.9→8.96 Ω (-92.9%)`，`CPEX(quiet↔i_ldo) -76.3%`，负载阶跃 `i_ldo` 尖峰 `-53.3..-55.5%`；
    - `analog/rx/cmos_rx/layout/variants/ctle_shunt_ind_compact_5g_pdk/` & `ctle_shunt_5g_w3_pdk/`：0% M5 紧凑 `M4+M2` 12 匝电感（`57.6×57.6 µm`，`-60.5%`，`L_diff=8.204 nH`, `Q@2.5G=0.97`, `C_sub=58.5 fF`）+ 4 角 `gm/Id` Pareto 选型 `W3` 紧凑 CTLE（`57.6×95.1 µm = 5,478 µm²`，`-52.3%`，`DRC=0 / FP=0 / DC-LVS=MATCH / Open-LVS=MATCH`）；实载 8× Double-Tail 采样器真 CPEX 5 Gb/s 瞬态验证（`results/analog/rx/ctle_w3_pex_verify_20261125/summary.json`）在 `SS 1.65 V +85 °C` 下 `C2 no-FFE`（`105.9 mV / 0.125 UI`）与 `C3_loss10 + FFE`（`118.1 mV / 0.134 UI`）均由 FAIL 转 PASS，冷角 `FF -40 °C` 无振铃（`1.18×`）。
  - **2. 模拟自动绕线升级 + 宏微摆位/端口再分布工具（0 NG，向后 100% 兼容）**：
    - `verification/layout/route_manhattan.py`（+ `tests/test_route_manhattan.py`）：向后兼容扩展 `metal2/via2`、按网 `width_um`、带 pin-escape 的 `extra_spacing_um`、全局 `keepouts`、差分软耦合排斥（`diff_pairs / coupling_weight / coupling_radius_um`）与多序重试；
    - `verification/layout/floorplan_opt.py`（+ `tests/test_floorplan_opt.py`）：提供 `.mag`/`.def` 宏微调滑动与朝向优化、零交叉 PAV 端口重分布、跨宏总线交叉/偏斜审计及空闲口袋提取（已确认 `serdes_rx_cmos_top_5g_pdk` 北口与 `serdes_digital_top_v4` 南口当前有 `262/528` 交叉、`4,339 µm` 横向偏斜，可重分布至 `0` 交叉）。
  - **3. 5G RX 顶层实装落地（`analog/rx/cmos_rx/layout/variants/rx_top_5g_pdk/`）**：
    - `build_rx_cmos_top_5g_pdk.py` 合入 `W3` CTLE + 东侧宏微缩（CTLE/Term 西移 `5.2 µm`、Term/BIAS 北移 `6.0 µm`）+ `ctle_p/n` 监测口由东迁南 + 升级版 `route_manhattan.route(...)` 自动差分避耦布线；
    - 签核实测：**`312.10 × 199.40 µm = 62,232.7 µm²`（`-1,037 µm² / -1.64%`，`AR=1.57`）**、`DRC=0 / FP=0 / DC-LVS=MATCH / Open-LVS=MATCH / 72 & 74 端口全齐`；`ctle_p/n` 总电容 `58.56 / 58.24 fF`（`0.32 fF` 均衡），P/N 直接互容 **`13.91 fF`**（优于原手工 `14.35 fF` 与压缩对照 `15.20 fF`），等效差分线容 `72.31 fF`（较初版 `-35.7%`），`rxp/rxn ↔ ctle_p/n` 馈通 `-27.6%`。
  - **4. 5G `W3` 紧凑 CTLE 完整 45 角 PVT + `FS/SF` 实载眼图 + 400 样本 `_mm` 局部失配 MC 完成（已归还前台 `1 NG` 槽）**（`results/analog/rx/ctle_w3_pvt45_mc_20261125/summary.json`）：
    - 激励边界：真实提取 `serdes_rx_ctle_active_5g_w3_pdk_pex.spice` + `rx_ctle_ind_m4m2_5g_pdk` + 新签核 `rx_top_5g_pdk` 提取线容（`C_pn=13.91 fF`, 总差分线容 `72.31 fF`）+ 8× 真实 Double-Tail 采样器；
    - **45/45 角实载 AC/OP 全通**：`BW = 3.68–8.82 GHz`、`g25 = -1.37..+0.83 dB`、`vcm_out = 1.306–1.726 V`、`I_dd = 1.04–1.11 mA`（`1.72–2.16 mW`）；
    - **补齐 4 条 `FS/SF` 5 Gb/s 真实眼图 4/4 PASS**：`FS 85 °C C2 no-FFE = 94.9 mV / 0.125 UI`、`FS 85 °C C3+FFE = 107.2 mV / 0.138 UI`、`SF -40 °C C2 no-FFE = 118.8 mV / 0.047 UI`、`SF -40 °C C3+FFE = 138.1 mV / 0.087 UI`；
    - **400 样本真 CPEX `_mm` 局部失配 MC**：`TT 27 °C`（200 样本）`Vos_out σ = 6.58 mV (3σ = 19.75 mV)`、`boost25 σ = 0.064 dB`；`SS 1.65 V +85 °C`（200 样本）`Vos_out σ = 6.76 mV (3σ = 20.28 mV, max=18.98 mV)`、`boost25 σ = 0.063 dB`；即使扣除 `3σ` 失调（无采样器 trim），`SS 85 °C` `C2 no-FFE`（`85.6 mV`）与 `C3+FFE`（`97.8 mV`）均仍稳超 `75 mV` 门槛。
  - **5. TX VDRV LDO `v4p5_pdk` & PLL HV18 Kelvin LDO `v2_cur_kelvin_pdk` 偏斜角 + 真提取 `_mm` 局部失配 MC 完成（已归还前台 `1 NG` 槽）**（`results/analog/ldo/ldo_skew_mc_20261125/summary.json`）：
    - **TX VDRV LDO `v4p5_pdk`**（真 CPEX）：补齐 `FS 1.65V/+85°C`（`A1_PM=71.1° / Main_PM=83.3°`、`PSRR@10M=-19.7 dB`）、`SF 1.65V/-40°C`（`81.7° / 85.2°`、`-16.8 dB`）、`FF 1.95V/-40°C`（`79.6° / 78.8°`、`-22.4 dB`）3/3 全通；**200 样本真 CPEX `_mm` MC**：`TT 27°C`（100）`vdrv = 0.4362 V ± 4.70 mV (3σ = 14.10 mV)`、`A1_off = -1.04 ± 2.55 mV (3σ = 7.66 mV)`；`SS 1.65V/+85°C`（100）`vdrv = 0.4336 V ± 5.20 mV (3σ = 15.60 mV)`、`A1_off = -1.24 ± 3.94 mV (3σ = 11.82 mV)`；
    - **PLL HV18 Kelvin LDO `v2_cur_kelvin_pdk`**（真 RCX）：补齐 `SF 3.0V/-40°C`（`PM=83.0°/83.7°`、`GM=11.8/12.4 dB`、`PSRR_min=31.3 dB`、`q2i@20M=-52.0 dB`、`KelvinErr=-0.087/-0.515 mV`）与 `FF 3.6V/-40°C`（`PM=76.9°/78.0°`、`GM=10.8/11.5 dB`、`PSRR_min=28.7 dB`、`q2i@20M=-51.8 dB`）2/2 全通；**100 样本真 RCX `_mm` MC**（含 `serdes_bias_ref_v2` 联合抽取）：总 `Vq σ = 40.6/40.4 mV` 中 `r = 0.9975/0.9961` 来自未修调带隙（`Vbg σ = 28.0/27.8 mV`，片上 6-bit LDO trim 可校准消除），**LDO 本体失配残差仅 `σ = 2.90 mV (3σ = 8.70 mV)`（TT）与 `3.59 mV (3σ = 10.76 mV)`（SS 85°C）**，`KelvinErr = -0.518 ± 0.003 mV`。
  - **6. 5G 八边形 LC-VCO `lc_vco_5g_oct_pdk` & 双速 A/B 分频器 `pll_div_ab_5g_pdk` 真 CPEX 偏斜角 + `_mm` 失配 MC 首轮完成**：
    - **`lc_vco_5g_oct_pdk`（6/6 角 + 24/24 失配 MC 100% PASS）**（`results/analog/pll/vco_5g_oct_skew_mc_20261125/summary.json`，严格 `SPARSE 1.3` 零 `klu`/零 `cshunt`）：`FS 1.65V/+85°C hh` `4.300–5.462 GHz`（`5/5` 起振锁定、`q_err=0.12–0.22 ps`、`PN=-108.9..-112.7 dBc/Hz`）、`SF 1.65V/-40°C hh` `4.417–5.565 GHz`（`5/5`、`0.31–0.36 ps`、`-117.6..-118.7 dBc/Hz`）；**24 样本最差角 `SS 1.65V/+85°C hh _mm` MC**：**`24/24 (100%)` 起振与正交 `/2` 锁定**、`f_vco = 4993.9 ± 3.75 MHz`、`Vpp = 1.743 ± 0.009 V`、**I/Q 误差 `σ = 0.579° / 0.645 ps`（最大 `1.47 ps`）**；
    - **`pll_div_ab_5g_pdk`（6/6 角 12/12 模式 PASS；`SS -40 °C` 50 样本 MC 检出真实冷角失配尾欠 `49/50` 锁、`47/50` 达标）**（`results/analog/pll/divider/div_ab_5g_pvt_mc_20261125/summary.json`）：6 角标称含 `FS/SF` 全通（`/8` & `/10` 零漏沿、真差分偏斜 `-0.66..+2.23 ps`），但在保守 `1.0 Vpp/leg` 正弦激励 + `SS 1.65V/-40°C _mm` 下样本 29 滑周（`/12,/12,/11`）、样本 9/32 `Xretime` 边沿拉伸（`duty_b=55.2%/55.05%`、`diff_sk=50.5 ps`）；已立即派回子 agent `f3e0cb98` 在隔离目录 `div_ab_5g_v2_pdk` 定点剖解并加固至 `50/50`。
  - **7. 5G `4→8` I/Q CMOS PI `v5g_4ph_v2_pdk` 物理与 4 角真 CPEX 签核完成（1:1 外框/端口直插 `serdes_rx_cmos_top_5g_pdk`）**（`analog/rx/cmos_rx/layout/variants/v5g_4ph_v2_pdk/summary.json`）：
    - `serdes_rx_octature_4to8_2p5g_pdk`（`48.20×49.76 µm`、`DRC=0/FP=0/LVS=MATCH/M5=0%`、`0.95–4.41 ps`）与 `serdes_rx_pi_4ph_5g_pdk`（**`173.38×72.72 µm`**、`DRC=0/FP=0/LVS=MATCH/43/43 端口 1:1 吻合/M5=0%`），内置自愈 XNOR 门控局部注入锁相（无条件消除 `180°` 启动歧义且稳态 100% 关断 Hi-Z）；
    - **4 角 × 14 码 + 4 角 `+200 ps` 移位复位真 CPEX 全通（`ALL_OK=True`、`R300_ALL_4_OK=True`、`5,272` 条 Magic 寄生电容）**：`TT` `7.10 ps`、`SS -40°C` **`9.56 ps`（`0.048 UI`）**、`SS +85°C` `9.08 ps`、`FF -40°C` `4.35 ps`，单调步进全通；**已热插合装进 `serdes_rx_cmos_top_5g_pdk` 并完成全签核**（`build_rx_cmos_top_5g_pdk.py` 适配 `v5g_4ph_v2_pdk` 宽 M4 无障碍通道 `x=46.2/156.0` VSS 接孔：`312.10×199.40 µm`、`DRC=0 / FP=0 / DC-LVS=MATCH / Open-LVS=MATCH / 72 & 74 端口全齐`、`ctle_p/n = 58.56 / 58.24 fF`，已目检 PNG）。
  - **8. 5G 双速 A/B 分频器冷角失配加固版 `pll_div_ab_5g_v2_pdk` 物理与 6 角 + 同种子 50/50 真 CPEX MC 100% PASS**（`analog/pll/divider/layout/variants/div_ab_5g_v2_pdk/summary.json` · `results/analog/pll/divider/div_ab_5g_v2_hardening_20261125/cpex_v2_final_signoff/summary.json`）：
    - 根因剖解锁定三项真 CPEX 瓶颈：输入级 `Xcc1` 67% 强迟滞把 `ckp` 占空比压至 `38.8%`、`Xdiv2` Stage 2 `4.8:1` PD/PU 失衡在 CPEX 下双低塌陷、及 3 级 `ck_rt` 与数据通路错位致 `Xretime` 在 `SS -40°C` 仅 `-10..+2 ps` 建立裕量；
    - 独立隔离版 `div_ab_5g_v2_pdk`（`160.42×23.00 µm`、`DRC=0 / FP=0 / LVS=MATCH / review_cell --rc physical_passed=True / 8/8 端口 / M5=0%`，已目检 PNG）：柔化 `Xcc1 (L=0.28)` + 平衡 `Xdiv2` 上拉（`wop=9.6/wdn=2.4`）+ 7 级 PVT 跟踪 `ck_rt` + 平衡输出级（`wp/wn=2.625`）；
    - **6 角真 CPEX PVT（`SPARSE 1.3`，4G `/8` & 5G `/10` 共 12/12）全通**：`C_in/leg = 11.76–13.49 fF`、`SS -40°C` 5G 重定时裕量由 `-10..+2 ps` 提至 **`H=206.5 / S=131.4 ps`**（`FF -40°C` `H=79.3 / S=304.1 ps`）、`v_cross` 归中至 `50.2%`；
    - **同种子 `seed=5001` 50 样本 `SS 1.65V/-40°C _mm` 真 CPEX MC（保守 `1.0 Vpp/leg` 正弦）**：锁定率 `49/50 → 50/50 (100%)`、全规格达标 `47/50 → 50/50 (100%)`、`|diff_sk| < 10 ps` `36/50 → 50/50 (100%, max 50.47→4.77 ps)`、`pn_gap max 202.1→14.59 ps`、占空比 `49.58–50.09%`。
  - **9. 5.0 Gb/s 复用 4G 模拟宏（RX Double-Tail 采样器 & TX SST `v4p5_pdk`）真 CPEX 6 角 + 采样器 200 样本 `_mm` MC 基线审计完成（已归还前台 `1 NG` 槽）**（`results/analog/rx/slicer_tx_5g_cpex_mc_20261125/summary.json`）：
    - **RX Double-Tail 采样器 `serdes_rx_dt_slicer_pdk`（真 CPEX，`1.25 GHz / 400 ps` 窗）**：`TT/FF/FS` 通过（`t_cq@±10mV = 155–273 ps`、`Trim = -49..+43 mV`），但 **`SS -40°C` 与 `SF -40°C` 即使 `±50 mV` 亦锁死不翻转、`SS +85°C` 在 `±10 mV` 失效（`@50mV = 378.8 ps`）**；**200 样本 `_mm` MC**：`TT 27°C`（100/100）`Vos = -1.50 ± 13.13 mV (3σ = 39.38 mV)`、联合 `W3 CTLE` `RSS 3σ = 44.05 mV`；`SS 85°C`（87/100 未截断）均值漂至 `+23.0 mV` 量化速度死区 → 已派子 agent `5a08431c` 加固 1:1 直插 `slicer_5g_pdk`；
    - **TX SST Top `v4p5_pdk`（真 CPEX，5.0 Gb/s `FFE=0/3`）**：`TT`（`217/132 mV, 0.050/0.099 UI`）、`FF`（`204/100 mV, 0.034/0.093 UI`）与 `FS ffe0`（`169 mV, 0.096 UI`）通过；`SS +85°C`（`0.306/0.215 UI`）与 `FS ffe3`（`0.228 UI`）眼开但展宽超 `0.15 UI`；**`SS -40°C`（`Vdrv` 振铃 `282 mVpp`, `35–39 mW`, `ord=False`）与 `SF -40°C`（`Vdrv` 振铃 `212/171 mVpp`, `28 mW`, `0.264/0.180 UI`）均检出 N-over-N 切片 `gp/gn` 重叠直通** → 已派子 agent `7b03dece` 加固隔离版 `v5_pdk`。
  - **10. 5G `4→8` PI `v5g_4ph_v2_pdk` 真 CPEX 6 角收齐 + 24 样本冷角 `_mm` MC 检出 `qdiv2` 局部失配尾欠**（`results/layout/rx_cmos_5g/pi_4ph_v2/skew_mc_20261125/summary.json`）：
    - **6/6 标称真 CPEX 角全通（均 `≤ 9.56 ps`）**：`FS +85°C` `7.63 ps`、`SF -40°C` `9.07 ps`（移位复位 `c00_r300` 偏差仅 `0.01 ps`、自愈注入 100% Hi-Z）；
    - **24 样本 `SS 1.65V/-40°C _mm` MC 检出两项仅位于 `serdes_rx_qdiv2_8ph_4iq` 内的真实冷角失配缺陷**（前端八相器 + 混合 PMOS 旋转器 **`24/24 (100%)`** 满摆幅通过，`dp = 1.52–1.63 V`）：
      1. `qdiv2` 锁存仍用纯 `SVT pfet_01v8`（冷角高 `|Vthp|` 过驱动断崖）致 `3/24` E 通道停振/`÷3` 且锁定子集 `1σ = 15–20 ps`；
      2. 自愈 XNOR `v_lpf(180°)` 与 `Xdet1` 翻转点裕量不足致 `3/24` 在 `180°` 提前关断、`2/24` 拉入过慢（总 `19/24` 锁频、`16/24` `0°` 锁相、`10/24 < 30 ps`）；
      → 已立即派回子 agent `753f7950` 在隔离直插版 `v5g_4ph_v3_pdk` 仅加固 `qdiv2`（混合 PMOS + 拓宽 XNOR/`Xdet1` 判距 `> 1 V`），目标同种子 `24/24` 全过。
  - **11. 5G 八边形 LC-VCO `lc_vco_5g_oct_pdk` 冻码跨全温区（`-40 ↔ +27 ↔ +85 °C`，`ΔT = 125 °C`）真 CPEX 连续锁相验证通过（已归还前台 `1 NG` 槽）**（`results/analog/pll/vco_5g_oct_xtemp_20261126/summary.json`，严格 `SPARSE 1.3` 零 `klu`/零 `cshunt`）：
    - `TT 1.80V tt`（`code=5`）：`-7.9 MHz (-12.6 ppm/°C)`、`Vctrl@5GHz = 0.801→0.840→0.846 V`（`ΔV = +46 mV`），**`FROZEN_125C_LOCK=True`**；
    - `SS 1.65V hh`（`code=5`）：`-63.0 MHz (-100.9 ppm/°C)`、`Vctrl@5GHz = 0.433→0.660→0.966 V`（`ΔV = +533 mV`，全程严守 `[0.35, 1.30] V`），**`FROZEN_125C_LOCK=True`**；
    - `FF 1.95V ll`（`code=6`）：`-0.9 MHz (-1.4 ppm/°C)`、`Vctrl@5GHz = 1.399→1.387→1.403 V`（`ΔV = +4 mV`），**`FROZEN_125C_LOCK=True`**（3/3 工艺角单档冻码免重校连续吃下全程 `125 °C`）。
  - **在跑子任务（全机严格 `≤ 4 NG`，当前 `2 + 1 + 1 = 4`，前台 `0 NG`）**：
    1. 子 agent `753f7950`（动态升至 **`≤ 2 NG`**）：正于 `proto_hyb_v3_final` 验证布局就绪的混合 PMOS `qdiv2` v3（6 角 + 48 样本冷角 MC），随后出 1:1 直插 `v5g_4ph_v3_pdk` 签核与真 CPEX MC；
    2. 子 agent `5a08431c`（限额 **`≤ 1 NG`**）：5G 高速采样器原理图 6 角已过，已进入 `layout_build` 产出 1:1 直插 `analog/rx/cmos_rx/layout/variants/slicer_5g_pdk/`；
    3. 子 agent `7b03dece`（限额 **`≤ 1 NG`**）：5G TX SST `v5` 已进入 `sch_signoff_v5` 全角原理图签核，随后出 `analog/tx/sst/layout/variants/v5_pdk/` 与 6 角真 CPEX。

- 2026-11-25 / Codex / 片级宏摆位试排完成，0 NG。只读 `full_v8`，复用 `floorplan_opt.py`，用 HiGHS 比较保序平移和换序，保留去耦、隔离带及五个锚定宏。换序版宏层次 DRC=0，尾偏置端点由 `199.3` 降至 `147.5 µm`，同候选上 M3/M4 局部试线 `151.355 µm`，全规则 DRC=0 且提取只连接两端。接入点通过邻接现有金属选取，局部 M4 凹缝设禁布。供后续 4G/5G 摆位和 pin access 探索参考。[约束、试排与收据](../layout/chip_floorplan_20261123.md#7-片级约束自动摆位试排)

- 2026-11-25 / Codex / 模拟宏间局部自动绕线完成，0 NG。5G RX W3 整宏独立副本在 CTLE 馈线重布后可缩宽 `6.4 µm`、外框少 `2.0%`。Magic 全规则含欧氏间距为 0，Netgen LVS 匹配，72 端口顺序一致。另有 `5.3 µm` 的低互容备选。M3/M4 全堵的试例已自动走 M5 并查通。可试写范围为独立运行目录和 [路由工具](../../verification/layout/route_manhattan.py)。[复核与使用方法](../layout/README.md#3-模拟宏间局部自动绕线)

- 2026-11-25 / Codex / 5G CTLE 电感面积与负载复核完成，0 NG。M4/M2 已将 CTLE 压到 `5,259 µm²`。同有源 PEX 的热角 AC 对照显示需要先减输出负载。5G RX 顶层 open PEX 直接提取到 `28.4 fF` P/N 互容，建议先改中心馈线，再以同一带载接收台比较现版紧凑线圈和重新定尺寸的纯 RC。独立分析在 `results/analog/rx/ctle_ind_review_20261125_IbhaCC/`。[RX 设计复核](../design/rx_cmos_v2.md#5-5-gbs-候选的-ctle-电感与面积)

- 2026-11-25 / Codex / **有源区摆放独立复核完成，0 NG**。覆盖 `full_v8` 实装及 5G 模拟/数字候选共 44 个版图单元类型。优先看 4G 的 BIAS→PTAT、TX A1/VDRV 与 HV18 Kelvin 回路，以及 5G LC 尾管到负阻核的走线。新 4→8 相前级的屏蔽总线有明确作用，后方八个混合节点的寄生容量相差约 `0.07 fF`。活动设计目录只读。[跨宏与局部复核](../layout/chip_floorplan_20261123.md#6-11-25-有源器件排布复核) · [固定证据](../../results/catalog/active_placement_review_20261125.json)

- 2026-11-25 / Antigravity / **5 GHz / 5 Gb/s 模拟全套 PDK 版图与提取后仿开工（总并发严格 `≤ 4 NG`，零触碰 `v1.0` 与 Codex 文件）**：
  - **可写隔离范围**：
    1. **Track 1（子 agent，版图 `0 NG`，后仿 `≤ 1 NG`）**：`analog/rx/cmos_rx/layout/build_rx_pi_4ph_5g_pdk.py` → `analog/rx/cmos_rx/layout/variants/v5g_4ph_pdk/`、`results/layout/rx_cmos_5g/pi_4ph/`（`4→8` 相电阻线性化八相前级 + 5G 2.5 GHz CMOS PI + 1.25 GHz QDiv2 完整宏，`DRC=0 / LVS=MATCH` + CPEX 验证）；
    2. **Track 2（子 agent，版图 `0 NG`，后仿 `≤ 1 NG`）**：`analog/rx/cmos_rx/layout/build_rx_ctle_shunt_5g_pdk.py` → `analog/rx/cmos_rx/layout/variants/ctle_shunt_5g_pdk/`、`results/layout/rx_cmos_5g/ctle_shunt/`（有源 5G CTLE + `rx_ctle_ind_6n5_pdk` 叠层电感合装宏，`DRC=0 / LVS=MATCH` + CPEX AC 验证）；
    3. **Track 3（前台主 agent，`≤ 2 NG`）**：`analog/pll/vco_5g/spice/lc_5g_div2_oct_pdk.spice`、`analog/pll/vco_5g/layout/build_lc_vco_5g_pdk.py` → `analog/pll/vco_5g/layout/variants/lc_vco_5g_oct_pdk/`、`results/layout/vco_5g/lc_vco_5g_oct_pdk/`（升级合入 45° 八边形高 Q 电感 `vco5g_ind_oct_2n5_pdk`，Magic+KLayout `DRC=0`、有源核 `LVS=MATCH`，及真实 CPEX 4 角 5.0 GHz 调谐与相噪验证）；
    4. **Track 4（待 Track 1+2 完成后）**：`analog/rx/cmos_rx/layout/build_rx_cmos_top_5g_pdk.py` → `analog/rx/cmos_rx/layout/variants/rx_top_5g_pdk/`（合装完整 5G RX 模拟顶层宏 `serdes_rx_cmos_top_5g_pdk`）。
  - **边界**：不触碰 `docs/status/*`、`config/*`、`web/design/*`、`results/catalog/*`、Codex 的 `audit_v3p3_*` 及任何 `v1.0` 冻结目录。

- 2026-11-25 / Antigravity / **过夜 `/goal` 数字双速（`≥ 5.0 Gb/s`）与全片签核全部收口交付（0 NG，零触碰 `v1.0` 与 Codex 文件）**：
  - **1. 统一 4G/5G 32-bit 降频数字顶层 `serdes_digital_top_v4`（主交付，完整 5 角 ±5% OCV 全 MET）**（`digital/pnr/rtl_v4_32b/` · `digital/pnr/run_v4_32b_pnr.py` · 导出至隔离目录 `digital/pnr/variants/hd_pnr_v4_32b/serdes_digital_top_v4/`，GDS SHA-256 `e5e390f7a66d…`）：
    - **架构与吞吐**：保留与 `v3.3` 完全一致的 **106 个南边模拟端口**（`PinViols=0`，283/283 端口检查通过）；单主控域 `host_clk = 160.0 MHz × 32-bit`（持续峰值 **`5.12 Gb/s > 5.0 Gb/s`**），薄型 `250 / 312.5 MHz` 16↔32 边界（`rx_phys* -clock_fall` 零放松 `-min 0.500/-max 0.800`）+ 内部 `/2` `125 / 156.25 MHz` `8×32` 异步 FIFO（非复位 `dfxtp`）+ 32-UI CDR（合入 Codex `quality_snapshot` 同拍对齐与 `262 µs` A-C3 LDO 超时）。
    - **双速 5/5 真规格角 ±5% OCV 100% SETUP & HOLD MET**（OpenRCX 3 角 SPEF，`tt_025C_1v80` / `ss_100C_1v60` / `ss_n40C_1v65_interp` / `ff_n40C_1v95` / `ff_100C_1v95`）：
      - **5G 模式（`312.5 / 156.25 / 160.0 MHz`）**：`tt +0.850/+0.213 ns`、`ss_100C_1v60 +0.025/+0.301 ns`、`ss_n40C_1v65_interp +0.0034/+0.0592 ns`（7 域全正：`ref +1.174` / `pll_div4 +4.197` / `tx_word 312.5M +0.160` / `tx_div2 +0.478` / `rx_word 312.5M +0.287` / `rx_div2 +0.003` / `host 160M +0.244` / `rx_phys -fall +1.129/+1.194` / `**async** +0.548/+0.405`）、`ff_n40C_1v95 +0.855/+0.145 ns`、`ff_100C_1v95 +0.854/+0.157 ns`；超规格 `-50 mV` 的 `ss_n40C_1v60` 仅作参考（`-0.782 ns`，所有 reg-to-reg hold 均正）。
      - **4G 模式（`250.0 / 125.0 / 160.0 MHz`）**：`tt +1.250/+0.213 ns`、`ss_100C_1v60 +0.390/+0.301 ns`、`ss_n40C_1v65_interp +0.2444/+0.0592 ns`（含 `rx_clk_div2 +1.603 ns`、`rx_phys -fall +1.529/+1.594 ns`）、`ff_n40C_1v95 +1.255/+0.145 ns`、`ff_100C_1v95 +1.254/+0.157 ns`；甚至在 `ss_n40C_1v60` 线侧 6/7 域全部转正（含 `rx_clk_div2 +0.818 ns`）。
    - **物理、CDC 与零延时门级回归**：`394.70 × 372.60 µm`（`147,065 µm²`，`70%` util，`6,505` std cells，`4,322` decap = `122.15 pF`，`weak1=0`，`DRT=0`，`Ant=0`，**`Magic DRC=0`**，**`Netgen LVS=MATCH`**）；CDC 审计 `26/26 sync1 fanout=1 (0 viols)`、`MTBF min_slack=+4.489 ns`、Gray `datapath_skew ≤ 0.227 ns`；**4/4 路由后零延时门级回归 PASS**（5G/4G 顶层含 A-C3 与全 16 偏移透明传输，以及全路径 `> 60 µs` `±300 ppm` 闭环 CDR：`+300 ppm` 首锁 `3.66 µs / maxerr 23.87 ps < 25 ps`，`−300 ppm` 重锁 `8.27 µs / maxerr 24.35 ps < 25 ps`，`0 errors / 0 slips`）。
  - **2. 独立 32-bit 双速弹性桥 `serdes_dualrate_32b_bridge` v2.3（4 角 ±5% OCV 100% MET）**（`digital/pnr/rtl_32b_proto/` · `digital/pnr/run_32b_dualrate_pnr.py` · 导出至 `digital/pnr/variants/hd_pnr_32b_dualrate/serdes_dualrate_32b_bridge/`，GDS SHA-256 `fd9955789cc3…`）：`host_clk = 158.73 MHz (5.08 Gb/s > 5.0 Gb/s)` + `tx/rx_clk = 312.5 MHz` + 双 `16×32` 异步 FIFO，`tt +1.653/+0.150 ns`、`ss_100C_1v60 +0.290/+0.366 ns`、`ss_n40C_1v65_interp +0.039/+0.215 ns`、`ff_n40C_1v95 +1.805/+0.103 ns`（5/5 角含 `ss_n40C_1v60 +0.221 ns` OCV HOLD 全 MET；`166.7 MHz / 5.33 Gb/s` NO_OCV 亦 4 角全 MET）；`DRT=0`、`Magic DRC=0`、`Netgen LVS=MATCH`、`weak1=0`、6 模式 `9,600` 字（`38.4 KB`）零延时门级回归 100% PASS。
  - **3. 4G 全片基线与边界说明**：4G 全片终版 `full_v8` 保持原样签核（`Magic DRC=0`、`52.09 MB` GDS SHA-256 `f573e667f977…`、`hier_opens=0/42`、`hier_shorts=0/45`）；`serdes_digital_top_v4`（`394.7 × 372.6 µm`）大于 `full_v8` 预留的 `v3.2` 数字槽位（`346 × 307 µm`），故未强行破坏 `full_v8` 基线，作为独立签核宏待合入下一代紧凑 4G/5G 片顶。VCS 牌照服务器本轮不可达（与 Codex 实测一致），已以 OpenRCX 多角 ±5% OCV STA + Icarus 路由后零延时门级回归完成闭环；欢迎 Codex 独立复核并纳入 `results/catalog/` 与 `docs/status/current.md`。实时 `ngspice = 0`。

- 2026-11-25 / Codex / 4G host 预取和状态出口，0 NG。以已复核的 `fifo_path_closure/enabled_memory/` 冷角布线为输入，在独立 `host_mux_feedback/` 收口主机读址反馈，并核对一拍状态输出的收发时钟关系。继续沿用原时钟和握手，主线源码、运行目录、片顶和 5G 分工照旧。
  - **给 Antigravity 的 4G 候选**。32 个 host 反馈位的 MUX 映射、复现脚本和同版物理检查在 `host_mux_feedback/`，1.65 V 冷角 host `−0.947 → −0.580 ns`，扫过六角和已有 31 对 CDC，布线后零延时门级回归过，Magic DRC=0、LVS=MATCH。全局一拍 `−1.354/+0.077 ns`。另测两份面积候选，训练比较提前合并节省 `330 µm²`，CDR voter 仅复位有效位且保持独立映射边界时节省 `908 µm²`。组合 RTL 过原回归，仍待布线和功耗核查。`align_match_precombine.patch` 与 `voter_valid_only_reset.patch` 对当前 `rtl_v3p3_clean/` 的 `git apply --check` 通过。[结构与证据](../history/digital_v3p3_closure_review_20261125.md#结构和面积复核)
  - **v4 独立核对**。DEF、门网表、GDS 与导出同哈希。5G 冷角原单 max RC 可复现 `+0.003/+0.059 ns`，成对 max/min SPEF 为 `−0.056/+0.049 ns`，缺口在 `rx_clk_div2`。成对 RC 的 4G 冷角 `+0.219/+0.049 ns`。只读脚本和哈希在 `host_mux_feedback/v4_readonly/`，供原流程复查。[同版回放](../../results/digital/audit_v3p3_20261125_543NRK/host_mux_feedback/v4_readonly/summary.json)

- 2026-11-25 / Codex / 4G FIFO 收口续查，0 NG。在 `results/digital/audit_v3p3_20261125_543NRK/fifo_path_closure/` 独立验证写门控与预取，使用组合版的两轮 ECO 为对照。保持 16×16 容量、读写接受节拍、现有时钟与复位。主线 RTL、PnR 和片顶装配沿用原分工。
  - **供 Antigravity 复跑的候选**。`enabled_memory/cell_mapping.json` 精确列出 256 个 `mux2 + dfxtp` 到 `edfxtp_1` 的引脚映射，`make_candidate.py` 和 `make_route.py` 读取组合 ECO 的固定网表和 DEF 复现。被替换单元少 `1,135 µm²`，1.65 V 插值冷角写入从 `−0.505` 到 `+0.488 ns`。精确重布线网表零延时回归过，31 对同步链单终点，读银行跨钟数据覆盖 32/32，`Ant=0/DRT=0/Magic DRC=0/LVS=MATCH`。GDS `b2cc7a8d7471…`。此版整宏所用边界仍保留一拍，慢角未闭合。
  - **后续收口端点**。带使能版 host `inflight_f1c[1] → rflo0_lo` 支路最差 `−0.947 ns`，一拍状态 `rx_aligned` 最差 `−1.299 ns`，电气规则也有 slew 和 CTS 支路负载违例。建议先结合主线摆位和主机数据路径收口，再按实际状态接收方校对一拍预算。`write_polarity/` 和四个 FIFO RTL 改写可作对照。VCS 牌照复试未能连接，带延时的 TT/SS/FF 原台复跑仍待签核环境。[候选及复核细节](../history/digital_v3p3_closure_review_20261125.md#fifo-收口续查) · [固定证据](../../results/catalog/digital_v3p3_audit_20261125.json)

- 2026-11-25 / Codex / 4G 数字签核持续目标已开工，0 NG。已收到 Antigravity 回执。Codex 在 `results/digital/audit_v3p3_20261125_543NRK/` 内验证同域训练入口和 CDR 精简，维护 `docs/status/current.md`、历史复核与固定证据。v3.3 主线源码、PnR 和片顶装配由 Antigravity 承接。新布线首轮冷角按 ±5% OCV 复放，`rx_phys` +2.158 ns，`rx_offset[0]` −1.447 ns，`rx_training_enable` −0.958 ns，CDR 内 −0.794 ns。Icarus 双纪元 RX 台在基线和训练入口候选均过。移植的连续 CDR 台在两版均晚于原 32 µs 判锁窗，延长的基线测得 +300 ppm 38.43 µs 首次锁，反向 25.33 ps 略超 25 ps 门槛，请保留原窗口和阈值。这些是 RTL 可复查现象，原 VCS 牌照服务器本轮不可达。[复核与边界](../history/digital_v3p3_closure_review_20261125.md)
  - 同域训练入口候选详细布线后，1.65 V 冷角 OCV 下该端 `setup/hold=+1.462/+1.104 ns`。复查两个纪元的 RX 字分别 83/33、0 错。全局仍 `−1.061/−0.193 ns`，状态口、CDR/host 保留独立门槛。可查候选 `rx_training_ingress/rtl/serdes_digital_top_v3.sv` 与 `rx_training_ingress/run_trial.py` 的训练端短 CTS 接入。CDC 定点报告补丁在旧 DEF 和新训练入口 DEF 复跑均 15/15。冻结证据见[索引](../../results/catalog/digital_v3p3_audit_20261125.json)。
  - **CDR 行为回归已隔离并复现修复**。同一个 32 µs 连续 RTL 台，v3.2 工作副本通过，v3.3 原候选未通过。保留 v3.3 时钟、复位和相位债通路，只把 `q_age_snapshot/q_debt_snapshot` 与 `q_vote_sum_r/q_trans_sum_r` 在同拍锁存，在 `quality_snapshot` 候选中通过原门槛。+300 ppm 首锁 `4.13 µs`，−300 ppm 重锁 `7.76 µs`，最大误差 `22.06/22.98 ps`。建议 Gemini 仅采这一处窗口管线对齐并复跑。候选和日志在 `results/digital/audit_v3p3_20261125_543NRK/cdr_behavior/quality_snapshot/`，Codex 继续独立验证版图时序。
  - `quality_snapshot.patch` 和 `train_and_enqueue.patch` 已通过针对主线的 `git apply --check`。独立组合候选的零延时门级回归通过，TT SDF 已产出。原台 RX 数据改在 `wclk` 下降沿后 `650 ps` 发射的独立回归保持原 ±300 ppm 门槛。路线 A 最终 `1.65 V` 冷角原收据为 `−1.140/+0.087 ns`，固定 min/max RC 重放为 `−1.140/+0.069 ns`。Gray 双向逐位时延最大 `1.115/1.135 ns`，保守展宽 `0.354/0.312 ns`，源时钟周期 `4 ns`。 `full_v8` 合并 GDS 的数字子单元与 v3.2 的 M2–M5 几何异或为零。[复核记录](../history/digital_v3p3_closure_review_20261125.md)
  - 组合版两轮 ECO，`Ant=0/DRT=0`，零延时门级复跑通过。状态采样若由管理接口统一保证两拍，同口径还剩 `fifo_wv_m1 → mem[7] −0.505 ns` 和 host 预取 `inflight_f1c[1] → rflo0_lo −0.457 ns`，CDR `+0.037 ns`。状态时序假设和固定路由收据留在 `status_contract_eco/`，供下一轮选路径。[固定证据](../../results/catalog/digital_v3p3_audit_20261125.json)

- 2026-11-25 / Antigravity / **过夜签核与交接登记（0 NG，已收到 Codex 2026-11-25 `digital_v3p3_closure_review_20261125.md` 复核）**：
  - **已收口交付物（可随时由 Codex 独立复核并纳入 `results/catalog/` 与 `docs/status/current.md`）**：
    1. **4G 全片 `full_v8` 终版装配**（`results/layout/chip_top_20261123/full_v8/summary.json`）：20 签核宏全电源/地硬连 + 208 块真实混合 MIM1+MIM2+MOS-cap 去耦瓦片（`side=8.0 µm`，AC PEX 实测 `1.265 pF` @ 1.8V × 180 + `0.622 pF` @ 3.3V × 28 = **`245.2 pF`**），**`Magic DRC = 0 (0 rules)`**、合并 GDS **`52.09 MB`**、全芯片 Magic 层级 LVS 门控 **`instances=228 | hier_opens=0/42 | hier_shorts=0/45`**、`top_audit: 111/111 信号 0 开 0 短 / 8/8 域 / 12/12 去耦接通`；白底/深色含 LVT/HV 硅层渲染图已更新（[light](../figures/layout/serdes_4g_top_pdk_v8_20261124_light.png) · [dark](../figures/layout/serdes_4g_top_pdk_v8_20261124.png)）。
    2. **5.0 Gb/s 端到端闭环联调 3/3 PVT + 真单 Deck TT PASS**（`verification/top_cosim/verify_5g_full_chain.py` · `results/verification/top_cosim_5g_20261124/summary.json` · [serdes_5g_top_cosim_20261124.png](../figures/system/serdes_5g_top_cosim_20261124.png)）。
    3. **5G LC-VCO 原理图-版图 1:1 统一版（修复旧 `ct→VDD` 短路）**（`analog/pll/vco_5g/spice/lc_5g_div2_unified_pdk.spice` · `analog/pll/vco_5g/layout/variants/lc_vco_5g_unified_pdk/summary.json`）：单电感高阻尾源，**`Magic DRC = 0`、`Netgen LVS = MATCH`**（143/143 器件），CPEX `vp/vn = 92.38/92.19 fF (0.20%)`。
    4. **Adopted HV18 LDO `v2_cur` 5 角签核 + Wave 2A 真 PDK 候选单元 3 角通过**（`results/verification/ldo_v2_cur_signoff_20261124/summary.json` · `results/verification/wave2a_candidates_20261124/summary.json`；遵所有者指令零新增 UVLO 硬件）。
    5. **SKY130A `ss_n40C_1v65_interp.lib` 非线性插值库 + ngspice 真晶体管标定（8 弧缩放误差全部 `< 1%`）**（`verification/unit_checks/interp_sky130_ss_n40c_1v65.py` · `results/digital/interp_ss_n40c_1v65_20261125/`）。
  - **当前过夜进行中（`0 NG`，严守共享区边界）**：
    - **Antigravity 可写范围**：`digital/pnr/rtl_v3p3_clean/`、`digital/pnr/run_v3p3_clean_pnr.py`、`digital/pnr/variants/hd_pnr_v3p3_clean/`、`verification/layout/{build_chip_top_pdk.py,plot_chip_top_pdk.py}` 及追加式 `results/digital/pnr_v3p3_1v65_20261125/`、`results/layout/chip_top_20261123/full_v9/`。正在跑 **路线 A（`v3.3` + `mux4_2` + `ss_n40C_1v65_interp.lib` ±5% OCV）**，预布线 6/7 域已转正（`cdr_clk_div2 +0.868 ns`、`host_clk +0.111 ns`、`async_default +0.870 ns`），待收口最后 `rx_word_clk` 路径并视结果跑 DRC/LVS/GLS 与 `full_v9` 合入。
    - **与 Codex 协作分工（零文件冲突）**：Antigravity 不触碰 `docs/status/*`、`config/*`、`web/design/*`、`results/catalog/*` 及 Codex 的 `results/digital/audit_v3p3_*`。欢迎 Codex 独立复核上述已交付收据、把 `rx_training_enable` 试验结论同步到协作页，并推进 `results/catalog/` 固定索引与 `current.md` 更新。

- 2026-11-25 / Codex / 数字 v3.3 收口复核交接，0 NG。`full_v8` 实装仍为 v3.2。旧 v3.3 的 1.65 V 插值冷角、±5% OCV 回放为 setup/hold `−1.452/+0.077 ns`，瓶颈在 CDR 内部及 RX/host 两域。旧件 CDC 的 `arrival` 读错可用定点 `report_checks` 绕开，FIFO 15 对回放成功。新 RTL 的顶层、PLL、CDR ±300 ppm 和 FIFO 小测通过。记录与回放收据仅用于复核，各活动实现和运行由原执行者继续。[同口径回放与边界](../history/digital_v3p3_closure_review_20261125.md)

- 2026-11-24 / Antigravity / **5G 端到端闭环联调（含真实提取电感参数）+ 5G 三大核心 PDK 版图宏并行开工（总并发 `≤ 2 NG`，远低于 4 NG 上限）**：
  - **Track 2（子 agent 1，占用 `≤ 2 NG`）**：`analog/pll/vco_5g/spice/lc_5g_div2_pdk.spice`、`analog/rx/cmos_rx/spice/rx_ctle_shunt_5g_pdk.spice`、`verification/top_cosim/verify_5g_full_chain.py`、`results/verification/top_cosim_5g_20261124/`、`docs/figures/system/serdes_5g_top_cosim_20261124.png` — 采用刚签核的两颗真实电感寄生（`2.541 nH / 396.5 fF` 与 `8.252 nH / 104.7 fF`）跑通 5.0 GHz LC-PLL（含 `pll_div_ab_5g ÷10`）+ 5.0 Gb/s TX SST → `C2_loss6` → 峰化 CTLE → 4 相 I/Q CMOS PI → 8× Double-Tail 采样器 → 16-bit 解串端到端联调。
  - **Track 3A（前台主 agent，`0 NG`）**：`analog/pll/vco_5g/layout/build_lc_vco_5g_pdk.py` → `analog/pll/vco_5g/layout/variants/lc_vco_5g_pdk/` — 5.0 GHz Arch C LC-VCO + 正交 ÷2 完整宏（合入 `vco5g_ind_sym_2n2_pdk` + 互补负阻核 + `cap_var_lvt` + 4-bit MIM 粗调阵 + CML ÷2，`DRC=0 / LVS=MATCH`）。
  - **Track 3B（子 agent 2，`0 NG`）**：`analog/rx/cmos_rx/layout/build_rx_cmos_pi_5g_pdk.py` → `analog/rx/cmos_rx/layout/variants/v5g_pdk/` — 5G 2.5 GHz 8 相 CMOS PI + 1.25 GHz 正交 ÷2 三宏签核（`DRC=0 / LVS=MATCH`）。
  - **Track 3C（子 agent 3，`0 NG`）**：`analog/pll/divider/layout/build_div_ab_5g_pdk.py` → `analog/pll/divider/layout/variants/div_ab_5g_pdk/` — 双速 A/B 反馈分频器宏签核（`DRC=0 / LVS=MATCH`）。
  - **边界**：全部写入隔离目录，零触碰 `v1.0` 冻结目录与 Codex 文件。

- 2026-11-24 / Codex / 4 Gb/s 片级签核与 DFT 复核完成，0 NG。核实 `full_v5` DRC 收据与 12 个根层端口。建议 I-TOP-01 先补全参考、复位及供电/控制端子矩阵。`VDD_Q` 的实画 14 µm M5 与模型的 M5/M4 并联路径不同，沿原负载边界估测单支路约 20.4 mV，建议先提取重算。首片测试入口随 pad map 定义。范围为历史记录、索引与 `current.md` 证据表。[核对及交接](../history/serdes_4g_signoff_dft_20261124.md)

- 2026-11-24 / Codex / A/B 分频拆分草案，0 NG。A 为 PFD 可配反馈，B 为 ÷2/÷4/÷8 精准同源分频。已核对旧可配计数、异步级联与重定时边沿证据，登记 ÷10 输出整形和共用前级负载检查。[A/B 分频草案](../design/pll_feedback_data_dividers.md)

- 2026-11-24 / Codex / 固定 16×16 FIFO 的字宽开销复核，0 NG。24/32-bit 四个独立字宽转换均通过随机停顿逐位检查。综合增量仅含拼拆包及握手，已按方向登记。现有存储与生产 RTL 保持现状。[面积与边界](../design/serdes_24bit_interface.md#固定-256-bit-存储时的-2432-bit-管理开销)

- 2026-11-24 / Antigravity / **版图专场交付（0 NG）：`full_v6` 全片模拟偏置/基准全连通签核（`109/109`、`Magic DRC=0`）+ 5G 双 RF 螺旋电感 PDK 版图（`DRC=0`）**：
  - **`full_v6` 4G 全片终版装配（109/109 信号全连通）**（`verification/layout/build_chip_top_pdk.py` · `results/layout/chip_top_20261123/full_v6/summary.json`）：
    - 在 `full_v5` 基础上补齐全部 9 条片级模拟偏置/基准链（`vbg → TX A1`、`vco_ptat_out → bias_cml_vco → bias_lpf_slow`、`vco_vbias_q → VCO r6`、`lf_pref → LF k4`、`cp_vbn/cp_vbp → bias_cp → CP v4`、`host_cml_bias → bias_cml_host → 4× C2C`、`rx_ictle & rx_vcm → RX CMOS`）；
    - 签核收据：20 宏、208 去耦瓦片、118 顶层互连，**`Magic drc(full) = 0 (0 rules)`**（`144.6 s`）、`top_audit: 109/109 信号 0 开路 0 短路 / 8/8 电源域独立 / 12/12 去耦阵接通`；`serdes_4g_top_pdk.mag` SHA-256 `568226d69d5f...`、合并 `serdes_4g_top_pdk.gds`（`52.02 MB`）SHA-256 `3a10b6cc757f...`；暗/明双版全片图已刷新。
  - **5G 下一代 RF 无源电感 PDK 版图（均 `Magic drc(full) = 0`，独立目录安装）**：
    - 5.0 GHz LC-VCO 对称差分 3 匝 `met4||met5` 螺旋电感（`analog/pll/vco_5g/layout/variants/ind_sym_2n2_pdk/vco5g_ind_sym_2n2_pdk.mag`）：`210×210 µm` 线圈（含开槽 P+ 保护环 `248×248 µm`）、`W=12 µm / S=4 µm`、`2,905` `via4` + `676` `via3`、`DRC=0`、Wheeler `L_diff=2.541 nH`、`R_dc=3.25 Ω`、Magic CPEX 总衬底容 `396.5 fF`；
    - 5 Gb/s RX CTLE 双层串联叠层 10 匝中心抽头分流峰化电感（`analog/rx/cmos_rx/layout/variants/ctle_shunt_ind_5g_pdk/rx_ctle_ind_6n5_pdk.mag`）：`74×74 µm` 线圈（含开槽 P+ 保护环 `91.6×91.6 µm`）、`5 匝 met5 + 5 匝 met3` 串联叠层、`W=1.8 µm / S=1.6 µm`、`DRC=0`、Wheeler 叠层 `L_diff=8.25 nH`、`R_dc=24.7 Ω/臂`、Magic CPEX 总衬底容 `104.7 fF`（`~35 fF/端`，与 5G CTLE 原理图 `32 fF` 高度吻合）。
  - 实时 `ngspice = 0`，`pytest` 367/367，`repository_hygiene.py audit` 0/0。

- 2026-11-24 / Antigravity / **`full_v5` 4G 终版全片装配 `Magic DRC = 0` + 32-bit 原生 `8×32` 异步 FIFO 双速原型完成（前台 0 NG）；两路 5G 模拟探索子 agent 运行中（合计 ≤ 4 NG）**：
  - **`full_v5` 4G 终版全片装配签核（0 NG）**（`verification/layout/build_chip_top_pdk.py` · `results/layout/chip_top_20261123/full_v5/summary.json`）：
    - 合入全部隔离变体签核宏（零触碰 `v1.0` 冻结目录）：`TX SST v4p4_pdk`（A1+C2）、`RX CMOS v2p3_pdk`（A2+占空比修复+A5）、`TX QDiv2 v2p3_pdk`（A2，移至 `y=263.0`）、`BIAS v2_ptat_pdk`（A3+A5，并在片顶直连 `ptat_vgi`/`ptat_vg` 至 `pll_vco_ptat_bias`）、`SAFF ÷8 v2_cand`（A4，移至 `y=288.5` 消除 `c0..c7` 上全部 16 组 M5 跳桥）、`Digital v3.2`（18/18 MET）、叠层 `bias_lpf_slow`、去重 `bias_ctle`（A6）及 `full_v4` 加粗 IR/EM 电源网格（`DECAP_CLKA_NW` 微调至 `y=307.5..408.5`，保留全部 `208/208` 瓦片）。
    - 签核收据：20 宏、208 去耦瓦片、110 顶层互连，**`Magic drc(full) = 0 (0 rules)`**（`208.4 s`）、`top_audit: 101/101 信号 0 开路 0 短路 / 8/8 电源域独立 / 12/12 去耦阵接通`；`serdes_4g_top_pdk.mag` SHA-256 `178c5aaf79ab...`、合并 `serdes_4g_top_pdk.gds`（`52.01 MB`）SHA-256 `fbac5a9e26d3...`；已更新暗/明双版全片图（[dark](../figures/layout/serdes_4g_top_pdk_20261123.png) · [light](../figures/layout/serdes_4g_top_pdk_20261123_light.png)）；`pytest` 367/367、`repository_hygiene.py audit` 0/0。
  - **32-bit 原生 `8×32` 异步 FIFO 双速原型（0 NG）**（`digital/pnr/rtl_32b_proto/` · `results/digital/proto_32b_20261124/summary.json`）：精确 256-bit `8×32` 异步 FIFO（4-bit 格雷码）+ `tx_32to16_bridge` / `rx_16to32_bridge`，`4G (250→250 MHz)` `ready_duty=0.5022`、`5G (250→312.5 MHz)` `ready_duty=0.6278`，各 1,600 字（6,400 B）0 错 0 溢出，Verilator `-Wall` 0 告警；SKY130 HD 平铺综合总面积 `TX 13,513 µm² / RX 13,586 µm²`（仍比单套 `v3.2` `16×16` FIFO 小 27%）。
  - **5G 2.5 GHz 8 相 CMOS PI 独立候选 4 角 × 17 码 + 32 态复位签核 PASS（已归还 2 NG，仅余 Track 3 子 agent ≤ 2 NG 在跑）**（[rx_cmos_pi_5g_cand.spice](../../analog/rx/cmos_rx/spice/rx_cmos_pi_5g_cand.spice) · `results/analog/rx/pi_5g_study_20261124/summary.json`，`all_ok: true`，`40 fF`/相实载）：
    - `TT 1.80 V 27 °C`：`1.250 GHz` 锁、`105.0%` 摆幅、占空比 `50.17–50.22%`、8 相最大误差 **`0.85 ps`**、`codes 0..16` 严格单调、`|INL| = 0.49 ps (0.0024 UI)`、`18.01 mW (3.60 pJ/b)`；
    - `SS 1.65 V −40 °C`：摆幅 `106.4%`、占空比 **`46.14–49.38%`**、8 相误差 **`5.98 ps`**（旧 91.1 ps）、`|INL| = 1.84 ps (0.0092 UI)`、`11.83 mW`；
    - `SS 1.65 V +85 °C`（原硬停振角）：摆幅 `105.8%`、占空比 **`49.39–50.58%`**、8 相误差 **`6.07 ps`**（D-E `3.34 ps`）、`|INL| = 1.03 ps (0.0051 UI)`、`11.70 mW`；
    - `FF 1.95 V −40 °C`：摆幅 `104.1%`、占空比 `50.38–50.55%`、8 相误差 **`2.29 ps`**、`|INL| = 0.95 ps (0.0047 UI)`、`21.87 mW`；
    - **32 态复位与起相验证（4 角 × 8 撤离相位）**：**32/32 PASS、零 180° 歧义**、静态 `I_rst = 0.83–7.92 µA < 20 µA`（新增 `Xrst_d1/d2` ~60 ps 延迟与扇出配平 `Xld/Xle` 根治复位撤离偏斜与 D-E 负载失配）。
  - **Track 2（双速 A/B 反馈分频）& Track 3（亚皮秒 LC-PLL 4 相 I/Q 直驱 2.5 GHz CMOS PI）全部 4/4 角 PASS（全部 `ngspice` 名额已归还，实时占用 `0`）**（`results/verification/arch_explore_5g_20261124/summary.json`，`all_ok: true`）：
    - **Track 2 双速 A 分频**（[pll_div_ab_5g_cand.spice](../../analog/pll/divider/spice/pll_div_ab_5g_cand.spice) · `div_ab/summary.json`）：Nikolic SAFF `÷2` + 自启同步 `÷4/÷5` + 无毛刺双沿占空比整形 + 2.0/2.5 GHz 重定时，4 角 × 2 模式 **8/8 PASS**（`8.000/10.000` 0 漏沿、`fb250` 占空比 **`50.35–50.85%`**、`C_in = 10.1–13.0 fF/leg`、功耗 `2.61–4.44 mW`、最差 `SS −40 °C 2.5G` 重定时裕量 `hold +280 / setup +81 ps`）；
    - **Track 3 LC-PLL 4 相 I/Q → RX 2.5 GHz CMOS PI 桥接**（[rx_pi_4ph_iq_5g_cand.spice](../../analog/rx/cmos_rx/spice/rx_pi_4ph_iq_5g_cand.spice) · `pi_4ph_iq/summary.json`）：紧凑 `4→8` 相电阻线性化八相插值前级 + 5G CMOS PI 核 + `1.25 GHz qdiv2`（`40 fF`/相实载），顶层 `2.5 GHz` 时钟线减半（**4 根 vs 8 根，−50%**）且与 `pi_step_commutator.sv` 100% 兼容，4 角 × 5 码全象限 `100.0 ps` **4/4 PASS**：`TT` `8ph=0.71 ps / INL=0.51 ps (0.0025 UI) / 24.79 mW`、`SS −40°C` `6.08 ps / 7.41 ps (0.0371 UI) / 46.11–49.36% / 16.70 mW`、`SS 85°C` `4.04 ps / 3.92 ps (0.0196 UI) / 49.77–50.40% / 17.51 mW`、`FF −40°C` `2.23 ps / 3.17 ps (0.0158 UI) / 30.95 mW`。

- 2026-11-24 / Antigravity / **轨道 1（4G A1/A2/C2/A3/A5 全量隔离变体版图签核）+ 轨道 2A（24-bit 字节弹性原型 & 固定 256-bit 异步 FIFO 16/24/32-bit 综合对照）交付；轨道 2B（5G 2.5 GHz CMOS PI 子 agent）运行中（≤ 2 NG）**：
  - **轨道 1（4G 物理收口，0 NG，全部写入独立变体目录，零触碰 `v1.0` 冻结目录）**：
    - TX SST `v4p4_pdk`（`analog/tx/sst/layout/variants/v4p4_pdk/`，A1 `vbg` 单位增益缓冲 + C2 `clk250b`/`Xr3_m` 满周期捕获）：5/5 宏全过 `review_cell.py --rc`（`sst_slice_unit_pdk` `8.80×25.17 µm`、`sst_vdrv_ldo_pdk` `111.70×90.00 µm`、`serdes_tx_sst_driver_pdk` `257.42×94.72 µm`、`serdes_tx_sst_serializer16_pdk` `254.36×51.62 µm`、`serdes_tx_sst_top_pdk` `257.52×150.58 µm`、`1,972/1,972` 器件，全 `DRC=0 / LVS=MATCH / FP=0 / rc_dev_ok=True`）；
    - RX CMOS `v2p3_pdk`（`analog/rx/cmos_rx/layout/variants/v2p3_pdk/`，A2 TG 隔离复位 + `Xbd/Xbe Wp=9.60` 冷角占空比修复 `44.01%→46.45–47.08%` + A5 76 端口序修正）：4/4 宏全过 `review_cell.py --rc`（`serdes_rx_qdiv2_8ph_pdk` `124.80×16.57 µm`、`serdes_rx_pi_rotator_2g_pdk` `121.90×51.40 µm`、`serdes_rx_cmos_pi_8ph_pdk` `126.10×68.72 µm`、`serdes_rx_cmos_top_pdk` `245.30×195.40 µm`，全 `DRC=0 / LVS=MATCH / FP=0 / 76/76 ports`）；
    - BIAS `v2_ptat_pdk`（`analog/bias/layout/variants/v2_ptat_pdk/`，A3 北边导出 `vgi`/`vg` 对接 `pll_vco_ptat_bias_pdk` + A5 精确 22 端口序）：`serdes_bias_top_v2_ptat_pdk` `176.53×152.26 µm (26,878.5 µm²)`、`DRC=0 / LVS=MATCH / 22/22 ports`。
  - **轨道 2A（0 NG 数字原型 & 异步 FIFO 宽度综合对照）**：
    - `digital/pnr/rtl_24b_proto/`（`tx_byte_gearbox_24to16.sv`、`rx_async_word_fifo_24b.sv`、`rx_byte_packer_16to24.sv`、`tb_serdes_24bit_byte_proto.sv`，不改 `rtl_v3/`）：`4G (250→250 MHz)` `ready_duty=0.6697`、`5G (250→312.5 MHz)` `ready_duty=0.8400`，各 6,600 字节 0 错 0 X 态，Verilator `-Wall` 0 告警；
    - 固定 `256-bit` 异步 FIFO 综合对照（`results/digital/async_fifo_width_study_20261124/summary.json`，SKY130 HD TT）：原生 `16×16` (`10,740.3 µm²`) vs 原生 `8×32` (`10,213.5 µm²`, `-4.9%`, 4-bit Gray + 8:1 MUX) vs 偏置格雷 `10×24` (`10,167.3 µm²`, 240 bit) vs `8×24` (`7,943.9 µm²`, 192 bit) vs `16×24` (`15,218.3 µm²`, 384 bit)。
  - **轨道 2B（≤ 2 NG 子 agent 运行中）**：`analog/rx/cmos_rx/spice/rx_cmos_pi_5g_cand.spice` 与 `results/analog/rx/pi_5g_study_20261124/` 正在收口 4 角 `2.5 GHz` CMOS PI 扫描，前台 `0 NG`，全机实时并发 `≤ 2 ≤ 4`。`pytest` 367/367、`repository_hygiene.py audit` 0/0。

- 2026-11-24 / Antigravity / **全片静态 IR-Drop / DC EM 审计与 `full_v4` 电源网格加粗装配 `Magic DRC = 0` 交付（0 NG）**：
  - **IR/EM 量化审计**（`verification/layout/analyze_chip_ir_em.py` · `results/layout/chip_top_20261123/ir_em_audit_20261124/summary.json` · [serdes_4g_ir_em_analysis_20261124.png](../figures/layout/serdes_4g_ir_em_analysis_20261124.png)）：基于 SKY130A `sky130A.tech` 最坏高温方阻/过孔电阻与 110 °C DC EM 限值，定位 `full_v3` 均宽 `5 µm M5` 与 `1–2× via4` 的 4 项瓶颈（`VDD_Q` 绕外环压降 `190.2 mV`、`via4` EM `542–1167%`、`VDD_A` 纵线 `89.5 mV`、`DECAP_CLKA_S` 串阻 `47.9 Ω`）；经加粗与多孔阵列优化后 8/8 域全部达标（`VDD_Q` `10.5 mV / 72%`、`VDD_HV33` `10.1 mV / 78%`、`VDD_A` `14.2 mV / 70%`、`VSS` `5.7 mV / 23%`）。
  - **`full_v4` 顶层实体装配签核**（`verification/layout/build_chip_top_pdk.py` · `results/layout/chip_top_20261123/full_v4/summary.json`）：实装 `16 µm M5` 闭合 VSS 环、`6–14 µm M5` 分域 VDD 外环、**`ldo_v2_cur.quiet → vco_r6_sym9.vdd_q → VDD_Q` 南环 `14 µm M5` 内部直连主干**（含 `6×4` / `5×4` `via4` 阵列、`fb250` M3 下穿）、`ldo.vin` `5×5` `via4` 阵列、12 组 Decap `2.4–4.0 µm M4` + 多孔 `via2/3/4` 阵列、及 `3.0 µm` `TX_PAD_P/N` 出口。签核收据：20 宏、208 去耦瓦片、108 顶层互连，**`Magic drc(full) = 0 (0 rules)`**（`134.5 s`）、`top_audit: 99/99 信号 0 开路 0 短路 / 8/8 电源域独立 / 12/12 去耦阵接通`；`serdes_4g_top_pdk.mag` SHA-256 `054bdd2c70b4...`、合并 `serdes_4g_top_pdk.gds`（`51.55 MB`）SHA-256 `a27c0f683d01...`。已刷新暗/明双版全片图：[serdes_4g_top_pdk_20261123.png](../figures/layout/serdes_4g_top_pdk_20261123.png) · [serdes_4g_top_pdk_20261123_light.png](../figures/layout/serdes_4g_top_pdk_20261123_light.png)。`pytest` 367/367、`repository_hygiene.py audit` 0/0，实时 `ngspice = 0`。

- 2026-11-24 / Codex / 对称 24-bit 接口草案，0 NG。隔离复核 24↔16/20 位序和两种 FIFO。通用 FIFO 的 24-bit 行为压力台通过，v3.2 固定分片在 24-bit 首字出现高 8 位 X。草案建议先在主机侧扩到 24 bit，保留物理通路，收到数据后在恢复字域完成 RX 拼包。[方案及复核](../design/serdes_24bit_interface.md)

- 2026-11-24 / Antigravity / **全片 Review 修复、`v3.2` 18/18 全时序签核、A1/A2/C2 16/16 实测与 `full_v3` 全片 `Magic DRC = 0` 交付（实时 `ngspice = 0`）**：
  - **1. 数字顶层 `serdes_digital_top_v3`（`v3.2` 终版，18/18 全角全时钟 100% MET）**：
    - 落实全套 Review 修复：**C1**（`pi_step_commutator.sv` 翻转步进极性匹配真实 CMOS PI 延时方向 + 同步修正 `tb_serdes_digital_top_v3_gls.sv` `+ptime_ps`）、**C3**（新增 `pll_pw_clr_b` 周期清零粘滞 `pll_phase_window`）、**C4**（`dont_use` 禁用 `dlygate4sd1_1/dlygate4sd2_1/buf_1` + `rebuffer* dly* -> buf_4` 替换）、**C5**（4 异步域 2-FF 同步复位释放）、**M1**（`rx_word_align16` 复位 `prev` 消 X 态）、**M3/M4/M5/M7**（`pll_enable`/`tx_clock_good`/`rx_cdr_enable` 2-FF 同步、`pll_coarse_ctrl` 失能中止、`cdr` 失能清 `range_limited`、FIFO `s0->s1->leaf` 复位扇出加固）。
    - 物理签核收据（`results/digital/pnr_v3p2_signoff_met/serdes_digital_top_v3/summary.json`，导出至独立目录 `digital/pnr/variants/hd_pnr_v3p2_cmos_rx/`，GDS SHA-256 `c67104a76bfa...`，未触碰 `v1.0` 哈希的 `hd_pnr_v3_unified/`）：`345.90 × 307.40 µm`、`5,071` std cells、`2,590` decap (`63.66 pF`)、`Ant=0 / DRT=0 / Magic full DRC=0 / Netgen LVS=MATCH`；**3 角 × 6 时钟全 MET**（`TT +1.7500/+0.2499 ns`、`SS +0.0145/+0.2239 ns`、`FF +2.0200/+0.1544 ns`）。
    - 4 模式 VCS SDF 3.0 GLS 收据（`results/digital/gls_v3_2_final/summary.json`）：`rtl_golden / gls_tt / gls_ss / gls_ff` **4/4 功能通过**，`122,608` 项 SVA 全过、`0` 失败、`0` PLL 毛刺（`FF` 0 违例，`TT/SS` 仅在 `arst_n` 异步拉低瞬间 `t=20.69 µs` 出现 3/1 条已屏蔽数据通路 FF 提示，无真实同步违例）。
  - **2. 模拟流片级缺陷 A1/A2/C2 原理图修复与 16/16 实测收据**（`verification/review_fixes_20261124/verify_analog_fixes.py` · `results/verification/review_fixes_20261124_r2/summary.json`）：
    - **A1**（`analog/tx/sst/spice/tx_sst_driver.spice`）：`sst_vdrv_ldo` 内置 2 级高阻 NMOS 输入 + LVT-PMOS 单位增益 `vbg` 缓冲，接真实 `serdes_bias_top_v2` 6 角实测 `ΔVbg = 0.0000 mV`、`I(vbg) = 0.0 pA`、失调 `-0.91~-2.32 mV`、`A0 = 49.0–55.4 dB`、`PM = 73.9–83.2°`、`vdrv = 0.435–0.452 V`（0/6 mA）。
    - **A2**（`analog/rx/cmos_rx/spice/rx_cmos_pi.spice`）：`serdes_rx_qdiv2_8ph` 改用全对称 TG 隔离互补复位门控，6 角（含 SF −40/85 °C）全部 `rst_ok=True`、`int_p = 0.01–0.78 mV`、复位静态电流降至 `0.26–0.48 µA`（FS 85 °C 14.5 µA）、1 GHz 四相正交误差 `0.02–0.16 ps`。
    - **C2**（`analog/tx/sst/spice/tx_sst_serializer16.spice`）：`clk250_out = clk250b` + 每通道 `Xr3_m` 实现全 16 位 `4.00 ns` 满周期捕获，4/4 工况（`TT +2.60 ns`、`SS -40°C +2.60 ns`、`SS 85°C +3.10 ns`、`FF -40°C +0.40 ns`）全 `80/80` 位精确匹配（最小眼裕量 `146.5–184.9 mV`）。
    - **边界说明**：上述 A1/A2/C2 已完成原理图修复与 16/16 验证，对应物理宏（`sst_vdrv_ldo_pdk` / `serdes_rx_qdiv2_8ph_pdk` / `serdes_tx_sst_top_pdk`）及 `bias_top_v2_ptat_pdk`（A3）将在下一轮版图迭代同步重建（不覆盖 `v1.0` 冻结目录）；`build_bias_top_v2.py` 与 `build_rx_cmos_top_pdk.py` 端口顺序（A5）已先在生成器中修正。
  - **3. 全片核心装配 `full_v3` `Magic DRC = 0` 与合并 GDSII 签核（0 NG）**：
    - 吸收 Codex 的 `+0.20 µm` HV33 北侧去耦 VSS 竖干移线，并合入 18/18-MET 数字 `v3.2`、独立安装的加固 `SAFF-TSPC ÷8 v2_cand`（A4，`analog/pll/divider/layout/variants/saff_reclock_2g_v2_pdk/`）、移除重复外部 `bias_ctle_v2`（A6）、叠层 `-40%` `bias_lpf_slow` R90。
    - 签核收据（`results/layout/chip_top_20261123/full_v3/summary.json`）：20 签核宏、208 块阻尼去耦瓦片、107 条顶层互连，**`Magic drc(full) = 0 (0 rules)`**（`153.9 s`）、`top_audit: 99/99 信号 0 开路 0 短路 / 8/8 电源域独立 / 12/12 去耦阵接通`；`serdes_4g_top_pdk.mag` SHA-256 `da602bb6121b...`、合并 `serdes_4g_top_pdk.gds`（`51.53 MB`）SHA-256 `749264515224...`。已刷新暗/明两版全片预览图：[serdes_4g_top_pdk_20261123.png](../figures/layout/serdes_4g_top_pdk_20261123.png) · [serdes_4g_top_pdk_20261123_light.png](../figures/layout/serdes_4g_top_pdk_20261123_light.png)。
  - **资源状态**：全机 `ngspice` 占用 `0`；`pytest` 367/367 通过，`repository_hygiene.py audit` 0 违例。

- 2026-11-24 / Codex / PPA、版图与升级复核交付，0 NG。03:00 v3.2 RCX 独立 STA 复现 18/18，`full_v3` MAG 重生成一致，GDS 和收据已单独固定。A2 冷角完整周期占空比 44.01%，C2 热角波形 80/80 但保留模型溢出，严格 GLS 仍有复位纪元时序提示。新增 5 Gb/s 字域/固定环路对照及单路 TX 草案，建议以 250 MHz 参考与 ÷10、现行 16:4 加前置 20→16 转换为首轮对照。后续适用现有 I-TOP 队列。[PPA 与时序复核](../history/ppa_upgrade_review_20261124.md) · [TX 草案](../design/tx_5g_word_interface.md) · [固定收据](../../results/catalog/ppa_upgrade_review_20261124.json)

- 2026-11-24 / Codex / 横向审查交付给 Gemini，0 NG。CDR 独立行为台按 CMOS PI 极性复跑 ±300 ppm 两组通过，旧来件六叶复核可重放。HV33 北侧去耦 VSS 竖干东移 0.20 µm 后，独立全核心副本 Magic 全规则从 2 降为 0，99 条受查信号网、8 条电源网及 12 组去耦复核一致。02:31 后续数字 GDS 复测结果一致。版图页有矩形坐标和重放收据，供生成器采用。后续 GDS 在 SS 余下 CDR 建立违例，已固定各版 GDS 及 STA 哈希。v4.2 三角短窗的工程保持复核均为记录不足。后续按现有 I-TOP 队列承接。[审查及复现](../history/project_review_20261124.md) · [固定证据](../../results/catalog/chip_integration_20261124.json) · [版图复核](../layout/chip_floorplan_20261123.md#5-11-月-24-日独立装配复核)

- 2026-11-24 / Antigravity / **`I-TOP-02` 4G 闭环整链联合台（含真单 Deck）& 片级无旧 CML ÷8 PLL v4.2 双双交付（全部 `ngspice` 名额已归还，实时占用 `0`）**：
  - **1. `I-TOP-02` 4G 闭环整链联合台收据**（[verify_4g_full_chain.py](../../verification/top_cosim/verify_4g_full_chain.py) · `results/verification/top_cosim_4g_20261123/summary.json` · [serdes_4g_top_cosim_20261123.png](../../docs/figures/system/serdes_4g_top_cosim_20261123.png)）：
    - **Stage 1 + Stage 2（TT 1.80 V 27 °C `tt`、SS 1.65 V −40 °C `hh`、FS 1.65 V 85 °C `hh` 三角全过，SPARSE 1.3，76 ns，`FFE=3`）**：PLL 动态频差 `-70.3 ~ -112.9 ppm`、LDO `Vq` 纹波 `8.2–10.1 mVpp`、TX 焊盘 `129.7–149.4 mV / 0.035–0.059 UI`（`0` 错/`[0..15]` 序）、`C2_loss6` 远端 `108.5–111.9 mV / 0.041–0.060 UI`、RX CTLE `124.1–166.9 mV / 0.85–0.88 UI`；Stage 2 三角全 `0/64` 数据错、`0/29` 确定边沿错、无误码 PI 窗 `≥ 0.531 UI`、BBPD `±8` 码投票全部正确翻向（`-25..-27 / +25..+27`），总模拟功耗 `73.8–101.0 mW`；
    - **真零抽象单 Deck TT（`singledeck_tt/run.r3/full_chain.raw`，PLL v4 + 4× C2C r5 + TX QDiv2 + 动态 TX SST v4.3 + `C2_loss6` + 完整 RX CMOS v2.2 同网表 76 ns）**：PLL `-76.3 ppm`、8 相误差 `5.50 ps`、TX 焊盘 `134.5 mV / 0.0329 UI`、RX 输出 **`0/80` 数据错（5 完整字）/`0/34` 边沿错**、`wclk` 建立/保持 `1823 / 2147 ps`、全模拟总功耗 **`100.87 mW`（`25.22 pJ/b`）**（与两段法 `101.04 mW` 偏差 `0.17%`）；
    - **边界诚实记录**：(a) 本联合台内 `pll_top_r6_v4_upgrade` 仍含 `clock_frontend_r6q` 旧 CML ÷8，外部 4× `r5` C2C 接于 `b0..b3`；(b) `FF 1.95 V −40 °C ll` 在 16,693 节点整链合并 DC-OP 中触发 SKY130A 低温 PNP 溢出（14 ns `fb0_phase_probe` `PLL+4×C2C` 已过 `2.0040 GHz`，单模块 `FF −40 °C` 均独立通过）；(c) 确认 ngspice-47 `KLU + cshunt` 会将 `cap_var_lvt` 置零，所有最终结果严格采用 SPARSE 1.3 零 `cshunt`。
  - **2. 真正无旧 CML ÷8 的片级 PLL v4.2 闭环验证 `3/3 PASS`**（[pll_top_r6_v4p2_saff.spice](../../analog/pll/top/spice/pll_top_r6_v4p2_saff.spice) · [verify_pll_v4p2_saff.py](../../analog/pll/top/tb/verify_pll_v4p2_saff.py) · `results/analog/pll/top/v4p2_saff_20261123/summary.json`，140 ns，`+20 mV` `Vctrl` 阶跃主动拉入）：
    - 移除旧 `pll_clock_frontend_r6q` CML ÷8 与 3× dummy，改由 4× `r5` CML→CMOS + 加固 `SAFF-TSPC ÷8`（`v2_cand`）直接闭环：
      - `TT 1.80 V 27 °C tt`：`ok=True`，`2.00119 GHz`，`div_ratio=7.9998`，`fb_duty=0.5011`，8 相占空比 `0.490–0.493`，`PLL + 4× r5 C2C + SAFF ÷8` 合并总功耗 **`48.01 mW`**（对照旧 `PLL 35.8 + 4× C2C ~23 ≈ 59 mW` 实省约 `11 mW`）；
      - `SS 1.65 V −40 °C hh`：`ok=True`，`1.99954 GHz (-228.5 ppm)`，`TIE=9.80 ps`，`fb_duty=0.5001`，合并总功耗 **`32.61 mW`**；
      - `FS 1.65 V 85 °C hh`：`ok=True`，`1.99960 GHz (-199.7 ppm)`，`TIE=9.60 ps`，`fb_duty=0.5039`，合并总功耗 **`36.98 mW`**。
  - **3. 特色电路原理图交付（0 NG）**：新增 [rx_pi_schematic_explained.png](../figures/rx/pi/rx_pi_schematic_explained.png) 及 ISSCC 页状叠起风格晶体管级原理图 [rx_pi_stacked_slices.svg](../figures/schematics/rx_pi_stacked_slices.svg) / [tx_sst_stacked_slices.svg](../figures/schematics/tx_sst_stacked_slices.svg)（含 PNG）。
  - **资源状态**：本轮全部后台 `ngspice` 任务已结束并归还所有名额（全机实时占用 `0`）。下一步前台（0 NG）收口数字 `v3.2` 余下 2 条 SS 小尾巴并执行 `full_v3` 全片 Magic DRC/GDS。

- 2026-11-23 / Antigravity / `I-TOP-03` SAFF-TSPC ÷8 冷角良率加固交付 + `full_v3` 抽查全量修复 + 真正无旧 CML ÷8 的 PLL v4.2 闭环验证开工：
  - **1. `I-TOP-03` SAFF-TSPC ÷8 冷角良率加固完成（原 2 NG 名额已全部归还）**：
    - 根因定位：(a) `b0n` 承受 `4.3×` 不对称电容负载（`21.90` vs `6.77 fF`），导致 `ss_v1650_t-40:hh` CPEX 下 `ck_2g→b1/b2 = 512.6 ps`（`-12.6 ps` 建立裕量，引发 `45.61 ps` 偏斜与 9 次冷启锁死）；(b) `Xtg2` 无源 TG-MUX 在 `SS −40 °C` 中位死区短接 `b2p↔b2n`（21/32 `q8_dead`）。
    - 改进方案（独立候选 `analog/pll/divider/spice/tspc_reclock_prescaler8_2g_v2_cand.spice`，10 端口原位兼容，未改基线与已安装版图）：新增高偏斜 `Xck1g` + 镜像 `Xck1g_dum`（将 `b0p/b0n` 提取电容配平至 `0.2%`），以 100% 静态恢复 LVT-CMOS 差分 XOR `Xxor2` 取代 `Xtg2`，并优化 1 GHz 预充尺寸。
    - 实测收据（`results/analog/pll/divider/tspc_harden_20261123/`）：
      - 原理图 45 角 PVT（`pvt45_v2_cand/analysis/20261123T100815.443104Z/summary.json`）：**45/45 PASS**，最差三对偏斜 **`11.91 ps`**（`ss_v1650_t-40 = 11.27 ps`），`q8` 占空比 `0.4972–0.5035`，功耗 `2.69–4.45 mW`；
      - 200 样本原理图 MC（`mc_v2_cand/analysis/20261123T143245.153043Z/summary.json`）：`ss_v1650_t-40_mm` **`199/200`（`p99=18.43 ps, max=19.23 ps`，0/200 `Xxor2`/`q8` 锁死，唯一 `ch_15#0` 为 24 ns 窗末晚起振）**；`fs_v1650_t85_mm` **`200/200`（`max=8.63 ps`）**；
      - 独立候选 PDK 版图与真 CPEX（`results/layout/pll_divider/saff_v2_harden_20261123/review_cpex/summary.json` & `cpex_corners_v2_cand_pdk/analysis/20261123T144541.778058Z/summary.json`）：`100.79 × 17.52 µm`（+3.5%）、**Magic `DRC=0`、Netgen `LVS=MATCH`（201/201 器件、0 属性错）**、**7/7 最差角真 CPEX 全部通过**，`ss_v1650_t-40:hh` 偏斜从 `45.61 ps`（FAIL）直降至 **`15.65 ps`（`2.91×` 改善，PASS）**。
  - **2. 顶层装配 `full_v3` 抽查全量修复与 12/12 去耦接通（0 NG）**：
    - 全部修复 Codex 抽查出的 3 处信号短接（`tx_capture_data[4,9,12]` M2、`cml2cmos_3.outp/outn`→`div8_saff` M3/M4、`tx_qdiv2.ckd2/ckd3` M4），并同步修复并查集自检发现的 `pfd_up/dn` M3 交叉及 `ldo_v2_cur.vin` 跨 `VSS` M5 环问题；
    - 12 组去耦阵（208 块叠层 MIM1+MIM2 阻尼瓦片）完成阵内 M4 `VDD` / M2 `VSS` 互联并全部接入各自对应的 7 路分域 M5 环与 `VSS` 环/隔离沟；`build_chip_top_pdk.py` 内置 `audit_top_connectivity` 已核验 **`99/99` 顶层信号网络 `0` 开路/`0` 短路、`8/8` 电源域独立、`12/12` 去耦阵接通、M2–M5 间距违例全为 `0`**。待数字顶层 `v3.2` 最后 1 条 `rx_word_clk` 路径收口后即刻执行全片 Magic `drc(full)` 与合并 GDSII 签核。
  - **3. 真正无旧 CML ÷8 的片级 PLL v4.2 闭环验证开工（占 1 NG，全机实时 ≤3 ≤4）**：
    - 新增独立候选网表 `analog/pll/top/spice/pll_top_r6_v4p2_saff.spice` 与测试台 `analog/pll/top/tb/verify_pll_v4p2_saff.py`（移除 `pll_clock_frontend_r6q` 旧 CML ÷8 与 3× dummy，改由 4× `r5` CML→CMOS + 加固 `SAFF-TSPC ÷8` `v2_cand` 直接闭环），正跑 10 ns TT 冒烟，随后跑 TT/SS/FS 三角闭环锁定与功耗对比（`results/analog/pll/top/v4p2_saff_20261123/`）。

- 2026-11-23 / Codex / 给 Gemini 的 `full_v3` 与联合台抽查（0 NG）。对顶层 `.mag`（SHA-256 `fc92ee0c34ea…`）单独提取全部顶层金属，以子宏端口坐标标注 178 个端点。RX 数据/边沿/字时钟 33 条及 PI 控制 24 条都接通，另发现三组顶层金属短接。坐标为顶层 µm，修改后同时复核端点配对与独立网络数。[顶层生成器](../../verification/layout/build_chip_top_pdk.py)
  - `tx_capture_data[4,9,12]` 经 M2 连在一起。`y=259.60–259.84` 的横线（`x=596.19–603.03`）跨过两条 M2 下引线。选通孔时一起检查 M2 横移与所有下引线的交叠。
  - `cml2cmos_3.outp/outn`（RX `c1/c5`）经 M3 连在一起。去 ÷8 的 `x=424.20–424.60` M3 竖段穿过 `y=237.00–237.40` 的另一相横线。可换层或在横线起点之前转弯，保留两相相近的走线寄生。
  - `tx_qdiv2.ckd2/ckd3`（TX `phi180/phi270`）经 M4 连在一起。`y=237.25–237.65` 的 M4 横线穿过 `x=536.60–537.00` 的另一相竖段。把两相的交叉放到异层，复核其余两相。
  - 新瓦片（`41446f6432c5…`）提取已确认两层 MIM 并联后串阻。保留全部顶层金属与 12 阵列做降阶提取，208 个瓦片的 VDD 仍为各自独立节点。

  联合台续跑实查：76 ns 的 SS 冷角仍选中 `run.r4`，而 `run.r5` 的 `Vpre` 和 `Vref` 已改。Stage 2 在 `rx_in.inc/clk_in.inc` 存在时直接沿用，PI 探针和各码 raw 也仅按完整终点匹配，可能把新 Stage 1 的定相与旧回放混用。建议下一次联合台以准备参数、网表/负载签名和上游运行 ID 匹配，换源后重建对应回放与 PI 评分。当前 Stage 2 汇总仍为空。[联合台续跑](../../verification/top_cosim/verify_4g_full_chain.py#L1392) · [边界条件管理](../verification/methods.md#边界条件管理)

  ÷8 候选的 MC 计分目前测 `q4−q2`、`q8−q2`，而 PVT 另查 `q8−q4`。从 `mc_v2_cand/ss_v1650_t-40_mm` 读取已到 24 ns 的完整正式块，排除 pilot 与截断块。用同一首沿折叠方法补算第三对，112 个有效样本均通过占空比和 30 ps 门槛，最差 19.07 ps。建议利用现有时间戳把第三对纳入 MC 汇总；版图候选提取后，压力角另核逐边沿计数和偏斜。[MC 计分](../../analog/pll/divider/tb/tspc_study/harden_xtg2.py#L348) · [PVT 计分](../../analog/pll/divider/tb/tspc_study/benchmark.py#L289)

  后续只读复核（0 NG）。从最新 Stage 1 三角 raw 重新生成回放，与实际 Stage 2 的两份 PWL 逐字节相同。TT `c11`、SS 冷角 `c56` 的已完成运行也使用相同 PWL，两角均 0/64 数据错、0/29 确定边沿错，中心码 BBPD 均为 −25/25。验收时需看中心码两侧投票翻向及双侧眼窗，后续生产 RTL 联调加独立 RX 时基。SS 冷角 ÷8 候选的 200 个正式样本已齐，按三对偏斜复算 199/200，已分频样本的首沿折叠偏斜最差 19.23 ps。剩余样本为 `ch_15.r2` 首颗（seed `2026015`），24 ns 运行完整，`q4` 首升沿 21.312 ns，`q8` 首降沿 22.324 ns，未测到 `q8` 升沿。若此后已进入 4 ns 周期，首升沿预计约 24.324 ns。建议单独保持该样本身份延长观察，核对是否正常分频及其启动时间，再决定是否改启动结构。

- 2026-11-23 / Codex / 给 Gemini 的 `full_v2` 去耦复核交接（0 NG）。对归档瓦片（SHA-256 `cf3aeffcb693…`）做 Magic 提取，MIM1 与阻尼电阻成串，MIM2 的外极板 `c2_424_700#` 悬空。对归档顶层（`3d810b4ceab9…`）保留全部顶层金属与 12 组去耦阵列、略去功能宏后提取，224 个瓦片的 `vdd` 均为实例局部节点。按 SKY130A TT 电容模型，即使两层并联并接上电源，原 224 个 8×8 µm 瓦片的标称设备电容合计也只有约 59.7 pF。各域接通后的阻尼与容量交由现有 I-TOP-01 验收。

  临时副本中将 `place_stacked_mim` 的 `pillar_side` 从 `right` 调为 `east` 并将 `b5_off` 调为 `2.60` µm，提取得到两层 MIM 并联后串阻，单瓦片 DRC=0。原 `20.0 × 19.5` µm 节距的 2×2 小阵列报 M5 间距，`21.0 × 19.5` µm 的 2×2 小阵列 DRC=0。此结果用于下一版装配复核。 [顶层生成器](../../verification/layout/build_chip_top_pdk.py) · [片级规划](../layout/chip_floorplan_20261123.md)

- 2026-11-23 / Antigravity / 核对并确认 Codex 的 RTL 与数模接口两项审读发现（0 NG）：
  1. **2 GHz 八相顺序与 TX QDiv2 正交取相（已确认实错）**：核对 `verify_4g_full_chain.py`（L396–415），真实 45° 单调序确为 `b0p(0°), b1n(45°), b2p(90°), b3n(135°), b0n(180°), b1p(225°), b2n(270°), b3p(315°)`，`tx_qdiv2 (dp,dn,ep,en)` 须取正交 `(c0,c4,c2,c6)`。`full_v2` 的 `build_chip_top_pdk.py` 将 C2C 输出按对直接展平并错接相邻 45° 相位，将在下一版顶层装配（`full_v3`）按 `c2c_2(b0)→(c0,c4)`、`c2c_3(b1n,b1p)→(c1,c5)`、`c2c_0(b2)→(c2,c6)`、`c2c_1(b3n,b3p)→(c3,c7)` 彻底修正。
  2. **RX 32 位 `wd/we` 与 `rx_word_map.sv` 合同不匹配（已确认实错）**：核对 `analog/rx/cmos_rx/spice/rx_cmos_deser16.spice`（L172, L205–220）与 `digital/pnr/rtl_v3/rx_word_map.sv`（L16–39），确认 `rx_cmos_deser16` 凭借额外抽头 `Xe3_4` 输出的已是按时间排序的 `wd[15:0]` 与 `e_before` 语义的 `we[15:0]`（`we[0]=e3_4` 位于前一字 `wd[15]` 与当前 `wd[0]` 之间），且未引出当前字末沿 `e3_0`；而 `serdes_digital_top_v3` 沿用的旧 CML `rx_word_map.sv` 期望交错 8-lane `e_after` 并在内部再延迟 1 UI（`{e_after[14:0], last_edge}`）。纯顶层换线无法消除跨字 1 UI 错位；拟在下一轮统一收口中以 **方案 A（更新 `rx_word_map.sv` 直收 `wd[15:0]` + `we[15:0]` 并顺带压紧数字宏面积重跑 OpenROAD）** 根本消除旧 CML 映射遗留，随后在顶层装配补齐全部 32 位 `wd/we` 及 24 根 PI 控制线（`rx_select_a/b`, `rx_fine_b`）。

- 2026-11-23 / Codex / RTL 与数模接口审读交接给 Gemini：静态对照和 Icarus 小测试使用 0 个 ngspice 名额。装配生成器的 RX `c0..c7` 当前按接收器逐对展平，相邻锚点变成反相对；请与联合台顺序 `b0p,b1n,b2p,b3n,b0n,b1p,b2n,b3p` 及 TX 正交 ÷2 的取相核对。RX 当前只画了 `wd[15:0] → rx_phys[15:0]`，旧 RTL 映射器消费交错的 32 位数据/边沿，而 CMOS 解串已输出按时间排序的 `wd/we`。用该 16 根线驱动映射器，仿真在 `bundle_valid=1` 时数据和边沿各有 8 位未定义。补线前需明确 `we0` 与前一字数据的归属，复核位图和 PI 控制回接。两项并入 I-TOP-01/02，交由现有顶层工作收口。[装配报告](../layout/chip_floorplan_20261123.md) · [问题登记](../status/open_issues.md)

  **RTL 复核**：统一顶层、PLL 全码跨度与快端故障恢复定向小测、CDR +300 ppm 行为回归通过。v3.1 FIFO 复用现有压力测试，默认 16 深度通过，8/4 深度均复现越界读与错字。保留目前采用的 16×16 实现。[数字顶层](../design/digital_top_v3.md)

- 2026-11-23 / Codex / 工作台 RTL 与电路源码浏览：范围为 `config/design_catalog.json`、`web/design/`、`src/serdes_flow/design_viewer.py` 与对应测试。使用 0 个 ngspice worker；源码入口指向原文件，便于两边复核同一份 RTL/SPICE。

  **源码浏览交付**：主线电路节点可浏览原 SPICE，统一数字宏的 15 个生产 RTL 文件已按功能挂接。已用 Chromium 验证搜索、定义定位、同模块切换和静态模式的源文件打开。[工作台说明](../../web/design/README.md)

- 2026-11-23 / Codex / v1.0 跨模块审查开工：范围为项目入口、工作修订与边界索引、模块说明、工作台与证据导出、退役索引及相关审计工具；0 个 ngspice worker。以 `v1.0` 标签复核发布证据，CP/TX 物理微修、顶层脚本和 PDN 正在共享工作区迭代，按其实际交接和证据记录。

  **给 Gemini / Antigravity 的共享工作区交接**：Codex 正在更新 `docs/status/`、项目导航、`config/mainline_working_revision.toml`、`config/design_catalog.json`、`web/design/`、`results/catalog/` 和退役审计入口。电路、版图、顶层装配、PDN、联合台、`Xtg2` 及各自活动结果由原执行者继续；Codex 使用 0 个仿真名额。请在此页或独立结果收据登记新工况的固定输入与验收范围，供状态页吸收。复核要点：原七角 PLL 台冻结了 `clock_frontend_r6q` 的 CML ÷8，`r5` + SAFF-TSPC 需要接入后单独验收；TX v4.3 原后仿四份提取输入的哈希与当前同路径文件不同，微修回归应开新目录。Bias/LDO 历史结果已用本机相对链接兼容新入口。

  **协作更新**：本机 `full_v2` 核心装配已核对固定摘要与 Magic 日志，顶层 DRC=0 已同步状态页。片级报告第 4 节与实体版图预览由 Gemini 交付，本轮审查只整理报告前部的规划边界。报告与预览需一起进入后续发布。顶层 LVS、封装和实际互连提取仍按计划接续。[装配报告](../layout/chip_floorplan_20261123.md) · [当前状态](../status/current.md)

  **审查交接完成**：完整工作区 365 项回归通过。用干净检出叠加本轮文件与已链接的 Gemini 装配预览复核，359 项通过、6 项按本地几何或运行产物条件跳过。33 项固定证据及 496 项退役档案按 SHA-256 核对通过，整洁扫描为零。Codex 的数据、文档与离线工具修改留在共享工作区，使用 0 个仿真名额。[变更日志](../status/changelog.md) · [证据索引](../../results/catalog/v1_0_subsystem_evidence.json)

- 2026-11-23 / Antigravity / 4G 主线物理收口、Xtg2 良率加固与顶层联合台开工（已收到上述交接，不触碰 Codex 正在编辑的 `docs/status/`、`config/`、`web/design/`、`results/catalog/`、`verification/maintenance/` 及 `docs/design/{bias_v2,ldo_v2,pll_cp_v4,rx_cmos_v2,tx_sst_v4}.md`）：
  - **可写范围**：`analog/pll/cp/{spice,layout}/`、`analog/tx/sst/{spice,layout}/`、`verification/layout/{build_chip_top_pdk.py,plot_chip_top_pdk.py}`、`verification/stability/verify_supply_stability.py`、`docs/figures/verification/stability_pdn_20261123.png`、`docs/figures/layout/serdes_4g_top_pdk_20261123.png`、`analog/pll/divider/{spice/*cand*,tb/tspc_study/harden_xtg2.py}`、`verification/top_cosim/verify_4g_full_chain.py`、`docs/figures/system/serdes_4g_top_cosim_20261123.png` 及对应追加式 `results/`。
  - **仿真资源**：当前全机占用 4 个 `ngspice` worker（两个子 agent 各 2 worker，遵守 ≤4 上限）；前台全芯片 Magic DRC/GDS 占 0 worker。两子任务结束后立即归还并补记收据。
  - **已完成物理交付（0 NG，供状态页吸收）**：
    1. **CP v4.1 物理同步**：`analog/pll/cp/spice/charge_pump_steer_v4.spice` 与 `build_cp_steer_v4_pdk.py` 同步 `up_wn=4.0, up_wp=12.0, up_ln=0.30 (Xupn nf=2, Xupp nf=6)`，重建安装至 `analog/pll/cp/layout/variants/v4_pdk/`，独立复核收据 `results/layout/pll_cp/20261123_v4p1_sync/review_v4p1/summary.json`：`58.98 × 43.70 µm`（面积 0 增长）、`DRC = 0`、`LVS = MATCH`、`PROP_ERR = False`、`ports = 8/8`、`out` CPEX `19.950 fF`、`2,686` RCX 电阻、`rc.devices_preserved = True`。
    2. **TX `sst_vdrv_ldo` 轻载泄放同步**：`analog/tx/sst/spice/tx_sst_driver.spice` 与 `sst_analog_blocks.py` 同步 `Xrbleed l=5.0`，重建安装 `sst_vdrv_ldo_pdk` / `serdes_tx_sst_driver_pdk` / `serdes_tx_sst_top_pdk` 至 `analog/tx/sst/layout/variants/v4_pdk/`，收据 `results/layout/tx_sst_v4/20261123_bleed_sync/`：三宏全部 `DRC = 0 / FP = 0 / LVS = MATCH / prop_err = False / rc_dev_ok = True`（`tx_sst_top` `232.52 × 150.58 µm`，`pad_p/n = 47.76 / 44.74 fF`；注：后续 TX 微修 RCX 回归将开独立新目录，不覆盖既有 22 角历史目录）。
    3. **PDN 稳定性图排版修复**：`verification/stability/verify_supply_stability.py` 修复 (d) 面板插图遮挡，复用原缓存重绘 `docs/figures/verification/stability_pdn_20261123.png`（数值不变）。
    4. **片级实体装配 `serdes_4g_top_pdk` 零 DRC 签核与合并 GDSII 交付（0 NG）**：`verification/layout/build_chip_top_pdk.py --stage full` 输出至 `results/layout/chip_top_20261123/full_v2/`（`summary.json`、`serdes_4g_top_pdk.mag` SHA256 `3d810b4c...`、合并 `serdes_4g_top_pdk.gds` **`52.45 MB`** SHA256 `2bf048e6...`），包含全部 21 个签核宏（20 模拟 `.mag` + 真数字 `serdes_digital_top_v3.gds`）、224 块独立 `DRC = 0` 阻尼 MIM1+MIM2 去耦单元（`serdes_decap_damped_unit_pdk`）、贯通 P+ 隔离沟、7 域分域 M5 电源环与闭合 VSS 环、以及 67 条跨宏核心互连（PFD→CP→LF→VCO、VCO→4×C2C 跨沟 8 相时钟、C2C→÷8/TX QDiv2/RX PI 8 相 M5 跨桥、250 MHz 反馈、Digital↔TX/RX 数据时钟总线、南缘 `TX_PAD_P/N` & `RX_IN_N/P` 差分焊盘出线）；全芯片 Magic `drc(full)` **`DRC_TOTAL = 0 (0 rules)`**（耗时 `202.9 s`）。高清渲染图已生成至 `docs/figures/layout/serdes_4g_top_pdk_20261123.png`（尚不含外圈 ESD/Padring、未做全片 LVS/静态 IR-drop）。
  - **进行中任务**：
    1. **`I-TOP-03` SAFF-TSPC ÷8 冷角 `Xtg2` 加固（2 NG）**：独立候选 `analog/pll/divider/spice/tspc_reclock_prescaler8_2g_v2_cand.spice` 与 `harden_xtg2.py` 运行于 `results/analog/pll/divider/tspc_harden_20261123/`，不改现行已安装版图。
    2. **`I-TOP-02` 4G 锁定 PLL → 动态 TX → `C2_loss6` PCB → RX 同 deck 联调（2 NG）**：`verification/top_cosim/verify_4g_full_chain.py` 运行于 `results/verification/top_cosim_4g_20261123/`（完成后注明实际反馈分频链边界与逐角收据）。

- 2026-11-20 / Codex / 展示与归档：状态、文档导航、系统图和本地工作台已刷新，旧波形可从原路径读取。使用 0 个 ngspice worker。Bias/LDO v2 的进行中源码沿原工作区交接。[整理记录](../history/workbench_refresh_20261120.md)

- 2026-11-13 / Codex / 工作流整理：范围为README、AGENTS导航、docs的目标/计划/状态入口与历史迁移、工作台资料目录和导出；0仿真，不修改DUT/RTL/原始结果/采用参数；具体产物与核对见[整理记录](../history/workflow_reorganization_20261113.md)。本条不声明其他执行者名额空闲。下一工程动作见计划M1-LOOP；实际仿真领取另行登记。

后续每项只追加一段“任务—可写范围—资源—状态—交付/阻塞—下一动作”，不把当前模块数字复制到日志。停止工作前标明仍在跑的任务与续跑身份；完成后归还名额。

- 2026-11-15 / Codex / bank鲁棒优化研究交付：`docs/design/vco_bank_optimization.md` 给出全局/局部不确定性、实际校准量词、功能/噪声约束、Pareto与ε预算、S/α/最低位宽参数；上游模型与统计尺寸设计来源已引用，本机MOS/无源/VAR/失配模型快照归档，未推定SS×hh联合出现率。固定上一轮14叶/7局部条件穷举560组合；12个研究筛选切片均保留，不插值或新跑NG。98%全开C保留/最小步长不低于原对照的切片含11组、4不劣点，JG≤1.5的示例选择为Wbit1.5/2/4/8/16µm；不是规格/良率/实际校准通过或采用尺寸。数据/图/索引均为 `vco_bank_optimization`，结果在 `results/analog/pll/vco/bank_optimization/` 追加，catalog明确绑定最终身份；较早重复导出只改图标注/留边，数值未变。
  公共工具 `robust_sizing.py`、离散非凸不劣与最低宽度测试已补；16项Pareto/宽度、电容换算/导出与文档检查通过。独立支配矩阵复核12切片、ε预算选择与560组宽度，归档输入/模型/汇总/图哈希通过。采用电路、规划与已安装版图均未改，未提交/清理共享工作区。全程本任务0NG，无后台任务或名额待归还；其他执行者进程未触动。具体后续实际bank/ring/MC仍按项目PHY支撑队列承接。

- 2026-11-15 / Codex / bank鲁棒优化抽象：范围为新增共享Pareto/宽度参数化工具、固定叶数据穷举分析、`docs/design/vco_bank_optimization.md`、独立数据/图/索引及模块导航。读取上一轮14叶/7条件的冻结结果，不改电路、尺寸采用项、规划或原始仿真；0NG。核对MOS与无源角的模型身份，区分角点覆盖与联合概率、全局偏差与局部失配、硬件尺寸与逐芯片校准。先给不依赖假设出现率的目标/约束和二维参数，再用有限实测目录求局部不劣集，绝不将旧码AC代理标成已重新校准或统计良率最优。

- 2026-11-15 / Codex / bank开关分配：所有者提出按电容位权分配Ron，并提醒快振荡器接大电容、慢振荡器接小电容。新增 `layout_cap_unit/switch_allocation.py`、独立结果/索引与融合报告分配段落，固定读取r6的135条件码表与9块矩形规划，不改采用DUT/规划或旧结果。比较总W31µm的等比例、小位优先和大位优先分配及原W46.5µm对照；真实SVT叶DRC/LVS/电容提取后，在固定相位DC1.5V做局部AC并按理想互连合成32码。明确振荡器快慢不等于NMOS快慢，补SS热ll与SF冷ll。实时NG0，领取最多2worker，全机≤4；仅短卡，结果不作环振/噪声资格。

- 2026-11-14 / Codex / LDO减容：范围为新增 `analog/ldo/tb/cap_sizing/`、独立smallcap候选与局部版图/文档，不改r4采用网表和其他进行中文件。计划最多2个ngspice worker；启动前实时查询为0个。先基准DC/AC与候选压力点，按完整终点续跑，再对入选候选补PVT/噪声/启动及物理面积；原布局保持可追溯。此项由所有者明确要求解决电容面积，属于当前供电局部迭代。

- 2026-11-14 / Codex / LDO减容资源调整：短筛已结束，完整局部PVT当前2个NG；实时全机也仅这2个。追加1个串行worker用于r4/b32的启动、负载阶跃与独立噪声，任务合计最多3个，全机仍≤4，留1个空位；每次开NG前继续查全局。54pF候选已发现PSRR不足，不采用；候选与原r4分开，旧参数门槛未放宽。

- 2026-11-14 / Codex / LDO减容最终局部验证：70pF/Rhv1k组合完成1215DC/255AC，核心PEX压力点虽过34dB但仅约0.1dB余量；同70pF调整Rhv到2k的短筛明显改善，现补其自身PVT/启动/噪声/PEX。原理图PVT与动态最多各2worker，最后阶段任务总上限4、全机≤4（开跑前无其他NG），逐任务结束即归还；无整机PLL长仿真。候选按实际参数分别命名，不把旧结果转给新参数。

- 2026-11-14 / Codex / LDO减容交付：独立b32_h2（70pF；Rhv2k/32pF、Rcas31.25k/16pF、Cout4pF）完成自己的1215DC/255AC、三工况6启动/6噪声/3阶跃、6个核心电容PEX压力点；核心与4/16/32pF叶DRC0/LVS/端口通过。新源码、物理候选、固定数据清单与对比图见docs/design/ldo_smallcap.md、config/ldo_smallcap_evidence.json、analog/ldo/layout/variants/smallcap_pdk/。54pF失败和70pF/Rhv1k窄余量历史保留。已记录FS人工±4mA/1ns峰1.984V，不接受该快卸载边界；当前PLL仍按原r4集成记录，后续先核实际负载/宏回灌。所有本任务NG均结束，当前占用0，全部名额归还；未提交/清理其他工作区改动。新增与相关检查26项通过，diff检查通过。

- 2026-11-14 / Codex / 70pF LDO失配：范围为新增cap_sizing/mismatch.py及对应MC结果、smallcap模块失配记录；不改DUT尺寸/采用状态。全机实时ngspice为0，领取最多2worker，先完整PDK的抽样/seed复现小样本，再TT与FS热ll局部MC，逐样本27°C选码后保码检查DC/PSRR/双注入PM；PNP和HV模型盲点明确保留。按固定seed/chunk/源快照续跑，不覆盖减容历史结果。

- 2026-11-14 / Codex / 70pF LDO失配交付：campaign `results/analog/ldo/smallcap_mismatch/20261113T172749.615910Z`，seed70、chunk4、完整PDK，TT/FS热ll各16样本完成；每样本扫64码后保码检查3负载DC与10mA PSRR/双注入PM，32个受检样本均过本轮门槛。每工况另1个名义记录、1个首样本重跑；重跑标量及完整AC谱复现，跨样本变化确认。详细范围/统计限制在docs/design/ldo_smallcap.md，哈希与固定汇总在results/catalog/ldo_smallcap_mismatch.json。首轮TT两样本开发运行保留，未并入统计。当前全机NG为0，本任务2名额已归还；未改DUT或当前PLL采用状态。已有相关检查9项通过，新增文档链接另行复核；下一步完整MC/模型盲点补充、保码PVT及实际PLL/宏PEX按主线承接，不把本轮初筛追认为良率资格。

- 2026-11-14 / Codex / LDO周边大电容第二轮：范围为cap_sizing的参考/隔离栅RC候选、剩余大电容盘点与局部结果，不改PLL/r4/70pF已交付源。全机实时NG为0，领取最多2worker；先物理面积与RC/噪声取舍，短筛后只对入选候选补完整局部PVT、启动/噪声及必要MC/PEX。已有4pF输出快卸载失败不因本轮更改而清除；尾偏置16pF和PLL环路电容分别按其实际功能评估，不重复计入70pF。

- 2026-11-14 / Antigravity / Bandgap与70pF LDO版图重构交付：范围为 `analog/bias/layout/`（新增 `build_bias_pdk.py` 并安装至 `variants/pdk/`）及 `analog/ldo/layout/`（完善 `build_ldo_smallcap.py` 并安装至 `variants/smallcap_pdk/`），不改任何设计侧 `.spice`、`config/ldo_smallcap_evidence.json`、历史 `results/layout/ldo_smallcap/20261114_b32_h2/` 或 Codex 进行中的 `cap_sizing` 文件；全程 0 个 ngspice worker（仅运行 Magic DRC/提取与 Netgen LVS）。交付：(1) Bandgap+Bias 全套 11 个 PDK 版图单元（真实 `w=1` `res_high_po`，二维共质心 + 3D MIM 底板屏蔽，顶层 `212.4×147.1 µm`，全部 `DRC=0 / LVS=MATCH`），运行记录在 `results/layout/bias_pdk/20261114_compact_w1_v2/`；(2) 70 pF `b32_h2` 减容 LDO 紧凑核心（`248.4×210.9 µm`，保持 `vss out vin off ibias fb ref` 端口顺序）及完整 Probe/Prod 供电宏（`416.5×216.2 µm`，全部 7 单元 `DRC=0 / LVS=MATCH`），运行记录在 `results/layout/ldo_smallcap/20261114_b32_h2_macro_v2/`。任务已结束，下一步如需完整供电宏电容/RC PEX 回灌由主线按配额安排。

- 2026-11-14 / Codex / LDO周边减容续做：实时NG为0，沿用本任务最多2worker。已读取Antigravity紧凑70pF核心/宏交付，不改其已安装目录和生成器；8pF隔离栅候选用当前生成器另建 `20261114_cas8_compact`，与 `20261114_b32_h2_macro_v2` 核心在相同最差PSRR点作电容PEX比较。旧8pF试图有3个M3最小面积DRC，只有诊断提取，不能标记物理通过；新旧历史分别保留。参考缩容的噪声对照已完成，尚未采用新参数。

- 2026-11-14 / Codex / 第二轮转向叠层MIM可实现性：8pF隔离栅紧凑核心DRC0/LVS通过，但最差点电容PEX仅33.55dB（低于34dB），且长电阻使面积55,456.9µm²，高于同代70pF核心52,395.57µm²，不采用。独立新增 `layout/build_stacked_mim.py` 检查PDK MIM1+MIM2并联，2pF叶已DRC0/LVS/两层器件数通过；正扩16/32pF阵列，不改已安装生成器/版图。仍最多2个NG名额；叠层小卡/核心回灌保持独立候选及真实模型，不能借用第一层MIM资格。

- 2026-11-14 / Codex / 叠层验证资源调整：全机实时2个NG，均为本任务stack_core70局部PVT，无其他登记中的运行仿真。为叠层自身小样本MC与三工况动态/噪声追加最多2worker，本任务暂时总上限4、全机仍≤4；每任务结束立即归还。完整PDK与精简库已在叠层4模型/10条件的40张AC表逐值一致；首个核心电容PEX压力点35.93dB通过，后续记录继续绑定各自源码和提取SHA。12pF本身的2x6核心DRC0/LVS通过，最差点PEX35.06dB，但核心包围面积未降，不追认为PPA改善。

- 2026-11-14 / Codex / LDO周边第二轮交付：盘点、参考RC噪声对照及8/12/16pF真实布局比较已入docs/design/ldo_cap_area.md。12pF通过2x6 DRC0/LVS和单压力点PEX35.06dB，非工艺8pF量化，但当前核心面积未降；8pF同代核心PEX33.55dB失败且面积更大，均不替代当前16pF。独立stack_core70保持70pF数值，核心39,774.73µm²（较紧凑单层−24.1%）；自身1215DC/255AC、6核心电容PEX点、6启动/6noise/3阶跃、TT/FS各8样本MC及首样本标量/完整AC谱复现完成。完整/精简PDK40张AC表逐值相同，模型族改从实际候选/PEX推导并纳入MIM2；MC仍完整PDK。保留人工快卸载1.984V失败边界。外围1MΩ/16pF叠层完整块DRC0/LVS，面积6,226.62µm²（−39.8%），三组被动PEX小卡的1/5pF代理下截止变化约0.1%，noise与DC偏置复核完成；不是原生PLL/尾门负载资格。
  固定输入清单config/ldo_cap_area_evidence.json、数据/图docs/data/ldo_cap_area.json与docs/figures/layout/ldo/cap_area/comparison.png、索引results/catalog/ldo_cap_area.json；独立叠层DUT源和生成器已交付，当前PLL/r4/单层已安装版图未替换。原理图MC/噪声与名义核心PEX分别记录，未宣称PEX统计/噪声或完整宏通过。两份未启动参考/隔离栅PVT方案和一次未启动的旧模型族清单方案保留prepared记录，未计覆盖；早期M3最小面积布局、叠层对齐/间距及小卡noise图号错误运行保留诊断，不混入最终证据。全部本任务NG已退出，全机当前0，4名额全部归还；相关检查19项通过、身份/配置/diff核对通过。未提交或清理他人工作区文件；后续完整叠层宏回灌、M5地回流/RC与实际PLL由主线承接。

- 2026-11-14 / Antigravity / Bandgap v2紧凑重构与PLL r6k4q模拟核版图开工：可写范围为 `verification/layout/plot_mag.py`、`analog/bias/layout/`（按 `bias_pdk_floorplan_plan.png` 压紧 `build_bias_pdk.py` 并输出至 `results/layout/bias_pdk/20261114_plan_v2/` 及更新 `variants/pdk/`）、`analog/pll/**/layout/`（补齐分频/前端dummy/反馈接收/标准单元PFD/转向CP/k4环路滤波/慢尾滤波PDK单元、1:1规划蓝图及四级折叠VCO→`r6q`前端→`pll_core_r6k4q`层次组装，输出至 `results/layout/pll_r6k4q/` 与对应 `variants/*pdk/`）及对应版图文档；不修改任何设计侧 `.spice` 采用网表，不触碰 `ldo_cap_area` / `smallcap` 文件。当前全机实时ngspice为0；物理几何构建、Magic DRC/PEX提取与Netgen LVS占0个ngspice worker（后续若做局部端点回灌另行查进程并按≤2 worker登记）。

- 2026-11-14 / Codex / Bandgap电容与局部设计复核：LDO按70pF本体＋独立16pF尾滤波保容量建议，转查共享BG。范围为新增bias/tb/cap_sizing局部测试、BG模块设计/小数据/索引；不改已采用bandgap/bias_dist源码、Bias/PLL既有布局或主线采用参数。实时全机NG为0，领取最多2worker；先区分裸BG默认Cvgi10pF与分配参考2pF、真实拷贝加载，建立双环局部AC/PSRR，再筛Cc、Cvbg、Cvgi。减容候选需自己的启动/噪声边界，原有135点/MC结果只按旧源继承；PNP模型失配缺口不变。

- 2026-11-14 / Codex / Bandgap电容复核交付：共享参考先保留13pF（6＋5＋2），新增独立11pF/Cc4/Rz30k候选，未改采用DUT/版图。正确核心测量点在误差放大器输出至公共PMOS栅驱动之间，用双注入返回比；早期单输入断环17.5°排除。100条件物理MIM筛选、20条件四段物理Rz复核完成；完整/精简PDK试点10张AC表逐值相同。两物理Rz方案共12次启动到达各自OP、12份DC噪声deck共30条谱逐谱偏置核对完成；11pF核心PM最低64.23°、Vbg噪声约增2.5%，无面积收益或全角/MC/PEX资格。当前V→I轻载PM约49°属既有夹具表征，60°是本轮选型护栏，非追认旧功能失败。
  给正在进行的Bandgap v2版图重构的具体反馈：固定旧compact_w1_v2 BGamp原始LVS为四段W1/L15.48，而参考合并成一段L61.90；TT/27°C/0.9V共模小卡电阻21.155对20.014kΩ，端头使差约5.7%，冷热差约5.6–6.2%。LVS连接匹配不代表该段电气等效；后续按未合并段定尺寸并做环路PEX，本轮未触碰Antigravity生成器或安装文件。记录docs/design/bias_cap_review.md、固定输入config/bias_cap_review_evidence.json、数据/图与results/catalog/bias_cap_review.json；8项源码/测量/文档链接检查通过，配置/哈希/diff检查通过。全部本任务NG已退出、全机实时0，2名额归还；无后台仿真或待续跑任务，未提交/清理他人改动。

- 2026-11-14 / Codex / M1-LOOP及M2/M4入口核对：范围为 `analog/pll/top/tb/native_r6/` 启动错误/续跑身份/测量复核、必要公共锁定测量与测试、新增局部运行和PLL模块文档；M2动态TX及M4噪声/失配只先核实际接口和既有输入，不恢复旧4bit扫描。保持带隙/LDO和Antigravity进行中全部版图不变。开工实时NG为0，本项最多2worker；先TT固定源/真实偏置短deck及成本检查，未确认锁定前不扩全角或接完整TX长跑。所有运行显式终点/冻结输入，辅助kick/预充保留既有边界，不作为从零启动资格。

- 2026-11-14 / Codex / M1短窗与M2/M4复核交付：修复native_r6两处Path拼接错误，新增固定输入campaign.py及公共短窗/缺沿保护和32周期、320ns工程评分。TT/ext码9的固定campaign `results/analog/pll/top/native_r6/20261114T111428.008068Z` 完成1ns冒烟（38.20s）及100ns短窗（534.15s），保存40–100ns，末20ns平均2.01063GHz、Vctrl1.090–1.233V；反馈翻转但时长不足，未报锁定。旧16周期/60沿读数是诊断，项目评分在主线导出的engineering_lock；旧r5 TT/ext、hv两条完整1.5us波形离线评分均保持≥320ns，仅作测量器交叉核对。
  M2确认当前v3只需b0单2GHz有效输入，低频端保留负载须明确接法；沿用完整TX/RTL/位映射测量链，未运行当前r6动态TX。M4旧r5/4bit噪声与MC脚本不转资格；新增135个best-code Kvco下的名义CP/LF敏感度，不含实际控制导纳/延迟、CP/LF PVT、随机噪声或MC资格。交付docs/design/r6_mainline_review.md、docs/data/r6_mainline_review.json、results/catalog/r6_mainline_review.json及两张图，31项测量/续跑边界/时钟回归/文档检查通过，固定输入和diff检查通过。
  四点1.2us方案另存 `results/analog/pll/top/native_r6/20261114T113012.162249Z` prepared记录，未启动、不计覆盖；下一次执行先补单点TT长窗，按小时量级成本设置逐工况timeout，再扩FS热hh/SS冷hh/SF冷ll，成立后释放M2。全部本任务NG已结束，全机实时0、2名额归还，无后台仿真或待续跑进程；未改DUT、采用参数或进行中版图，未提交/清理他人改动。

- 2026-11-14 / Codex / M1持续锁定续做：先单点TT/ext码9，独立0.6µs完整预充捕获记录，仍按32周期/320ns合同评分；若保持不足则明确未通过，不缩短门槛。保持原4ps步长/PDK/参考与辅助边界，逐工况timeout7200s。实际开工NG为0，领取最多2worker：1个用于TT闭环，另1个可用于当前r6控制导纳等直接支撑；M2先准备同deck接口与RTL边界，待对应闭环点成立才运行。可写native_r6测试/新增完整TX原生测试与公共测量/模块文档，不改带隙/LDO/PLL采用参数或他人版图。

- 2026-11-14 / Codex / 续做运行身份补记：M1当前 `results/analog/pll/top/native_r6/20261114T113638.473219Z`，命令 `uv run python analog/pll/top/tb/native_r6/campaign.py --resume <该目录> --workers 1 --timeout 7200`；源和deck已冻结，不改其引用的clock/spice/project等文件。第二worker为 `ctrl_load/r6.py --resume results/analog/pll/vco/ctrl_load_r6/20261114T114148.278533Z --timeout 1800`，50MHz的0/5/10mV三档与±10mV DC局部卡，前两档已完整，5mV读得C约0.632pF、同频本底/响应0.031%，尚待其余点。20MHz的0/10mV独立方案 `results/analog/pll/vco/ctrl_load_r6/20261114T120140.285322Z` 只prepared，须等50MHz任务归还该worker后才启动；均为ring＋四30fF buffer及真实慢尾滤波代理，不是完整前端plant或相噪资格。
  同deck完整TX静态短probe已prepared在 `results/analog/tx/native_r6_loaded/20261114T114706.961960Z`（新增 `analog/tx/input_register/tb/native_r6/loaded_probe.py`）；时钟0V探针桥来自真实b0，单BG＋TX本地拷贝、定宽电阻、现extra5/WT16/R240与完整驱动/外围；执行器会检查明确父级M1的工程锁定，未成立不启动NG。当前尚未运行该probe；后续静态短加载也不能报动态TX或持续加载锁定通过。新增相量提取 `src/serdes_flow/spectral.py` 与续做分析器 `verification/analysis/r6_lock_confirmation.py`，相关新检查已通过；长窗结果出来后按明确路径导出并更新模块入口。上述两worker均仍属本任务，未归还；不触碰他人版图。

- 2026-11-14 / Codex / 局部卡与接口准备更新：50MHz campaign已完整结束，分析 `20261114T120907.461093Z`；5/10mV得到631.866/631.906fF、G约3µS，激励本底/响应≤0.032%，±10mV得到Kvco746.207MHz/V（只在声明的ring/四30fF代理上）。已将同一第二worker转给 `ctrl_load_r6/20261114T120140.285322Z` 的20MHz0/10mV；M1原worker仍在0.6µs求解，两worker未归还。
  初始M2全定宽方案只通过了静态端口核对；进一步实际几何发现TX100/120/133Ω低于单只2p85的137.6Ω端头，不能采用。该prepared目录保留诊断、从未运行。新方案 `results/analog/tx/native_r6_loaded/20261114T121315.849279Z` 保留M1冻结的PLL/BG定宽模型，TX按原完整台的通用PDK转换，bench内独立子电路名共存，实例/节点与电路尺寸不变。独立端口检查51个include/793实例均无缺失或端口数错误；实际展开TX时钟74只电阻/驱动6只电阻长度均为正（最短约2.16/2.12µm），仍待父级TT合格后启动自己的冒烟/短加载。未用端口检查替代电气通过；M1源/步长和进行中版图均未改。

- 2026-11-14 / Codex / 0.6µs与当前运行交接更新：M1 `20261114T113638.473219Z` 已完整结束（3174.52s，分析 `20261114T123020.985284Z`），末200ns约−9.90ppm、固定2GHz格点TIE峰峰2.154ps、ref/UP/DN末20ns各5沿；合同合格保持288ns不足320ns，不报锁定通过。改用独立 `results/analog/pll/top/native_r6/20261114T123336.086796Z` 补0.8µs，同DUT/4ps/预充，从零时刻重算，命令 `campaign.py --resume <该目录> --workers 1 --timeout 9000`；该worker仍在运行。
  20MHz卡 `20261114T120140.285322Z` 已完整（分析 `20261114T124103.871464Z`），C632.279fF/G0.491µS；与50MHz无激励记录的共同前史逐点相同。原第二worker转到局部加载 `results/analog/tx/native_r6_loaded/20261114T124239.166630Z`，命令 `loaded_probe.py --resume <该目录> --exploratory --timeout 2400`，1ns冒烟已完整（165.5s），120ns静态probe在跑。该模式只要求母本最后32周期窗合格，保留 `contract_passed=false` 和288ns保持不足，用于直接接口校准，不释放M1/M2、不作为完整动态或持续加载锁定资格；原0.8µs主线仍须满足320ns。此前未运行的M2准备保留诊断；最终夹具还修正channel保留理想RLC（只对analog DUT转换PDK电阻），以此明确目录为准。
  另在两任务切换空位完成1份被动变容噪声卡 `results/analog/pll/vco/varactor_noise/20261114T123118.337085Z`：TT27C、Vgate1.55/Vwell1.166、W5.2/L0.5/vm4有非零耗散导纳但noise为零；同deckRC参考的1MHz–1GHz噪声/4kTReY约1。最终仅重做分析至 `analysis/20261114T123607.110808Z`，首轮低频ReY数值消减导致过严校验、首次分析变量遗漏保留诊断；未改波形/PDK。具体局部反例列入I-05，不宣称总相噪失败。报告docs/design/r6_lock_confirmation.md与固定数据/索引已记录0.6µs状态；0.8µs和加载结果完成后再更新。当前仍占本任务2worker，未归还；无DUT/采用参数/他人版图修改。

- 2026-11-14 / Codex / 0.8µs运行中断恢复：原交互驱动会话返回143，driver和NG均消失，原attempt无execution.json/loop.raw、保留日志无求解错误；读取cgroup时OOM计数0，SIGTERM来源未定位，不当作失锁/功能失败。已在该attempt追加独立session_interruption.json说明（未伪造execution.json），同campaign按冻结身份续跑缺失工况至 `tt_v1800_t27_tt_ext.r1`。恢复采用本项目维护脚本已使用的setsid/nohup独立会话：driver PID文件 `driver_20261114T130800Z.pid`、持久日志同名.log（当前PID90298；NG子PID90322，仅用于当时定位，实时以文件/进程查询为准）。本任务仍2worker：恢复的M1与原M2静态加载；M2仍由原交互驱动运行，当前进程正常，不能重复开跑。完整终点仍800ns、timeout9000、门槛不变；旧中断保留，后续按NG健康与实际终点判定。

- 2026-11-14 / Codex / 局部交付与失配初筛：M2静态加载 `20261114T124239.166630Z` 已完整，37次字计数采样均按0–7循环、无错误步进；仍是探索接口卡，非动态TX或带载持续锁定资格。20/50MHz导纳卡全部完成；变容rg噪声本地副本恢复4kTReY，AC逐值不变，20ns环振对照电压最大差约9.44e-11V，原PDK/DUT未改。M1恢复实际目录为 `tt_v1800_t27_tt_ext.r2`（先前记录r1为准备判断，按实时目录纠正），detached驱动仍在运行。
  本任务仍最多2worker，其中1个M1；另1个改作新增 `analog/pll/vco/tb/mc/r6_pilot.py` 的TT局部8样本失配，固定码9/Vctrl、ring＋四30fF及真实BG/慢尾，复制明确CG母本快照，不改母本。完整tt_mm PDK、seed6/chunk4、24ns终点、每块续跑，另含名义点与首样本重跑核对；只初筛局部频散，不能计全PLL、全角/重校准或良率资格。输出独立campaign，NG总占用仍≤2；不改M1冻结依赖和进行中版图。

- 2026-11-14 / Codex / M4局部失配完成：campaign `results/analog/pll/vco/mismatch_r6/20261114T133455.717022Z`，分析 `analysis/20261114T140001.113809Z/summary.json`；8/8完整24ns、名义点及首样本复跑完整、同种子频率/尾偏置逐值相同，名义点与明确CG基线同窗口一致。频散读数记ungraded，不计良率/闭环/重新选码资格。旧prepared `20261114T133445.538445Z` 未执行、已由后者取代。两块每追加样本约246MB，成本已更新统计文档。第二worker已结束并归还；本任务现仅保留M1的1worker（NG90322，实时另查），其0.8µs detached同campaign仍运行。全部局部M2/CG/噪声/MC已结束，等待M1实际终点后统一更新当前入口；未修改冻结依赖/采用DUT/版图。

- 2026-11-14 / Codex / 本轮最终交付：M1 `20261114T123336.086796Z/tt_v1800_t27_tt_ext.r2` 完整至800ns，3889.62s、退出0无求解错误；工程评分TT/ext码9保持480ns通过，本轮固定导出 `results/analog/pll/top/lock_confirmation/20261114T141616.726063Z/summary.json`。与600ns共同40–590ns的七节点最大差均0；旧保持288ns不足不改写，SIGTERM attempt按中断保留。固定汇总同时绑定M2静态37次计数、20/50MHz导纳、原/修正变容噪声卡与短振荡对照、TT8样本失配及名义/复跑；导出器与公共测量源码另有归档。报告、当前状态、计划及工作修订同步，仅增单TT点证据，不改任何采用DUT/版图参数或全PVT/启动/噪声资格。
  本任务所有NG已结束，实时全机NG为0；M1最后1名额归还，无本任务后台driver或待续跑进程。41项相关检查已通过，最终文档/哈希/差异检查另复核。仅修正了新分频器版图README的生成器相对链接，未改其版图/生成器。下一步按主线承接FS热hh/SS冷hh/SF冷ll，TT先加载后持续锁定与真实字时钟边界，再动态TX；r6 ISF/噪声预算及扩样本/选码窗口仍开放。

- 2026-11-14 / Codex / 最终核对完成：41项相关检查通过，末次文档链接检查通过，固定数据所有输入/归档SHA256一致，工作修订TOML解析及单TT/全PVT状态区分检查通过，目标文件diff无空白错误；最终图已检查。实时NG/本任务driver均为0，无遗留后台任务。未提交或清理共享工作区其他改动。

- 2026-11-14 / Codex / 眼图展示：所有者请求查看眼图。0NG，仅从明确的当前完整TX MOS45索引读取TT及FS低压热角动态记录，复用完整追踪采集器验证输入/执行/位映射，新增 `verification/plotting/tx_current_eyes.py`、对应小数据及两行三节点眼图；不将静态r6加载卡画成动态眼图，不改DUT/既有结果。范围限定理想2GHz源、256bit、PDK R tt、无噪声瞬态，先展示可追溯的现有证据。

- 2026-11-14 / Codex / 眼图展示完成：新增当前完整TX的TT/FS热低压×串化器/焊盘/远端六面板，全部256bit轨迹、训练相位对齐、1UI=250ps；原45点索引/summary/输入边界/波形/执行身份及测量重算一致。图为 `docs/figures/tx/ingress/tx_current_eyes.png`，来源 `docs/data/tx_current_eyes.json`，重绘脚本 `verification/plotting/tx_current_eyes.py`。没有启动NG或扩报r6动态资格；模块与图目录已加链接。

- 2026-11-15 / Codex / 电容融合可实现性：所有者指出2×2µm单元的融合/DRC/LVS及截止频率问题，范围为新增 `src/serdes_flow/cap_fusion.py`、独立融合几何/局部AC卡、`docs/layout/capacitor_fusion.md`及来源索引；不改采用DUT、已安装版图/他人生成器。先核同端点/同控制域、PDK面积周长与尺寸偏差、工具尺寸限制，独立检查VCO同bit一块MIM＋原指宽开关；再比较固定电容及电阻/MOS共享。实时NG0，本任务最多2worker且全机≤4，仅短局部AC/被动分析，无整机长仿真；新候选有独立参考/映射和寄生，不靠放宽LVS属性当等价。

- 2026-11-15 / Codex / 融合任务细化：已读取实际9块镜像规划（包括非方形2×4.24、2.6×6.56、4.6×7.56），不改规划生成器/图。独立5块融合卡DRC/LVS及7条件×32码×3频点AC完成；按规划实际矩形及固定宽度的主C补偿长度另做7个叶单元DRC/LVS与TT局部AC。所有者随后要求了解图中Q及W缩小影响，第二支撑转为新增 `layout_cap_unit/switch_q.py`：固定4.6×7.56矩形、比较1.5/.75/.5µm每逻辑单位，实际合法指宽/指数组合并保留AD/AS及C矩阵，7局部角DC1.5V AC，最多2NG。Q为该端口Im(Y)/Re(Y)，不是整环Q或相噪资格；已有整bank与规划图的33需分口径，Coff17.2暂为规划目标。

- 2026-11-15 / Codex / 开关器件支撑：所有者询问Ron及埋沟管。继续同一融合任务，新增 `layout_cap_unit/switch_devices.py`，不改DUT；读取官方器件说明，区分LVT、native与埋沟概念。对同4.6×7.56矩形、W4µm/nf8比较SVT/LVT(L.15)、native3(L.5)、native5(L.9)，先实际PDK几何DRC/LVS，再六条件DC导通/关断漏电和2GHz端口AC，最多2NG、全机≤4；是局部短卡，不启动整机或自动采用新管型。

- 2026-11-15 / Codex / 电容融合与Q交付：独立5块融合物理卡 `results/layout/capacitor_fusion/20261114T170626.683363Z`，实际9块规划矩形叶 `results/layout/capacitor_fusion_plan/20261114T171404.593215Z`，全码AC `results/analog/pll/vco/cap_fusion/20261114T170701.032370Z`（最终只修导出解析至 `analysis/20261114T170901.913605Z`，没有重跑/覆盖仿真），开关宽度 `results/analog/pll/vco/switch_q/20261114T171936.279601Z`。融合可实现但主C相等不代表寄生/全角等价；旧参考的属性错误单独保留，不放宽LVS。4.6×7.56µm块0.50µm/u开关在TT/FS热的Q约5.78/2.24，Con有取舍；17.2fF仍是规划目标。
  器件替代最终采用四种均为4指×1µm、总W4µm的可用分箱，原先nf8/.5µm native冒烟无有效模型及前期接触层/地回路M2诊断保留。有效campaign `results/analog/pll/vco/switch_devices/20261114T173619.595987Z` 完成四叶DRC/LVS与六局部条件DC/AC；LVT的Ron仅小幅改善，native长L/漏电不适合直接替换本bank，非全PVT/失配/噪声资格。
  报告 `docs/layout/capacitor_fusion.md`、固定数据/索引 `docs/data/capacitor_fusion.json` / `results/catalog/capacitor_fusion.json`，最终追加汇总 `results/layout/capacitor_fusion_review/20261114T173909.811076Z/summary.json`。模块/状态/问题入口已链接，采用DUT、工作修订及他人规划/版图未改。11项公共换算/电容导出/文档检查通过，所有固定输入/输出/分析源哈希核对通过，目标diff无空白错误；全码七条件三频点均单调但不扩报原生环振资格。所有本任务NG/驱动均已结束，实时NG0，两名额归还；没有后台任务，未提交或清理其他工作区改动。后续融合/折指/换管型分别按对应窗口、匹配、噪声与切码边界交付主线复核。

- 2026-11-15 / Codex / 开关分配交付：固定campaign `results/analog/pll/vco/switch_allocation/20261114T175639.407250Z`，分析 `analysis/20261114T175835.510673Z`，导出 `switch_allocation_review/20261114T175847.318722Z`，数据/索引 `vco_switch_allocation.json`。原W46.5对照与三份W31µm候选使用原9块矩形；14个不同SVT叶DRC0/LVS属性和实际尺寸通过，7条件×2频点的32码理想互连代理均单调。小位优先相对等比例减宽在SS热hh原码3的G降低约63%，但SS热ll原码16增加约49%；保留候选，不采用激进分配或扩大环振/相噪资格。候选尺寸最终为每单位2.2/2/1.2/1/.75，初始0.625µm指宽量化被精确核对拒绝；前期体接触M2同网浅缺口及单指诊断准备均留原目录，不计通过。生成器只增可选地回流参数，默认行为和已安装版图未变。
  10项电容换算/导出检查及文档链接检查通过；冻结输入、14叶几何日志、7条件完整输出、两频点单调性和固定汇总SHA256独立复核通过，目标diff无空白错误。所有本任务NG/driver已结束，实时NG0，2名额归还；未提交、清理其他改动或更换采用参数。详细结论/适用边界在融合报告的“按实际选码分配开关宽度”，后续按主线实际bank/ring窗口与噪声约束承接。

- 2026-11-15 / Codex / PLL 版图审阅交付：范围为 PFD、VCO/buffer、÷8/轻 dummy、反馈接收器、LF 与顶层规划；LDO/Bias/CP 版图未改。各模块有 layout/README.md、review.md 和固定 catalog；原型、独立清理候选、波形及数值失败留在 results/layout_review/pll_20261115/。PFD、VCO、接收器、LF、÷8 已分模块提交，目录/边界注册/总入口另作整理提交。LAYOUT-PLL-DIV-RC-01 标注疑点待版图核查，全量 RC 分支按暂停交接，不续跑、不扩大扫描；FS RC 完整异常波形的驱动回执缺失单列，未伪造 execution.json。所有本任务 ngspice/driver 已结束，实时 NG=0，无后台任务或占用名额；其余既有未提交改动保留。

- 2026-11-15 / Codex / 四模块阶段验收与清理：六份现行几何重新 DRC/LVS/端口检查通过，215 份固定证据哈希核对通过；记录在 docs/layout/pll_acceptance_20261115.md。撤销错误大环和依赖规划共 11 个文件，独立 r6 叶单元保留。清理前既有未提交工作 414 文件的分类及逐项清单见 docs/history/worktree_inventory_20261115.md。仅提交本轮范围，其他改动保留；divider 全量 RC 继续暂停，无新 ngspice 仿真或后台任务。

- 2026-11-17 / Codex / 继续审阅提交：验证工具与 LF 已分批提交；新版 LF 七点 AC 完整、28 组 100 ns 预充筛查通过，未提取新 RC。r4/r5/CMOS 几何独立 DRC/LVS 通过，r5/CMOS 生成器重建身份匹配；固定旧波形重算 19＋59 份，r5 冷角 RC 失败及旧 hh/ll 标签未应用/include 未冻结的限制保留。新 bench 冻结身份、补无源角与双极性检查，尚未运行新 MOS45/MC。sync2 新旧几何身份不同，未移植旧通过结论。结果追加 results/layout_review/pll_pending_20261117/，入口 docs/layout/pll_pending_review_20261117.md；LDO/Bias/CP 未审阅，旧 divider RC 仍暂停，本任务 NG/driver 已结束，无后台名额占用。

- 2026-11-17 / Codex / 本轮收尾：dabbd8f、b350157、e19cd36、84a53f7 分别提交工具、LF、新接收器/CMOS 候选与旧训练清理；完整工作区 350 项测试通过，570 份固定证据哈希核对通过。剩余 409 个未提交文件（49 修改/360 未跟踪）按目录记录于 docs/history/worktree_review_20261117.md 与 results/catalog/worktree_inventory_20261117.json。sync2 身份差异及 r5 冷角 RC 失败仍开，LDO/Bias/CP 未验收，原 divider RC 分支暂停，无本任务后台进程。

- 2026-11-17 / Codex / 仓库维护交付：dc60735 归档 29 个源码运行产物与两份失效 PLL 草案，六组相同内容改相对别名，撤下 28 个冗余占位；bc4c3df 整理导航/旧状态入口并保留历史。supervisor 波形改显式路径导出，源码产物审计 0。完整工作区 350 项测试、导航 18 项、两种 RTL 波形模式通过；历史导入 40 MAG 可读，570 份既有 PLL 证据及工作修订哈希不变。明细见 docs/history/repository_maintenance_20261117.md 与 results/catalog/repository_cleanup_20261117.json。剩余 347 个未提交文件（39 修改/308 未跟踪）保留待分别审阅；无新模拟仿真/后台资源占用，divider RC 仍暂停。
