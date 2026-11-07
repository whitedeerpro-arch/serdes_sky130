# TX 字入口有效字控制交付

控制器提供字时钟域内的预热、空泡插入及 A/B 半字有效标签。`WARMUP_FALLS` 默认 1，要求至少为 1；连续许可的指定次数下降沿后 `word_ready` 才置位。`enable` 或 `clock_good` 在下降沿不许可时清除预热和 ready；上升沿不改变 ready。异步低有效复位清除 ready 和标签。

`capture_valid = word_ready && in_valid`，数据有效时 `capture_data` 直通输入，否则输出 `IDLE_WORD`（默认 0），不增加数据拍。A 标签在上升沿采样有效位，B 标签在下降沿采样旧 A 标签；禁用后在飞行 B 标签自然排空。标签对应不同半字流水时刻，不能视为同一时刻完整 16 位总线的有效位。

## 验证

在仓库根目录执行：

```bash
iverilog -g2012 -s tb_tx_ingress_control -o /tmp/tx_ingress_control.vvp digital/tx/rtl/tx_ingress_control.sv digital/tx/tb/tb_tx_ingress_control.sv && vvp /tmp/tx_ingress_control.vvp
verilator --lint-only -Wall --top-module tx_ingress_control digital/tx/rtl/tx_ingress_control.sv
yosys -Q -T -p 'read_verilog -sv digital/tx/rtl/tx_ingress_control.sv; hierarchy -check -top tx_ingress_control; proc; opt; check -assert'
```

Icarus 自检通过：`WARMUP_FALLS=1` 为 25 项，`WARMUP_FALLS=2` 为 32 项，共 57 项；Verilator lint 通过；Yosys 0.9 默认参数的结构检查报告 0 个问题。原尺寸强转改为整数常量位选以兼容旧 Yosys，行为不变。测试在时钟高初态检查真实下降沿前不 ready，覆盖预热、组合数据及空泡、禁用和重新许可的排空、`clock_good` 丢失、停钟、重启与异步复位。边沿后等待 NBA 更新再检查；数据没有额外寄存延迟。

## 范围与待办

输入请求和数据已在 PHY 字时钟域；此模块不是 CDC 同步器。`clock_good` 的产生、跨域与停钟检测、线驱动 blank 和立即中止在飞字、模拟捕获电路接入、库映射及 STA 均未实现或验证。时钟停止时本模块不能自行检测或更新状态。本次未进行 ngspice、电路/PVT 或完整串化链验证。
