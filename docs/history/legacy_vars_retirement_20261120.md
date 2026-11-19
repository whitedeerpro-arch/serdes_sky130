# 历史版本退休清理记录（2026-11-20）

为控制各模块在研版本数量（每个设计仅保留现行基线及最近 2–3 个有效 Var），本批次按仓库既有归档规范退休 73 个早期 `v0.1 / r1 / r2 / r3 / r4` 历史网表、旧版图原型与专属旧测试台。全部原字节已按原相对路径归档至 `results/maintenance/legacy_vars_retirement/20261120/files/`，并登记至 [retired_legacy_vars_20261120.json](../../results/catalog/retired_legacy_vars_20261120.json)（同时纳入 `verification/maintenance/repository_hygiene.py` 防回流检查）。原文件亦可通过 Git 历史（`source_commit` 及 `baseline-prelayout-20261113`、`releases/v0.1-design-freeze-20261028/`）完整恢复。

## 退休范围与保留版本

| 模块 | 退休内容 | 保留的现行与最近 2–3 个 Var |
|---|---|---|
| PLL 顶层 (`analog/pll/top/spice/`) | `clock_frontend_{balanced,pvt_candidate,lowov,r4}.spice`、`pll_balanced_{core,startup_core}.spice` 及 11 个专属 v0.1/r3/r4 测试台 | 前端：`clock_frontend_{r5,r5q,r6q}.spice`（3）；核心：`pll_core_{r5k4,r5k4q,r6k4q}.spice`（3） |
| LDO (`analog/common/ldo/spice/`) | `ldo_hv18_{r1,r2,core}.spice`、`pll_supply_hv18.spice`、`tb/modes/` | `r4`（现行采用）、`smallcap`（70 pF 单层）、`stacked`（70 pF 叠层）（3）；版图：`mim_pdk`、`r4_pdk`、`smallcap_pdk`（3） |
| VCO (`analog/pll/vco/`) | `vco_ring4_pvt_candidate.spice`、旧原型版图 `layout/variants/sym9_pdk/` | VCO：`vco_ring4`（参考）、`vco_ring4_4b`（r5）、`vco_ring4_r6`+`vco_delay_r6`（r6）（3）；电容阵列：`3b/4b/5b`（3）；版图：`sym9_clean`、`r6_pdk`（2） |
| 电荷泵 (`analog/pll/cp/spice/`) | `charge_pump_{source_switched,enabled}.spice` | `charge_pump.spice`、`charge_pump_steer.spice`（2） |
| 环路滤波 (`analog/pll/loop_filter/spice/`) | `passive_rc_pdk_candidate.spice` 及 `tb/pdk_mapping/` | `passive_rc.spice`、`passive_rc_precharge.spice`、`passive_rc_pdk_k4.spice`（3） |
| CML→CMOS (`analog/common/cml_to_cmos/spice/`) | `cml_to_cmos_acsb.spice` | 公共基类 + `pvt_candidate`（250M 反馈）+ `r4`/`r4_v4` + `r5`（v6）；版图 `pdk`/`r4_pdk`/`r5_pdk`（3） |
| TX 驱动/串化/MUX | `cml_line_driver_{biaswell,footer}_candidate.spice`、`serializer16_tree{,_cmos_select}.spice`、`cml_mux2_cmos_select.spice` 及对应旧 TB | 驱动：`cml_line_driver` + `lowvt_enable`（2）；串化：`retimed` + `retimed_lowov`（2）；MUX：基础 + `cml_lowov_cells`（2） |

## 同步清理与验证

- 22 份引用上述旧文件的 Markdown 文档已将失效相对链接更新为退休说明，保证 `tests/test_doc_links.py` 全部通过。
- `config/design_catalog.json` 与 `web/design/catalog.js` 中的旧 `pll_balanced_*` 引用已同步指向现行 `pll_core_r6k4q.spice` / `pll_core_r5k4q.spice`。
- 分频器目录（`analog/pll/divider/`）的旧版图与遗留 SPICE 退休将在 TSPC / 重定时高速分频器方案定型后单独成批处理并登记。
