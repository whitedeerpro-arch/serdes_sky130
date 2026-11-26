# PLL 环路滤波器（`analog/pll/loop_filter/`）

4.0 Gb/s PLL v4 主线与 5.0 Gb/s Plan-C 共享的二阶无源 `k = 4` 环路滤波器（`Rz = 4.13 kΩ`、`Ci = 18.38 pF` 12/6 电源分接、不另加 `Cf`、配双节点普通 NMOS + LVT PMOS 预充传输门）。完整环路选型、电源分接推导与验证记录见 [docs/design/pll_loop.md](../../../docs/design/pll_loop.md)。

## 现行源码、版图与测试台

| 文件 / 目录 | 角色与状态 |
|---|---|
| [`spice/passive_rc_pdk_k4.spice`](spice/passive_rc_pdk_k4.spice) | **主线 PDK `k = 4` 环路滤波器**（`res_high_po_0p69` + 18 颗显式实例化 1 pF `cap_mim_m3_1`，12 接 `VDD` / 6 接 `VSS` + 双节点预充门） |
| [`spice/passive_rc_precharge.spice`](spice/passive_rc_precharge.spice) | 早期理想 R/C 双节点预充原型参考 |
| [`layout/README.md`](layout/README.md) · [`layout/variants/fused_pdk/`](layout/variants/fused_pdk/README.md) | 融合 6 站点 MIM1+MIM2 叠层 PDK 版图 `v2`（`6,382 µm²`，`DRC=0 / LVS=MATCH`，`ctrl` 寄生较离散 MIM 降 `−41.4%`；审阅见 [`layout/review.md`](layout/review.md)） |
| [`tb/layout_pex/run.py`](tb/layout_pex/run.py) | 原理图 / CPEX / 原生 RCX 的 AC 阻抗与双节点预充对比验证脚本 |

注意：SKY130A 中 `cap_mim_m3_1` 的 `mf` 参数仅进入失配项而不乘名义电容，见 [docs/verification/statistics.md](../../../docs/verification/statistics.md#sky130a-失配与高阻多晶硅热噪声边界pdk-实测核对)。所有运行输出追加写入 `results/analog/pll/loop_filter/`。
