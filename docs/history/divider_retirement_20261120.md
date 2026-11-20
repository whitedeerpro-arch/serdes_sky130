# 分频器旧版与失败候选归档记录（2026-11-20）

按“CML（11 端口）与 CMOS/TSPC（10 端口）分族管理、每族保留现行及最近 2 个可用 Var”的整理原则，本批共归档清理 **59 个已入库历史分频器文件**（带逐文件 SHA-256 收据）及 **32 个未入库的失败/中间过程候选文件**。

## 保留清单（CML 2 Var + CMOS/TSPC 2 Var）

- **CML 族（11 端口）**：
  - Var 1（主线 r3）：`analog/pll/divider/spice/{cml_prescaler8,cml_div2,cml_latch}.spice` + `analog/pll/divider/layout/variants/review_clean/`
  - Var 2（候选）：`analog/pll/divider/spice/sync_prescaler8_2stack.spice` + `analog/pll/divider/layout/variants/sync2_routed/`
- **CMOS/TSPC 族（10 端口）**：
  - Var 1（纹波基线）：`analog/pll/divider/spice/cmos_prescaler8_2g.spice` + `analog/pll/divider/layout/variants/cmos_2g_pdk/`
  - Var 2（主推重定时候选）：`analog/pll/divider/spice/tspc_reclock_prescaler8_2g.spice` + `analog/pll/divider/layout/variants/saff_reclock_2g_pdk/`

## 归档与回溯位置

- **已入库历史文件（59 个）**：
  - 源码：`spice/exploratory/latch_candidates.spice`、`spice/{cml_dff,cml_binary_chain,cml_divider_programmable,cml_logic,cmos_divider_programmable}.spice`
  - 测试台：`tb/topology_exploration/`、`tb/logic_truth/`、`tb/functional/tb_{cml_chain,cml_programmable,cmos_divider}_ngspice.cir.in`
  - 被 `variants/review_clean/` 取代的旧版图目录：`layout/variants/pdk/`（45 个文件）
  - 归档本体：`results/maintenance/divider_retirement/20261120/files/`
  - SHA-256 收据与原提交哈希索引：[retired_divider_vars_20261120.json](../../results/catalog/retired_divider_vars_20261120.json)
- **未入库失败与中间候选（32 个）**：
  - 寒角/MC 未过关的 `cmos_sync_prescaler8_2g` 全套（`spice/cmos_sync_prescaler8_2g.spice`、`layout/build_cmos_sync_prescaler8_2g_pdk.py`、`layout/variants/cmos_sync_2g_pdk/`、`tb/cmos_sync_2g/`），其功能已由 `saff_reclock_2g_pdk` 取代；
  - 被 `variants/sync2_routed/` 取代的未布线中间态：`layout/place_sync2_blocks.py`、`layout/variants/sync2_pdk/`；
  - 归档本体：`results/maintenance/divider_retirement/20261120/untracked/`。

本次清理不改变 `config/pll_working_revision.toml` 中的现行采用配置或任何已登记验证证据。
