# `pll_loop_filter_k4_fused_pdk` — 3×2 Stacked `MIM1+MIM2` Under-MIM SKY130 Loop Filter Layout

当前独立结论统一见 [审阅报告](../../review.md)，目录职责见 [模块入口](../../README.md)；本页保留原生成记录。

2026-11-17 dummy 修订已独立重建及复核，当前身份和七点 CPEX 回归见[新版索引](../../../../../../results/catalog/pll_pending_lf_review_20261117.json)。11 月 15 日的原生 RC 与旧几何记录仅属于当时输入。

- **生成器**：`analog/pll/loop_filter/layout/build_lf_fused_pdk.py`
- **平面 Plan**：`analog/pll/loop_filter/layout/plan/plan_lf.py`（[plan 图](../../plan/lf_plan.png)、[数据](../../plan/lf_plan.json)）
- **对应电路**：`analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice` 新增候选 `.subckt pll_loop_filter_k4_fused`（原 `pll_loop_filter_k4` 未修改；零压测量连线 `Vlink cp_in ctrl 0` 并入物理端口 `ctrl`）
- **原生成检查记录**：`results/layout/pll_lf/20261115_fused_stack6_v9/`

## 结构与几何对比

| 变体 | Cell | 尺寸 (µm) | 面积 (µm²) | MIM 结构 | DRC (full) | LVS | 属性误差 |
|---|---|---:|---:|---|---:|---|---|
| 原 18 颗方案 | `pll_loop_filter_k4_pdk` | `154.42 × 80.46` | `12,424.63` | 18 颗 `MIM1` (`22.1965 µm`，`6 VSS + 12 VDD`) | `0` | `MATCH` | `False` |
| **融合堆叠方案** | **`pll_loop_filter_k4_fused_pdk`** | **`98.34 × 70.10`** | **`6,893.63` (-44.5%)** | **6 站点堆叠 `MIM1+MIM2` (`27.22 µm`，`2×2 VSS + 4×2 VDD`)** | **`0`** | **`MATCH`** | **`False`** |

- 导出端口：`ctrl z pre_ref pre_en vdd vss`（与 `pll_loop_filter_k4_pdk` 一致；`pre_ref`/`pre_en` 缩进外侧 `M5` 悬臂区下方 `x=-49.60, y=0.00/-0.96` 经短 `M2` 跨桥越过 `Xrz` 并交错穿过两排 MIM 间空隙，`ctrl` 端口贴近底边 `x=-10.80, y=-34.22`）。
- 器件提取：`6 × sky130_fd_pr__cap_mim_m3_1`、`6 × sky130_fd_pr__cap_mim_m3_2`（`w=27.22, l=27.22 <= 30.0 µm` PCell 上限）、`1 × sky130_fd_pr__res_high_po_0p69 (l=7.59 µm)`、`8 × nfet_01v8`、`4 × pfet_01v8`、`12 × pfet_01v8_lvt`。

## 版图要点

- **三明治堆叠保持 1:2 电源纹波抵消 (`[VDD, VSS, VDD]`)**：每站点叠放 `cap_mim_m3_1`（M3–M4，1.500 pF）与镜像对齐的 `cap_mim_m3_2`（M4–M5，1.500 pF），共享中间 `metal4` 极板接入积分节点 `z`，下 `metal3` 与上 `metal5` 极板同接列电源（`col 0, 2` 接 `vdd` 共 12 pF，`col 1` 接 `vss` 共 6 pF）。
- **`Col 1` 侧置带 Dummy 电阻 + 紧缩 CMOS 孤岛 + 共享双保护环**：
  - `Xrz` 移至 `Col 1` 左侧（`dx=-10.80, dy=0.00`），两侧加设 `0.69 µm` 纯多晶硅 dummy 条（`x=-12.45, -9.15`，`polycont+locali+M1` 钳位 `vss`，无 `xpolycontact` 不增改网表）；自带 `psubdiff` 环用四边 `M1 + 12 点 viali` 钳位 `vss`。
  - 紧邻右侧 `Xfast + Xinv + Xint`（`dx=-3.80, +0.50, +6.00`，`dy_n=-3.10`, `dy_p=+3.10`）去掉独立冗余环后紧缩为 **`16.5 × 10.4 µm`** 的单框双环 CMOS 孤岛（`guard frame [-6.65, -5.20]..[+9.85, +5.20]`）；顶部 3 颗 PMOS（`pfet_01v8_lvt` 与标准 `pfet_01v8`）**Y 向镜像使栅极朝内**，共用连续 `nwell`（`x=[-7.10, +10.30], y=[1.45, 5.65]`）与 VDD `nsubdiff` 保护框，底部 NMOS 共用 VSS `psubdiff` 保护框；每颗 NMOS（6 根接 `vss`）与每颗 PMOS（6 根接 `vdd`）两侧均加设偏置场多晶硅 dummy 栅极。
  - 中间 `y in [-0.96, +0.96]` 布设 5 条 `0.48 µm` 节距 `M1` 信号轨；MIM 投影区内部仅使用 `locali / metal1 / metal2`，所有 `via2/via3/via4` 换层孔全部落在阵列外部或间隙通道。
- **图像检查**：[整图](pll_loop_filter_k4_fused_pdk.png)、[Under-MIM 局部放大图](pll_lf_fused_under_mim.png)。

## SPICE 电学等价性复核（TT, 1.8 V, 27 °C）

实测脚本及原始波形位于 `results/layout/pll_lf/20261115_fused_stack6_v9/tb_compare.cir`（[汇总 JSON](../../../../../../results/layout/pll_lf/20261115_fused_stack6_v9/compare_summary.json)）：

| 指标 | `k4` 原理图 | `k4_pdk` 版图 PEX | `k4_fused` 原理图 | `k4_fused_pdk` 版图 PEX |
|---|---:|---:|---:|---:|
| 等效 `Ci @ 10 kHz` (pF) | `18.0207` | `18.8767` | `18.0181` | `18.8254` |
| 零点电阻 `Rz @ 20 MHz` (Ω) | `4126.97` | `4117.79` | `4127.01` | `4120.49` |
| `|V(ctrl)/V(vdd)| @ 20 MHz` | `0.66647` | `0.66476` | `0.66643` | `0.66466` |
| 预充后 `ctrl` (`1.99 µs` → `3.00 µs`, V) | `1.40000 → 1.40153` | `1.40000 → 1.40162` | `1.40000 → 1.40153` | `1.40000 → 1.40156` |
