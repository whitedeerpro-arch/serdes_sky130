# Bandgap & Bias Distribution PDK Layout Suite (`variants/pdk`)

Built and verified by [build_bias_pdk.py](../../build_bias_pdk.py) following the **Plan-First Analog Layout Workflow** ([bias_pdk_floorplan_plan.png](../../bias_pdk_floorplan_plan.png)) against the unmodified schematic parameters in [bandgap.spice](../../../spice/bandgap.spice) and [bias_dist.spice](../../../spice/bias_dist.spice).

All 11 cells use real SKY130 parameterized primitives (`sky130_fd_pr__nfet_01v8`, `nfet_01v8_lvt`, `pfet_01v8`, `pfet_01v8_lvt`, `res_high_po_0p35` with true `w=1.0 µm` finger widths, `cap_mim_m3_1`, and `rf_pnp_05v5_W3p40L3p40`) and pass `verification/layout/check.py` (`DRC_TOTAL 0`, `LVS_MATCH True`, `LVS_PROPERTY_ERRORS False`, zero disconnected nets).

- [Suite Overview Sheet](bias_pdk_suite_overview.png)
- [Floorplan Blueprint](../../bias_pdk_floorplan_plan.png)
- [Verification Summary JSON](summary.json)
- Append-only signoff run: `results/layout/bias_pdk/20261114_plan_v2/`

## Verified Cells (11/11)

| Cell | Size (µm) | Area (µm²) | Analog Floorplan & Matching Highlights | Ports | Verification |
|---|---:|---:|---|---|---|
| `serdes_bias_ctle_pdk` | `4.83 × 4.10` | `19.8` | 4-finger `nfet_01v8_lvt` (`W=8, L=0.5`) diode | `iin vss` | `DRC=0, LVS=MATCH` |
| `serdes_bias_pcopy_pdk` | `18.83 × 8.19` | `154.2` | `1×4` `pfet_01v8_lvt` (`W=24, L=4`) mirror branch | `out vgi vdd` | `DRC=0, LVS=MATCH` |
| `serdes_bias_pcopy_n20_pdk` | `48.77 × 17.92` | `873.7` | `2×10` folded `pfet_01v8_lvt` (`W=120, L=4`) | `out vgi vdd` | `DRC=0, LVS=MATCH` |
| `serdes_bias_pcopy_n85_pdk` | `78.80 × 46.99` | `3,702.4` | `5×17` folded `pfet_01v8_lvt` (`W=510, L=4`) | `out vgi vdd` | `DRC=0, LVS=MATCH` |
| `serdes_bias_cp_pdk` | `11.77 × 13.99` | `164.7` | `[DN, MN, MN, DN]` common-centroid NMOS + PMOS diode | `vbn vbp vcp vss` | `DRC=0, LVS=MATCH` |
| `serdes_bias_cml_pdk` | `127.84 × 36.90` | `4,717.3` | `nfet_01v8` `5/0.5` diode + `5×1 pF` MIM decoupling | `iin vss` | `DRC=0, LVS=MATCH` |
| `serdes_bg_ota_pdk` | `59.50 × 45.10` | `2,683.5` | Guarded 2D checkerboard `4×4` PMOS load + `[A,A,B,B,B,B,A,A]` NMOS pair (`m2_bottom_only` guard, left-edge ports) | `vbn inp inn out vdd vss` | `DRC=0, LVS=MATCH` |
| `serdes_bg_amp_pdk` | `64.10 × 76.90` | `4,929.3` | Guarded 3D-shielded 2-stage error amp (`2×3` 6 pF MIM over active + 4-bar `w=1` `20 kΩ` `Xrz`) | `inp inn vbn out vdd vss` | `DRC=0, LVS=MATCH` |
| `serdes_ref_vbuf_pdk` | `74.72 × 51.50` | `3,848.1` | Guarded height-matched 2-bay OTA + 8-bar `w=1` `105.2 kΩ` `Xr` (`l=331.86 µm`) | `iin ibias out vdd vss` | `DRC=0, LVS=MATCH` |
| `serdes_bandgap_pdk` | `183.70 × 127.90` | `23,495.2` | Plan-First 3-Column Height-Matched Bandgap (**−62.7% area** vs legacy `389 × 162 µm` and **−24.8% area** vs v1 `212.4 × 147.1 µm`): Col 1 guarded `[A,B,B,A,B,A,A,B]` `w=1` `Xrsa/Xrsb` + `[5×R2 \| R1 \| 5×R2]` PTAT + startup + `4×3` PNP thermal island (`Q1` center, `8×Q2` ring, `Q3` + dummy P+ guards); Col 2 `Xamp` + split `4×(3+2)` `LU.3`-clean 2D common-centroid core PMOS; Col 3 3D Under-MIM `w=1` `Xrref` + 5-bit trim + `Xota` + `10×2` V→I PMOS beneath `2×5` 10 pF `Cvgi` | `g4..g0 iout0..3 vbg vg vgi vdd vss` | `DRC=0, LVS=MATCH` |
| `serdes_bias_ref_pdk` | `183.70 × 127.90` | `23,495.2` | Matching 3-Column Bandgap reference macro for `bias_dist.spice` (`Cvgi=2 pF` `1×2` + `Cvbg=5 pF` `1×5` stacked over Col 3) | `g4..g0 i0..3 vbg vg vgi vdd vss` | `DRC=0, LVS=MATCH` |

## Regenerate

```bash
uv run python analog/common/bias/layout/build_bias_pdk.py \
  --output-dir results/layout/bias_pdk/<new_run_id> \
  --install-dir analog/common/bias/layout/variants/pdk
```
