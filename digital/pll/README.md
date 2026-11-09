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
上电从码15逐码往快搜，每步等`SETTLE_CYCLES`；停止后梯码回到运行值，若低于vlo则退回一码。运行中hi/lo每`SAMPLE_DIV`周期采样、连续`PERSIST`次才切相邻码，切后`HOLD_CYCLES`内不再判；码0仍越上沿给`fast_end`，码15低于下沿给`slow_end`（快芯片的正常状态）。
搜索须在环路闭合、CP开启时进行（监督器ACQUIRE内）；搜索期间由上层屏蔽送监督器的`quality_valid`，并把ACQUIRE超时设得大于最坏搜索（18×SETTLE_CYCLES）。

```sh
iverilog -g2012 -s tb_pll_coarse_ctrl -o /tmp/coarse.vvp digital/common/rtl/mon_sync.sv digital/common/rtl/mon_persist.sv digital/pll/rtl/pll_coarse_ctrl.sv digital/pll/tb/tb_pll_coarse_ctrl.sv && vvp /tmp/coarse.vvp
```

`tb_pll_coarse_ctrl`对行为环路（每码锁定Vctrl随温度线性漂移、z一阶跟随300 ns、比较器±2 mV噪声）检查：三档温度×四种芯片偏移的上电码与独立实现的规则一致（门限±3 mV内两码都算对）；错档上电后−40→85→−40 °C扫描，升温往快码、降温往慢码，共3次切码，无两次间隔小于HOLD；码15下沿保持与码0上沿标志。

Icarus行为检查、Verilator lint、Yosys通用综合检查不等于SKY130映射后的时序/CDC验证。
模拟电路、结果、接口边界和其他模型接手的测试模板见[启动优化](../../docs/history/pll_startup_optimization.md)。
