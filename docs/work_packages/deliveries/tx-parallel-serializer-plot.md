# TX 并行入口到串行输出图：交付

`verification/plotting/tx_parallel_serializer.py` 从完成的动态 campaign 重算三处节点的串行检查和位映射，并生成眼图、数据和结果索引；不运行仿真。默认采集 TT 结果，追加完成的工况时显式重复参数：

```bash
uv run python verification/plotting/tx_parallel_serializer.py \
  --collect results/analog/tx/parallel_serializer/20261107T044921Z \
  --collect results/analog/tx/parallel_serializer/20261107T051545Z
```

执行前第二个 campaign 必须完成。脚本检查快照和生产者输出的哈希、manifest 与 captures.tsv 的逐项一致性、上游探针和时钟计划、运行状态、执行 deck 和波形结束时间；以实际字时钟匹配生产者捕获，再用实际半字时钟确定序列起点。`serial.check` 和 `serial.bit_mapping` 独立重算并与归档 summary 对照；不一致或缺失记入数据的 `collection_failures` 并返回非零状态。图上的眼图使用训练段相位和固定 250 ps UI；位映射诊断按其既有定义使用载荷边沿确定无序眼相位。图中每条件选取最多 64 条载荷眼轨迹，数值检查仍使用全部载荷。

适用范围：实际 capture、v3 时钟分发、完整串化器、驱动和 RLC16 远端；理想 2 GHz 输入、真实偏置及 PDK tt 电阻、计数器初态、RTL 事件模型标签。不是原生 PLL、上电、45 PVT、MC 或噪声验证。输入边界、半字保持、标签和计数器字段目前来自原 summary；此脚本独立复算的是串行检查、位映射及捕获时间匹配，不把 summary 的其他字段当作独立复验。最后一个空闲捕获的完整半字窗口超过仿真结束，不能把它视为已验证窗口。
