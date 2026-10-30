# 电路层次与接口

## 所有权

公共模拟模块放在 `analog/common/`，可供 PLL 和后续 TX/RX 复用。
PLL 专用模块放在 `analog/pll/`；跨模块连接和闭环集成属于 `pll/top/`。
上层实例化下层子电路，避免复制实现。
子电路名称使用模块前缀，如 `serdes_cml_buffer`、`pll_pfd`。

```text
common/bias ─→ common/cml_buffer
       └────→ pll/vco、pll/cp（按实现选择）

reference ─→ pfd ─→ cp ─→ loop_filter ─→ vco ─→ output
              ↑                           │
              └──────── divider ←─────────┘
```

按实际摆幅、共模和接收门限插入公共电平转换器，不预先规定所有时钟域的电平类型。

## 模块目录

| 目录 | 内容 |
|---|---|
| spice/ | 晶体管及无源实现 |
| behavioral/ | 同外部接口的行为模型，明确其有效范围 |
| schematic/ | Xschem 原理图、符号 |
| layout/ | 版图源文件 |
| tb/<case>/ | 测试计划、测试台、专用激励 |

DUT 只定义电路和参数；电源、源阻抗、负载、激励、分析命令与测量放在测试台。
DUT 不内嵌测试用理想负载、绝对路径或顶层 `.end`。
初期可手写 SPICE；若转为原理图生成网表，应明确权威来源，避免双重维护。
提取网表归档到运行目录，不覆盖前仿真实现。
行为模型与晶体管模型接口一致，但噪声、启动和供电行为的有效性需要分别说明。

## 初始接口草案

端口顺序和拓扑在电路实现时固定。

| 模块 | 信号约定 |
|---|---|
| bias | 偏置电压/参考电流、vdd、vss；注明电流输出顺从范围 |
| cml_buffer | inp、inn、outp、outn、偏置、vdd、vss |
| cml_to_cmos | inp、inn、outp、outn、vbias、vdd、vss；当前实现是带状态恢复的时钟接收器 |
| cmos_to_cml | clk_in、outp、outn、偏置、vdd、vss |
| pfd | ref、fb、rst_b、up、dn、vdd、vss；复位低有效，UP/DN 高有效 |
| cp | up、dn、iout、偏置、vdd、vss；UP 注入电荷，DN 抽取电荷 |
| vco | vctrl、振荡输出、偏置、vdd、vss；单端/差分输出随拓扑确定 |
| divider | 默认反馈 CML ÷8；自由 CMOS 分频另接多相 CML 转换后的最高 2 GHz CMOS 时钟，时序待设计验证 |
| loop_filter | cp_in、vctrl、vss；阶数及无源/有源形式待定 |
| rx_input_termination | inp、inn、vcm；两只50Ω，替换既有远端终端，vcm缓冲尚待设计 |
| rx_ctle_rc | inp、inn、outp、outn、eq0、eq1、vbias、vdd、vss；正极性四档RC退化初稿，后接采样器 |
| top | ref、rst_b、输出时钟、vdd、vss；测试观测点单独定义 |

差分电压统一为 `v(outp)-v(outn)`，共模为两端电压的平均值。
电流测量注明 SPICE 支路方向，再转换为指标的统一符号。
所有时间指标注明边沿、阈值和负载。

默认 PLL 反馈以 CML ÷8 为基准：2 GHz 经三级二分频得到 250 MHz，再转 CMOS 进入 PFD。
CML 的 ÷2/÷4 抽头保留，默认链不再放置第四级 ÷16，完整 CML 整数计数器也不在当前路径中。
用户所指的自由 CMOS 分频另接多相 CML 转换后的最高 2 GHz CMOS 时钟，用于时钟分发/串化需求。
此前将其固定放在 250 MHz 后面的理解已修正；250 MHz 的原型结果不证明 2 GHz 分频能力。
默认反馈总分频仍为 8，250 MHz 参考对应 2 GHz VCO。若未来另加反馈 M，须显式重算环路分频比。
500 MHz 参考在 VCO≤2 GHz 时不能走默认 ÷8 路径，可另选 ÷4 抽头；选择与未用级关断尚未集成。
此前 250 MHz CMOS 实验的 tick 可供边沿 PFD，clk_out 为注册分频时钟；这不定义新 2 GHz 自由时钟域的反馈连接。
独立的后级派生时钟可不进入 PLL 反馈；调整它不自动改变 VCO 或所有串化时钟。
配置仅在 CMOS rst_b 为低时更新。CMOS 计数器已有复位，CML 前端仍没有确定相位复位，字对齐未验证。
当前定义见 [时钟域修正](clock_domain_clarification.md)，此前 250 MHz 实验见 [混合分频记录](hybrid_divider_results.md)。
粗细调交接策略见 [vco_coarse_calibration.md](vco_coarse_calibration.md)。

当前 PFD 使用静态 CMOS 上升沿触发结构：CML 反馈分频输出先经时钟接收器转换为 CMOS，
再与 CMOS 参考时钟比较。整数反馈脉冲不要求 50% 占空比，但必须满足接收器和 DFF 的最小高/低电平时间。
PFD 的主从锁存器均异步清零；共同复位路径保留门延迟，用于后续与 CP 的最小有效脉宽协调。
实现及测试边界见 [pfd_cmos_results.md](pfd_cmos_results.md)。
CP、LF 及其与真实 PFD 的开环联调见 [pfd_cp_lf_results.md](pfd_cp_lf_results.md)。

RX输入/CTLE已独立表征并用真实TX的6dB通道电压回放，见[RX前端首版](rx_frontend_first_design.md)。真实驱动器/PCB/实际RX加载另已完成[缩小模型联调](rx_loaded_link.md)，边界在TX隔离buffer输入。实际采样器和CDR仍待设计；公共时钟接收器不视为已完成的数据RX。
