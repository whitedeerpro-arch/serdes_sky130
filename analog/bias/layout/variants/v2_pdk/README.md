# BIAS v2 PDK Layout Suite (`variants/v2_pdk`)

Clean SKY130A PDK physical layouts for the redesigned **BIAS v2** reference and distribution subsystem, generated programmatically by [`build_bias_v2_pdk.py`](../../build_bias_v2_pdk.py) and [`build_bias_top_v2.py`](../../build_bias_top_v2.py).

All 7 cells pass Magic full-rule **DRC = 0**, Netgen flat/hierarchical **LVS = MATCH**, and visual inspection via `verification/layout/plot_mag.py`.

## Cell Summary

| Cell | Size (µm) | Area (µm²) | AR | vs v1 Area | DRC | LVS | Extracted | Ports |
|---|---:|---:|---:|---:|---:|---|---|---:|
| `serdes_bias_ctle_v2_pdk` | `6.41 × 3.79` | `24.3` | `1.69` | — | `0` | **MATCH** | CPEX + **RCX** | 2 (`iin, vss`) |
| `serdes_bias_cp_v2_pdk` | `8.89 × 11.58` | `102.9` | `1.30` | **−37.5%** (`164.6`) | `0` | **MATCH** | CPEX + **RCX** | 4 (`vbn, vbp, vcp, vss`) |
| `serdes_bias_cml_v2_pdk` | `60.79 × 28.96` | `1,760.5` | `2.10` | **−62.7%** (`4,717`) | `0` | **MATCH** | CPEX + **RCX** | 2 (`iin, vss`) |
| `serdes_ref_vbuf_v2_pdk` | `76.75 × 48.97` | `3,758.4` | `1.57` | — | `0` | **MATCH** | CPEX + **RCX** | 5 (`iin, ibias, out, vdd, vss`) |
| `serdes_ref_pbuf_v2_pdk` | `114.20 × 64.96` | `7,418.4` | `1.76` | 100% real CMOS | `0` | **MATCH** | CPEX + **RCX** | 10 (`iin, ibias, out, en, c0..3, vdd, vss`) |
| `serdes_bias_ref_v2_pdk` | `153.13 × 101.11` | `15,483.0` | `1.51` | **−34.1%** (`23,495`) | `0` | **MATCH** | CPEX | 13 (`vbg, i0..3, vgi, g0..4, vdd, vss`) |
| `serdes_bias_top_v2_pdk` | `176.53 × 152.26` | `26,878.5` | `1.16` | Integrated macro | `0` | **MATCH** | CPEX | 20 (all perimeter; `vgi` internal) |

## Key Physical Improvements over v1

1. **Zero-`Cc` Single-Stage FC-OTA Core**: Removes the `6 pF` Miller cap + `20 kΩ` `Rz` (~`3,500 µm²` saved) and improves DC VDD line regulation from `39–51 mV/V` (`-27 dB`) to `< 9 mV/V` (`< -41 dB`).
2. **Head-R-Calibrated Multi-Segment `res_high_po` Banks + Outer Dummies**: Every precision resistor (`Xrsa/Xrsb`, `Xr1/Xr2`, `Xrref`, `Vbuf Xr`, `Pbuf` 16-tap string) uses exact `R = N·(378 + 317·L)/W` segment lengths matching `bias_v2.spice` to the `0.005 µm` Magic grid, eliminating v1's `+2.4%..+3.2%` systematic layout shift, flanked by grounded dummy poly bars.
3. **True Analog Matching & WPE/LOD Symmetry**:
   - `Xm1..Xm5` arranged as a 2D common-centroid `2×12` array with outer dummy fingers so `Xm3` (`vbg`) shares identical N-well edge proximity with `Xm1/Xm2`.
   - `4×3` PNP thermal island (`Q1` surrounded by `8× Q2`, `Q3` flanked by P+ dummy islands).
   - Outer dummy fingers on `FC-OTA`, `V→I OTA`, `vbuf`/`pbuf` OTAs, unified `pcopy` bank (`153` active + `7` dummies in shared N-well), and local `cp`/`ctle` mirror cells.
4. **Stacked MIM1+MIM2 (`cap_mim_m3_1 + cap_mim_m3_2`)**:
   - `serdes_bias_cml_v2_pdk` tucks the `5/0.5` NMOS diode directly underneath a `2×1` stacked `5.0 pF` MIM roof (`4,717 → 1,760.5 µm²`, `AR = 2.10` vs `3.46`).
   - `serdes_bias_ref_v2_pdk` and `serdes_bias_top_v2_pdk` stack `Cvbg (6 pF)` and `Cvgi (2 pF)` over the resistor array with multi-via3/via4 rail arrays.
5. **100% Real-Transistor `serdes_ref_pbuf_v2`**: Replaces behavioral `Bs0..15` with a real 4-to-16 CMOS decoder + 16 transmission gates + matched 16-tap `high_po` string + switched 300 µA LVT OTA follower.
6. **Perimeter-Pinned Integrated Macro (`serdes_bias_top_v2_pdk`)**: Keeps high-Z `vgi` completely internal (driving the unified `pcopy` bank for `icml`, `ictle`, `icp`, `i_ldo0`, `i_ldo1`), collapses nested guard rings into a single outer ring with zone dividers, and exports all 20 top-level ports cleanly to the macro boundary.
