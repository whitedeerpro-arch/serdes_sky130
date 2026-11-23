# 运行结果与归档入口

本机波形使用两种归档方式。2026-11-20 的整理由 `waveform_archive.py` 将波形移至 `/opt/serdes_archive`，原路径保留软链接，读取与续跑沿用原路径。2026-10-29 的历史批量归档使用 `tar.xz` 并按下文命令读取或恢复。[11 月 20 日归档清单](catalog/waveform_archive_20261120.json)

## 本机波形软链接

归档工具忽略配置的近期时段和活动仿真目录，每个波形在复制校验后才替换为软链接。逐文件 SHA-256 清单写入 `results/maintenance/waveform_archive/`。

```bash
uv run python verification/maintenance/waveform_archive.py verify
uv run python verification/maintenance/waveform_archive.py restore results/某个运行目录
```

## 历史打包归档

```text
results/
  acceptance/20261029-rx-functional/  阶段审阅入口、VCD/FST、GTKWave会话
  catalog/                           实验清单、归档索引、清理/恢复记录
  archives/
    analog/<模块>/<实验>/<run>.bulk.tar.xz
    ...                              原目录层级下的大文件归档
  analog/<模块>/<实验>/<run>/         输入快照、日志、指标、小数据表
  digital/                           RTL单元、串并、CDR长时行为plant结果
  verification/                      信道、流窗、实时数模联调
  infrastructure/                    工具与激励自检
  schematics/                        历史原理图导出实验
```

- 阶段审阅与波形 (`results/acceptance/20261029-rx-functional/README.md`)
- [按模块／实验索引](catalog/README.md)，[逐运行TSV](catalog/experiments.tsv)
- [原文件→归档成员索引](catalog/artifacts.tsv)，[完整归档账本](catalog/archive_ledger.json)
- [清理策略](../verification/results/retention.toml)，[阶段结论](../docs/history/stage_review_20261029.md)

被压缩的运行目录有 `ARTIFACTS_ARCHIVED.json`。大文件从常用目录移出前，已完整解压流校验每个成员的 SHA256；相同内容在归档内用硬链接成员去重。原文件可以按历史路径恢复，输入/netlist/source/snapshots、日志、指标和当前验收波形保留在原处。

```bash
verification/results/artifact.sh locate results/某个历史运行/raw/waveforms.tsv
verification/results/artifact.sh verify results/某个历史运行/raw/waveforms.tsv
verification/results/artifact.sh restore results/某个历史运行/raw/waveforms.tsv
```

`cat` 可直接读取压缩中的文件。`restore` 校验哈希后恢复到原路径，已存在文件不覆盖。重做旧分析或仿真前，先恢复所需大文件；通用读取脚本不会自动识别归档。历史证据中的哈希指向原始字节，归档后的存放位置由上述索引补充。

运行产物由 .gitignore 排除，本说明除外。需要长期随设计保存的归档定位表在 [docs/data/results_archive_manifest.json](../docs/data/results_archive_manifest.json)。冻结的 `releases/v0.1-design-freeze-20261028` 未修改。详见 [测试与结果约定](../docs/verification/methods.md)。
