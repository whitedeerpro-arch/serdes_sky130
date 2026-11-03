# 变更日志

按日期倒序。细节见 [history](../history/index.md)。

## 2026-11-04

- RX 失调校准：空闲输入下采样器有迟滞，判决依赖本路上一次判决（[idle_sweep.py](../../analog/rx/sampler/tb/offset_dac/idle_sweep.py)：TT ±2.4–3 mV、SS 1.65 V 85 °C ±4 mV）。单次 SAR 落在迟滞带内的任意位置；第一版联调（TT，四路同时 / 顺序）残差达 2–3 mV，单路斜坡与原位（CTLE + PI，PI 码 0/4/8，相差 ≤ 0.5 mV）两种核对一致，排除了环境差异。[rx_offset_cal.sv](../../digital/rx/rtl/rx_offset_cal.sv) 改为两边沿 SAR：每次试探前分别以码 0 / 63 预置，找上下沿后取中点。行为模型加迟滞后，残差 2.08 → 0.92 LSB（无噪声）、1.53 → 1.19 LSB（0.5 mV 噪声）。顺序校准约 1.34 µs。两边沿版 TT 联调运行中。
- 联调校准版（`make build-cal`，`mixed_cdr_cal_top`、`receiver_cal.cir.in`）：ac_trim_rk、24 个码脚、启动顺序为空闲 → 校准 → CDR，`cal_done` 之前 CDR 关闭。核对脚本 [cal_check.py](../../analog/rx/sampler/tb/offset_dac/cal_check.py)、[insitu.py](../../analog/rx/sampler/tb/offset_dac/insitu.py)。
- RX 读出接修调采样器（ac_trim_rk + deser16，码 32）：45 条件 4880 个数据位、2433 个边沿全部正确，余量与 ac_rk 相同，功耗 +1–2 mW。数值处理：`readout_deser --reltol`、`--op-steps`（TT 1.65 V −40 °C 工作点不收敛，`gminsteps=srcsteps=100` 后约 3 min 收敛）、`--case-timeout`。

## 2026-11-03

- RX 采样器失调修调（`ac_trim`，[rx_offset_trim.spice](../../analog/rx/sampler/spice/rx_offset_trim.spice) + [rx_offset_cal.sv](../../digital/rx/rtl/rx_offset_cal.sv)）：主锁存器辅助对（共用尾管，2/4 指）+ 6 bit DAC 推电阻 T 网络 + 四路同时 SAR 前台校准；主尾管 +8 指。45 条件窗口与 ac 相同（压力角 0.875–1.0 UI、门槛 39/39、栅极时钟 ≥ 328 mVpp），测试台 +1.3–2 mW。校准后 MC：每路（采样器 + CTLE）3σ 2.2 / 3.4 / 4.4 mV（27 °C 校准，27 / 85 / −40 °C 工作），不修调约 27–30 mV。先做的电流型 DAC（`ac_cal`）步长随温度变 1.8 倍，放弃。
- MC 方法与工具（[统计与蒙特卡洛](../verification/statistics.md)）：`serdes_flow.mc` / `stats` / `rcorner`；配对 MC（同一种子换条件）——修复 `mc`：读网表时抽的第一个样本不受种子控制，现在丢弃；失配与工艺角的组合方法。失配分析：采样器 σ 6–7 mV、CTLE 6.1 mV，时钟、PI 可忽略。
- 偏置：带隙 + 恒摆幅参考 + vcm 缓冲，5 bit 修调；135 条件（MOS × 电阻角）I·R ±0.7 %、修调后 vcm 约 ±26 mV，上电 135/135（[偏置](../design/bias.md)）。
- 工具：`spice.case_output(t_end=…)` 把"timestep too small"中止后写出的截断波形算作缺失（此前 `link_pvt` 会把它当成完整结果；扫描 1324 个已有波形，只有当天 4 个 ac_trim 工况受影响，已重跑）；`link_pvt --dut ac_trim --cal-code --reltol`。
- 实时联调接物理读出（`cosim_words.cpp`、`receiver_words.cir.in`、`mixed_cdr_words_top.sv`，`make build-words`）：w 上升沿后读 deser16 的 32 位，全部 RTL 在 w 上运行，去掉行为打包。TT 下 PI 0→14 码（跨扇区 7→8）与 0→63 回卷都在训练释放后发生，payload 22 / 17 字全部正确，无重新对齐；原 pair 版保留。
- 背靠背字流（`analog/rx/top/tb/b2b_stream`）：真实 TX r2 → C2 → RX 端接 + CTLE 连续 29 个字，远端登记为边界条件后回放进 deser16，实际 RTL 解出 16/16 个 payload 字按序正确，TX→RX 16.9 ns（TT，开环码 22）。`view.sh` 一条命令打开 GTKWave（TX 字、线、远端、CTLE、采样、w、RTL 字与期望）。RTL 测试台复位改为显式复位沿（时刻 0 竞争）。

## 2026-11-02

- RX 采样器候选 ac（低过驱尾管 + 隔直时钟）与时钟 buffer c2（尺寸设计第二轮）：45 条件采样窗口 ≥ 0.5 UI，栅极时钟 325–866 mVpp。
- RX 读出 demux2：2 GHz 直转 CMOS 是结构性失败；改为 PI 时钟 ÷2 的 CML 1:2 分路 + 匹配转换，45 条件逐位正确；p2 恒定 τ 半尺寸，读出约 18 → 10 mA。静态负载检查 `serdes_flow.loading`。
- RX 读出 deser16（I-15 读出部分）：CMOS DFF 单元卡（`devices/tb/cmos_dff_card`）显示原复位 DFF clk→q 171–635 ps 超过半个 1 GHz 周期，新增精简 TG 主从 DFF `serdes_cmos_dff`（37–159 ps）；时序规划 `theory/readout_deser_plan.py` 在仿真前发现选通方案的位映射不连续（ckqb 路改用 J1）；45 条件 4960 数据位、2466 确定边沿全部正确，映射处处相同，字时钟窗口 ≥ 1.5 ns，功耗与 demux2 持平。demux2 拆为 `serdes_rx_readout_front` + 捕获 DFF（展平逐器件相同）。
- RX 数字：`rx_word_map`（物理 32 位 → 时间顺序 16 数据 + 16 边沿）、`rx_word_align16`（训练字找字边界）；`tb_rx_word_path` 16 种窗口起点、928 次投票、767 个字全部正确。
- 工具：`serdes_flow.vcd`（raw → VCD，GTKWave 分组脚本）；`--analyse-only` 不再改写 campaign 的 plan.json（部分重分析曾让健康探针总数变小）。

## 2026-11-01

- 虚拟机三次卡死的原因：ngspice 默认按核数开 OpenMP 线程，RX 等模板没有限制，4 个并发任务把 8 个 vCPU 超额占满（CTLE DC 扫描 > 10 min，单线程 13.6 s）。`spice.run` 现在对所有任务设单线程。
- I-28：RX CTLE AC/DC PVT。原 0.8–0.9 V 输入共模在慢角尾管掉进线性区；改为 vcm 1.05 V（AC 耦合链路），45 条件 × 4 档全部满足，尾管余量 ≥ 103 mV，最高档 2 GHz 峰化 4.17–5.96 dB。
- 结果清理：大波形就地 gzip；被取代的 TX 时钟回放波形（约 5 GB）先提取对比图与数据再删除，`results/` 15 → 5.5 GB。
## 2026-10-31

- I-07：TX 分发 v3（S4：3 位同步 CML 计数器共用时钟跟随器 + 2G clk→q 复制单元，`tx_clock_counter.spice`、`dist_v3.py`）在 15 个原生 V/T 点上按原始位序全部满足：串化器 121.6–173.1 mV、散布 ≤ 0.140 UI，同一工艺内摇摆带 ≤ 0.06 UI，四路相对位置 15 点合计散布 ≤ 0.08 UI；计数器建立/保持 ≥ 305/88 ps。功耗 38–51 mW 待优化。回放新增 `word` 模式（数据跟随字时钟）与计数器探测 `counter.py`。
- I-07（续）：TX 分发 v2（250M/500M/1G 在 2G 主干上打拍）把同一工艺内随 V/T 的摇摆带从 0.22–0.38 UI 压到 ≤ 0.10 UI；落位修正版 v2b 在 15 个 V/T 点上 10 点满足，余下是 85 °C 的 TT/FF/SF。新增 `wobble.py`（按工艺画摇摆带）。
- 新增结构时序平衡分析库 `serdes_flow.balance` 与元件库 `config/timing_elements.json`（由 v2b 探测和原生抽头拟合）。TX 选择时钟六种构造比较：同步二进制计数器 + 2G clk→q 复制单元在组合树下 λmax ≥ 4、单芯片带宽 0.01 UI；现状与单链逐级 ÷2 不满足；v2b 型受打拍器窗口限制。
- I-07：PLL r4 原生前端 + TX r2 联合仿真，TT 正常，SS 冷/热失败。拆分为位置与质量：录制原生抽头、在 TX 单独 bench 回放（`tb/clock_replay`）。SS 冷角只是位置漂移；热角即使放回标定位置也失败，原因是分频抽头幅度不足（FS 热 1 GHz 151 mVpp）而分发两级增益不够。热角单轴时序窗口：500 MHz −0.5~+0.1、1 GHz ±0.25、2 GHz −0.1~+0.3 UI；统一对中在 FS 热角不成立。
- I-07（续）：分发 v1（500M/1G 加一级高增益 buffer、去 RC trim）恢复热角时钟质量，4 个原生点位置对准时最差 125.4 mV / 0.073 UI。位置漂移与各路分频级数之差成正比；FF 1.95 V −40 °C 原生点（码 5、1.174 V）下固定设置失效（2G 晚 0.88 UI，位序改变），需要重新打拍。
- TX 串化器：末级每次选择切换时负载电流从约 0.6 mA 掉到 0.2 mA，造成长连码时每个位边界的凹口；末级摆幅试验（400→330→270 Ω）裕量近比例下降，保留 r2 摆幅。新增看图脚本 `tb/waveform_view`。
- I-01：证实分频器启动状态只造成字内固定位重排（8 状态 × 6 工况一致）；新增 3 bit 状态检测器（48/48）与 `tx_word_remap` RTL；调序后 24/24 端到端满足规格，FS 热角 1024 bit 最差 0.127 UI。
- I-04 解决，PLL 工作修订 r4：全速 CML→CMOS 改用 `serdes_cml_to_cmos_r4`（根因是 PMOS 镜像负载上拉不足）；标准边界 45/45，原生 VCO 5 个工作点四路全部正常；前端 TT 功耗 +4.2 mW。交流耦合自偏置方案在 SS 冷热失败，未采用。
- 单链打拍时钟探索归档（未采用）；`serial.bit_mapping` 把眼图健康和位映射分开测。
- 共享库支持二进制 raw 输出和起始保存时间：TX bench 文件 21.2 → 8.9 MB，仿真时间不变。
- 规格：名义 BER 1e-12、高低温档 1e-9；400 mVpp 定为上界和驱动目标。

## 2026-10-30

- 文档重构：README 一页化；新增 overview / design / verification / status；旧实验记录归入 history。
- 项目交接到 fork1；初始化 git，基线标签 `baseline-handover-20261030`；不再使用"冻结"流程。
- TX r2 收尾：补算 2 条 1024 bit 记录（TT 与 FS/1.65 V/85 °C 均零错误；FS 热角散布 0.1149 UI），生成数据与图，波形无损压缩。
- TX r2 工作修订：逻辑尾偏置分离 + 6 倍宽尾管、末级保持 40 µm/300 Ω、2 GHz 加两级 buffer、低阈值使能门。串化器草案 36/45 → 45/45；输出级从禁用态启动 45/45；C2 四工况零错误。
- TX r3 时钟相位核对：r3 级间 buffer 改变了各抽头相位，1 GHz 在一次启动中差约 2 UI；2 UI 眼图改为中央完整眼显示。
- TX PVT（v0.1 电路）：45 条件整链功能 45/45，但串化器草案只有 36/45；定位到 CML 堆叠尾管余量和输出使能接管。
- PLL 环路选定工况 PVT：CP DC 与 PFD→CP 45 条件；4 工况 × 3 初值分层闭环锁定；r3 原生短时接回。
- 分频器尺寸与全速 CMOS 优先级评估：先接受 r3 尺寸；全速转换器对 PLL 优先级降低，RX 依赖保留。
- PLL r3：每个 prescaler 加两个级间 CML buffer；标准输入 45 条件分频/反馈全部正确，全速 CMOS 44/45；4 个原生工况约 2 GHz 正常（SS 冷角全速 CMOS 除外）。

## 2026-10-29

- 偏置清单与级间 buffer 的 SS 冷热补测；提出主参考需求。
- 锁存器/分频器结构探索（两层去尾源、folded、PMOS 负载、C²MOS、TSPC）与弱时钟回放；结论：保留静态 CML，加级间 buffer。
- PLL r2：低过驱动宽尾管 + 真实本地偏置镜 + 源跟随器 80 µm；45 条件分频/反馈 45/45，全速 CMOS 44/45。
- SS 分频链定位：尾管压差不足是主因，单调 Vbias 无法恢复。
- VCO/接收器修整候选：变容管与电容加大、接收器前级加宽；SS 冷端边界 (−13, −12] °C。
- PLL 首轮 PVT（9 个 pilot）与物理 poly/MIM LF 候选。
- 阶段审阅：4 Gb/s 名义条件下分层功能原型阶段收束；结果归档（4.19 GB → 1.24 GB）。
- RX：实时 Verilator ↔ ngspice 联调；RTL CDR + 解串 10 组 100 µs 闭环；静态 CMOS 读出与 pair 对齐；四相 CML 采样器与 PI 交接 RTL；选定共享 PLL + 每路 PI-CDR 架构。

## 2026-10-28

- 64 码 PI 首版；TX → PCB → RX 实际加载联调；RX 端接与四档 CTLE。
- 合成 100 Ω PCB 信道族 C0–C5；真实 TX 接 C0/C2/C3。
- TX 输出级（8 mA、源端 50 Ω）与链路路线规划。
- **v0.1 发布**：PLL、启动扩展、时钟分发、16:1 串化器（末级锁存器 24 µm/200 Ω）。
- 串化时序溯源：末级 A 支路跟踪/恢复与上游到达时刻耦合；分频多相间隔不等距来自抽出极性。
- PLL 双节点预充（LF 建立约快 14 倍）与启动监督 RTL。
- 原生 PLL 时钟经实际 CML 分发驱动串化器，1024 bit 零错误，散布 0.162 UI。
- 时钟域定义修正：自由 CMOS 分频接多相 CML 转换后的 2 GHz 时钟。
- 冻结 PLL 时钟回放驱动串化器；理想 CMOS 选择对照（后停止）。

## 2026-10-27

- 项目建立：目录、验证约定、共享激励。
- 四级差分环振首版（TT 2.008 GHz、415 mVpp）；CML→CMOS 时钟接收器；CML 分频器；CMOS PFD；CP/LF 原型；首轮混合视图 PLL 捕获；LF 冷态预充；原生预充捕获。
- 16:1 CML 串化树首轮。
