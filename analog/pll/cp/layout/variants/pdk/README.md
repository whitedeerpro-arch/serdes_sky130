# `pll_cp_steer_pdk` — SKY130 PDK Current-Steering Charge Pump Layout

- **生成器**：`analog/pll/cp/layout/build_cp_steer_pdk.py`
- **对应电路**：`analog/pll/cp/spice/charge_pump_steer.spice`（采用 `analog/pll/top/spice/pll_core_r6k4q.spice` 的 `k = 4 / Icp = 200 µA` 实例参数，未修改设计网表）
- **最新签核运行**：`results/layout/pll_cp/20261114_steer_pdk_v2/`

## 结构与几何指标

| Cell | 尺寸 (µm) | 面积 (µm²) | 器件数 | DRC (full) | LVS | 属性误差 | 导出端口 |
|---|---:|---:|---:|---:|---|---|---|
| `pll_cp_steer_pdk` | `127.58 × 40.60` | `5,179.75` | `19` (含 `Cdum`) | `0` | `MATCH` | `False` | `up dn out vbn vbp ibias vdd vss` |

## 版图要点

- **左进右出单向控制流**：左侧接收来自 PFD 的 `up / dn` 脉冲及偏置 `vbn / vbp / ibias`，中部放置 `Xp (80/1, nf=16)` / `Xn (20/1, nf=4)` 主镜像与对称电流舵开关 `Xps / Xpd`、`Xns / Xnd`，右侧输出 `out` 直接朝向环路滤波器 `ctrl` 与 VCO `vctrl`。
- **共质心单位增益缓冲器**：`dum` 节点跟随器采用一维共质心 `[Xa0, Xb0, Xb1, Xa1]` LVT NMOS 差分对（`win = 24 µm, l = 1 µm`）与纵向严格对齐的 `[Xla0, Xlb0, Xlb1, Xla1]` LVT PMOS 有源负载（`wl = 96 µm, l = 1 µm`），抑制失调引起的静态充放电偏置。
- **3D 堆叠 `Cdum = 0.3 pF`**：在跟随器正上方 `metal3 / metal4` 叠放 `sky130_fd_pr__cap_mim_m3_1`（`w = 12.08 µm, l = 12.08 µm -> 299.81 fF`），下极板接 `vss` 兼作屏蔽层，零额外硅面积开销。
