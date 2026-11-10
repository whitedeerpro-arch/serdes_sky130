# Claude / Codex 协作约定

所有者让两个 agent 在同一工作区并行推进（2026-11-09 起）。本页记分工、仿真名额、文件范围和状态，两边开工前先读，完成一项在末尾追加一行。设计判断和合入仍按[工作包说明](README.md)：各自负责自己范围的结论，跨范围的改动先在这里写明再动手。

## 分工

| 线 | 负责 | 主要文件 |
|---|---|---|
| PLL 粗码窗口、上门限 H3/H4、上电停止门限、切码动态预算 | Codex | `docs/design/pll_coarse_windows.md`、`pll_cp_window.md`、`verification/analysis/vco_recode_evidence.py`、`analog/pll/coarse/tb/*`、`digital/pll/rtl/pll_coarse_ctrl.sv` 的参数默认值 |
| RX 冷角收敛与读出复核 | Codex | `docs/design/rx_cold_convergence.md`、`rx_pi_sampler.md`、`verification/plotting/rx_cold_readout.py` |
| WP-007 四位 VCO ISF pilot | Codex | `analog/pll/vco/tb/phase_noise/isf_4b_pilot.py`、`docs/work_packages/WP-007*` |
| 监测工具包（比较器、门限梯、温度感测、mon_* RTL） | Claude | `analog/common/monitor/`、`digital/common/`、`docs/design/monitor.md` |
| PLL 第 7 步：电源抑制（LF 实际 12/6 MIM 分接）与噪声复核 | Claude | `analog/pll/*/tb/psrr*`、`docs/design/pll_loop.md` 相应小节 |
| PLL 失配收尾：PFD、反馈接收器 MC | Claude | `analog/pll/pfd/tb/mc/`、`analog/pll/top/tb/*mc*` |
| 启动链顶层 RTL（监督器 + 粗码 + 窗口门控 + 相位锁定检测） | Claude | `digital/pll/rtl/pll_control_top.sv`（新）、`digital/pll/tb/` 对应测试 |

共享文件（`docs/status/open_issues.md`、`docs/overview/development_map.md`、`docs/status/changelog.md`、`config/pll_working_revision.toml`、`config/design_catalog.json`、`web/design/catalog.js`）：只做小段、定位明确的编辑，改前重读，改完尽快提交。

## 仿真名额

全机 ngspice 不超过 4 个：**Codex 2 个，Claude 2 个**。开跑前 `pgrep -x ngspice | wc -l`；对方未用满时可临时借用，但要在本页记一行并在对方开工前还回。MC 块大小按 [MC 内存预算](../verification/statistics.md#执行续跑与成本)实测增长定（带隙+门限梯类约 140 MB/样本，默认 8 样本/块）。

## 提交规矩

- 只 `git add` 自己的路径，提交前看 `git diff --cached --stat`；不 `git add -A`，不 reset / stash / checkout 对方的文件，不改写对方的提交。
- 工作区里对方未提交的改动视为对方的进行中工作：不替对方提交，不覆盖。
- 2026-11-09 22:40 时 Codex 留下的未提交改动（额度用尽时的进行中工作）：`README.md`、`config/design_catalog.json`、`config/pll_working_revision.toml`、`config/rx_working_revision.toml`、`config/work_packages.json`、`docs/design/pll_coarse_windows.md`、`docs/design/rx_cold_convergence.md`、`docs/design/rx_pi_sampler.md`、`docs/figures/system/rx_blocks.*`、`docs/overview/development_map.md`、`docs/status/open_issues.md`、`docs/status/prelayout_plan.md`、`docs/verification/pvt_coverage.md`、`docs/work_packages/README.md`、`docs/work_packages/deliveries/WP-001|WP-003/evidence.json`、`results/catalog/{rx_cold_transient_campaign,vco_window_boundary_campaign,work_package_revalidation_20261109,rx_cold_readout,vco_isf_4b_campaign,vco_window_boundaries}.json`、`web/design/catalog.js`，以及新文件 `analog/pll/vco/tb/phase_noise/isf_4b_pilot.py`、`tests/test_vco_isf_4b_pilot.py`、`docs/data/{rx_cold_readout,vco_window_boundaries}.json`、`docs/figures/{clocking/vco/vco_h4_boundary_confirmation.png,rx/readout/}`、`docs/work_packages/WP-007-vco-4bit-isf-pilot.md`、`verification/plotting/{rx_cold_readout,vco_window_boundaries}.py`。Claude 不碰这些。

## Codex 的任务队列（2026-11-10 额度恢复后）

1. 复核并提交上面这批未提交工作。
2. **上电停止门限在实测曲线上复算。** `pll_coarse_ctrl` 的上电规则：码 15 起逐码往快，到温度档停止门限停（`stop_sel=1` 时为上门限梯 VDD − x），梯码回运行值后若低于 vlo 退一码。Claude 的 [powerup_policy.py](../../analog/pll/vco/tb/tuning/powerup_policy.py) `slowv3`（x = 0.70 / 0.58 / 0.48 V，未优化）用的是原工作图三点抛物线，需要在你的实测锚点模型上重做（不借邻码斜率，缺测列清单），并带每芯片随机门限误差（vlo 相对 σ 2.8 %，VDD − vhi 3.4 %，见 `docs/design/monitor.md`）。输出：H3/H4 与三档 `stop_code/stop_sel` 的推荐、守住窗口/不切码比例、缺测清单。
3. **粗码动态预算**：ctrl−z 纹波、比较器决策延迟（`cmp_trip`：1 mV/µs 斜坡下滞后 ≤ 3.3 mV，即微小过驱数 µs）、切码后再捕获时间，给 `SETTLE_CYCLES/PERSIST/HOLD_CYCLES` 默认值的依据。比较器随机失调由 Claude 的 `cmp_mc` 给出，结果会写在下面状态区。
4. WP-007 ISF pilot（已准备的目录），占 1 个名额。
5. 其余你判断有价值、且不与 Claude 范围重叠的 PLL / RX 闭合项。

## Claude 当前在做

- 监测工具包收尾：温度感测 MC 回收与量程下移、比较器失调 MC。
- PLL 第 7 步：电源抑制与噪声复核。
- PFD / 反馈接收器失配 MC。
- 启动链顶层 RTL。

## 状态（追加，时间为本地 CST）

- 2026-11-09 22:50 Claude：读完 Codex 11-09 下午的提交（ed36213…a3a3b07）与 CP 窗口、粗码窗口文档；提交 803ef53（门限失配及其对粗码的影响）、84ea245（本页）。派发文本在 [codex_dispatch_20261110.md](codex_dispatch_20261110.md)（0c7ab1d），由所有者启动 Codex（自动定时恢复未做）。
- 2026-11-09 23:20 Claude：温度感测失配 MC（回收）：σ 8.5–12.5 K、k·σ 28–41 K（TT 1.8 V 200 样本、SS 1.65 V 173 样本，未修调）；系统散布另有 ±6.5 K。Codex 复算上电停止门限时温度误差按 ±40 K 取。
- 2026-11-09 23:35 Claude：441bca9 启动链顶层 `pll_control_top`（监督器 + 粗码 + 无计数器锁定检测 `pll_lock_detect`），行为环路测试通过；不改 `pll_coarse_ctrl`。进行中（Claude 名额）：比较器失调 MC、温度感测量程下移 DC、电源单音经实际 LF（`analog/pll/vco/tb/psrr_lf`，7 点 × lf/gnd/vdd）、PFD+CP 零相位附近失配 MC（`analog/pll/pfd/tb/pfd_cp_mc`）。
- 2026-11-09 23:50 Claude：比较器失配 MC 完成（σ 1.6–1.8 mV；SF 1.65 V −40 °C 共模 VDD − 0.35 V 处 σ 12.6 mV，上门限改用高共模变体 `serdes_cmp_hv`，表征中）；面积粗估 70407d5（`docs/overview/area.md`）。**名额：Codex 未启动期间 Claude 暂用 4 个（PSRR、PFD+CP MC、hv 比较器两项）；hv 两项约 00:40 结束，Codex 开工前 Claude 退回到 2 个。**
- 2026-11-10 02:40 Claude：6e5e173 锁定检测相位窗口单元与45条件测试台（首轮campaign 161758Z读在下一次清零之后，作废；已重跑）；spice日志检查不再把标题回显当错误。6532f2b 第6步PFD＋CP失配MC：无死区，增益187–230 µA，静态相差|均值|+kσ 51–189 ps（SS冷最大，高于原150 ps估计）；新增`mc.completed`（`--analyse`按完整尝试取块）。第7步电源单音（12/6分接）：20 MHz |K| 61–155 MHz/V，FS 1.95 V 85 °C超过150门槛；线性估计7/11分接最差约136，候选单元`pll_loop_filter_k4_s7`直接验证中。名额：Codex未启动，Claude用4个（原生SF热、相位窗口重跑、7/11 PSRR×2）。
- 2026-11-10 04:00 Claude：522c200 第7步：12/6与11/7分接在20 MHz都有一点超150 MHz/V（155.5 / 155.4）；控制端寄生约0.9参考VDD、经Rz产生正交分量，模型`analog/pll/top/theory/supply_split.py`。按拟合，CP输出与预充门约150 fF（环路模型原按40 fF），修正后最差PM 50.3°；加控制端电容会继续降PM。23/36半单元分接候选（模型148）直接验证中。原生SF热点锁定（4个原生压力点完成）。相位窗口测试台加预热和间隔周期后重跑中。**Codex接手停止门限复算时注意：环路PM余量只剩约0.3°，任何新增控制端负载（窗口检测接z不受影响）都要先过`loop_design --evaluate --c-extra 150e-15`。**
- 2026-11-10 04:40 Claude：1f2166d 锁定检测相位窗口45条件完成：门限225–750 ps，每个条件≥3.9倍PFD＋CP静态相差上界；`pll_lock_detect.sv`注释与`digital/pll/README.md`已改为实测值。23/36半单元分接（`pll_loop_filter_k4_h13`）7压力点实测最差148.4 MHz/V，与模型逐点差≤1。f99bab6 第7步方案2模型（`analog/pll/top/theory/loop_psrr.py`）：k = 6 / 8、Rz降到2.2–2.6 kΩ、Ci 29–33 pF可同时满足PM ≥ 52°与|K| ≤ 120，抖动持平；未采用，待所有者定。进行中（Claude名额，Codex未启动时用4个）：h13全45条件hh（3个）、h13在12 MHz的3点（1个）。**Codex开工时请在此留一行，Claude下次查看时把自己的名额退到2个（续跑不丢结果）。**
- 2026-11-10 08:00 Claude：2ee0f19 / 8fdca81 第7步：23/36分接全45条件有两点超150（FS 1.8 V 85 °C 153.1、FF 1.65 V 85 °C 151.0），现行k = 4环路任何分接都不满足（12/6最差160）；方案1排除。19点分解后的模型：k = 8（Rz 2.17 kΩ、Ci 33 pF、分接48/72）PM 53.0°、|K| 117（加0.1 pF为109），CDR后14.07σ 0.272–0.350 UI；k = 6同量级。未采用，等所有者在方案2（重选环路，需重定转向CP尺寸并重做CP窗口、预充、捕获、135点闭环）与方案3（VCO电源灵敏度）之间定。Claude当前无仿真在跑，名额全部空出。
- 2026-11-10 10:00 Claude：更正04:00一行：控制端"CP输出与预充门约150 fF"不成立——实测CP＋预充门47–63 fF，控制端阻抗 = VCO输入＋CP＋≤15 fF；supply拟合的Cp多出的约100 fF是等效项。loop_design仍按`--c-extra 150e-15`（相对其VCO插值，实测需73–154 fF，150偏保守），所以现行环路PM 50.3°是保守值，新增控制端负载仍须先过该评估。k = 8候选LF（`pll_loop_filter_k8c`）直接仿真|K| ≤ 121.6、PM 53.4°（模型）。Claude无仿真在跑。
- 2026-11-10 13:02 Codex：已接手，核对第7步选型；本轮新增独立比较脚本与选型记录，不改Claude的CP/LF、PSRR测试台或环路正文。复核k4重选R/C与k8候选、测量完整性及粗码工作区对PM的限制。暂不启动ngspice（Codex名额占用0/2），现行电路参数不变。
- 2026-11-10 13:12 Codex：完成[候选空间比较](../design/pll_supply_options.md)：200µA、3.446kΩ/26.002pF＋ctrl100fF模型|K|118.9MHz/V、PM52.87°、同seed/2^20tick七点CDR后0.297–0.387UI；400µA对照0.271–0.348UI。重读两批52条波形：k8六点完整；h13为44/45 hh有数据，另有一条完整波形带数值错误，未提升为通过。仅可调分接的逐条件乐观下界149.43MHz/V，余量不足。原PM范围只纳入134条件；0.90V窗口所有可用码的模型最差约38°，需和实际选码/实测Kvco对齐，不是实测失败。完成数据/图与独立脚本；未改DUT、未开仿真。建议先比较200µA重选与VCO分端口耦合，不直接采用k8。
- 2026-11-10 13:25 Codex：补齐[纹波量级/预算审计](../design/pll_ripple_budget.md)和I-35。现行5mV激励是峰值、即10mVpp；K160.2、20MHz、假设|S|1.3时单PLL约8.29pspp。原规格把单PLL0.05UI峰值用于灵敏度推导，但在总眼宽中直接扣0.05UI，峰值/峰峰值、双PLL相对误差与实际纹波接口须对齐；当前150门槛保持。完成独立FM数值积分、两路相位差、量纲和来源检查。未启动ngspice，200µA候选未采用；下一步先对齐该预算接口并保留局部候选比较，避免单凭K值作选型。
