# TX 数字前级

## tx_word_remap

串化器的 500 MHz（支路 2 的 ÷4）和 1 GHz（支路 3 的 ÷2）分频器上电状态不确定。相对 250 MHz 字时钟，共有 4 × 2 = 8 种状态。每种状态只把字内的位按固定方式重排，眼图不受影响：

- 相邻两位 (2j, 2j+1) 始终一起移动；
- 两个半字各自用同一种 4 对置换。

8 张置换表由 SPICE 测得（`analog/tx/serializer/tb/clock_states`，6 个压力工况 × 3 个观测节点完全一致），见 `tb/data/serializer_state_permutations.hex`。

模块在并行输入侧预先做逆置换，使 `data_in` 的 bit0 最先发出。输入 `state = {c500[1:0], c1g}` 由启动状态检测器给出（待实现）；输出寄存一拍，运行在 250 MHz 字时钟域。

```bash
iverilog -g2012 -s tb_tx_word_remap -o /tmp/remap.vvp digital/tx/rtl/tx_word_remap.sv digital/tx/tb/tb_tx_word_remap.sv && vvp /tmp/remap.vvp
verilator --lint-only -Wall --top-module tx_word_remap digital/tx/rtl/tx_word_remap.sv
```

testbench 从项目根目录运行（`$readmemh` 用相对路径），检查"调序 + 实测置换 = 原序"。尚无综合/STA；250 MHz 下只是 16 个 4 选 1 加一级寄存器。
