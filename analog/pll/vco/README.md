# 4G 环振 VCO（`analog/pll/vco/`）

4.0 Gb/s PLL v4 主线采用的四级差分 CML 环振 VCO（**`r6`**，2.0 GHz、5-bit 融合 MIM 电容阵粗调 + LVT 变容管细调 + BIAS v2 PTAT `28/66` 尾流温补，八相输出）。5.0 Gb/s 双速演进采用的八边形电感 LC-VCO 位于独立目录 [`../vco_5g/README.md`](../vco_5g/README.md)。

- **设计报告**：[VCO r6 + PTAT `28/66` 码窗报告](../../../docs/design/pll_vco_r6_ptat.md) · [r6 `sym9_clean` CPEX 与相噪/抖动报告](../../../docs/design/pll_vco_r6_perf.md) · [sym9 版图教训](../../../docs/layout/vco_sym9_layout_lessons.md)

## 现行源码与 PDK 版图

| 位置 | 角色与状态 |
|---|---|
| [`spice/vco_ring4_r6.spice`](spice/vco_ring4_r6.spice) · [`spice/vco_delay_r6.spice`](spice/vco_delay_r6.spice) · [`spice/cap_bank_5b.spice`](spice/cap_bank_5b.spice) | **主线 `r6` 5-bit 四级环振 VCO**（`cwire = 12 fF/node` 寄生预算、成对长多晶负载 `res_high_po_2p85`） |
| [`spice/vco_ptat_bias.spice`](spice/vco_ptat_bias.spice) | BIAS v2 `28/66` 恒摆幅 + PTAT 混流尾偏置（实现 45/45 跨三温单一共同码覆盖、高温摆幅全过 `≥ 400 mVpp`） |
| [`layout/README.md`](layout/README.md) · [`layout/variants/sym9_clean/`](layout/variants/sym9_clean/README.md) · [`layout/variants/ptat_bias_pdk/`](layout/variants/ptat_bias_pdk/README.md) | 已签核 `sym9_clean` 2×2 对称环振物理核（`DRC=0 / LVS=MATCH`，CPEX 八相误差 `≤ 0.76 ps`）与 PTAT 偏置宏；版图审阅见 [`layout/review.md`](layout/review.md) |

## 现行测试台

| 脚本 / 目录 | 说明 |
|---|---|
| [`tb/tuning/r6_ptat.py`](tb/tuning/r6_ptat.py) · [`tb/tuning/r6.py`](tb/tuning/r6.py) | 135 条件调谐码窗、跨三温共同码覆盖、摆幅与尾管裕量扫描 |
| [`tb/phase_noise/char_r6_ptat_perf.py`](tb/phase_noise/char_r6_ptat_perf.py) | 5 代表角原理图 vs `sym9_clean` CPEX 对照、20 MHz PSRR、ISF 相噪分解与 PLL v4 抖动合成 |
| [`tb/layout_pex/run.py`](tb/layout_pex/run.py) | VCO 提取版图 CPEX / 寄生频偏验证 |
| [`tb/ctrl_load/README.md`](tb/ctrl_load/README.md) | 振荡态控制端输入电容、变容等效与 `rg` 噪声测量（`r6.py`、`varactor_noise.py`） |
| [`tb/mc/README.md`](tb/mc/README.md) | `r6` 局部失配 MC 初筛（`r6_pilot.py`） |
| [`tb/psrr_lf/run.py`](tb/psrr_lf/run.py) · [`tb/bias_path_ac/run.py`](tb/bias_path_ac/run.py) | 带实际 LF 的电源单音灵敏度与尾偏置线 AC 传递测试 |

结果追加写入 `results/analog/pll/vco/`，执行约定见 [docs/verification/methods.md](../../../docs/verification/methods.md)。
