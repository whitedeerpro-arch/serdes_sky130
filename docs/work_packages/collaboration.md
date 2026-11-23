# 协作、资源与接手

长期执行规则见[工作流](../status/workflow.md)，技术决定见[架构决定](../status/architecture_decisions.md)，任务顺序只在[执行计划](../status/prelayout_plan.md)维护。本页只登记实际开工范围、仿真资源和短交接。技术主线归Fable；Codex承接工作组织、基础设施、局部实现和复核。历史记录中的Claude署名与当时分工保留，不据旧署名另开技术路线。

## 开工与共享工作区

开工先读current.md、计划、对应模块、最近协作记录和`git status --short`。在本页写具体文件/任务范围再改共享文件；没有永久模块禁区。未提交改动先核对归属，不能代为清理或提交；只暂存自己审阅过的路径/段落，不`git add -A`，不reset/stash/checkout他人进行中文件。提交前检查cached diff；不得把HEAD当成与脏工作区相同的输入。

跨执行器交付用[工作包](README.md)，必须给定输入身份和可编辑范围，结果由集成者独立复核。是否派发子agent以当前会话的明确授权为准；保存可外发工作包不等于已经授权自动并行执行。

## 仿真资源

全机ngspice≤4。依[架构决定第9条](../status/architecture_decisions.md)由集成者按主线分配，撤销旧固定2+2叙述。开跑前同时查登记和实时进程；`pgrep -x ngspice | wc -l`只反映当时占用，不能代替互相登记，也不能假定日志里“已归还”仍有效。内存/MC按[实测规则](../verification/statistics.md#执行续跑与成本)。

一次登记包含：任务/执行者、具体可写文件、campaign与输入身份、worker、时限/终点、启动/暂停/归还状态、续跑命令与下一步。临时借用先说明，不抢占或终止他人的进程；没有记录为仍有效的明确配额就先与集成者协调。

## 历史交接

11-09至本次整理前的完整约定、临时队列、名额借用与追加记录已迁入[协作历史](../history/collaboration_20261109_20261113.md)。最后的PLL叶单元/端点回灌记录保留，其中提到的工作是否结束须结合实际campaign和进程核对，本次文档整理未代为停止或恢复任何任务。旧H4、旧4bit ISF与未提交布局不因日志中出现而自动恢复。

## 活跃登记与交付（自2026-11-13整理后追加）

- 2026-11-20 / Codex / 展示与归档：状态、文档导航、系统图和本地工作台已刷新，旧波形可从原路径读取。使用 0 个 ngspice worker。Bias/LDO v2 的进行中源码沿原工作区交接。[整理记录](../history/workbench_refresh_20261120.md)

- 2026-11-13 / Codex / 工作流整理：范围为README、AGENTS导航、docs的目标/计划/状态入口与历史迁移、工作台资料目录和导出；0仿真，不修改DUT/RTL/原始结果/采用参数；具体产物与核对见[整理记录](../history/workflow_reorganization_20261113.md)。本条不声明其他执行者名额空闲。下一工程动作见计划M1-LOOP；实际仿真领取另行登记。

后续每项只追加一段“任务—可写范围—资源—状态—交付/阻塞—下一动作”，不把当前模块数字复制到日志。停止工作前标明仍在跑的任务与续跑身份；完成后归还名额。

- 2026-11-15 / Codex / bank鲁棒优化研究交付：`docs/design/vco_bank_optimization.md` 给出全局/局部不确定性、实际校准量词、功能/噪声约束、Pareto与ε预算、S/α/最低位宽参数；上游模型与统计尺寸设计来源已引用，本机MOS/无源/VAR/失配模型快照归档，未推定SS×hh联合出现率。固定上一轮14叶/7局部条件穷举560组合；12个研究筛选切片均保留，不插值或新跑NG。98%全开C保留/最小步长不低于原对照的切片含11组、4不劣点，JG≤1.5的示例选择为Wbit1.5/2/4/8/16µm；不是规格/良率/实际校准通过或采用尺寸。数据/图/索引均为 `vco_bank_optimization`，结果在 `results/analog/pll/vco/bank_optimization/` 追加，catalog明确绑定最终身份；较早重复导出只改图标注/留边，数值未变。
  公共工具 `robust_sizing.py`、离散非凸不劣与最低宽度测试已补；16项Pareto/宽度、电容换算/导出与文档检查通过。独立支配矩阵复核12切片、ε预算选择与560组宽度，归档输入/模型/汇总/图哈希通过。采用电路、规划与已安装版图均未改，未提交/清理共享工作区。全程本任务0NG，无后台任务或名额待归还；其他执行者进程未触动。具体后续实际bank/ring/MC仍按项目PHY支撑队列承接。

- 2026-11-15 / Codex / bank鲁棒优化抽象：范围为新增共享Pareto/宽度参数化工具、固定叶数据穷举分析、`docs/design/vco_bank_optimization.md`、独立数据/图/索引及模块导航。读取上一轮14叶/7条件的冻结结果，不改电路、尺寸采用项、规划或原始仿真；0NG。核对MOS与无源角的模型身份，区分角点覆盖与联合概率、全局偏差与局部失配、硬件尺寸与逐芯片校准。先给不依赖假设出现率的目标/约束和二维参数，再用有限实测目录求局部不劣集，绝不将旧码AC代理标成已重新校准或统计良率最优。

- 2026-11-15 / Codex / bank开关分配：所有者提出按电容位权分配Ron，并提醒快振荡器接大电容、慢振荡器接小电容。新增 `layout_cap_unit/switch_allocation.py`、独立结果/索引与融合报告分配段落，固定读取r6的135条件码表与9块矩形规划，不改采用DUT/规划或旧结果。比较总W31µm的等比例、小位优先和大位优先分配及原W46.5µm对照；真实SVT叶DRC/LVS/电容提取后，在固定相位DC1.5V做局部AC并按理想互连合成32码。明确振荡器快慢不等于NMOS快慢，补SS热ll与SF冷ll。实时NG0，领取最多2worker，全机≤4；仅短卡，结果不作环振/噪声资格。

- 2026-11-14 / Codex / LDO减容：范围为新增 `analog/ldo/tb/cap_sizing/`、独立smallcap候选与局部版图/文档，不改r4采用网表和其他进行中文件。计划最多2个ngspice worker；启动前实时查询为0个。先基准DC/AC与候选压力点，按完整终点续跑，再对入选候选补PVT/噪声/启动及物理面积；原布局保持可追溯。此项由所有者明确要求解决电容面积，属于当前供电局部迭代。

- 2026-11-14 / Codex / LDO减容资源调整：短筛已结束，完整局部PVT当前2个NG；实时全机也仅这2个。追加1个串行worker用于r4/b32的启动、负载阶跃与独立噪声，任务合计最多3个，全机仍≤4，留1个空位；每次开NG前继续查全局。54pF候选已发现PSRR不足，不采用；候选与原r4分开，旧参数门槛未放宽。

- 2026-11-14 / Codex / LDO减容最终局部验证：70pF/Rhv1k组合完成1215DC/255AC，核心PEX压力点虽过34dB但仅约0.1dB余量；同70pF调整Rhv到2k的短筛明显改善，现补其自身PVT/启动/噪声/PEX。原理图PVT与动态最多各2worker，最后阶段任务总上限4、全机≤4（开跑前无其他NG），逐任务结束即归还；无整机PLL长仿真。候选按实际参数分别命名，不把旧结果转给新参数。

- 2026-11-14 / Codex / LDO减容交付：独立b32_h2（70pF；Rhv2k/32pF、Rcas31.25k/16pF、Cout4pF）完成自己的1215DC/255AC、三工况6启动/6噪声/3阶跃、6个核心电容PEX压力点；核心与4/16/32pF叶DRC0/LVS/端口通过。新源码、物理候选、固定数据清单与对比图见docs/design/ldo_smallcap.md、config/ldo_smallcap_evidence.json、analog/ldo/layout/variants/smallcap_pdk/。54pF失败和70pF/Rhv1k窄余量历史保留。已记录FS人工±4mA/1ns峰1.984V，不接受该快卸载边界；当前PLL仍按原r4集成记录，后续先核实际负载/宏回灌。所有本任务NG均结束，当前占用0，全部名额归还；未提交/清理其他工作区改动。新增与相关检查26项通过，diff检查通过。

- 2026-11-14 / Codex / 70pF LDO失配：范围为新增cap_sizing/mismatch.py及对应MC结果、smallcap模块失配记录；不改DUT尺寸/采用状态。全机实时ngspice为0，领取最多2worker，先完整PDK的抽样/seed复现小样本，再TT与FS热ll局部MC，逐样本27°C选码后保码检查DC/PSRR/双注入PM；PNP和HV模型盲点明确保留。按固定seed/chunk/源快照续跑，不覆盖减容历史结果。

- 2026-11-14 / Codex / 70pF LDO失配交付：campaign `results/analog/ldo/smallcap_mismatch/20261113T172749.615910Z`，seed70、chunk4、完整PDK，TT/FS热ll各16样本完成；每样本扫64码后保码检查3负载DC与10mA PSRR/双注入PM，32个受检样本均过本轮门槛。每工况另1个名义记录、1个首样本重跑；重跑标量及完整AC谱复现，跨样本变化确认。详细范围/统计限制在docs/design/ldo_smallcap.md，哈希与固定汇总在results/catalog/ldo_smallcap_mismatch.json。首轮TT两样本开发运行保留，未并入统计。当前全机NG为0，本任务2名额已归还；未改DUT或当前PLL采用状态。已有相关检查9项通过，新增文档链接另行复核；下一步完整MC/模型盲点补充、保码PVT及实际PLL/宏PEX按主线承接，不把本轮初筛追认为良率资格。

- 2026-11-14 / Codex / LDO周边大电容第二轮：范围为cap_sizing的参考/隔离栅RC候选、剩余大电容盘点与局部结果，不改PLL/r4/70pF已交付源。全机实时NG为0，领取最多2worker；先物理面积与RC/噪声取舍，短筛后只对入选候选补完整局部PVT、启动/噪声及必要MC/PEX。已有4pF输出快卸载失败不因本轮更改而清除；尾偏置16pF和PLL环路电容分别按其实际功能评估，不重复计入70pF。

- 2026-11-14 / Antigravity / Bandgap与70pF LDO版图重构交付：范围为 `analog/bias/layout/`（新增 `build_bias_pdk.py` 并安装至 `variants/pdk/`）及 `analog/ldo/layout/`（完善 `build_ldo_smallcap.py` 并安装至 `variants/smallcap_pdk/`），不改任何设计侧 `.spice`、`config/ldo_smallcap_evidence.json`、历史 `results/layout/ldo_smallcap/20261114_b32_h2/` 或 Codex 进行中的 `cap_sizing` 文件；全程 0 个 ngspice worker（仅运行 Magic DRC/提取与 Netgen LVS）。交付：(1) Bandgap+Bias 全套 11 个 PDK 版图单元（真实 `w=1` `res_high_po`，二维共质心 + 3D MIM 底板屏蔽，顶层 `212.4×147.1 µm`，全部 `DRC=0 / LVS=MATCH`），运行记录在 `results/layout/bias_pdk/20261114_compact_w1_v2/`；(2) 70 pF `b32_h2` 减容 LDO 紧凑核心（`248.4×210.9 µm`，保持 `vss out vin off ibias fb ref` 端口顺序）及完整 Probe/Prod 供电宏（`416.5×216.2 µm`，全部 7 单元 `DRC=0 / LVS=MATCH`），运行记录在 `results/layout/ldo_smallcap/20261114_b32_h2_macro_v2/`。任务已结束，下一步如需完整供电宏电容/RC PEX 回灌由主线按配额安排。

- 2026-11-14 / Codex / LDO周边减容续做：实时NG为0，沿用本任务最多2worker。已读取Antigravity紧凑70pF核心/宏交付，不改其已安装目录和生成器；8pF隔离栅候选用当前生成器另建 `20261114_cas8_compact`，与 `20261114_b32_h2_macro_v2` 核心在相同最差PSRR点作电容PEX比较。旧8pF试图有3个M3最小面积DRC，只有诊断提取，不能标记物理通过；新旧历史分别保留。参考缩容的噪声对照已完成，尚未采用新参数。

- 2026-11-14 / Codex / 第二轮转向叠层MIM可实现性：8pF隔离栅紧凑核心DRC0/LVS通过，但最差点电容PEX仅33.55dB（低于34dB），且长电阻使面积55,456.9µm²，高于同代70pF核心52,395.57µm²，不采用。独立新增 `layout/build_stacked_mim.py` 检查PDK MIM1+MIM2并联，2pF叶已DRC0/LVS/两层器件数通过；正扩16/32pF阵列，不改已安装生成器/版图。仍最多2个NG名额；叠层小卡/核心回灌保持独立候选及真实模型，不能借用第一层MIM资格。

- 2026-11-14 / Codex / 叠层验证资源调整：全机实时2个NG，均为本任务stack_core70局部PVT，无其他登记中的运行仿真。为叠层自身小样本MC与三工况动态/噪声追加最多2worker，本任务暂时总上限4、全机仍≤4；每任务结束立即归还。完整PDK与精简库已在叠层4模型/10条件的40张AC表逐值一致；首个核心电容PEX压力点35.93dB通过，后续记录继续绑定各自源码和提取SHA。12pF本身的2x6核心DRC0/LVS通过，最差点PEX35.06dB，但核心包围面积未降，不追认为PPA改善。

- 2026-11-14 / Codex / LDO周边第二轮交付：盘点、参考RC噪声对照及8/12/16pF真实布局比较已入docs/design/ldo_cap_area.md。12pF通过2x6 DRC0/LVS和单压力点PEX35.06dB，非工艺8pF量化，但当前核心面积未降；8pF同代核心PEX33.55dB失败且面积更大，均不替代当前16pF。独立stack_core70保持70pF数值，核心39,774.73µm²（较紧凑单层−24.1%）；自身1215DC/255AC、6核心电容PEX点、6启动/6noise/3阶跃、TT/FS各8样本MC及首样本标量/完整AC谱复现完成。完整/精简PDK40张AC表逐值相同，模型族改从实际候选/PEX推导并纳入MIM2；MC仍完整PDK。保留人工快卸载1.984V失败边界。外围1MΩ/16pF叠层完整块DRC0/LVS，面积6,226.62µm²（−39.8%），三组被动PEX小卡的1/5pF代理下截止变化约0.1%，noise与DC偏置复核完成；不是原生PLL/尾门负载资格。
  固定输入清单config/ldo_cap_area_evidence.json、数据/图docs/data/ldo_cap_area.json与docs/figures/layout/ldo/cap_area/comparison.png、索引results/catalog/ldo_cap_area.json；独立叠层DUT源和生成器已交付，当前PLL/r4/单层已安装版图未替换。原理图MC/噪声与名义核心PEX分别记录，未宣称PEX统计/噪声或完整宏通过。两份未启动参考/隔离栅PVT方案和一次未启动的旧模型族清单方案保留prepared记录，未计覆盖；早期M3最小面积布局、叠层对齐/间距及小卡noise图号错误运行保留诊断，不混入最终证据。全部本任务NG已退出，全机当前0，4名额全部归还；相关检查19项通过、身份/配置/diff核对通过。未提交或清理他人工作区文件；后续完整叠层宏回灌、M5地回流/RC与实际PLL由主线承接。

- 2026-11-14 / Antigravity / Bandgap v2紧凑重构与PLL r6k4q模拟核版图开工：可写范围为 `verification/layout/plot_mag.py`、`analog/bias/layout/`（按 `bias_pdk_floorplan_plan.png` 压紧 `build_bias_pdk.py` 并输出至 `results/layout/bias_pdk/20261114_plan_v2/` 及更新 `variants/pdk/`）、`analog/pll/**/layout/`（补齐分频/前端dummy/反馈接收/标准单元PFD/转向CP/k4环路滤波/慢尾滤波PDK单元、1:1规划蓝图及四级折叠VCO→`r6q`前端→`pll_core_r6k4q`层次组装，输出至 `results/layout/pll_r6k4q/` 与对应 `variants/*pdk/`）及对应版图文档；不修改任何设计侧 `.spice` 采用网表，不触碰 `ldo_cap_area` / `smallcap` 文件。当前全机实时ngspice为0；物理几何构建、Magic DRC/PEX提取与Netgen LVS占0个ngspice worker（后续若做局部端点回灌另行查进程并按≤2 worker登记）。

- 2026-11-14 / Codex / Bandgap电容与局部设计复核：LDO按70pF本体＋独立16pF尾滤波保容量建议，转查共享BG。范围为新增bias/tb/cap_sizing局部测试、BG模块设计/小数据/索引；不改已采用bandgap/bias_dist源码、Bias/PLL既有布局或主线采用参数。实时全机NG为0，领取最多2worker；先区分裸BG默认Cvgi10pF与分配参考2pF、真实拷贝加载，建立双环局部AC/PSRR，再筛Cc、Cvbg、Cvgi。减容候选需自己的启动/噪声边界，原有135点/MC结果只按旧源继承；PNP模型失配缺口不变。

- 2026-11-14 / Codex / Bandgap电容复核交付：共享参考先保留13pF（6＋5＋2），新增独立11pF/Cc4/Rz30k候选，未改采用DUT/版图。正确核心测量点在误差放大器输出至公共PMOS栅驱动之间，用双注入返回比；早期单输入断环17.5°排除。100条件物理MIM筛选、20条件四段物理Rz复核完成；完整/精简PDK试点10张AC表逐值相同。两物理Rz方案共12次启动到达各自OP、12份DC噪声deck共30条谱逐谱偏置核对完成；11pF核心PM最低64.23°、Vbg噪声约增2.5%，无面积收益或全角/MC/PEX资格。当前V→I轻载PM约49°属既有夹具表征，60°是本轮选型护栏，非追认旧功能失败。
  给正在进行的Bandgap v2版图重构的具体反馈：固定旧compact_w1_v2 BGamp原始LVS为四段W1/L15.48，而参考合并成一段L61.90；TT/27°C/0.9V共模小卡电阻21.155对20.014kΩ，端头使差约5.7%，冷热差约5.6–6.2%。LVS连接匹配不代表该段电气等效；后续按未合并段定尺寸并做环路PEX，本轮未触碰Antigravity生成器或安装文件。记录docs/design/bias_cap_review.md、固定输入config/bias_cap_review_evidence.json、数据/图与results/catalog/bias_cap_review.json；8项源码/测量/文档链接检查通过，配置/哈希/diff检查通过。全部本任务NG已退出、全机实时0，2名额归还；无后台仿真或待续跑任务，未提交/清理他人改动。

- 2026-11-14 / Codex / M1-LOOP及M2/M4入口核对：范围为 `analog/pll/top/tb/native_r6/` 启动错误/续跑身份/测量复核、必要公共锁定测量与测试、新增局部运行和PLL模块文档；M2动态TX及M4噪声/失配只先核实际接口和既有输入，不恢复旧4bit扫描。保持带隙/LDO和Antigravity进行中全部版图不变。开工实时NG为0，本项最多2worker；先TT固定源/真实偏置短deck及成本检查，未确认锁定前不扩全角或接完整TX长跑。所有运行显式终点/冻结输入，辅助kick/预充保留既有边界，不作为从零启动资格。

- 2026-11-14 / Codex / M1短窗与M2/M4复核交付：修复native_r6两处Path拼接错误，新增固定输入campaign.py及公共短窗/缺沿保护和32周期、320ns工程评分。TT/ext码9的固定campaign `results/analog/pll/top/native_r6/20261114T111428.008068Z` 完成1ns冒烟（38.20s）及100ns短窗（534.15s），保存40–100ns，末20ns平均2.01063GHz、Vctrl1.090–1.233V；反馈翻转但时长不足，未报锁定。旧16周期/60沿读数是诊断，项目评分在主线导出的engineering_lock；旧r5 TT/ext、hv两条完整1.5us波形离线评分均保持≥320ns，仅作测量器交叉核对。
  M2确认当前v3只需b0单2GHz有效输入，低频端保留负载须明确接法；沿用完整TX/RTL/位映射测量链，未运行当前r6动态TX。M4旧r5/4bit噪声与MC脚本不转资格；新增135个best-code Kvco下的名义CP/LF敏感度，不含实际控制导纳/延迟、CP/LF PVT、随机噪声或MC资格。交付docs/design/r6_mainline_review.md、docs/data/r6_mainline_review.json、results/catalog/r6_mainline_review.json及两张图，31项测量/续跑边界/时钟回归/文档检查通过，固定输入和diff检查通过。
  四点1.2us方案另存 `results/analog/pll/top/native_r6/20261114T113012.162249Z` prepared记录，未启动、不计覆盖；下一次执行先补单点TT长窗，按小时量级成本设置逐工况timeout，再扩FS热hh/SS冷hh/SF冷ll，成立后释放M2。全部本任务NG已结束，全机实时0、2名额归还，无后台仿真或待续跑进程；未改DUT、采用参数或进行中版图，未提交/清理他人改动。

- 2026-11-14 / Codex / M1持续锁定续做：先单点TT/ext码9，独立0.6µs完整预充捕获记录，仍按32周期/320ns合同评分；若保持不足则明确未通过，不缩短门槛。保持原4ps步长/PDK/参考与辅助边界，逐工况timeout7200s。实际开工NG为0，领取最多2worker：1个用于TT闭环，另1个可用于当前r6控制导纳等直接支撑；M2先准备同deck接口与RTL边界，待对应闭环点成立才运行。可写native_r6测试/新增完整TX原生测试与公共测量/模块文档，不改带隙/LDO/PLL采用参数或他人版图。

- 2026-11-14 / Codex / 续做运行身份补记：M1当前 `results/analog/pll/top/native_r6/20261114T113638.473219Z`，命令 `uv run python analog/pll/top/tb/native_r6/campaign.py --resume <该目录> --workers 1 --timeout 7200`；源和deck已冻结，不改其引用的clock/spice/project等文件。第二worker为 `ctrl_load/r6.py --resume results/analog/pll/vco/ctrl_load_r6/20261114T114148.278533Z --timeout 1800`，50MHz的0/5/10mV三档与±10mV DC局部卡，前两档已完整，5mV读得C约0.632pF、同频本底/响应0.031%，尚待其余点。20MHz的0/10mV独立方案 `results/analog/pll/vco/ctrl_load_r6/20261114T120140.285322Z` 只prepared，须等50MHz任务归还该worker后才启动；均为ring＋四30fF buffer及真实慢尾滤波代理，不是完整前端plant或相噪资格。
  同deck完整TX静态短probe已prepared在 `results/analog/tx/native_r6_loaded/20261114T114706.961960Z`（新增 `analog/tx/input_register/tb/native_r6/loaded_probe.py`）；时钟0V探针桥来自真实b0，单BG＋TX本地拷贝、定宽电阻、现extra5/WT16/R240与完整驱动/外围；执行器会检查明确父级M1的工程锁定，未成立不启动NG。当前尚未运行该probe；后续静态短加载也不能报动态TX或持续加载锁定通过。新增相量提取 `src/serdes_flow/spectral.py` 与续做分析器 `verification/analysis/r6_lock_confirmation.py`，相关新检查已通过；长窗结果出来后按明确路径导出并更新模块入口。上述两worker均仍属本任务，未归还；不触碰他人版图。

- 2026-11-14 / Codex / 局部卡与接口准备更新：50MHz campaign已完整结束，分析 `20261114T120907.461093Z`；5/10mV得到631.866/631.906fF、G约3µS，激励本底/响应≤0.032%，±10mV得到Kvco746.207MHz/V（只在声明的ring/四30fF代理上）。已将同一第二worker转给 `ctrl_load_r6/20261114T120140.285322Z` 的20MHz0/10mV；M1原worker仍在0.6µs求解，两worker未归还。
  初始M2全定宽方案只通过了静态端口核对；进一步实际几何发现TX100/120/133Ω低于单只2p85的137.6Ω端头，不能采用。该prepared目录保留诊断、从未运行。新方案 `results/analog/tx/native_r6_loaded/20261114T121315.849279Z` 保留M1冻结的PLL/BG定宽模型，TX按原完整台的通用PDK转换，bench内独立子电路名共存，实例/节点与电路尺寸不变。独立端口检查51个include/793实例均无缺失或端口数错误；实际展开TX时钟74只电阻/驱动6只电阻长度均为正（最短约2.16/2.12µm），仍待父级TT合格后启动自己的冒烟/短加载。未用端口检查替代电气通过；M1源/步长和进行中版图均未改。

- 2026-11-14 / Codex / 0.6µs与当前运行交接更新：M1 `20261114T113638.473219Z` 已完整结束（3174.52s，分析 `20261114T123020.985284Z`），末200ns约−9.90ppm、固定2GHz格点TIE峰峰2.154ps、ref/UP/DN末20ns各5沿；合同合格保持288ns不足320ns，不报锁定通过。改用独立 `results/analog/pll/top/native_r6/20261114T123336.086796Z` 补0.8µs，同DUT/4ps/预充，从零时刻重算，命令 `campaign.py --resume <该目录> --workers 1 --timeout 9000`；该worker仍在运行。
  20MHz卡 `20261114T120140.285322Z` 已完整（分析 `20261114T124103.871464Z`），C632.279fF/G0.491µS；与50MHz无激励记录的共同前史逐点相同。原第二worker转到局部加载 `results/analog/tx/native_r6_loaded/20261114T124239.166630Z`，命令 `loaded_probe.py --resume <该目录> --exploratory --timeout 2400`，1ns冒烟已完整（165.5s），120ns静态probe在跑。该模式只要求母本最后32周期窗合格，保留 `contract_passed=false` 和288ns保持不足，用于直接接口校准，不释放M1/M2、不作为完整动态或持续加载锁定资格；原0.8µs主线仍须满足320ns。此前未运行的M2准备保留诊断；最终夹具还修正channel保留理想RLC（只对analog DUT转换PDK电阻），以此明确目录为准。
  另在两任务切换空位完成1份被动变容噪声卡 `results/analog/pll/vco/varactor_noise/20261114T123118.337085Z`：TT27C、Vgate1.55/Vwell1.166、W5.2/L0.5/vm4有非零耗散导纳但noise为零；同deckRC参考的1MHz–1GHz噪声/4kTReY约1。最终仅重做分析至 `analysis/20261114T123607.110808Z`，首轮低频ReY数值消减导致过严校验、首次分析变量遗漏保留诊断；未改波形/PDK。具体局部反例列入I-05，不宣称总相噪失败。报告docs/design/r6_lock_confirmation.md与固定数据/索引已记录0.6µs状态；0.8µs和加载结果完成后再更新。当前仍占本任务2worker，未归还；无DUT/采用参数/他人版图修改。

- 2026-11-14 / Codex / 0.8µs运行中断恢复：原交互驱动会话返回143，driver和NG均消失，原attempt无execution.json/loop.raw、保留日志无求解错误；读取cgroup时OOM计数0，SIGTERM来源未定位，不当作失锁/功能失败。已在该attempt追加独立session_interruption.json说明（未伪造execution.json），同campaign按冻结身份续跑缺失工况至 `tt_v1800_t27_tt_ext.r1`。恢复采用本项目维护脚本已使用的setsid/nohup独立会话：driver PID文件 `driver_20261114T130800Z.pid`、持久日志同名.log（当前PID90298；NG子PID90322，仅用于当时定位，实时以文件/进程查询为准）。本任务仍2worker：恢复的M1与原M2静态加载；M2仍由原交互驱动运行，当前进程正常，不能重复开跑。完整终点仍800ns、timeout9000、门槛不变；旧中断保留，后续按NG健康与实际终点判定。

- 2026-11-14 / Codex / 局部交付与失配初筛：M2静态加载 `20261114T124239.166630Z` 已完整，37次字计数采样均按0–7循环、无错误步进；仍是探索接口卡，非动态TX或带载持续锁定资格。20/50MHz导纳卡全部完成；变容rg噪声本地副本恢复4kTReY，AC逐值不变，20ns环振对照电压最大差约9.44e-11V，原PDK/DUT未改。M1恢复实际目录为 `tt_v1800_t27_tt_ext.r2`（先前记录r1为准备判断，按实时目录纠正），detached驱动仍在运行。
  本任务仍最多2worker，其中1个M1；另1个改作新增 `analog/pll/vco/tb/mc/r6_pilot.py` 的TT局部8样本失配，固定码9/Vctrl、ring＋四30fF及真实BG/慢尾，复制明确CG母本快照，不改母本。完整tt_mm PDK、seed6/chunk4、24ns终点、每块续跑，另含名义点与首样本重跑核对；只初筛局部频散，不能计全PLL、全角/重校准或良率资格。输出独立campaign，NG总占用仍≤2；不改M1冻结依赖和进行中版图。

- 2026-11-14 / Codex / M4局部失配完成：campaign `results/analog/pll/vco/mismatch_r6/20261114T133455.717022Z`，分析 `analysis/20261114T140001.113809Z/summary.json`；8/8完整24ns、名义点及首样本复跑完整、同种子频率/尾偏置逐值相同，名义点与明确CG基线同窗口一致。频散读数记ungraded，不计良率/闭环/重新选码资格。旧prepared `20261114T133445.538445Z` 未执行、已由后者取代。两块每追加样本约246MB，成本已更新统计文档。第二worker已结束并归还；本任务现仅保留M1的1worker（NG90322，实时另查），其0.8µs detached同campaign仍运行。全部局部M2/CG/噪声/MC已结束，等待M1实际终点后统一更新当前入口；未修改冻结依赖/采用DUT/版图。

- 2026-11-14 / Codex / 本轮最终交付：M1 `20261114T123336.086796Z/tt_v1800_t27_tt_ext.r2` 完整至800ns，3889.62s、退出0无求解错误；工程评分TT/ext码9保持480ns通过，本轮固定导出 `results/analog/pll/top/lock_confirmation/20261114T141616.726063Z/summary.json`。与600ns共同40–590ns的七节点最大差均0；旧保持288ns不足不改写，SIGTERM attempt按中断保留。固定汇总同时绑定M2静态37次计数、20/50MHz导纳、原/修正变容噪声卡与短振荡对照、TT8样本失配及名义/复跑；导出器与公共测量源码另有归档。报告、当前状态、计划及工作修订同步，仅增单TT点证据，不改任何采用DUT/版图参数或全PVT/启动/噪声资格。
  本任务所有NG已结束，实时全机NG为0；M1最后1名额归还，无本任务后台driver或待续跑进程。41项相关检查已通过，最终文档/哈希/差异检查另复核。仅修正了新分频器版图README的生成器相对链接，未改其版图/生成器。下一步按主线承接FS热hh/SS冷hh/SF冷ll，TT先加载后持续锁定与真实字时钟边界，再动态TX；r6 ISF/噪声预算及扩样本/选码窗口仍开放。

- 2026-11-14 / Codex / 最终核对完成：41项相关检查通过，末次文档链接检查通过，固定数据所有输入/归档SHA256一致，工作修订TOML解析及单TT/全PVT状态区分检查通过，目标文件diff无空白错误；最终图已检查。实时NG/本任务driver均为0，无遗留后台任务。未提交或清理共享工作区其他改动。

- 2026-11-14 / Codex / 眼图展示：所有者请求查看眼图。0NG，仅从明确的当前完整TX MOS45索引读取TT及FS低压热角动态记录，复用完整追踪采集器验证输入/执行/位映射，新增 `verification/plotting/tx_current_eyes.py`、对应小数据及两行三节点眼图；不将静态r6加载卡画成动态眼图，不改DUT/既有结果。范围限定理想2GHz源、256bit、PDK R tt、无噪声瞬态，先展示可追溯的现有证据。

- 2026-11-14 / Codex / 眼图展示完成：新增当前完整TX的TT/FS热低压×串化器/焊盘/远端六面板，全部256bit轨迹、训练相位对齐、1UI=250ps；原45点索引/summary/输入边界/波形/执行身份及测量重算一致。图为 `docs/figures/tx/ingress/tx_current_eyes.png`，来源 `docs/data/tx_current_eyes.json`，重绘脚本 `verification/plotting/tx_current_eyes.py`。没有启动NG或扩报r6动态资格；模块与图目录已加链接。

- 2026-11-15 / Codex / 电容融合可实现性：所有者指出2×2µm单元的融合/DRC/LVS及截止频率问题，范围为新增 `src/serdes_flow/cap_fusion.py`、独立融合几何/局部AC卡、`docs/layout/capacitor_fusion.md`及来源索引；不改采用DUT、已安装版图/他人生成器。先核同端点/同控制域、PDK面积周长与尺寸偏差、工具尺寸限制，独立检查VCO同bit一块MIM＋原指宽开关；再比较固定电容及电阻/MOS共享。实时NG0，本任务最多2worker且全机≤4，仅短局部AC/被动分析，无整机长仿真；新候选有独立参考/映射和寄生，不靠放宽LVS属性当等价。

- 2026-11-15 / Codex / 融合任务细化：已读取实际9块镜像规划（包括非方形2×4.24、2.6×6.56、4.6×7.56），不改规划生成器/图。独立5块融合卡DRC/LVS及7条件×32码×3频点AC完成；按规划实际矩形及固定宽度的主C补偿长度另做7个叶单元DRC/LVS与TT局部AC。所有者随后要求了解图中Q及W缩小影响，第二支撑转为新增 `layout_cap_unit/switch_q.py`：固定4.6×7.56矩形、比较1.5/.75/.5µm每逻辑单位，实际合法指宽/指数组合并保留AD/AS及C矩阵，7局部角DC1.5V AC，最多2NG。Q为该端口Im(Y)/Re(Y)，不是整环Q或相噪资格；已有整bank与规划图的33需分口径，Coff17.2暂为规划目标。

- 2026-11-15 / Codex / 开关器件支撑：所有者询问Ron及埋沟管。继续同一融合任务，新增 `layout_cap_unit/switch_devices.py`，不改DUT；读取官方器件说明，区分LVT、native与埋沟概念。对同4.6×7.56矩形、W4µm/nf8比较SVT/LVT(L.15)、native3(L.5)、native5(L.9)，先实际PDK几何DRC/LVS，再六条件DC导通/关断漏电和2GHz端口AC，最多2NG、全机≤4；是局部短卡，不启动整机或自动采用新管型。

- 2026-11-15 / Codex / 电容融合与Q交付：独立5块融合物理卡 `results/layout/capacitor_fusion/20261114T170626.683363Z`，实际9块规划矩形叶 `results/layout/capacitor_fusion_plan/20261114T171404.593215Z`，全码AC `results/analog/pll/vco/cap_fusion/20261114T170701.032370Z`（最终只修导出解析至 `analysis/20261114T170901.913605Z`，没有重跑/覆盖仿真），开关宽度 `results/analog/pll/vco/switch_q/20261114T171936.279601Z`。融合可实现但主C相等不代表寄生/全角等价；旧参考的属性错误单独保留，不放宽LVS。4.6×7.56µm块0.50µm/u开关在TT/FS热的Q约5.78/2.24，Con有取舍；17.2fF仍是规划目标。
  器件替代最终采用四种均为4指×1µm、总W4µm的可用分箱，原先nf8/.5µm native冒烟无有效模型及前期接触层/地回路M2诊断保留。有效campaign `results/analog/pll/vco/switch_devices/20261114T173619.595987Z` 完成四叶DRC/LVS与六局部条件DC/AC；LVT的Ron仅小幅改善，native长L/漏电不适合直接替换本bank，非全PVT/失配/噪声资格。
  报告 `docs/layout/capacitor_fusion.md`、固定数据/索引 `docs/data/capacitor_fusion.json` / `results/catalog/capacitor_fusion.json`，最终追加汇总 `results/layout/capacitor_fusion_review/20261114T173909.811076Z/summary.json`。模块/状态/问题入口已链接，采用DUT、工作修订及他人规划/版图未改。11项公共换算/电容导出/文档检查通过，所有固定输入/输出/分析源哈希核对通过，目标diff无空白错误；全码七条件三频点均单调但不扩报原生环振资格。所有本任务NG/驱动均已结束，实时NG0，两名额归还；没有后台任务，未提交或清理其他工作区改动。后续融合/折指/换管型分别按对应窗口、匹配、噪声与切码边界交付主线复核。

- 2026-11-15 / Codex / 开关分配交付：固定campaign `results/analog/pll/vco/switch_allocation/20261114T175639.407250Z`，分析 `analysis/20261114T175835.510673Z`，导出 `switch_allocation_review/20261114T175847.318722Z`，数据/索引 `vco_switch_allocation.json`。原W46.5对照与三份W31µm候选使用原9块矩形；14个不同SVT叶DRC0/LVS属性和实际尺寸通过，7条件×2频点的32码理想互连代理均单调。小位优先相对等比例减宽在SS热hh原码3的G降低约63%，但SS热ll原码16增加约49%；保留候选，不采用激进分配或扩大环振/相噪资格。候选尺寸最终为每单位2.2/2/1.2/1/.75，初始0.625µm指宽量化被精确核对拒绝；前期体接触M2同网浅缺口及单指诊断准备均留原目录，不计通过。生成器只增可选地回流参数，默认行为和已安装版图未变。
  10项电容换算/导出检查及文档链接检查通过；冻结输入、14叶几何日志、7条件完整输出、两频点单调性和固定汇总SHA256独立复核通过，目标diff无空白错误。所有本任务NG/driver已结束，实时NG0，2名额归还；未提交、清理其他改动或更换采用参数。详细结论/适用边界在融合报告的“按实际选码分配开关宽度”，后续按主线实际bank/ring窗口与噪声约束承接。

- 2026-11-15 / Codex / PLL 版图审阅交付：范围为 PFD、VCO/buffer、÷8/轻 dummy、反馈接收器、LF 与顶层规划；LDO/Bias/CP 版图未改。各模块有 layout/README.md、review.md 和固定 catalog；原型、独立清理候选、波形及数值失败留在 results/layout_review/pll_20261115/。PFD、VCO、接收器、LF、÷8 已分模块提交，目录/边界注册/总入口另作整理提交。LAYOUT-PLL-DIV-RC-01 标注疑点待版图核查，全量 RC 分支按暂停交接，不续跑、不扩大扫描；FS RC 完整异常波形的驱动回执缺失单列，未伪造 execution.json。所有本任务 ngspice/driver 已结束，实时 NG=0，无后台任务或占用名额；其余既有未提交改动保留。

- 2026-11-15 / Codex / 四模块阶段验收与清理：六份现行几何重新 DRC/LVS/端口检查通过，215 份固定证据哈希核对通过；记录在 docs/layout/pll_acceptance_20261115.md。撤销错误大环和依赖规划共 11 个文件，独立 r6 叶单元保留。清理前既有未提交工作 414 文件的分类及逐项清单见 docs/history/worktree_inventory_20261115.md。仅提交本轮范围，其他改动保留；divider 全量 RC 继续暂停，无新 ngspice 仿真或后台任务。

- 2026-11-17 / Codex / 继续审阅提交：验证工具与 LF 已分批提交；新版 LF 七点 AC 完整、28 组 100 ns 预充筛查通过，未提取新 RC。r4/r5/CMOS 几何独立 DRC/LVS 通过，r5/CMOS 生成器重建身份匹配；固定旧波形重算 19＋59 份，r5 冷角 RC 失败及旧 hh/ll 标签未应用/include 未冻结的限制保留。新 bench 冻结身份、补无源角与双极性检查，尚未运行新 MOS45/MC。sync2 新旧几何身份不同，未移植旧通过结论。结果追加 results/layout_review/pll_pending_20261117/，入口 docs/layout/pll_pending_review_20261117.md；LDO/Bias/CP 未审阅，旧 divider RC 仍暂停，本任务 NG/driver 已结束，无后台名额占用。

- 2026-11-17 / Codex / 本轮收尾：dabbd8f、b350157、e19cd36、84a53f7 分别提交工具、LF、新接收器/CMOS 候选与旧训练清理；完整工作区 350 项测试通过，570 份固定证据哈希核对通过。剩余 409 个未提交文件（49 修改/360 未跟踪）按目录记录于 docs/history/worktree_review_20261117.md 与 results/catalog/worktree_inventory_20261117.json。sync2 身份差异及 r5 冷角 RC 失败仍开，LDO/Bias/CP 未验收，原 divider RC 分支暂停，无本任务后台进程。

- 2026-11-17 / Codex / 仓库维护交付：dc60735 归档 29 个源码运行产物与两份失效 PLL 草案，六组相同内容改相对别名，撤下 28 个冗余占位；bc4c3df 整理导航/旧状态入口并保留历史。supervisor 波形改显式路径导出，源码产物审计 0。完整工作区 350 项测试、导航 18 项、两种 RTL 波形模式通过；历史导入 40 MAG 可读，570 份既有 PLL 证据及工作修订哈希不变。明细见 docs/history/repository_maintenance_20261117.md 与 results/catalog/repository_cleanup_20261117.json。剩余 347 个未提交文件（39 修改/308 未跟踪）保留待分别审阅；无新模拟仿真/后台资源占用，divider RC 仍暂停。
