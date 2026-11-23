# `pll_vco_ptat_bias_pdk` — SKY130 PDK VCO PTAT + Constant-Swing Blended Bias Cell (`ptat_bias_pdk`)

Physical SKY130A PDK layout implementing **`serdes_bias_cml_blend_v2`** from `analog/pll/vco/spice/vco_ptat_bias.spice` (verified 135/135 PVT and 45/45 3-temp single-code VCO lock at commit `267245a`).

## Circuit & Physical Summary

| Metric | Value |
|---|---|
| **Cell Name** | `pll_vco_ptat_bias_pdk` |
| **Schematic Reference** | `serdes_bias_cml_blend_v2` (`analog/pll/vco/spice/vco_ptat_bias.spice`) |
| **Active Devices** | `Xconst`: `28 × 8/4 µm` (`W=224, L=4`) `pfet_01v8_lvt` (`vgi`) + `Xptat`: `66 × 14/6 µm` (`W=924, L=6`) `pfet_01v8_lvt` (`vg`) = `94` total fingers |
| **BBox / Footprint** | `[-74.20, -1.00, +74.60, +60.60] µm` → **`148.80 × 61.60 µm`** (`AR = 2.42`) |
| **Area** | **`9,166.08 µm²`** |
| **Magic Full-Rule DRC** | **`0`** |
| **Netgen LVS / Prop Errors / Disconnected** | **`MATCH` / `0` / `0`** |
| **Floating Poly** | **`0`** (tied outer field-poly dummies contacted via `polycont+locali+viali+M1` to `vdd` N-tap) |
| **M5 Usage** | **`0.0%`** (`0` `metal5` rectangles; strictly M1–M4) |
| **Independent `review_cell.py --rc`** | **PASS (`checker_exit = 0`, `physical_passed = True`, `1,288` R ≥ 1 Ω, `devices_preserved = True`)** |

## Perimeter Ports (Exact `serdes_bias_cml_blend_v2` Order)

| Port | Layer | Coordinates (µm) | Edge | CPEX Total Node Cap (fF) | Integration Hookup |
|---|---|---:|---|---:|---|
| `out` | `metal4` | `(+74.00, 29.00)` | East | `290.610` | `icml_vco` current output → local `serdes_bias_cml_v2_pdk.iin` |
| `vgi` | `metal2` | `(-74.00, 1.06)` | West | `111.547` | BIAS v2 internal constant-swing gate `vgi` |
| `vg` | `metal2` | `(-74.00, 27.86)` | West | `458.166` | BIAS v2 internal bandgap PTAT gate `vg` |
| `vdd` | `metal4` | `(0.00, 59.60)` | Top (+ full bottom M4 rail at `y=0.00`) | `1,467.718` | `1.8 V` analog supply rail |

## Layout Architecture Highlights

- **4-Row Even-Finger Array in Continuous N-Well**: `Row 0` (`Xconst`, `nf=28`) and `Rows 1..3` (`3 × Xptat`, `nf=22` each) all use even finger counts so every outer S/D diffusion is tied to `vdd`, shielding `out` drains from perimeter walls and matching `ad = as = 173.71 µm²` (`pd = ps = 1,226.42 µm`).
- **Latchup Margin (`LU.3`)**: Continuous closed `nsubdiff` guard ring plus full-width horizontal N-tap bars between every row keep max P-diff-to-N-tap distance `≤ 7.8 µm` (`< 15 µm` limit).
- **Sub-Ohm `out` Collector (`0.0%` M5)**: 6 vertical M3 `vdd` spines strap top/bottom M4 `vdd` rails; 4 vertical M3 `out` spines merge onto a central M4 `out` collector (`y = 29.00 µm`) with `2×2` `via3` arrays (`out` has zero segments ≥ 1 Ω in native `1 Ω` RCX).
- **Abutment Compatibility**: Width `148.80 µm` fits cleanly inside `serdes_bias_top_v2_pdk` (`176.53 µm` wide), and height `61.60 µm` fits cleanly alongside `pll_vco_core_sym9_s32p5_clean` (`79.80 µm` tall).

## Files & Reproduction

- Generator: `analog/pll/vco/layout/build_vco_ptat_bias_pdk.py`
- Signoff build dir: `results/layout/pll_vco/ptat_bias_pdk/build_v2/`
- Independent `review_cell.py --rc` audit: `results/layout/pll_vco/ptat_bias_pdk/review_rc_v1/`
