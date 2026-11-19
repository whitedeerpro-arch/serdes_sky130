# `pll_cp_steer_pdk` — SKY130 PDK Current-Steering Charge Pump Layout (v3)

- **生成器**：`analog/pll/cp/layout/build_cp_steer_pdk.py`
- **对应电路**：`analog/pll/cp/spice/charge_pump_steer.spice`（采用 `analog/pll/top/spice/pll_core_r6k4q.spice` 的 `k = 4 / Icp = 200 µA` 实例参数，未修改设计网表）
- **签核构建目录**：`results/layout/pll_cp/20261120_steer_pdk_v3/`
- **独立复核目录（含 RCX）**：`results/layout_review/pll_cp_steer_20261120_v3/`

## 结构与几何对比（v2 → v3）

| 版本 | 尺寸 (µm) | 面积 (µm²) | 器件数 | DRC (full) | LVS | 属性误差 | 浮空 Poly | `out` CPEX (fF) | `dum` CPEX (fF) | RCX 电阻数 (`devices_preserved`) |
|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|
| v2 (`20261114`) | `127.58 × 40.60` | `5,179.75` | `19` | `0` | `MATCH` | `False` | `0` | `23.567` | `51.643` | `1,118` (`True`) |
| **v3 (`20261120`)** | **`56.58 × 38.45`** | **`2,175.50` (-58.0%)** | **`19`** | **`0`** | **`MATCH`** | **`False`** | **`0`** | **`16.112` (-31.6%)** | **`48.096`** | **`1,751` (`True`)** |

- 导出端口（8/8 精确匹配）：`up dn out vbn vbp ibias vdd vss`（`up/dn/vbn/vbp/ibias/vdd/vss` 位于左侧，`out` 位于右侧且上下夹持接地 `vss` 屏蔽线）。
- 器件提取：`44 × pfet_01v8`、`32 × pfet_01v8_lvt`、`20 × nfet_01v8`、`8 × nfet_01v8_lvt`、`1 × cap_mim_m3_1 (12.08 × 12.08 µm)`，总扩散面积 `AD=AS` 从 `77.29 µm²` 降至 `72.36 µm²`（-6.4%）。

## v3 版图要点

- **三列紧凑左进右出模拟架构（56.58 × 38.45 µm）**：
  - **列 1（左侧，驱动级）**：`Xupn/Xupp`、`Xdn1`、`Xdn2` 紧凑排布，栅极朝内对接中心通道、源极直连顶底电源轨，右侧以垂直 `P+/N+` 护墙与模拟核隔离。
  - **列 2（中部，主镜像与共质心电流舵开关）**：两排堆叠 `Xp (2×pmir8, 80/1)` 与底部 `Xn (nmir4, 20/1)` 通过双对称 `M3` 跳线直连同轴放置的共享扩散 **ABBA 共质心** 开关 `Xps/Xpd (psw16)` 与 `Xns/Xnd (nsw8)`；`out` 与 `dum` 漏极以对称平行 `M2` 竖干引出，`out` 对 `vdd` 耦合仅 `0.305 fF`、对 `up` 仅 `0.089 fF`。
  - **列 3（右侧，跟随器 OTA 与 3D 堆叠 `Cdum`）**：相邻偏置镜像 `Xbd/Xt`、共享扩散 **ABBA 共质心** LVT NMOS 差分对 `Xa/Xb (inlvt8)`、两排互补 **2D 共质心** (`ABBA/BAAB`) LVT PMOS 负载 `Xla/Xlb (2×ldlvt16)`；正上方 3D 堆叠 `Cdum = 0.3 pF` (`cap_mim_m3_1`)，下极板 `M3` 宽线直落底边 `vss` 轨兼作屏蔽。
- **全偏置 Dummy 与完整护环/电源网**：所有模拟镜像、开关及 OTA 阵列两侧均加设与沟长匹配的偏置场多晶硅 dummy（全接 `vdd`/`vss`，零浮空非器件 poly）；连续单 `nwell`、四周及列间 `P+/N+` 护墙、全宽四层 `M1–M4` 电源轨。
