# PLL启动监督器

RTL：`rtl/pll_startup_supervisor.sv`。参考域顺序为WAIT_READY→PRECHARGE→GAP→FLUSH→ACQUIRE→TRACK。
模拟控制由保留的一热状态位产生，避免多位二进制状态译码毛刺；state_id只供诊断。默认250MHz下，预充128周期=512ns，断开等待2周期=8ns，PFD先运行2周期=8ns，最后开启CP。
锁定后连续两个坏测量窗撤销locked并保持LF状态重新捕获；超时、范围或偏置故障进入FAULT并关闭CP。

这不是频率计/TDC，也不产生模拟偏置或预充参考。`quality_valid`必须代表一个新测量窗，
`frequency_good`与`phase_good`均为真才累积好窗；单独频率接近或Vctrl平坦不能判锁。
长时间没有新测量会清除捕获积累或在TRACK撤销锁定。检测前端的阈值和校准尚需实现。

除`rst_n`、`abort_async`外，输入需在参考时钟域内稳定；异步来源必须先同步。
复位应异步置位、同步释放。独立参考看门狗可通过`abort_async`在参考停钟时立即钳制控制输出，
并需保持至确认；其状态经两级同步后进入FAULT。监督器本身无法靠已经停止的参考时钟检测停钟。
ready信号在门控路径中，必须来自无毛刺、已资格确认的逻辑，不能直接接裸模拟比较器。

FAULT状态下，start且ready有效可重启；disable优先回IDLE。故障码：1偏置丢失，2预充参考丢失，
3控制范围故障，4等待/捕获超时，5外部abort，6测量失效。FAULT码在重启/禁用时清除。

参数均要求正整数。周期数当前是综合参数，尚无运行期CSR；更换参考频率必须重新设定时间预算，
不能把250MHz的512ns直接套到50/500MHz。反馈比例仍以÷8为基准，500MHz参考需另行规划÷4。

`tb/tb_pll_startup_supervisor.sv`测试异常交接和状态；`tb/tb_pll_startup_default_timing.sv`核对真实默认周期。
运行示例（在仓库根目录，输出文件放在结果目录）：

```sh
iverilog -g2012 -s tb_pll_startup_supervisor -o /tmp/pll_startup.vvp digital/pll/rtl/pll_startup_supervisor.sv digital/pll/tb/tb_pll_startup_supervisor.sv
vvp /tmp/pll_startup.vvp
verilator --lint-only --top-module pll_startup_supervisor digital/pll/rtl/pll_startup_supervisor.sv
```

## 粗码控制

RTL：`rtl/pll_coarse_ctrl.sv`（I-18），例化[公共监测单元](../common/README.md)的`mon_sync`/`mon_persist`。输入为[Vctrl窗口检测](../../analog/pll/coarse/README.md)的异步hi/lo、温度档`tclass`和各档停止门限（梯码+选用哪一侧比较器）；输出VCO粗码与两条门限梯的码。
VCO粗码宽度由`CODE_BITS`决定，默认4位（0–15）；5位可表示0–31。`lo_code`、`hi_code`和`stop_code`中的每档门限仍是独立的4位电压梯码；H3/H4表示梯码数值。上电从最大粗码逐码往快搜，每步等`SETTLE_CYCLES`；停止后梯码回到运行值，若低于vlo则退回一码。运行中hi/lo每`SAMPLE_DIV`周期采样、连续`PERSIST`次才切相邻码，切后`HOLD_CYCLES`内不再判；码0仍越上沿给`fast_end`，最大码低于下沿给`slow_end`（快芯片的正常状态）。
搜索须在环路闭合、CP开启时进行（监督器ACQUIRE内）；搜索期间由上层屏蔽送监督器的`quality_valid`。每个等待段装载后递减到零，再在下一拍判决，耗 `SETTLE_CYCLES + 1` 周期；`2**CODE_BITS`个搜索码加CHECK/BACK最多`2**CODE_BITS + 2`段。ACQUIRE超时至少留出`(2**CODE_BITS + 2) × (SETTLE_CYCLES + 1) + 8`个参考周期，并另计上层交接和模拟建立余量。控制顶层默认`ACQ_TIMEOUT_CYCLES=1024 × 2**CODE_BITS`，4位保持16384，5位为32768；修改等待时间后须另算预算，不能只靠默认缩放。

滤波器在切码同一时钟沿同步清除，并在保持期、搜索期和 `track_en=0` 时持续清除；恢复跟踪后须重新取得 `PERSIST` 个采样点。同步器仍有两拍输入延迟，上层须允许比较器输出和环路在切码后建立。`hi` 与 `lo` 同时有效时保持高越界优先；这不作为合格模拟窗口输入。`SETTLE_CYCLES` 与 `HOLD_CYCLES` 是数字等待值，须结合模拟比较器与 PLL 再捕获时间逐角校准。

```sh
iverilog -g2012 -s tb_pll_coarse_ctrl -o /tmp/coarse.vvp digital/common/rtl/mon_sync.sv digital/common/rtl/mon_persist.sv digital/pll/rtl/pll_coarse_ctrl.sv digital/pll/tb/tb_pll_coarse_ctrl.sv && vvp /tmp/coarse.vvp
```

`uv run pytest -q tests/test_pll_coarse_rtl.py`同时运行上述行为环路、公共滤波器清除检查及短HOLD/关闭再恢复跟踪回归。短HOLD用例取`HOLD_CYCLES=1、PERSIST=8`，检查一次已消失的越界不会被旧确认状态重复消费。

`tb_pll_coarse_ctrl`对行为环路（每码锁定Vctrl随温度线性漂移、z一阶跟随300 ns、比较器±2 mV噪声）检查：三档温度×四种芯片偏移的上电码与独立实现的规则一致（门限±3 mV内两码都算对）；错档上电后−40→85→−40 °C扫描，升温往快码、降温往慢码，共3次切码，无两次间隔小于HOLD；码15下沿保持与码0上沿标志。

`tb_pll_coarse_5bit`以抽象比较器规则覆盖全部32个搜索结果、CHECK/BACK的15→16与30→31、最大码回退钳位、运行中15↔16切换和0/31端点；同时检查搜索/运行门限梯仍为4位。`tb_pll_control_5bit`保留默认512周期等待，搜索31→0，要求搜索期间不能锁定、完成后仅一次搜索并保持锁定。第二个实例故意保留16384周期超时，必须进入FAULT 4；32768默认值须成功。两者及原4位控制顶层现纳入同一pytest入口，共6项。此处验证码算术和数字交接；物理r6的频率图、窗口、捕获、cfg4/复位/quiet轨接线及45点PVT仍须使用r6本身的证据，配置默认仍为4位。

## 启动链顶层

`rtl/pll_control_top.sv`把监督器、粗码控制和`rtl/pll_lock_detect.sv`接在一起，不用频率计：
- **phase_good**：一个测量窗（默认32个参考周期）内，相位误差脉冲UP xor DN（宽度即|相差|，不含公共复位脉冲）从未长于τd。模拟侧用该脉冲延迟τd后的沿对它本身采样，送入`pw_late_async`。不用"参考沿+τ时UP|DN仍高"：复位脉宽在45条件为290–746 ps（`analog/pll/pfd/tb/reset_pvt`），τ要盖过它，FF角就会放过约600 ps相差。模拟单元`pll_phase_window`（`analog/pll/pfd/spice/phase_window.spice`，6级反相器、每级10 fF）由真实PFD驱动，45条件门限225–750 ps（FF 1.95 V −40 °C … SS 1.65 V −40 °C），每个条件≥3.9倍同条件的锁定静态相差上界（PFD＋CP失配|均值|+kσ 51–189 ps），远小于捕获期的ns级相差（[PLL环路](../../docs/design/pll_loop.md#锁定检测相位窗口2026-11-10)）。清零后一直为高的xor没有新沿、不置位；这种情况（UP卡死、VCO停振）Vctrl到轨，由frequency_good报告。
- **frequency_good**：粗码搜索结束，且整窗内窗口检测既无hi也无lo。环路锁在窗口内即在2 GHz，码不够时Vctrl被推出门限。
- 顺序：start后第一次进入ACQUIRE时触发一次粗码搜索，搜索期间不向监督器报告测量窗；锁定后开启运行中切码；切码扰动使监督器回到ACQUIRE（保留LF状态）后重新锁定，不重复搜索。`fast_end`（码0仍高于上门限）作为range_fault，进入FAULT 3。

```sh
iverilog -g2012 -s tb_pll_control_top -o /tmp/ctop.vvp digital/common/rtl/mon_sync.sv digital/common/rtl/mon_persist.sv digital/pll/rtl/pll_startup_supervisor.sv digital/pll/rtl/pll_coarse_ctrl.sv digital/pll/rtl/pll_lock_detect.sv digital/pll/rtl/pll_control_top.sv digital/pll/tb/tb_pll_control_top.sv && vvp /tmp/ctop.vvp
```

`tb_pll_control_top`对行为环路（每码锁定Vctrl随温度线性漂移，预充到1.20 V，CP开启后z一阶跟随300 ns，偏离锁定点15 mV以上或钳位时相差脉冲过τd）检查：27 °C冷启动7.6 µs锁定于码13且只搜一次；升温60 K（7 mV/K）切码2次后重新锁定，无FAULT、不重搜；码0仍达不到2 GHz的芯片进入FAULT 3；FAULT后重启再次搜索并锁定。τd已按静态相差校准（见上）；测量窗长度需按切码暂态校准。

Icarus行为检查、Verilator lint、Yosys通用综合检查不等于SKY130映射后的时序/CDC验证。
模拟电路、结果、接口边界和其他模型接手的测试模板见[启动优化](../../docs/history/pll_startup_optimization.md)。
