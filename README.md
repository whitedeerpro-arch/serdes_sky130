# Simple SerDes

面向 SKY130 的 SerDes 电路设计，先开展 PLL 与 CML 电流舵。

最新独立实验见 [锁存器拓扑/PMOS负载与级间buffer探索](docs/cml_latch_topology_experiments.md)：已完成选角比较，尚未替换工作设计。

当前 PLL 工作修订为 [带级间 buffer 的 r3](docs/pll_buffered_pvt.md)：分频/反馈标准边界 45/45，四个约 2 GHz 原生选角均有正确 CML 反馈；SS 冷角全速 CMOS 转换仍有功能缺口。已完成 [PFD/CP/LF 选角分层闭环](docs/pll_loop_pvt.md)：12 个局部跟踪场景通过工程判据；原生 r3 仅做短时接回，尚未完成持续锁定签核。分频器尺寸与全速 CMOS 优先级见 [评估](docs/divider_size_and_clock_priority.md)。冻结 v0.1 保留；旧原理图尚未同步 r3，电路演进见 [CML 锁存器调研](docs/cml_latch_topology_review.md)。

TX 已完成 [电流舵与输出级 PVT](docs/tx_pvt.md)：近无损负载下独立输出级45/45、真实加载TX45/45有限码型功能正确，但串化器仅36/45满足裕量草案；SS/FS弱角接6dB PCB已出现错误，冷角输出使能接管也有缺口。两个实际MOS候选保留为局部实验，默认电路与冻结版本未替换。

新增 [分频buffer相位与眼图显示核对](docs/tx_clock_phase_audit.md)：TX PVT仍对应旧冻结源；r3的分频状态/极性与trim需重标定。当前2UI眼图已采用中央完整眼、左右半眼，绘图样本和指标不变。

```text
analog/
  common/
    bias/                 偏置、电流参考
    cml_buffer/           CML 差分对、电流舵、缓冲
    cml_mux/              差分2:1选择器与数据锁存重定时
    cml_to_cmos/          CML → CMOS
    cmos_to_cml/          CMOS → CML
  pll/
    pfd/                  鉴频鉴相器
    cp/                   电荷泵
    vco/                  压控振荡器
    divider/              反馈分频器
    loop_filter/          环路滤波器
    top/                  子模块集成与 PLL 闭环
  tx/serializer/          16:1串化树与输入数据转换联调
  rx/
    input/                100Ω差分端接/共模接口原型
    ctle/                 可调RC退化CTLE原型
    sampler/、cdr/、top/   后续采样器/恢复时钟/联调预留
config/                   工具、PDK 和仿真器设置
verification/
  stimuli/spice/          共享理想激励
  corners/               PVT 计划，与随机失配分开
  templates/             待填写的测试台模板
  contracts/             结果记录格式
  smoke/                 可运行的基础设施测试
docs/                     层次、接口、测试约定
results/                  按 DUT / 测试项 / run_id 归档
```

每个电路模块统一包含 `spice/`、`behavioral/`、`schematic/`、`layout/`、`tb/`。
`tb/<case>/case.toml` 记录测试计划，具体测试台随后在同目录实现。
目前已有四级差分 VCO、CML 时钟接收器、CML 缓冲/分频器和静态 CMOS PFD 原型，并做了部分联调。
测试状态见各 case.toml；其余模块仍待设计。
共享激励检查可直接运行。VCO 方案见 [串化时钟与 VCO](docs/serdes_clock_plan.md)。
首轮晶体管级结果与波形见 [VCO 首轮结果](docs/vco_ring4_first_results.md)。
真实 CML→CMOS 时钟接收器和可选 CML 缓冲见 [接口电路与联调](docs/cml_clock_receiver_results.md)。
二进制 CML 分频链和整数 1–16 反馈原型见 [分频器验证](docs/cml_divider_results.md)；
电容阵列逐次校准和频段重叠策略见 [粗调校准](docs/vco_coarse_calibration.md)。
CMOS 鉴频鉴相器与反馈接口测试见 [PFD 原型](docs/pfd_cmos_results.md)。
CP、LF 原型和实际电荷/滤波响应见 [PFD/CP/LF 联调](docs/pfd_cp_lf_results.md)。
混合视图 PLL 捕获与带对称 dummy 的真实反馈链见 [PLL 首轮调试](docs/pll_first_debug.md)。
LF预充与后续捕获/跟踪见 [本轮记录](docs/pll_precharge_capture.md)。
带宽、稳定时间与扫频速率的区别及第一版目标见 [PLL跟踪研判](docs/pll_tracking_assessment.md)。
16:1电流舵串化树及固定参考的2UI眼图见 [发送端首轮结果](docs/serializer16_first_results.md)。
理想互补CMOS时钟驱动选择管的对照见 [CMOS选择试验](docs/cmos_select_trial.md)。
连续原生PLL时钟的冻结回放、64字串化对照及后续检查夹具见 [PLL时钟回放](docs/pll_clock_replay_results.md)。
新原生PLL记录、实际相位路由/电容微调/扇出buffer及64字测试见 [实际时钟分发结果](docs/physical_clock_distribution_results.md)。
时钟按周期叠加、过零边沿放大及散布来源分析见 [时钟叠图诊断](docs/clock_overlay_results.md)。
可编辑 Xschem 原理图、PDF 和网表核对结果见 [原理图入口](docs/schematics.md)。
此前固定 CML ÷8 后接 250 MHz CMOS 分频的实验见 [混合分频记录](docs/hybrid_divider_results.md)；
此前全 CML 整数反馈结果保留为历史探索。
后续已澄清：自由 CMOS 分频接多相 CML 转换后的最高 2 GHz CMOS 域，
不固定在 ÷8 后，见 [当前时钟域定义](docs/clock_domain_clarification.md)。
激励的默认数值仅用于自检，不代表 SerDes 指标。

环境使用 `uv sync`、`uv run python`。仿真器路径见
[tools.toml](config/tools.toml)，PDK 安装版本见 [pdk.toml](config/pdk.toml)。
当前默认 ngspice 为旧版，本项目使用 `/opt/ngspice47/bin/ngspice`。
配置文件和 case.toml 暂未接入通用执行器；RX实时联调已有独立C++运行入口，见下文。

阅读 [电路层次](docs/architecture.md)、[测试与结果约定](docs/verification.md) 后，
先确定供电、目标码率、参考频率、VCO 范围、输出负载及抖动预算。
推荐先表征偏置、CML 电流舵和 VCO，再做相邻模块集成及 PLL 闭环。

分频相位间隔核对及末级锁存器跟踪/恢复限制的诊断见[串化时序溯源](docs/serializer_timing_root_cause.md)。

PLL双节点预充和RTL启动/状态监督器见[启动优化](docs/pll_startup_optimization.md)；附新原生冷启动模板，测量前端与片内预充参考尚待实现。

PLL与电流舵串化器当前设计定稿见[v0.1冻结清单](docs/design_freeze_v0p1.md)，完整源码、参数与证据哈希在releases中。

后续TX输出级、片内/PCB解耦、FFE、RX/CDR及编码速率预算见[输出级与链路路线](docs/tx_output_stage_and_link_plan.md)。

RX主目标已选100Ω板内/板间PCB；3/6/10dB损耗、残桩与偏斜的合成信道族及S4p/SPICE检查见[PCB信道模型](docs/pcb_channel_family.md)。

真实串化器/输出级接入近无损、6dB、10dB PCB后的固定2UI眼图、采样裕量和ISI影响见[TX与PCB联调](docs/tx_pcb_channel_integration.md)。

RX输入终端与四档CTLE首版、DC/AC表征及6dB通道记录回放见[RX前端设计](docs/rx_frontend_first_design.md)。真实TX驱动器/PCB/RX输入的缩小模型联合仿真及边界验证见[实际加载联调](docs/rx_loaded_link.md)；采样器和CDR仍待实现。

固定4Gb/s多端口已选共享基准PLL、每RX独立PI-CDR，资源关系、频偏补偿及开发目标见[CDR架构](docs/rx_cdr_architecture.md)。

真实MOS相位选择/电流加权插值、64码与规定跨圈控制测试见[PI首版](docs/rx_pi_first_design.md)。

后续已新增四相CML采样器、逐步调相交接RTL及样本投票RTL，真实PI/CTLE加载和控制轨迹回放见[采样器与PI控制](docs/rx_sampler_control.md)。该页保留当时的单元测试边界，后续进展见下文。

最新已新增静态CMOS读出与pair重定时、Q16数字CDR、训练字对齐及16位串转并；10组实际RTL/行为采样plant长时闭环见[RX闭环阶段](docs/rx_cdr_closed_loop.md)。沿用现有TX PLL，后续聚焦降速/数字时序、PI控制驱动及前端接口模型，按分层证据验收，见[验收边界](verification/contracts/rx_cdr.toml)。

CML移位后整字保持/CMOS收集的结构讨论见[字收集方案](docs/rx_cml_word_capture_plan.md)。常驻求解、触发前后窗口采集与进度估算的小规模验证见[流式记录](verification/streaming/README.md)；此项未启动SerDes长仿真。

实际SystemVerilog/Verilator与shared-ngspice的双向实时RX联调、数模边界及16位恢复结果见[混合联调](docs/mixed_signal_cosim.md)；构建/运行见[执行入口](verification/mixed_signal/README.md)。当前16UI打包为行为适配器，新CML字保持bank仍待实现。

2026-10-29已收束一次[阶段审阅](docs/stage_review_20261029.md)：含GTKWave用VCD/FST、10ns仿真耗时/产物估算，以及按模块／实验／运行批次的大文件无损归档。运行 `verification/mixed_signal/view.sh` 可打开波形；[结果总入口](results/README.md)提供实验索引及恢复命令。
