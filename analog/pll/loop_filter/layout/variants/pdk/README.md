# `pll_loop_filter_k4_pdk` — 3D Under-MIM SKY130 PDK Loop Filter Layout

当前独立结论统一见 [审阅报告](../../review.md)，目录职责见 [模块入口](../../README.md)；本页保留原生成记录。

- **生成器**：`analog/pll/loop_filter/layout/build_lf_pdk.py`
- **对应电路**：`analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice`（`pll_loop_filter_k4`，未修改设计网表；零压测量连线 `Vlink cp_in ctrl 0` 按 `docs/layout/pll_r6.md` 并入物理端口 `ctrl`）
- **原生成检查记录**：`results/layout/pll_lf/20261114_pdk_v1/`

## 结构与几何指标

| Cell | 尺寸 (µm) | 面积 (µm²) | MIM 单元数 | DRC (full) | LVS | 属性误差 | 导出端口 |
|---|---:|---:|---:|---:|---|---|---|
| `pll_loop_filter_k4_pdk` | `154.42 × 80.46` | `12,424.63` | `18` (`6 VSS + 12 VDD`) | `0` | `MATCH` | `False` | `ctrl z pre_ref pre_en vdd vss` |

## 版图要点

- **一维共质心电源纹波分配 `[VDD, VSS, VDD, VDD, VSS, VDD]`**：采用 `6 × 3` 共 18 颗 `sky130_fd_pr__cap_mim_m3_1`（`w = 22.1965 µm, l = 22.1965 µm`），上极板 `metal4` 汇入积分节点 `z`，下极板 `metal3` 按列对称引出第 `0, 2, 3, 5` 列（12 颗）接 `vdd`、第 `1, 4` 列（6 颗）接 `vss`。
- **`ctrl` 敏感控制节点减少直接 VDD 耦合**：零点电阻 `Xrz`（`res_high_po_0p69, l = 7.59 µm`）与快充传输门 `Xfast` 完全置于第 1 列接 `vss` 的 MIM 下极板正下方，`ctrl` 走线仅与接地 `metal3` 底板重叠，不穿过任何接 `vdd` 的底板。
- **3D Under-MIM 正交走线**：阵列下方仅使用 `locali / metal1`（横向）与 `metal2`（纵向）放置 `Xrz`、`Xinv`、`Xfast`、`Xint`，阵列内部零 `via2 / metal3 / metal4` 穿刺，整块环路滤波器零额外硅面积开销。
