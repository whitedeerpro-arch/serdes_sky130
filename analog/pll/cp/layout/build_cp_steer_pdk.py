#!/usr/bin/env python3
"""Build SKY130 PDK Current-Steering Charge Pump Layout (pll_cp_steer_pdk).

Implements ``pll_cp_steer`` from ``analog/pll/cp/spice/charge_pump_steer.spice``
with the ``pll_core_r6k4q.spice`` k=4 (Icp = 200 uA) parameters:
  wn=20, wp=80, lmirror=1, wsn=8, wsp=16, up_wn=2, up_ln=0.88, up_wp=8,
  dn_wn=4, dn_wp=8, pnf=16, nnf=4, win=24, lin=1, wl=96, ll=1, ntail=2, cdum=0.3p.

Architecture:
- Left-to-right signal flow: PFD inputs (up, dn) and biases (vbn, vbp, ibias)
  enter on the left; steered current output ``out`` exits on the right toward
  ``pll_loop_filter_k4`` and VCO ``vctrl``.
- Common-centroid [Xa0, Xb0, Xb1, Xa1] LVT NMOS input quad and vertically aligned
  [Xla0, Xlb0, Xlb1, Xla1] LVT PMOS mirror load quad for the dummy-node unity-gain
  follower OTA.
- 3D-stacked ``Cdum = 0.3 pF`` (cap_mim_m3_1 w=12.08, l=12.08 -> 299.81 fF) directly
  above the follower OTA on M3/M4 with zero silicon area overhead.
- Strict HV routing (M1 horizontal tracks in central channel, M2 vertical risers).
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell, pdk_device  # noqa: E402
import magicutil as mu  # noqa: E402

MIM_MODEL = "sky130_fd_pr__cap_mim_m3_1"


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def via3(c: Cell, x: float, y: float) -> None:
    c.pad("metal3", x, y, 0.52)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.52)


def clean_prim(work: Path, name: str, model: str, params: dict) -> Cell:
    p = pdk_device(work, name, model, params)
    p.rects.pop("checkpaint", None)
    return p


def draw_cdum_mim(work: Path) -> Cell:
    name = "cdum_mim_raw"
    mag = work / f"{name}.mag"
    mu.new_cell(mag)
    tcl = work / f"{name}.tcl"
    tcl.write_text(
        f"drc off\nload {name}\nbox values 0 0 0 0\n"
        f"set p [dict merge [sky130::{MIM_MODEL}_defaults] "
        f"[dict create w 12.08 l 12.08 nx 1 ny 1 stack 0]]\n"
        f"sky130::{MIM_MODEL}_draw $p\nsave {name}\nquit -noprompt\n"
    )
    res = mu.run_magic(tcl, work)
    (work / f"{name}.log").write_text(res.log)
    res.need(name)
    mc = Cell.read(mag)
    mc.rects.pop("checkpaint", None)
    mc.labels.clear()
    return mc


def place_mos(
    c: Cell,
    prim: Cell,
    cut_layer: str,
    dx: float,
    dy: float,
    finger_w: float,
    is_pmos: bool,
    body_rail_y: float,
) -> dict:
    """Place MOSFET, strap S/D onto local M2 combs, escape G left on M1, tie B on M1."""
    c.include(prim, dx=dx, dy=dy)
    sds = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects[cut_layer]})
    s_xs = sds[::2]
    d_xs = sds[1::2]
    pin_off = min(0.46, grid(finger_w / 2.0 - 0.24)) if finger_w <= 2.0 else grid(finger_w / 2.0 - 0.60)
    bus_off = grid(finger_w / 2.0 + 1.45)

    if is_pmos:
        # Source comb ABOVE (toward VDD rail), drain comb BELOW (toward channel)
        s_y_pin, d_y_pin = grid(dy + pin_off), grid(dy - pin_off)
        s_bus_y, d_bus_y = grid(dy + bus_off), grid(dy - bus_off)
        by = grid(dy + abs(prim.pins("B")[0][1]))
    else:
        # Source comb BELOW (toward VSS rail), drain comb ABOVE (toward channel)
        s_y_pin, d_y_pin = grid(dy - pin_off), grid(dy + pin_off)
        s_bus_y, d_bus_y = grid(dy - bus_off), grid(dy + bus_off)
        by = grid(dy - abs(prim.pins("B")[0][1]))

    for sx in s_xs:
        c.via1(sx, s_y_pin)
        c.wire("metal2", [(sx, s_y_pin), (sx, s_bus_y)], 0.26)
    for sx in d_xs:
        c.via1(sx, d_y_pin)
        c.wire("metal2", [(sx, d_y_pin), (sx, d_bus_y)], 0.26)
    if len(s_xs) > 1:
        c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[-1], s_bus_y)], 0.34)
    if len(d_xs) > 1:
        c.wire("metal2", [(d_xs[0], d_bus_y), (d_xs[-1], d_bus_y)], 0.34)

    gy = grid(dy + prim.pins("G")[0][1])
    gx0 = grid(dx + min(p[0] for p in prim.pins("G")))
    gx_esc = grid(sds[0] - 0.90)
    c.wire("metal1", [(gx_esc, gy), (gx0, gy)], 0.20)
    c.via1(gx_esc, gy)

    c.pad("viali", dx, by, 0.17)
    c.pad("metal1", dx, by, 0.32)
    c.wire("metal1", [(dx, by), (dx, body_rail_y)], 0.30)

    return {
        "dx": dx,
        "s_xs": s_xs,
        "d_xs": d_xs,
        "s_bus_y": s_bus_y,
        "d_bus_y": d_bus_y,
        "g_pt": (gx_esc, gy),
    }


def m2_to_m1(c: Cell, x: float, y_from: float, y_m1: float, w: float = 0.28) -> None:
    c.wire("metal2", [(x, y_from), (x, y_m1)], w)
    c.via1(x, y_m1)


def build_cp_steer(out: Path) -> dict:
    cell = "pll_cp_steer_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    # PDK primitives matching charge_pump_steer.spice @ pll_core_r6k4q.spice sizing
    upn_p = clean_prim(w, "upn_pdk", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.88, nf=1, conn_gates=1))
    n2_p = clean_prim(w, "n2_pdk", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=2, conn_gates=1))
    n4_p = clean_prim(w, "n4_pdk", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=4, conn_gates=1))
    p4_p = clean_prim(w, "p4_pdk", "sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.15, nf=4, conn_gates=1))
    p8_p = clean_prim(w, "p8_pdk", "sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.15, nf=8, conn_gates=1))
    nmir_p = clean_prim(w, "nmir_pdk", "sky130_fd_pr__nfet_01v8", dict(w=5.0, l=1.0, nf=4, conn_gates=1))
    pmir8_p = clean_prim(w, "pmir8_pdk", "sky130_fd_pr__pfet_01v8", dict(w=5.0, l=1.0, nf=8, conn_gates=1))
    bd_p = clean_prim(w, "bd_pdk", "sky130_fd_pr__nfet_01v8", dict(w=1.0, l=1.0, nf=1, conn_gates=1))
    tail_p = clean_prim(w, "tail_pdk", "sky130_fd_pr__nfet_01v8", dict(w=5.0, l=1.0, nf=2, conn_gates=1))
    inlvt_p = clean_prim(w, "inlvt_pdk", "sky130_fd_pr__nfet_01v8_lvt", dict(w=6.0, l=1.0, nf=2, conn_gates=1))
    ldlvt_p = clean_prim(w, "ldlvt_pdk", "sky130_fd_pr__pfet_01v8_lvt", dict(w=6.0, l=1.0, nf=8, conn_gates=1))
    cdum_c = draw_cdum_mim(w)

    c = Cell()

    dy_n, dy_p = 0.00, 27.00
    y_vss_m1 = -6.20
    y_vdd_m1 = 33.80

    # Dedicated horizontal M1 channel tracks (1.05 um pitch, zero crossings)
    T = {
        "up": 6.20,
        "up_b": 7.25,
        "dn": 8.30,
        "dn_b": 9.35,
        "dn_on": 10.40,
        "vbn": 11.45,
        "ns": 12.50,
        "vbp": 13.55,
        "ps": 14.60,
        "ibias": 15.65,
        "tail": 16.70,
        "da": 17.75,
        "dum": 18.80,
        "out": 19.85,
    }

    # 1. Place NMOS row (bottom, dy = 0.00)
    m_upn = place_mos(c, upn_p, "ndiffc", 4.00, dy_n, 2.0, False, y_vss_m1)
    m_dn1n = place_mos(c, n2_p, "ndiffc", 10.50, dy_n, 2.0, False, y_vss_m1)
    m_dn2n = place_mos(c, n2_p, "ndiffc", 17.00, dy_n, 2.0, False, y_vss_m1)
    m_nmir = place_mos(c, nmir_p, "ndiffc", 25.00, dy_n, 5.0, False, y_vss_m1)
    m_ns = place_mos(c, n4_p, "ndiffc", 32.20, dy_n, 2.0, False, y_vss_m1)
    m_nd = place_mos(c, n4_p, "ndiffc", 39.20, dy_n, 2.0, False, y_vss_m1)
    m_bd = place_mos(c, bd_p, "ndiffc", 47.00, dy_n, 1.0, False, y_vss_m1)
    m_tail = place_mos(c, tail_p, "ndiffc", 66.80, dy_n, 5.0, False, y_vss_m1)

    cc_xs = [75.00, 89.00, 103.00, 117.00]  # [A, B, B, A]
    m_in = [place_mos(c, inlvt_p, "ndiffc", x, dy_n, 6.0, False, y_vss_m1) for x in cc_xs]

    # 2. Place PMOS row (top, dy = 27.00)
    m_upp = place_mos(c, p4_p, "pdiffc", 4.00, dy_p, 2.0, True, y_vdd_m1)
    m_dn1p = place_mos(c, p4_p, "pdiffc", 10.50, dy_p, 2.0, True, y_vdd_m1)
    m_dn2p = place_mos(c, p4_p, "pdiffc", 17.00, dy_p, 2.0, True, y_vdd_m1)
    m_pmir0 = place_mos(c, pmir8_p, "pdiffc", 26.50, dy_p, 5.0, True, y_vdd_m1)
    m_pmir1 = place_mos(c, pmir8_p, "pdiffc", 40.50, dy_p, 5.0, True, y_vdd_m1)
    m_ps = place_mos(c, p8_p, "pdiffc", 51.50, dy_p, 2.0, True, y_vdd_m1)
    m_pd = place_mos(c, p8_p, "pdiffc", 60.00, dy_p, 2.0, True, y_vdd_m1)
    m_ld = [place_mos(c, ldlvt_p, "pdiffc", x, dy_p, 6.0, True, y_vdd_m1) for x in cc_xs]

    # 3. Power rails (VSS bottom M1 + M3 port, VDD top M1 + M3 port)
    x_pwr_port = -2.50
    c.wire("metal1", [(x_pwr_port, y_vss_m1), (cc_xs[-1], y_vss_m1)], 0.60)
    c.via1(x_pwr_port, y_vss_m1)
    c.via2(x_pwr_port, y_vss_m1)
    c.pad("metal3", x_pwr_port, y_vss_m1, 0.60)

    c.wire("metal1", [(x_pwr_port, y_vdd_m1), (cc_xs[-1], y_vdd_m1)], 0.60)
    c.via1(x_pwr_port, y_vdd_m1)
    c.via2(x_pwr_port, y_vdd_m1)
    c.pad("metal3", x_pwr_port, y_vdd_m1, 0.60)

    # Tie NMOS VSS sources
    for m in (m_upn, m_dn1n, m_dn2n, m_nmir, m_bd, m_tail):
        m2_to_m1(c, m["s_xs"][0], m["s_bus_y"], y_vss_m1, 0.30)
    # Tie PMOS VDD sources
    for m in (m_upp, m_dn1p, m_dn2p, m_pmir0, m_pmir1, *m_ld):
        m2_to_m1(c, m["s_xs"][0], m["s_bus_y"], y_vdd_m1, 0.30)

    # 4. Pulse drivers (up -> up_b, dn -> dn_b -> dn_on)
    x_in_port = -1.00
    # up (bridge m_upp.G=2.14 and m_upn.G=2.515 on M2 at T["up"] with w=0.32 matching via1)
    c.wire("metal2", [m_upn["g_pt"], (m_upn["g_pt"][0], T["up"]), (m_upp["g_pt"][0], T["up"]), m_upp["g_pt"]], 0.32)
    c.via1(m_upp["g_pt"][0], T["up"])
    m2_to_m1(c, m_pd["g_pt"][0], m_pd["g_pt"][1], T["up"])
    c.wire("metal1", [(x_in_port, T["up"]), (m_pd["g_pt"][0], T["up"])], 0.34)

    # up_b
    m2_to_m1(c, m_upn["d_xs"][0], m_upn["d_bus_y"], T["up_b"])
    m2_to_m1(c, m_upp["dx"], m_upp["d_bus_y"], T["up_b"])
    m2_to_m1(c, m_ps["g_pt"][0], m_ps["g_pt"][1], T["up_b"])
    c.wire("metal1", [(m_upp["dx"], T["up_b"]), (m_ps["g_pt"][0], T["up_b"])], 0.34)

    # dn
    m2_to_m1(c, m_dn1n["g_pt"][0], m_dn1n["g_pt"][1], T["dn"])
    m2_to_m1(c, m_dn1p["g_pt"][0], m_dn1p["g_pt"][1], T["dn"])
    c.wire("metal1", [(x_in_port, T["dn"]), (m_dn1n["g_pt"][0], T["dn"])], 0.34)

    # dn_b
    c.wire("metal2", [(m_dn1n["dx"], m_dn1n["d_bus_y"]), (m_dn1p["dx"], m_dn1p["d_bus_y"])], 0.32)
    c.via1(m_dn1n["dx"], T["dn_b"])
    m2_to_m1(c, m_dn2n["g_pt"][0], m_dn2n["g_pt"][1], T["dn_b"])
    m2_to_m1(c, m_dn2p["g_pt"][0], m_dn2p["g_pt"][1], T["dn_b"])
    m2_to_m1(c, m_nd["g_pt"][0], m_nd["g_pt"][1], T["dn_b"])
    c.wire("metal1", [(m_dn1n["dx"], T["dn_b"]), (m_nd["g_pt"][0], T["dn_b"])], 0.34)

    # dn_on
    c.wire("metal2", [(m_dn2n["dx"], m_dn2n["d_bus_y"]), (m_dn2p["dx"], m_dn2p["d_bus_y"])], 0.32)
    c.via1(m_dn2n["dx"], T["dn_on"])
    m2_to_m1(c, m_ns["g_pt"][0], m_ns["g_pt"][1], T["dn_on"])
    c.wire("metal1", [(m_dn2n["dx"], T["dn_on"]), (m_ns["g_pt"][0], T["dn_on"])], 0.34)

    # 5. Mirror sources & steering switches (vbn, ns, vbp, ps)
    # vbn
    m2_to_m1(c, m_nmir["g_pt"][0], m_nmir["g_pt"][1], T["vbn"])
    c.wire("metal1", [(x_in_port, T["vbn"]), (m_nmir["g_pt"][0], T["vbn"])], 0.34)

    # ns: Xn.D (25.00), Xns.S (step right to 35.40), Xnd.S (step right to 42.20)
    m2_to_m1(c, m_nmir["dx"], m_nmir["d_bus_y"], T["ns"], 0.36)
    for m_sw, x_riser in ((m_ns, 35.40), (m_nd, 42.20)):
        c.wire("metal2", [(m_sw["s_xs"][-1], m_sw["s_bus_y"]), (x_riser, m_sw["s_bus_y"]), (x_riser, T["ns"])], 0.32)
        c.via1(x_riser, T["ns"])
    c.wire("metal1", [(m_nmir["dx"], T["ns"]), (42.20, T["ns"])], 0.42)

    # vbp
    m2_to_m1(c, m_pmir0["g_pt"][0], m_pmir0["g_pt"][1], T["vbp"])
    m2_to_m1(c, m_pmir1["g_pt"][0], m_pmir1["g_pt"][1], T["vbp"])
    c.wire("metal1", [(x_in_port, T["vbp"]), (m_pmir1["g_pt"][0], T["vbp"])], 0.34)

    # ps: Xp0.D (26.50), Xp1.D (40.50), Xps.S (step right to 55.00), Xpd.S (step right to 63.50)
    m2_to_m1(c, m_pmir0["dx"], m_pmir0["d_bus_y"], T["ps"], 0.36)
    m2_to_m1(c, m_pmir1["dx"], m_pmir1["d_bus_y"], T["ps"], 0.36)
    for m_sw, x_riser in ((m_ps, 55.00), (m_pd, 63.50)):
        c.wire("metal2", [(m_sw["s_xs"][-1], m_sw["s_bus_y"]), (x_riser, m_sw["s_bus_y"]), (x_riser, T["ps"])], 0.32)
        c.via1(x_riser, T["ps"])
    c.wire("metal1", [(m_pmir0["dx"], T["ps"]), (63.50, T["ps"])], 0.42)

    # 6. Follower OTA (ibias, tail, da, dum, out)
    # ibias
    m2_to_m1(c, m_bd["g_pt"][0], m_bd["g_pt"][1], T["ibias"])
    m2_to_m1(c, m_bd["d_xs"][0], m_bd["d_bus_y"], T["ibias"])
    m2_to_m1(c, m_tail["g_pt"][0], m_tail["g_pt"][1], T["ibias"])
    c.wire("metal1", [(x_in_port, T["ibias"]), (m_tail["g_pt"][0], T["ibias"])], 0.34)

    # tail: Xt.D (66.80) -> m_in[0..3].S (step right to dx + 2.80)
    m2_to_m1(c, m_tail["dx"], m_tail["d_bus_y"], T["tail"], 0.34)
    tail_risers = []
    for mi in m_in:
        xr = grid(mi["dx"] + 2.80)
        tail_risers.append(xr)
        c.wire("metal2", [(mi["s_xs"][-1], mi["s_bus_y"]), (xr, mi["s_bus_y"]), (xr, T["tail"])], 0.32)
        c.via1(xr, T["tail"])
    c.wire("metal1", [(m_tail["dx"], T["tail"]), (tail_risers[-1], T["tail"])], 0.40)

    # Common-centroid [A, B, B, A] vertical drain links (Xa/Xla -> da; Xb/Xlb -> dum)
    for idx, mi, ml in zip(range(4), m_in, m_ld):
        c.wire("metal2", [(mi["dx"], mi["d_bus_y"]), (ml["dx"], ml["d_bus_y"])], 0.36)
        net_d = "da" if idx in (0, 3) else "dum"
        c.via1(mi["dx"], T[net_d])
        m2_to_m1(c, ml["g_pt"][0], ml["g_pt"][1], T["da"])
        net_g = "out" if idx in (0, 3) else "dum"
        m2_to_m1(c, mi["g_pt"][0], mi["g_pt"][1], T[net_g])

    c.wire("metal1", [(m_ld[0]["g_pt"][0], T["da"]), (cc_xs[3], T["da"])], 0.36)

    # Steered outputs to out (Xps.D, Xns.D) and dum (Xpd.D, Xnd.D)
    m2_to_m1(c, m_ns["dx"], m_ns["d_bus_y"], T["out"], 0.34)
    m2_to_m1(c, m_ps["dx"], m_ps["d_bus_y"], T["out"], 0.34)
    x_out_port = 124.50
    c.wire("metal1", [(m_ns["dx"], T["out"]), (x_out_port, T["out"])], 0.42)
    c.via1(x_out_port, T["out"])
    c.via2(x_out_port, T["out"])
    c.pad("metal3", x_out_port, T["out"], 0.56)

    m2_to_m1(c, m_nd["dx"], m_nd["d_bus_y"], T["dum"], 0.34)
    m2_to_m1(c, m_pd["dx"], m_pd["d_bus_y"], T["dum"], 0.34)

    # 7. 3D-stacked Cdum = 0.3 pF MIM over follower OTA (dx = 96.00, dy = 13.50)
    dx_cd, dy_cd = 96.00, 13.50
    c.include(cdum_c, dx=dx_cd, dy=dy_cd)
    # Bottom plate C2 (metal3: y = 7.26 .. 19.74) -> VSS via dedicated empty X = 94.00
    x_cd_vss, y_cd_vss_via = 94.00, 5.60
    c.wire("metal2", [(x_cd_vss, y_vss_m1), (x_cd_vss, y_cd_vss_via)], 0.34)
    c.via1(x_cd_vss, y_vss_m1)
    c.via2(x_cd_vss, y_cd_vss_via)
    c.wire("metal3", [(x_cd_vss, y_cd_vss_via), (x_cd_vss, 7.60)], 0.50)
    # Top plate C1 (metal4: x = 89.425..101.115, y = 7.655..19.345) -> dum via empty X = 98.50
    x_cd_dum, y_cd_dum_via = 98.50, 21.60
    c.rect("metal4", grid(x_cd_dum - 0.50), dy_cd, grid(x_cd_dum + 0.50), grid(y_cd_dum_via + 0.30))
    via3(c, x_cd_dum, y_cd_dum_via)
    c.via2(x_cd_dum, y_cd_dum_via)
    m2_to_m1(c, x_cd_dum, y_cd_dum_via, T["dum"], 0.32)

    c.wire("metal1", [(m_nd["dx"], T["dum"]), (cc_xs[2], T["dum"])], 0.42)

    # Left input M3 port pads
    for pname in ("up", "dn", "vbn", "vbp", "ibias"):
        c.via1(x_in_port, T[pname])
        c.via2(x_in_port, T[pname])
        c.pad("metal3", x_in_port, T[pname], 0.54)

    # Export exact port order: up dn out vbn vbp ibias vdd vss
    c.port("up", "metal3", x_in_port, T["up"])
    c.port("dn", "metal3", x_in_port, T["dn"])
    c.port("out", "metal3", x_out_port, T["out"])
    c.port("vbn", "metal3", x_in_port, T["vbn"])
    c.port("vbp", "metal3", x_in_port, T["vbp"])
    c.port("ibias", "metal3", x_in_port, T["ibias"])
    c.port("vdd", "metal3", x_pwr_port, y_vdd_m1)
    c.port("vss", "metal3", x_pwr_port, y_vss_m1)
    c.write(w / f"{cell}.mag")

    # Explicit numeric W/L reference netlist matching pll_core_r6k4q.spice instantiation
    ref_lines = [
        "* Physical LVS reference for pll_cp_steer @ pll_core_r6k4q.spice sizing (k=4, Icp=200 uA)",
        f".subckt {cell} up dn out vbn vbp ibias vdd vss",
        "Xupn up_b up vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.88",
        "Xupp up_b up vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15",
        "Xdn1_n dn_b dn vss vss sky130_fd_pr__nfet_01v8 w=4 l=0.15",
        "Xdn1_p dn_b dn vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15",
        "Xdn2_n dn_on dn_b vss vss sky130_fd_pr__nfet_01v8 w=4 l=0.15",
        "Xdn2_p dn_on dn_b vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15",
        "Xp ps vbp vdd vdd sky130_fd_pr__pfet_01v8 w=80 l=1",
        "Xps out up_b ps vdd sky130_fd_pr__pfet_01v8 w=16 l=0.15",
        "Xpd dum up ps vdd sky130_fd_pr__pfet_01v8 w=16 l=0.15",
        "Xns out dn_on ns vss sky130_fd_pr__nfet_01v8 w=8 l=0.15",
        "Xnd dum dn_b ns vss sky130_fd_pr__nfet_01v8 w=8 l=0.15",
        "Xn ns vbn vss vss sky130_fd_pr__nfet_01v8 w=20 l=1",
        "Xbd ibias ibias vss vss sky130_fd_pr__nfet_01v8 w=1 l=1",
        "Xt tail ibias vss vss sky130_fd_pr__nfet_01v8 w=10 l=1",
        "Xa da out tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=1",
        "Xb dum dum tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=1",
        "Xla da da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=96 l=1",
        "Xlb dum da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=96 l=1",
        f"Xcdum dum vss {MIM_MODEL} w=12.08 l=12.08",
        f".ends {cell}",
        "",
    ]
    ref_path = w / f"{cell}_ref.spice"
    ref_path.write_text("\n".join(ref_lines))

    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"),
         str(w), cell, "--ref", str(ref_path)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    log = proc.stdout + proc.stderr
    (w / "check.log").write_text(log)
    if proc.returncode != 0:
        raise RuntimeError(f"{cell} failed checks:\n{log}")

    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"),
         str(w / f"{cell}.mag"), str(w / f"{cell}.png")],
        cwd=REPO, check=True, capture_output=True,
    )
    drc_m = re.search(r"^DRC_TOTAL (\d+)", log, re.M)
    ports_m = re.search(r"^LVS_EXPORTED_PORTS (.+)$", log, re.M)
    lvs_spice = (w / f"{cell}_lvs.spice").read_text()
    models = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_spice, re.M)))
    bx1, by1, bx2, by2 = Cell.read(w / f"{cell}.mag").bbox()
    return {
        "cell": cell,
        "checker_exit": proc.returncode,
        "drc_boxes": int(drc_m[1]) if drc_m else None,
        "lvs_match": "LVS_MATCH True" in log,
        "lvs_property_errors": "LVS_PROPERTY_ERRORS True" in log,
        "exported_ports": ports_m[1].split() if ports_m else [],
        "bbox_um": [bx1, by1, bx2, by2],
        "size_um": [round(bx2 - bx1, 3), round(by2 - by1, 3)],
        "area_um2": round((bx2 - bx1) * (by2 - by1), 2),
        "extracted_models": models,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--install-dir", type=Path, default=None)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)

    r = build_cp_steer(out)
    print(
        f"{r['cell']:28s} | DRC={r['drc_boxes']} | LVS={r['lvs_match']} | "
        f"PROP_ERR={r['lvs_property_errors']} | ports={len(r['exported_ports'])} | size={r['size_um']} um",
        flush=True,
    )
    (out / "summary.json").write_text(json.dumps([r], indent=2) + "\n")
    if args.install_dir:
        inst = args.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "summary.json", inst / "summary.json")
        cdir = out / r["cell"]
        for ext in (".mag", ".png", "_ref.spice", "_lvs.spice", "_lvs.log", "_pex.spice"):
            src = cdir / f"{r['cell']}{ext}"
            if src.exists():
                shutil.copy2(src, inst / src.name)


if __name__ == "__main__":
    main()
