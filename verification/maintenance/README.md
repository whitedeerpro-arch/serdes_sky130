# 仓库与结果维护

源码、手写文档、配置和小数据入 Git；运行产物放追加式 `results/`，通过 `results/catalog/` 记录身份。旧失败证据与发布基线不能当作临时文件批量删除。

源码目录整洁检查：

```bash
uv run python verification/maintenance/repository_hygiene.py audit
```

检查会发现 `analog/**/layout/` 的原始日志/EXT，以及仓库根目录的 VCD/raw/fst 波形，包括已被 Git 忽略的文件；发现时返回非零。测试目录的 EXT fixture、器件参考、几何与提取网表不在清理集合。

需要清理时显式给新目录：

```bash
uv run python verification/maintenance/repository_hygiene.py archive \
  --output-dir results/maintenance/repository_hygiene/new_run
```

脚本先复制全部文件、比较源/目标 SHA256 并写清单，再移走源码区副本；旧输出目录拒绝覆盖。归档记录需要发布时，把小清单纳入 `results/catalog/`。生成器的安装产物应限于几何、独立参考、必要预览、小摘要与明确身份的网表；日志/EXT 留在构建结果中。`.gitignore` 防止误入库，不能替代此检查。

大波形空间维护继续使用 [waveform_archive.py](waveform_archive.py) 和 [compress_waveforms.py](compress_waveforms.py)：它们检查活跃仿真和已登记来源，压缩/跨分区归档须用对应命令，不能直接删除波形或改写历史 deck 的路径。

相同内容的共享资源保留一个规范路径；已有消费者使用过的路径可留仓库内相对软链接。图表重新生成写规范路径，旧 JSON/历史记录的内容哈希继续可读。文件迁移后运行文档链接、资料入口与相关身份检查；发布记录不能只靠修改时间选“最新”。
