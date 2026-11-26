# RX 2 GHz 64-Code Pure CMOS Phase Interpolator — Analog Canvas 投稿包

本目录为 [analog-canvas.tokenzhang.com](https://analog-canvas.tokenzhang.com)（`cascode-ai/analog-canvas`）整理的**零外部依赖、分层 Cell 结构**投稿素材，直接对应项目主线电路 [rx_cmos_pi.spice](../../../../analog/rx/cmos_rx/spice/rx_cmos_pi.spice)。

## 文件清单

| 文件 | 用途 |
|---|---|
| `rx_cmos_pi_canvas.sp` | 自包含 5-Cell 分层结构化 SPICE 网表（标准 4 端 `M` / `R` / `C`，无自定义 `X` 封装依赖，可直接 `File → Import SPICE / SCS…`） |
| `../../../figures/schematics/rx_pi_stacked_slices.svg` | ISSCC 页状叠起参考原理图（对应 1-leg 顶层与单切片晶体管摆位） |
| `../../../figures/rx/pi/rx_pi_schematic_explained.png` | 4 联架构与原理导读图（8 相圆、5 级信号流、RC 线性混相波形、确定性正交 ÷2） |

## 导入与摆位建议（3 步出精品）

1. **导入网表**：在 Analog Canvas 中选择 **`File → Import SPICE / SCS…`**，选择 `rx_cmos_pi_canvas.sp`。工具会自动解析出 5 个独立分层 Cell：
   - `pi_tgate_lvt`（2 管：静态 LVT 传输门）
   - `pi_mux4_tg`（4 路 LVT 传输门 + 反相输出级）
   - `pi_slice_r`（**核心叶单元**：有效加权支路 + 5.8 kΩ 汇加电阻 + 互补无源 MOS 门电容 Dummy）
   - `pi_ac_rec_1leg`（**亮点恢复级**：37 fF 隔直 + 12.3 kΩ 负反馈自偏置 LVT 反相器 + 匹配输出级）
   - `rx_cmos_pi_1leg`（**顶层展示 Cell**：`2× pi_mux4_tg` + `8× pi_slice_r` 整齐并排汇入 `mix` + `37 fF Cmix` + `1× pi_ac_rec_1leg`）
2. **推荐视觉摆位**：
   - 先把 `pi_slice_r` 与 `pi_ac_rec_1leg` 两张叶单元按经典左进右出、VDD 在上 / VSS 在下排齐（参考 [rx_pi_stacked_slices.png](../../../figures/schematics/rx_pi_stacked_slices.png) 中景与右侧）；
   - 再在顶层 `rx_cmos_pi_1leg` 中将 `Xmux_a / Xmux_b` 放左侧、`Xs0..Xs7` 垂直或水平等距排成一列（公共 `mix` 干线拉直并挂 `Cmix = 37 fF`）、`Xrec` 放右侧，整体画面非常清爽。
3. **发布到 Community Gallery** 时可直接复用下方中英文卡片文案。

---

## Gallery 发布文案参考（可直接粘贴）

**Title**
> `2 GHz 64-Code Pure CMOS Resistor-Linearized Phase Interpolator (SKY130A 1.8 V, ~7 mW)`

**Tags**
> `SerDes` · `Phase Interpolator` · `CDR` · `SKY130` · `Pure CMOS` · `Low Power` · `2 GHz`

**Description**
> Ultra-low-power, zero-CML 2 GHz 64-code phase interpolator designed in SKY130A 1.8 V for a 4 Gb/s quarter-rate NRZ SerDes receiver (`~7 mW` total for full 32-slice Data+Edge differential array + deterministic quadrature ÷2, `|INL| <= 0.015 UI` across extreme PVT corners down to `SS 1.65 V -40 °C`).
>
> **Key Circuit Highlights:**
> 1. **Glitch-Free Even/Odd 4:1 LVT-TG Coarse Mux (`pi_mux4_tg`)**: Separates 8 PLL 2 GHz anchor clocks (45° = 62.5 ps spacing) into Even Bank A (`c0,c2,c4,c6`) and Odd Bank B (`c1,c3,c5,c7`). Static DC control bits incur zero switching power; inactive bank switches silently at 0% weight (`f = 0x00 / 0xFF`) for zero-glitch octant handoff.
> 2. **Constant-Load Resistor-Linearized 8-Slice Mixer (`pi_slice_r` ×8)**: Each slice uses a lean CMOS inverter driving a `5.8 kΩ` high-poly resistor into a shared `37 fF` MIM cap (`τ_mix ≈ 43 ps`) to linearize phase weighting (`7.81 ps = 1/32 UI` per fine code). A complementary passive gate-cap dummy (`S=D` tied to `VDD/VSS`) keeps `C(ca) = C(cb)` constant across all codes (`0.00 ps` parabolic bow, zero switching current).
> 3. **Zero-Static-DC AC-Coupled Self-Biased LVT Recovery (`pi_ac_rec_1leg`)**: A `37 fF` MIM cap + `12.3 kΩ` negative DC feedback resistor auto-biases a matched `Wp/Wn = 4.00` LVT-PMOS/LVT-NMOS inverter right at `V_M = VDD/2` (`~0.34 ns` settling), guaranteeing 50.0% duty cycle without tail bias even at `SS 1.65 V -40 °C`.
>
> *Full chip instantiates 4 copies of `rx_cmos_pi_1leg` (Data `0°/180°` + Edge `+90°/+270°` = 32 slices) followed by a master-resampled deterministic quadrature ÷2 divider (`serdes_rx_qdiv2_8ph`).*
