# WP-003 交接

交付文件：`evidence.json`、`summary.md`、`handoff.md`，均位于本目录；复用既有 `verification/work_packages/wp003_rx_lineage.py`，未修改脚本或历史数据。

执行 `uv run python verification/work_packages/wp003_rx_lineage.py --output docs/work_packages/deliveries/WP-003`，退出码 0。读取 59 个 raw，共 479,436,002 字节，最大单个 8,975,368 字节；脚本逐个用 `spice.Waves` 读取并释放，SHA256 分块读取。检查命令及结果见下方。未启动 ngspice、联网、重算 PRBS、提交或修改中央状态。

Terra首次交接提出以下3项，由集成者审查并完成2处代码返工后重跑：

1. TT真实偏置运行的库段为`hh`，审计曾误要求`tt_hh`。集成者改为调用公共`bias.section`的库段映射，补回归测试；固定范围完整格数由6改为7，原始历史数据未改。
2. `output_integrity_status_counts`统计输出尝试而非独立计划条件，含1个smoke；已保留52/64尝试完整与54个计划条件的分别表述，不把两者相除为设计通过率。此项无需改算法。

3. 检查器曾拒绝6个明确缺失输入的null哈希。集成者补上缺失记录契约：路径必须当前确实缺失，后来出现则拒绝复用。634个现有文件（含新增调用的库段映射实现）与6个缺失路径均保留，重跑检查退出0；实际历史失败和缺失检查没有删除。

未确定项：旧45点实际`whold`及缺失快照中的默认值、无源实现仍无法确定；FS冷hh重试无完整正式输出。JSON的3条unresolved记录保留；修正后的压力表另有5格没有本集合内完整指定边界。历史summary的PRBS结果未经独立重算。此交付不构成全仓库覆盖或物理上电资格。
