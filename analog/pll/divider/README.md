# 反馈分频器

当前主线（11 端口 CML 族）采用 `spice/cml_prescaler8.spice`（三级固定 CML ÷8，输出 `/2`、`/4`、`/8` 抽头；2 GHz 输入对应 1 GHz / 500 MHz / 250 MHz）。纯 CMOS / TSPC 2 GHz ÷8 为独立的 10 端口替代研究分支，不与 CML 族混计版本槽位。

早期全 CML 可编程计数器、`cml_binary_chain`、`cmos_divider_programmable`、`exploratory/latch_candidates` 及已淘汰的 `cmos_sync_prescaler8_2g` 已于 2026-11-20 归档退役（见 [divider_retirement_20261120.md](../../../docs/history/divider_retirement_20261120.md) 与 `results/catalog/retired_divider_vars_20261120.json`）。

## 当前保留实现（CML 族 2 Var + CMOS/TSPC 族 2 Var）

| 家族 | 实现 | 用途与状态 |
|---|---|---|
| **CML（11 端口）Var 1（主线）** | [cml_prescaler8.spice](spice/cml_prescaler8.spice)、[cml_div2.spice](spice/cml_div2.spice)、[cml_latch.spice](spice/cml_latch.spice) | 现行工作修订 r3 三级固定 CML ÷8；物理清理版在 [layout/variants/review_clean](layout/variants/review_clean/README.md) |
| **CML（11 端口）Var 2（候选）** | [sync_prescaler8_2stack.spice](spice/sync_prescaler8_2stack.spice) | 2-Stack 同步 CML 候选，版图在 `layout/variants/sync2_routed`（已归档至 `retired_pre_release_20261123.json`）（见 [pll_sync_prescaler8.md](../../../docs/design/pll_sync_prescaler8.md)，身份与 RC 复核边界未关闭） |
| **CMOS/TSPC（10 端口）Var 1** | [cmos_prescaler8_2g.spice](spice/cmos_prescaler8_2g.spice) | 级联 C²MOS 纹波 ÷8 基线，版图在 `layout/variants/cmos_2g_pdk`（已归档至 `retired_pre_release_20261123.json`）（`verify_r5_pdk.py` / `pll_pending_review.py` 引用） |
| **CMOS/TSPC（10 端口）Var 2（主推候选）** | [tspc_reclock_prescaler8_2g.spice](spice/tspc_reclock_prescaler8_2g.spice) | Equalized Nikolic SAFF-TSPC + 1 GHz 同步计数 + 三路 2 GHz 重定时 ÷8（含 9T 动态对照）；版图 v2 在 [layout/variants/saff_reclock_2g_pdk](layout/variants/saff_reclock_2g_pdk/README.md)，报告见 [pll_tspc_reclock_divider.md](../../../docs/design/pll_tspc_reclock_divider.md) |

## 测试台

| 测试项 | 层次 | 说明 |
|---|---|---|
| [pvt](tb/pvt/case.toml) / [rcorner.py](tb/pvt/rcorner.py) | block | CML ÷8 低过驱动 45 角与电阻角筛选 |
| [div2_map](tb/div2_map/run.py) | cell | 首级 CML ÷2 可行区图（保持管宽度 / 频率 / 摆幅） |
| [layout_pex](tb/layout_pex/run.py) | post-layout | 2 GHz 实际 buffer + CML ÷8 提取网表 + 反馈接收联合台 |
| [mc](tb/mc/run.py) | block | CML ÷8 失配蒙特卡洛 |
| [sync2_pvt](tb/sync2_pvt/) / [sync2_mc](tb/sync2_mc/) | block | 2-Stack CML 候选 PVT / MC |
| [tspc_study](tb/tspc_study/benchmark.py) | block / post-layout | 纯 CMOS/TSPC 多角度对比（9 硬角 / 45 角 / 静态与纹波 `Kd` / 频率 Shmoo / CPEX & RCX / 200 样本 MC） |
| [functional](tb/functional/case.toml) / [input_range](tb/input_range/case.toml) | cell | CML ÷2 基础功能与输入范围 |

结果统一输出到 `results/analog/pll/divider/<case>/<run_id>/`，按 [测试约定](../../../docs/verification/methods.md) 使用 ngspice 47 执行。
