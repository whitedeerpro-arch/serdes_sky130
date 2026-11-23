# 缩小边界的TX—信道—RX联合测试

`tb/loaded_link/`保留真实TX隔离buffer、预驱动和输出级、源端50 Ω、pad/封装代理、AC电容、C2 PCB、远端50 Ω和真实CTLE。

激励来自完整串化器运行的`dout`与`cmout`，在TX隔离buffer输入重建两线PWL。TX焊盘与RX输入没有理想电压源钳位。由此仍可求解驱动阻抗、信道反射、CTLE输入导纳及其相互作用；被截去的串化器/PLL和共享偏置耦合不在新电路内。

原100 fF/端负载用于对照完整串化链的边界误差。真实RX两组去掉该代理，仅保留真实门极和2 fF/端残余布线示例，RX终端替换原两只50 Ω，测试无峰化/最大峰化模式。20 fF/端输出电容仍是未来采样器代理。

这是加载联调夹具，不是已经完成采样器/CDR的芯片RX顶层。当前独立理想电源、地与偏置参考不能验证实际供电/回流隔离。

## 背靠背字流 `tb/b2b_stream/`（2026-11-03）

真实 TX r2（clock_replay 的 r2 配置：录制的 TT PLL 边沿、r2 修整、lowvt 使能驱动、真实 CMOS→CML 输入与时钟分发）发连续字流（每 4 ns 一个字、不插空：2 × aaaa、8 × b5e3 训练、payload PRBS7 字、3 个尾字）→ 焊盘/封装/AC 10 nF → C2_loss6 → RX 分裂端接到 1.05 V + 真实 CTLE（EQ3）。远端差分电压登记为边界条件 `rx_c2_far_txr2_stream_<campaign>@ctle_rc`，回放进读出测试台（采样器 ac_rk + deser16），PI 码按远端过零相位相对 `rx_c2_far_nominal@ctle_rc`（中心约码 20）选取。每个 w 上升沿读 32 位，交给 iverilog 上的实际 RTL（[tb_rx_word_replay](../../../digital/rx/tb/tb_rx_word_replay.sv)：`rx_word_map`、投票、`rx_word_align16`），检查 payload 逐字按序、无缺无重。

```bash
uv run python analog/rx/top/tb/b2b_stream/run.py all [--payload 16]   # tx -> rx -> decode -> view
analog/rx/top/tb/b2b_stream/view.sh [campaign]                       # GTKWave: TX 字 → 线 → 远端 → CTLE → 采样 → w → RTL 字 vs 期望
```

TT 结果（`results/analog/rx/top/b2b_stream/20261102T181556Z`）：PI 码 22（远端过零比参考早 12.2 ps）；16/16 个 payload 字按序正确（另 1 个尾字也正确），之前输出 2 个训练字；TX 入字到 RX 出字 16.9 ns。开环下投票一直为负（−5…−16，边沿采样在跳变之前），闭环时 PI 会往低码走。TX 14 min、RX 23 min。只有 TT、开环（固定 PI 码）、TX 与 RX 同一 TT 条件、无频偏与噪声。
