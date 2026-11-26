# PLL 顶层集成、闭环台与环路模型（`analog/pll/top/`）

本目录维护 4.0 Gb/s PLL v4 顶层电路网表、晶体管级闭环验收台，以及供 4G / 5G 环路共用的线性环路/相噪/电源抑制理论模型。完整架构与最新结论见 [docs/design/pll_loop.md](../../../docs/design/pll_loop.md)、[docs/design/pll_vco_r6_perf.md](../../../docs/design/pll_vco_r6_perf.md) 与 [docs/status/current.md](../../../docs/status/current.md)；5.0 Gb/s 八边形 LC-VCO 与双速分频器独立入口见 [`../vco_5g/README.md`](../vco_5g/README.md) 与 [`../divider/README.md`](../divider/README.md)。

## 现行顶层网表

| 文件 | 作用与边界 |
|---|---|
| [`spice/pll_top_r6_v4_upgrade.spice`](spice/pll_top_r6_v4_upgrade.spice) | **4G `v1.0` 发布闭环顶层**：VCO `r6` + PTAT `28/66` + `CP v4` + `LF k4` + `PFD sc_dly` + `HV18 v2_cur` + 冻结 `clock_frontend_r6q`（7/7 角通过 320 ns 工程锁定合同） |
| [`spice/pll_top_r6_v4p2_saff.spice`](spice/pll_top_r6_v4p2_saff.spice) | **片级反馈 `v4.2` 候选顶层**：4× `r5` 直接驱动八相时钟，由 `c1/c5` 经加固 SAFF ÷8 `v2_cand` 反馈 |
| [`spice/pll_core_r6k4q.spice`](spice/pll_core_r6k4q.spice) · [`spice/clock_frontend_r6q.spice`](spice/clock_frontend_r6q.spice) | `r6` 分域安静核与冻结前端参考子电路 |

## 闭环测试台与理论脚本

| 位置 | 层次 | 说明 |
|---|---|---|
| [`tb/lock_v4/verify_pll_v4_closed_loop.py`](tb/lock_v4/verify_pll_v4_closed_loop.py) | system | **4G PLL v4 主线 7 角闭环锁定验收台**（按 [pll_lock_screen.toml](../../../verification/contracts/pll_lock_screen.toml) 评分） |
| [`tb/verify_pll_v4p2_saff.py`](tb/verify_pll_v4p2_saff.py) | system | `v4.2`（4× `r5` + 加固 SAFF ÷8）固定粗码、预充后短窗功能筛查（见 [chip_integration_20261124.json](../../../results/catalog/chip_integration_20261124.json)） |
| [`tb/frontend_r6/run.py`](tb/frontend_r6/run.py) | integration | `r6` VCO + 前端缓冲与分频器开环表征 |
| [`theory/`](theory/) | analytical | 环路选型（`loop_design.py`）、闭环相噪合成（`pll_noise.py`）、CDR 抖动滤波（`cdr_jitter.py`）、电源分接与 LDO 纹波容限（`loop_psrr.py`、`supply_split.py`、`supply_tolerance.py`、`ldo_supply_tolerance.py`、`recode_transient.py`） |

所有运行结果追加写入 `results/analog/pll/top/`，接口约定见 [docs/overview/architecture.md](../../../docs/overview/architecture.md)。
