# WP-001–003 证据重提取复核（2026-11-09）

结论：重新提取的三包 `observations`、`checks`、`unresolved` 与原交付一致；WP-003 的路径字符串统一去掉当前仓库绝对前缀后逐字段一致。旧交付的输入哈希不再匹配，不能仅更换哈希冒充复核；本次结果另存，未覆盖原交付，也不改变工作包接受状态或设计签核。

| 包 | 新执行状态 | 输入数 | 检查结果 | unresolved | 原始差异 |
|---|---|---:|---|---:|---|
| WP-001 | complete | 17 | 42 pass、3 ungraded | 0 | 三个内容字段完全一致 |
| WP-002 | partial | 18 | 8 pass、1 fail、5 ungraded | 6 | 三个内容字段完全一致 |
| WP-003 | complete | 640 | 240 pass、7 fail、12 missing、2 ungraded | 3 | 路径绝对/相对表示不同；规范化后内容一致 |

WP-002 的 `metadata_extraction` 仍为 fail：`docs/design/tx_serializer.md` 中预期文字“没有并行字捕获寄存器”出现 0 次。WP-003 检查了 10 个固定历史根、54 个条件行、52 条历史 summary、63 个正式尝试和 1 个 smoke；输出完整性为 52 pass、7 fail、5 missing，12 个范围格中 7 个有明确完整证据。历史失败、缺失和未知项均保留；这些数字不代表当前设计规格通过。

输入身份变化：WP-001 的 `AGENTS.md`、`README.md`、`config/boundary_conditions.json` 和 `src/serdes_flow/spice.py`；WP-002 的 `config/tx_working_revision.toml`；WP-003 的 `AGENTS.md` 和 `src/serdes_flow/spice.py`。其余已规范化路径的输入哈希一致；完整哈希见对应证据 JSON。

新证据位于 `results/work_packages/revalidation/20261109T083146113800458Z/WP-001/evidence.json`、同目录 `WP-002/evidence.json` 和 `WP-003/evidence.json`。分别运行 `uv run python verification/work_packages/wp001_pll_waveforms.py --output DIR`、`wp002_tx_ingress.py --output DIR`、`wp003_rx_lineage.py --output DIR`，均完成提取。WP-003 的脚本拒绝输出到 `results/`，故使用 `/tmp/serdes-wp003-revalidation-9gumwA` 作为输出目录，再原样复制 JSON 至上述目录。没有运行 ngspice。

原交付执行 `uv run python -m serdes_flow.work_packages check WP-NNN`：WP-001 与 WP-003 首个报错均为 `input changed: AGENTS.md`，WP-002 为 `input changed: config/tx_working_revision.toml`；WP-004 仍为 `delivery_format: valid`、状态 accepted，6 个输入、1 pass 和 1 ungraded。检查器在首个不符输入处停止，上述输入变化清单来自逐项比较。

## 集成采纳与归档兼容

重新提取后又修复了两处输入身份问题：WP-001随共享任务说明更新再次提取；WP-003保留原仓库路径作为身份，避免把波形软链接解析到归档后写成绝对路径。检查器仅接受results下到`/opt/serdes_archive/<同仓库相对路径>`的精确映射，任意外部链接及错位映射仍拒绝。

集成者再次把WP-001–004与保存的原交付逐项比较：统一仓库/精确归档的路径表示后，observations/checks/unresolved相同，失败和缺失未删减。新证据已采纳到原交付路径，原证据另存复核目录的original子目录；WP-004因上游身份更新也重新计算，模型结果不变。四包当前格式/输入检查均valid，其中WP-002仍partial并保留1 fail，WP-003仍保留7 fail和12 missing。接受工作包不等于接受整个模块。
