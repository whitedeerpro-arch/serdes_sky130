# `pll_cp_steer_v4_pdk` — SKY130 PDK Wide-Swing Active-Matching Charge Pump Layout (v4 Candidate)

- **Generator**: `analog/pll/cp/layout/build_cp_steer_v4_pdk.py`
- **Circuit**: `analog/pll/cp/spice/charge_pump_steer_v4.spice` (`k = 4 / Icp = 200 µA`, 100% real SKY130A devices, exact 8-port drop-in interface `up dn out vbn vbp ibias vdd vss`)
- **Signoff build**: `results/layout/pll_cp/20261123_v4p1_sync/` (synced to **v4.1** skew-aligned UP inverter `Xupn 4.0/0.30 nf=2`, `Xupp 12.0/0.15 nf=6` in the exact same `58.98 × 43.70 µm = 2,577.43 µm²` footprint, cutting 250 MHz `Vctrl` glitch `2.2–3.5×` → `−60 dBc` ref spur)
- **Independent review (`review_cell.py --rc`)**: `results/layout/pll_cp/20261123_v4p1_sync/review/` (`DRC = 0`, `LVS = MATCH`, `PROP_ERR = False`, `8/8` ports, `out` CPEX `19.950 fF`, `2,686` RCX resistors, `devices_preserved = True`)
- **Verification**: `results/analog/pll/cp/v4/verify_20261122/` (135-corner real-BIAS DC), `results/analog/pll/cp/v4/verify_20261122_v2/` (AC servo stability + 250 MHz transient), `results/analog/pll/cp/v4/verify_20261122_pex/` (6-corner post-layout CPEX DC)

## v3 vs v4 Physical & Electrical Summary

| Metric | v3 (`pll_cp_steer_pdk`) | v4 (`pll_cp_steer_v4_pdk`) | Delta |
|---|---:|---:|---:|
| Footprint (µm) | `56.58 × 38.45` | `58.98 × 43.70` | `+2.40 × +5.25 µm` |
| Area (µm²) | `2,175.50` | `2,577.43` | `+18.5%` (target `2,200–2,650`) |
| Devices / Nets | `19 / 14` | `35 / 25` | `+16` (replica + 8T servo + `Xcsrv`) |
| DRC (full sky130A) | `0` | `0` | Clean |
| Netgen LVS / Prop Err | `MATCH / False` | `MATCH / False` | Clean (`8/8` ports) |
| Floating poly / M5 usage | `0 / 0.0%` | `0 / 0.0%` | Clean |
| `out` CPEX (fF) | `16.112` | `19.943` | `≤ 20 fF` |
| RCX resistors (`devices_preserved`) | `1,751 (True)` | `2,647 (True)` | Clean |
| 135-corner max UP/DN mismatch (`[0.60, VDD-0.35]`) | `11.29%` (mid) | `0.193%` (`0.330%` over `[0.50, VDD-0.30]`) | **58× reduction** |
| 1.65 V 5%-droop window (min gap to `vhi`) | `[0.38, 1.26] V` (`24.37 mV`) | `[0.38, 1.49] V` (`251.2 mV`) | **`+230 mV` (`10.3×` margin)** |
| 1.80 V 5%-droop window (min gap to `vhi`) | `[0.39, 1.42] V` (`36.27 mV`) | `[0.39, 1.67] V` (`284.7 mV`) | **`+250 mV` (`7.8×` margin)** |
| 1.95 V 5%-droop window (min gap to `vhi`) | `[0.41, 1.57] V` (`39.19 mV`) | `[0.41, 1.84] V` (`308.5 mV`) | **`+270 mV` (`7.9×` margin)** |
| Servo AC Phase Margin (6 corners × 3 `Vout`) | N/A | `60.2° – 80.6°` (`50–89 dB` DC gain) | Unconditionally stable |
| Post-layout CPEX DC (6 extreme corners) | — | `1.65 V hi ≥ 1.49 V`, `mm ≤ 0.146%` (`[0.60, VDD-0.35]`) | Matches schematic |

## Layout Architecture Highlights

- **NW & SW Column-1 Cavity Reuse**: The 1/4-scale exact unit-finger replica (`Xpr 28/1`, `Xpsr 6/0.15`, `Xnsr 2/0.15`, `Xnr 5/1`), `vbp`-driven servo bias (`Xsb_p`, `Xsb_n`), 8T rail-to-rail symmetrical servo OTA (`Xst`, `Xsa/Xsb`, `Xsla..d`, `Xsn1..2`), and 3D-stacked `10.0 × 14.0 µm` Miller MIM cap `Xcsrv` (M3–M4) are tucked directly into the Column 1 NW & SW cavities above and below the pulse drivers.
- **Wide-Swing Column 2**: `Xp` widened from `80/1` (`5 µm` fingers) to `112/1` (`2 × 8 × 7 µm`) and ABBA common-centroid PMOS steering switches `Xps/Xpd` widened from `16/0.15` to `24/0.15` (`3 µm` fingers).
- **Low-CPEX Elevated M4 `out` Trunk**: Single straight M4 trunk at `y = -0.95 µm` connects `Xsb`, `Xps/Xns`, `Xa`, and right-side `out` port above `Cdum`'s M3 ground strap, keeping `out` CPEX at `19.943 fF` with `0.0%` M5.
