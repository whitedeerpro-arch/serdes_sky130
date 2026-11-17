# WP-002：TX 字入口事实与理想选择表

你是事实提取执行者。本包给实际字捕获设计准备可复核输入；不选架构、不声称模拟时序满足。工作目录 本仓库根目录，命令用 `uv run python`，遵守[工作包约定](README.md)。

## 固定输入

- `analog/tx/serializer/spice/serializer16_retimed_lowov.spice`
- `analog/common/cml_mux/spice/cml_lowov_cells.spice`
- `analog/common/cml_mux/spice/cml_mux2.spice`
- `analog/common/cmos_to_cml/spice/cmos_to_cml_data.spice`
- `analog/common/devices/spice/cmos_dff_reset.spice`
- `analog/common/devices/spice/cmos_logic.spice`
- `analog/tx/serializer/tb/native_clock/run.py`
- `analog/tx/serializer/tb/native_clock/r5_v3.py`
- `analog/tx/serializer/tb/clock_replay/counter.py`
- `analog/tx/clock_distribution/spice/tx_clock_counter.spice`
- `config/tx_working_revision.toml`
- `docs/design/tx_serializer.md`、`docs/design/tx_clock_distribution.md`

## 具体步骤

1. 对上述实际输入记录 SHA256。用 `rg -n` 提取根 `.subckt` 端口、`Xr1_*`/`Xr2_*`/`Xr3_*`/`Xr4_0` 实例；输出四级连接表：实例、A/B 数据对、选择时钟、输出、cell，每条带文件和行号。合并 SPICE 的 `+` 续行后再解析；找不到预期8/4/2/1实例时报告失败。
2. 理想非反相 MUX 约定：`sp>sn` 选B，`sp<sn`选A。枚举 `s250,s500,s1g,s2g` 的16种静态状态，沿实际连接递归追到 `d0..d15`，把末级 **仅在这个真值表中** 当成理想MUX。验证16个叶子恰好各一次；明确它不包含末级锁存器历史、clk→q、传播延时或模拟动态。
3. 提取实际末级 A/B 锁存器的 track/hold 时钟接线与源文件行号，说明与上一步抽象的区别。只报告可由实例接线证明的极性，不推导模拟建立/保持数值。
4. 定位当前是否有字入口寄存器：沿测试台 `d0..d15` 到 CMOS→CML 再到串化器，并列出现有静态 CMOS DFF 的端口/复位/极性和 CMOS→CML 的输入负载器件尺寸。不得把最终一级的重定时锁存器当作字入口寄存器。
5. 提取已有数据激励约定：`WORD_DELAY`、`WORDS`、`stimuli` 转换沿宽度、word更新参考边沿；区分旧 native data 路径和 r5_v3 的静态字测试。所有数字带单位和代码行号。查不到的 r5 动态字入口约定写 unknown；不要从旧版数值推定已采用。
6. 手写一页给 WP-004 的事实交接：已知数据/时钟边界、可复用单元、尚需测量的 clk→q / 输入电容 / 允许更新窗，及必须由集成者决定的时序/字延迟契约。可列候选方案名称，但不替集成者选方案或修改DUT。

## 唯一允许输出

- `verification/work_packages/wp002_tx_ingress.py`，`--output DIR`，输出连接/理想真值表和输入身份。
- `docs/work_packages/deliveries/WP-002/evidence.json`、手写 `summary.md`、`handoff.md`。

```sh
uv run python verification/work_packages/wp002_tx_ingress.py --output docs/work_packages/deliveries/WP-002
```

验收：连接计数8/4/2/1，16种静态选择叶子完整且不重复，记录实际末级锁存器接线与抽象差别，所有事实可定位。不同修订的激励分别记录，未知项不补猜值。无仿真、无电路或共享状态修改、无提交/切分支。
