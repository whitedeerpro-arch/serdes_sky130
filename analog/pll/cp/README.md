# PLL 电荷泵（`analog/pll/cp/`）

4.0 Gb/s PLL v4 主线与 5.0 Gb/s Plan-C 共享的 `Icp = 200 µA` 电流转向电荷泵模块，采用 1/4 单位指副本主动伺服匹配环与宽摆幅 PMOS 主支路。完整设计推导与 135 角验证数据见 [docs/design/pll_cp_v4.md](../../../docs/design/pll_cp_v4.md)，环路集成见 [docs/design/pll_loop.md](../../../docs/design/pll_loop.md)。

## 现行源码、版图与测试台

| 文件 / 目录 | 角色与状态 |
|---|---|
| [`spice/charge_pump_steer_v4.spice`](spice/charge_pump_steer_v4.spice) | **主线共享 CP v4**（8 端口 `up dn out vbn vbp ibias vdd vss`）：135 角 UP/DN 失配 `0.193%`（降 58×），`1.65 V` 线性上限 `1.49 V` |
| [`spice/charge_pump_steer_v4_en.spice`](spice/charge_pump_steer_v4_en.spice) | 带 `en` 门控端口的 CP v4（供启动序列控制使用） |
| [`layout/build_cp_steer_v4_pdk.py`](layout/build_cp_steer_v4_pdk.py) · [`layout/variants/v4_pdk/`](layout/variants/v4_pdk/README.md) | 已签核 PDK 版图（`58.98 × 43.70 µm = 2,577.43 µm²`，Magic `DRC=0`、Netgen `LVS=MATCH`、`M5=0%`、`out` CPEX `19.94 fF`） |
| [`tb/dc/verify_cp_v4.py`](tb/dc/verify_cp_v4.py) | CP v4 135 角 DC、伺服环 AC 稳定性、250 MHz 瞬态与 6 角 CPEX DC 综合验收脚本 |

历史开关/噪声/输出电容测试目录（`tb/ripple/`、`tb/noise/`、`tb/out_cap/`）保留作局部参考；所有运行产物追加写入 `results/analog/pll/cp/`。
