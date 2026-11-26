# PLL 分频器版图入口（`analog/pll/divider/layout/`）

本目录维护 5G 双速 A/B 分频器与 4G SAFF-TSPC 重定时 ÷8 的 SKY130A PDK 版图生成器及签核交付物；电气验证口径见 [pll_feedback_data_dividers.md](../../../../docs/design/pll_feedback_data_dividers.md)、[pll_tspc_reclock_divider.md](../../../../docs/design/pll_tspc_reclock_divider.md) 与 [serdes_5g_signoff_20261126.json](../../../../results/catalog/serdes_5g_signoff_20261126.json)。

## 当前保留变体与生成器

| 变体目录 | 生成器 | 状态与定位 |
|---|---|---|
| [`variants/div_ab_5g_v2_pdk/`](variants/div_ab_5g_v2_pdk/)（[`summary.json`](variants/div_ab_5g_v2_pdk/summary.json)） | [`build_div_ab_5g_v2_pdk.py`](build_div_ab_5g_v2_pdk.py) | **5G Plan-C 双速 A/B 分频器（`÷8 / ÷10`）**：`DRC=0 / LVS=MATCH / M5=0%`，6/6 角（12/12）CPEX + 50/50 `SS −40 °C` MC 100% PASS（早期初版保留在 `variants/div_ab_5g_pdk/`） |
| [`variants/saff_reclock_2g_pdk/`](variants/saff_reclock_2g_pdk/README.md) | [`build_saff_reclock_prescaler8_2g_pdk.py`](build_saff_reclock_prescaler8_2g_pdk.py) | **4G 主线 SAFF-TSPC 重定时 ÷8 (`v2`)**：`97.335 × 17.520 µm = 1,705.31 µm²`，`DRC=0 / LVS=MATCH`，45/45 CPEX 功能通过、`RCX_BOTH` 5/5；静态 LVT XOR 加固候选见 [`variants/saff_reclock_2g_v2_pdk/`](variants/saff_reclock_2g_v2_pdk/) |
| [`variants/review_clean/`](variants/review_clean/) | — | 历史 r3 双翼 CML ÷8 物理清理参考快照（原全量 RC 分支 `LAYOUT-PLL-DIV-RC-01` 已暂停） |
| — | [`build_cmos_prescaler8_2g_pdk.py`](build_cmos_prescaler8_2g_pdk.py) | 历史级联 C²MOS 纹波 ÷8 生成器参考 |

已退役的早期变体（`pdk`、`sync2_routed`、`cmos_sync_2g_pdk`、`cmos_2g_pdk` 等）均按 SHA-256 归档于 [`retired_divider_vars_20261120.json`](../../../../results/catalog/retired_divider_vars_20261120.json) 与 [`retired_pre_release_20261123.json`](../../../../results/catalog/retired_pre_release_20261123.json)。
