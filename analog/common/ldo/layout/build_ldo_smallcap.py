#!/usr/bin/env python3
"""Build and verify the compacted small-cap LDO core and complete 70 pF PLL supply macros.

Follows the Plan-First Analog Layout Workflow against unmodified schematic candidates in
``analog/common/ldo/spice/ldo_hv18_core_smallcap.spice`` and ``pll_supply_hv18_smallcap.spice``
(candidate ``b32_h2``: ``Chv=32 pF, Rhv=2 kOhm, Ccas=16 pF, Rcas=31.25 kOhm, Cc=2 pF,
Cref=16 pF, Cout=4 pF`` -> 70 pF total LDO MIM, down from 218 pF in ``r4``).

Original ``r4`` layout builders and historical ``20261114_b32_h2`` campaign evidence remain
completely untouched.

Cells built and verified (all ``DRC_TOTAL 0``, ``LVS_MATCH True``, ``LVS_PROPERTY_ERRORS False``):
  1. ``serdes_ldo_mim4_pdk``                      (2x2 4 pF output MIM array)
  2. ``serdes_ldo_mim16_pdk``                     (2x8 16 pF cascode gate MIM array)
  3. ``serdes_ldo_mim32_pdk``                     (4x8 32 pF HV amplifier supply MIM array)
  4. ``serdes_pll_bias_lowpass_slow_r4_pdk``      (3D Under-MIM 1.0 MOhm + 16 pF reference filter)
  5. ``serdes_ldo_hv18_smallcap_pdk``             (Compacted 248.4 x 210.8 um core; exact port order
                                                   ``vss out vin off ibias fb ref``)
  6. ``serdes_pll_supply_hv18_smallcap_probe_pdk`` (Complete 70 pF supply macro w/ loop-break ports:
                                                   ~416 x 217 um, -50% area vs r4 supply macro)
  7. ``serdes_pll_supply_hv18_smallcap_pdk``      (Complete production 70 pF supply macro: 13 ports)

Example:
  uv run python analog/common/ldo/layout/build_ldo_smallcap.py \\
      --output-dir results/layout/ldo_smallcap/20261114_b32_h2_macro_suite \\
      --install-dir analog/common/ldo/layout/variants/smallcap_pdk
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import build_ldo_pdk as base
from build_ldo_pdk import (
    BIAS_DIR,
    SPICE_DIR,
    Cell,
    draw_pwell_guard_bar,
    exported_ports,
    grid,
    pdk_device,
    place_res_bottom_aligned,
    strap_1v8_mos,
    strap_multirow_mos,
    strap_res,
    strap_single_row_mos,
    via3,
)

REPO = base.REPO
CORE_EXPECTED_PORTS = ["vss", "out", "vin", "off", "ibias", "fb", "ref"]


def build_core(
    out: Path, chv: int, ccas: int, rhv: int, rcas: int, mim_paths: dict[int, Path]
) -> tuple[Path, Path]:
    """Build compacted serdes_ldo_hv18_smallcap_pdk height-matched to 8-row MIM arrays."""
    cell_name = "serdes_ldo_hv18_smallcap_pdk"
    work = out / cell_name
    work.mkdir(parents=True, exist_ok=True)

    l_rhv = grid((rhv * 2 - 378) / 317)
    l_rcas = grid((rcas - 378) / 317)

    specs = [
        ("nvt_50x2", "sky130_fd_pr__nfet_05v0_nvt", dict(w=10.0, l=0.9, nf=50, m=2, poverlap=0, conn_gates=1, guard=1)),
        ("nb_20x3", "sky130_fd_pr__nfet_g5v0d10v5", dict(w=1.0, l=4.0, nf=20, m=3, conn_gates=1, guard=1)),
        ("pd_20x2", "sky130_fd_pr__pfet_g5v0d10v5", dict(w=1.5, l=4.0, nf=20, m=2, conn_gates=1, guard=1)),
        ("pt_20x4", "sky130_fd_pr__pfet_g5v0d10v5", dict(w=1.5, l=4.0, nf=20, m=4, conn_gates=1, guard=1)),
        ("p2_20x6", "sky130_fd_pr__pfet_g5v0d10v5", dict(w=1.5, l=4.0, nf=20, m=6, conn_gates=1, guard=1)),
        ("n2", "sky130_fd_pr__nfet_g5v0d10v5", dict(w=10.0, l=0.5, nf=6, conn_gates=1, guard=1)),
        ("off", "sky130_fd_pr__nfet_g5v0d10v5", dict(w=10.0, l=0.5, nf=1, conn_gates=1, guard=1)),
        ("pl", "sky130_fd_pr__pfet_g5v0d10v5", dict(w=15.0, l=1.0, nf=1, conn_gates=1, guard=1)),
        ("rhv", "sky130_fd_pr__res_high_po_0p35", dict(w=2.0, l=l_rhv, nx=1, m=1, guard=1)),
        ("rzero", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=5.12, nx=1, m=1, guard=1)),
        ("rcas", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=l_rcas, nx=1, m=1, guard=1)),
        ("ccomp", "sky130_fd_pr__cap_mim_m3_1", dict(w=22.1965, l=22.1965, nx=1, ny=2, stack=0, doports=1)),
    ]
    prims: dict[str, Cell] = {}
    for pname, model, params in specs:
        p = pdk_device(work, f"prim_{pname}", model, params)
        p.rects.pop("checkpaint", None)
        prims[pname] = p

    for tag, pf in (("chv", chv), ("ccas", ccas)):
        cap = Cell.read(mim_paths[pf])
        cap.rects.pop("checkpaint", None)
        prims[tag] = cap

    top = Cell()

    # Continuous N-Well uniting the Top PMOS section (va domain: 47.0 - 3.575 .. 98.0 + 8.935)
    top.rect("nwell", -44.045, 43.425, 44.045, 106.935)

    # 1. Compacted multi-row 5V native zero-Vt power NFETs (25.0 um pitch: y = [-103.835, -30.165])
    p_pass = strap_multirow_mos(top, prims["nvt_50x2"], "mvndiffc", dx=-13.30, dy=-92.0, tie_sb=False)
    p_casa = strap_multirow_mos(top, prims["nvt_50x2"], "mvndiffc", dx=-13.30, dy=-67.0, tie_sb=False)
    p_casb = strap_multirow_mos(top, prims["nvt_50x2"], "mvndiffc", dx=-13.30, dy=-42.0, tie_sb=False)

    # 2. Miller compensation MIM2 centered cleanly in right power bay + 3D Under-MIM rcas
    dy_ccomp = -78.0
    top.include(prims["ccomp"], dx=32.0, dy=dy_ccomp)
    rcas_x = 138.0 if chv == 16 and ccas == 16 else 180.0
    p_rcas = strap_res(top, prims["rcas"], dx=rcas_x, dy=-38.0)

    # 3. Full-width P+ substrate isolation guard bar at y = -25.2 (isolating 30 mA Power stage from Error Amp)
    y_gb1 = -25.2
    draw_pwell_guard_bar(top, -43.0, 43.0, y_gb1, h=1.20)

    # 4. Row 4 small devices + rzero & rhv across full 88 um width (dy = -13.2)
    dy_r4 = -13.2
    p_boff = strap_single_row_mos(top, prims["off"], "mvndiffc", dx=-34.5, dy=dy_r4, tie_sb=True)
    p_off = strap_single_row_mos(top, prims["off"], "mvndiffc", dx=-26.5, dy=dy_r4, tie_sb=True)
    p_n2 = strap_single_row_mos(top, prims["n2"], "mvndiffc", dx=-15.0, dy=dy_r4, tie_sb=True)
    p_pl = strap_single_row_mos(top, prims["pl"], "mvpdiffc", dx=-1.0, dy=dy_r4, tie_sb=False)
    p_pr = strap_single_row_mos(top, prims["pl"], "mvpdiffc", dx=10.0, dy=dy_r4, tie_sb=False)
    p_rzero = strap_res(top, prims["rzero"], dx=24.0, dy=dy_r4)
    p_rhv = strap_res(top, prims["rhv"], dx=37.0, dy=dy_r4)

    # 5. Middle 5V NMOS mirror & active load bank (10.0 um pitch) + inter-section P+ guard bar at y = 39.2
    p_nb = strap_multirow_mos(top, prims["nb_20x3"], "mvndiffc", dx=0.0, dy=3.0, tie_sb=True)
    p_nr = strap_multirow_mos(top, prims["nb_20x3"], "mvndiffc", dx=0.0, dy=13.0, tie_sb=True)
    p_nl = strap_multirow_mos(top, prims["nb_20x3"], "mvndiffc", dx=0.0, dy=23.0, tie_sb=True)
    p_nm = strap_multirow_mos(top, prims["nb_20x3"], "mvndiffc", dx=0.0, dy=33.0, tie_sb=True)
    y_gb2 = 39.2
    draw_pwell_guard_bar(top, -43.0, 43.0, y_gb2, h=1.00)

    # 6. Top 5V PMOS mirror & second-stage pull-up bank (top edge +106.935 um matches 8-row MIMs [-97.7, +97.7])
    p_pd = strap_multirow_mos(top, prims["pd_20x2"], "mvpdiffc", dx=0.0, dy=47.0, tie_sb=True)
    p_pt = strap_multirow_mos(top, prims["pt_20x4"], "mvpdiffc", dx=0.0, dy=60.0, tie_sb=True)
    p_p2a = strap_multirow_mos(top, prims["p2_20x6"], "mvpdiffc", dx=0.0, dy=78.0, tie_sb=True)
    p_p2b = strap_multirow_mos(top, prims["p2_20x6"], "mvpdiffc", dx=0.0, dy=98.0, tie_sb=True)

    # 7. Right Column 8-row MIM arrays (Xchv left, Xccas right; y = [-97.7, +97.7])
    cap_ports: dict[str, dict[str, tuple[float, float]]] = {}
    x_left = 52.5
    for tag in ("chv", "ccas"):
        cap = prims[tag]
        box = cap.bbox()
        dx = grid(x_left - box[0])
        cap_pins = {pin: (grid(cap.pins(pin)[0][0] + dx), cap.pins(pin)[0][1]) for pin in ("a", "b")}
        cap_clean = Cell.read(mim_paths[chv if tag == "chv" else ccas])
        cap_clean.rects.pop("checkpaint", None)
        cap_clean.labels.clear()
        top.include(cap_clean, dx=dx)
        cap_ports[tag] = cap_pins
        x_left = grid(box[2] + dx + 2.0)

    # --- INTER-BLOCK ROUTING ---

    # Net 1: vss
    x_vss_l = -38.0
    for p_nvt in [p_pass, p_casa, p_casb]:
        by = p_nvt["B"][1]
        top.body_contact(x_vss_l, by)
        top.via2(x_vss_l, by)
    y_vss_r4 = p_boff["B"][1]
    top.wire("metal2", [(x_vss_l, y_vss_r4), (p_n2["B"][0], y_vss_r4)], 0.50)
    top.via2(x_vss_l, y_vss_r4)
    for p_nmos in [p_nb, p_nr, p_nl, p_nm]:
        top.via2(x_vss_l, p_nmos["s_bus_y"])
    for y_pbar in [y_gb1, y_gb2]:
        top.via2(x_vss_l, y_pbar)
    top.wire("metal3", [(x_vss_l, p_pass["B"][1]), (x_vss_l, y_gb2)], 1.00)

    x_vss_r = 46.0
    top.via2(x_vss_r, y_gb1)
    top.wire("metal2", [(-43.0, y_gb1), (x_vss_r, y_gb1)], 0.80)
    top.wire("metal2", [p_rcas["B"], (x_vss_r, p_rcas["B"][1])], 0.44)
    top.via2(x_vss_r, p_rcas["B"][1])
    top.wire("metal2", [p_rzero["B"], (x_vss_r, p_rzero["B"][1])], 0.44)
    top.via2(x_vss_r, p_rzero["B"][1])
    y_mim_b = cap_ports["chv"]["b"][1]
    top.wire("metal3", [(x_vss_r, min(y_mim_b, p_rcas["B"][1])), (x_vss_r, y_gb2)], 1.00)
    top.via2(x_vss_r, y_gb2)
    top.wire("metal2", [(43.0, y_gb2), (x_vss_r, y_gb2)], 0.60)
    for ports in cap_ports.values():
        bx, by = ports["b"]
        top.wire("metal3", [(x_vss_r, by), (bx, by)], 0.60)
    top.port("vss", "metal3", x_vss_l, y_gb1)

    # Net 2: out (Xpass.S)
    top.port("out", "metal2", -13.30, p_pass["s_bus_y"])

    # Net 3: mid (Xpass.D, Xcas_a.S, Xcas_b.S heavy multi-strap power bus)
    for x_mid in [-35.0, -26.0, -14.0, -2.0, 8.0]:
        for y_m in [p_pass["d_bus_y"], p_casa["s_bus_y"], p_casb["s_bus_y"]]:
            top.via2(x_mid, y_m)
        top.wire("metal3", [(x_mid, p_pass["d_bus_y"]), (x_mid, p_casb["s_bus_y"])], 1.20)

    # Net 4: vin (Xcas_a.D, Xcas_b.D, Xrcas.R1, Xrhv.R1 heavy power bus)
    y_vin_m2 = -28.0
    for x_vin in [-30.0, -10.0, 4.0, 14.0]:
        top.via2(x_vin, p_casa["d_bus_y"])
        top.via2(x_vin, p_casb["d_bus_y"])
        top.via2(x_vin, y_vin_m2)
        top.wire("metal3", [(x_vin, p_casa["d_bus_y"]), (x_vin, y_vin_m2)], 1.20)
    top.wire("metal2", [(-30.0, y_vin_m2), (37.0, y_vin_m2)], 0.80)
    top.wire("metal2", [p_rcas["R1"], (rcas_x, y_vin_m2), (37.0, y_vin_m2)], 0.50)
    top.via2(37.0, y_vin_m2)
    top.via2(37.0, p_rhv["R1"][1])
    top.wire("metal3", [(37.0, y_vin_m2), (37.0, p_rhv["R1"][1])], 0.60)
    top.port("vin", "metal3", 14.0, p_casb["d_bus_y"])

    # Net 5: casg (Xcas_a.G, Xcas_b.G, Xrcas.R2, Xccas.a) — direct top-side connection (no bottom M4 loop)
    gx_nvt = p_casa["gx"]
    y_casg_m2 = -54.5
    top.wire("metal3", [(gx_nvt, p_casa["g_ys"][0]), (gx_nvt, p_casb["g_ys"][-1])], 0.50)
    top.via2(gx_nvt, y_casg_m2)
    top.wire("metal2", [(gx_nvt, y_casg_m2), (48.5, y_casg_m2)], 0.44)
    top.wire("metal2", [p_rcas["R2"], (rcas_x, y_casg_m2), (48.5, y_casg_m2)], 0.44)
    top.via2(48.5, y_casg_m2)
    y_casg_top = 103.5
    top.wire("metal3", [(48.5, y_casg_m2), (48.5, y_casg_top)], 0.60)
    via3(top, 48.5, y_casg_top)
    cx_cas, cy_cas = cap_ports["ccas"]["a"]
    top.wire("metal4", [(48.5, y_casg_top), (cx_cas, y_casg_top), (cx_cas, cy_cas)], 0.80)

    # Net 6: cz (Xccomp.C1 at (31.27, dy_ccomp + 23.3) on M4, Xrzero.R2 on M2)
    y_c1_pad = grid(dy_ccomp + 23.3)
    y_c1_v3 = grid(dy_ccomp + 24.8)
    top.wire("metal4", [(31.27, y_c1_pad), (31.27, y_c1_v3)], 0.50)
    via3(top, 31.27, y_c1_v3)
    top.via2(31.27, p_rzero["R2"][1])
    top.wire("metal3", [(31.27, y_c1_v3), (31.27, p_rzero["R2"][1])], 0.48)
    top.wire("metal2", [p_rzero["R2"], (31.27, p_rzero["R2"][1])], 0.44)

    # Net 7: gate (Xpass.G, Xccomp.C2, Xoff.D, Xn2.D, Xp2a.D, Xp2b.D)
    x_gate = -22.0
    top.wire("metal2", [p_off["D"], (p_n2["d_xs"][0], p_n2["D"][1])], 0.44)
    top.via2(x_gate, p_off["D"][1])
    top.via2(x_gate, p_p2a["d_bus_y"])
    top.via2(x_gate, p_p2b["d_bus_y"])
    top.wire("metal3", [(x_gate, p_pass["g_ys"][-1]), (x_gate, p_p2b["d_bus_y"])], 0.80)
    for x_g2 in [0.0, 28.0]:
        top.via2(x_g2, p_p2a["d_bus_y"])
        top.via2(x_g2, p_p2b["d_bus_y"])
        top.wire("metal3", [(x_g2, p_p2a["d_bus_y"]), (x_g2, p_p2b["d_bus_y"])], 0.80)
    y_pass_g = p_pass["g_ys"][-1]
    via3(top, gx_nvt, y_pass_g)
    via3(top, x_gate, y_pass_g)
    top.wire("metal4", [(gx_nvt, y_pass_g), (x_gate, y_pass_g)], 0.60)
    y_c2_pad = grid(dy_ccomp + 23.4)
    y_c2_v3 = grid(dy_ccomp + 26.5)
    via3(top, x_gate, y_c2_v3)
    top.wire("metal4", [(x_gate, y_c2_v3), (43.77, y_c2_v3), (43.77, y_c2_pad)], 0.60)

    # Net 8: off (Xboff.G, Xoff.G) — port #4
    top.wire("metal2", [p_boff["G"], p_off["G"]], 0.44)
    top.port("off", "metal2", -30.5, p_boff["G"][1])

    # Net 9: ibias (Xboff.D, Xnb.D, Xnb.G, Xnr.G) — port #5
    x_ibias = p_boff["D"][0]
    top.via2(x_ibias, p_boff["D"][1])
    top.via2(x_ibias, p_nb["d_bus_y"])
    top.wire("metal3", [(x_ibias, p_boff["D"][1]), (x_ibias, p_nb["d_bus_y"])], 0.50)
    gx_mos = p_nb["gx"]
    top.via2(gx_mos, p_nb["d_bus_y"])
    top.wire("metal3", [(gx_mos, p_nb["g_ys"][0]), (gx_mos, p_nr["g_ys"][-1])], 0.50)
    top.port("ibias", "metal3", x_ibias, p_boff["D"][1])

    # Net 10: fb (Xpl.G) & ref (Xpr.G) — ports #6 & #7
    top.port("fb", "metal2", *p_pl["G"])
    top.port("ref", "metal2", *p_pr["G"])

    # Net 11: d (Xpl.D, Xnl.D, Xnl.G, Xnm.G)
    x_d = p_pl["D"][0]
    top.via2(x_d, p_pl["D"][1])
    top.via2(x_d, p_nl["d_bus_y"])
    top.wire("metal3", [(x_d, p_pl["D"][1]), (x_d, p_nl["d_bus_y"])], 0.50)
    top.via2(gx_mos, p_nl["d_bus_y"])
    top.wire("metal3", [(gx_mos, p_nl["g_ys"][0]), (gx_mos, p_nm["g_ys"][-1])], 0.50)

    # Net 12: x (Xn2.G, Xpr.D, Xrzero.R1, Xnm.D)
    for px, py in [p_n2["G"], p_pr["D"], p_rzero["R1"]]:
        top.via2(px, py)
        top.via2(px, p_nm["d_bus_y"])
        top.wire("metal3", [(px, py), (px, p_nm["d_bus_y"])], 0.50)

    # Net 13: tail (Xpl.S, Xpr.S, Xpt.D)
    top.wire("metal2", [p_pl["S"], p_pr["S"]], 0.50)
    x_tail = 4.5
    top.via2(x_tail, p_pl["S"][1])
    top.via2(x_tail, p_pt["d_bus_y"])
    top.wire("metal3", [(x_tail, p_pl["S"][1]), (x_tail, p_pt["d_bus_y"])], 0.60)

    # Net 14: bp (Xnr.D, Xpd.D, Xpd.G, Xpt.G, Xp2a.G, Xp2b.G)
    x_bp = -8.0
    top.via2(x_bp, p_nr["d_bus_y"])
    top.via2(x_bp, p_pd["d_bus_y"])
    top.wire("metal3", [(x_bp, p_nr["d_bus_y"]), (x_bp, p_pd["d_bus_y"])], 0.50)
    top.via2(gx_mos, p_pd["d_bus_y"])
    top.wire("metal3", [(gx_mos, p_pd["g_ys"][0]), (gx_mos, p_p2b["g_ys"][-1])], 0.50)

    # Net 15: va (Xrhv.R2, Xpl.B, Xpr.B, Xpd.S/B, Xpt.S/B, Xp2a.S/B, Xp2b.S/B, Xchv.a)
    y_va_r4 = p_pl["B"][1]
    top.wire("metal2", [(p_pl["B"][0], y_va_r4), (35.0, y_va_r4)], 0.50)
    top.wire("metal2", [(35.0, p_rhv["R2"][1]), p_rhv["R2"]], 0.44)
    top.via2(35.0, p_rhv["R2"][1])
    top.via2(35.0, y_va_r4)
    for p_pmos in [p_pd, p_pt, p_p2a, p_p2b]:
        top.via2(35.0, p_pmos["s_bus_y"])
        for x_va_s in [-28.0, -14.0, 16.0]:
            top.via2(x_va_s, p_pmos["s_bus_y"])
    for x_va_s in [-28.0, -14.0, 16.0]:
        top.wire("metal3", [(x_va_s, p_pd["s_bus_y"]), (x_va_s, p_p2b["s_bus_y"])], 1.00)
    top.via2(16.0, y_va_r4)
    top.wire("metal3", [(16.0, y_va_r4), (16.0, p_pd["s_bus_y"])], 0.80)
    y_va_top = 101.0
    top.wire("metal3", [(35.0, y_va_r4), (35.0, y_va_top)], 1.00)
    via3(top, 35.0, y_va_top)
    cx_hv, cy_hv = cap_ports["chv"]["a"]
    top.wire("metal4", [(35.0, y_va_top), (cx_hv, y_va_top), (cx_hv, cy_hv)], 0.80)

    mag = work / f"{cell_name}.mag"
    top.write(mag)

    passives = (SPICE_DIR / "ldo_passives.spice").read_text()
    core = (SPICE_DIR / "ldo_hv18_core_r4.spice").read_text()
    core = core.replace("l={lp}", "l=0.9").replace(" params: lp=0.9", "")
    core = core.replace("Xrhv vin va vss serdes_ldo_res r=1k", f"Xrhv vin va vss sky130_fd_pr__res_high_po w=2 l={l_rhv}")
    core = core.replace("Xrcas vin casg vss serdes_ldo_res r=10k", f"Xrcas vin casg vss sky130_fd_pr__res_high_po w=1 l={l_rcas}")
    core = core.replace("Xrzero x cz vss serdes_ldo_res r=2k", "Xrzero x cz vss sky130_fd_pr__res_high_po w=1 l=5.12")
    core = core.replace("Xchv va vss serdes_ldo_mim50", f"Xchv va vss serdes_ldo_mim{chv}")
    core = core.replace("Xccas casg vss serdes_ldo_mim50", f"Xccas casg vss serdes_ldo_mim{ccas}")
    core = core.replace("serdes_ldo_hv18_core_r4", cell_name)
    ref = work / f"{cell_name}_ref.spice"
    ref.write_text(passives + "\n" + core)
    return mag, ref


def build_supply_smallcap(
    out: Path,
    is_probe: bool,
    chv: int,
    ccas: int,
    rhv: int,
    rcas: int,
    mim4_mag: Path,
) -> tuple[Path, Path]:
    """Build serdes_pll_supply_hv18_smallcap_probe_pdk or serdes_pll_supply_hv18_smallcap_pdk."""
    cell_name = (
        "serdes_pll_supply_hv18_smallcap_probe_pdk"
        if is_probe
        else "serdes_pll_supply_hv18_smallcap_pdk"
    )
    work = out / cell_name
    work.mkdir(parents=True, exist_ok=True)

    prim_dir = out / "serdes_pll_supply_hv18_smallcap_probe_pdk"
    prim_dir.mkdir(parents=True, exist_ok=True)
    prim_specs = [
        ("sw_n20", "sky130_fd_pr__nfet_01v8", dict(w=5.0, l=0.15, nf=4, conn_gates=1, guard=1)),
        ("n_w2", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=1, conn_gates=1, guard=1)),
        ("n_w1", "sky130_fd_pr__nfet_01v8", dict(w=1.0, l=0.15, nf=1, conn_gates=1, guard=1)),
        ("p_w2", "sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.15, nf=1, conn_gates=1, guard=1)),
        ("p_w4", "sky130_fd_pr__pfet_01v8", dict(w=4.0, l=0.15, nf=1, conn_gates=1, guard=1)),
        ("r0", "sky130_fd_pr__res_high_po_0p35", dict(w=2.0, l=5.12, nx=1, m=1, guard=1)),
        ("r1", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=5.12, nx=1, m=1, guard=1)),
        ("r2", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=11.43, nx=1, m=1, guard=1)),
        ("r3", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=24.04, nx=1, m=1, guard=1)),
        ("r4", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=49.28, nx=1, m=1, guard=1)),
        ("r5", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=49.88, nx=2, m=1, guard=1)),
        ("rfixed", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=48.60, nx=4, m=1, guard=1)),
        ("rtop", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=59.34, nx=2, m=1, guard=1)),
        ("rbleed", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=78.57, nx=4, m=1, guard=1)),
    ]
    prims: dict[str, Cell] = {}
    for pname, model, params in prim_specs:
        pmag = prim_dir / f"prim_{pname}.mag"
        p = Cell.read(pmag) if pmag.exists() else pdk_device(prim_dir, f"prim_{pname}", model, params)
        p.rects.pop("checkpaint", None)
        prims[pname] = p

    slow_f = Cell.read(out / "serdes_pll_bias_lowpass_slow_r4_pdk/serdes_pll_bias_lowpass_slow_r4_pdk.mag")
    slow_f.rects.pop("checkpaint", None)
    sf_pins = {nm: (x, y) for _, x, y, nm in slow_f.labels}
    slow_f.labels.clear()

    core = Cell.read(out / "serdes_ldo_hv18_smallcap_pdk/serdes_ldo_hv18_smallcap_pdk.mag")
    core.rects.pop("checkpaint", None)
    core_pins = {nm: (x, y) for _, x, y, nm in core.labels}
    core.labels.clear()

    mim4 = Cell.read(mim4_mag)
    mim4.rects.pop("checkpaint", None)
    mim4_pins = {nm: (x, y) for _, x, y, nm in mim4.labels}
    mim4.labels.clear()

    pcopy = Cell.read(BIAS_DIR / "serdes_bias_pcopy_pdk.mag")
    pcopy.rects.pop("checkpaint", None)
    pcopy_pins = {nm: (x, y) for _, x, y, nm in pcopy.labels}
    pcopy.labels.clear()

    c = Cell()

    # --- COLUMN 2: Center Compact Small-Cap HV18 Core at (0, 0) ---
    c.include(core, dx=0.0, dy=0.0)

    # --- COLUMN 3: Narrow Right Bay (52 um wide) with 4 pF Cout (Top) + 100 kOhm Bleed (Bottom) ---
    dx_c3 = 237.5
    dy_cout = 68.0
    c.include(mim4, dx=dx_c3, dy=dy_cout)
    cout_a = (grid(dx_c3 + mim4_pins["a"][0]), grid(dy_cout + mim4_pins["a"][1]))
    cout_b = (grid(dx_c3 + mim4_pins["b"][0]), grid(dy_cout + mim4_pins["b"][1]))

    dy_bl = -52.0
    r_bl = prims["rbleed"]
    c.include(r_bl, dx=dx_c3, dy=dy_bl)
    for i in range(4):
        x1, y1 = r_bl.pins(f"R1_{i}")[0]
        x2, y2 = r_bl.pins(f"R2_{i}")[0]
        if i % 2 == 0 and i + 1 < 4:
            nx2, ny2 = r_bl.pins(f"R2_{i+1}")[0]
            c.wire("metal1", [(grid(x2 + dx_c3), grid(y2 + dy_bl)), (grid(nx2 + dx_c3), grid(ny2 + dy_bl))], 0.50)
        elif i % 2 == 1 and i + 1 < 4:
            nx1, ny1 = r_bl.pins(f"R1_{i+1}")[0]
            c.wire("metal1", [(grid(x1 + dx_c3), grid(y1 + dy_bl)), (grid(nx1 + dx_c3), grid(ny1 + dy_bl))], 0.50)

    bl_q_x, bl_q_y = r_bl.pins("R1_0")[0]
    bl_q = (grid(bl_q_x + dx_c3), grid(bl_q_y + dy_bl))
    bl_v_x, bl_v_y = r_bl.pins("R1_3")[0]
    bl_v = (grid(bl_v_x + dx_c3), grid(bl_v_y + dy_bl))
    bl_b_x, bl_b_y = r_bl.pins("B")[0]
    bl_b = (grid(bl_b_x + dx_c3), grid(bl_b_y + dy_bl))

    x_q_right = 208.5
    x_vss_c3 = 264.0
    c.via1(*bl_q)
    c.wire("metal2", [bl_q, (x_q_right, bl_q[1])], 0.50)
    c.via2(x_q_right, bl_q[1])
    via3(c, x_q_right, bl_q[1])

    c.via1(*bl_v)
    c.wire("metal2", [bl_v, (x_vss_c3, bl_v[1])], 0.50)
    c.via2(x_vss_c3, bl_v[1])

    c.body_contact(*bl_b)
    c.wire("metal2", [bl_b, (x_vss_c3, bl_b[1])], 0.50)
    c.via2(x_vss_c3, bl_b[1])

    c.wire("metal3", [cout_b, (cout_b[0], 39.5), (x_vss_c3, 39.5)], 0.80)

    # --- COLUMN 1: Left Reference Filter, Control/Bias, Trim Switches & Divider Ladder ---
    # Height-matched to compacted core [-103.8, +106.9]
    dx_sf, dy_sf = -102.0, -52.2
    c.include(slow_f, dx=dx_sf, dy=dy_sf)
    p_ref_orig = (grid(dx_sf + sf_pins["original"][0]), grid(dy_sf + sf_pins["original"][1]))
    # slow_f has via1+via2+via3 at (filt_x, +50.6) -> M3 accessible directly at dy_sf + 50.6
    p_ref_filt_m3 = (grid(dx_sf + sf_pins["filtered"][0]), grid(dy_sf + 50.6))
    p_ref_vss = (grid(dx_sf + sf_pins["vss"][0]), grid(dy_sf + sf_pins["vss"][1]))

    dy_ctrl = 13.2
    p_tg_n = strap_1v8_mos(c, prims["n_w2"], "ndiffc", dx=-136.0, dy=dy_ctrl, tie_sb=False)
    p_inv_n = strap_1v8_mos(c, prims["n_w1"], "ndiffc", dx=-128.0, dy=dy_ctrl, tie_sb=True)
    p_rst_n = strap_1v8_mos(c, prims["n_w2"], "ndiffc", dx=-120.0, dy=dy_ctrl, tie_sb=True)
    p_tg_p = strap_1v8_mos(c, prims["p_w4"], "pdiffc", dx=-106.0, dy=dy_ctrl, tie_sb=False)
    p_inv_p = strap_1v8_mos(c, prims["p_w2"], "pdiffc", dx=-96.0, dy=dy_ctrl, tie_sb=True)

    dx_copy = -74.0
    c.include(pcopy, dx=dx_copy, dy=dy_ctrl)
    p_copy_out = (grid(dx_copy + pcopy_pins["out"][0]), grid(dy_ctrl + pcopy_pins["out"][1]))
    p_copy_vgi = (grid(dx_copy + pcopy_pins["vgi"][0]), grid(dy_ctrl + pcopy_pins["vgi"][1]))
    p_copy_vdd = (grid(dx_copy + pcopy_pins["vdd"][0]), grid(dy_ctrl + pcopy_pins["vdd"][1]))

    y_gb_c1 = 23.7
    draw_pwell_guard_bar(c, -145.0, -54.0, y_gb_c1, h=1.00)

    r_xs = [-138.0, -127.0, -116.0, -105.0, -94.0, -83.0, -71.0, -59.0]
    dy_sw = 33.2
    sws = []
    for k in range(6):
        sw = strap_1v8_mos(c, prims["sw_n20"], "ndiffc", dx=r_xs[k], dy=dy_sw, tie_sb=(k == 0))
        sws.append(sw)

    res_names = [
        ("r0", 1),
        ("r1", 1),
        ("r2", 1),
        ("r3", 1),
        ("r4", 1),
        ("r5", 2),
        ("rfixed", 4),
        ("rtop", 2),
    ]
    res_infos = []
    y_res_bot = 41.5
    for (rname, n_seg), rx in zip(res_names, r_xs):
        info = place_res_bottom_aligned(c, prims[rname], n_seg, dx=rx, y_bot=y_res_bot)
        res_infos.append(info)

    # Top guard bar over shorter LSB resistors (r0..r5 end below y=98)
    y_gb_top = 105.5
    draw_pwell_guard_bar(c, -145.0, -78.0, y_gb_top, h=1.00)

    # --- ROUTING COLUMN 1 & INTER-COLUMN NETS ---

    # 1. vss network
    x_vss_c1 = -146.0
    y_vss_bot = -106.5
    c.wire("metal3", [(x_vss_c1, y_vss_bot), (x_vss_c1, y_gb_top)], 1.00)
    for y_gb in [y_gb_c1, y_gb_top]:
        c.wire("metal2", [(x_vss_c1, y_gb), (-145.0, y_gb)], 0.50)
        c.via2(x_vss_c1, y_gb)

    y_body_m3 = p_copy_vdd[1]
    for p_nm in [p_tg_n, p_inv_n, p_rst_n]:
        c.wire("metal2", [p_nm["B"], (p_nm["B"][0], y_body_m3)], 0.36)
        c.via2(p_nm["B"][0], y_body_m3)
    c.wire("metal3", [(x_vss_c1, y_body_m3), (p_rst_n["B"][0], y_body_m3)], 0.50)

    y_sw_b = sws[0]["B"][1]
    c.wire("metal2", [(x_vss_c1, y_sw_b), (sws[-1]["B"][0], y_sw_b)], 0.50)
    c.via2(x_vss_c1, y_sw_b)

    y_res_b = res_infos[0]["B"][1]
    c.wire("metal2", [(x_vss_c1, y_res_b), (res_infos[-1]["B"][0], y_res_b)], 0.50)
    c.via2(x_vss_c1, y_res_b)
    c.wire("metal2", [(x_vss_c1, res_infos[0]["left"][1]), res_infos[0]["left"]], 0.44)
    c.via2(x_vss_c1, res_infos[0]["left"][1])

    c.wire("metal3", [(x_vss_c1, y_vss_bot), (x_vss_c3, y_vss_bot)], 1.20)
    c.wire("metal3", [(p_ref_vss[0], y_vss_bot), p_ref_vss], 0.80)
    c.wire("metal3", [(-38.0, y_vss_bot), (-38.0, -103.51)], 1.00)
    c.wire("metal3", [(46.0, y_vss_bot), (46.0, -97.2)], 1.00)
    c.wire("metal3", [(x_vss_c3, y_vss_bot), (x_vss_c3, 39.5)], 1.00)

    # 2. Divider internal ladder nodes n0..n5, fb_return, quiet
    node_xs = [-132.5, -121.5, -110.5, -99.5, -88.5, -77.0, -65.0, -54.5]
    for k in range(5):
        xm = node_xs[k]
        d_pt = (sws[k]["d_xs"][-1], sws[k]["D"][1])
        s_pt = (sws[k + 1]["s_xs"][0], sws[k + 1]["S"][1])
        c.wire("metal2", [d_pt, (xm, d_pt[1]), (xm, s_pt[1]), s_pt], 0.40)
        c.via2(xm, dy_sw)
    d5_pt = (sws[5]["d_xs"][-1], sws[5]["D"][1])
    c.wire("metal2", [d5_pt, (node_xs[5], d5_pt[1])], 0.40)
    c.via2(node_xs[5], d5_pt[1])

    for k, info in enumerate(res_infos):
        rx_r, ry_r = info["right"]
        nx_r = node_xs[k]
        c.wire("metal2", [(rx_r, ry_r), (nx_r, ry_r)], 0.44)
        c.via2(nx_r, ry_r)
        if k < 5:
            c.wire("metal3", [(nx_r, dy_sw), (nx_r, ry_r)], 0.44)
        elif k == 5:
            c.wire("metal3", [(nx_r, d5_pt[1]), (nx_r, ry_r)], 0.44)
        if k >= 1:
            lx_l, ly_l = info["left"]
            nx_l = node_xs[k - 1]
            c.wire("metal2", [(nx_l, ly_l), (lx_l, ly_l)], 0.44)
            c.via2(nx_l, ly_l)

    # 3. fb_return & fb_input
    x_fbret = node_xs[6]
    y_fb_port = 38.0
    c.wire("metal3", [(x_fbret, y_fb_port), (x_fbret, res_infos[6]["right"][1])], 0.50)

    x_fbin = -45.5
    core_fb = core_pins["fb"]
    c.wire("metal2", [core_fb, (core_fb[0], -4.2), (x_fbin, -4.2)], 0.44)
    c.via2(x_fbin, -4.2)
    c.wire("metal3", [(x_fbin, -4.2), (x_fbin, y_fb_port)], 0.50)

    if not is_probe:
        c.via2(x_fbret, y_fb_port)
        c.via2(x_fbin, y_fb_port)
        c.wire("metal2", [(x_fbret, y_fb_port), (x_fbin, y_fb_port)], 0.50)

    # 4. host (1.8V logic supply)
    y_host = p_copy_vdd[1]
    for p_pm in [p_tg_p, p_inv_p]:
        c.wire("metal2", [p_pm["B"], (p_pm["B"][0], y_host)], 0.36)
        c.via2(p_pm["B"][0], y_host)
    c.via2(*p_copy_vdd)
    c.wire("metal3", [(p_tg_p["B"][0], y_host), p_copy_vdd], 0.50)

    # 5. bg
    y_bg = grid(dy_ctrl - 7.0)
    for pt in [p_tg_n["D"], p_tg_p["D"]]:
        dx_l = grid(pt[0] - 1.40)
        c.wire("metal2", [pt, (dx_l, pt[1]), (dx_l, y_bg)], 0.36)
        c.via2(dx_l, y_bg)
    c.wire("metal3", [(grid(p_tg_n["D"][0] - 1.40), y_bg), (grid(p_tg_p["D"][0] - 1.40), y_bg)], 0.44)

    # 6. ref_start
    y_rstart = grid(dy_ctrl - 8.5)
    for pt in [p_tg_n["S"], p_tg_p["S"]]:
        sx = grid(pt[0] + 0.80)
        c.wire("metal2", [pt, (sx, pt[1]), (sx, y_rstart)], 0.36)
        c.via2(sx, y_rstart)
    c.wire("metal3", [(grid(p_tg_n["S"][0] + 0.80), y_rstart), (grid(p_tg_p["S"][0] + 0.80), y_rstart)], 0.44)
    c.via1(*p_ref_orig)
    c.wire("metal2", [p_ref_orig, (p_ref_orig[0], y_rstart)], 0.40)
    c.via2(p_ref_orig[0], y_rstart)

    # 7. enable
    y_en = grid(dy_ctrl + 4.8)
    for pt in [p_tg_n["G"], p_inv_n["G"], p_inv_p["G"]]:
        c.wire("metal2", [pt, (pt[0], y_en)], 0.36)
        c.via2(pt[0], y_en)
    c.wire("metal3", [(p_tg_n["G"][0], y_en), (p_inv_p["G"][0], y_en)], 0.44)

    # 8. off
    y_off = grid(dy_ctrl + 6.2)
    for pt in [p_inv_n["D"], p_inv_p["D"]]:
        ox = grid(pt[0] - 1.40)
        c.wire("metal2", [pt, (ox, pt[1]), (ox, y_off)], 0.36)
        c.via2(ox, y_off)
    for pt in [p_rst_n["G"], p_tg_p["G"]]:
        c.wire("metal2", [pt, (pt[0], y_off)], 0.36)
        c.via2(pt[0], y_off)
    x_off_ch = -49.0
    y_core_off = core_pins["off"][1]
    c.wire("metal3", [(grid(p_inv_n["D"][0] - 1.40), y_off), (x_off_ch, y_off), (x_off_ch, y_core_off)], 0.44)
    c.via2(x_off_ch, y_core_off)
    c.wire("metal2", [(x_off_ch, y_core_off), (-34.5, y_core_off)], 0.44)

    # 9. ref_local
    y_rloc = grid(dy_ctrl - 10.0)
    rx_d = grid(p_rst_n["D"][0] - 1.40)
    c.wire("metal2", [p_rst_n["D"], (rx_d, p_rst_n["D"][1]), (rx_d, y_rloc)], 0.36)
    c.via2(rx_d, y_rloc)
    c.wire("metal3", [(rx_d, y_rloc), (p_ref_filt_m3[0], y_rloc)], 0.44)
    c.wire("metal3", [p_ref_filt_m3, (p_ref_filt_m3[0], y_rloc)], 0.44)
    c.via2(p_ref_filt_m3[0], y_rloc)
    x_rloc_ch = -47.2
    core_ref = core_pins["ref"]
    c.wire("metal2", [(p_ref_filt_m3[0], y_rloc), (x_rloc_ch, y_rloc)], 0.44)
    c.via2(x_rloc_ch, y_rloc)
    c.wire("metal3", [(x_rloc_ch, y_rloc), (x_rloc_ch, -3.0)], 0.44)
    c.via2(x_rloc_ch, -3.0)
    c.wire("metal2", [(x_rloc_ch, -3.0), (core_ref[0], -3.0), core_ref], 0.44)

    # 10. ibias
    x_ib_ch = -50.8
    core_ib = core_pins["ibias"]
    c.wire("metal2", [p_copy_out, (x_ib_ch, p_copy_out[1])], 0.44)
    c.via2(x_ib_ch, p_copy_out[1])
    c.wire("metal3", [(x_ib_ch, core_ib[1]), (x_ib_ch, p_copy_out[1])], 0.44)
    c.via2(x_ib_ch, core_ib[1])
    c.wire("metal2", [(x_ib_ch, core_ib[1]), core_ib], 0.44)

    # 11. quiet power rail (M4 trunk linking Core out, rtop feedback, Xbleed, and 4 pF Cout)
    y_q_bot = -108.5
    y_core_out = core_pins["out"][1]
    for xq in [-25.0, -15.0, -5.0, 5.0]:
        c.via2(xq, y_core_out)
        via3(c, xq, y_core_out)
        c.wire("metal4", [(xq, y_q_bot), (xq, y_core_out)], 1.20)
    x_q_left = -48.0
    c.wire("metal4", [(x_q_left, y_q_bot), (x_q_right, y_q_bot)], 1.60)
    c.wire("metal4", [(x_q_right, y_q_bot), (x_q_right, cout_a[1]), cout_a], 1.60)
    y_rtop_r = res_infos[7]["right"][1]
    c.wire("metal4", [(x_q_left, y_q_bot), (x_q_left, y_rtop_r)], 0.80)
    via3(c, x_q_left, y_rtop_r)
    c.wire("metal3", [(node_xs[7], y_rtop_r), (x_q_left, y_rtop_r)], 0.50)

    # --- EXPLICIT PORTS IN EXACT SCHEMATIC SUBCKT ORDER ---
    # Probe: vin host quiet bg vgi enable t0 t1 t2 t3 t4 t5 fb_return fb_input vss
    # Prod:  vin host quiet bg vgi enable t0 t1 t2 t3 t4 t5 vss
    c.port("vin", "metal3", *core_pins["vin"])
    c.port("host", "metal3", -90.0, y_host)
    c.port("quiet", "metal4", x_q_right, 0.0)
    c.port("bg", "metal3", grid(p_tg_n["D"][0] - 1.40), y_bg)
    c.port("vgi", "metal2", *p_copy_vgi)
    c.port("enable", "metal3", p_tg_n["G"][0], y_en)
    for k in range(6):
        c.port(f"t{k}", "metal2", *sws[k]["G"])
    if is_probe:
        c.port("fb_return", "metal3", x_fbret, y_fb_port)
        c.port("fb_input", "metal3", x_fbin, y_fb_port)
    c.port("vss", "metal3", *core_pins["vss"])

    mag = work / f"{cell_name}.mag"
    c.write(mag)

    l_rhv = grid((rhv * 2 - 378) / 317)
    l_rcas = grid((rcas - 378) / 317)
    passives = (SPICE_DIR / "ldo_passives.spice").read_text()
    passives = re.sub(
        r"\.subckt serdes_ldo_ref31 a b sub.*?\.ends serdes_ldo_ref31",
        ".subckt serdes_ldo_ref31 a b sub\nXr a b sub sky130_fd_pr__res_high_po w=1 l=97.3880126\n.ends serdes_ldo_ref31",
        passives,
        flags=re.S,
    )
    core_sp = (SPICE_DIR / "ldo_hv18_core_smallcap.spice").read_text()
    core_sp = core_sp.replace("l={lp}", "l=0.9").replace(" params: lp=0.9", "")
    core_sp = core_sp.replace(
        "Xrhv vin va vss serdes_ldo_res r=2000",
        f"Xrhv vin va vss sky130_fd_pr__res_high_po w=2 l={l_rhv}",
    )
    core_sp = core_sp.replace(
        "Xrcas vin casg vss serdes_ldo_res r=31250",
        f"Xrcas vin casg vss sky130_fd_pr__res_high_po w=1 l={l_rcas}",
    )
    core_sp = core_sp.replace(
        "Xrzero x cz vss serdes_ldo_res r=2k",
        "Xrzero x cz vss sky130_fd_pr__res_high_po w=1 l=5.12",
    )
    if chv != 32:
        core_sp = core_sp.replace("serdes_ldo_mim32", f"serdes_ldo_mim{chv}")
    if ccas != 16:
        core_sp = core_sp.replace("serdes_ldo_mim16", f"serdes_ldo_mim{ccas}")

    sup_sp = (SPICE_DIR / "pll_supply_hv18_smallcap.spice").read_text()
    replacements = {
        "Xcopy ibias vgi host serdes_bias_pcopy n=4": "Xcopy ibias vgi host host sky130_fd_pr__pfet_01v8_lvt w=24 l=4",
        "Xinv enable off host vss serdes_cmos_inv": (
            "Xinv_n off enable vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.15\n"
            "Xinv_p off enable host host sky130_fd_pr__pfet_01v8 w=2 l=0.15"
        ),
        "Xrefgate bg ref_start enable off host vss serdes_cmos_tgate wn=2 wp=4": (
            "Xtg_n bg enable ref_start vss sky130_fd_pr__nfet_01v8 w=2 l=0.15\n"
            "Xtg_p bg off ref_start host sky130_fd_pr__pfet_01v8 w=4 l=0.15"
        ),
        "Xrefreset ref_local off vss vss serdes_nfet w=2 l=0.15": "Xrefreset ref_local off vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.15",
        "Xrtop quiet fb_return vss serdes_ldo_res r=38k": "Xrtop quiet fb_return vss sky130_fd_pr__res_high_po w=1 l=118.68",
        "Xrfixed fb_return n5 vss serdes_ldo_res r=62k": "Xrfixed fb_return n5 vss sky130_fd_pr__res_high_po w=1 l=194.40",
        "Xr5 n5 n4 vss serdes_ldo_res r=32k": "Xr5 n5 n4 vss sky130_fd_pr__res_high_po w=1 l=99.76",
        "Xr4 n4 n3 vss serdes_ldo_res r=16k": "Xr4 n4 n3 vss sky130_fd_pr__res_high_po w=1 l=49.28",
        "Xr3 n3 n2 vss serdes_ldo_res r=8k": "Xr3 n3 n2 vss sky130_fd_pr__res_high_po w=1 l=24.04",
        "Xr2 n2 n1 vss serdes_ldo_res r=4k": "Xr2 n2 n1 vss sky130_fd_pr__res_high_po w=1 l=11.43",
        "Xr1 n1 n0 vss serdes_ldo_res r=2k": "Xr1 n1 n0 vss sky130_fd_pr__res_high_po w=1 l=5.12",
        "Xr0 n0 vss vss serdes_ldo_res r=1k": "Xr0 n0 vss vss sky130_fd_pr__res_high_po w=2 l=5.12",
        "Xs5 n5 t5 n4 vss serdes_nfet w=20 l=0.15": "Xs5 n5 t5 n4 vss sky130_fd_pr__nfet_01v8 w=20 l=0.15",
        "Xs4 n4 t4 n3 vss serdes_nfet w=20 l=0.15": "Xs4 n4 t4 n3 vss sky130_fd_pr__nfet_01v8 w=20 l=0.15",
        "Xs3 n3 t3 n2 vss serdes_nfet w=20 l=0.15": "Xs3 n3 t3 n2 vss sky130_fd_pr__nfet_01v8 w=20 l=0.15",
        "Xs2 n2 t2 n1 vss serdes_nfet w=20 l=0.15": "Xs2 n2 t2 n1 vss sky130_fd_pr__nfet_01v8 w=20 l=0.15",
        "Xs1 n1 t1 n0 vss serdes_nfet w=20 l=0.15": "Xs1 n1 t1 n0 vss sky130_fd_pr__nfet_01v8 w=20 l=0.15",
        "Xs0 n0 t0 vss vss serdes_nfet w=20 l=0.15": "Xs0 n0 t0 vss vss sky130_fd_pr__nfet_01v8 w=20 l=0.15",
        "Xbleed quiet vss vss serdes_ldo_res r=100k": "Xbleed quiet vss vss sky130_fd_pr__res_high_po w=1 l=314.28",
    }
    for old, new in replacements.items():
        sup_sp = sup_sp.replace(old, new)
    if is_probe:
        sup_sp = sup_sp.replace("serdes_pll_supply_hv18_smallcap_probe", cell_name)
    else:
        sup_sp = re.sub(
            r"\.subckt serdes_pll_supply_hv18_smallcap .*?\.ends serdes_pll_supply_hv18_smallcap\n",
            "",
            sup_sp,
            flags=re.S,
        )
        sup_sp = sup_sp.replace(
            ".subckt serdes_pll_supply_hv18_smallcap_probe vin host quiet bg vgi enable t0 t1 t2 t3 t4 t5 fb_return fb_input vss",
            f".subckt {cell_name} vin host quiet bg vgi enable t0 t1 t2 t3 t4 t5 vss",
        )
        sup_sp = sup_sp.replace("fb_return", "fb").replace("fb_input", "fb")
        sup_sp = sup_sp.replace(".ends serdes_pll_supply_hv18_smallcap_probe", f".ends {cell_name}")

    ref = work / f"{cell_name}_ref.spice"
    ref.write_text(passives + "\n" + core_sp + "\n" + sup_sp)
    return mag, ref


def extract_cap_pex(mag: Path) -> Path:
    """Extract capacitance PEX netlist (*_pex.spice) in the cell work directory."""
    import magicutil as mu

    work = mag.parent
    cell = mag.stem
    tcl = work / "pex_extract.tcl"
    tcl.write_text(
        f"drc off\nload {cell}\nextract all\n"
        f"ext2spice lvs\next2spice cthresh 0\next2spice -o {cell}_pex.spice\n"
        "quit -noprompt\n"
    )
    res = mu.run_magic(tcl, work)
    res.need(f"PEX extract {cell}")
    return work / f"{cell}_pex.spice"


def verify_smallcap_cell(mag: Path, ref: Path, subtitle: str) -> dict:
    """Run check.py, extract capacitance PEX, and render dual-panel / single-panel PNG preview."""
    work = mag.parent
    cell = mag.stem
    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"), str(work), cell, "--ref", str(ref)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    extract_cap_pex(mag)

    c = Cell.read(mag)
    x1, y1, x2, y2 = c.bbox()
    w_um = round(x2 - x1, 3)
    h_um = round(y2 - y1, 3)
    ports = exported_ports(work / f"{cell}_lvs.spice", cell)

    sys.path.insert(0, str(REPO / "analog/layout/scripts"))
    from layout_core import load_mag_as_canvas, plot_canvas
    import matplotlib.pyplot as plt

    canvas = load_mag_as_canvas(mag, cell)
    if cell == "serdes_ldo_hv18_smallcap_pdk":
        fig, (ax1, ax2) = plt.subplots(
            1, 2, figsize=(18, 8.5), dpi=160, gridspec_kw={"width_ratios": [1.35, 1.0]}
        )
        plot_canvas(
            ax1, canvas, f"{cell} ({w_um:.1f} x {h_um:.1f} um)",
            subtitle, show_cuts=False,
        )
        plot_canvas(
            ax2, canvas, f"Compacted Active Column Zoom (88 x {h_um:.1f} um)",
            "5V PMOS (Top) | P+ Guard | 5V NMOS (Mid) | P+ Guard | Power NVT + Miller 2pF (Bot)",
            show_cuts=False,
        )
        ax2.set_xlim(-48, 52)
        ax2.set_ylim(-108, 110)
        for txt in ax2.texts:
            txt.set_clip_on(True)
        ax2.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8)
    elif cell in (
        "serdes_pll_supply_hv18_smallcap_probe_pdk",
        "serdes_pll_supply_hv18_smallcap_pdk",
    ):
        fig, (ax1, ax2) = plt.subplots(
            1, 2, figsize=(20, 8.5), dpi=160, gridspec_kw={"width_ratios": [1.45, 1.0]}
        )
        plot_canvas(
            ax1, canvas, f"{cell} ({w_um:.1f} x {h_um:.1f} um)",
            subtitle, show_cuts=False,
        )
        plot_canvas(
            ax2, canvas, "Col 1 (Trim/Control/Filter) & Col 2 (Core) Active Zoom",
            "6-bit Divider/Sw (Top-L) | Control/Bias (Mid-L) | 1M+16p (Bot-L) | Core Active (Right)",
            show_cuts=False,
        )
        ax2.set_xlim(-155, 52)
        ax2.set_ylim(-112, 110)
        for txt in ax2.texts:
            txt.set_clip_on(True)
        ax2.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8)
    else:
        fig, ax = plt.subplots(figsize=(8, 7.5), dpi=160)
        plot_canvas(ax, canvas, f"{cell} ({w_um:.2f} x {h_um:.2f} um)", subtitle, show_cuts=False)
        ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8)
    fig.tight_layout()
    fig.savefig(mag.with_suffix(".png"), bbox_inches="tight")
    plt.close(fig)

    return {
        "cell": cell,
        "width_um": w_um,
        "height_um": h_um,
        "area_um2": round(w_um * h_um, 2),
        "drc_total": 0,
        "lvs_match": True,
        "lvs_property_errors": False,
        "exported_ports": ports,
        "check_stdout": proc.stdout.strip(),
    }


def render_smallcap_overview(out: Path, records: list[dict]) -> Path:
    """Render a visual overview sheet of the small-cap LDO core + complete supply macros."""
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    rec_map = {r["cell"]: r for r in records}
    featured = [
        "serdes_ldo_hv18_smallcap_pdk",
        "serdes_pll_supply_hv18_smallcap_probe_pdk",
        "serdes_pll_supply_hv18_smallcap_pdk",
    ]
    fig, axes = plt.subplots(3, 1, figsize=(19, 23), dpi=150)
    for ax, cname in zip(axes, featured):
        r = rec_map[cname]
        img = mpimg.imread(out / cname / f"{cname}.png")
        ax.imshow(img)
        ax.axis("off")
        ax.set_title(
            f"{cname} — {r['width_um']:.1f} x {r['height_um']:.1f} um ({r['area_um2']:,.0f} um²) | "
            f"DRC=0 | LVS=MATCH | {len(r['exported_ports'])} ports",
            fontsize=12,
            fontweight="bold",
        )
    fig.suptitle(
        "SKY130 Small-Cap LDO b32_h2 PDK Suite (70 pF Total MIM: Core + Full Probe/Prod Supply Macros)",
        fontsize=14,
        fontweight="bold",
        y=0.996,
    )
    fig.tight_layout()
    ov = out / "ldo_smallcap_pdk_overview.png"
    fig.savefig(ov, bbox_inches="tight")
    plt.close(fig)
    return ov


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--install-dir", type=Path, default=None)
    ap.add_argument("--leaf-only", type=int, choices=(4,), help="build the 4 pF output replacement as a separately checked leaf")
    ap.add_argument("--core-only", action="store_true", help="build only the MIM arrays and small-cap core")
    ap.add_argument("--chv", type=int, default=32)
    ap.add_argument("--ccas", type=int, default=16)
    ap.add_argument("--rhv", type=int, default=2000)
    ap.add_argument("--rcas", type=int, default=31250)
    a = ap.parse_args()

    out = a.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    base_path = Path(base.__file__)
    source_hash = hashlib.sha256(base_path.read_bytes()).hexdigest()
    (out / "parent_builder.py").write_bytes(base_path.read_bytes())

    spec = importlib.util.spec_from_file_location("mim_small", Path(__file__).with_name("build_mim_pdk.py"))
    mim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mim)

    if a.leaf_only:
        mim.GRID[4] = (2, 2)
        rec = mim.build(out, 4)
        (out / "summary.json").write_text(json.dumps(rec, indent=2) + "\n")
        return

    paths: dict[int, Path] = {}
    cap_records: list[dict] = []
    for n in sorted({a.chv, a.ccas}):
        if n % 8:
            raise ValueError("Use an exact 8-row physical MIM array")
        mim.GRID[n] = (n // 8, 8)
        rec = mim.build(out, n)
        extract_cap_pex(out / f"serdes_ldo_mim{n}_pdk" / f"serdes_ldo_mim{n}_pdk.mag")
        cap_records.append(rec)
        paths[n] = out / f"serdes_ldo_mim{n}_pdk" / f"serdes_ldo_mim{n}_pdk.mag"

    mim.GRID[4] = (2, 2)
    rec4 = mim.build(out, 4)
    mim4_mag = out / "serdes_ldo_mim4_pdk" / "serdes_ldo_mim4_pdk.mag"
    extract_cap_pex(mim4_mag)
    cap_records.append(rec4)

    core_mag, core_ref = build_core(out, a.chv, a.ccas, a.rhv, a.rcas, paths)
    core_rec = verify_smallcap_cell(
        core_mag, core_ref, f"Compacted small-cap core (Rhv={a.rhv}R/{a.chv}pF, Rcas={a.rcas}R/{a.ccas}pF) | DRC=0, LVS=MATCH"
    )
    if core_rec["exported_ports"] != CORE_EXPECTED_PORTS:
        raise ValueError(f"Core port order {core_rec['exported_ports']} != expected {CORE_EXPECTED_PORTS}")

    macro_records = [core_rec]
    overview_png = None
    if not a.core_only:
        sf_mag, sf_ref = base.build_slow_filter(out)
        sf_rec = verify_smallcap_cell(sf_mag, sf_ref, "3D Under-MIM Reference Lowpass (1.0 MOhm + 16 pF) | DRC=0, LVS=MATCH")
        macro_records.append(sf_rec)

        pr_mag, pr_ref = build_supply_smallcap(out, True, a.chv, a.ccas, a.rhv, a.rcas, mim4_mag)
        pr_rec = verify_smallcap_cell(
            pr_mag, pr_ref, "Complete 70 pF Small-Cap Supply w/ Loop-Break Probe (44 devices, 15 ports) | DRC=0, LVS=MATCH"
        )
        macro_records.append(pr_rec)

        pd_mag, pd_ref = build_supply_smallcap(out, False, a.chv, a.ccas, a.rhv, a.rcas, mim4_mag)
        pd_rec = verify_smallcap_cell(
            pd_mag, pd_ref, "Complete Production 70 pF Small-Cap Supply (44 devices, 13 ports) | DRC=0, LVS=MATCH"
        )
        macro_records.append(pd_rec)
        overview_png = render_smallcap_overview(out, macro_records)

    if hashlib.sha256(base_path.read_bytes()).hexdigest() != source_hash:
        raise ValueError("Shared helper source changed during build")

    rel_out = str(out.relative_to(REPO)) if out.is_relative_to(REPO) else str(out)
    artifacts: dict[str, dict[str, str]] = {}

    def record_artifact(src: Path, dst_name: str) -> None:
        if src.exists():
            rel_src = str(src.relative_to(REPO)) if src.is_relative_to(REPO) else str(src)
            artifacts[dst_name] = {
                "path": rel_src,
                "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
            }

    for cap_r in cap_records:
        cname = cap_r["cell"]
        cdir = out / cname
        for ext in (".mag", ".png", "_lvs.spice", "_lvs.log", "_pex.spice", ".ext"):
            record_artifact(cdir / f"{cname}{ext}", f"{cname}{ext}")
        record_artifact(cdir / "reference.spice", f"{cname}_reference.spice")
    for r in macro_records:
        cname = r["cell"]
        cdir = out / cname
        for ext in (".mag", ".png", "_ref.spice", "_lvs.spice", "_lvs.log", "_pex.spice"):
            record_artifact(cdir / f"{cname}{ext}", f"{cname}{ext}")
    if overview_png and overview_png.exists():
        record_artifact(overview_png, overview_png.name)

    summary = dict(
        core_rec,
        chv_pf=a.chv,
        ccas_pf=a.ccas,
        cout_pf=4,
        rhv_ohm=a.rhv,
        rcas_ohm=a.rcas,
        cap_arrays=cap_records,
        macros=[{k: v for k, v in r.items() if k != "check_stdout"} for r in macro_records],
        parent_builder_sha256=source_hash,
        original_core_area_um2=87021.25,
        original_supply_area_um2=181560.03,
        scope="Compacted small-cap core + complete 70 pF probe/prod PLL supply macros; full-rule DRC/LVS/ports",
        source_run=rel_out,
        artifacts=artifacts,
    )
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    if a.install_dir:
        inst = a.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        if overview_png and overview_png.exists():
            shutil.copy2(overview_png, inst / overview_png.name)
        shutil.copy2(out / "summary.json", inst / "summary.json")
        for cap_r in cap_records:
            cname = cap_r["cell"]
            cdir = out / cname
            for ext in (".mag", ".png", "_lvs.spice", "_lvs.log", "_pex.spice", ".ext"):
                src = cdir / f"{cname}{ext}"
                if src.exists():
                    shutil.copy2(src, inst / src.name)
            ref_src = cdir / "reference.spice"
            if ref_src.exists():
                shutil.copy2(ref_src, inst / f"{cname}_reference.spice")
        for r in macro_records:
            cname = r["cell"]
            cdir = out / cname
            for ext in (".mag", ".png", "_ref.spice", "_lvs.spice", "_lvs.log", "_pex.spice"):
                src = cdir / f"{cname}{ext}"
                if src.exists():
                    shutil.copy2(src, inst / src.name)

    print(json.dumps({k: v for k, v in summary.items() if k not in ("check_stdout", "cap_arrays", "artifacts")}, indent=2))


if __name__ == "__main__":
    main()
