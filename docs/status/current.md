# 当前状态（唯一入口）

**这一页是项目级采用状态与验证数字的唯一汇总。** README、模块地图、计划和工作台均引用本页；模块设计文档保留详细分析、参数推导与原始边界，工作修订保留机器参数和历史身份。规则见 [架构决定](architecture_decisions.md) 与 [文档职责](../README.md)。

截至 **2026-11-24**，`v1.0` 发布基线覆盖 4 Gb/s NRZ SerDes 的独立宏、模块验证和片级规划。采用项见[主线工作修订](../../config/mainline_working_revision.toml)，固定记录见[发布证据](../../results/catalog/v1_0_subsystem_evidence.json)和[片级集成证据](../../results/catalog/chip_integration_20261124.json)。
- **PLL v4**：VCO `r6` + BIAS v2 PTAT (`28/66`, `sym9_clean` CPEX) + CP v4 + 融合 LF v2 + `pll_pfd_sc_dly`。片级反馈目标采用 `r5` CML→CMOS 接收器与 SAFF-TSPC 重定时 ÷8。
- **供电与偏置**：HV18 LDO `v2_cur` + 慢尾偏置滤波 `bias_filter_r4` + `BIAS v2`
- **TX**：CMOS/SST SST `v4.3`（16:4 CMOS 串化 + 4 相 N-over-N 28-slice SST 含 2-tap FFE）
- **RX**：CMOS/SST CMOS RX `v2.2`（100 Ω 端接 + CTLE + 2 GHz 64 码纯 CMOS PI + 四分之一速 Double-Tail 采样 + 8→32 解串）
- **数字顶层**：统一精简宏 `serdes_digital_top_v3`（v3.1，多速率 `250 / 125 / 62.5 MHz`）
- **片级版图规划**：已完成真实宏摆位与阻尼去耦预留，按规划外框做几何核对。

历史 CML 基准标签 `baseline-prelayout-20261113` 及历史 `v0.1-design-freeze-20261028` 原样保留可追溯。

---

## 1. 一句话状态

**发布基线已完成独立宏验证。** 片级已做核心布线及模拟链路短窗联调。采用反馈链的带载判锁、生产数字 CDR/FIFO 回接和全片物理签核仍在[集成队列](prelayout_plan.md)。

---

## 2. 当前 4 Gb/s 主线模块状态

“驱动 / 边界”一栏注明该条证据实际采用的激励与寄生边界；局部通过不自动替代顶层芯片级联合后仿。

| 模块 | 当前修订 / 版图目录 | 驱动 / 边界 | 验证结果 | 待集成 / 未覆盖边界 |
|---|---|---|---|---|
| **[PLL v4 闭环顶层](../design/pll_vco_r6_perf.md)** | `pll_top_r6_v4_upgrade`（[闭环台](../../analog/pll/top/tb/lock_v4/verify_pll_v4_closed_loop.py)） | 原理图闭环，固定粗码、预充后捕获。冻结顶层用 `clock_frontend_r6q` 的 CML ÷8 和 `cml_to_cmos_pvt_candidate`，CP 为 v4。六点用真实 HV18 `v2_cur`，SF 热点直供 1.65 V | **7/7 角通过 320 ns 锁定合同**（保持 `416–640 ns`，频偏 `−4.75..+2.25 ppm`，TT 静态相差 `+12.2 ps`，250 MHz 杂散估计 `−40..−59 dBc`，`TIE_pp 0.74–4.11 ps`，TT `35.8 mW`） | 接入 `r5` + SAFF-TSPC 与 CP v4.1 后复核原生闭环，继而验证带载、顶层 RCX 与从零自动粗搜 |
| **[VCO r6 + PTAT](../design/pll_vco_r6_ptat.md)** | `r6` + PTAT `28/66`（[sym9_clean](../../analog/pll/vco/layout/variants/sym9_clean/README.md) · [ptat_bias_pdk](../../analog/pll/vco/layout/variants/ptat_bias_pdk/README.md)） | `sym9_clean` CPEX 5 角 + 135 条件原理图表征。相噪由 ISF 合成，PLL/CDR 抖动由环路模型估算 | 45/45 跨三温单码覆盖，`sym9_clean` CPEX 八相误差 `≤ 0.76 ps`。TT `L(1M/10M) = −88.5/−109.2 dBc/Hz`，10 kHz–100 MHz 模型 RMS 抖动 `1.91 ps` TT / `2.29 ps` 最差，CDR `14.07σ = 0.272–0.296 UI` | VCO、PTAT、分频器与真实互连带载后的 RCX 和系统预算 |
| **[CP v4 / v4.1 & 融合 LF v2](../design/pll_cp_v4.md)** | `pll_cp_steer_v4`（[v4_pdk](../../analog/pll/cp/layout/variants/v4_pdk/README.md)）· `lf_k4_fused`（[fused_pdk](../../analog/pll/loop_filter/layout/variants/fused_pdk/README.md)） | CP v4 独立 135 角 DC、AC/瞬态和压力点 CPEX。v4.1 局部原理图对照与物理复核分开记录 | v4.1 微修已在本机 CP 几何与参考配对通过独立物理复核，见[证据索引](../../results/catalog/v1_0_subsystem_evidence.json)。LF `6,382 µm²`（`ctrl` CPEX −41.4%） | v4.1 交接发布及联合环路回归 |
| **[SAFF-TSPC ÷8 & r5 接收器](../design/pll_tspc_reclock_divider.md)** | `tspc_reclock_prescaler8_2g`（[saff_reclock_2g_pdk](../../analog/pll/divider/layout/variants/saff_reclock_2g_pdk/README.md)）· `r5` v6（[r5_pdk](../../analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md)） | 45 角 CPEX / RCX + 200 样本失配 MC | ÷8 面积 `1,705 µm²`，DRC=0/LVS=MATCH，CPEX 功能 45/45、44/45 偏斜 `< 30 ps`，`RCX_BOTH` 5/5；`r5` v6 CPEX 45/45、原生 RCX 6 压力点通过、TT/SS 冷 200/200 MC 通过 | SAFF-TSPC `SS 1.65 V −40 °C` 失配下 `Xtg2` 路径偏斜边界（168/200 正常分频） |
| **[HV18 LDO v2_cur](../design/ldo_v2.md)** | `serdes_pll_supply_hv18_v2_cur`（[v2_cur_pdk](../../analog/ldo/layout/variants/v2_cur_pdk/README.md) · [bias_filter_r4_pdk](../../analog/ldo/layout/variants/bias_filter_r4_pdk/README.md)） | 电流参考供电宏独立 DRC/LVS、CPEX/RCX 提取及 PLL 预充后闭环。前代电压参考 `v2` 的独立 DC/AC/瞬态结果单独留存 | 生产宏 `37,958.68 µm²`、DRC=0/LVS=MATCH。六个带 LDO 闭环条件的安静域 `1.781–1.797 V` | 电流参考版独立电气扩角，实际芯片上电、负载与封装引线电感耦合 |
| **[BIAS v2](../design/bias_v2.md)** | `bias_top_v2`（[v2_pdk](../../analog/bias/layout/variants/v2_pdk/README.md)） | 135 角 PVT + 200 样本 MC + 启动 + RCX | 单级 FC-OTA + 真 CMOS `ref_pbuf` + 集成 `bias_top` 全套 DRC=0/LVS=MATCH；向 PLL/TX/RX 提供稳定 `Vbg`/`Vcm`/`Ibias`/PTAT | 芯片级跨宏长距离偏置分配寄生 |
| **[TX SST v4.3](../design/tx_sst_v4.md)** | `serdes_tx_sst_top`（[v4_pdk](../../analog/tx/sst/layout/variants/v4_pdk/README.md)） | 理想 1 GHz 四相。22 项后仿记录含驱动器 ZQ/S11 的 6 CPEX + 6 RCX，以及完整 TX 的 6 RLC16 CPEX、2 C2 CPEX、2 RLC16 RCX | 原理图 MOS45 通过，原后仿完整 TX 十项均满足焊盘及各台远端门槛。子稳压器 v4.3.1 泄放微修及上层几何已在本机通过独立物理复核。现有四份提取输入与原 `identity.json` 的哈希均不同 | 冻结当前提取输入并补受影响电气回归；锁定 PLL 动态联调及 Pad/ESD/封装 |
| **[RX CMOS v2.2](../design/rx_cmos_v2.md)** | `serdes_rx_cmos_top`（[v2_pdk](../../analog/rx/cmos_rx/layout/variants/v2_pdk/README.md)） | 六个压力点原理图同 deck；MOS45 原理图与 3 点 CPEX 回放逐角 TX SST `FFE=3`、`C2_loss6` 波形。均使用理想 PI 锚点 | 面积 `245.30 × 195.40 = 47,932 µm²`，8/8 单元 DRC=0/LVS=MATCH。**45/45 原理图回放 + 3/3 CPEX 回放通过**（`TT / SS −40°C / FF −40°C`，每点 `0/64` 数据错、`0/27..30` 边沿错，TT `36.11 mW`）。PI TT 64 码 CPEX 单调，`\|INL\| = 0.0177 UI` | 45 角全量 CPEX；实际锁相 PLL 锚点及失配下门限校准 |
| **[数字顶层 v3.1](../design/digital_top_v3.md)** | `serdes_digital_top_v3`（[summary.json](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/summary.json)） | 3 角 OpenRCX SPEF STA。VCS 回归含 1 个 RTL 参考与 3 个 SDF GLS 工况 | 面积 `338.10 × 307.40 = 103,932 µm²`，4,932 单元，DRT=0/ANT=0/DRC=0/LVS=MATCH。6 时钟域全 MET（SS `+0.074 ns`、FF `+0.125 ns`）。四模式通过，每模式 122,608 项 SVA 通过，0 同步违例，`±300 ppm` CDR 通过 | 顶层模拟-数字跨宏接口寄生与片级 IR drop |
| **[信道 C0–C5](../design/channel_model.md)** | 合成 100 Ω 差分 PCB 族（[配置](../../config/channel_family.toml)） | SST/RX 主线验证采用 `C2_loss6` 的 SPICE 等效；TX 近无损筛查用 RLC16 | C2 是设计与回归基线；C3–C5 是挑战和诊断条件 | 实际 PCB / 封装 S 参数、串扰与链路验收边界 |
| **[片级规划与阻尼 PDN](../layout/chip_floorplan_20261123.md)** | `chip_floorplan_20261123`（[plan_chip_floorplan.py](../../verification/layout/plan_chip_floorplan.py)） | 21 个 `.mag`/`.def` 功能宏实测外框与 12 个去耦预留矩形。去耦按分域模型估算 | 核心 **`845.4 × 601.4 µm = 0.5084 mm²`**，功能宏 `302,393 µm²`（59.5%），含去耦区域总填充 `81.0%`、外框零重叠。估算新增 `761.0 pF`、片上合计 `957.9 pF` | 去耦器件几何、顶层电源环/焊盘环、分域阻尼和布线提取 |

![PLL v4 闭环锁定与波形签核](../figures/clocking/pll_v4_closed_loop_20261123.png)

---

## 3. 历史 CML 路线状态留存（Reference Baseline）

早期全 CML 架构（PLL `r6k4q`、TX `v3/extra5` 45/45 理想源、RX `ac_trim/c2/W40`、HV18 LDO `r4`、Bias `B2`）的完整源码、测试台、证据卡及 2026-11-15 阶段版图审阅均按原始身份保留，便于对比功耗、面积与架构演进：

- **历史 CML TX**：[tx_final_retime.md](../design/tx_final_retime.md)（理想 2 GHz 源 45/45，最差 FS 1.65 V 85 °C 焊盘 136.0 mV / 0.138 UI）与 [tx_clock_distribution.md](../design/tx_clock_distribution.md)
- **历史 CML RX**：[rx_pi_sampler.md](../design/rx_pi_sampler.md)（C2 信道 135 条件无读出窗口最差 0.8125 UI）
- **历史 CML ÷8 与阶段审阅**：[pll_divider.md](../design/pll_divider.md)、[pll_acceptance_20261115.md](../layout/pll_acceptance_20261115.md)、[pll_review_20261115.md](../layout/pll_review_20261115.md)（原三叠层 CML ÷8 的全量原生 RC 分支 `LAYOUT-PLL-DIV-RC-01` 仍标记暂停，主线已切换至 SAFF-TSPC CMOS ÷8）

---

## 4. 发布后的片级集成证据

| 验证对象 | 已复核结果 | 适用边界与待收口 |
|---|---|---|
| `full_v8` 核心装配 | Magic 全规则 **DRC=0**，111 条登记信号网通过。层次提取查 42 组应连接端和 45 组应独立端均通过。数字宏仍为 v3.2 | 追加的层级审计确认 **四路 CML→CMOS 的偏置与 `VSS` 短接**。该组端点未纳入原门控，修正在 5G 构造验证。片顶外部为 4 个高速端和 8 个电源及地端。完整 pad/ESD、全网表 LVS 和最终供电验收依 I-TOP-01。[原装配证据](../../results/catalog/digital_v3p3_audit_20261125.json) · [追加门控和 5G 候选](../layout/chip_floorplan_20261123.md#5g-iq-时钟组宏) |
| `full_v5` 核心装配 | Magic 全规则 **DRC=0**。**101 条受查信号无开短路、8 个电源网根互异、12/12 组去耦接通**。合并 GDS 根层导出 4 个高速端和 8 个电源端 | 参考时钟、复位及部分供电/控制仍需顶层连接。片上电源已加宽及增加过孔，原 IR/EM 结果来自几何代理，实装 `VDD_Q` 主干与模型不同。Padring/ESD、全片 LVS/RCX、实际 IR/EM 及测试入口随 I-TOP-01 收口。[片级签核与 DFT 复核](../history/serdes_4g_signoff_dft_20261124.md) |
| 顶层核心装配 | `full_v3` 已合入北侧接地移线、03:00 数字 GDS、加固 SAFF ÷8 和叠层尾滤波，固定合并 GDS 及全规则 **DRC=0** 收据。**99 条受查信号网无开短路、8 条电源网互异、12/12 去耦阵列接通** | 独立重新装配得到相同顶层 MAG。各宏供电/控制补线、实装去耦、Padring/ESD、全片 LVS、RCX 和 IR drop 待验 |
| PLL v4.2 候选 | 由 4× `r5` 和加固 ÷8 `v2_cand` 直接反馈。TT、SS 冷、FS 热 **3/3 完成预充后短窗功能筛查** | 固定粗码、预充偏置 +20 mV，140 ns 原理图台。三角最终 40 ns 频差约 `+597 / −229 / −200 ppm`，全部缺少工程判锁的 320 ns 保持纪录。实际 TX/RX 负载与互连待回灌 |
| 短窗 4 Gb/s 模拟联合台 | 同源 PLL→TX→`C2_loss6`→RX 的分段 TT、SS 冷、FS 热三角回放每点 **0/64 数据错**，PI 中心及 ±8 码通过三个离散点的 `0.50 UI` 跨度门槛且 BBPD 翻向。TT 同 deck **0/80 数据错、0/34 确定边沿错** | 76 ns 台的 PLL 内部仍用旧 CML ÷8。FF 冷角整链在低温 PNP OP 数值上未完成；采用反馈、独立 RX 时基、RTL CDR/FIFO、正式锁定与 BER 各自待验 |
| 加固 SAFF ÷8 候选 | 原理图 PVT **45/45**，SS 冷和 FS 热各 200 样本 MC 为 **199/200 和 200/200**。候选叶独立 DRC/LVS 通过，**7/7** 受查压力点 CPEX 功能与偏斜通过，已装入 `full_v3` | 失配运行的候选 ÷8 为原理图，接收器为 CPEX。SS 的剩余样本在 24 ns 窗口内缺 `q8` 升沿，保存为待诊断。候选自身布局的完整 MC/RCX 和实际反馈锁定仍待 |
| 数字 v3.2 候选 | `full_v3` 使用的 03:00 GDS 宏级 DRC=0、LVS=MATCH，独立 STA 复现 **18/18**，SS 建立/保持最差 **+14.5/+223.9 ps**。VCS 四模式功能通过 | TT/SS 各有 3/1 条复位纪元时序提示，严格 GLS `all_passed=false`。时序提取和 v3.1 发布身份各自保留 |
| 数字 v3.3 候选 | 对齐 CDR 质量窗后通过原 ±300 ppm 功能门槛。隔离的带使能写位方案把最差写入 setup 推至 **+0.488 ns**，又将两组 host 反馈重映射，host 冷角由 **−0.947 提至 −0.580 ns**。该布线过零延时门级回归、所核 31 对同步链、Magic DRC 和 Netgen LVS | 主线路线 A 冷角最差 setup **−1.140 ns**。隔离 host 反馈版一拍接口全局 **−1.354/+0.077 ns**，最差在 RX 一拍状态输出。慢角时序、电气限制和 SDF 延时回归仍需闭合。`full_v8` 实装 `v3.2`。[收口复核](../history/digital_v3p3_closure_review_20261125.md) |
| 数字 v4 32-bit 独立宏 | Antigravity 导出 `394.7 × 372.6 µm` 双速宏。导出和运行目录的 DEF、网表、GDS 哈希一致。原流程两种速率各五角 setup/hold 为正，宏级 DRC=0、LVS=MATCH | 同版 1.65 V 插值冷角复放 max/min RC 后，4G **+0.219/+0.049 ns**，5G **−0.056/+0.049 ns**。SDF 带延时回归和新片顶采用待验。[只读复核](../history/digital_v3p3_closure_review_20261125.md#结构和面积复核) |
| A1/A2/C2 片级接口微修 | A1 局部 6/6。A2 局部复位/相位 6/6。C2 严格 3/4，SS 热波形重算 80/80 | A2 的 SS 冷角完整周期占空比最低 44.01%，C2 热角执行有模型溢出。物理同步和联合台复测待验 |

固定的摘要与实际分层边界见[11 月 24 日集成证据](../../results/catalog/chip_integration_20261124.json)及[后续复核收据](../../results/catalog/ppa_upgrade_review_20261124.json)。历次装配见[片级版图报告](../layout/chip_floorplan_20261123.md)。

[问题登记](open_issues.md)维护关闭条件，[执行计划](prelayout_plan.md)维护顺序。模拟联合台按各自实际时钟、初始化、寄生和数据路径验收。

---

## 5. 5.0 Gb/s 演进路线签核快照（2026-11-26）

在保留上述 4 Gb/s `v1.0` 冻结基线与历史对照目录完全不变的前提下，独立隔离演进的 **5.0 Gb/s 双速（4/5 Gb/s）SerDes** 已完成全套 8/8 模拟单元真 CPEX/RCX 签核、端口协同 32-bit 数字宏 `v4p1` 签核与 Plan-C 全片物理装配签核，固定证据索引见 [5G 签核台账](../../results/catalog/serdes_5g_signoff_20261126.json) 与 [片级版图报告第 9 节](../layout/chip_floorplan_20261123.md#9-50-gbs-plan-c-全片物理装配与层级签核2026-11-26)：

| 子系统 | 隔离变体 / 入口 | 物理与提取签核 | 关键实测边界 |
|---|---|---|---|
| **5G 八边形 LC-VCO** | `lc_vco_5g_oct_pdk` | `DRC=0 / LVS=MATCH` | 6/6 角 + **125 °C 冻码** 3/3 PASS（全角公共交集 `4.469–5.350 GHz`）；24/24 `SS +85°C` MC 锁定，I/Q `σ=0.65 ps` |
| **5G 双速 A/B 分频器** | `div_ab_5g_v2_pdk` | `DRC=0 / LVS=MATCH / M5=0%` | 6/6 角（12/12 `÷8/÷10`）PASS；50/50 `SS −40°C` MC 100% 达标（`\|diff_sk\| ≤ 4.77 ps`） |
| **供电与偏置加固** | `v2_cur_kelvin_pdk` · `v4p5_pdk` | `DRC=0 / LVS=MATCH` | HV18 Kelvin `R_eff -92.9%` / `PSRR ≥ 28.7 dB` / 100× MC 本体 `3σ ≤ 10.8 mV`；TX VDRV LDO 200× MC `3σ ≤ 15.6 mV` |
| **5G TX SST 顶层** | `tx/sst/layout/variants/v5_pdk` | `DRC=0 / LVS=MATCH`（`256.8×169.6 µm`, 38 端口） | 真 CPEX **16/16（12 路 5G + 4 路 4G）PASS**：散布 `0.006–0.145 UI`，`Vdrv_rip ≤ 44.3 mVpp`（零冷角直通），裕量 `100–227 mV` |
| **5G RX 集成顶层** | `rx_top_5g_pdk`（`v5g_4ph_v3_pdk` + `slicer_5g_pdk` + `W3 CTLE`） | `DRC=0 / FP=0 / DC & Open LVS=MATCH`（72/74 端口） | W3 CTLE 45/45 AC + 400× MC；`slicer_5g` 6/6 + 250/250 MC（`3σ ≤ 20.3 mV`）；`PI v3` 6/6 标称 `ALL_OK` + 24×冷角 MC `0/24` 翻转/停振、`20/24 < 30 ps` |
| **5G 数字顶层 `v4p1`** | `hd_pnr_v4p1_5g_coopt` | `DRC=0 / LVS=MATCH`（`385.9×353.6 µm`, `-7.2%`） | 32-bit 降频双速，6 角 ±5% OCV 5G/4G 全 MET（`setup ≥ +0.059 ns / hold ≥ +0.073 ns`），CDC `26/26`，RX 33-bit `0` 交叉 |
| **5G Plan-C 全片装配** | `serdes_5g_top_pdk` | **Magic `DRC=0` / `55.43 MB` GDS / 层级 `ext2spice` `28/28` 连通 & `41/41` 隔离** | `936 × 650 µm = 0.6084 mm²`（`−21.8%` vs Plan A），13 宏密度 `70.3%`，131 紧缩 Direct/Damped/HV33 瓦片 `10.9%`（`147.0 pF`），8 供电域严格独立 |
