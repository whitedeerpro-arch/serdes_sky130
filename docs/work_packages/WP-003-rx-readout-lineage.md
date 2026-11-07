# WP-003：RX 读出 W40/W80 证据清点

你是历史结果清点执行者。本包只识别每次运行实际用了什么电路/边界和有哪些结果，不重跑仿真，不把旧证据升级成当前设计通过。工作目录 `/home/host/Desktop/workspace/simple_serdes_fork1`，遵守[工作包约定](README.md)。

## 固定输入

当前意图：`config/rx_working_revision.toml`、`analog/rx/sampler/spice/rx_readout_deser16.spice`、`analog/rx/sampler/spice/rx_readout_demux2.spice`、`analog/pll/divider/spice/cml_div2.spice`、`analog/rx/sampler/tb/readout_deser/run.py`。

仅检查以下历史根目录，以及它们目录内部的 summary、plan、实际deck、执行日志/记录与被deck引用的项目电路快照：

- `results/analog/rx/sampler/readout_deser/20261103T124408Z_ac_trim32`
- `results/analog/rx/sampler/readout_deser/20261105T195752Z_ac_trim32_realbias_rhh`
- `results/analog/rx/sampler/readout_deser/20261105T195755Z_ac_trim32_realbias_rhh`
- `results/analog/rx/sampler/readout_deser/20261105T195758Z_ac_trim32_realbias_rhh`
- `results/analog/rx/sampler/readout_deser/20261105T195801Z_ac_trim32_realbias_rhh`
- `results/analog/rx/sampler/readout_deser/20261105T211802Z_ac_trim32_realbias_rhh`
- `results/analog/rx/sampler/readout_deser/20261105T211805Z_ac_trim32_realbias_rll`
- `results/analog/rx/sampler/readout_deser/20261105T211808Z_ac_trim32_realbias_rll`
- `results/analog/rx/sampler/readout_deser/20261105T211811Z_ac_trim32_realbias_rll`
- `results/analog/rx/sampler/readout_deser/20261105T213614Z_ac_trim32_realbias_rhh`

个别路径若不存在，保留 missing 记录并继续其他目录；禁止扫描“最新”目录补齐它。

## 具体步骤

1. 展开每个根目录 `plan.json` 的 deck 条目和 summary 中实际条件；一个运行条件一行。保留只在计划、不在summary、无execution的条件。对所有作为结论依据的文件记 SHA256。
2. 用原 deck 和被其 include 的项目快照判断：MOS/VDD/T、passive库段、理想/真实参考、sampler DUT 名称和参数（含 `_rk`、rb、修调码）、readout cell。记录来源路径与原文；不凭目录名或当前源码判断历史尺寸。
3. 找到实际读出 ÷2 的 `whold` 取值：先看实例参数覆盖，再看该运行实际引用的 subckt 默认值（必要时沿 include）；也检查外层 `div_*` 参数传递。有明确记录才写40/80；无法判断写 null+原因。不要把 PLL prescaler 首级W40自动套给RX。
4. 从 deck 控制段提取目标tran结束时间和输出文件名。用 `spice.case_output(..., t_end=目标)` 或 `spice.Waves` 实查对应输出终点与有限性。原 runner 一个deck可有多个 `tran/write` 时逐项匹配，不能只看执行退出码或有文件。此包只重查完整性，不重算全部PRBS字流。
5. 摘录 summary 的 `map_ok`、`data_errors`、`edge_errors`、`words`、`capture_data_slack_min_ps` 等现有字段。标明它们是 historical_summary 结果。完整波形与零错 summary同时存在也只说明原边界；W80/理想参考不能转为W40/真实无源角证据。
6. 输出两张清单：按运行分的事实表；当前W40/真实偏置 hh/ll、6个压力条件对应的明确证据、缺失/不明或原边界不符。六条件为 TT1.8/27、SS1.65/−40、SS1.65/85、FS1.65/−40、FS1.65/85、FF1.95/−40。重复条件保留各运行来源，不静默覆盖。

## 唯一允许输出

- `verification/work_packages/wp003_rx_lineage.py`，`--output DIR`，只读提取和完整性检查。
- `docs/work_packages/deliveries/WP-003/evidence.json`、手写 `summary.md`、`handoff.md`。

```sh
uv run python verification/work_packages/wp003_rx_lineage.py --output docs/work_packages/deliveries/WP-003
```

验收：十个根目录都有条目，计划条件完整保留；每个尺寸与边界结论有历史deck/快照依据，失踪/截断不误计完成；当前意图与历史观测独立列出。输入规模过大时先报告大小和可用方法，不盲目加载所有大波形。每次只读一个raw，无ngspice、无历史修改、无提交/切分支。
