# 验证方法与结果记录

> 先分块验证，再用实际负载、电平、边沿和延迟把相邻模块衔接起来；不以"跑一次全晶体管长仿真"作为有效性的唯一判据。执行成功与设计通过分开记录。

项目任务的选择、验收、发布和交接见[工作流](../status/workflow.md)；当前结果与队列分别在[current.md](../status/current.md)和[执行计划](../status/prelayout_plan.md)。本页只维护验证方法。

长扫描出现异常耗时时，先运行 `uv run python -m serdes_flow.audit <campaign>`：区分未启动、运行中断、超时、输出截断和完整求解，并统计各类进程耗时。它不判定电路通过；原始波形按 `tran` 终点核查，旧 MC 没有终点字段时只能检查行数。轻量进度监控仍用 `serdes_flow.watch`。MC 分块恢复与样本身份见 [统计方法](statistics.md#执行续跑与成本)。

## 测试层次

| 层次 | 位置 | 关注点 |
|---|---|---|
| unit / infrastructure | `tests/`、`verification/unit_checks/` | 共享库自检、模型插值、局部电路冒烟与单元核对 |
| block | 各模块 `tb/<case>/` | 独立功能、电气范围、噪声、失配、CPEX/RCX 签核 |
| integration | `analog/pll/top/tb/`、`analog/rx/cmos_rx/tb/`、`analog/tx/sst/tb/` 等 | 相邻模块的电平、极性、脉宽、负载与后仿联调 |
| system | `verification/top_cosim/`、`verification/stability/`、`digital/pnr/` | 全链协同仿真、供电 PDN 稳定性、RTL/GLS 闭环与片级签核 |

实现视图（behavioral / schematic / extracted）是另一个维度。行为级锁定不能代替晶体管级起振或噪声验证。

### 分块衔接的常用边界

- **理想化源 + 真实负载。** 保存上游真实波形的过零时刻，理想化成有限边沿源，再接真实 MOS buffer 与负载（例如 TX 时钟分发用 PLL 边沿记录）。
- **电压记录回放。** 把上游节点电压用 B 源 `pwl(time, …)` 回放到下一级有限驱动阻抗之前（例如 RX 联调在信道远端回放逐角 TX 波形），并用原负载对照验证截断误差。
- **实测曲线行为模型。** 把同工况实测的 VCO 调谐曲线、PI 相位曲线做成行为模型，配真实 PFD/CP 或真实 RTL 做长时闭环。
- **全链与数模协同仿真。** 模拟顶层与跨宏链路由 [verify_4g_full_chain.py](../../verification/top_cosim/verify_4g_full_chain.py) / [verify_5g_full_chain.py](../../verification/top_cosim/verify_5g_full_chain.py) 分段或同 deck 联调；数字顶层与 CDR/FIFO 闭环在 `digital/pnr/` 内通过 VCS RTL 与带延时 SDF GLS 验证。

每种边界都要写明被裁掉的反向耦合（共享电源、偏置、回流），以及截断误差的验证方法。

### 边界条件管理

从别的仿真复制或推导来的激励（以下称边界条件）一律登记在 [config/boundary_conditions.json](../../config/boundary_conditions.json)，由 [serdes_flow.boundary](../../src/serdes_flow/boundary.py) 读写。

- **按 id 引用，不找"最新"。** 下游脚本用 `boundary.point_run(id, point)` 取来源 run，运行记录里写 `bc` 和激励文件哈希。新录制要么登记成新 id，要么在同一 id 下补新的工作点（已有工作点不允许改）。
- **登记内容。** 类型、上游模块与工作修订、各工作点（工况、码、Vctrl、VCO 频率、来源 run、git 版本、deck 哈希）、录制时的下游负载、处理方式、对照验证、失效条件。
- **负载签名。** 录制电压会受下游输入级负载影响。签名取下游单元中直接接在输入端口上的实例，去掉实例名和内部节点名，保留单元名和参数后做哈希；不包含这些级的输出侧负载（Miller）。回放前比较签名，不一致就拒绝运行；探索时可以显式放行，运行记录会标为 `MISMATCH (allowed)`，结论只能作为参考。
- **开跑前冒烟。** `spice.run_many` 默认先把第一个 job 跑到第一个保存点后 1 ns，确认 ngspice 无报错并写出波形，再放整批。bench 模板直接引用 DUT 内部节点（`let`、`.save`）时，换 DUT 变体最容易在这一步暴露问题。

当前登记：

| id | 类型 | 内容 | 失效条件 |
|---|---|---|---|
| `tx_clk_ideal_tt_v01` | 理想化边沿记录 | v0.1 TT 闭环 PLL 的四路时钟过零时刻，400 mVpp、20 ps 边沿；理想 CMOS 数据 | 只代表 TT；r2 的 45 条件都用它，所以 r2 的 45/45 不含源端随工况的变化（I-07） |
| `pll_r4_taps@tx_in_r2` | 电压回放 | PLL r4 前端送给 TX 分发的 8 个单端抽头，VCO 开环固定 Vctrl，5 个工作点 | PLL 修订改变；TX 分发输入级与 r2 不同 |

旧脚本（`clock_states`、`swing_trial`、`waveform_view`）仍直接读 `r2_stimuli.inc` 或按"最新"取结果，只在登记表里记录了来源，没有接入检查。

## 测试定义与测试台

- `tb/<case>/case.toml` 是测试定义，没有通用执行器。`planned` 表示尚未实现，`prototype` 表示已有探索测试但条件/视图未全覆盖。
- 测试台模板 `*.cir.in` 中的 `@KEY@` 占位符由脚本替换（模型库、工艺角、供电、温度、步长等），替换后必须没有剩余占位符。
- DUT 不内嵌理想负载、绝对路径或 `.end`。
- SKY130 测试台：把 [config/ngspice/spiceinit](../../config/ngspice/spiceinit) 复制为运行目录的 `.spiceinit`，确认日志显示 `hsa` 模式；用 `/opt/ngspice47/bin/ngspice`。
- 温度必须在 `reset` 之后设置（早期有过 `reset` 覆盖 `set temp` 的无效运行）。逐项核对日志中的实际 TEMP、供电和模型段。

## 结果路径与记录

```text
results/<analog|digital|verification>/<模块>/<测试>/<run_id 或 campaign>/
```

run_id 用 UTC 时间加引擎/工况，例如 `20261027T120000Z_ngspice_tt_001`。运行目录只追加不覆盖。

| 产物 | 内容 |
|---|---|
| `tb.cir` / 网表快照 | 实际执行的顶层网表与输入 |
| 日志 | 完整模拟器输出 |
| `execution.json` / `run.json` | 命令、版本、退出码、耗时、输入哈希 |
| `metrics.json` | 数值、单位、窗口、方法、规格与判定 |
| 原始数据 | 波形 TSV（大文件 gzip）、边沿表、扫描表 |

规则：

- 未知数值写 JSON `null`，禁止 NaN/Infinity。
- 执行状态与设计判定分开：仿真失败不能忽略；没有规格的量记为 ungraded；退出码为 0 不代表通过。
- 测量失败记为不可用，功能失败单列；未起振时频率不可用，不能记为 0。
- 失败、无效（例如超出 PDK 模型 bin）、被替代的运行保留状态与记录，单独标注，不混入验收数据。
- 长期结论写进设计文档并引用数据文件或 run 路径。

### 归档

≥ 1 MiB 的大波形按原模块/实验/run 无损压缩或归档，完整读回核对 SHA-256 后才移走原文件。索引见 [results/catalog](../../results/catalog/README.md)，维护命令见 [maintenance README](../../verification/maintenance/README.md)。

2026-10-31 起，结果目录内的大波形就地 gzip（`spice.Waves` 直接读 `.gz`）；批量处理用 [compress_waveforms.py](../../verification/maintenance/compress_waveforms.py)（跳过入库文件引用的波形、24 h 内的和运行中的目录，解压核对 SHA-256 后才删原件，清单在 `results/maintenance/compress_waveforms/`）。磁盘按固定分区划分，`/home` 只有 47 GB、`/opt` 75 GB。波形本体用 [waveform_archive.py](../../verification/maintenance/waveform_archive.py) `archive` 转存到 `/opt/serdes_archive/<同一相对路径>`，原位置换成文件软链接（先核对 SHA-256，再一次 rename 替换）；读取、续跑判断、登记边界的 SHA 校验都照常，记录文件留在原处，`verify` 检查链接，`restore <前缀>` 搬回。整个 `results/` 迁到 `/opt` 并 bind mount 回原路径的备选方案是 [results_on_opt.sh](../../verification/maintenance/results_on_opt.sh)（需 root）。已被后续版本取代的探索轮次可以删除波形本体：删除前先用脚本把需要的数提成图和紧凑数据，保留每个运行的 `tb.cir`、日志、`execution.json`、激励和汇总，并把删除清单存在提取结果旁边。登记过的边界条件录制和被代码固定引用的运行不删。

## 结构时序平衡分析

结构层面的问题先在理论层面回答，不跑电路：路径上放哪些元件，各条路径之间的时序关系能否在 45 个 PVT 点上同时成立，每类元件还能变差多少。库是 [`serdes_flow.balance`](../../src/serdes_flow/balance.py)。

- **元件是约束，不是尺寸。** 延迟 = TT 值 × 工艺系数 × (1 + α·v + β·t)，v = (VDD − 1.8)/0.15，t = (T − 22.5)/62.5。参数由实测拟合（`fit_element`，记录点数与残差），也可以直接写成目标值。复制单元用 `track` 指向被跟踪的元件，跟踪误差另给。
- **结构是路径。** 路径由 `Inst`（元件实例；两条路径上同一个 id 是同一个物理实例，没有失配）、`Fixed`（精确偏移，例如 VCO 相位）、`Knob`（对中旋钮：固定档、延迟、级数）组成。
- **关系三种。** `Skew`：两路相对位置在周期窗口内；`Sample`：数据路径被时钟路径采样，满足建立/保持；`Budget`：路径之和不超过上限（例如计数器反馈）。
- **先配平，再对中。** 旋钮只移动名义偏移，`centre` 按路径顺序逐路联合搜索、再按最差裕量细调。散布由两条路径的元件组成差决定：同类元件互相抵消，异类元件不抵消。
- **输出。** 最差裕量；每个工艺的带宽（一颗芯片只有一个工艺，带宽就是它随 V/T 的摇动）；`lambda_max`（所有元件的 PVT 变化同时放大多少倍、重新对中后仍成立）；`limits`（旋钮不动时，每类元件的 PVT 变化和延迟各能放大多少倍，以及失配能放大多少倍）。

**用于其他模块。** 把模块写成路径和关系即可，例如 RX 多相采样时钟、PLL 分频反馈、数据路径打拍。`limits` 中的"延迟可放大倍数"就是这类元件的 shrink 余量：可以换成更慢、更省电的单元，直到这个倍数用完。最紧的那条关系指出 enhance 应该花在哪里。新元件类型先拟合或给出目标值，写进结构脚本并注明来源。

历史上第一个用例是早期 CML TX 选择时钟 S0–S5 结构比较（主线现已采用 CMOS/SST 串化架构，见 [tx_sst_v4.md](../design/tx_sst_v4.md)）。

时序平衡是尺寸设计流程中的一类约束；完整流程（输入、输出、迭代、拓扑判据）见 [尺寸设计流程](sizing.md)。

## 相位噪声

ngspice 没有 PSS/PNOISE，所以用 ISF：瞬态里在噪声点注入小电荷脉冲，由前后相位跳变得到 h(x)，再和器件噪声谱合成 L(f)。当前 VCO 相噪脚本在 [phase_noise](../../analog/pll/vco/tb/phase_noise/)，公式在 [pnoise.py](../../src/serdes_flow/pnoise.py)。

- 白噪声：L = (S/2)⟨(hα)²⟩/(2πΔf)²；慢噪声：L = (S(Δf)/2)⟨hα⟩²/(2πΔf)²。α(x) 是噪声随工作点的调制（gm、Id）。
- 流程：r6 + PTAT 相噪表征脚本 [char_r6_ptat_perf.py](../../analog/pll/vco/tb/phase_noise/char_r6_ptat_perf.py)（调谐 → ISF → 器件噪声 → L(f) → Kb/Kvdd/Kvco），再由 [pll_noise.py](../../analog/pll/top/theory/pll_noise.py) 合成闭环相噪、[cdr_jitter.py](../../analog/pll/top/theory/cdr_jitter.py) 算 CDR 后抖动、[loop_psrr.py](../../analog/pll/top/theory/loop_psrr.py) 评估电源到频率的相量传递。
- 历史直接瞬态噪声核对：直接瞬态噪声 ÷ ISF 预测在 TT 理想偏置下为 0.85–1.14（差 ≤ 0.7 dB）；SF 1.65 V 85 °C R hh 真实偏置下，两随机种子平均后负载 R 为 0.90–0.98、输入管为 0.88–0.94，ISF 略偏保守（差 ≤ 0.6 dB）；DC 电流引起的频移与 ⟨h⟩ 预测差 1.4%（TT）。

三个容易出错的地方：

1. **相位覆盖。** 脉冲间隔 = K 周期 + 步进，周期误差会累积：K = 10 时 0.1 % 的周期误差就是每脉冲 5 ps（步进约 20 ps）。环比假设的周期慢时扫不满一周，⟨h⟩ 和 rms 在缺口上插值。ISF 扫描须名义覆盖 ≥ 1.25 周，缺口 > 0.08 周时报错。
2. **振幅建立。** 热、慢角振幅建立约 14 ns，过早测量会使频率偏高约 1.4 %。ISF 脉冲注入和慢灵敏度窗口均须在振幅充分建立之后开始。
3. **直流灵敏度不等于高频灵敏度。** 偏置线有去耦，VDD 到偏置线这条路只在低频起作用，FS 1.65 V 热角直流 Kvdd −782 MHz/V，20 MHz 下只有 −584 MHz/V。高频电源门槛应采用交流单音相量增益，而非直流灵敏度。

没有进预算的：变容管串联电阻和电容阵列开关的热噪声（手算约 +0.15 dB，SF 热角）。

## 失配与蒙特卡洛

工艺角管全局偏差，MC（`<corner>_mm`）管局部失配；判据分串联（每个实例都必须过）和传播（平方和），器件参数和模块预算超出都不算失败，只看系统判据。方法、样本数、修调、工具与 SKY130A 失配/电阻噪声实测边界见 [统计与蒙特卡洛](statistics.md)。

## 有效性约定

- 每次记录稳定等待时间、测量窗口、最大步长、输出采样间隔、边沿阈值。启动段与稳态分开，启动短周期不能记成随机抖动。
- 调谐曲线逐点稳定测量；快速控制斜坡只用于动态响应。Kvco 标明单位、计算点和区间（两点割线不是全频段常数）。
- 无噪声瞬态的边沿变化不能归因于器件随机噪声；有限码型零错误不是统计 BER。
- 关键弱角结果做步长复核（例如最大步长减半后波形差、错误数不变）。
- PVT 不开 Monte Carlo；统计运行另记随机种子与失配开关，先确认统计参数确实改变了实例。
- Xyce 与 ngspice 的模型兼容性、噪声方法分别验证；HB、普通小信号 NOISE 或短窗 FFT 不自动等于已验证的振荡器相噪流程。

## 离线自检与冒烟

从项目根目录运行共享库与流程离线自检（不加载 PDK）：

```bash
uv run pytest -q
```

批量 SPICE 任务通过 `spice.run_many` 默认执行开跑前 1 ns 冒烟，确认 ngspice 无报错并写出波形后再放行整批。

## 仿真成本与精简模型库

先确认器件/寄生可实现，再用局部模型定参数；长任务前量一次稳定时间、步长误差、模型加载及实际求解成本。头部写清已校准设置和观测窗口。输出只保存测量所需量；缩文件不等于加快求解。短OP/AC按角合deck，名义重复结构可比较倍数合并，但须先证明电气等价，不能直接用于独立失配样本。

`serdes_flow.model_library.build`提供显式选择器件族的名义精简库：保留完整器件文件、共有参数及原include顺序，不改模型表达式或原PDK；不自动替换任何生产测试台。统计段拒绝生成，MC随机身份未认证；自定义网表须显式给全依赖，新增使用先与完整库对照。

裁剪证明的是与输入库等价；固定多晶硅电阻的已知 AC 导数问题仍需显式选用经验证的模型修正输入，不能因精简库与完整库一致就忽略原模型问题。

2026-11-13实测（单worker、热缓存；[紧凑数据](../data/model_library_cost.json)直接链接完整结果）：

| 测试 | 完整库 | 精简库 | 等价性 |
|---|---:|---:|---|
| 四器件族CML卡，TT/SS_hh/FF_ll，OP＋20MHz AC＋2ns瞬态 | 16.53–19.21s | 1.44–1.54s | 所存DC/AC/瞬态值逐项相同 |
| 实际r6 VCO TT1.8V/27°C，K9/Vctrl1.163V，14ns/4ps单点新deck | 45.60s | 28.04s | 两端波形相同，均1.997120738GHz |

短卡加载完成时 ngspice 程序大小约 346→24 MB，为进程级测量。短卡提速 11.5–12.5 倍，VCO 单 deck 提速 1.63 倍，多工况合 deck 可摊销加载。稳定窗口、模型选点及求解器成本分别记录。全机上限为 4，执行者配额见[协作页](../work_packages/collaboration.md)。

```bash
uv run pytest -q tests/test_model_library.py
```

## 历史脚本

旧 campaign 的分析代码存放在各自的 `execution/*.txt`，路径指向已停用的原项目 `../simple_serdes`（经 `/tmp/serdes_*_campaign` 指针）。只作记录；复跑按 [AGENTS.md](../../AGENTS.md) 的说明在内存里重定向。结果目录的大波形以 gzip 存放（`spice.Waves` 直接读 `.gz`，判断用 `spice.has_waves`）。新代码写成正常的 `.py`。
