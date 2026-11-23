# WP-LDO-001：LDO 局部结果复核（可外发）

适合能读JSON、执行Python/bash和整理局部结论的外部agent；无需电路修改或新仿真。系统集成者复核交付后再更新模块状态。**本包不占ngspice名额。**

## 输入与范围

- `config/ldo_working_revision.toml`
- `docs/design/ldo.md`
- `docs/data/ldo_characterization.json`（明确的campaign、summary/raw/deck/execution身份，禁止按“最新运行”另找结果）
- `analog/ldo/tb/{regulation,stability,dynamic,power_switch,modes}/run.py`，仅阅读其测量定义。

结果波形在当前机器的`results/analog/ldo/`。若外部环境只有git源码/汇总，没有波形本体，则交付“汇总复核”，列出无法复核的raw身份，不能称为波形复核通过。

## 工作

1. 核对两套DC/AC各135点、双注入135点、动态36项、隔离DC45点及TT宏四模式的数量、坐标和重复/缺项。区别HV3.0/3.3/3.6V与宿主固定1.8V，不把它写成原SerDes宿主45条件全覆盖。
2. 对照所引summary SHA；选取TT、最低PSRR、最高不受控启动峰值、最大4mA下冲和无HV旁路点，核对run中的deck SHA、execution及原始输出SHA。`spice.Waves`检查finite与时间单调，再查`t_end`/窗口，列出实际波形与激励。
3. 分别摘出稳态输出、20MHz幅值/PSRR、双注入所有交越、三种阶跃、噪声积分频带、受控与不受控启动。特别说明1.892V核心峰值、约105mV压力下冲、模式切换输出中断与−18mV瞬态。
4. 查文档是否误将理想参考噪声、无源模型、独立宿主电源、失配、UVLO或真实PLL负载写成完成；不自行发明新的通过门槛。

不要启动ngspice、改DUT/工作修订、改其他agent的结论或提交git。可用`uv run python`和已有`serdes_flow.spice.Waves`读波形；脚本另存正常`.py`，避免只交一段不可重跑的shell记录。

## 交付

在`docs/work_packages/deliveries/WP-LDO-001/`交付`summary.md`、`evidence.json`及使用的采集脚本。`evidence.json`含输入哈希、逐点索引、实际边界和异常清单；没有波形本体时明确标为summary-only。正文结论先行，不记录对话过程。集成者负责电路决策、真实PLL边界、后续campaign和commit。
