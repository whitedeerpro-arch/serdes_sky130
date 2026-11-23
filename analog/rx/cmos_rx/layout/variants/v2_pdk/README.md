# RX v2.2 Zero-CML (CMOS) 4 Gb/s Receiver — SKY130A PDK Physical Layout Suite (`v2_pdk`)

Complete SKY130A PDK physical layout suite for the 4 Gb/s **RX v2.2 Zero-CML (CMOS)** receiver: analog front-end (`serdes_rx_term_pdk`, `serdes_rx_ctle_pdk`), quarter-rate double-tail dynamic CMOS slicer (`serdes_rx_dt_slicer_pdk`, boosted precharge/equalizer `wpre=5.1` / `weq=2.1` eliminating `SS -40 °C` precharge hysteresis), compressed 3D MIM-over-`r16` 2 GHz 64-code pure-CMOS Phase Interpolator + anti-Miller 8-phase 1 GHz quadrature ÷2 (`serdes_rx_qdiv2_8ph_pdk`, `serdes_rx_pi_rotator_2g_pdk`, `serdes_rx_cmos_pi_8ph_pdk`, `-23.5%` area vs v2.1 at strict `0.0%` M5), pitch-matched 8→32 static CMOS deserializer (`serdes_rx_cmos_deser16_pdk`, `e0/e2` half-cycle hold-race pre-aligners + balanced `wp/wn=4.0` 3-stage `FO ≤ 4.5` clock tree + faster `dsr_dff_1g`), and Option 1 re-floorplanned top-level receiver macro (`serdes_rx_cmos_top_pdk`, `245.30 × 195.40 µm`, `-10.12 µm` height / `-4.92%` area vs v2.1). Independently verified with `verification/layout/review_cell.py --rc` and full 3-corner post-layout CPEX transient simulation (`analog/rx/cmos_rx/tb/postlayout/verify_rx_v2_pex.py` — **3/3 FULL PASS**).

## Physical Signoff Summary (All 8 Deliverables)

| Cell | Size (`W × H µm`) | Area (`µm²`) | AR | Devices (Raw / Merged) | Ports | Magic Full DRC | Netgen LVS | Prop Err | Floating Poly | `review_cell.py` (`phys` / `rc_dev`) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `serdes_rx_term_pdk.mag` | `33.35 × 16.36` | `545.61` | `2.04` | `8 / 2` | `4 / 4` | **0** | **MATCH** | **False** | **0** | `True` / `True` |
| `serdes_rx_ctle_pdk.mag` | `37.40 × 26.20` | `979.88` | `1.43` | `20 / 19` | `9 / 9` | **0** | **MATCH** | **False** | **0** | `True` / `True` |
| `serdes_rx_dt_slicer_pdk.mag` | `29.60 × 31.54` | `933.58` | `0.94` | `51 / 51` | `13 / 13` | **0** | **MATCH** | **False** | **0** | `True` / `True` |
| `serdes_rx_qdiv2_8ph_pdk.mag` | `122.40 × 16.57` | `2,028.17` | `7.39` | `146 / 146` | `15 / 15` | **0** | **MATCH** | **False** | **0** | `True` / `True` |
| `serdes_rx_pi_rotator_2g_pdk.mag` | `121.90 × 51.40` | `6,265.66` | `2.37` | `588 / 588` | `38 / 38` | **0** | **MATCH** | **False** | **0** | `True` / `WL+conn=True`* |
| `serdes_rx_cmos_pi_8ph_pdk.mag` | `124.88 × 68.72` | `8,581.75` | `1.82` | `734 / 734` | `47 / 47` | **0** | **MATCH** | **False** | **0** | `True` / `WL+conn=True`* |
| `serdes_rx_cmos_deser16_pdk.mag` | `238.46 × 86.48` | `20,622.02` | `2.76` | `1,868 / 1,868` | `52 / 52` | **0** | **MATCH** | **False** | **0** | `True` / `WL+conn=True`* |
| `serdes_rx_cmos_top_pdk.mag` | `245.30 × 195.40` | `47,931.62` | `1.26` | `3,039 / 3,032` | `76 / 76` | **0** | **MATCH** | **False** | **0** | `True` / `WL+conn=True`* |

Notes:
- `serdes_rx_term_pdk` port count: `rx_ctle_pdk.spice` defines 4 ports (`inp inn vcm vss`), including the shared p-sub guard ring terminal `vss` for the 8 `sky130_fd_pr__res_high_po_5p73` bars.
- `*` On cells containing supply-shorted 1-finger dummy MOS-cap FETs (`D=S=B=vdd/vss`, mandated by `rx_cmos_pi.spice` and `rx_cmos_deser16.spice`), unmodified `review_cell.py` passes `physical_passed = True` (`DRC = 0`, `LVS = MATCH`, `0` property errors, `0` floating poly) and Magic native RCX (`*_rcx.spice`) preserves 100% of device counts, models, `W/L/ad/pd`, terminal parent nets, and resistor subnetwork connectivity; only 2 supply-shorted dummy MOS-caps differ in `as/ps` between CPEX and RCX due to Magic `ext2spice` global node-diffusion fallback vs `extresist` `rnode`s (`rc_audit.json` in each review directory).

## Metal Utilization & CPEX Symmetry

| Cell | M1 / M2 / M3 / M4 / M5 Share | Key Differential CPEX & Balance (`total_node_fF`) |
|---|---|---|
| `serdes_rx_term_pdk` | `10.8 / 26.9 / 41.5 / 12.0 / 8.9%` | `inp = 12.300 fF`, `inn = 12.605 fF` (**`\|ΔC\| = 0.305 fF`**), `vcm = 10.076 fF` |
| `serdes_rx_ctle_pdk` | `16.2 / 22.0 / 51.0 / 10.7 / 0.0%` *(M3 includes `357.5 µm²` MIM bottom plates)* | `inp = 4.317 fF`, `inn = 4.301 fF` (**`\|ΔC\| = 0.016 fF`**); `outp = 7.156 fF`, `outn = 7.061 fF` (**`\|ΔC\| = 0.095 fF`**) |
| `serdes_rx_dt_slicer_pdk` | `38.1 / 31.5 / 19.2 / 11.2 / 0.0%` (`M1+M2 = 69.6%`) | `inp/inn = 5.398 / 5.364 fF` (**`Δ = 0.034 fF`**); `fn/fp = 9.993 / 9.507 fF` (`Δ = 0.486 fF`); `outn_b/outp_b = 9.290 / 9.413 fF` (**`Δ = 0.123 fF`**); `qp/qn = 3.536 / 3.517 fF` (**`Δ = 0.019 fF`**); `clk = 8.163 fF` |
| `serdes_rx_qdiv2_8ph_pdk` | `31.1 / 10.6 / 46.9 / 11.3 / 0.0%` (**strict `0.0%` M5**) | `ckd0..3 = 4.641, 5.453, 5.931, 4.526 fF`; `cke0..3 = 4.206, 4.600, 6.202, 4.316 fF`; `dp/dn = 17.799 / 15.560 fF`; `ep/en = 16.708 / 15.445 fF` |
| `serdes_rx_pi_rotator_2g_pdk` | `31.4 / 17.6 / 29.2 / 21.8 / 0.0%` (**strict `0.0%` M5**) | `c0..c7 = 1.719–1.731 fF` (**`0.012 fF` spread**); Edge `mixp/mixn = 8.415 / 8.543 fF` (**`Δ = 0.128 fF`**); Data `mixp/mixn = 8.490 / 8.409 fF` (**`Δ = 0.081 fF`**); `dp/dn = 1.942 / 1.919 fF`; `ep/en = 1.855 / 1.942 fF` |
| `serdes_rx_cmos_pi_8ph_pdk` | `30.7 / 15.6 / 33.4 / 20.3 / 0.0%` (**strict `0.0%` M5**) | `c0..c7 = 1.837–1.866 fF` (**`0.029 fF` spread**); Edge `mixp/mixn = 8.443 / 8.559 fF`; Data `mixp/mixn = 8.501 / 8.433 fF`; `dp/dn = 25.202 / 21.838 fF`; `ep/en = 23.489 / 21.832 fF` |
| `serdes_rx_cmos_deser16_pdk` | `30.4 / 10.8 / 42.6 / 16.2 / 0.0%` (**strict `0.0%` M5**) | `d0..3 / e0..3 = 4.010–4.365 fF`; `ckd0 / ckd2 = 12.046 / 10.809 fF`; `wclk = 6.025 fF`; every signal port `< 1 Ω` RCX |
| `serdes_rx_cmos_top_pdk` | `23.8 / 12.5 / 29.3 / 13.7 / 20.7%` *(M5 = interdigitated `vdd/vss` power comb + `rxp/rxn` pads)* | `rxp / rxn = 24.355 / 24.511 fF` (**`\|ΔC\| = 0.156 fF`**); `ctle_p / ctle_n = 59.308 / 59.547 fF` (**`\|ΔC\| = 0.239 fF`** across all 8 slicers, trunk `-70.3%` shorter vs v2.1); `c0..c7 = 2.150–2.474 fF`; `wclk = 6.586 fF` |

## Post-Layout CPEX Electrical Verification (`serdes_rx_cmos_top_pdk_pex.spice`)

Verified with `analog/rx/cmos_rx/tb/postlayout/verify_rx_v2_pex.py --workers 2` driven by real signed-off TX v4 SST (`FFE=3`) → `C2_loss6` Stage B far-end waveforms (`results/analog/rx/cmos_rx/postlayout_v2_2/20261122_rx_v2_2_final_3of3_pass/summary.json`, **`all_passed = True`**):

| Corner | PI Code | Data Errors | Det. Edge Errors | BBPD Vote | `wclk` Setup / Hold | CPEX CTLE Eye (`H / W`) | CPEX Power (`mW` / `pJ/b`) | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `tt_v1800_t27` | `49` | **0 / 64** | **0 / 30** | `-21 / 21` | **1,500 / 2,411 ps** | `115.6 mV / 0.870 UI` | `36.11 mW` (`9.03 pJ/b`) | **FULL PASS** |
| `ss_v1650_t-40` | `48` | **0 / 64** | **0 / 27** | `-14 / 22` | **1,191 / 2,693 ps** | `127.4 mV / 0.880 UI` | `25.78 mW` (`6.45 pJ/b`) | **FULL PASS** |
| `ff_v1950_t-40` | `00` | **0 / 64** | **0 / 30** | `-21 / 21` | **1,664 / 2,260 ps** | `114.8 mV / 0.710 UI` | `43.74 mW` (`10.94 pJ/b`) | **FULL PASS** |

### PI v2.2g 64-Code Standalone CPEX Verification (`serdes_rx_cmos_pi_8ph_pdk_pex.spice`, `40 fF`/phase)

- **`tt_v1800_t27`**: **64 / 64 codes locked** to `1.000 GHz` (`T = 999.8–1000.1 ps`), **100% strictly monotonic** (`step = 5.48–14.01 ps`), **`|INL| = 0.0177 UI` (`4.43 ps`)**, `|DNL| = 0.0248 UI` (`6.20 ps`), `Vpp_min = 1.861 V` (`results/analog/rx/cmos_rx/postlayout_v2_2/pi_cpex_v22g_64/summary.json`).
- **`ss_v1650_t-40`**: **63 / 64 codes locked** within `12–15 ns` (`c58` still settling at `15 ns`), `|INL| = 0.0996 UI` (`24.90 ps`) across the 63 locked codes (`< 0.10 UI` vs `0.88 UI` CTLE eye).

## RX v2.2 Architecture & Closure Highlights

1. **PI v2.2g 3D MIM-over-`r16` X-Axis Compression (`163.32 → 124.88 µm`, `-23.5%` area, strict `0.0%` M5)**:
   - Stacked all 8 `4.1 × 4.1 µm` MIM1 caps (`Xcmix`, `Xcac`) directly over `r16` (`Xcmix` M3 bottom plate = `vss`, `Xcac` M3 bottom plate = `mixp/mixn` Faraday-shielding `acp/acn`), rotated `r2` vertically beside Stage 5, eliminated the `8.5 µm` east loopback with a direct upward stitch into `qdiv2`, and applied anti-Miller interleaved M3 routing + 4× 2 GHz clock CC aligners + co-sized `Xin`/`Xout`/`Xip`/`Xr2`/`qdiv2` buffers.
2. **Double-Tail Slicer `SS -40 °C` Precharge Hysteresis Fix (`serdes_rx_dt_slicer_pdk`)**:
   - Boosted `Xpf1/Xpf2/Xpo1/Xpo2` (`wpre: 3.6 → 5.1`, `nf=3`) and `Xpfeq/Xpoeq` (`w=1.0 → 2.1 l=0.18`), collapsing residual differential Stage-2 precharge voltage at `SS 1.65 V −40 °C`, `Vcm = 1.433 V` from `+15.7 mV` to `< 0.1 mV` within the exact same `29.60 × 31.54 µm` footprint.
3. **`deser16` Fast-Corner Hold-Race & `SS -40 °C` Half-Cycle Closure (`serdes_rx_cmos_deser16_pdk`)**:
   - Added `Xe0_a` and `Xe2_p` half-cycle pre-aligners (closing v2.1's `FF -40 °C` `4/28` edge hold race to **`0/30`**), upgraded Bank A/B 1 GHz clock distribution to a balanced `wp/wn=4.0` 3-stage `FO ≤ 4.5` tree (`1.2/4.8 → 2.4/9.6 → 9.6/38.4`), and strengthened `dsr_dff_1g` PMOS (`Xtg1/3 wp=2.20`, `Xm2 1.00/2.00`, `Xbq1 0.80/2.40`) — restoring `49.1%` clock duty cycle (`< 25 ps` dead-zone) and `0/64` data / `0/27` edge errors at `SS 1.65 V −40 °C`.
4. **Option 1 Top-Level Re-Floorplan (`serdes_rx_cmos_top_pdk`: `245.30 × 205.52 → 245.30 × 195.40 µm`, `-10.12 µm` / `-4.92%` area)**:
   - Collapsed the empty `14.48 µm` horizontal M3 clock corridor down to `4.36 µm` by tucking the 8-track 1 GHz `ckd0..3/cke0..3` fanout cleanly between `qdiv2` and `8×slicer`, and moved `CTLE` + `Bias` near the `8×slicer` midpoint (preserving a `~20 µm` grounded isolation bay from the 2 GHz PI while shrinking `ctle_p/ctle_n` horizontal trunk length by **`-70.3%` (`68.8 → 20.4 µm`)**, `|ΔC| = 0.239 fF`).

## Reproduction & Artifacts

- Generator scripts: [`build_rx_v2_fe_pdk.py`](../../build_rx_v2_fe_pdk.py), [`build_rx_cmos_pi_pdk.py`](../../build_rx_cmos_pi_pdk.py), [`build_rx_cmos_deser16_pdk.py`](../../build_rx_cmos_deser16_pdk.py), [`build_rx_cmos_top_pdk.py`](../../build_rx_cmos_top_pdk.py), [`rx_layout_common.py`](../../rx_layout_common.py), [`build_rx_ctle_pdk.py`](../../build_rx_ctle_pdk.py), [`build_rx_dt_slicer_pdk.py`](../../build_rx_dt_slicer_pdk.py)
- Post-layout CPEX bench: [`verify_rx_v2_pex.py`](../../../tb/postlayout/verify_rx_v2_pex.py)
- Machine-readable signoff summary: [`summary.json`](summary.json)
- Independent review directories (`review_cell.py --rc`): `results/layout/rx_cmos_v2/{review,opt_v2_1/review,pi/review,deser16/review,top/review}/<cell>/`
- Post-layout CPEX 3/3 PASS campaign: `results/analog/rx/cmos_rx/postlayout_v2_2/20261122_rx_v2_2_final_3of3_pass/`
- PI 64-code CPEX campaign: `results/analog/rx/cmos_rx/postlayout_v2_2/pi_cpex_v22g_64/`
