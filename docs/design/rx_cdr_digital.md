# RX 数字 CDR 与 16 位解串

> **当前修订**：首版 RTL（[digital/rx/rtl](../../digital/rx/rtl/)，[说明](../../digital/rx/README.md)，[配置](../../config/rx_cdr.toml)）。
> **关键数字**：实际 RTL + 行为采样 plant 的 10 组 100 µs 场景（0/±100/±300 ppm、确定扰动、孔径偏移）共 199360 个字全部正确；实时 Verilator ↔ ngspice 闭环接物理读出 deser16（TT）：PI 工作中步进 0→14 码（含跨扇区 7→8）和 0→63 回卷，训练释放后 22 / 17 个 payload 字全部正确、无重新对齐。
> **主要缺口**：无综合/STA；16 UI 降速/打包在混合仿真中是行为实现；到系统时钟域的 FIFO/CDC 未设计。

## 结构

| 模块 | 功能 |
|---|---|
| `bbpd_window_vote` | 输入已降速并按时间排序的 16 个数据 + 16 个边沿样本（bit0 最早）；数据跳变时边沿等于后一数据投 +1（时钟偏晚，PI 超前），等于前一数据投 −1；输出 [−16, 16] 与跳变数 |
| `cdr_phase_frequency` | 二阶控制：频率积分器 + 相位债务；只在交接器报告 applied 后扣除实际步进 |
| `pi_step_commutator` | 只接受 ±1 码 valid/ready；细码每次变一个温度计单元；跨扇区只切零权重支路，端点恢复与新锚点建立各等保护周期 |
| `rx_cdr_loop` | 连接上述三者 |
| `rx_deserializer16` | 连续 4 个可编程训练字 0xb5e3 确定字边界；输出 bit0 最早；连续移位，不因 locked 抖动丢样本（吃 2 GHz pair 流，只用于行为闭环） |
| `rx_word_map` | 物理读出 [rx_readout_deser16](../../analog/rx/sampler/spice/rx_readout_deser16.spice) 的 32 位（8 通道 × 4 级）→ 按时间排序的 16 数据 + 16 边沿；edge[0] 和 previous_data 取自上一字 |
| `rx_word_align16` | 物理字是数据流中任意一个 16 UI 窗口；在 {上一字, 本字} 的 32 位里找训练字 0xb5e3 的位置（同一偏移连续 4 次），输出对齐字，比输入晚一字 |

控制运行在恢复字时钟域（标称 250 MHz / 16 UI），不调共享 VCO。物理路径：读出字时钟 w（PI 后时钟 ÷2 再 ÷4）→ `rx_word_map` → 投票器（不需要字边界）与 `rx_word_align16`（数据输出）。

**物理字的位映射**（结构决定，45 条件仿真核对，见 [CMOS 1:4](rx_pi_sampler.md#cmos-14-到-16-ui-字2026-11-02)）：数据输出 `<lane>_<k>`（k = 0 最新）在字内的时间位置 a0: 12 − 4k、b1: 13 − 4k、b0: 14 − 4k、a1: 15 − 4k；边沿输出与同相位、同级的数据输出配对（ae1–a0、be1–b0、ae0–a1、be0–b1），是该数据位之后的边沿。窗口起点由 ÷2 分频器、Johnson 计数器的上电状态和 PI 位置决定，是任意的；恢复时钟跟随远端频率，起点不漂移，只有分频/计数被扰动时需要重新训练。

| 参数 | 初版 |
|---|---:|
| Q 格式 | 每 PI 步 65536 |
| 比例 KP | 8192（0.125 步/次） |
| 频率积分 KI | 32（1/2048 步/控制周期/次） |
| 频率限制 | ±0.5 步/控制周期 |
| 质量窗口 / 宣告锁定 / 失锁迟滞 | 128 周期 / 连续 4 好窗 / 4 坏窗 |
| 无跳变超时 | 256 控制周期（约 1.024 µs） |
| 交接保护 | 默认 1 周期 = 4 ns |

## 已验证结果

### 长时闭环（实际 RTL + 行为采样 plant，每组 400000 UI ≈ 100 µs）

| 场景 | ppm | 首次质量标志 | PI 回卷 | 错字 / 缺口 / 滑移 | 峰值数据相位误差 |
|---|---:|---:|---:|---|---:|
| zero | 0 | 2.578 µs | 1 | 0/0/0 | 0.0146 UI |
| plus300 / minus300 | ±300 | 4.113 / 3.603 µs | 61 | 0/0/0 | 0.0412 / 0.0406 UI |
| ±300 + 5 ps 确定扰动 | ±300 | 3.601 / 3.603 µs | 61 / 60 | 0/0/0 | 0.0526 / 0.0555 UI |
| ±100 + 处理延迟 | ±100 | 4.122 / 3.610 µs | 29 / 32 | 0/0/0 | 0.0704 / 0.0725 UI |
| +300 保持 | 300 | 3.601 µs | 61 | 0/0/0 | 0.0526 UI |
| ±300 + 边沿孔径偏移 | ±300 | 3.089 / 3.603 µs | 61 | 0/0/0 | 0.1382 / 0.1377 UI |

孔径偏移压力组的峰值误差约 0.138 UI，说明固定鉴相偏移会移动数据采样中心。来源：[RX 闭环](../history/rx_cdr_closed_loop.md)、[数据](../data/rx_cdr_closed_loop.json)。

### 物理字路径（RTL）

[tb_rx_word_path](../../digital/rx/tb/tb_rx_word_path.sv)：按上面的位映射生成读出输出的行为模型，16 种窗口起点 × 60 字（12 个训练字后接 payload），边沿逐字交替"时钟偏晚/偏早"：928 次投票与直接在比特流上计算的结果全部一致，767 个对齐字逐个等于 payload、无缺字。`rx_word_map`、`rx_word_align16` 过 Verilator `-Wall` lint。

### 实时数模联调

**物理读出版（2026-11-03，当前）。** [cosim_words.cpp](../../verification/mixed_signal/cpp/cosim_words.cpp) + [receiver_words.cir.in](../../verification/mixed_signal/tb/receiver_words.cir.in) + [mixed_cdr_words_top](../../verification/mixed_signal/rtl/mixed_cdr_words_top.sv)：模拟端为真实 PI、CTLE（输入共模 1.05 V）、采样器 ac_rk、读出 deser16；每个 w 上升沿后 100 ps 读 32 个输出，全部 RTL（`rx_word_map` → 投票 → 环路 → 交接器，`rx_word_align16`）在 w 上运行，没有行为打包。训练 10 个字后接 payload，释放训练时要求已对齐。TT、KP = 65536（快速冒烟值）：

| 运行 | TX 相位 | 时长 | PI 码 | 跨扇区（释放后） | payload | 结果 |
|---|---|---|---|---|---|---|
| live140 | 0 | 140 ns | 0 → 14，时钟 −110 ps | 7→8 约 80 ns | 22 字 0 错 | 通过 |
| boundary_tx74 | 74 ps | 120 ns | 0→1→0→63…60…63 | 0→63（回卷）约 58 ns | 17 字 0 错 | 通过 |
| live80 | 0 | 80 ns | 0 → 8 | 7→8 在最后一次读数 | 7 字 0 错 | 通过 |

释放在 51.7 ns；所有读数无未知区；没有重新对齐。PI 步进（含跨扇区与回卷）没有让读出 ÷2 分频器和 Johnson 计数器错计。另用 `--hold-controls`（PI 脚不动）在码 0 扫 TX 相位找锁定点：62.5 ps 全票偏晚、78 ps 部分偏早、≥ 94 ps 全票偏早。KP = 65536 时每字欠债最多 8 步而交接器每 8 ns 执行 1 步，投票变号后码还要走几步（压摆受限过冲）；锁定动态按生产 KP 另行验证。数据：[mixed_signal_cosim_words.json](../data/mixed_signal_cosim_words.json)，运行目录 `results/verification/mixed_signal/20261102T17*_words_*`。

**原版（2026-10-29，旧读出）。** SystemVerilog → Verilator C++ 与 shared ngspice 47 连续瞬态双向连接：模拟端为真实 PI、CTLE、采样器、CMOS 转换与 pair 重定时，数字端运行上述 RTL。真实 CMOS 电压 ≤ 0.54 V 判 0、≥ 1.26 V 判 1（随 VDD 按 0.3/0.7 缩放）。RTL 控制位经 50 ps 发射延迟、20 ps 边沿、两级真实 CMOS 反相器驱动 PI。192 UI 内相位更新 5 次，恢复字 1200/1337/146e/15a5/16dc 全对。快速接口测试用 KP = 65536，生产 KP 不变。来源：[实时联调](../history/mixed_signal_cosim.md)，运行入口见 [verification/mixed_signal](../../verification/mixed_signal/README.md)。

## 适用范围

- 长时闭环的采样是行为 plant（用 PI 实测曲线），不是 100 µs 晶体管仿真；5 ps 是确定扰动幅值，不是随机抖动。
- 原版实时联调中 16 UI 打包和 pair 读取（每 500 ps）是 C++ 行为实现；物理读出版去掉了这一层。两版都只有 TT、理想 NRZ 源、无频偏/噪声，时长不足以触发 locked。
- RTL 只做过 Verilator lint 与 yosys proc/opt/check，没有库映射或时序。

## 待解决

- 物理 16 UI 降速：读出 [rx_readout_deser16](../../analog/rx/sampler/spice/rx_readout_deser16.spice) + `rx_word_map` / `rx_word_align16` 已有并接入实时联调（TT）；长时闭环（行为 plant）仍用 pair 流；联调只有 TT、无频偏。
- 综合与 STA（I-16）。
- 系统时钟域弹性 FIFO、空闲补偿（I-15）。
- 鉴相零点校准（I-23）。
