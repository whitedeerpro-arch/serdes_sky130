# TX 字入口 RTL 回放激励

`verification/digital/tx_ingress_stimulus.py` 将登记边界提供的字时钟事件和输入字送入既有 `tx_ingress_control`，用 Icarus 记录组合数据、有效位和 A/B 标签，再生成 SPICE 电压源；不重新实现控制逻辑。

```bash
python3 verification/digital/tx_ingress_stimulus.py --schedule /path/to/schedule.json --output /path/to/output
```

输入 JSON 包含 `rises_ps`、`falls_ps`（从时钟初始高态开始，完整覆盖至停止时间）、按时间严格递增的 `updates`（`time_ps` 和 16 位整数 `word`）、`reset_release_ps`、`permit_ps`、`stop_ps`、`supply_v` 和原样保留的 `boundary_id`。通常复位释放为 8000 ps、许可为 12000 ps；许可同时拉高 enable 和 clock_good。每个更新必须位于一次下降沿之后 100 ps，最后一次更新 4 ns 后撤销 valid。所有时间非负且须能以 1 fs 表示，所有输入事件不得同时发生；停止时间须包含撤销 valid。调用方负责提供完整、准确的边沿和边界身份。

输出目录必须不存在；脚本创建新目录，重复使用已有目录会失败，以保留原有证据。

输出为 `generated_tb.sv`、`compile.log`、`run.log`、`trace.tsv`、`captures.tsv`、`stimuli.inc` 和 `manifest.json`，另有编译产物 `simulation.vvp`。trace 每行依次为时间 ps、十六进制 capture_data、capture_valid、ready、a_valid、b_valid；captures 在上升沿记录实际捕获的数据和有效位。trace 使用 `$fstrobe`，同一时刻的重复稳定值必须一致，否则拒绝；复位释放后的 X/Z 拒绝，之前的未知行忽略。manifest 包含输入、RTL、脚本、生成测试台和输出的 SHA256，以及捕获列表和来源。

`stimuli.inc` 包含 `Vd0` 至 `Vd15` 和 `Vguard_a`、`Vguard_b`、`Vguard_ready`、`Vguard_valid`，初始电压为零，变化以事件为中心做 20 ps 线性斜坡。负时间、同一源上时间不严格递增以及不同事件的斜坡重叠均拒绝。

使用 4 ns 字周期、3 个字 `1234`、`abcd`、`5555` 的本地数字冒烟通过：8 次上升沿捕获中依次有 3 次有效字，最后两次为空泡。该结果只验证 RTL 事件回放；不包含物理标签路径、单元库延迟、CDC、模拟时钟拟合或数据建立/保持验证。实际 probe 应另行检查时钟相位与数据时序；本次未运行 ngspice。
