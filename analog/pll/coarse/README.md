# PLL 粗码控制（I-18）

PLL 侧的使用方：用[监测工具包](../../../docs/design/monitor.md)的积木搭 Vctrl 窗口检测，数字控制在
[pll_coarse_ctrl](../../../digital/pll/rtl/pll_coarse_ctrl.sv)。策略与模型见 [VCO 粗细调交接](../../../docs/design/pll_vco.md#粗细调交接策略)。

| 部分 | 文件 | 说明 |
|---|---|---|
| 窗口检测 | [spice/vctrl_window.spice](spice/vctrl_window.spice) | `pll_vctrl_window z hi lo ilo ihi ibh ibl vdd vss`：感测 LF 积分电容节点 z；vlo 对地梯、vhi 对电源梯，各 16 档；电流来自 4 路带隙拷贝（2+2+1+1 指） |
| 控制器 | `digital/pll/rtl/pll_coarse_ctrl.sv` | 上电从最慢码 15 逐码往快搜（分频器不会被推到明显高于 2 GHz），停止门限按温度档；运行中持续越界确认 + 最短保持后切相邻码 |
| 测试 | [tb/window_dc](tb/window_dc/run.py)、`digital/pll/tb/tb_pll_coarse_ctrl.sv` | 窗口翻转点 45 条件 × 电阻角；控制器对行为环路 |

感测 z 而不是 ctrl：锁定时直流相同，没有 CP 纹波，比较器栅的回踢进 18 pF 的 Ci。
