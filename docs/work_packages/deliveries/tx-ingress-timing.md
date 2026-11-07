# TX guard 映射时序可行性

默认 `WARMUP_FALLS=1`、`IDLE_WORD=0` 的 guard 在本次假设下，SS 两个库的 setup 出现负裕量；这是需要复核和改进的可行性结果，**不是设计通过或签核**。TT 库映射一次，同一网表由四个 HD 库、每输出 5/10/20 fF 分别分析；全部报告为 ungraded。

运行 `uv run python verification/digital/tx_ingress_timing.py`。结果独立追加至 `results/digital/tx/ingress_timing/<UTC>/`，索引为 `results/catalog/tx_ingress_timing.json`。归档包含 RTL、脚本、四个 Liberty、映射网表、SDC/Tcl、工具二进制哈希和版本、命令、日志及 summary；失败也保留 summary。最终为 `20261107T051940Z`（明确设置理想时钟的 slew；先前 `20261107T051848Z` 保留），Yosys 0.9、OpenSTA 2.0.17，12 组分析完成。

| 库 | 5 fF WNS / ns | 10 fF | 20 fF |
|---|---:|---:|---:|
| TT 25°C 1.80 V | 0 | 0 | 0 |
| SS −40°C 1.60 V | −0.39968 | −0.57753 | −0.94519 |
| SS 100°C 1.60 V | −0.18043 | −0.31157 | −0.59435 |
| FF −40°C 1.95 V | 0 | 0 | 0 |

这里 WNS 是 OpenSTA `report_wns`，0 表示没有负 setup WNS，不表示真实最小正裕量为零或已签核。SS 冷角 10 fF 最差路径为下降沿 ready 寄存器到 `capture_valid`；同例 `capture_data`、A/B 标签等也有 setup 违例。报告包含带 slew/capacitance 的最大/最小时序路径、unconstrained 路径、`check_setup` 和工具支持的 max/min delay、max transition 违例。旧 OpenSTA 的 `report_check_types` 不提供 max-capacitance 违例选项，故未声称完成电容规则检查；逐路径 capacitance 字段不等于完整电容规则检查。

## 约束与限制

4 ns 时钟，上升/下降 0/2 ns，输入时钟 slew 0.1 ns；数据和 valid 由下降沿发出，max/min 输入延迟 0.2/0.05 ns；enable 和 clock_good 由上升沿发出，max/min 0.5/0.05 ns。capture 数据/valid 对下一上升沿的输出延迟 max 0.5、min −0.05 ns；word_ready 的 max 为 0.5 ns。A 标签对下降沿、B 标签对上升沿的 max 为 1.3 ns，min 为 0；1.3 ns 是 SS bank 延迟约 1.176 ns 加 0.1 ns 的近似预算。setup/hold 时钟不确定度均为 0.05 ns。负载由每份 Liberty 的 `capacitive_load_unit` 换算，本次 1 pF 单位下分别为 0.005/0.01/0.02 pF。

`rst_n` 固定为 1 的正常模式不检查恢复/移除，`check_setup` 仍提示它缺少 input delay；不以此隐藏报告。OpenSTA 对这些库提示 `default_operating_condition ... not found`，工具仍生成结果，具体解释及对数值的影响需进一步核查。word_ready 未指定外部 min 输出延迟，须由接口合同补全。报告不包含真实模拟 DFF 建立/保持、valid buffer 输入电容、寄生、clock_good 产生、CDC、驱动 blank 或复位路径；1.60 V 与 1.65 V、25°C 与 27°C 不等价，四个库不代表 45 PVT。

## 驱动强度受控迭代

`20261107T052206Z` 在相同 4 库 × 3 负载上，按相同约束比较 TT 原映射和三个**未采用的网表候选**；补充 `word_ready` 的 min 输出延迟 0 ns。归档 summary 给出每组 setup 与 hold 的真实最小 slack、起点和终点；完整路径和违例在日志。四库中的 `dfrtn_2/_4` 均不存在，不能直接增强下降沿 ready/B 触发器：

- `strength2/4`：仅将 `dfrtp_1`、`and2_0`、`and3_1` 替换为对应强度 2 或 4；下降沿 FF 保持 `_1`。四库中实际引脚集合逐一比对，OpenSTA link 检查每份网表。
- `outputbuf`：在 ready、A、B 三个寄存器 Q 后分别插入 `buf_4`；ready 的原有扇出由 buffer 驱动，A 的原有 B 输入也在缓冲后。单独评估，不与强驱动替换叠加。

10 fF 示例，数值为真实最小 setup / hold slack，单位 ns：

| 映射 | TT | SS 冷 | SS 热 | FF |
|---|---|---|---|---|
| baseline | +0.19957 / +0.33369 | −0.57753 / +0.75997 | −0.31157 / +0.72415 | +0.34987 / +0.20082 |
| strength2 | +0.19957 / +0.33369 | −0.56631 / +0.75997 | −0.33292 / +0.72415 | +0.34987 / +0.20082 |
| strength4 | +0.15388 / +0.33369 | −0.90073 / +0.75997 | −0.61313 / +0.72415 | +0.33547 / +0.20082 |
| outputbuf | +0.13399 / +0.33369 | −0.41694 / +0.75997 | −0.35151 / +0.72415 | +0.30782 / +0.20082 |

SS 冷角缓冲候选的最差端点转到 `a_valid`，仍为负；增强门的输入负载使 strength4 更差。以上局部比较未解决约束，也不表示候选已被采用。每组显式设置对应库中的 operating condition，但读库时 OpenSTA 仍提示默认 operating condition 未找到；该警告和 max-cap 检查未知状态均保留，不能据此掩盖工具或库问题。候选未做物理布局、形式等价或模拟接口验证。
