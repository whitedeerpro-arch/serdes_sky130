# Verilator 与 ngspice 实时 RX 联调

运行实际 SystemVerilog 投票器、CDR 滤波器、PI 交接器和 16 位串转并；真实 SKY130 PI、CTLE、CML 采样器、CMOS 转换/重定时及 PI 控制缓冲由 ngspice 连续求解。C++ 在两者之间调度，控制结果会影响后续模拟采样。

## 物理读出版（2026-11-03，当前）

[cpp/cosim_words.cpp](cpp/cosim_words.cpp) + [tb/receiver_words.cir.in](tb/receiver_words.cir.in) + [rtl/mixed_cdr_words_top.sv](rtl/mixed_cdr_words_top.sv)。桥接机制与原版相同（一个连续瞬态、按已接受时间点推进 RTL、控制脚 50 ps 发射 + 20 ps 边沿 + 两级真实反相器）；模拟端换成采样器 ac_rk（rb = 2 kΩ、rk W8）+ 读出 [rx_readout_deser16](../../analog/rx/sampler/spice/rx_readout_deser16.spice)，输入共模 1.05 V。模→数边界：每个字时钟 w 上升沿（0.9 V）后 100 ps 读 32 个输出（≤ 0.54 V 判 0、≥ 1.26 V 判 1）；数据位落在中间区记为未知并判失败，边沿位落在中间区则该包不投票。全部 RTL（`rx_word_map` → 投票 → 环路 → 交接器、`rx_word_align16`）在 w 上运行，**没有行为打包**。

激励：理想 NRZ，`--train-ui`（默认 160 UI = 10 字）个 b5e3 后接 payload `0x1200 + n·0x137`；`--release-ns`（默认 50 ns）之后、对齐器已对齐时释放 training，此后输出字逐个对 payload。

```bash
make -C verification/mixed_signal build-words
results/verification/mixed_signal/build_words/Vmixed_cdr_words_top --root "$PWD" \
  --out "$PWD/results/verification/mixed_signal/<run>" --stop-ns 140 [--tx-phase-ps 74] [--hold-controls] [--wall-s 5400]
```

通过条件：到达终点、无致命错误、无数据未知、payload ≥ 4 字且零错、释放时已对齐、RTL 有调相、（非 hold 时）模拟控制脚实际翻转。summary 另记跨扇区次数、走过的码、重新对齐次数。80 ns 在本机约 6.5 min（单线程）。结果见 [RX 数字](../../docs/design/rx_cdr_digital.md#实时数模联调)、[数据](../../docs/data/mixed_signal_cosim_words.json)。

## 失调校准启动版（2026-11-03）

同一桥接编译时加 `COSIM_CAL`：[rtl/mixed_cdr_cal_top.sv](rtl/mixed_cdr_cal_top.sv)（mixed_cdr_words_top + [rx_offset_cal](../../digital/rx/rtl/rx_offset_cal.sv)，CDR 由 `enable & cal_done` 门控）+ [tb/receiver_cal.cir.in](tb/receiver_cal.cir.in)（采样器 ac_trim_rk，24 个修调码脚由 RTL 驱动，与控制脚同样的发射延迟和边沿）。

- 输入在 `--cal-end-ns` 之前保持电气空闲（差分 0），第一个计数字时发 `cal_start`；之后训练和 payload 与物理读出版相同。
- `--inject-ua d0p=…,e1n=…` 在修调节点 t<p|n> 上加吸收电流，代替失配。
- `--corner/--supply/--temp` 选择条件。
- 输出 `cal.tsv`（码随时间变化）；summary 的 `cal_lanes` 列出各路最终码。

summary 里的 `expected`（31.5 ∓ k/2）按注入灵敏度估算，不准：注入会压缩步长。校准结果以 [cal_check.py](../../analog/rx/sampler/tb/offset_dac/cal_check.py) 或 [insitu.py](../../analog/rx/sampler/tb/offset_dac/insitu.py) 的核对为准。

```bash
make -C verification/mixed_signal build-cal            # CAL_NW=2 CAL_SETTLE=4
results/verification/mixed_signal/build_cal/Vmixed_cdr_cal_top --root "$PWD" --out "$PWD/results/verification/mixed_signal/<run>" \
  --stop-ns 1500 --cal-end-ns 1400 --inject-ua d0p=19.92,d1n=13.944,e0p=5.976,e1n=29.88 --wall-s 20000
```

结果和结论见 [RX 采样器 · 失调修调](../../docs/design/rx_pi_sampler.md#失调修调2026-11-03)。第一版算法（单次 SAR）：
- 四路同时：173 ns 完成；
- 顺序：677 ns 完成；
- 两者之后 payload 都是 12 字 0 错；
- 但采样器在空闲输入下有迟滞，残差达 2–3 mV，因此改成两边沿 SAR。

TT 下 820 ns 的运行约 1.8 h。

以下为原版（旧 pair 对齐读出 + 行为 16 UI 打包，2026-10-29 验证记录）。

## 运行

已验证 Verilator 4.028、g++、make 和本机新安装的 shared ngspice 47。默认库路径为 `$HOME/.local/opt/ngspice47-shared`，可用 `NGSPICE_PREFIX` 覆盖。

```bash
make -C verification/mixed_signal boundary-test
make -C verification/mixed_signal build
results/verification/mixed_signal/build/Vmixed_cdr_top \
  --root "$PWD" --out "$PWD/results/verification/mixed_signal/my_live48" --stop-ns 48
results/verification/mixed_signal/build/Vmixed_cdr_top \
  --root "$PWD" --out "$PWD/results/verification/mixed_signal/my_hold24" --stop-ns 24 --hold-controls
```

使用新的输出目录。`make run OUT=/absolute/run/path` 运行默认 48 ns 场景。程序返回 0 表示该场景检查通过，返回 1 为验收失败，返回 2 为启动错误。`--probe --stop-ns 8` 只检查接口启动，不要求 PI 已更新或收齐数据字。

默认 `KP=65536`，即每次比例校正 1 个 PI 步，便于短窗内看到控制动作；生产 RTL 默认仍为 8192。本轮没有修改生产参数。`make ... KP=8192 BUILD=/absolute/separate/build` 可建立另一配置，但默认短窗的“必须发生调相”检查未针对该配置设置；不能把它直接用于生产参数锁定验收。

新共享库来自官方 ngspice-47 源码，独立安装，既有 `/opt/ngspice47/bin/ngspice` 不变。构建选项：`--with-ngshared --with-readline=no --without-x --enable-klu --disable-debug CFLAGS=-O2`；构建来源、日志哈希见结果证据清单。此实现直接使用 C++ 模型端口与 shared-ngspice C API；没有依赖 DPI-C、Verilog-AMS 或 Python 常驻脚本。

## 边界与时序

模拟到数字：真实 CMOS `ck` 上升过 0.9 V 后 **350 ps**，读取真实重定时输出 `ad0/ad1/ae0/ae1`。电压 ≤0.54 V 判 0，≥1.26 V 判 1，中间区单独记录 unknown。Verilator 是二态执行；unknown 不靠其内部 X 传播模拟，数据 unknown 会使验收失败，边沿 unknown 使本包投票无效并计数。该 valid 是仿真诊断，不代表片上存在亚稳态探测器。

每 500 ps 提交一个真实数据 pair 给串转并 RTL；每 8 个 pair 形成 16 个数据和 16 个边沿样本，保存前包最后数据位，再延迟 50 ps 提交给投票/控制 RTL。两类时钟高脉宽分别为 250 ps 和 2 ns。**16 UI 打包仍是行为适配器**，没有以此声称 2 GHz CMOS 移位链已通过物理时序，也没有实现新讨论的 CML 字保持 bank。

数字到模拟：实际交接器给出 one-hot/thermometer 控制；改变后延迟 **50 ps** 才启动 0/1.8 V 源的 **20 ps 线性边沿**，每根控制再经两级真实 CMOS 反相器驱动 PI 的实际 MOS 负载。RTL 流水线、交接器等待周期、外部发射延迟、实际缓冲延迟分别保留。50 ps 是当前接口假设，尚未用布局/STA 标定。

接收数据为有限 20 ps 边沿、350 mVpp 差分、0.9 V 共模的理想 NRZ 源。前 96 UI 为重复 `b5e3` 训练，后续字依次 `1200、1337、146e、15a5、16dc…`，LSB 先发。PI 锚点为理想相关的 2 GHz 多相时钟。本夹具没有包含 TX、PCB、原生 PLL、噪声、时钟频偏或新的 CML 移位/字保持电路；这些与既有分层测试证据分开记录。

## 连续求解和数据采集

一个进程只加载一个电路、运行一次 transient。模拟器不按窗口重启；只在已接受的模拟时间点推进 RTL，并通过同步回调将下一步约束到读出、打包、数字时钟下降沿和控制源边沿事件。源查询是时间的纯函数，拒绝步/试探调用不会消耗事件；控制改变从将来开始，保留最近 2 ns 控制历史。

`.save none` 在此 ngspice 47 共享接口中保留当前模拟点，并继续逐点回调；结束检查 `time` 向量长度为 1。每点只拷贝 18 列到外部环形窗。环保留 2 ns、最多 32768 点；启动窗 0–8 ns；控制变化前后各 2 ns，最多 16 个窗，每窗最多 65536 点，超容量显式失败。已完成的窗立即落盘并释放行数据；遇到 Tstop 的末窗按实际终点截断。短测数字 VCD 和文本事件日志仍随时长增长，**整个进程尚不是无限时长、无限日志的服务**。

加载完整 PDK 的初始解析时间单独显示；transient 每约 5 秒输出当前 UI、完成百分比、平滑 ETA 和 RSS。ETA 依据最近模拟推进速度，不能预测后续收敛困难。PDK/电路模型本身约占 700 MB，窗口记录避免的是随总模拟点数增长的历史数组。

## 文件与判据

- `summary.json`：时长、相位变化、字比较、unknown、窗口和保留点数。
- `pairs.tsv / controls.tsv / words.tsv`：A/D 判决、真实 RTL 控制及串并结果。
- `clock_phase.tsv / da_pin_events.tsv`：实际模拟时钟过零、缓冲后控制脚过零。
- `windows/*.tsv / digital.vcd`：选择性模拟波形与短测数字波形。
- `progress.jsonl / ngspice.log / netlist/`：进度、求解日志和本次电路快照。

闭环场景检查到达终点、无数据 unknown、无错字、至少两个 payload 字、RTL 发生更新、模拟控制脚实际翻转且时钟相位移动 >5 ps；固定控制端对照要求 RTL 仍更新，但模拟脚不翻转、相位漂移 <1 ps。边界测试另查阈值/未知区、NRZ 完整边沿、D/A 延迟/斜率和源的乱序查询。

具体记录、图和适用范围见 [联调结果](../../docs/history/mixed_signal_cosim.md) 与 [case.toml](case.toml)。

已归集GTKWave会话和VCD/FST，运行 `verification/mixed_signal/view.sh`；查看[阶段波形说明](../../results/acceptance/20261029-rx-functional/README.md)。大文件保留策略与10ns成本估算见[阶段审阅](../../docs/history/stage_review_20261029.md)。
