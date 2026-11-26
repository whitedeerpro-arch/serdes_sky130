# 统一精简数字顶层宏（`serdes_digital_top_v3`）

> **当前修订**：`serdes_digital_top_v3`（**v3.1 门级网表优化与 RTL 缺陷清零版**；RTL：[digital/pnr/rtl_v3](../../digital/pnr/rtl_v3/)，流程：[run_unified_v3_pnr.py](../../digital/pnr/run_unified_v3_pnr.py)，签核交付物：[variants/hd_pnr_v3_unified/serdes_digital_top_v3](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/)）。
> **关键数字**：单宏芯片面积 **338.10 × 307.40 µm = 103,932 µm²（0.1039 mm²）**，较 4 独立块 v2 基线合计（185,359 µm²）缩减 **−43.9%**（较 v3.0 进一步缩减 **−9.2%**）；标准单元 **4,932**（较 v2 −21.0%、较 v3.0 −8.5%），总布线长 **128.60 mm**（较 v2 −26.6%、较 v3.0 −10.0%），核心利用率 **75.0%**，集成 2,606 个去耦单元（**65.94 pF**，较 v3.0 +11.1%）与 33 个天线二极管；**保持时间缓冲器零巨型 `clkbuf_16`**（`hold_clkbuf_16 = 0`，较 v3.0 的 328 个彻底清零），复合单元 `mux4_2 = 88`；**3 角 OpenRCX 签核 STA（全部 6 个时钟域）100% MET**（`tt_025C_1v80` setup `+1.7151 ns` / hold `+0.2184 ns`，`ss_100C_1v60` setup **`+0.0740 ns`** / hold `+0.1105 ns`，`ff_n40C_1v95` setup `+2.0432 ns` / hold **`+0.1249 ns`**，全部 `TNS = 0`），**OpenROAD DRT = 0、Antenna = 0、Cardinal Pin Region Violations = 0（249 信号引脚）、Magic full DRC = 0、Netgen LVS = MATCH**。

## 架构与多速率时钟域

`serdes_digital_top_v3` 在保留全部 4 个外部 250 MHz 根时钟端口的前提下，将 SerDes 四个数字子系统整合为单个紧凑 SKY130A `sky130_fd_sc_hd` 宏，并复用单个 `rx_word_map`：

| 子系统 | 时钟域（频率 / 周期） | 综合单元数 | 综合面积 (µm²) | 架构优化要点 |
|---|---|---:|---:|---|
| `pll_control_top` (5-bit VCO) | `ref_clk` (250 MHz) → 内部同步 ÷4 `pll_clk_div4` (62.5 MHz / 16.0 ns) | 686 | 8,100.3 | 保持墙钟定时一致，内部控制域 ÷4 后最小面积映射；`precharge_en`/`pfd_rst_b`/`cp_en`/`locked` 全纯寄存器直出防毛刺 |
| `tx_ingress_control` | `tx_word_clk` (250 MHz / 4.0 ns) | 47 | 783.3 | 全上升沿单周期捕获，`word_ready` 按高低字节复制以控制扇出与压摆 |
| `rx_word_map`（共享） | `rx_word_clk` (250 MHz / 4.0 ns) | 37 | 797.0 | 单实例同时馈送对齐/FIFO 与 CDR，消除重复采样重排逻辑 |
| `rx_word_host_shared` (`rx_word_align16` + `rx_async_word_fifo_core`) | `rx_word_clk` (250 MHz) ↔ `host_clk` (250 MHz) | 1,859 | 29,574.6 | 解锁 `mux4_2`（88 例，减 168 单元且 0.000 ns SS 损失）；主 `arst_n` 异步复位 + `!word_online`/`!host_online` 同步清零（零衍生 FF 异步复位）；`rx_word_align16` 32 个控制/偏移/候选 FF 全部显式复位防 X 传播 |
| `rx_cdr_loop` (`bbpd_window_vote` + `cdr_phase_frequency` + `pi_step_commutator`) | `rx_word_clk` (250 MHz) → 内部同步 ÷2 `cdr_clk_div2` (125 MHz / 8.0 ns) | 1,774 | 22,530.4 | 物理位宽裁剪（17-bit `frequency_q`、23-bit `phase_debt_q`）；`s2_delta_q` 一级流水 + 2 级并行进位选择饱和累加器 + 零延迟 `debt_ge1_r`/`debt_adv_r` 影子寄存器 + 无加法器补码质量窗两拍评估 |
| **顶层合计（含胶合/缓冲）** | **4 根时钟 + 2 同步分频生成时钟** | **4,522** | **63,717.4** | — |

## v3.0 → v3.1 门级网表优化与 RTL 缺陷修复

针对 v3.0 门级网表审计发现的 3 类问题，v3.1 完成了定点清理并在全流程重新签核：

1. **彻底消除 328 个巨型 `clkbuf_16` 保持缓冲器**：v3.0 在 `repair_design` 之后才对 `clkbuf_*` 设 `set_dont_use`，OpenROAD resizer 缓存了初始缓冲池并因 `dly*` 禁用而插入 328 个 `clkbuf_16`（25.02 µm²/个，浪费约 8,200 µm² 及大动态电流尖峰）。v3.1 在流程最前端即对 `clkbuf_*`/`clkinv_*` 设 `set_dont_use`（CTS 显式 `-root_buf`/`-buf_list` 仍正常使用 `clkbuf_16/8/4`），同时开放 DRC 洁净的紧凑延迟单元（`dlygate4sd1/2/3_1`、`dlymetal6s2s/4s_1`、`buf_1/2`）。后布线 `hold*` 总数由 411 降至 **140**（−65.9%），`hold_clkbuf_16 = 0`（98× `dlygate4sd3_1`、9× `dlymetal6s4s_1`、5× `dlymetal6s2s_1`、28× `buf_1..8`）；全部 131 个 `clkbuf_16` 100% 为 CTS 时钟树单元。同时修复 ECO 有用偏斜脚本中 OpenSTA 起止点取反缺陷（改用 `get_property $pe startpoint/endpoint`）。
2. **修复 2 处遗留 ASIC RTL 缺陷与启动 X 态安全**：
   - **Bug A（`pll_startup_supervisor.sv`）**：将直接馈送模拟 PLL 开关与电荷泵的 `precharge_en`、`pfd_rst_b`、`cp_en`、`locked` 由组合门控输出改为基于 `next_state` 与双拍同步 `abort_sync[1]` 驱动的纯触发器输出（`!rst_n` 异步清零至安全态 `0`，状态切换周期与原协议 0 拍偏移，门级网表确认 4 端口直接由 `dfrtp_2`/`dfrtp_4` Q 端驱动，彻底消除状态翻转与原始 `abort_async` 组合毛刺）。
   - **Bug B（`serdes_digital_top_v3.sv` `rx_word_host_shared`）**：移除数据同步器 Q 端（`word_online_rst = r_up_w[1]` 与 `host_online = w_up_r[1]`）驱动的 `negedge` 异步复位树；`u_align`、`align_prime0/1`、`payload_started`、`source_fault` 及 `fault_host`/`host_error_r` 全部改用主复位口 `arst_n` 异步复位 + `!word_online_int`/`!host_online` 同步清零，彻底消除衍生寄存器异步复位，并将 `ff_n40C_1v95` 全局保持裕量由 `+0.0496 ns` 提升至 **`+0.1249 ns`（2.5×）**。
   - **X 态安全（`rx_word_align16.sv`）**：为 `offset[3:0]`、`cand[3:0]`、`off0_a..off3_b` 及 `s2b_vtf_0` 增加主 `arst_n` 异步复位与 `sclr` 同步清零（共 32 个控制/偏移 FF），上电复位即零 X 态。
3. **复合单元映射实测取舍（`mux4_2` 保留，`fa/ha` 按 SS 时序实测禁用）**：
   - 解锁 `sky130_fd_sc_hd__mux4_2` 在 `rx_word_host_shared` 映射出 **88** 个单元，净减 168 单元 / 901 µm² 且 `word_clk`/`host_clk` SS 综合建立裕量 **0.000 ns 损失**（`+0.4156 ns` / `+0.7719 ns` 持平），予以保留（并在 ECO 中屏蔽 DRC 禁用的 `mux4_4`）。
   - 实测 `extract_fa` 映射 `sky130_fd_sc_hd__fa_2`（71 例，SS 三叠 PMOS 进位链典型延迟 `1.123 ns`）虽可减 `rx_cdr_loop` 821 µm²，但将 250 MHz `ctrl_clk` 综合 SS 建立裕量由 `+0.7655 ns` 恶化至 `−0.0765 ns`（−0.842 ns）、`cdr_clk_div2` 恶化至 `−1.0158 ns`（且 `pll_control_top` 无全加器），因此保持 `fa_*`/`ha_*` 禁用以保高速 SS 时序最优。

## 物理实现与基线对比

| 指标 | 4 独立块 v2 合计 | 统一宏 v3.0 | 统一宏 v3.1（当前） | v3.1 vs v3.0 | v3.1 vs v2 |
|---|---:|---:|---:|---:|---:|
| 芯片面积 (µm²) | 185,359 | 114,493（353.70 × 323.70） | **103,932**（338.10 × 307.40） | **−9.2%** | **−43.9%** |
| 有效单元面积 (µm²) | 105,475 | 84,871 | **73,125** | **−13.8%** | **−30.7%** |
| 标准单元数 | 6,241 | 5,392 | **4,932** | **−8.5%** | **−21.0%** |
| 核心利用率 (%) | 62.7（加权） | 79.0 | **75.0** | **−4.0 pp** | +12.3 pp |
| 总金属布线长 (mm) | 175.10 | 142.85 | **128.60** | **−10.0%** | **−26.6%** |
| 保持缓冲器总数 / `clkbuf_16` | — | 411 / 328 | **140 / 0** | **−65.9% / −100%** | — |
| 全片 `clkbuf_16` 总数 | — | 495（含 328 hold + 15 rep） | **131**（100% CTS） | **−73.5%** | — |
| 延迟单元 `dly*` / 复合 `mux4_2` | — | 0 / 0 | **115 / 88** | — | — |
| 集成去耦单元 / 电容 | 5,842 / 198.85 pF | 2,614 / 59.35 pF | **2,606 / 65.94 pF** | **+11.1% C** | 紧凑填充 |
| 天线二极管 / 违例 | 0 / 0 | 35 / 0 | **33 / 0** | −2 二极管 | 0 违例 |
| `ss_100C_1v60` Setup WNS (ns) | +0.0252（最差块） | +0.0112 | **+0.0740** | **+62.8 ps（6.6×）** | +48.8 ps |
| `ff_n40C_1v95` Hold WNS (ns) | +0.0256（最差块） | +0.0496 | **+0.1249** | **+75.3 ps（2.5×）** | +99.3 ps |
| OpenROAD DRT / Magic full DRC / Netgen LVS | 0 / 0 / MATCH | 0 / 0 / MATCH | **0 / 0 / MATCH** | 100% 洁净 | 100% 洁净 |

方向性引脚规划（共 249 信号引脚，0 越区违例）：南侧面向模拟核心（西→东：`PLL Analog [22]` | `TX Analog [21]` | `RX Analog [63]`），西侧 `PLL Host Cfg + rst_n [29]`，北侧 `PLL Status [21]` | `TX Host [19]` | `RX Host FIFO & Align [29]`，东侧 `RX CDR Cfg/Status & Telemetry [45]`。

## 3 角 OpenRCX 签核 STA（全 6 时钟域）

所有工艺角使用对应 OpenRCX 寄生规则（`nom` / `max` / `min`）提取 SPEF 后做全传播时钟 STA，全部时钟组 `setup_tns = 0.0 ns`、`hold_tns = 0.0 ns`：

| 工艺角 | 全局 Setup WNS (ns) | 全局 Hold WNS (ns) | `ref_clk` (250M) | `pll_clk_div4` (62.5M) | `tx_word_clk` (250M) | `rx_word_clk` (250M) | `cdr_clk_div2` (125M) | `host_clk` (250M) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `tt_025C_1v80` | **+1.7151** | **+0.2184** | +2.6931 / +0.3647 | +2.4779 / +0.2868 | +1.8843 / +0.2890 | +1.7151 / +0.2800 | +2.5714 / +0.4353 | +1.9358 / +0.3241 |
| `ss_100C_1v60` | **+0.0740** | **+0.1105** | +1.5991 / +0.3209 | +0.8707 / +0.1105 | +0.2418 / +0.1382 | +0.0740 / +0.2893 | +0.1448 / +1.0016 | +0.1553 / +0.5204 |
| `ff_n40C_1v95` | **+2.0432** | **+0.1249** | +2.8505 / +0.2631 | +3.0138 / +0.1736 | +2.1094 / +0.2637 | +2.0432 / +0.1622 | +3.1122 / +0.2700 | +2.2163 / +0.1948 |

*注：各时钟列格式为 `setup WNS / hold WNS (ns)`。v3.1 移除 `host_online` 衍生异步复位后，`ff_n40C_1v95` 保持裕量全部 ≥ `+0.1249 ns`；`ss_100C_1v60` 全部 6 个时钟域建立裕量 ≥ `+0.0740 ns`。*

## 行为回归验证

使用 `iverilog -g2012` 在当前 v3.1 `digital/pnr/rtl_v3/` 源码上通过全部 4 组回归及专项缺陷验证：

- **`tb_pll_control_5bit_v3`**：PASS（5-bit VCO `code 31 -> 0` 在 17,188 个 `ref_clk` 周期锁定，与 v3.0 周期零偏移；旧 16,384 超时正确报 `FAULT 4`）。
- **`tb_rx_cdr_closed_loop_v3` (+300 ppm)**：PASS（400,000 UI 闭环实测 PI LUT，`lock_ns = 18.99 µs`，`wraps = 61`，`19,936` 字 0 错字 / 0 缺口 / 0 滑移，峰值误差 `22.84 ps`，RMS `9.00 ps`，`locked = 1`，`limited = 0`）。
- **`tb_rx_cdr_closed_loop_v3` (−300 ppm)**：PASS（`lock_ns = 23.10 µs`，`wraps = 61`，`19,936` 字 0 错字 / 0 缺口 / 0 滑移，峰值误差 `22.82 ps`，RMS `9.21 ps`，`locked = 1`，`limited = 0`）。
- **`tb_serdes_digital_top_v3`**：PASS（4 子系统联合验证：PLL 423 周期锁定 `vco_code=18`、TX 预热与 A/B 流水、RX `offset=11` 对齐与异步 FIFO 60 字 0 错、CDR 跨 `arst_n` 纪元复位持续跟踪且 PI 选通严格独热）。
- **v3.1 专项验证**：确认 `pll_startup_supervisor` 周期中段拉高 `abort_async` 不产生模拟端口组合毛刺并在同步后安全进入 `FAULT 5`、确认 `rx_word_align16` 异步复位后 32 个控制/偏移/候选寄存器全零无 X 态。

### 现行 CMOS RX RTL 的独立 CDR 回归

v3.2 工作树的 PI 码递增使采样时钟延后。独立 CDR 台使用与 GLS 台相同的历史 LUT 步长，两路采样都按 CMOS 极性增加延时。以 400,000 UI 的行为时钟、±300 ppm 频偏分别回归，两点各 19,936 字，错字、缺口和滑移均为 0。下节 GLS 收据对应发布的 v3.1。复现步骤见[横向审查记录](../history/project_review_20261124.md#rtl-回归和历史版图复现)。

02:17 的独立核心复跑导入 01:22 的 v3.2 GDS，SS 建立违例位于 RX 字时钟域和 CDR 时钟域。02:31 的后续 GDS 宏级 DRC=0、LVS=MATCH，SS 的 RX 字时钟域达到正裕量，仍有 CDR 建立违例。该版最长路径从 `rx_cdr_phase_applied` 寄存器出发，经过延时单元和运算逻辑。[两版 STA 与 GDS 哈希](../../results/catalog/chip_integration_20261124.json)

## VCS SDF 后布局门级仿真（GLS）+ SVA + Verdi FSDB 签核

本机 Synopsys **VCS-MX O-2018.09-SP2** 和 **Verdi O-2018.09-SP2 PLI** 完成 1 个 RTL 参考模式及 3 个 SDF 3.0 门级模式。OpenROAD（`-threads 1`）从签核 `.def` 与 `nom/max/min` OpenRCX `.spef` 导出 SDF，每角含 12,026 IOPATH、12,489 INTERCONNECT 和 1,375 TIMINGCHECK。VCS 反标 0 报错，156 条提示对应顶层输出端口上层互连 `SDFCOM_UHICD`。[门级网表](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/serdes_digital_top_v3.v) · [运行脚本](../../digital/pnr/run_v3_gls_vcs.py) · [测试台](../../digital/pnr/rtl_v3/tb_serdes_digital_top_v3_gls.sv) · [RTL 清单](../../digital/pnr/rtl_v3/rtl_v3.f) · [GLS 清单](../../digital/pnr/rtl_v3/gls_v3.f)

| 仿真模式 | SDF 反标 / 标志 | 状态 | 同步时序违例 | 异步 FIFO 未选中体 `s1_b*` 跨越 | SVA 通过 / 失败 | PLL 模拟端口毛刺 | RX 错字 (`e0/e1`) | CDR `+300` / `−300 ppm` 峰值误差 (ps) |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `rtl_golden` | RTL 黄金 | **PASS** | **0** | 0 | 122,608 / **0** | **0** | 0 (`82 / 34`) | `21.08` / `22.84` |
| `gls_tt_025C_1v80` | `typ` + `+neg_tchk -negdelay` + Verdi FSDB | **PASS** | **0** | 13（0 X 逸出） | 122,608 / **0** | **0** | 0 (`83 / 34`) | `21.08` / `22.84` |
| `gls_ss_100C_1v60` | `max` + `+neg_tchk -negdelay` | **PASS** | **0** | 22（0 X 逸出） | 122,608 / **0** | **0** | 0 (`83 / 34`) | `24.13` / `24.19` |
| `gls_ff_n40C_1v95` | `min` + `+neg_tchk -negdelay` | **PASS** | **0** | 5（0 X 逸出） | 122,608 / **0** | **0** | 0 (`83 / 34`) | `21.08` / `22.84` |

关键签核细节与透明披露：

- **4 子系统门级实测（全角默认生产参数）**：PLL 冷启动 5-bit 粗调 4,953 拍锁定 `vco_code=26` 且周期中段 `pll_abort_async` 脉冲零毛刺进入 `FAULT 5`；TX 250 MHz 16 字捕获与 A/B 排空全匹配；RX 跨异步 `rx_word_clk` (4.000 ns) → `host_clk` (3.920 ns) 含周期背压完成 `offset=11`（83 字）与 `arst_n` 纪元复位恢复 `offset=5`（34 字）全 0 错字；RX CDR 通过共享 `rx_word_map` 在实测 PI LUT 上完成 `+300 ppm` 闭环锁定与不停机 `−300 ppm` 反向重锁（`wraps = 21/17..18`，RMS `8.98–9.79 ps`，0 非法 PI 跳变）。
- **SVA 协议断言（每模式 122,608 拍全通过 / 0 失败）**：全周期实时监测 `rx_select_a`/`rx_select_b` 严格独热且互斥、`rx_fine_b` 合法温度计码、`precharge_en`/`pfd_rst_b`/`cp_en`/`pll_locked` 零 X/Z 且零 `< 8 ns` 组合毛刺、`host_valid` 期间 `host_data` 零 X/Z、`tx_capture_valid` 期间 `tx_capture_data` 零 X/Z。
- **CDC 同步器时序检查豁免与未选中体追踪**：全片 1,375 个触发器中，仅对 **24 个明确的第一级异步/CDC 同步触发器**通过 `+optconfigfile`（`noTiming`，保留全部 SDF 延迟）关闭违例检查：PLL 异步输入首级 8 例（`_5051_`/`_5052_`/`_5059_`/`_5144_`/`_5145_`/`_5170_`/`_5171_`/`_5172_`）、RX↔Host 跨时钟域首级 14 例（`_8022_`、`w_gray_r1` `_8523_.._8527_`、`_8528_`、`_8530_`、`r_gray_w1` `_8591_.._8595_`、`_8596_`）及 `arst_n` 复位同步首级 2 例（`r_rst_s0` `_8606_`、`w_rst_s0` `_8612_`）；其余 **1,351 个触发器全部开启完整 `$setuphold`/`$recrem` 检查并确认 0 同步时序违例**。异步 FIFO 一级 4 体无条件预取触发器 `s1_b0..s1_b3`（64 例，未豁免）在异步写未选中存储体时产生 13 / 22 / 5 次预期跨时钟提示，由 Gray 指针保护的 `s1_hi`/`s1_valid` 完全屏蔽，0 X 态逸出至 `host_data`。
- **工具环境说明**：本机许可不含 `VT_VCS_XProp` 扩展，门级仿真采用 VCS 原生 4 态标准单元 UDP 传播（所有未复位寄存器初态为 `X`）；Verdi 波形已导出至 `results/digital/gls_v3_1/serdes_digital_top_v3_tt_gls.fsdb`（4.1 MB），汇总 JSON 位于 `results/digital/gls_v3_1/summary.json`。

## 交付物与适用范围

- FIFO 采用 `DATA_WIDTH=16`、`ADDR_BITS=4`。v3.1 读出固定读取 16 个存储槽，写指针更新按 16 位实现。现有 FIFO 压力台复用 v3.1 RTL 时，默认深度通过，`ADDR_BITS=3/2` 各出现存储越界和读出错误。上述两个参数以采用值作为集成边界。
- 交付物位于 [digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/)：`.def`、`.gds`、`.v`、`_pg.v`、`.png` 与 [summary.json](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/summary.json)。
- 适用范围：3 角 STA 覆盖 SKY130A `sky130_fd_sc_hd` `tt_025C_1v80` / `ss_100C_1v60` / `ff_n40C_1v95` 与对应 OpenRCX 寄生规则；顶层与模拟核心对接后的片级电源网压降（IR drop）与模拟-数字端口寄生耦合待顶层集成阶段验证。
