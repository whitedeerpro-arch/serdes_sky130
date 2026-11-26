# `v2_cur_kelvin_pdk` — Shielded Coaxial Kelvin Return & Shortened FB Variant of LDO `v2_cur`

Isolated layout optimization candidate addressing the active-placement review ([`chip_floorplan_20261123.md#6-11-25-有源器件排布复核`](../../../../../docs/layout/chip_floorplan_20261123.md#6-11-25-有源器件排布复核)) while keeping frozen [`../v2_cur_pdk/`](../v2_cur_pdk/README.md) 100% untouched.

## Preserved Architectural & Physical Invariants
- **Distal load-side Kelvin tap**: preserved at `(304.8, -48.5)` on the `quiet` M4/M5 power plate.
- **47-bar common-centroid divider**: `rdiv26`/`rdiv21` matching structure and `m_cff` placement preserved verbatim.
- **Domain power & perimeter contract**: identical `13/13` production and `15/15` probe external port locations/layers (`Ports identical = True`), macro footprint strictly within baseline (`312.52 × 121.42 µm` prod / `312.52 × 121.44 µm` probe).
- **Backward compatibility**: default `build_ldo_v2_cur_pdk.py` (without `--kelvin-opt`) reproduces frozen `v2_cur_pdk` `.mag` bit-for-bit.

## Routing Changes (`--kelvin-opt`)
1. **Coaxial-shielded Kelvin return**: replaces the unshielded `206.4 µm × 0.44 µm` M2 run at `y = -62.7` (`0.33 µm` edge-to-edge from `i_ldo` at `y = -62.00`) with:
   - Wide parallel M4 (`1.60 µm`) + M5 (`1.80 µm`) off `(304.8, -48.5)` across Zone 3 south (`y = -57.5` to `x = 255.5`, east of `x_vgb`),
   - Multi-via drop into a coaxial-shielded `1.40 µm` parallel M1 + M2 bus at `y = -63.80` (with parallel `1.00 µm` M3 west of `x = 139.8` directly into `m_cff["b"]` M3 at `(98.43, -63.76)`), directly beneath the solid `1.60 µm` `y_vss_south` M4 ground plane,
   - Continuous grounded M2 VSS guard wire at `y = -62.65` (`x = 71.0..251.5`, tied to VSS at `x = 71.0, 222.0, 251.5`) separating `i_ldo` from the Kelvin return,
   - Single compact multi-via vertical riser at `x = 139.8` to `p_rdiv_top["quiet"]`.
2. **Shortened / separated `fb` routing**:
   - **Production macro**: eliminates the `96 µm` south-edge U-turn by bridging `fb_return -> fb_input` directly across `y = -23.0` on M4 (`34.1 µm` straight between `m_cc` and `m_cghf`).
   - **Probe macro**: keeps exact external ports `(180.4, -64.5)` & `(213.0, -64.5)` while jogging `fb_input` M3 from `x = 213.0` to `x = 214.5` above `y = -45.5` (`2.6 µm` clear of `gate` at `x = 211.9`).

## Physical Signoff Summary

| Macro | Dimensions (µm) | Magic Full DRC | Netgen LVS | Property Errors | Floating Poly | Ports | 100 mΩ RCX R |
|---|---|---:|---|---:|---:|---|---:|
| `serdes_pll_supply_hv18_v2_cur_pdk` (prod) | `312.52 × 121.42` | **`0`** | **`MATCH`** | **`0`** | **`0`** | `13/13` exact | `6,063` |
| `serdes_pll_supply_hv18_v2_cur_probe_pdk` (probe) | `312.52 × 121.44` | **`0`** | **`MATCH`** | **`0`** | **`0`** | `15/15` exact | `6,052` |

## Parasitic & Electrical A/B Highlights (`v2_cur_pdk` → `v2_cur_kelvin_pdk`, 100 mΩ RCX)
- **Kelvin path `R_eff` (`quiet` port → `Xrtop_rdiv`)**: `126.9 → 9.0 Ω` (**−92.9%, 14.1× lower**).
- **Kelvin path `R_eff` (`quiet` port → `Cff`)**: `68.7 → 9.6 Ω` (**−86.0%, 7.1× lower**).
- **CPEX `quiet <-> i_ldo`**: `6.863 → 1.624 fF` (**−76.3%**, 4.2× lower); prod **`fb <-> i_ldo`**: `0.798 → 0.126 fF` (**−84.2%**); prod **`fb` total node cap**: `97.96 → 90.48 fF` (**−7.6%**); probe **`fb_input <-> gate`**: `1.630 → 1.142 fF` (**−30.0%**).
- **AC `quiet → i_ldo` bias coupling (20 / 100 MHz)**: improved by **−5.4 to −7.9 dB** across all 12 corner×load points (TT 10 mA: `−42.4 / −34.0 dB → −50.1 / −41.6 dB`).
- **Transient `i_ldo` kick (prod RCX, real BIAS v2 boundary)**:
  - `±1 mA / 1 ns`: **`−53.3%` to `−55.5%`** across all 4 corners (TT `0.987 → 0.440 mVpp`).
  - `±4 mA / 1 ns`: **`−23.1%` to `−53.5%`** across all 4 corners (`ss_m40c` `3.721 → 1.729 mVpp`, `fs_p85c` `5.376 → 3.546 mVpp`).
- **Loop stability, PSRR, load-step droop/overshoot**: PM strictly improved (`+0.06°` to `+0.16°`), GM strictly improved (`+0.06` to `+0.09 dB`), 20 MHz PSRR preserved/improved (`+0.00` to `+0.03 dB`), 2→10 mA DC load regulation tightened `1.3 → 0.9 mV`, and `±1 / ±4 mA` droop/overshoot/settling match baseline within `0.1–1.5 mV / 0–1 ns`.

## Reproduction
```bash
uv run python analog/ldo/layout/build_ldo_v2_cur_pdk.py \
  --kelvin-opt --variant v2_cur_kelvin_pdk \
  --output-dir results/layout/ldo_v2_cur_kelvin/build_v3 \
  --install-dir analog/ldo/layout/variants/v2_cur_kelvin_pdk

uv run python analog/ldo/tb/v2/verify_kelvin_ab.py \
  --work-dir results/analog/ldo/v2_cur_kelvin_ab_20261125
```
Full A/B data: `results/analog/ldo/v2_cur_kelvin_ab_20261125/summary.json`.
