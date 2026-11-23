# TX 数字前级

## tx_word_remap

串化器的 500 MHz（支路 2 的 ÷4）和 1 GHz（支路 3 的 ÷2）分频器上电状态不确定。相对 250 MHz 字时钟，共有 4 × 2 = 8 种状态。每种状态只把字内的位按固定方式重排，眼图不受影响：

- 相邻两位 (2j, 2j+1) 始终一起移动；
- 两个半字各自用同一种 4 对置换。

8 张置换表由 SPICE 测得（`analog/tx/serializer/tb/clock_states`，6 个压力工况 × 3 个观测节点完全一致），见 `tb/data/serializer_state_permutations.hex`。

模块在并行输入侧预先做逆置换，使 `data_in` 的 bit0 最先发出。输入 `state = {c500[1:0], c1g}` 由启动状态检测器给出（模拟单元已有，原生分发联动待完成）；输出寄存一拍，运行在 250 MHz 字时钟域。上述置换表仍是原有r2边界的证据，不能代替v3＋新字入口的动态位映射。

```bash
iverilog -g2012 -s tb_tx_word_remap -o /tmp/remap.vvp digital/tx/rtl/tx_word_remap.sv digital/tx/tb/tb_tx_word_remap.sv && vvp /tmp/remap.vvp
verilator --lint-only -Wall --top-module tx_word_remap digital/tx/rtl/tx_word_remap.sv
```

testbench 从项目根目录运行（`$readmemh` 用相对路径），检查"调序 + 实测置换 = 原序"。尚无综合/STA；250 MHz 下只是 16 个 4 选 1 加一级寄存器。

## tx_ingress_control

完整字捕获/两组保持的输入保护 RTL 已实现，**数据与标签波形回放已接入[完整TX候选](../../docs/design/tx_parallel_serializer.md)，物理路径及线驱动blank仍未完成**。输入数据、`in_valid`、`enable`、`clock_good` 都已在 PHY 字时钟域；本模块不做 CDC，也不产生时钟质量或计数器相位有效判据。

`enable` 与 `clock_good` 在下降沿采样，连续 `WARMUP_FALLS` 个许可下降沿后 `word_ready` 才开放（默认1，允许值≥1）。时钟初态即使为高，没有真实下降沿也不会开放入口。`capture_valid=word_ready && in_valid`，有效时组合直通 `capture_data`，否则送 `IDLE_WORD`；没有新增数据寄存拍，数据仍由模拟入口 DFF 在上升沿捕获。上游必须满足该输入的建立/保持条件。

`a_valid` 在上升沿采本次接受标记，`b_valid` 在下降沿采已有的 A 标记。禁用时下一次上升沿的 A 变无效，上一有效字的 B 标记继续排空；不能把两者合成任意时刻同字总线的 valid。下降沿 B 寄存也避免了用上升沿 valid 寄存器直接驱动 B 透明锁存器的同沿竞争。标签路径的物理延迟仍需库映射、STA和模拟接口验证。

控制器不寄存 `in_data`。若在它之前放置已寄存一拍的 `tx_word_remap`，`in_valid` 必须同样延迟一拍，与映射后的字对齐。下述legacy preprocessor采用组合映射，当前v3实测自然位序，未采用该适配器。复位是异步低有效，停钟时不能自行检测故障；立即中止或屏蔽在飞字必须由独立驱动/启动控制处理。

A/B标签表示被接受的输入字，不应直接作为线驱动使能；空泡输出的IDLE_WORD仍可能需要发送，以维持接收端训练/跟踪。默认IDLE_WORD=0只定义数据占位，不保证跳变或字对齐；RX字对齐器当前训练字为B5E3，具体训练序列及物理输出开放时刻仍须由启动协议决定。

运行并归档证据：`uv run python verification/digital/tx_ingress_control.py`。覆盖预热1/2/3/5个下降沿、初始高态、空泡、禁用与重启、停钟和异步复位，共149项行为断言；Verilator lint、Yosys通用结构检查通过。Yosys 0.9不支持最初的尺寸强转常量，已改成整数常量位选。

`verification/digital/tx_ingress_timing.py`已做默认guard的HD库映射与OpenSTA局部可行性分析。四库、三负载及驱动/缓冲对照显示SS时序不足，候选未采用；[约束与结果](../../docs/work_packages/deliveries/tx-ingress-timing.md)。实际模拟DFF建立保持/输入电容尚未提取，库条件也不等同45 PVT，不构成STA或模拟联合签核。

## legacy r2 组合调序与入口保护

`tx_word_remap_comb`共用旧置换表；`tx_ingress_preprocessor`在未ready时于下降沿锁存mapping_state，再组合送guard，ready期间状态冻结，不增加数据寄存拍。映射失效会关闭新捕获并保留旧B标签排空。该状态语义仅用于已核实的旧r2边界，不是v3状态检测器，当前v3候选不接该模块。

`uv run python verification/digital/tx_ingress_preprocessor.py`归档旧512字、新438项行为检查、两项lint及结构检查。[集成者review](../../docs/work_packages/reviews/tx-ingress-preprocessor.md)保留适用域与复核修正。
