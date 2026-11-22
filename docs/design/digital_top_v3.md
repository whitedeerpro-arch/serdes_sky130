# 统一精简数字顶层宏（`serdes_digital_top_v3`）

> **当前修订**：`serdes_digital_top_v3`（RTL：[digital/pnr/rtl_v3](../../digital/pnr/rtl_v3/)，流程：[run_unified_v3_pnr.py](../../digital/pnr/run_unified_v3_pnr.py)，签核交付物：[variants/hd_pnr_v3_unified/serdes_digital_top_v3](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/)）。
> **关键数字**：单宏芯片面积 **353.70 × 323.70 µm = 114,493 µm²（0.1145 mm²）**，较 4 独立块 v2 基线合计（185,359 µm²）缩减 **−38.2%**；标准单元 5,392（−13.6%），总布线长 142.85 mm（−18.4%），利用率 79.0%，集成 2,614 个去耦单元（59.35 pF）与 35 个天线二极管；**3 角 OpenRCX 签核 STA（全部 6 个时钟域）100% MET**（`tt_025C_1v80` setup `+1.818 ns` / hold `+0.134 ns`，`ss_100C_1v60` setup `+0.011 ns` / hold `+0.086 ns`，`ff_n40C_1v95` setup `+2.056 ns` / hold `+0.050 ns`，全部 `TNS = 0`），**OpenROAD DRT = 0、Antenna = 0、Cardinal Pin Region Violations = 0（249 信号引脚）、Magic full DRC = 0、Netgen LVS = MATCH**。

## 架构与多速率时钟域

`serdes_digital_top_v3` 在保留全部 4 个外部 250 MHz 根时钟端口的前提下，将 SerDes 四个数字子系统整合为单个紧凑 SKY130A `sky130_fd_sc_hd` 宏，并复用单个 `rx_word_map`：

| 子系统 | 时钟域（频率 / 周期） | 综合单元数 | 综合面积 (µm²) | 架构优化要点 |
|---|---|---:|---:|---|
| `pll_control_top` (5-bit VCO) | `ref_clk` (250 MHz) → 内部同步 ÷4 `pll_clk_div4` (62.5 MHz / 16.0 ns) | 704 | 8,221.6 | 保持墙钟定时一致，内部控制域 ÷4 后以最小面积映射 |
| `tx_ingress_control` | `tx_word_clk` (250 MHz / 4.0 ns) | 47 | 783.3 | 全上升沿单周期捕获，`word_ready` 按高低字节复制以控制扇出与压摆 |
| `rx_word_map`（共享） | `rx_word_clk` (250 MHz / 4.0 ns) | 37 | 797.0 | 单实例同时馈送对齐/FIFO 与 CDR，消除重复采样重排逻辑 |
| `rx_word_host_shared` (`rx_word_align16` + `rx_async_word_fifo_core`) | `rx_word_clk` (250 MHz) ↔ `host_clk` (250 MHz) | 2,018 | 30,270.3 | 写侧满判比较器与写使能副本按对拆分（`r_gray_w2_m` / `w_gray_p1_m` / `w_ready_nxt_2a..3b`，每路扇出 ≤ 2）；`host_error` 在双触发器同步器后单拍寄存 |
| `rx_cdr_loop` (`bbpd_window_vote` + `cdr_phase_frequency` + `pi_step_commutator`) | `rx_word_clk` (250 MHz) → 内部同步 ÷2 `cdr_clk_div2` (125 MHz / 8.0 ns) | 1,774 | 22,530.4 | 物理位宽裁剪（17-bit `frequency_q`、23-bit `phase_debt_q`）；`s2_delta_q` 一级流水 + 2 级并行进位选择饱和累加器 + 零延迟 `debt_ge1_r`/`debt_adv_r` 影子寄存器 + 无加法器补码质量窗两拍评估 |
| **顶层合计（含胶合/缓冲）** | **4 根时钟 + 2 同步分频生成时钟** | **4,700** | **64,538.1** | — |

## 物理实现与基线对比

| 指标 | 4 独立块 v2 合计 | 统一精简宏 v3 | 变化 |
|---|---:|---:|---:|
| 芯片面积 (µm²) | 185,359 | **114,493**（353.70 × 323.70 µm） | **−38.2%** |
| 标准单元数 | 6,241 | **5,392** | **−13.6%** |
| 核心利用率 (%) | 62.7（加权） | **79.0** | +16.3 pp |
| 总金属布线长 (mm) | 175.10 | **142.85** | **−18.4%** |
| 集成去耦单元 / 电容 | 5,842 / 198.85 pF | **2,614 / 59.35 pF** | 紧凑填充 |
| 天线二极管 / 违例 | 0 / 0 | **35 / 0** | 0 违例 |
| OpenROAD DRT / Magic full DRC / Netgen LVS | 0 / 0 / MATCH | **0 / 0 / MATCH** | 100% 洁净 |

方向性引脚规划（共 249 信号引脚，0 越区违例）：南侧面向模拟核心（西→东：`PLL Analog [22]` | `TX Analog [21]` | `RX Analog [63]`），西侧 `PLL Host Cfg + rst_n [29]`，北侧 `PLL Status [21]` | `TX Host [19]` | `RX Host FIFO & Align [29]`，东侧 `RX CDR Cfg/Status & Telemetry [45]`。

## 3 角 OpenRCX 签核 STA（全 6 时钟域）

所有工艺角使用对应 OpenRCX 寄生规则（`nom` / `max` / `min`）提取 SPEF 后做全传播时钟 STA，全部时钟组 `setup_tns = 0.0 ns`、`hold_tns = 0.0 ns`：

| 工艺角 | 全局 Setup WNS (ns) | 全局 Hold WNS (ns) | `ref_clk` (250M) | `pll_clk_div4` (62.5M) | `tx_word_clk` (250M) | `rx_word_clk` (250M) | `cdr_clk_div2` (125M) | `host_clk` (250M) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `tt_025C_1v80` | **+1.8176** | **+0.1343** | +2.7485 / +0.3111 | +2.8457 / +0.2861 | +1.8960 / +0.2986 | +1.8176 / +0.2555 | +2.6550 / +0.4326 | +1.8942 / +0.3751 |
| `ss_100C_1v60` | **+0.0112** | **+0.0863** | +1.3864 / +0.2032 | +1.9914 / +0.0863 | +0.3104 / +0.1680 | +0.0692 / +0.3768 | +0.0112 / +1.0222 | +0.1471 / +0.5816 |
| `ff_n40C_1v95` | **+2.0559** | **+0.0496** | +3.0093 / +0.2461 | +3.2433 / +0.1721 | +2.1363 / +0.2560 | +2.0559 / +0.1292 | +3.1943 / +0.2799 | +2.1175 / +0.2265 |

*注：各时钟列格式为 `setup WNS / hold WNS (ns)`；`ff_n40C_1v95` 全局最差保持路径为 `host_clk` 异步复位移除检查（`+0.0496 ns`，MET）。*

## 行为回归验证

使用 `iverilog -g2012` 在当前 `digital/pnr/rtl_v3/` 源码上通过全部 4 组回归：

- **`tb_pll_control_5bit_v3`**：PASS（5-bit VCO `code 31 -> 0` 在 17,188 个 `ref_clk` 周期锁定，旧 16,384 超时正确报 `FAULT 4`）。
- **`tb_rx_cdr_closed_loop_v3` (+300 ppm)**：PASS（400,000 UI 闭环实测 PI LUT，`lock_ns = 18.99 µs`，`wraps = 61`，`19,936` 字 0 错字 / 0 缺口 / 0 滑移，峰值误差 `22.84 ps`，RMS `9.00 ps`，`locked = 1`，`limited = 0`）。
- **`tb_rx_cdr_closed_loop_v3` (−300 ppm)**：PASS（`lock_ns = 23.10 µs`，`wraps = 61`，`19,936` 字 0 错字 / 0 缺口 / 0 滑移，峰值误差 `22.82 ps`，RMS `9.21 ps`，`locked = 1`，`limited = 0`）。
- **`tb_serdes_digital_top_v3`**：PASS（4 子系统联合验证：PLL 423 周期锁定 `vco_code=18`、TX 预热与 A/B 流水、RX `offset=11` 对齐与异步 FIFO 60 字 0 错、CDR 跨 `arst_n` 纪元复位持续跟踪且 PI 选通严格独热）。

## 交付物与适用范围

- 交付物位于 [digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/)：`.def`、`.gds`、`.v`、`_pg.v`、`.png` 与 [summary.json](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/summary.json)。
- 适用范围：3 角 STA 覆盖 SKY130A `sky130_fd_sc_hd` `tt_025C_1v80` / `ss_100C_1v60` / `ff_n40C_1v95` 与对应 OpenRCX 寄生规则；顶层与模拟核心对接后的片级电源网压降（IR drop）与模拟-数字端口寄生耦合待顶层集成阶段验证。
