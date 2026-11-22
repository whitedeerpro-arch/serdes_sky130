# RX v2 Zero-CML (CMOS) 4 Gb/s Receiver — SKY130A PDK Physical Layout Suite (`v2_pdk`)

Complete SKY130A PDK physical layout suite for the 4 Gb/s RX v2 Zero-CML (CMOS) receiver: analog front-end (`serdes_rx_term_pdk`, `serdes_rx_ctle_pdk`), quarter-rate double-tail dynamic CMOS slicer (`serdes_rx_dt_slicer_pdk`), 2 GHz 64-code pure-CMOS Phase Interpolator + deterministic 8-phase 1 GHz quadrature ÷2 (`serdes_rx_qdiv2_8ph_pdk`, `serdes_rx_pi_rotator_2g_pdk`, `serdes_rx_cmos_pi_8ph_pdk`, synced to Phase 2 `rx_cmos_pi.spice` `2.60/6.80` output buffers & `1.25/3.30` latch buffers), pitch-matched 8→32 static CMOS deserializer (`serdes_rx_cmos_deser16_pdk`), and full integrated top-level receiver macro (`serdes_rx_cmos_top_pdk`). Independently verified with `verification/layout/review_cell.py --rc` and post-layout CPEX transient simulation (`analog/rx/cmos_rx/tb/postlayout/verify_rx_v2_pex.py`).

## Physical Signoff Summary (All 8 Deliverables)

| Cell | Size (`W × H µm`) | Area (`µm²`) | AR | Devices (Raw / Merged) | Ports | Magic Full DRC | Netgen LVS | Prop Err | Floating Poly | `review_cell.py` (`phys` / `rc_dev`) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| [`serdes_rx_term_pdk.mag`](serdes_rx_term_pdk.mag) | `33.35 × 16.36` | `545.61` | `2.04` | `8 / 2` | `4 / 4` | **0** | **MATCH** | **False** | **0** | `True` / `True` |
| [`serdes_rx_ctle_pdk.mag`](serdes_rx_ctle_pdk.mag) | `37.40 × 26.20` | `979.88` | `1.43` | `20 / 19` | `9 / 9` | **0** | **MATCH** | **False** | **0** | `True` / `True` |
| [`serdes_rx_dt_slicer_pdk.mag`](serdes_rx_dt_slicer_pdk.mag) | `29.60 × 31.54` | `933.58` | `0.94` | `51 / 51` | `13 / 13` | **0** | **MATCH** | **False** | **0** | `True` / `True` |
| [`serdes_rx_qdiv2_8ph_pdk.mag`](serdes_rx_qdiv2_8ph_pdk.mag) | `155.20 × 16.57` | `2,571.66` | `9.37` | `146 / 138` | `15 / 15` | **0** | **MATCH** | **False** | **0** | `True` / `True` |
| [`serdes_rx_pi_rotator_2g_pdk.mag`](serdes_rx_pi_rotator_2g_pdk.mag) | `154.52 × 51.40` | `7,942.33` | `3.01` | `588 / 588` | `38 / 38` | **0** | **MATCH** | **False** | **0** | `True` / `WL+conn=True`* |
| [`serdes_rx_cmos_pi_8ph_pdk.mag`](serdes_rx_cmos_pi_8ph_pdk.mag) | `163.32 × 68.72` | `11,223.35` | `2.38` | `734 / 726` | `47 / 47` | **0** | **MATCH** | **False** | **0** | `True` / `WL+conn=True`* |
| [`serdes_rx_cmos_deser16_pdk.mag`](serdes_rx_cmos_deser16_pdk.mag) | `238.46 × 86.48` | `20,622.02` | `2.76` | `1,812 / 1,812` | `52 / 52` | **0** | **MATCH** | **False** | **0** | `True` / `WL+conn=True`* |
| [`serdes_rx_cmos_top_pdk.mag`](serdes_rx_cmos_top_pdk.mag) | `245.30 × 205.52` | `50,414.06` | `1.19` | `2,983 / 2,968` | `76 / 76` | **0** | **MATCH** | **False** | **0** | `True` / `WL+conn=True`* |

Notes:
- `serdes_rx_term_pdk` port count: the frozen `rx_ctle_pdk.spice` schematic defines 4 ports (`inp inn vcm vss`), including the shared p-sub guard ring terminal `vss` for the 8 `sky130_fd_pr__res_high_po_5p73` bars.
- `serdes_rx_qdiv2_8ph_pdk` & `serdes_rx_cmos_pi_8ph_pdk` Phase 2 sync: confirmed byte-for-byte identical to current `rx_cmos_pi.spice` (`Xbd0..Xbe3` `2.60/6.80 nfn=2 nfp=4` and `Xop/Xon` `1.25/3.30 nfn=1 nfp=2`).
- `*` On cells containing supply-shorted 1-finger dummy MOS-cap FETs (`D=S=B=vdd/vss`, mandated by frozen `rx_cmos_pi.spice` and `rx_cmos_deser16.spice`), unmodified `review_cell.py` passes `physical_passed = True` (`DRC = 0`, `LVS = MATCH`, `0` property errors, `0` floating poly) and Magic native RCX (`*_rcx.spice`) preserves 100% of device counts, models, `W/L/ad/pd`, terminal parent nets, and resistor subnetwork connectivity; only 2 supply-shorted dummy MOS-caps differ in `as/ps` between CPEX and RCX due to Magic `ext2spice` global node-diffusion fallback vs `extresist` `rnode`s (`rc_audit.json` in each review directory).

## Metal Utilization & CPEX Symmetry

| Cell | M1 / M2 / M3 / M4 / M5 Share | Key Differential CPEX & Balance (`total_node_fF`) |
|---|---|---|
| `serdes_rx_term_pdk` | `10.8 / 26.9 / 41.5 / 12.0 / 8.9%` | `inp = 12.300 fF`, `inn = 12.605 fF` (**`\|ΔC\| = 0.305 fF`**), `vcm = 10.076 fF` |
| `serdes_rx_ctle_pdk` | `16.2 / 22.0 / 51.0 / 10.7 / 0.0%` *(M3 includes `357.5 µm²` MIM bottom plates)* | `inp = 4.317 fF`, `inn = 4.301 fF` (**`\|ΔC\| = 0.016 fF`**); `outp = 7.156 fF`, `outn = 7.061 fF` (**`\|ΔC\| = 0.095 fF` ≤ 1.0 fF**) |
| `serdes_rx_dt_slicer_pdk` | `38.0 / 31.5 / 19.3 / 11.2 / 0.0%` (`M1+M2 = 69.5%`) | `inp/inn = 5.397 / 5.357 fF` (**`Δ = 0.040 fF`**); `fn/fp = 9.701 / 9.208 fF` (**`Δ = 0.493 fF`**); `outn_b/outp_b = 8.963 / 8.964 fF` (**`Δ = 0.001 fF`**); `qp/qn = 3.536 / 3.517 fF` (**`Δ = 0.019 fF`**); `clk = 7.683 fF` |
| `serdes_rx_qdiv2_8ph_pdk` | `27.5 / 8.1 / 56.5 / 7.9 / 0.0%` | `ckd0..3 = 5.279, 5.703, 5.831, 5.090 fF`; `cke0..3 = 5.187, 5.331, 6.101, 5.169 fF` (**`\|D − E\| = 0.08–0.37 fF`**); `dp/dn = 21.770 / 20.462 fF`; `ep/en = 19.087 / 18.965 fF` |
| `serdes_rx_pi_rotator_2g_pdk` | `29.4 / 17.9 / 29.8 / 22.8 / 0.0%` (`M1+M2 = 47.3%`) | `c0..c7 = 1.099–1.134 fF` (**`0.035 fF` spread**); Edge `mixp/mixn = 8.125 / 8.270 fF` (**`Δ = 0.145 fF`**); Data `mixp/mixn = 8.318 / 8.125 fF` (**`Δ = 0.193 fF`**); `dp/dn = 1.780 / 1.694 fF`; `ep/en = 1.676 / 1.780 fF` |
| `serdes_rx_cmos_pi_8ph_pdk` | `28.2 / 14.8 / 37.1 / 20.0 / 0.0%` (`M1+M2 = 43.0%`) | `c0..c7 = 1.241–1.300 fF` (**`0.059 fF` spread**); Edge `mixp/mixn = 8.125 / 8.270 fF`; Data `mixp/mixn = 8.282 / 8.125 fF`; `dp/dn = 28.813 / 28.239 fF`; `ep/en = 26.956 / 26.679 fF` |
| `serdes_rx_cmos_deser16_pdk` | `30.1 / 10.5 / 42.8 / 16.6 / 0.0%` (**strict `0.0%` M5**) | `d0..3 / e0..3 = 3.962–4.240 fF`; `ckd0 / ckd2 = 9.833 / 10.007 fF` (**`Δ = 0.174 fF`**); `wclk = 5.924 fF`; every signal port `< 1 Ω` RCX |
| `serdes_rx_cmos_top_pdk` | `23.3 / 12.4 / 29.9 / 14.1 / 20.3%` *(M5 = interdigitated `vdd/vss` power comb + `rxp/rxn` pads)* | `rxp / rxn = 19.550 / 19.889 fF` (**`\|ΔC\| = 0.339 fF`**); `ctle_p / ctle_n = 62.443 / 62.929 fF` (**`\|ΔC\| = 0.486 fF`** across all 8 slicers); `c0..c7 = 1.538–1.888 fF`; `wclk = 6.291 fF`; every signal port `< 1 Ω` RCX |

## Post-Layout CPEX Electrical Verification (`serdes_rx_cmos_top_pdk_pex.spice`)

Verified with `analog/rx/cmos_rx/tb/postlayout/verify_rx_v2_pex.py --workers 2` driven by real signed-off TX v4 SST (`FFE=3`) → `C2_loss6` Stage B far-end waveforms (`results/analog/rx/cmos_rx/postlayout_v2/20261122T032651Z_rx_v2_cpex/summary.json`):

| Corner | PI Code | Data Errors | Det. Edge Errors | BBPD Vote | `wclk` Setup / Hold | CPEX CTLE Eye (`H / W`) | CPEX Power (`mW` / `pJ/b`) | vs. Schematic Power | Status / Findings |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `tt_v1800_t27` | `62` | **0 / 64** | **0 / 30** | `+0 / 22` | **1,454 / 2,461 ps** | `116.3 mV / 0.890 UI` | `27.60 mW` (`6.90 pJ/b`) | `+43.6%` (`19.22 mW`) | **PASS** (4 full words, dead-center lock) |
| `ff_v1950_t-40` | `53` | **0 / 64** | `4 / 28` *(e0/e2 only)* | `-20 / 22` | **1,645 / 2,284 ps** | `116.9 mV / 0.720 UI` | `34.84 mW` (`8.71 pJ/b`) | `+54.3%` (`22.58 mW`) | **Data PASS; Edge hold bottleneck** *(see below)* |
| `ss_v1650_t-40` | `09` | — *(PI stalled)* | — | — | — | **`138.0 mV / 0.880 UI`** | `3.06 mW` *(FE only)* | — (`13.72 mW`) | **FE PASS; 2 GHz PI CPEX bottleneck** *(see below)* |

### Honest Post-Layout CPEX Bottleneck Audit (Actionable for Phase 3 Closure)

1. **`ss_v1650_t-40` 2 GHz PI Rotator CPEX Stall (`serdes_rx_pi_rotator_2g_pdk`)**:
   - The analog front-end (`term + bias_ctle + ctle + 8× slicer` load) passes strongly under full CPEX (`138.0 mV / 0.880 UI` CTLE eye).
   - Direct internal CPEX probing (`results/analog/rx/cmos_rx/postlayout_v2/diag_rot_chain_ss/`) pinpointed the stall to two 2 GHz internal nodes inside pre-existing `serdes_rx_pi_rotator_2g_pdk`:
     - `cb0..cb7` carry `16–22 fF` interconnect CPEX on the `1.00/2.80` `Xin0..7` input buffers → at `SS 1.65 V -40 °C`, PMOS rise collapses duty cycle (`0.00..1.25 V`, mean `0.47 V`).
     - `cap/can/cbp/cbn` carry `22–23 fF` interconnect CPEX on `1.40/3.30` `pi_mux4_tg` `Xout` → pinned at `1.50–1.65 V` (`0.08–0.13 Vpp`), leaving `mixp/mixn` at `0.000 V` DC.
     - Downstream `dp/dn/ep/en` also carry `26.7–28.8 fF` interconnect CPEX (`21.8 fF` inside `qdiv2` + `7 fF` stitch) on `0.95/3.10` `Xr2p/Xr2n` (`~6×` schematic load).
   - **Remediation**: Co-optimize `rx_cmos_pi.spice` (`Xin0..7`, `Xout`, `Xr2p/n` sizing) + compact `cb0..7`/`cap..cbn`/`dp..en` wiring in `build_rx_cmos_pi_pdk.py` to cut 2 GHz internal CPEX by ≥2×.
2. **`ff_v1950_t-40` Fast-Corner Hold Race on `e0/e2` (`serdes_rx_cmos_deser16`)**:
   - Co-locating `deser16` input clock receivers (`Xck0_i1/Xck2_i1`) directly between Bank A & Bank B drivers cut `ck0_1b/ck2_1b` CPEX from `21.4 fF → < 5 fF` and `ck0b/ck0bb` from `145 fF → 129–132 fF`, completely eliminating all edge errors at `tt_v1800_t27` (`0/30`).
   - At `ff_v1950_t-40`, all 64 data bits (`0/64`) and lanes `e1/e3` (`0/14`) pass cleanly, but `e0` (`cke0=125 ps → ck0b=0 ps`) and `e2` (`cke2=625 ps → ck0bb=500 ps`) — the only two lanes in `rx_cmos_deser16.spice` with a `125 ps` nominal hold window — still show `4/28` shoot-through transitions (`bits[j] → bits[j+4]`) when fast slicer `t_cq` (~70 ps) meets the `~180 ps` CPEX Bank B clock insertion delay.
   - **Remediation**: Add a half-cycle pre-aligner on `e0` (`ck0bb`) and `e2` (`ck0b`), matching `Xd0_a` and giving all 8 lanes `≥ 250–375 ps` post-layout hold margin.

## Architecture & Craftsmanship Notes

1. **`serdes_rx_term_pdk`**: Two stacked `nx=4` blocks of `sky130_fd_pr__res_high_po_5p73 l=2.34` in 2D common-centroid ABBA/BAAB with merged central p-sub guard ring, East M2+M3 `vcm` spine, and West M3→M4→M5 `inp/inn` trunks.
2. **`serdes_rx_ctle_pdk`**: Compact `979.9 µm²` (`AR = 1.43`) analog layout combining a MIM-free North signal band (2D common-centroid LVT NMOS input quad flanked by split `res_high_po_2p85 l=4.14` loads, `|ΔC(outp, outn)| < 0.10 fF`) with a 3D Under-MIM South band (3× `9.81×9.81 µm` MIM1 caps over 16-finger ABBA tail sinks, `Xrdeg`, and static EQ switches).
3. **`serdes_rx_dt_slicer_pdk`**: Abutment-ready `29.60 µm`-pitch (`933.6 µm²`, `AR = 0.94`) winged-trim slice tiling seamlessly into an 8× bank (`236.80 µm`) with full-width M3 `vdd`, `vss`, `inp`, `inn` abutment buses, 2 continuous NWELL bands, and central `x_rel = 0` M4 `clk` spine with clean M4 pass-through headroom above `y_rel = 17.5`.
4. **`serdes_rx_qdiv2_8ph_pdk` & `serdes_rx_cmos_pi_8ph_pdk`**: `163.32 × 68.72 µm` (`11,223.4 µm²`, strict `0.0%` M5) Phase-2-synced 2 GHz CMOS PI + deterministic 8-phase ÷2 with mirrored `pi_diff_chan` symmetry (`|ΔC(mixp, mixn)| ≤ 0.16 fF`) and cardinal ports (`c0..c7/rst_n` West, `a/b/f` South, `ckd0..3/cke0..3` North).
5. **`serdes_rx_cmos_deser16_pdk`**: `238.46 × 86.48 µm` (`20,622.0 µm²`, strict **`0.0%` M5**) 8-column bit-sliced CMOS deserializer directly pitch-matched (`29.60 µm`/col) to the 8× slicer bank, with zero cross-column data wiring, co-located center clock receiver + Bank A/B drivers, centered Row 6 Johnson ÷4 + `wcap/wcapb/wclk` drivers, 9 full-height vertical M4 power straps, and `< 1 Ω` RCX wire resistance on every signal port.
6. **`serdes_rx_cmos_top_pdk`**: `245.30 × 205.52 µm` (`50,414.1 µm²`, `AR = 1.19`, matching TX v4 `~231.5 µm` width) full RX v2 macro integrating all 6 sub-blocks with an isolated East analog front-end bay (`term` + `ctle` + exact 1:1 `bias_ctle` diode separated by a grounded M4/M5 shield from the 2 GHz PI), equalized-span (`82.0 µm`) 8-phase 1 GHz clock bus with straight M4 pass-through across all 8 slicers into `deser16`, center-fed symmetric differential `ctle_p/ctle_n` trunk (`|ΔC| = 0.486 fF`), and a non-crossing interdigitated `2.2–2.4 µm` M5 `vdd`/`vss` power comb with 30+ distributed `via4` drops.

## Reproduction & Artifacts

- Generator scripts: [`build_rx_v2_fe_pdk.py`](../../build_rx_v2_fe_pdk.py), [`build_rx_cmos_pi_pdk.py`](../../build_rx_cmos_pi_pdk.py), [`build_rx_cmos_deser16_pdk.py`](../../build_rx_cmos_deser16_pdk.py), [`build_rx_cmos_top_pdk.py`](../../build_rx_cmos_top_pdk.py), [`rx_layout_common.py`](../../rx_layout_common.py), [`build_rx_ctle_pdk.py`](../../build_rx_ctle_pdk.py), [`build_rx_dt_slicer_pdk.py`](../../build_rx_dt_slicer_pdk.py)
- Post-layout CPEX bench: [`verify_rx_v2_pex.py`](../../../tb/postlayout/verify_rx_v2_pex.py)
- Machine-readable signoff summary: [`summary.json`](summary.json)
- Independent review directories (`review_cell.py --rc`): `results/layout/rx_cmos_v2/{review,opt_v2_1/review,pi/review,deser16/review,top/review}/<cell>/`
- Post-layout CPEX campaign: `results/analog/rx/cmos_rx/postlayout_v2/20261122T032651Z_rx_v2_cpex/`
