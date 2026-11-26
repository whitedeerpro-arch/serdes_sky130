# `serdes_pll_supply_hv18_v2_cur` — Current-Mode Bias Input LDO v2 (`v2_cur_pdk`)

Adopted current-input HV18 PLL supply macro, with a 3.0–3.6 V input and 60 pF of stacked and fused MIM. It accepts the BIAS v2 current directly. The older voltage-input v2 characterization and current-input v2_cur verification are documented in the LDO report. [LDO v2 and v2_cur](../../../../../docs/design/ldo_v2.md)

## Interface Mismatch Resolved

| Side | Legacy `v2_pdk` | Current-Mode `v2_cur_pdk` |
|---|---|---|
| **BIAS v2 (`serdes_bias_top_v2_pdk`)** | Keeps high-Z `vgi` strictly internal; exports 10 µA current outputs `i_ldo0` / `i_ldo1` (`Xpc_ldo0/1`, `4 × 8/4` `pfet_01v8_lvt`, `W=32/L=4`). | **Direct 1:1 match** — connects `serdes_bias_top_v2_pdk.i_ldo0` straight to `serdes_pll_supply_hv18_v2_cur_pdk.i_ldo`. |
| **LDO v2 Bias Input** | Expected voltage port `vgi` and instantiated a legacy BIAS v1 `serdes_bias_pcopy_pdk` (`4 × 6/4`, `W=24/L=4`, `-25%` current error if driven by BIAS v2 `vgi`). | Removes redundant `Xcopy`; routes West port `i_ldo` directly along `y = -62.00 µm` (M2) into `serdes_ldo_hv18_core_v2`'s local unit-finger-matched 5 V NMOS diode mirror (`Xnb` `30/2 nf=6` → `Xnr` `30/2 nf=6` `1:1` + `Xpre_sink` `9/2 nf=3` `0.3:1` + `Xboff` `10/0.5` shutdown clamp). |

### Key Electrical & Physical Benefits

1. **Zero High-Z `vgi` Exposure**: `vgi` remains 100% locked inside `serdes_bias_top_v2_pdk`; only low-impedance current-mode `i_ldo` (`10.0 µA` into `Xnb`, `Vgs ≈ 0.85–1.05 V`) traverses chip-level routing.
2. **Exact 1:1 Bias Current Ratio**: Eliminates the hidden v1 `w=24/4` vs v2 `w=32/4` (`-25%`) mirror mismatch while saving `154 µm²` of active silicon (`p_copy` removed).
3. **Safe Shutdown (`enable = 0`)**: `Xboff` pulls `i_ldo` (`= ibias`) to `vss` (`~0 V`), safely sinking `Xpc_ldo0`'s `10 µA` within `1.8 V` SOA while keeping `Xnb`/`Xnr`/`Xpre_sink` completely off.
4. **Zero Perturbation to Verified LDO Core**: Preserves 100% of `v2_pdk`'s 60.00 pF stacked+fused MIM2 bay, active HV PMOS pre-regulator, 47-bar common-centroid divider, 0.15 µm active overshoot clamp, full-height P+ guard barrier, and `17.5 µm` M4/M5 NVT power stage with Kelvin sense.

## Physical Verification Summary

| Macro | Dimensions (µm) | Area (µm²) | Magic Full DRC | Netgen LVS | Property Errors | Floating Poly | Ports | `100 mΩ` RCX R |
|---|---|---:|---:|---|---:|---:|---|---:|
| `serdes_pll_supply_hv18_v2_cur_pdk` (production) | `312.52 × 121.46` | `37,958.68` | **`0`** | **`MATCH`** | **`0`** | **`0`** | `13/13` exact (`vin host quiet bg i_ldo enable t0..t5 vss`) | `6,026` |
| `serdes_pll_supply_hv18_v2_cur_probe_pdk` (probe) | `312.52 × 121.44` | `37,952.43` | **`0`** | **`MATCH`** | **`0`** | **`0`** | `15/15` exact (+ `fb_return fb_input`) | `6,014` |

Independent `review_cell.py` audit (`results/layout/ldo_v2_cur/review_rc_v1/`):
- `physical_passed = True`, `checker_exit = 0`, `855/855` extracted devices matched, `total_substrate_cap = 3,569.955 fF`, `total_coupling_cap = 1,753.942 fF`.
- Key port CPEX totals: `i_ldo = 64.498 fF` (`35.745` sub + `28.754` coup), `quiet = 854.222 fF`, `bg = 4.614 fF`.
- Native `1 Ω` `extresist` (`--rc`) extracted cleanly with `0` bridged nets and `0` disconnected RC subnetworks; the strict string-equality check in `review_cell.py` flags only `1/855` devices (`X79 vss vss vss vss`, an inherited `v2_pdk` `vss`-shorted `nfet_g5v0d10v5` outer dummy where `extresist` redistributes shared `vss` source area `as=40.89 → 0` on the same net).

## Files & Reproduction

- SPICE schematic: `analog/ldo/spice/pll_supply_hv18_v2_cur.spice`
- Layout generator: `analog/ldo/layout/build_ldo_v2_cur_pdk.py`
- Build & verification work dir: `results/layout/ldo_v2_cur/build_v1/`
- Independent `review_cell.py --rc` audit: `results/layout/ldo_v2_cur/review_rc_v1/`
