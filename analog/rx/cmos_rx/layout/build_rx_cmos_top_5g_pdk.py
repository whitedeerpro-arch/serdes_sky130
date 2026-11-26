#!/usr/bin/env python3
"""SKY130A PDK Physical Layout Builder & Signoff Suite for Complete 5.0 Gb/s RX Analog Top Macro:

  `serdes_rx_cmos_top_5g_pdk` : Complete 5.0 Gb/s Zero-CML (CMOS) + Shunt-Peaked CTLE SerDes RX Top
                                matching `serdes_rx_cmos_top_5g_pdk` in `rx_cmos_top_5g_pdk.spice`
                                1:1 (72 cardinal perimeter ports, ready to mate with `serdes_digital_top_v4`).

Integrated Signed-Off PDK Sub-Macros:
  1. `serdes_rx_pi_4ph_5g_pdk`        (`variants/v5g_4ph_v3_pdk/`): 2.5 GHz 4->8 octature + 64-code CMOS PI + hardened 1.25 GHz QDiv2
  2. `serdes_rx_ctle_shunt_5g_w3_pdk` (`variants/ctle_shunt_5g_w3_pdk/`): W3 gm/Id=10.7 5G shunt-peaked CTLE + compact 57.6x57.6 um 8.204 nH M4+M2 stacked inductor (0% M5)
  3. `serdes_rx_term_pdk`             (`variants/v2_pdk/`): 50 Ohm split RX input termination
  4. `serdes_bias_ctle_v2`            (inline exact PDK LVT diode mirror adjacent to CTLE vbias)
  5. `8x serdes_rx_dt_slicer_5g_pdk`  (`variants/slicer_5g_pdk/`): Abutted 236.80 um quarter-rate 5G StrongARM slicer bank
  6. `serdes_rx_cmos_deser16_pdk`     (`variants/v2_pdk/`): Pitch-matched 236.80 um 8->32 static CMOS deserializer

Rectangular Isolated-Coil Floorplan (~312.1 x 199.4 um = 0.0622 mm^2, AR ~ 1.57):
  - West-South  [0..173.4] x [0..72.7]     : `serdes_rx_pi_4ph_5g_pdk` (0% M5; ip/qp/in/qn + rst_n West; a/b/f South)
  - West-Middle [0..236.8] x [77.1..108.6] : 8x abutted 5G StrongARM slicers + equalized 110 um 8-phase clock channel
  - West-North  [0..236.8] x [111.3..197.3]: Pitch-matched `serdes_rx_cmos_deser16_pdk` (wd0..15, we0..15, wclk North)
  - East Bay    [245.0..302.6] x [33.8..149.1]:
      * Vertically mirrored (`mirror_y=True`) `serdes_rx_ctle_shunt_5g_w3_pdk`:
          - Active core directly aligned with slicer `inp/inn` (84.45/85.25) and VDD (89.5)!
          - Compact 57.6x57.6 um 8.204 nH M4+M2 stacked inductor isolated in North-East quiet bay [245.0..302.6] x [91.5..149.1]
            (8.2 um clear of slicers, 16.2 um clear of M5 power comb, 0% M5 over coil!)
      * `serdes_rx_term_pdk` + `serdes_bias_ctle_v2` directly below CTLE active -> straight vertical M4 `rxp/rxn` feed into CTLE `inp/inn` with zero crossings!
  - Cardinal Perimeter Ports (72 total):
      * West  : ip, qp, in, qn (2.5 GHz LC-VCO I/Q clocks), rst_n, vdd, vss
      * South : a0..7, b0..7, f0..7, eq0, eq1, ibias_ctle, vcm_ref, ctle_p, ctle_n (monitor)
      * East  : rxp, rxn (high-speed analog differential input)
      * North : wd0..15, we0..15, wclk (33-bit 312.5 MHz digital bus -> `serdes_digital_top_v4`)
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rx_layout_common as rlc  # noqa: E402
import build_rx_cmos_top_pdk as top4g  # noqa: E402
import build_rx_ctle_shunt_5g_w3_pdk as ctle5g_w3  # noqa: E402
from rx_layout_common import (  # noqa: E402
    Cell,
    PdkCache,
    grid,
    via1_clean,
    via2_clean,
    via3_pad,
    via4_pad,
)

REPO = rlc.REPO
LAYOUT_VERIF_DIR = REPO / "verification/layout"
if str(LAYOUT_VERIF_DIR) not in sys.path:
    sys.path.insert(0, str(LAYOUT_VERIF_DIR))
import route_manhattan as rm  # noqa: E402
SPICE_DIR = REPO / "analog/rx/cmos_rx/spice"
PI_5G_DIR = HERE / "variants" / "v5g_4ph_v3_pdk"
CTLE_5G_W3_DIR = HERE / "variants" / "ctle_shunt_5g_w3_pdk"
V2_DIR = HERE / "variants" / "v2_pdk"
V2P3_DIR = HERE / "variants" / "v2p3_pdk"
SLICER_5G_DIR = HERE / "variants" / "slicer_5g_pdk"
VARIANT_DIR = HERE / "variants" / "rx_top_5g_pdk"
RESULTS_DIR = REPO / "results" / "layout" / "rx_cmos_5g" / "top"

CELL_NAME = "serdes_rx_cmos_top_5g_pdk"
TOP_PORTS = (
    ["rxp", "rxn", "vcm_ref", "ibias_ctle", "eq0", "eq1"]
    + ["ip", "qp", "in", "qn"]
    + [f"a{i}" for i in range(8)]
    + [f"b{i}" for i in range(8)]
    + [f"f{i}" for i in range(8)]
    + ["rst_n"]
    + [f"wd{i}" for i in range(16)]
    + [f"we{i}" for i in range(16)]
    + ["wclk", "ctle_p", "ctle_n", "vdd", "vss"]
)
OPEN_PORTS = TOP_PORTS + ["ctle_lp_mid", "ctle_ln_mid"]


def _include_flip_y(dst: Cell, src: Cell, dx: float, y_mirror_axis: float) -> None:
    """Include `src` shifted by `dx` and mirrored vertically (`y -> y_mirror_axis - y`)."""
    dx, ym = grid(dx), grid(y_mirror_axis)
    for lyr, rects in src.rects.items():
        for x1, y1, x2, y2 in rects:
            dst.rect(lyr, grid(x1 + dx), grid(ym - y2), grid(x2 + dx), grid(ym - y1))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_ref_spice_5g(
    out_path: Path,
    cell_name: str,
    *,
    pi_dir: Path = PI_5G_DIR,
    slicer_variant: str = "slicer_5g_pdk",
    ctle_variant: str = "ctle_shunt_5g_w3_pdk",
    inductor_open: bool = False,
) -> list[str]:
    """Generate flat 100% PDK-primitive LVS reference netlist for `serdes_rx_cmos_top_5g_pdk`.

    Includes the exact evaluated `*_ref.spice` subcircuits for every signed-off submacro so Netgen
    compares true numeric W/L/NF parameters with zero un-evaluated `{param}` defaults.
    """
    if ctle_variant not in ("w3", "ctle_shunt_5g_w3_pdk"):
        raise ValueError(f"Unsupported CTLE variant {ctle_variant!r}; use 'ctle_shunt_5g_w3_pdk' (or 'w3').")
    term_ref = top4g._resolve_submacro(V2P3_DIR, "serdes_rx_term_pdk_ref.spice").read_text()
    if slicer_variant == "slicer_5g_pdk":
        slicer_ref = (SLICER_5G_DIR / "serdes_rx_dt_slicer_5g_pdk_ref.spice").read_text()
        slicer_subckt = "serdes_rx_dt_slicer_5g_pdk"
    else:
        slicer_ref = top4g._resolve_submacro(V2P3_DIR, "serdes_rx_dt_slicer_pdk_ref.spice").read_text()
        slicer_subckt = "serdes_rx_dt_slicer_pdk"
    deser_ref = top4g._resolve_submacro(V2P3_DIR, "serdes_rx_cmos_deser16_pdk_ref.spice").read_text()
    pi_ref = (pi_dir / "serdes_rx_pi_4ph_5g_pdk_ref.spice").read_text()
    ctle_prim_fn = ctle5g_w3.active_primitive_lines_w3

    bias_sub = (
        ".subckt serdes_bias_ctle_v2_pdk iin vss\n"
        "Xm iin iin vss vss sky130_fd_pr__nfet_01v8_lvt w=8.0 l=0.5 nf=4\n"
        ".ends serdes_bias_ctle_v2_pdk\n"
    )

    if inductor_open:
        ctle_sub = (
            ".subckt serdes_rx_ctle_shunt_5g_open inp inn outp outn lp_mid ln_mid eq0 eq1 vbias vdd vss\n"
            + "\n".join(ctle_prim_fn("lp_mid", "ln_mid"))
            + "\n.ends serdes_rx_ctle_shunt_5g_open\n"
        )
        ports = OPEN_PORTS
        ctle_inst = "Xctle rxp rxn ctle_p ctle_n ctle_lp_mid ctle_ln_mid eq0 eq1 ibias_ctle vdd vss serdes_rx_ctle_shunt_5g_open"
    else:
        ctle_sub = (
            ".subckt serdes_rx_ctle_shunt_5g_dc inp inn outp outn eq0 eq1 vbias vdd vss\n"
            + "\n".join(ctle_prim_fn("vdd", "vdd"))
            + "\n.ends serdes_rx_ctle_shunt_5g_dc\n"
        )
        ports = TOP_PORTS
        ctle_inst = "Xctle rxp rxn ctle_p ctle_n eq0 eq1 ibias_ctle vdd vss serdes_rx_ctle_shunt_5g_dc"

    top_sub = "\n".join([
        f".subckt {cell_name} " + " ".join(ports),
        "Xterm rxp rxn vcm_ref vss serdes_rx_term_pdk",
        "Xbias_ctle ibias_ctle vss serdes_bias_ctle_v2_pdk",
        ctle_inst,
        "Xpi ip qp in qn "
        + " ".join(f"a{i}" for i in range(8)) + " "
        + " ".join(f"b{i}" for i in range(8)) + " "
        + " ".join(f"f{i}" for i in range(8))
        + " rst_n dp dn ep en ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 vdd vss serdes_rx_pi_4ph_5g_pdk",
        f"Xsd0 ctle_p ctle_n ckd0 d0 d0b vdd vss vss vss vss vss vdd vss {slicer_subckt}",
        f"Xsd1 ctle_p ctle_n ckd1 d1 d1b vdd vss vss vss vss vss vdd vss {slicer_subckt}",
        f"Xsd2 ctle_p ctle_n ckd2 d2 d2b vdd vss vss vss vss vss vdd vss {slicer_subckt}",
        f"Xsd3 ctle_p ctle_n ckd3 d3 d3b vdd vss vss vss vss vss vdd vss {slicer_subckt}",
        f"Xse0 ctle_p ctle_n cke0 e0 e0b vdd vss vss vss vss vss vdd vss {slicer_subckt}",
        f"Xse1 ctle_p ctle_n cke1 e1 e1b vdd vss vss vss vss vss vdd vss {slicer_subckt}",
        f"Xse2 ctle_p ctle_n cke2 e2 e2b vdd vss vss vss vss vss vdd vss {slicer_subckt}",
        f"Xse3 ctle_p ctle_n cke3 e3 e3b vdd vss vss vss vss vss vdd vss {slicer_subckt}",
        "Xdeser d0 d1 d2 d3 e0 e1 e2 e3 ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 rst_n "
        + " ".join(f"wd{i}" for i in range(16)) + " "
        + " ".join(f"we{i}" for i in range(16))
        + " wclk vdd vss serdes_rx_cmos_deser16_pdk",
        f".ends {cell_name}",
        "",
    ])

    all_txt = "\n".join([
        f"* LVS reference netlist for {cell_name} (inductor_open={inductor_open}, pi_dir={pi_dir.name})",
        term_ref, bias_sub, ctle_sub, pi_ref, slicer_ref, deser_ref, top_sub,
    ])
    out_path.write_text(all_txt)
    return list(ports)


def build_rx_cmos_top_5g_pdk(
    cache: PdkCache | None = None,
    add_ports: bool = True,
    include_inductor: bool = True,
    pi_dir: Path = PI_5G_DIR,
    slicer_variant: str = "slicer_5g_pdk",
    ctle_variant: str = "ctle_shunt_5g_w3_pdk",
    results_dir: Path = RESULTS_DIR,
) -> tuple[Cell, dict]:
    """Assemble integrated 5.0 Gb/s `serdes_rx_cmos_top_5g_pdk` (72 ports)."""
    if cache is None:
        cache = PdkCache(results_dir / "_pdk_cache")
    if ctle_variant not in ("w3", "ctle_shunt_5g_w3_pdk"):
        raise ValueError(f"Unsupported CTLE variant {ctle_variant!r}; use 'ctle_shunt_5g_w3_pdk' (or 'w3').")
    c = Cell()
    is_w3 = True
    is_compact = True

    # Load all signed-off sub-macros (strip labels so only top-level perimeter ports exist)
    pi_mag = pi_dir / "serdes_rx_pi_4ph_5g_pdk.mag"
    term_mag = top4g._resolve_submacro(V2P3_DIR, "serdes_rx_term_pdk.mag")
    slicer_mag = (
        SLICER_5G_DIR / "serdes_rx_dt_slicer_5g_pdk.mag"
        if slicer_variant == "slicer_5g_pdk" else
        top4g._resolve_submacro(V2P3_DIR, "serdes_rx_dt_slicer_pdk.mag")
    )
    deser_mag = top4g._resolve_submacro(V2P3_DIR, "serdes_rx_cmos_deser16_pdk.mag")
    if include_inductor:
        ctle_mag = CTLE_5G_W3_DIR / "serdes_rx_ctle_shunt_5g_w3_pdk.mag"
        ctle_cell = top4g._read_unlabeled(ctle_mag)
    else:
        act_cell, act_meta = ctle5g_w3.build_rx_ctle_active_5g_w3_pdk(cache, add_ports=False)
        ctle_cell, _ = ctle5g_w3.build_w3_ctle_top(
            act_cell, act_meta, include_inductor=False, add_ports=False
        )

    pi_cell = top4g._read_unlabeled(pi_mag)
    term_cell = top4g._read_unlabeled(term_mag)
    slicer_cell = top4g._read_unlabeled(slicer_mag)
    deser_cell = top4g._read_unlabeled(deser_mag)

    pi_ports = {nm: (x, y) for _l, x, y, nm in Cell.read(pi_mag).labels}
    deser_ports = {nm: (x, y) for _l, x, y, nm in Cell.read(deser_mag).labels}

    # --- 1. South-West Band: 2.5 GHz 4->8 CMOS PI (`173.38 x 72.72 um`, 0% M5) ---
    dx_pi, dy_pi = 1.900, 0.500
    c.include(pi_cell, dx=dx_pi, dy=dy_pi)  # world bbox [0.00, 0.00, 173.38, 72.72]

    # --- 2. Middle Band: 8x Abutted Double-Tail Slicers (`236.80 um` wide!) ---
    col_pitch = 29.600
    dy_slicer = 78.200  # world y in [77.080, 108.620] (4.36 um clock corridor above PI 72.72!)
    slicer_ctrs = [grid(14.800 + col * col_pitch) for col in range(8)]
    for x_ctr in slicer_ctrs:
        c.include(slicer_cell, dx=x_ctr, dy=dy_slicer)

    # --- 3. North Band: Pitch-Matched Deser16 (`236.80 um` wide!) ---
    dx_deser, dy_deser = 0.000, 120.280  # south pins y=111.280, north pins y=197.280
    c.include(deser_cell, dx=dx_deser, dy=dy_deser)

    # --- 4. Isolated East Analog Bay: Vertically Mirrored 5G Shunt-Peaked CTLE + Term + BIAS_CTLE ---
    # Micro-placed W3 bay (`floorplan_opt` + `route_manhattan`):
    #   - Shift CTLE + Term -5.2 um West (`dx_ctle=273.8`, `x_ctle_w=245.0`: 8.2 um clear of slicers, 6.5 um of deser,
    #     16.2 um magnetic clearance from M5 power comb at x=228.8!).
    #   - Slide Term & BIAS +6.0 um North (`dy_term=42.0`) directly beneath CTLE active -> -18% shorter rxp/rxn M4 risers!
    #   - Redistribute `ctle_p/ctle_n` monitor probes from East (70 um cross-over over rxp/rxn!) to South M4 (`x=238.0/241.2`),
    #     eliminating rxp/rxn <-> ctle_p/n input-output feedthrough coupling AND freeing the y=50..54 corridor!
    #   - Auto-route the high-speed 3-terminal `ctle_p/ctle_n` differential feeds via `route_manhattan.route(...)` with
    #     inductor keepout + soft differential proximity repulsion!
    ctle_hx = 28.800 if is_compact else 45.800
    ctle_ind_y2 = 63.800 if is_compact else 97.800
    ctle_vdd_loc = -4.200 if is_compact else -3.600
    dx_ctle = 273.800 if is_compact else 296.000
    y_mir_ctle = 85.300 if is_compact else 86.000
    _include_flip_y(c, ctle_cell, dx=dx_ctle, y_mirror_axis=y_mir_ctle)

    # Mapped CTLE coordinates: (x_local + dx_ctle, y_mir_ctle - y_local)
    x_ctle_w = grid(dx_ctle - ctle_hx)          # 245.000 (compact/w3) or 250.200 (m5m3)
    x_ctle_e = grid(dx_ctle + ctle_hx)          # 302.600 (compact/w3) or 341.800 (m5m3)
    y_ctle_inp = grid(y_mir_ctle - 6.450)
    y_ctle_inn = grid(y_mir_ctle - 5.550)
    y_ctle_op  = grid(y_mir_ctle - 7.300)
    y_ctle_on  = grid(y_mir_ctle - 4.700)
    y_ctle_eq0 = grid(y_mir_ctle - (11.450 if is_w3 else 11.650))
    y_ctle_eq1 = grid(y_mir_ctle - (26.950 if is_w3 else 23.250))
    y_ctle_vb  = grid(y_mir_ctle - (27.200 if is_w3 else 23.600))
    y_ctle_vdd = grid(y_mir_ctle - ctle_vdd_loc)
    y_ctle_vss = grid(y_mir_ctle - (30.400 if is_w3 else 26.600))
    ctle_act_y_loc = 31.300 if is_w3 else 27.500

    # 50 Ohm Term mirrored in X directly South of CTLE East margin (flush East edge, +6 um closer to CTLE!)
    x_mir_term = 284.300 if is_compact else 323.500
    dy_term = 42.000 if is_compact else 36.000
    top4g._include_flip_x(c, term_cell, x_mirror_axis=x_mir_term, dy=dy_term)

    # Exact `serdes_bias_ctle_v2` LVT diode mirror cleanly West of Term & South of CTLE active
    x_bias_c = 256.000 if is_compact else 290.000
    dy_bias = 42.000 if is_compact else 36.000
    bias_pts = top4g._draw_bias_ctle_diode(c, cache, x_bias_c, dy_bias)

    # Cardinal perimeter coordinates
    x_west = -4.200
    x_east = 305.800 if is_compact else 345.000
    y_south = -1.600
    y_north = grid(dy_deser + 77.000)  # 197.280

    # --- 5. Analog Front-End Routing (`rxp/rxn`, `vcm_ref`, `ibias_ctle`, `eq0/eq1`, `ctle_p/ctle_n`) ---
    # 5a. East `rxp/rxn` M5 input pads -> x_east
    y_rxp_term = grid(dy_term + 2.400)  # 44.400 (compact) or 38.400 (m5m3)
    y_rxn_term = grid(dy_term - 2.400)  # 39.600 (compact) or 33.600 (m5m3)
    x_term_m5_start = grid(x_mir_term + 17.000)  # 301.300 (compact) or 340.500 (m5m3)
    c.wire("metal5", [(x_term_m5_start, y_rxp_term), (x_east, y_rxp_term)], 1.800)
    c.wire("metal5", [(x_term_m5_start, y_rxn_term), (x_east, y_rxn_term)], 1.800)

    # Straight vertical M4 risers from Term M4 bars -> CTLE `inp/inn` M3 (passes cleanly over CTLE's M4-free East margin!)
    x_rxp_m4 = grid(x_mir_term - (-13.900))  # 298.200 (compact) or 337.400 (m5m3)
    x_rxn_m4 = grid(x_mir_term - (-16.100))  # 300.400 (compact) or 339.600 (m5m3)
    c.wire("metal4", [(x_rxp_m4, grid(dy_term + 7.550)), (x_rxp_m4, y_ctle_inp)], 0.640)
    via3_pad(c, x_rxp_m4, y_ctle_inp)
    c.wire("metal4", [(x_rxn_m4, grid(dy_term + 6.350)), (x_rxn_m4, y_ctle_inn)], 0.640)
    via3_pad(c, x_rxn_m4, y_ctle_inn)

    # 5b. `vcm_ref`: Term vcm (M3) -> South port (M4)
    x_vcm_s = 266.800 if is_compact else 305.000
    c.wire("metal3", [(x_vcm_s, dy_term), (grid(x_mir_term - 14.400), dy_term)], 0.520)
    via3_pad(c, x_vcm_s, dy_term)
    c.wire("metal4", [(x_vcm_s, y_south), (x_vcm_s, dy_term)], 0.560)

    # 5c. `ibias_ctle`: bias_ctle iin (M2) -> CTLE East vbias (M2) + South port (M4)
    x_bias_in, y_bias_in = bias_pts["iin"]
    y_ibias_bus = 51.800 if is_compact else 50.000  # clean channel between Term top (50.18) and CTLE bottom (54.00)!
    x_vb_east = grid(x_ctle_e + 1.200)  # 303.800 (compact/w3) or 343.000 (m5m3)
    x_ibias_s = x_bias_c
    c.wire("metal2", [
        (x_bias_in, y_bias_in),
        (x_bias_in, y_ibias_bus),
        (x_vb_east, y_ibias_bus),
        (x_vb_east, y_ctle_vb),
        (x_ctle_e, y_ctle_vb),
    ], 0.400)
    via2_clean(c, x_ibias_s, y_ibias_bus)
    via3_pad(c, x_ibias_s, y_ibias_bus)
    c.wire("metal4", [(x_ibias_s, y_south), (x_ibias_s, y_ibias_bus)], 0.480)

    # 5d. `eq0` & `eq1`: CTLE West M1 pins -> South ports (M4)
    x_eq0_s, x_eq1_s = (244.000, 242.800) if is_compact else (248.600, 247.000)
    for x_s, y_e in ((x_eq0_s, y_ctle_eq0), (x_eq1_s, y_ctle_eq1)):
        c.wire("metal1", [(x_s, y_e), (x_ctle_w, y_e)], 0.280)
        via1_clean(c, x_s, y_e)
        via2_clean(c, x_s, y_e)
        via3_pad(c, x_s, y_e)
        c.wire("metal4", [(x_s, y_south), (x_s, y_e)], 0.440)

    # 5e. Auto-Routed Low-Mutual-Cap Differential `ctle_p / ctle_n` Feed + Redistributed South Monitors!
    # Moving monitor probes from East (70 um M3 cross-over over rxp/rxn) to South M4 (`x=238.0 / 241.2`, 3.2 um apart)
    # eliminates 100% of rxp/rxn <-> ctle_p/n input-output feedthrough coupling while cutting total wire capacitance.
    # The high-speed differential interconnects in the compacted 8.2 um corridor are routed automatically by
    # `verification/layout/route_manhattan.py` with inductor keepout + differential soft proximity avoidance!
    y_sl_inp = grid(dy_slicer + 6.250)   # 84.450
    y_sl_inn = grid(dy_slicer + 7.050)   # 85.250
    route_report: dict = {}
    pair_diag: dict = {}

    if is_compact:
        x_mon_p, x_mon_n = 238.000, 241.200
        y_mon_tap_p, y_mon_tap_n = 76.200, 80.600
        # South monitor M4 risers (0.32 um low-cap width, 3.20 um pitch -> ~0 fF P/N mutual cap!)
        c.wire("metal4", [(x_mon_p, y_south), (x_mon_p, y_mon_tap_p)], 0.320)
        c.pad("metal4", x_mon_p, y_mon_tap_p, 0.440)
        c.wire("metal4", [(x_mon_n, y_south), (x_mon_n, y_mon_tap_n)], 0.320)
        c.pad("metal4", x_mon_n, y_mon_tap_n, 0.440)
        # Clean terminal anchor pads at Slicer East (M3) and CTLE West (M4)
        c.pad("metal3", 236.800, y_sl_inp, 0.360)
        c.pad("metal3", 236.800, y_sl_inn, 0.360)
        c.pad("metal4", x_ctle_w, y_ctle_op, 0.440)
        c.pad("metal4", x_ctle_w, y_ctle_on, 0.440)

        # Invoke upgraded `route_manhattan.route(...)` with inductor keepout + diff-pair coupling avoidance
        # Route `ctle_n` first along x=241.2 (1 via3, stays >= 3.5 um clear of VDD @ y=89.5!), then `ctle_p`
        # jumps cleanly underneath on M3 at y=78.0 with a single orthogonal 0.16 um^2 cross (~0.015 fF)!
        ctle_nets = [
            {
                "name": "ctle_n",
                "terminals": [
                    ["metal4", x_ctle_w, y_ctle_on],
                    ["metal4", x_mon_n, y_mon_tap_n],
                    ["metal3", 236.800, y_sl_inn],
                ],
            },
            {
                "name": "ctle_p",
                "terminals": [
                    ["metal4", x_ctle_w, y_ctle_op],
                    ["metal4", x_mon_p, y_mon_tap_p],
                    ["metal3", 236.800, y_sl_inp],
                ],
            },
        ]
        ind_keepout = [{
            "box_um": [x_ctle_w, grid(y_mir_ctle + 6.200), x_ctle_e, grid(y_mir_ctle + ctle_ind_y2)],
            "layers": ["metal3", "metal4", "metal5"],
        }]
        c, route_report = rm.route(
            c,
            [236.600, 75.600, grid(x_ctle_w + 0.400), 86.200],
            ctle_nets,
            layers=("metal3", "metal4"),
            keepouts=ind_keepout,
            diff_pairs=[("ctle_p", "ctle_n")],
            coupling_weight=8.0,
            coupling_radius_um=3.0,
            pair_diagnostics=pair_diag,
        )
        ctle_port_p = ("metal4", x_mon_p, y_south)
        ctle_port_n = ("metal4", x_mon_n, y_south)
    else:
        x_cp_m4, x_cn_m4 = 245.400, 248.000
        c.wire("metal4", [(x_ctle_w, y_ctle_op), (x_cp_m4, y_ctle_op), (x_cp_m4, y_sl_inp)], 0.440)
        via3_pad(c, x_cp_m4, y_sl_inp)
        c.wire("metal3", [(236.800, y_sl_inp), (x_cp_m4, y_sl_inp)], 0.360)
        c.wire("metal4", [(x_ctle_w, y_ctle_on), (x_cn_m4, y_ctle_on), (x_cn_m4, y_sl_inn)], 0.440)
        via3_pad(c, x_cn_m4, y_sl_inn)
        c.wire("metal3", [(236.800, y_sl_inn), (x_cn_m4, y_sl_inn)], 0.360)
        x_mon_p, x_mon_n = 240.600, 243.400
        y_mon_p, y_mon_n = 52.800, 46.800
        for y_sl, x_mon, y_mon in ((y_sl_inp, x_mon_p, y_mon_p), (y_sl_inn, x_mon_n, y_mon_n)):
            via3_pad(c, x_mon, y_sl)
            c.wire("metal4", [(x_mon, y_mon), (x_mon, y_sl)], 0.360)
            via3_pad(c, x_mon, y_mon)
            c.wire("metal3", [(x_mon, y_mon), (x_east, y_mon)], 0.320)
        ctle_port_p = ("metal3", x_east, y_mon_p)
        ctle_port_n = ("metal3", x_east, y_mon_n)

    # --- 6. Equalized-Span 8-Phase 1.25 GHz Clock Distribution (Over-Slicer Collapsed Channel!) ---
    clk_names = ["ckd0", "ckd1", "ckd2", "ckd3", "cke0", "cke1", "cke2", "cke3"]
    clk_y_trks = [
        grid(dy_slicer - 4.700), grid(dy_slicer - 3.800), grid(dy_slicer - 2.900), grid(dy_slicer - 2.000),
        grid(dy_slicer + 0.950), grid(dy_slicer + 1.850), grid(dy_slicer + 2.750), grid(dy_slicer + 3.650),
    ]
    y_sl_clk_bot = grid(dy_slicer - 0.900)   # 77.300
    y_sl_clk_top = grid(dy_slicer + 17.200)  # 95.400
    y_dsr_s = grid(dy_deser - 9.000)         # 111.280

    # M4-free vertical riser x overrides for cke1 & cke3 (avoid slicer trim M4 at x_rel in [-12.75..-7.30])
    cke_x_rise = {"cke1": 116.000, "cke3": 146.000}
    for k, cname in enumerate(clk_names):
        x_pi_ck = grid(dx_pi + pi_ports[cname][0])
        y_pi_ck = grid(dy_pi + pi_ports[cname][1])  # 72.500
        x_rise = cke_x_rise.get(cname, x_pi_ck)
        x_sl_ck = slicer_ctrs[k]
        y_trk = clk_y_trks[k]

        # Equalized 110.00 um horizontal M3 span strictly inside [0..236.0] (14.2 um clear of CTLE at x=250.2!)
        x_lo = min(x_rise, x_sl_ck)
        x_hi = min(236.000, max(x_rise, x_sl_ck, grid(x_lo + 110.000)))
        x_lo = min(x_lo, grid(x_hi - 110.000))
        if abs(x_rise - x_pi_ck) > 0.01:
            y_jog = 73.000
            c.wire("metal4", [(x_pi_ck, y_pi_ck), (x_pi_ck, y_jog), (x_rise, y_jog), (x_rise, y_trk)], 0.440)
        else:
            c.wire("metal4", [(x_pi_ck, y_pi_ck), (x_pi_ck, y_trk)], 0.440)
        top4g._dual_via3_h(c, x_rise, y_trk, dx=0.62)
        c.wire("metal3", [(x_lo, y_trk), (x_hi, y_trk)], 0.460)
        top4g._dual_via3_h(c, x_sl_ck, y_trk, dx=-0.62)
        if y_trk < y_sl_clk_bot:
            c.wire("metal4", [(x_sl_ck, y_trk), (x_sl_ck, y_sl_clk_bot)], 0.440)
        c.wire("metal4", [(x_sl_ck, y_sl_clk_top), (x_sl_ck, y_dsr_s)], 0.440)

    # --- 7. Slicer Hardwired Trim Ties (`t5=vdd`, `t4..t0=vss`) & Straight `qp -> Deser16` Stitches ---
    y_sl_vss = grid(dy_slicer + 0.000)       # 78.200
    y_sl_vdd = grid(dy_slicer + 11.300)      # 89.500
    y_sl_qp  = grid(dy_slicer + 30.250)      # 108.450
    t_vss_offs = (-12.750, -11.850, -10.050, -8.150, -7.300)
    t5_off = -10.950

    for x_ctr in slicer_ctrs:
        for toff in t_vss_offs:
            via3_pad(c, grid(x_ctr + toff), y_sl_vss)
        via3_pad(c, grid(x_ctr + t5_off), y_sl_vdd)
        x_qp = grid(x_ctr - 2.250)
        via2_clean(c, x_qp, y_sl_qp)
        via3_pad(c, x_qp, y_sl_qp)
        c.wire("metal4", [(x_qp, y_sl_qp), (x_qp, y_dsr_s)], 0.400)

    # --- 8. Perimeter Extensions: West `ip/qp/in/qn` + `rst_n`; South `a0..7, b0..7, f0..7` ---
    west_iq_ports: dict[str, tuple[float, float]] = {}
    for nm in ("ip", "qp", "in", "qn"):
        x_p = grid(dx_pi + pi_ports[nm][0])
        y_p = grid(dy_pi + pi_ports[nm][1])
        c.wire("metal3", [(x_west, y_p), (x_p, y_p)], 0.440)
        west_iq_ports[nm] = (x_west, y_p)

    # West rst_n: PI rst_n (0.30, 57.75, M3) -> M4 trunk at x=-0.800 -> Deser16 rst_n (-0.800, 121.58, M4)
    y_pi_rstn = grid(dy_pi + pi_ports["rst_n"][1])        # 57.750
    x_dsr_rstn = grid(dx_deser + deser_ports["rst_n"][0]) # -0.800
    y_dsr_rstn = grid(dy_deser + deser_ports["rst_n"][1]) # 121.580
    c.wire("metal3", [(x_west, y_pi_rstn), (grid(dx_pi + pi_ports["rst_n"][0]), y_pi_rstn)], 0.440)
    via3_pad(c, x_dsr_rstn, y_pi_rstn)
    c.wire("metal4", [(x_dsr_rstn, y_pi_rstn), (x_dsr_rstn, y_dsr_rstn)], 0.520)

    south_ctrl_ports: dict[str, tuple[float, float]] = {}
    for grp in ("a", "b", "f"):
        for k in range(8):
            nm = f"{grp}{k}"
            x_p = grid(dx_pi + pi_ports[nm][0])
            y_p = grid(dy_pi + pi_ports[nm][1])
            c.wire("metal2", [(x_p, y_south), (x_p, y_p)], 0.300)
            south_ctrl_ports[nm] = (x_p, y_south)

    # --- 9. Low-R Interdigitated M5 Power Comb (`vdd` West-Rooted, `vss` East-Rooted; ZERO M5 Near CTLE Inductor!) ---
    # M5 comb stays strictly inside x <= 228.80 -> 21.4 um magnetic clearance from the 8.252 nH CTLE coil (x >= 250.2)!
    x_vdd_m5_w = -4.200
    x_vss_m5_e = 227.600
    x_vdd_m5_end = 222.000
    x_vss_m5_beg = 1.800

    y_m5_vdd_lo  = grid(dy_pi + pi_ports["vdd"][1])       # 53.800 (aligned 1:1 with PI M3 vdd rail!)
    y_m5_vdd_sl1 = grid(dy_slicer + 11.300)               # 89.500 (aligned 1:1 with Slicer & CTLE vdd!)
    y_m5_vdd_sl2 = grid(dy_slicer + 29.350)               # 107.550
    y_m5_vdd_ds0 = grid(dy_deser - 8.400)                 # 111.880
    y_m5_vdd_hi  = grid(dy_deser + 68.400)                # 188.680

    y_m5_vss_lo  = 30.000
    y_m5_vss_sl1 = grid(dy_slicer + 0.000)                # 78.200
    y_m5_vss_sl2 = grid(dy_slicer + 20.750)               # 98.950
    y_m5_vss_ds0 = grid(dy_deser + 0.000)                 # 120.280
    y_m5_vss_hi  = grid(dy_deser + 76.000)                # 196.280

    # Draw VDD M5 Comb
    c.wire("metal5", [(x_vdd_m5_w, y_m5_vdd_lo), (x_vdd_m5_w, y_m5_vdd_hi)], 2.400)
    for yv in (y_m5_vdd_lo, y_m5_vdd_sl1, y_m5_vdd_sl2, y_m5_vdd_ds0, y_m5_vdd_hi):
        c.wire("metal5", [(x_vdd_m5_w, yv), (x_vdd_m5_end, yv)], 2.200)

    # Draw VSS M5 Comb
    c.wire("metal5", [(x_vss_m5_e, y_m5_vss_lo), (x_vss_m5_e, y_m5_vss_hi)], 2.400)
    c.wire("metal5", [(x_vdd_m5_w, y_m5_vss_lo), (x_vss_m5_e, y_m5_vss_lo)], 2.200)  # full-width South VSS -> West port!
    for yv in (y_m5_vss_sl1, y_m5_vss_sl2, y_m5_vss_ds0, y_m5_vss_hi):
        c.wire("metal5", [(x_vss_m5_beg, yv), (x_vss_m5_e, yv)], 2.200)

    # 9a. Stitch PI_4ph vdd (y=53.80) into y_m5_vdd_lo at 5 M4-free locations (West x=-4.2 + 4 interior drops!)
    c.wire("metal3", [(x_vdd_m5_w, y_m5_vdd_lo), (grid(dx_pi + pi_ports["vdd"][0]), y_m5_vdd_lo)], 0.600)
    for xv_d in (x_vdd_m5_w, 50.000, 76.000, 110.000, 145.000):
        via3_pad(c, xv_d, y_m5_vdd_lo)
        via4_pad(c, xv_d, y_m5_vdd_lo)

    # 9b. Stitch PI_4ph vss (y=52.80) into y_m5_vss_lo (30.00) at 3 clean M4-free locations
    y_pi_vss = grid(dy_pi + pi_ports["vss"][1])  # 52.800
    x_vss_pi_w = -2.000  # 2.20 um East of West VDD via4 (-4.20) & 1.20 um West of rst_n M4 (-0.80) -> 0 conflict!
    c.wire("metal3", [(x_vss_pi_w, y_pi_vss), (grid(dx_pi + pi_ports["vss"][0]), y_pi_vss)], 0.600)
    via3_pad(c, x_vss_pi_w, y_pi_vss)
    c.wire("metal4", [(x_vss_pi_w, y_m5_vss_lo), (x_vss_pi_w, y_pi_vss)], 0.800)
    via4_pad(c, x_vss_pi_w, y_m5_vss_lo)
    if pi_dir.name in ("v5g_4ph_v2_pdk", "v5g_4ph_v3_pdk"):
        # v5g_4ph_v2_pdk / v3_pdk have wide M4-free vertical alleys at x in [41.64..50.64] (9.0 um) & [149.91..162.07] (12.2 um)
        for x_vss_drop in (46.200, 156.000):
            via3_pad(c, x_vss_drop, y_pi_vss)
            c.wire("metal4", [(x_vss_drop, y_m5_vss_lo), (x_vss_drop, y_pi_vss)], 0.800)
            via4_pad(c, x_vss_drop, y_m5_vss_lo)
    else:
        # Direct via4 onto v1 PI's existing full-height M4 VSS spine at x_world = 1.9 + 59.7 = 61.60!
        via4_pad(c, 61.600, y_m5_vss_lo)
        # East PI VSS drop in the M4-free alley x_world = 162.0 (x_local = 160.1, clear of MIM <= 155 & M4 spine 163.7!)
        via3_pad(c, 162.000, y_pi_vss)
        c.wire("metal4", [(162.000, y_m5_vss_lo), (162.000, y_pi_vss)], 0.800)
        via4_pad(c, 162.000, y_m5_vss_lo)

    # 9c. Stitch 5G CTLE vdd (x_ctle_w, 89.50, M3+M4) cleanly into Slicer M3 VDD (236.80, 89.50) & M5 y_m5_vdd_sl1!
    # Keep M4 strictly East of Col-7 `cke3` M4 spine (x=222.00): use M3 across x=222, M4 on [230.0..x_ctle_w], extra M5 drop at x=216.0!
    c.wire("metal3", [(236.800, y_sl_vdd), (x_ctle_w, y_sl_vdd)], 1.600)
    c.wire("metal4", [(230.000, y_sl_vdd), (x_ctle_w, y_sl_vdd)], 1.600)
    for xv_d in (231.000, 238.000, grid(x_ctle_w - 1.200)):
        via3_pad(c, xv_d, y_sl_vdd)
    via3_pad(c, 216.000, y_sl_vdd)
    via4_pad(c, 216.000, y_sl_vdd)

    # 9d. Stitch 5G CTLE vss (x_ctle_w, y_ctle_vss, M3), Term vss (M2), & BIAS_CTLE vss (M2) -> x_vss_m5_e!
    c.wire("metal3", [(x_vss_m5_e, y_ctle_vss), (x_ctle_w, y_ctle_vss)], 1.600)
    via3_pad(c, x_vss_m5_e, y_ctle_vss)
    via4_pad(c, x_vss_m5_e, y_ctle_vss)
    x_term_vss = grid(x_mir_term - 14.400)
    y_term_vss = grid(dy_term - 4.100)
    x_bias_vss, y_bias_vss = bias_pts["vss"]
    x_fe_vss = 263.000 if is_compact else 298.000
    c.wire("metal2", [(x_fe_vss, y_term_vss), (x_term_vss, y_term_vss)], 0.500)
    c.wire("metal2", [(x_bias_vss, y_bias_vss), (x_fe_vss, y_bias_vss)], 0.560)
    # Clean zero-crossing M3 hop over y_ibias_bus M2
    y_hop_lo = grid(y_ibias_bus - 1.200)
    y_hop_hi = grid(y_ibias_bus + 1.200)
    c.wire("metal2", [(x_fe_vss, y_term_vss), (x_fe_vss, y_hop_lo)], 0.600)
    via2_clean(c, x_fe_vss, y_hop_lo)
    c.wire("metal3", [(x_fe_vss, y_hop_lo), (x_fe_vss, y_hop_hi)], 0.600)
    via2_clean(c, x_fe_vss, y_hop_hi)
    c.wire("metal2", [(x_fe_vss, y_hop_hi), (x_fe_vss, y_ctle_vss)], 0.600)
    via2_clean(c, x_fe_vss, y_ctle_vss)

    # 9e. Stitch 8x Slicer Bank vdd & vss into M5 comb (7 distributed drops per rail, cols 0..6!)
    for x_ctr in slicer_ctrs[:7]:
        x_drop = grid(x_ctr + 8.000)
        for yv in (y_m5_vdd_sl1, y_m5_vdd_sl2, y_m5_vss_sl1, y_m5_vss_sl2):
            via3_pad(c, x_drop, yv)
            via4_pad(c, x_drop, yv)

    # 9f. Stitch Deser16 vdd & vss into M5 comb (6 distributed drops; skip col 3 to clear wcap/wcapb!)
    for col in (0, 1, 2, 4, 5, 6):
        x_drop = grid(col * col_pitch + 22.400)
        for yv in (y_m5_vdd_ds0, y_m5_vdd_hi, y_m5_vss_ds0, y_m5_vss_hi):
            via3_pad(c, x_drop, yv)
            via4_pad(c, x_drop, yv)

    # --- 10. Export Exact 72 Cardinal Perimeter Ports (+ 2 inductor-open pads when `include_inductor=False`) ---
    north_ports = {
        nm: (grid(dx_deser + deser_ports[nm][0]), grid(dy_deser + deser_ports[nm][1]))
        for nm in ([f"wd{i}" for i in range(16)] + [f"we{i}" for i in range(16)] + ["wclk"])
    }

    if add_ports:
        c.port("rxp", "metal5", x_east, y_rxp_term)
        c.port("rxn", "metal5", x_east, y_rxn_term)
        c.port("vcm_ref", "metal4", x_vcm_s, y_south)
        c.port("ibias_ctle", "metal4", x_ibias_s, y_south)
        c.port("eq0", "metal4", x_eq0_s, y_south)
        c.port("eq1", "metal4", x_eq1_s, y_south)
        for nm in ("ip", "qp", "in", "qn"):
            c.port(nm, "metal3", *west_iq_ports[nm])
        for grp in ("a", "b", "f"):
            for k in range(8):
                nm = f"{grp}{k}"
                c.port(nm, "metal2", *south_ctrl_ports[nm])
        c.port("rst_n", "metal3", x_west, y_pi_rstn)
        for nm, pt in north_ports.items():
            c.port(nm, "metal4", *pt)
        c.port("ctle_p", *ctle_port_p)
        c.port("ctle_n", *ctle_port_n)
        c.port("vdd", "metal5", x_west, y_m5_vdd_lo)
        c.port("vss", "metal5", x_west, y_m5_vss_lo)
        if not include_inductor:
            if is_compact:
                c.port("ctle_lp_mid", "metal4", grid(dx_ctle - 3.000), grid(y_mir_ctle + 8.500))
                c.port("ctle_ln_mid", "metal4", grid(dx_ctle + 3.000), grid(y_mir_ctle + 8.500))
            else:
                c.port("ctle_lp_mid", "metal5", grid(dx_ctle - 4.600), grid(y_mir_ctle + 11.000))
                c.port("ctle_ln_mid", "metal5", grid(dx_ctle + 4.600), grid(y_mir_ctle + 11.000))

    return c, {
        "north_ports": north_ports,
        "west_iq_ports": west_iq_ports,
        "south_ctrl_ports": south_ctrl_ports,
        "ctle_bbox_um": [x_ctle_w, grid(y_mir_ctle - ctle_act_y_loc), x_ctle_e, grid(y_mir_ctle + ctle_ind_y2)],
        "ind_bbox_um": [x_ctle_w, grid(y_mir_ctle + 6.200), x_ctle_e, grid(y_mir_ctle + ctle_ind_y2)],
        "auto_route": route_report,
        "auto_route_pair_diag": pair_diag,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pi-variant", default="v5g_4ph_v3_pdk",
                    help="4-phase 5G PI variant subdir under variants/ (default: v5g_4ph_v3_pdk)")
    ap.add_argument("--slicer-variant", choices=["slicer_5g_pdk", "v2p3_pdk"], default="slicer_5g_pdk",
                    help="Slicer variant: slicer_5g_pdk (5G StrongARM 1:1 drop-in, default) or v2p3_pdk (4G double-tail)")
    ap.add_argument("--ctle-variant", choices=["ctle_shunt_5g_w3_pdk", "w3"], default="ctle_shunt_5g_w3_pdk",
                    help="CTLE variant: ctle_shunt_5g_w3_pdk (or alias w3: gm/Id=10.7 + 57.6um M4+M2, 0% M5)")
    ap.add_argument("--signoff", action="store_true",
                    help="Run full Magic DRC=0 + DC-LVS + Inductor-Open LVS + CPEX + PNG and install into variants/rx_top_5g_pdk/")
    args = ap.parse_args()

    pi_dir = HERE / "variants" / args.pi_variant
    slicer_mag_used = (
        SLICER_5G_DIR / "serdes_rx_dt_slicer_5g_pdk.mag"
        if args.slicer_variant == "slicer_5g_pdk" else
        top4g._resolve_submacro(V2P3_DIR, "serdes_rx_dt_slicer_pdk.mag")
    )
    ctle_mag_used = CTLE_5G_W3_DIR / "serdes_rx_ctle_shunt_5g_w3_pdk.mag"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    VARIANT_DIR.mkdir(parents=True, exist_ok=True)
    cache = PdkCache(RESULTS_DIR / "_pdk_cache")

    watch_nets = [
        "rxp", "rxn", "ctle_p", "ctle_n", "vcm_ref", "ibias_ctle",
        "ip", "qp", "in", "qn", "wclk", "rst_n", "vdd", "vss",
    ]

    # 1. Build & verify full flat 5G RX top (with integrated 8.2 nH CTLE inductor)
    w_top = RESULTS_DIR / "top_verify"
    w_top.mkdir(parents=True, exist_ok=True)
    top_mag = (VARIANT_DIR if args.signoff else w_top) / f"{CELL_NAME}.mag"
    top_ref = (VARIANT_DIR if args.signoff else w_top) / f"{CELL_NAME}_ref.spice"
    top_png = (VARIANT_DIR if args.signoff else w_top) / f"{CELL_NAME}.png"

    print(f"\n=== [1/3] Building & Verifying Full Integrated `{CELL_NAME}` (72 ports, pi={args.pi_variant}, slicer={args.slicer_variant}, ctle={args.ctle_variant}) ===", flush=True)
    cell, meta = build_rx_cmos_top_5g_pdk(
        cache=cache, add_ports=True, include_inductor=True,
        pi_dir=pi_dir, slicer_variant=args.slicer_variant, ctle_variant=args.ctle_variant, results_dir=RESULTS_DIR,
    )
    cell.write(top_mag)
    exp_ports = _write_ref_spice_5g(top_ref, CELL_NAME, pi_dir=pi_dir, slicer_variant=args.slicer_variant, ctle_variant=args.ctle_variant, inductor_open=False)
    rep_top = rlc.verify_flat_cell(w_top, CELL_NAME, top_mag, top_ref, exp_ports, timeout_s=480)
    print(
        f"  Top `{CELL_NAME}`: {rep_top['width_um']:.2f} x {rep_top['height_um']:.2f} um "
        f"({rep_top['area_um2']:,.1f} um^2, AR={rep_top['aspect_ratio']:.2f}) | "
        f"DRC={rep_top['drc_total']} FP={rep_top['floating_poly']} "
        f"DC-LVS={rep_top['lvs_match']} prop_err={rep_top['lvs_property_errors']} "
        f"ports={len(rep_top['exported_ports'])}/{len(exp_ports)}",
        flush=True,
    )
    if rep_top["drc_total"] != 0:
        for r in rep_top.get("drc_rules", [])[:20]:
            print("    DRC:", r, flush=True)

    # 2. Build & verify Inductor-Open harness (74 ports: proves lp_mid/ln_mid stay 100% isolated from vdd/vss outside coil!)
    print(f"\n=== [2/3] Running Inductor-Open Interconnect LVS Proof (`{CELL_NAME}_open`, 74 ports) ===", flush=True)
    w_open = RESULTS_DIR / "top_open_verify"
    w_open.mkdir(parents=True, exist_ok=True)
    open_name = f"{CELL_NAME}_open"
    open_mag = w_open / f"{open_name}.mag"
    open_ref = w_open / f"{open_name}_ref.spice"
    open_cell, _ = build_rx_cmos_top_5g_pdk(
        cache=cache, add_ports=True, include_inductor=False,
        pi_dir=pi_dir, slicer_variant=args.slicer_variant, ctle_variant=args.ctle_variant, results_dir=RESULTS_DIR,
    )
    open_cell.write(open_mag)
    open_ports = _write_ref_spice_5g(open_ref, open_name, pi_dir=pi_dir, slicer_variant=args.slicer_variant, ctle_variant=args.ctle_variant, inductor_open=True)
    rep_open = rlc.verify_flat_cell(w_open, open_name, open_mag, open_ref, open_ports, timeout_s=480)
    print(
        f"  Inductor-Open `{open_name}`: DRC={rep_open['drc_total']} FP={rep_open['floating_poly']} "
        f"LVS={rep_open['lvs_match']} prop_err={rep_open['lvs_property_errors']} "
        f"ports={len(rep_open['exported_ports'])}/{len(open_ports)}",
        flush=True,
    )

    # 3. Render PNG & write summary.json
    print(f"\n=== [3/3] Rendering PNG -> {top_png} ===", flush=True)
    rlc.render_png_plot_mag(top_mag, top_png)

    pcaps = rep_top.get("parasitics", {}).get("port_caps_fF", {})
    key_caps = {k: pcaps[k] for k in watch_nets if k in pcaps}
    open_pcaps = rep_open.get("parasitics", {}).get("port_caps_fF", {})
    for k in watch_nets:
        if k in key_caps:
            print(f"  CPEX {k:10s}: {key_caps[k]}", flush=True)
    for k in ("ctle_lp_mid", "ctle_ln_mid"):
        if k in open_pcaps:
            print(f"  OPEN {k:10s}: {open_pcaps[k]}", flush=True)

    summary = {
        "variant": "rx_top_5g_pdk",
        "pdk": "sky130A",
        "cell": CELL_NAME,
        "source_spice": "analog/rx/cmos_rx/spice/rx_cmos_top_5g_pdk.spice",
        "mag": str(top_mag.relative_to(REPO)),
        "mag_sha256": _sha256(top_mag),
        "ref_spice": str(top_ref.relative_to(REPO)),
        "png": str(top_png.relative_to(REPO)),
        "pex_spice": str((w_top / f"{CELL_NAME}_pex.spice").relative_to(REPO)),
        "open_pex_spice": str((w_open / f"{open_name}_pex.spice").relative_to(REPO)),
        "bbox_um": rep_top["bbox_um"],
        "width_um": rep_top["width_um"],
        "height_um": rep_top["height_um"],
        "area_um2": rep_top["area_um2"],
        "area_mm2": round(rep_top["area_um2"] / 1e6, 5),
        "aspect_ratio": rep_top["aspect_ratio"],
        "ctle_bbox_um": meta["ctle_bbox_um"],
        "ind_bbox_um": meta["ind_bbox_um"],
        "auto_route": meta.get("auto_route", {}),
        "auto_route_pair_diag": meta.get("auto_route_pair_diag", {}),
        "expected_port_count": len(exp_ports),
        "exported_port_count": len(rep_top["exported_ports"]),
        "port_count_match": rep_top["port_count_match"],
        "drc_total": rep_top["drc_total"],
        "drc_rules": rep_top.get("drc_rules", []),
        "floating_poly": rep_top["floating_poly"],
        "dc_lvs_match": rep_top["lvs_match"],
        "dc_lvs_property_errors": rep_top["lvs_property_errors"],
        "inductor_open_drc_total": rep_open["drc_total"],
        "inductor_open_lvs_match": rep_open["lvs_match"],
        "inductor_open_lvs_property_errors": rep_open["lvs_property_errors"],
        "metal_shares": rep_top["metal_shares"],
        "key_port_caps_fF": key_caps,
        "inductor_open_ctle_caps_fF": {
            k: open_pcaps[k] for k in ("ctle_lp_mid", "ctle_ln_mid", "ctle_p", "ctle_n", "rxp", "rxn") if k in open_pcaps
        },
        "submacros": {
            "pi_4ph": str((pi_dir / "serdes_rx_pi_4ph_5g_pdk.mag").relative_to(REPO)),
            "ctle_shunt": str(ctle_mag_used.relative_to(REPO)),
            "term": str(top4g._resolve_submacro(V2P3_DIR, "serdes_rx_term_pdk.mag").relative_to(REPO)),
            "slicer": str(slicer_mag_used.relative_to(REPO)),
            "deser16": str(top4g._resolve_submacro(V2P3_DIR, "serdes_rx_cmos_deser16_pdk.mag").relative_to(REPO)),
        },
    }

    if args.signoff:
        import shutil
        for src_p, dst_name in [
            (w_top / f"{CELL_NAME}_lvs.spice", f"{CELL_NAME}_lvs.spice"),
            (w_top / f"{CELL_NAME}_pex.spice", f"{CELL_NAME}_pex.spice"),
            (w_open / f"{open_name}_pex.spice", f"{open_name}_pex.spice"),
        ]:
            if src_p.exists():
                shutil.copy2(src_p, VARIANT_DIR / dst_name)
        (VARIANT_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Wrote {VARIANT_DIR / 'summary.json'}", flush=True)
        assert summary["drc_total"] == 0, f"DRC={summary['drc_total']}"
        assert summary["floating_poly"] == 0, f"FP={summary['floating_poly']}"
        assert summary["dc_lvs_match"] is True and summary["dc_lvs_property_errors"] is False, "DC-LVS failed"
        assert summary["inductor_open_lvs_match"] is True and summary["inductor_open_lvs_property_errors"] is False, "Open-LVS failed"
        assert summary["port_count_match"] is True, "Port count mismatch"
        print(f"SIGNOFF PASS: {CELL_NAME} -> {VARIANT_DIR}", flush=True)
    else:
        (w_top / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
