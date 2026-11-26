# PLL 反馈与数据分频器（`analog/pll/divider/`）

本目录维护 **5.0 Gb/s 双速 A/B 分频器（`div_ab_5g_v2_pdk`）**、**4.0 Gb/s SAFF-TSPC 重定时 ÷8 预分频器（`saff_reclock_2g_pdk` / `v2_cand`）** 及早期 CML ÷8 参考网表。设计报告见 [pll_feedback_data_dividers.md](../../../docs/design/pll_feedback_data_dividers.md) 与 [pll_tspc_reclock_divider.md](../../../docs/design/pll_tspc_reclock_divider.md)，项目级签核状态见 [current.md](../../../docs/status/current.md) 与 [serdes_5g_signoff_20261126.json](../../../results/catalog/serdes_5g_signoff_20261126.json)。

## 现行实现与版图变体

| 路线 / 变体 | 原理图网表 | PDK 版图与状态 |
|---|---|---|
| **5G 双速 A/B 分频器（`÷8 / ÷10`）** | [`spice/pll_div_ab_5g_v2.spice`](spice/pll_div_ab_5g_v2.spice) | [`layout/variants/div_ab_5g_v2_pdk/`](layout/variants/div_ab_5g_v2_pdk/)（[`summary.json`](layout/variants/div_ab_5g_v2_pdk/summary.json)）：`DRC=0 / LVS=MATCH / M5=0%`，6/6 角（12/12 `÷8/÷10`）PASS，50/50 `SS −40 °C` MC 100% 达标（`\|diff_sk\| ≤ 4.77 ps`） |
| **4G SAFF-TSPC 重定时 ÷8（主线片级宏）** | [`spice/tspc_reclock_prescaler8_2g.spice`](spice/tspc_reclock_prescaler8_2g.spice) · [`spice/tspc_reclock_prescaler8_2g_v2_cand.spice`](spice/tspc_reclock_prescaler8_2g_v2_cand.spice) | [`layout/variants/saff_reclock_2g_pdk/`](layout/variants/saff_reclock_2g_pdk/README.md)（`1,705 µm²`，45/45 CPEX 功能通过、`RCX_BOTH` 5/5）与加固候选 [`layout/variants/saff_reclock_2g_v2_pdk/`](layout/variants/saff_reclock_2g_v2_pdk/) |
| **早期 CML ÷8（历史参考）** | [`spice/cml_prescaler8.spice`](spice/cml_prescaler8.spice) · [`spice/cml_div2.spice`](spice/cml_div2.spice) · [`spice/cml_latch.spice`](spice/cml_latch.spice) | [`layout/variants/review_clean/`](layout/variants/review_clean/)（仅保留供 4G 冻结闭环对照） |

版图生成器索引见 [`layout/README.md`](layout/README.md)。已退役的早期分频器变体与 SHA-256 收据记录在 [`retired_divider_vars_20261120.json`](../../../results/catalog/retired_divider_vars_20261120.json) 与 [`retired_pre_release_20261123.json`](../../../results/catalog/retired_pre_release_20261123.json)。

## 现行测试台

| 测试脚本 | 层次 | 说明 |
|---|---|---|
| [`tb/tspc_study/benchmark.py`](tb/tspc_study/benchmark.py) | block / post-layout | SAFF-TSPC ÷8 四架构对比、45 角 CPEX PVT、静态/纹波 `Kd`、频率 Shmoo、双端原生 RCX 与 200 样本失配 MC |
| [`tb/tspc_study/harden_xtg2.py`](tb/tspc_study/harden_xtg2.py) | block / post-layout | 加固版 `v2_cand`（静态 LVT XOR 替代 `Xtg2` 传输门）PVT / MC 验证 |

结果统一输出到 `results/analog/pll/divider/`，执行约定见 [docs/verification/methods.md](../../../docs/verification/methods.md)。
