# PLL Charge Pump v4（宽摆幅 + 1/4 单位指副本主动伺服匹配候选）

> **状态**：独立候选（`charge_pump_steer_v4.spice` / `pll_cp_steer_v4_pdk`），未替换主线 `config/pll_working_revision.toml`；保持 `up dn out vbn vbp ibias vdd vss` 精确 8 端口即插即用兼容。

## 结论

相对 v3（`pll_cp_steer_pdk`），v4 在保持 `Icp = 200 µA`、相同 8 端口和无 M5 约束的前提下，通过**1/4 单位指副本主动伺服匹配环**与**宽摆幅 PMOS 支路加宽**，消除了 v3 在 `1.65 V` 低压和 `SF/FS` 偏角下的两大短板：

- **135 角 UP/DN 电流失配（`[0.60, VDD−0.35] V`）**：`11.29%` → **`0.193%`**（降幅 **58×**；`1.65 V` 下 `0.146%`；展宽至 `[0.50, VDD−0.30] V` 为 `0.330%`）。
- **`1.65 V` 5% 跌落上限**：`[0.38, 1.26] V`（距 VCO `vhi` 裕量 `24.4 mV`）→ **`[0.38, 1.49] V`（裕量 `251.2 mV`，提升 `+230 mV` / `10.3×`）**；`1.80 V` / `1.95 V` 上限同步拓宽至 `1.67 V` / `1.84 V`。
- **伺服环稳定性与动态建立**：6 极端角 × 3 `Vout` 下相位裕度 **`60.2°–80.6°`**（直流增益 `50–89 dB`，UGBW `1.8–16.9 MHz`）；250 MHz 脉冲与阶跃瞬态 6/6 无振铃，TT 功耗 `753.6 → 794.6 µW`（`+5.4%`）。
- **SKY130 PDK 物理版图与后仿**：`58.98 × 43.70 µm = 2,577.43 µm²`（相对 v3 `2,175.50 µm²` 仅 `+18.5%`），Magic 全规则 `DRC = 0`、Netgen `LVS = MATCH`（`0` 参数误差，`35/35` 器件，`8/8` 端口）、`0` 浮空多晶、`0.0%` M5、`out` 节点 CPEX `19.943 fF`、RCX `2,647` 电阻（`devices_preserved = True`）；6 极端角 CPEX DC 失配 `≤ 0.146%`，与原理图吻合至 `0.001%`。

## 架构与版图设计

- **电路源码**：`analog/pll/cp/spice/charge_pump_steer_v4.spice`
  - **1/4 单位指副本**：`Xpr (28/1, nf=4)` + `Xpsr (6/0.15, nf=2)` 对 `Xnr (5/1, nf=1)` + `Xnsr (2/0.15, nf=1)`，与主支路 `Xp (112/1)`、`Xps/Xpd (24/0.15)`、`Xn (20/1)`、`Xns/Xnd (8/0.15)` 保持严格 4:1 单位指比例。
  - **8T 轨到轨对称伺服 OTA**：由外部 `vbp` 经 `Xsb_p/Xsb_n` 提供 `2.5 µA` 尾流（不给 `ibias` 增负，且保持 8 端口全有效），输出 `vbp_srv` 闭环调节 `Xp`/`Xpr` 栅压；`rep` 与 `vbp_srv` 之间跨接 `10.0 × 14.0 µm` M3–M4 米勒 MIM 电容 `Xcsrv` 补偿主极点。
  - **宽摆幅 PMOS 主支路**：`Xp` 由 `80/1` 加宽至 `112/1`（`2 × 8 × 7 µm` 指），ABBA 共质心 PMOS 转向开关 `Xps/Xpd` 由 `16/0.15` 加宽至 `24/0.15`（`8 × 3 µm` 指）。
- **物理版图**：`analog/pll/cp/layout/build_cp_steer_v4_pdk.py` → `analog/pll/cp/layout/variants/v4_pdk/`
  - 将 1/4 副本、8T 伺服 OTA 与 3D 堆叠米勒 MIM 电容 `Xcsrv` 嵌入原 v3 左侧空腔，右侧保持三列主电流镜 + ABBA 转向开关 + 单位增益缓冲与 `Cdum` 布局。
  - 输出 `out` 采用单条悬空 M4 干线（`y = -0.95 µm`）直出右边界，控制 `out` 寄生电容在 `19.943 fF`，全单元 M1–M4 完成（`0.0%` M5）。

## v3 与 v4 实测对比

| 指标 | v3 (`pll_cp_steer_pdk`) | v4 (`pll_cp_steer_v4_pdk`) | 变化 |
|---|---:|---:|---|
| 135 角 UP/DN 失配（`[0.60, VDD−0.35]`） | `11.29%`（中点） | **`0.193%`**（`1.65 V`: `0.146%`；`[0.50, VDD−0.30]`: `0.330%`） | 降低 **58×** |
| `1.65 V` 5% 跌落窗口（距 `vhi` 最小裕量） | `[0.38, 1.26] V`（`24.37 mV`） | **`[0.38, 1.49] V`（`251.2 mV`）** | **`+230 mV`**（`10.3×`） |
| `1.80 V` 5% 跌落窗口（距 `vhi` 最小裕量） | `[0.39, 1.42] V`（`36.27 mV`） | **`[0.39, 1.67] V`（`284.7 mV`）** | **`+250 mV`**（`7.8×`） |
| `1.95 V` 5% 跌落窗口（距 `vhi` 最小裕量） | `[0.41, 1.57] V`（`39.19 mV`） | **`[0.41, 1.84] V`（`308.5 mV`）** | **`+270 mV`**（`7.9×`） |
| 伺服环 AC 相位裕度（6 角 × 3 `Vout`） | — | **`60.2°–80.6°`**（直流增益 `50–89 dB`） | 无条件稳定 |
| 250 MHz 瞬态建立 / TT 功耗 | `753.6 µW` | 6/6 无振铃，`vbp_srv` 纹波 `9.0–52.0 mV` / **`794.6 µW`** | `+5.4%` |
| 版图后仿 CPEX DC（6 极端角） | — | `1.65 V hi ≥ 1.49 V`，最大失配 **`0.146%`** | 与原理图差 `0.001%` |
| 尺寸 / 面积 | `56.58 × 38.45 µm` / `2,175.50 µm²` | **`58.98 × 43.70 µm` / `2,577.43 µm²`** | `+18.5%` |
| DRC / LVS / 浮空多晶 / M5 | `0 / MATCH / 0 / 0.0%` | **`0 / MATCH / 0 / 0.0%`** | 全过（`review_cell.py --rc`） |
| `out` CPEX / RCX 电阻数 | `16.112 fF` / `1,751` | **`19.943 fF`** / **`2,647`**（`devices_preserved=True`） | `≤ 20 fF` |

## 适用范围与验证边界

- 所有 135 角 DC、AC、250 MHz 瞬态与 6 极端角 CPEX DC 均采用真实 SKY130A 器件模型与真实偏置接口；135 角包含 `5 MOS × 3 VDD (1.65/1.80/1.95 V) × 3 T (−40/27/85 °C) × 3 RC (ll/tt/hh)`。
- 尚未跑完整 PLL 闭环噪声与锁定瞬态整机替换回归；正式采纳前需在 PLL 顶层接入 `charge_pump_steer_v4` 复核参考杂散与锁定时间。

## 证据路径

- 验证脚本：`analog/pll/cp/tb/dc/verify_cp_v4.py`
- 135 角 DC 汇总：`results/analog/pll/cp/v4/verify_20261122/dc_135_summary.json`
- AC 与 250 MHz 瞬态汇总：`results/analog/pll/cp/v4/verify_20261122_v2/{ac_stability_summary.json,tran_250m_summary.json}`
- 6 极端角 CPEX DC 汇总：`results/analog/pll/cp/v4/verify_20261122_pex/pex_dc_6_summary.json`
- 版图签核与独立 `review_cell.py --rc`：`results/layout/pll_cp/v4_pdk/review_rc_v5/summary.json`
- 安装版图与预览：`analog/pll/cp/layout/variants/v4_pdk/README.md`
