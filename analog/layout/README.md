# 模拟版图公共基础设施（`analog/layout/`）

当前采用状态与全片装配结论统一见 [项目当前状态](../../docs/status/current.md)、[版图文档入口](../../docs/layout/README.md) 与 [片级版图与 PDN 报告](../../docs/layout/chip_floorplan_20261123.md)；5.0 Gb/s Plan-C 签核台账见 [serdes_5g_signoff_20261126.json](../../results/catalog/serdes_5g_signoff_20261126.json)。各模块几何、生成器与交付物保存在各自的 `layout/` 目录，构建日志与提取结果统一输出至 `results/layout/`，不在源码目录残留中间提取文件。

## 本目录内容

| 文件 | 作用 |
|---|---|
| [`scripts/layout_core.py`](scripts/layout_core.py) | SKY130A Magic 参数化绘图、阵列与预览公共库（供各模拟模块 PDK 版图生成器与预览脚本复用） |
| [`import.json`](import.json) | 2026-11-13 历史导入与归属审计清单 |

## 物理流程与历史导入边界

- 独立物理复核与全片装配脚本位于 `verification/layout/`（含 `review_cell.py`、`build_chip_top_pdk.py`、`build_chip_top_5g_pdk.py`、`decap_5g_tiles.py` 等），Magic 电容节点修复补丁说明见 [`verification/layout/patches/README.md`](../../verification/layout/patches/README.md)。
- 全部现行 4G `v1.0` 与 5G Plan-C 模块版图均以实测 SKY130A PDK 器件规则从零脚本生成，并逐单元通过 Magic full-rule `DRC = 0`、Netgen `LVS = MATCH`（零属性误差、全部端口出外边界）与独立寄生提取。VCO `sym9_clean` 布局与寄生教训见 [vco_sym9_layout_lessons.md](../../docs/layout/vco_sym9_layout_lessons.md)。
- 早期 2026-11-13 导入的通用 MOS 草案与旧整包生成器已按 SHA-256 核对后退役归档，清单与恢复索引统一维护在 [波形归档与历史退役清单](../../results/catalog/README.md#波形归档与历史退役清单)、[`retired_layout_suites_20261117.json`](../../results/catalog/retired_layout_suites_20261117.json) 与 [`retired_gemini_duplicate_references_20261124.json`](../../results/catalog/retired_gemini_duplicate_references_20261124.json)，禁止从旧整包恢复覆盖现行 PDK 候选。
