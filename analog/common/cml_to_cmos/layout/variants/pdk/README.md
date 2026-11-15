# `serdes_cml_to_cmos_pvt_candidate_pdk` — Ultra-Compact Mirror-Symmetric SKY130 PDK CML-to-CMOS Receiver Layout

当前独立结论统一见 [审阅报告](../../review.md)，目录职责见 [模块入口](../../README.md)；本页保留原生成记录。

- **生成器**：`analog/common/cml_to_cmos/layout/build_cml_to_cmos_pdk.py`（Plan C6）
- **历史蓝图**：`analog/common/cml_to_cmos/layout/plan/plan_cml_to_cmos.py`（Plan C2 参考）
- **对应电路**：`analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice` 与 `cml_to_cmos.spice`（完整 48 管差分源极跟随 + 镜像差分转单端 + 时钟恢复锁存器 + 24 颗共享扩散 `l=0.15` Bias Dummy FET + 19 对左右/间隙偏置 Field-Poly Dummy 栅，主电路参数未修改）
- **原生成检查记录**：`results/layout/cml_to_cmos/20261115_pvt_pdk_c6_v3/`

## 结构与几何指标

| 版图迭代 | 尺寸 (µm) | 面积 (µm²) | DRC (full) | LVS | 属性误差 | 导出端口 |
|---|---:|---:|---:|---|---|---|
| `v1` 早期基线 | `134.87 × 71.00` | `9,575.77` | `0` | `MATCH` | `False` | `inp inn outp outn vbias vdd vss` |
| `Plan C2`（单管环卫 + M2 纵连） | `49.38 × 20.365` | `1,005.62` | `0` | `MATCH` | `False` | `inp inn outp outn vbias vdd vss` |
| `Plan C4`（共享阱 + 连续 Poly + Locali + M1 通道） | `43.345 × 13.105` | `568.04` | `0` | `MATCH` | `False` | `inp inn outp outn vbias vdd vss` |
| `Plan C5`（分域合并 NP 环卫 + 初版偏置 Dummy 栅） | `49.735 × 13.785` | `685.60` | `0` | `MATCH` | `False` | `inp inn outp outn vbias vdd vss` |
| **`Plan C6`（加宽显式 NP 保护环 + 独立对齐全覆盖 Dummy 栅）** | **`51.945 × 14.11`** | **`732.94`** | **`0`** | **`MATCH`** | **`False`** | **`inp inn outp outn vbias vdd vss`** |

> 相比 `Plan C2` 在保留显式加宽域级合并保护环、模拟/数字双墙隔离及独立贴边双侧偏置 Dummy 栅的前提下，面积仍缩减 **`27.1%`**（高度 `-30.7%`）；相比早期基线 `v1` 面积缩减 **`92.3%`**。

## Plan C6 核心版图结构

1. **显式加宽分域合并 NP 保护环与 A/D 双墙隔离**：
   - 水平顶/底轨（`Y_VDD = ±6.690 µm`）采用 **`0.350 µm`** 宽 `psubdiff`/`nsubdiff`（`0.200 µm` `M1` 居其中），中心 `VSS` 脊柱采用 **`0.250 µm`** 宽 `psubdiff`（`0.180 µm` `M1` + `viali` 局部焊盘），垂直域间壁 **`0.360 µm`**、左右最外框 **`0.440 µm`**（宽于 `0.320 µm M2`），全框绿/青色有源区保护环清晰包络。
   - **Domain A（模拟 SF + Tail）**：闭合四面 `psubdiff` 衬底保护环包围；**Domain B（模拟差分转单端）**：左/右 `psubdiff + nsubdiff` 一体化立柱合并顶底轨；与 **C1/C2/C3 数字域**间保持双墙基底隔离，在 `y = ±3.320 µm` 为 `poly/locali` 通道留空。
2. **VDD (P) / VSS (N) 偏置工艺匹配 Dummy 栅（尺寸与位置全校准）**：
   - 所有 Field-Poly Dummy 栅统一补齐外侧 **`+0.130 µm`** `poly` 悬伸端帽，并按 NMOS 与 PMOS 各自实际扩散边界独立放置（不再使用 `max(hw_n, hw_p)`）。
   - `Domain A` 对 `Xsp`、`Xtail`（`L=0.50`）与 `Xfp`（`L=0.15`）两侧等距对称置 Dummy；`Domain B` 在 `Xip/Xin`（`nf=3`）两侧各增设**双指翼** `VSS` 偏置 Field-Poly Dummy 与 `Xlp/Xln`（`nf=4+2`）轮廓匹配；数字区 `bp-L`、`bp_n-R`、`dp1_n-L`、`dp3-R`、`setb-L`、`qpa-R`、`rp1-L` 逐管贴边对齐，消除短指纹与宽指纹间的密度空档；`Xlp/Xln`、`op/on`、`opr/onr` 保留 `nf+2` 共享扩散偏置 Dummy 指并完整写入 `_ref.spice`。

## 版图视图

- **全版图总览**：[`serdes_cml_to_cmos_pvt_candidate_pdk.png`](serdes_cml_to_cmos_pvt_candidate_pdk.png)
- **三段放大细节**：[`cml_to_cmos_c6_zoom.png`](cml_to_cmos_c6_zoom.png)
