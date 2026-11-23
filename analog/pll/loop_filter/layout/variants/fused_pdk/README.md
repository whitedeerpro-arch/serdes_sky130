# `pll_loop_filter_k4_fused_pdk` — 3×2 Stacked `MIM1+MIM2` Under-MIM SKY130 Loop Filter Layout (v2 Compact)

当前独立审阅历史见 [审阅报告](../../review.md)，目录职责见 [模块入口](../../README.md)；本页记录当前已安装的 v2 紧凑堆叠融合版。

- **生成器**：`analog/pll/loop_filter/layout/build_lf_fused_pdk.py`
- **平面 Plan**：`analog/pll/loop_filter/layout/plan/plan_lf.py`（[plan 图](../../plan/lf_plan.png)、[数据](../../plan/lf_plan.json)）
- **对应电路**：`analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice` 的 `.subckt pll_loop_filter_k4_fused`（原 `pll_loop_filter_k4` 未修改；零压测量连线 `Vlink cp_in ctrl 0` 并入物理端口 `ctrl`）
- **v2 签核构建目录**：`results/layout/pll_lf/20261120_fused_compact/`
- **v2 独立复核目录（含 RCX）**：`results/layout_review/pll_lf_fused_20261120/`

## 结构与几何对比

| 变体 | Cell | 尺寸 (µm) | 面积 (µm²) | DRC (full) | LVS | 属性误差 | 浮空 Poly | `ctrl` CPEX (fF) | RCX 电阻数 (`devices_preserved`) |
|---|---|---:|---:|---:|---|---|---:|---:|---:|
| 原 18 颗方案 | `pll_loop_filter_k4_pdk` | `154.42 × 80.46` | `12,424.63` | `0` | `MATCH` | `False` | `0` | `17.47` | — |
| 融合堆叠 v1 (`20261117`) | `pll_loop_filter_k4_fused_pdk` | `98.34 × 70.10` | `6,893.63` (-44.5%) | `0` | `MATCH` | `False` | `0` | `11.920` (对地 `8.913`) | `483` (`True`) |
| **融合堆叠 v2 紧凑版 (`20261120`)** | **`pll_loop_filter_k4_fused_pdk`** | **`98.34 × 64.90`** | **`6,382.27` (-48.6% vs 原版 / -7.4% vs v1)** | **`0`** | **`MATCH`** | **`False`** | **`0`** | **`6.984` (-41.4% vs v1; 对地 `4.451`)** | **`480` (`True`)** |

- 导出端口（6/6 精确匹配）：`ctrl z pre_ref pre_en vdd vss`。
- 器件提取：`6 × sky130_fd_pr__cap_mim_m3_1`、`6 × sky130_fd_pr__cap_mim_m3_2`（`w=27.22, l=27.22 <= 30.0 µm` PCell 上限，2:1 `vdd:vss`）、`1 × sky130_fd_pr__res_high_po_0p69 (l=7.59 µm)`、`8 × nfet_01v8`、`4 × pfet_01v8`、`12 × pfet_01v8_lvt`。

## v2 紧凑版升级要点

- **顶底汇流排压至 `met5.2` 物理下限（高 `70.10 → 64.90 µm`，省 `5.20 µm` / `511 µm²`）**：
  - 顶部 `z` M4 汇流排收紧至 `y = +30.02`，`Col 1` VSS M5/M3 汇流排收紧至 `y = +31.65`（顶边 `+32.45`，`met5.2 = 1.63 µm >= 1.60 µm`、`met4.2 = 0.38 µm >= 0.30 µm`），顶部省去 `3.17 µm`。
  - 底部 `Col 0/2` VDD 以 M5 在 `y = -31.65`（底边 `-32.45`）直连，去掉跨 `Col 1` 的冗余 M3 桥，使 `ctrl` M3 端口（`y = -32.00`）齐平收入底框内，底部省去 `2.03 µm`。
- **Under-MIM 器件区迁入 `Col 1` 下半区（`y ≈ -20.0 µm`）并重构顺序 `[Xinv, Xint, Xfast] + Xrz`**：
  - S/D M2 梳状母线直接压在有源扩散上方，CMOS 孤岛高度从 `10.40 µm` 缩至 `9.40 µm`（`16.65 × 9.40 µm`），完整保留 2026-11-17 审阅全部修复：12 根沟长匹配偏置场多晶硅 MOS dummy（6 NMOS 接 `vss`、6 PMOS 接 `vdd`）、`Xrz` 两侧接地 `0.69 µm` poly dummy、共享 `P+/N+` 护环框及连续 `nwell`、零浮空非器件 poly。
  - `Xrz` 移至右侧紧邻 `Xfast` 并贴近底边：`pre_ref / pre_en / vdd` 从左侧直入 CMOS 孤岛，**彻底消除跨 `Xrz` 的 M2 跨桥与顶部 `vdd` 跨越**；`ctrl` 金属走线由约 `35 µm` 缩短至约 `14 µm`，`ctrl` 总寄生电容从 `11.920 fF` 降至 `6.984 fF`（对地从 `8.913 fF` 降至 `4.451 fF`，-50.1%）。
- **图像检查**：[整图](pll_loop_filter_k4_fused_pdk.png)、[Under-MIM 局部放大图](pll_lf_fused_under_mim.png)。
