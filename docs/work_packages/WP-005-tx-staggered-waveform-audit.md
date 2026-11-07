# WP-005：实际字时钟下的首级字流与保持复核

## 任务与权限

做只读的原始波形审计，输出小数据与一页结论。不要修改 DUT、测试台、共享库、规格、模块状态或原 campaign。ngspice 配额 **0**；不要启动任何仿真、联网或另派 agent。不要提交、reset/stash 或切分支。

只写 `verification/work_packages/wp005_staggered_waveforms.py` 与 `docs/work_packages/deliveries/WP-005/`。先读本包、[通用交付约定](README.md)、仓库 `AGENTS.md`。不必通读项目，也不负责决定电路尺寸。

## 固定输入

- 主 campaign：`results/analog/tx/staggered_ingress/20261106T202607Z`。其 `plan.json` 指定 6 条件、40 ns、4 ns 预热。使用该目录的保存 deck 与 `execution/` 源码快照，不以当前可变工作区源码代替历史分析版本。
- 理想匹配时钟对照：`results/analog/tx/staggered_ingress/20261106T200647Z`，36 ns，无预热。这是不同测试边界，不混成同一个网格。
- 启动失败对照：`results/analog/tx/staggered_ingress/20261106T202119Z`，只有 TT，36 ns，无预热。保留首字失败；未运行条件记 missing。
- 边界与接线说明：`docs/design/tx_word_capture.md`、`analog/tx/input_register/spice/word_capture16_staggered.spice`、`analog/common/cml_mux/spice/cml_lowov_cells.spice`。
- 通用读波形/交越：`src/serdes_flow/spice.py` 的 `Waves`、`src/serdes_flow/clock.py` 的 `edges`。不要另写 raw 解析器或交越算法。

若主 campaign 尚未完整，保留已存在结果并报告 partial，不启动补跑。不用“最新一次”或 `/tmp` 指针定位输入。

## 机械步骤

1. 为读取的 plan、summary、保存 deck、实际 raw、使用的执行快照及本脚本记录 SHA256。检查 plan 条件无重复，summary 条件集合与计划一致；检查执行源码快照与 plan 中对应哈希。真实偏置和 PDK R 的接线由保存 deck 确认。
2. 每个原始波形检查全部数值有限、时间单调、最后时间达到对应 plan.stop_s。成功退出和文件存在都不能代替完整性。所有缺失/失败保留，不能补零或删除。
3. 主 campaign 从 `sp-sn` 的实际零交越取 A 下降沿和 B 上升沿。首个受检 A/B 分别约 7.015/9.015 ns，每 4 ns 重复，共 8 字。不要用延迟后的 CMOS clk 作为 MUX 选择边界；不要拟合位序或搜索最佳相位。理想旧波形缺 sp/sn 时，只允许按保存 deck 的同源关系从 clk/vdd 重建，并注明推导。
4. 对字 k、lane 0–7 取 A 选择沿后 1 ns 的 `z[i]p-z[i]n` 符号；lane 8–15 取 B 选择沿后 1 ns 的同一 `z[i-8]`。按 lane 原位重组，逐字比较 `A55A,5AA5,0000,FFFF,0FF0,F00F,1234,ECA7`。第 9 字 B79C 只用于最后一次后继更新。记录 8 个 expected/recovered，不能仅返回总通过数。
5. 按保存分析版本的定义，在每个 lane 所选沿前 100 ps 到后 1.9 ns，重测 Q 相对 VDD/2 的有符号最小值与转换器 CML 差分最小值，分别检查 >0.3 VDD 和 >0。将不符项列出 word/lane/时间；这些是输入保持检查，不能当作完整串化眼图。
6. B 组每个预期翻转：在 B 选择沿后 1.9 ns 内查下一字对应方向的 `h8…h15` 交越，必须恰好一次；与对应 `clk_b` 下降交越相减。缺失/多次为 fail。给出最小值的 condition/word/lane 与两交越时间，同时保留全部观测。没有孔径门槛，该间隔只能作 ungraded 诊断。
7. 重测 CMOS clk 相对 CML 选择的上升/下降延迟与周期数，和 summary 比较。允许交越插值带来的数值差（先按 0.1 ps 核对，超出写出差值），不按角平移时间。
8. 启动失败对照应独立复现首字 0000、后七字正确；把结果解释为此测试边界下首字失败，不推广为所有启动情况。若不符，报告实际结果。

## 交付与停止条件

按通用协议输出 `evidence.json`、手写 `summary.md`、`handoff.md`。`package_id=WP-005`。JSON 区分 source identity、raw integrity、word mapping、input hold、clock counts 的 pass/fail/missing，以及关闭→数据间隔的 ungraded。所有来源都用固定相对路径和 SHA256；缺失文件保留 `sha256:null,reason:"file missing"`。

脚本入口：`uv run python verification/work_packages/wp005_staggered_waveforms.py --output docs/work_packages/deliveries/WP-005`；不接受任意 campaign 自动选择。脚本之外只运行 `uv run python -m serdes_flow.work_packages check WP-005` 做交付格式检查。不要自动接受任务或改写设计完成度。

本包不证明锁存器孔径、完整 16:1 串化位序/眼图、异步 CDC、硬件 valid/flush、全45 PVT、hh/ll、失配或噪声。完成复核即停止，把任何结构或测量疑点交给集成者。
