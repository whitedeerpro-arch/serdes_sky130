# TX 字入口调序与有效控制

`tx_ingress_preprocessor` 将组合调序接到既有有效字控制器，数据不增加寄存拍。未 ready 且许可时在下降沿锁存映射状态；ready 期间冻结状态。首次 ready 的同一下降沿可锁存状态，下一上升沿捕获使用该映射。`mapping_valid` 丢失经 guard 在下降沿生效，B 标签照常排空；异步复位清映射及标签。输入均属于 PHY 字时钟域。

原 `tx_word_remap` 接口和上升沿寄存行为保持，八张表只在同文件的 `tx_word_remap_comb` 中保留一份。组合核放在同文件以保留原有单文件编译方式；文件名 lint 提示在该模块局部抑制。

## 验证

在仓库根目录运行：

```bash
iverilog -g2012 -s tb_tx_word_remap -o /tmp/remap.vvp digital/tx/rtl/tx_word_remap.sv digital/tx/tb/tb_tx_word_remap.sv && vvp /tmp/remap.vvp
iverilog -g2012 -s tb_tx_ingress_preprocessor -o /tmp/preprocessor.vvp digital/tx/rtl/tx_word_remap.sv digital/tx/rtl/tx_ingress_control.sv digital/tx/rtl/tx_ingress_preprocessor.sv digital/tx/tb/tb_tx_ingress_preprocessor.sv && vvp /tmp/preprocessor.vvp
verilator --lint-only -Wall --top-module tx_word_remap digital/tx/rtl/tx_word_remap.sv
verilator --lint-only -Wall --top-module tx_ingress_preprocessor digital/tx/rtl/tx_word_remap.sv digital/tx/rtl/tx_ingress_control.sv digital/tx/rtl/tx_ingress_preprocessor.sv
yosys -Q -T -p 'read_verilog -sv digital/tx/rtl/tx_word_remap.sv digital/tx/rtl/tx_ingress_control.sv digital/tx/rtl/tx_ingress_preprocessor.sv; hierarchy -check -top tx_ingress_preprocessor; proc; opt; check -assert'
```

原调序测试按实测正向置换表恢复 8 状态共 512 字。新自检按同一外部置换表验证全部 8 状态的单比特及混合字，覆盖首次捕获、组合直通、运行中映射冻结、有效位丢失及重新许可、排空、空泡和复位；`WARMUP_FALLS=1` 和 2 分别通过 211 和 227 项。两个 lint 通过；Yosys 0.9 默认参数结构检查 0 问题。

## 边界

映射表来自旧 r2 实测；当前 v3 与新模拟入口所需映射仍须通过完整 SPICE 动态点确定。该交付不是 v3 或物理 STA 签核，不实现 CDC、映射有效信号或 clock_good 的产生、物理驱动 blank；未运行 ngspice。
