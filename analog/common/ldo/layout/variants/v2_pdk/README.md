# `serdes_pll_supply_hv18_v2` — Physical Layout (`v2_pdk`)

Clean-sheet SKY130 HV18-to-1.8 V PLL LDO topology and stacked+fused MIM2 physical macro (`v2_pdk`), 100% pin-compatible with `serdes_pll_supply_hv18_smallcap`.

## Key Architectural & Physical Upgrades (vs `r4` / `smallcap`)

1. **Active HV PMOS Pre-Regulator (`Xpre_p`/`Xpre_d`/`Xpre_sink`) + High-R/Low-C Gate Filters (`Rpre`/`Cpre`, `Rcas`/`Ccas`)**:
   - Replaces the legacy `r4`/`smallcap` passive `Xrhv` (2 kΩ) + `Xchv` (32 pF) and `Xrcas` (31.25 kΩ) + `Xccas` (16 pF) RC blocks.
   - Feeds the EA HV rail `va` through an actively regulated PMOS stage (`Xpre_p`), adding active isolation on top of high-R poly-resistor filtering (`400 kΩ` snakes tucked directly beneath the MIM bay).
   - Improves worst-case post-layout 20 MHz PSRR from `35.94 dB` (`smallcap` PEX) to **`42.42 dB` (CPEX) / `43.42 dB` (RCX)** (`+8.4` to `+9.4 dB` above the `34 dB` spec).
2. **2-Stage High-Pass-Triggered Active Overshoot Clamp (`Xclamp`, `Xcl_chp`, `Xcl_p2`, `Xcl_n1`, `Xcl_nref`)**:
   - DC-quiescent in steady state (`vg_clamp ≈ 0.01–0.38 V` DC, zero DC regulation corruption) and trips only on fast positive `dV/dt` unload transients.
   - Eliminates `smallcap`'s `FS 85 °C` unload failure (`1.984 V > 1.95 V`), clamping `6 mA ± 4 mA / 1 ns` unload to **`1.8973 V` (schematic) / `1.9039 V` (CPEX) / `1.9042 V` (RCX)** on `FS 85 °C` and **`1.8998 V` (schematic) / `1.9013 V` (CPEX) / `1.9009 V` (RCX)** on `TT 27 °C` (`< 0.5 mV` RCX-vs-CPEX difference!).
3. **47-Bar Head-R-Calibrated Common-Centroid Divider with Tied Outer Dummies (`rdiv28` + `rdiv23`)**:
   - Uses identical `sky130_fd_pr__res_high_po_0p35` (`w=1.0 µm`, `l=11.425 µm`) unit bars for both the 26-bar top leg (`Xrtop`/`Xrfixed` common-centroid palindrome) and 21-bar binary-weighted trim ladder (`Xr0..Xr5`, switches `Xs0..Xs5`), flanked on both outer ends by **4 zero-current tied-to-`vss` outer dummy bars** (`Xrdum_t0/t1/b0/b1`, tied straight into the `vss` guard ring at both ends — zero floating poly, 0% head-R ratio error, **100% 64-code monotonicity** across all 15 MOS×RC corners).
4. **EA Precision Pair Outer Dummy Fingers (`Xpl/Xpr` & `Xnl/Xnm`)**:
   - Shared-diffusion tied-off outer dummy fingers on every half of the 2D AB/BA common-centroid diff pair (`Xpl/Xpr`, `8` outer fingers with `G = D = B = va, S = tail`, `0 A` off-state) and active NMOS mirror (`Xnl/Xnm`, `4` outer fingers with `G = S = D = B = vss`), eliminating outer-finger LOD/STI mismatch while preserving exact `0`-property-error Netgen `LVS = MATCH`.
5. **60.00 pF Stacked+Fused MIM1/MIM2 Bay + Under-MIM Passive Integration + Low-ESR Power Super-Highway**:
   - Stacks `cap_mim_m3_1` + `cap_mim_m3_2` (2× density per footprint) over the high-R poly snakes, matched divider, and active overshoot clamp (`M1`/`M2` strictly under MIM; `M3`/`M4`/`M5` dedicated to MIM plates and power distribution).
   - Keeps Zone 2 (EA + Pre-Reg, with dual `va` N-well taps keeping `LU.3 < 6 µm`) and Zone 3 (NVT Power Stage `Xcas | Xpass`) 100% MIM-free, separated by a full-height P+ guard barrier (`x = 251.5 µm`) carrying a stacked `3.0 µm M5 + 2.2 µm M4 + M3` ground super-highway directly linking `C_out`, `Xclamp.S` (`1×5` via2/via3 + `2.8 µm` M4 bridge), and the `vss` port.
   - `quiet` East plate uses `17.5 µm` stacked `M4 + M5` with 3× `via2` arrays (`48` `via2`s) across all 4 `Xpass` rows, dense `via4` arrays at the `quiet` port, and triple-section parallel `M3 + M4` `quiet` trunking, achieving **`1.14–1.15 mV` max IR drop at 10 mA (`R_eff = 114–115 mΩ`)** in full `100 mΩ` RCX, with a dedicated Kelvin sense trace to `Xrtop`/`Xcff`.

## Layout & Physical Verification Summary

| Macro | Dimensions (µm) | Area (µm²) | Area vs `smallcap` | Area vs `r4` | Magic Full DRC | Netgen LVS | Property Errors | Perimeter Ports | RCX Resistors (`100 mΩ`) |
|---|---|---:|---:|---:|---|---|---|---|---:|
| `serdes_pll_supply_hv18_v2_pdk` (production, 13-pin) | `312.52 × 121.46` | **`37,958.68`** | **`−57.9%`** | **`−79.1%`** | **`0`** | **`MATCH`** | **`0`** | `13/13` exact | `6,078` |
| `serdes_pll_supply_hv18_v2_probe_pdk` (probe, 15-pin) | `312.52 × 121.44` | **`37,952.43`** | **`−57.9%`** | **`−79.1%`** | **`0`** | **`MATCH`** | **`0`** | `15/15` exact | `6,076` |

Preview images (white-background SKY130 palette via `verification/layout/plot_mag.py`):
- Production macro: `serdes_pll_supply_hv18_v2_pdk.png`
- Loop-probe macro: `serdes_pll_supply_hv18_v2_probe_pdk.png`

## Quantitative Electrical Comparison (`r4` vs `smallcap` vs `v2`)

| Metric | Spec | `r4` (legacy) | `smallcap` (legacy) | `v2` Schematic (15-corner PVT + Full-PDK Dyn) | `v2` Post-Layout CPEX (`v2_pdk`) | `v2` Post-Layout RCX (`100 mΩ`, `v2_pdk`) |
|---|---|---:|---:|---:|---:|---:|
| **Layout Area** | `≤ 38,000 µm²` | `181,560 µm²` | `90,066 µm²` | — | **`37,958.7 µm²`** | **`37,958.7 µm²`** |
| **Total MIM Capacitance** | `< 70 pF` | `~140 pF` | `70 pF` | **`60.00 pF`** (stacked MIM1+MIM2) | **`60.00 pF`** | **`60.00 pF`** |
| **64-Code Trim Monotonicity** | `100%` | Pass | Pass | **`15/15` corners (step `2.97–11.56 mV`)** | **`5/5` corners (step `2.97–11.51 mV`)** | Verified |
| **DC Regulation (`quiet`)** | `[1.764, 1.836] V` | Pass | `1.776–1.815 V` | **`1.7762–1.8121 V`** (`1,215` pts) | **`1.7783–1.8076 V`** | **`1.7781–1.8076 V`** |
| **20 MHz PSRR (worst / TT)** | `≥ 34 dB` | `~44 dB` | `35.94 dB` (PEX) | **`44.55 dB`** (`fs:hh`) / `50.18 dB` (`tt`) | **`42.42 dB`** (`fs:ll`) / `47.91 dB` (`tt`) | **`43.42 dB`** (`fs:ll`) / `49.63–49.96 dB` (`tt`) |
| **Loop Phase Margin (Middlebrook)** | `≥ 60°`, `x0 = 1` | Pass | Pass | **`63.60°` min** (`ff:hh`), `77.98°` (`tt`), `255/255 x0=1` | **`68.84°` min** (`fs:ll`), `77.78°` (`tt`), `x0=1` | **`63.21°` min** (`fs:ll`), `74.81°` (`tt`), `12/12 x0=1` |
| **Fast Load Step `FS 85 °C` (`±4 mA / 1 ns`)** | `< 1.95 V` | Pass | **FAIL `1.984 V`** | **`[1.6618, 1.8973] V`** | **`[1.6631, 1.9039] V`** | **`[1.6667, 1.9042] V`** (`−79.8 mV` vs `smallcap`) |
| **Fast Load Step `TT 27 °C` (`±4 mA / 1 ns`)** | `< 1.95 V` | Pass | Pass | **`[1.6691, 1.8998] V`** | **`[1.6887, 1.9013] V`** | **`[1.6935, 1.9009] V`** |
| **Fast Load Step `±1 mA / 1 ns` (`TT` / `FS`)** | — | — | — | `-24.8/+24.4` / `-31.3/+29.5 mV` | `-24.9/+24.5` / `-31.1/+29.6 mV` | `-24.1/+23.9` / `-30.4/+29.2 mV` |
| **Output Noise (`1 kHz–200 MHz`)** | `≤ 250 µVrms` | — | `225–262 µVrms` | `230.0–259.6 µVrms` (`246.2` TT 10 mA) | `226.0–255.3 µVrms` (`239.5` TT 10 mA) | — |
| **Zero-Start Startup (10 mV settle)** | `≤ 120 µs`, no OS | — | — | `72.0–116.5 µs` (`≤ 0.2 mV` OS) | `75.7–120.6 µs` (`≤ 0.2 mV` OS) | — |
| **`quiet` Power-Rail IR Drop (`10 mA`)** | `< 5.0 mV` | — | — | — | — | **`1.14–1.15 mV`** (`R_eff = 114–115 mΩ`) |

## Files & Reproduction

- Generator: `analog/common/ldo/layout/build_ldo_v2_pdk.py`
- SPICE schematics:
  - `analog/common/ldo/spice/ldo_v2_passives.spice`
  - `analog/common/ldo/spice/ldo_hv18_core_v2.spice`
  - `analog/common/ldo/spice/pll_supply_hv18_v2.spice`
- Verification testbenches:
  - `analog/common/ldo/tb/v2/run_v2.py` (schematic PVT + full-PDK dynamic + post-layout CPEX)
  - `analog/common/ldo/tb/v2/verify_rcx.py` (post-layout `100 mΩ` RCX IR drop, PSRR, Middlebrook PM, and apples-to-apples `6 mA ± 0.1/1/4 mA (1 ns)` load step)
- Archived verification runs:
  - Schematic 15-corner PVT DC/AC: `results/analog/common/ldo/v2/20261120T070822.297791Z_schem_pvt/summary.json`
  - Schematic full-PDK dynamic signoff: `results/analog/common/ldo/v2/20261120T073417.659705Z_schem_dyn_fullpdk/summary.json`
  - Post-layout CPEX screen: `results/analog/common/ldo/v2/20261120T102608.250446Z_pex_cpex/summary.json`
  - Post-layout RCX (`100 mΩ`, final Option-B `v2_pdk_optb3`): `results/analog/common/ldo/v2/20261120T130702.587460Z_pex_rcx/summary.json`
