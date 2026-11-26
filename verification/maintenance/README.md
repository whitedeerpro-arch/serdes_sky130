# 仓库与结果维护

源码、手写文档、配置和小数据入 Git；运行产物放追加式 `results/`，通过 `results/catalog/` 记录身份。旧失败证据与发布基线不能当作临时文件批量删除。

源码目录整洁检查：

```bash
uv run python verification/maintenance/repository_hygiene.py audit
```

检查会发现 `analog/**/layout/` 的原始日志/EXT，以及仓库根目录的 VCD/raw/fst 波形，包括已被 Git 忽略的文件；发现时返回非零。测试目录的 EXT fixture、器件参考、几何与提取网表不在清理集合。

检查同时读取 `results/catalog/retired_*.json` 的 `files[].former_path`，拒绝已清退文件重新出现在源码区（包括软链接）。旧大环顶层、旧整包生成器与失效总览因此不会被悄悄恢复。退役清单记录明确判定过的文件，不按文件年龄或所有未提交文件自动删除。下方 `archive` 只搬运行产物；重新出现的退役文件需复核来源，不能直接当作原件覆盖归档。

在装有本地归档的工作区，使用 `uv run python verification/maintenance/repository_hygiene.py verify-retired` 核对退役文件的大小和 SHA-256。归档路径和各清单的恢复线索见[结果索引](../../results/catalog/README.md#退役索引)。普通 Git 检出可独立执行上面的 `audit`。

需要清理时显式给新目录：

```bash
uv run python verification/maintenance/repository_hygiene.py archive \
  --output-dir results/maintenance/repository_hygiene/new_run
```

脚本先复制全部文件、比较源/目标 SHA256 并写清单，再移走源码区副本；旧输出目录拒绝覆盖。归档记录需要发布时，把小清单纳入 `results/catalog/`。生成器的安装产物应限于几何、独立参考、必要预览、小摘要与明确身份的网表；日志/EXT 留在构建结果中。`.gitignore` 防止误入库，不能替代此检查。

大波形空间维护继续使用 [waveform_archive.py](waveform_archive.py) 和 [compress_waveforms.py](compress_waveforms.py)：它们检查活跃仿真和已登记来源，压缩/跨分区归档须用对应命令，不能直接删除波形或改写历史 deck 的路径。

相同内容的共享资源保留一个规范路径；已有消费者使用过的路径可留仓库内相对软链接。图表重新生成写规范路径，旧 JSON/历史记录的内容哈希继续可读。文件迁移后运行文档链接、资料入口与相关身份检查；发布记录不能只靠修改时间选“最新”。
