#!/usr/bin/env python3
"""Build AC-coupled self-biased 2 GHz SKY130 PDK CML-to-CMOS Receiver (serdes_cml_to_cmos_r5_pdk).

Implements `analog/common/cml_to_cmos/spice/cml_to_cmos_r5.spice`:
  - Domain A + B Analog strip identical to verified r4_v4 (Xfp/Xfn=32 LVT, Xip/Xin=16 LVT, Xlp/Xln=32, Xtail=32).
  - AC/Rfb Coupling Bay (between Analog and Digital):
      * XCac_p/n: single-layer MIM cap (sky130_fd_pr__cap_mim_m3_1 w=9.0 l=5.5 -> ~100 fF, stack=0) on M3/M4.
      * XRfb_p/n: compact 3-leg folded poly resistor (sky130_fd_pr__res_high_po_0p35 l=6.0 nx=3 -> ~20 kOhm)
                  underneath XCac in pwell, blocking Diff-to-SE DC offset; mismatch sensitivity remains.
  - Digital Strip (y_vss=0 mirror-symmetric):
      * Xbp/Xbn (6.0/7.2) + weak cross-coupled Xk_bp/Xk_bn (0.6/1.2)
      * Xop/Xon (3.6/6.4) + weak cross-coupled Xk_rp/Xk_rn (0.6/1.2)
      * Skew-locked restorer_r5: dp1..3 (1.2/3.2), set/rst (4.5/4.5), qp/qn (6.0/9.0),
        rp1 (2.4/7.2), rp2 (1.5/4.5), bpr/bnr (2.4/3.6), opr/onr (4.0/8.0).
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

# Reuse verified Analog strip + primitive helpers directly from r4 builder
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_cml_to_cmos_r4_pdk as r4  # noqa: E402

grid = r4.grid
W_M1, W_M2, W_M3 = r4.W_M1, r4.W_M2, r4.W_M3
W_PWR_M1, W_PWR_M2, W_PWR_M3 = r4.W_PWR_M1, r4.W_PWR_M2, r4.W_PWR_M3
Y_ANA_VSS, Y_A_T0, Y_A_T1, Y_A_T2 = r4.Y_ANA_VSS, r4.Y_A_T0, r4.Y_A_T1, r4.Y_A_T2
Y_A_TOP_GR, Y_VDD1, Y_VDD_DIG, Y_A_WELL = r4.Y_A_TOP_GR, r4.Y_VDD1, r4.Y_VDD_DIG, r4.Y_A_WELL
D_N_OFF, D_T0_OFF, D_T1_OFF, D_T2_OFF, D_P_OFF = r4.D_N_OFF, r4.D_T0_OFF, r4.D_T1_OFF, r4.D_T2_OFF, r4.D_P_OFF
D_NPOLY_OFF, D_PPOLY_OFF, D_NDUM_OFF, D_PDUM_OFF = r4.D_NPOLY_OFF, r4.D_PPOLY_OFF, r4.D_NDUM_OFF, r4.D_PDUM_OFF
H_TAP_VSS, H_TAP_VDD, V_TAP_WALL, V_TAP_EDGE = r4.H_TAP_VSS, r4.H_TAP_VDD, r4.V_TAP_WALL, r4.V_TAP_EDGE


def via3_pad_r5(cell: Cell, x: float, y: float) -> None:
    """via3 with SKY130 DRC-clean 0.32 via3 + 0.52 x 0.52 M3/M4 pads (0.2704 >= 0.24 um^2)."""
    cell.pad("via3", x, y, 0.32)
    cell.pad("metal3", x, y, 0.52, 0.52)
    cell.pad("metal4", x, y, 0.52, 0.52)


def build_mim_cell(w: Path, name: str, w_um: float, l_um: float) -> Cell:
    tcl = w / f"{name}.tcl"
    mag = w / f"{name}.mag"
    mu.new_cell(mag)
    tcl.write_text(
        f"drc off\nload {name}\nbox values 0 0 0 0\n"
        f"set p [dict merge [sky130::sky130_fd_pr__cap_mim_m3_1_defaults] "
        f"[dict create w {w_um} l {l_um} nx 1 ny 1 stack 0]]\n"
        f"sky130::sky130_fd_pr__cap_mim_m3_1_draw $p\nsave {name}\nquit -noprompt\n"
    )
    mu.run_magic(tcl, w).need(name)
    mc = Cell.read(mag)
    mc.rects.pop("checkpaint", None)
    mc.labels.clear()
    return mc


def build_rpo_3leg(w: Path, name: str, l_um: float = 6.0) -> tuple[Cell, dict]:
    p = pdk_device(w, name, "sky130_fd_pr__res_high_po_0p35", {"w": 0.35, "l": l_um, "m": 1, "nx": 3, "guard": 0})
    p.rects.pop("checkpaint", None)
    # Extract label coords: R1_0, R2_0, R1_1, R2_1, R1_2, R2_2
    pts = {lbl: (grid(x), grid(y)) for _, x, y, lbl in p.labels}
    p.labels.clear()
    # Wire 3 legs in series inside cell: R1_0 is term A, R2_0->R2_1 bottom bend, R1_1->R1_2 top bend, R2_2 is term B
    p.wire("metal1", [pts["R2_0"], pts["R2_1"]], 0.25)
    p.wire("metal1", [pts["R1_1"], pts["R1_2"]], 0.25)
    return p, {"a": pts["R1_0"], "b": pts["R2_2"]}


def build_digital_half_r5(w: Path, x_dig_l_wall: float) -> tuple[Cell, dict]:
    """Build r5 Digital half-chain in dy > 0 around local y=0 (embedded at y=0 with mirror_y=False/True)."""
    h = Cell()
    y_vss = 0.000
    y_ndiff_top = D_N_OFF
    y_t0, y_t1, y_t2 = D_T0_OFF, D_T1_OFF, D_T2_OFF
    y_pdiff_bot = D_P_OFF
    y_vdd = Y_VDD_DIG

    specs_c1 = [
        ("bp",  2.00, 3, 1.80, 4, 0.800),  # 6.0/7.2 AC-self-biased pre-driver
        ("kbp", 0.60, 1, 1.20, 1, 0.420),  # 0.6/1.2 weak cross-coupled inverter (bn->bp)
        ("op",  1.80, 2, 1.60, 4, 0.420),  # 3.6/6.4
        ("krp", 0.60, 1, 1.20, 1, 0.420),  # 0.6/1.2 weak cross-coupled inverter (rawn->rawp)
        ("dp1", 1.20, 1, 1.60, 2, 0.420),  # 1.2/3.2
        ("dp2", 1.20, 1, 1.60, 2, 0.340),
        ("dp3", 1.20, 1, 1.60, 2, 0.340),
    ]
    specs_c2 = [
        ("setb", 1.50, 3, 1.50, 3, 0.800),  # 4.5/4.5
        ("seta", 1.50, 3, 1.50, 3, 0.340),
        ("qpb",  2.00, 3, 2.25, 4, 0.340),  # 6.0/9.0
        ("qpa",  2.00, 3, 2.25, 4, 0.500),
    ]
    specs_c3 = [
        ("rp1",  1.20, 2, 2.40, 3, 0.800),  # 2.4/7.2
        ("rp2",  1.50, 1, 2.25, 2, 0.340),  # 1.5/4.5
        ("bprb", 1.20, 2, 1.80, 2, 0.340),  # 2.4/3.6
        ("bpra", 1.20, 2, 1.80, 2, 0.340),
        ("opr",  2.00, 2, 2.00, 4, 0.340),  # 4.0/8.0
    ]

    dcols: dict[str, dict] = {}

    def place_group(x_start_wall: float, specs: list[tuple]) -> float:
        x_edge = x_start_wall
        for nm, n_wf, n_nf, p_wf, p_nf, gap_b in specs:
            dy_nc = grid(y_ndiff_top - n_wf / 2.0)
            dy_pc = grid(y_pdiff_bot + p_wf / 2.0)
            cn, inf_n = r4.build_mos(w, f"d5_{nm}_n", "sky130_fd_pr__nfet_01v8", n_wf, 0.15, n_nf, dy_nc, False)
            cp, inf_p = r4.build_mos(w, f"d5_{nm}_p", "sky130_fd_pr__pfet_01v8", p_wf, 0.15, p_nf, dy_pc, True)
            hw_col = max(inf_n["hw_diff"], inf_p["hw_diff"])
            cx = grid(x_edge + gap_b + hw_col)
            h.include(cn, dx=cx)
            h.include(cp, dx=cx)
            dcols[nm] = {"cx": cx, "hw": hw_col, "inf_n": inf_n, "inf_p": inf_p, "n_wf": n_wf, "p_wf": p_wf}
            x_edge = grid(cx + hw_col)
        return x_edge

    x_c1_end = place_group(x_dig_l_wall, specs_c1)
    x_c12_wall = grid(x_c1_end + 0.860)
    x_c2_end = place_group(x_c12_wall, specs_c2)
    x_c2_r_wall = grid(x_c2_end + 0.860)
    x_cr2_n = grid(x_c2_r_wall + V_TAP_WALL + 0.340)
    x_cr2_p = grid(x_cr2_n + 0.740)
    x_c3_l_wall = grid(x_cr2_p + 0.340 + V_TAP_WALL)
    x_c3_end = place_group(x_c3_l_wall, specs_c3)
    x_right_tap = grid(x_c3_end + 0.860)

    def flank(nm: str, side: int, offset: float = 0.220, x_wall: float | None = None) -> None:
        col = dcols[nm]
        x_dn = grid(col["cx"] + side * (col["inf_n"]["hw_diff"] + offset))
        x_dp = grid(col["cx"] + side * (col["inf_p"]["hw_diff"] + offset))
        r4.add_field_poly_dummy(h, x_dn, 0.15, grid(y_ndiff_top - col["n_wf"]), y_ndiff_top, D_NDUM_OFF, False, y_vss, x_wall=x_wall)
        r4.add_field_poly_dummy(h, x_dp, 0.15, y_pdiff_bot, grid(y_pdiff_bot + col["p_wf"]), D_PDUM_OFF, True, y_vdd, x_wall=x_wall)

    flank("bp",   -1, x_wall=x_dig_l_wall)
    flank("dp3",  +1, x_wall=x_c12_wall)
    flank("setb", -1, x_wall=x_c12_wall)
    flank("qpa",  +1, x_wall=x_c2_r_wall)
    flank("rp1",  -1, x_wall=x_c3_l_wall)
    flank("opr",  +1, x_wall=x_right_tap)

    def conn_col(cx: float, inf_n: dict, inf_p: dict, *, n_s: bool = True, p_s: bool = True,
                 n_d: bool = True, p_d: bool = True, d_trunk_dx: float | None = None,
                 xg_dx: float | None = None, g_trk: float = y_t1, skip_ns_m1_ge_d: bool = False) -> dict:
        if n_s:
            for sx in inf_n["s_xs"]:
                xc = grid(cx + sx)
                h.rect("locali", grid(xc - 0.085), y_vss, grid(xc + 0.085), grid(inf_n["c_y1"] + 0.08))
            ns_m1_xs = [sx for sx in inf_n["s_xs"] if not skip_ns_m1_ge_d or sx < min(inf_n["d_xs"])]
            y_ns_hi = grid(min(inf_n["c_y2"], 2.050))
            n_vys = ([grid(inf_n["c_y1"] + 0.140), grid(y_ns_hi - 0.140)]
                     if (y_ns_hi - inf_n["c_y1"]) >= 0.70 else [grid((inf_n["c_y1"] + y_ns_hi) / 2.0)])
            r4.strap_m1_sources(h, cx, ns_m1_xs, y_vss, y_ns_hi, n_vys, width=0.22)
        if p_s:
            for sx in inf_p["s_xs"]:
                xc = grid(cx + sx)
                h.rect("locali", grid(xc - 0.085), grid(inf_p["c_y2"] - 0.08), grid(xc + 0.085), y_vdd)
            y_ps_lo = grid(max(inf_p["c_y1"], 5.100))
            p_vys = ([y_ps_lo + 0.100, grid(inf_p["c_y2"] - 0.100)]
                     if (inf_p["c_y2"] - y_ps_lo) >= 0.70 else [grid((y_ps_lo + inf_p["c_y2"]) / 2.0)])
            r4.strap_m1_sources(h, cx, inf_p["s_xs"], y_ps_lo, y_vdd, p_vys, width=0.22)

        r4.tie_poly_fingers(h, cx, inf_n["g_xs"], inf_n["l_f"], D_NPOLY_OFF, y_ndiff_top)
        r4.tie_poly_fingers(h, cx, inf_p["g_xs"], inf_p["l_f"], D_PPOLY_OFF, y_pdiff_bot)

        xg = grid(cx + (inf_n["g_xs"][0] if xg_dx is None else xg_dx))
        x_sp_lo = max(grid(cx + inf_n["g_xs"][0]), grid(cx + inf_p["g_xs"][0]))
        x_sp_hi = min(grid(cx + inf_n["g_xs"][-1]), grid(cx + inf_p["g_xs"][-1]))
        x_spine = grid(min(max(xg, x_sp_lo), x_sp_hi)) if x_sp_lo <= x_sp_hi else grid(cx)
        if x_sp_lo > x_sp_hi:
            h.rect("poly", grid(min(cx + inf_n["g_xs"][0], cx + inf_p["g_xs"][0]) - 0.075), D_NPOLY_OFF[0],
                   grid(max(cx + inf_n["g_xs"][-1], cx + inf_p["g_xs"][-1]) + 0.075), D_NPOLY_OFF[1])
        h.rect("poly", grid(x_spine - 0.075), D_NPOLY_OFF[0], grid(x_spine + 0.075), D_PPOLY_OFF[1])
        # Tie horizontal poly bar for P too if xg lies outside P finger range
        if xg < grid(cx + inf_p["g_xs"][0]) - 1e-6:
            h.rect("poly", grid(xg - 0.135), D_PPOLY_OFF[0], grid(cx + inf_p["g_xs"][0] + 0.075), D_PPOLY_OFF[1])
        r4.poly_cont_pad(h, xg, g_trk)
        x_al, x_ar = min(grid(xg - 0.135), grid(x_spine - 0.075)), max(grid(xg + 0.135), grid(x_spine + 0.075))
        h.rect("poly", x_al, grid(g_trk - 0.170), x_ar, grid(g_trk + 0.170))

        n_d_abs = [grid(cx + d) for d in inf_n["d_xs"]] if n_d else []
        p_d_abs = [grid(cx + d) for d in inf_p["d_xs"]] if p_d else []
        xd = grid(cx + d_trunk_dx) if d_trunk_dx is not None else (p_d_abs[0] if p_d_abs else n_d_abs[0])
        if n_d_abs:
            for xc in n_d_abs:
                h.rect("locali", grid(xc - 0.085), grid(inf_n["c_y2"] - 0.08), grid(xc + 0.085), grid(y_t0 + 0.085))
            if len(n_d_abs) > 1 or abs(n_d_abs[0] - xd) > 1e-6:
                h.rect("locali", grid(min(min(n_d_abs), xd) - 0.085), grid(y_t0 - 0.085), grid(max(max(n_d_abs), xd) + 0.085), grid(y_t0 + 0.085))
        if p_d_abs:
            for xc in p_d_abs:
                h.rect("locali", grid(xc - 0.085), grid(y_t2 - 0.085), grid(xc + 0.085), grid(inf_p["c_y1"] + 0.08))
            if len(p_d_abs) > 1 or abs(p_d_abs[0] - xd) > 1e-6:
                h.rect("locali", grid(min(min(p_d_abs), xd) - 0.085), grid(y_t2 - 0.085), grid(max(max(p_d_abs), xd) + 0.085), grid(y_t2 + 0.085))
        if n_d_abs and p_d_abs:
            h.rect("locali", grid(xd - 0.085), grid(y_t0 - 0.085), grid(xd + 0.085), grid(y_t2 + 0.085))
        elif p_d_abs:
            h.rect("locali", grid(xd - 0.085), grid(y_t2 - 0.085), grid(xd + 0.085), grid(inf_p["c_y1"] + 0.08))
        return {"cx": cx, "xg": xg, "xd": xd,
                "n_s": [grid(cx + x) for x in inf_n["s_xs"]],
                "p_s": [grid(cx + x) for x in inf_p["s_xs"]],
                "n_d": [grid(cx + x) for x in inf_n["d_xs"]],
                "p_d": [grid(cx + x) for x in inf_p["d_xs"]]}

    def wire_nand2(b_nm: str, a_nm: str, xg_b_dx: float, xg_a_dx: float, d_b_dx: float, d_a_dx: float) -> tuple[dict, dict]:
        cb, ca = dcols[b_nm], dcols[a_nm]
        wb = conn_col(cb["cx"], cb["inf_n"], cb["inf_p"], n_s=True, p_s=True, n_d=False, p_d=True,
                      d_trunk_dx=d_b_dx, xg_dx=xg_b_dx, skip_ns_m1_ge_d=True)
        wa = conn_col(ca["cx"], ca["inf_n"], ca["inf_p"], n_s=False, p_s=True, n_d=True, p_d=True,
                      d_trunk_dx=d_a_dx, xg_dx=xg_a_dx)
        ym_c = grid((max(cb["inf_n"]["c_y1"], ca["inf_n"]["c_y1"]) + min(cb["inf_n"]["c_y2"], ca["inf_n"]["c_y2"])) / 2.0)
        mid_xs = wb["n_d"] + wa["n_s"]
        if len(wb["n_s"]) == 1 and len(wa["n_s"]) == 1:
            h.rect("locali", grid(wb["n_d"][-1] - 0.085), grid(ym_c - 0.12), grid(wa["n_s"][0] + 0.085), grid(ym_c + 0.12))
        else:
            for xc in mid_xs:
                h.pad("viali", xc, ym_c, 0.17)
                h.pad("metal1", xc, ym_c, 0.29)
            h.wire("metal1", [(min(mid_xs), ym_c), (max(mid_xs), ym_c)], W_M1)
        return wb, wa

    dc_wire = {}
    all_n_s: list[float] = []
    all_p_s: list[float] = []

    def track_col(res: dict) -> dict:
        all_n_s.extend(res["n_s"])
        all_p_s.extend(res["p_s"])
        return res

    # C1 columns (kbp/krp gates sit at y_gt_k=2.880: clear of both n_s locali @ 2.45 and M1 y_t1 @ 3.40!)
    y_gt_k = 2.880
    dc_wire["bp"]  = track_col(conn_col(dcols["bp"]["cx"],  dcols["bp"]["inf_n"],  dcols["bp"]["inf_p"],
                                        xg_dx=dcols["bp"]["inf_p"]["g_xs"][0], d_trunk_dx=dcols["bp"]["inf_p"]["d_xs"][-1]))
    dc_wire["kbp"] = track_col(conn_col(dcols["kbp"]["cx"], dcols["kbp"]["inf_n"], dcols["kbp"]["inf_p"],
                                        xg_dx=-0.220, d_trunk_dx=dcols["kbp"]["inf_n"]["d_xs"][0], g_trk=y_gt_k))
    dc_wire["op"]  = track_col(conn_col(dcols["op"]["cx"],  dcols["op"]["inf_n"],  dcols["op"]["inf_p"],
                                        xg_dx=dcols["op"]["inf_p"]["g_xs"][0], d_trunk_dx=dcols["op"]["inf_p"]["d_xs"][-1]))
    dc_wire["krp"] = track_col(conn_col(dcols["krp"]["cx"], dcols["krp"]["inf_n"], dcols["krp"]["inf_p"],
                                        xg_dx=-0.220, d_trunk_dx=dcols["krp"]["inf_n"]["d_xs"][0], g_trk=y_gt_k))
    for dnm in ("dp1", "dp2", "dp3"):
        # nf=1 N, nf=2 P -> gate offset -0.44 clear of P d_xs[0]=0.00 and N d_xs[0]=+0.26; drain trunk = +0.26!
        dc_wire[dnm] = track_col(conn_col(dcols[dnm]["cx"], dcols[dnm]["inf_n"], dcols[dnm]["inf_p"],
                                            xg_dx=-0.440, d_trunk_dx=dcols[dnm]["inf_n"]["d_xs"][0]))

    # C2 NAND2s
    wb_set, wa_set = wire_nand2("setb", "seta", -0.48, -0.48, +0.72, +0.72)
    wb_qp,  wa_qp  = wire_nand2("qpb",  "qpa",  -0.72, -0.72, +0.48, +0.48)
    all_n_s.extend(wb_set["n_s"] + wb_qp["n_s"])
    all_p_s.extend(wb_set["p_s"] + wa_set["p_s"] + wb_qp["p_s"] + wa_qp["p_s"])
    dc_wire["setb"], dc_wire["seta"] = wb_set, wa_set
    dc_wire["qpb"],  dc_wire["qpa"]  = wb_qp,  wa_qp

    # C3 restorer tail (bpr/bnr p_nf=2 -> P drain is at 0.00!)
    dc_wire["rp1"] = track_col(conn_col(dcols["rp1"]["cx"], dcols["rp1"]["inf_n"], dcols["rp1"]["inf_p"],
                                        xg_dx=-0.48, d_trunk_dx=dcols["rp1"]["inf_p"]["d_xs"][-1]))
    dc_wire["rp2"] = track_col(conn_col(dcols["rp2"]["cx"], dcols["rp2"]["inf_n"], dcols["rp2"]["inf_p"],
                                        xg_dx=-0.44, d_trunk_dx=dcols["rp2"]["inf_n"]["d_xs"][0]))
    wb_bpr, wa_bpr = wire_nand2("bprb", "bpra", -0.44, -0.44, 0.00, 0.00)
    all_n_s.extend(wb_bpr["n_s"])
    all_p_s.extend(wb_bpr["p_s"] + wa_bpr["p_s"])
    dc_wire["bprb"], dc_wire["bpra"] = wb_bpr, wa_bpr
    dc_wire["opr"] = track_col(conn_col(dcols["opr"]["cx"], dcols["opr"]["inf_n"], dcols["opr"]["inf_p"],
                                        xg_dx=-0.72, d_trunk_dx=dcols["opr"]["inf_p"]["d_xs"][-1]))

    tapped_pts: set[tuple[float, float]] = set()

    def m1_tap(x: float, y_src: float, y_trk: float) -> None:
        key = (grid(x), grid(y_src))
        if key not in tapped_pts:
            h.pad("viali", x, y_src, 0.17)
            h.pad("metal1", x, y_src, 0.24, 0.29)
            tapped_pts.add(key)
        if abs(y_src - y_trk) > 1e-6:
            h.wire("metal1", [(x, y_src), (x, y_trk)], W_M1)

    def m1_hop(x1: float, x2: float, y: float = y_t1) -> None:
        m1_tap(x1, y, y)
        m1_tap(x2, y, y)
        h.wire("metal1", [(x1, y), (x2, y)], W_M1)

    # Dual gate straps on bp & op (g_xs[0] and g_xs[1], clear of xd!)
    xg_bp2 = grid(dcols["bp"]["cx"] + dcols["bp"]["inf_p"]["g_xs"][1])
    r4.poly_cont_pad(h, xg_bp2, y_t1)
    h.rect("poly", grid(dc_wire["bp"]["xg"] - 0.135), grid(y_t1 - 0.170), grid(xg_bp2 + 0.135), grid(y_t1 + 0.170))
    m1_hop(dc_wire["bp"]["xg"], xg_bp2)

    xg_op2 = grid(dcols["op"]["cx"] + dcols["op"]["inf_p"]["g_xs"][1])
    r4.poly_cont_pad(h, xg_op2, y_t1)
    h.rect("poly", grid(dc_wire["op"]["xg"] - 0.135), grid(y_t1 - 0.170), grid(xg_op2 + 0.135), grid(y_t1 + 0.170))
    m1_hop(dc_wire["op"]["xg"], xg_op2)

    # bp -> kbp.D -> op.G (straight M1 on y_t1!)
    m1_hop(dc_wire["bp"]["xd"], dc_wire["kbp"]["xd"])
    m1_hop(dc_wire["kbp"]["xd"], dc_wire["op"]["xg"])

    # rawp: op.D -> krp.D -> dp1.G (straight M1 on y_t1!)
    m1_hop(dc_wire["op"]["xd"], dc_wire["krp"]["xd"])
    m1_hop(dc_wire["krp"]["xd"], dc_wire["dp1"]["xg"])

    # Tap kbp.G and krp.G on y_gt_k for top-level M3 cross-coupling
    m1_tap(dc_wire["kbp"]["xg"], y_gt_k, y_gt_k)
    m1_tap(dc_wire["krp"]["xg"], y_gt_k, y_gt_k)

    # M2 bypass rawp -> seta.G
    m1_tap(dc_wire["seta"]["xg"], y_t1, y_t1)
    h.via1(dc_wire["dp1"]["xg"], y_t1)
    h.via1(dc_wire["seta"]["xg"], y_t1)
    h.wire("metal2", [(dc_wire["dp1"]["xg"], y_t1), (dc_wire["seta"]["xg"], y_t1)], W_M2)

    m1_hop(dc_wire["dp1"]["xd"], dc_wire["dp2"]["xg"])
    m1_hop(dc_wire["dp2"]["xd"], dc_wire["dp3"]["xg"])
    m1_hop(dc_wire["dp3"]["xd"], dc_wire["setb"]["xg"])

    # set_b -> y_t2 -> drop on M1 in qpb-qpa column gap -> y_t1 -> qpa.G (keeps qpa.xg locali clear of qpa P-diff!)
    m1_tap(wb_set["xd"], 4.620, y_t2)
    m1_tap(wa_set["xd"], y_t2, y_t2)
    x_set_drop = grid((dcols["qpb"]["cx"] + dcols["qpb"]["hw"] + dcols["qpa"]["cx"] - dcols["qpa"]["hw"]) / 2.0)
    m1_tap(dc_wire["qpa"]["xg"], y_t1, y_t1)
    h.wire("metal1", [(wb_set["xd"], y_t2), (x_set_drop, y_t2), (x_set_drop, y_t1), (dc_wire["qpa"]["xg"], y_t1)], W_M1)

    # qp -> y_t0 -> cr2_n & rp1.G & bpra.G
    x_qpb_pd, x_qpa_pd = wb_qp["xd"], wa_qp["xd"]
    for xc in (x_qpb_pd, x_qpa_pd):
        h.pad("viali", xc, 4.620, 0.17)
        h.pad("metal1", xc, 4.620, 0.24, 0.29)
    h.wire("metal1", [(x_qpb_pd, 4.620), (x_qpa_pd, 4.620)], W_M1)
    h.pad("viali", x_qpa_pd, y_t0, 0.17)
    h.pad("metal1", x_qpa_pd, y_t0, 0.24, 0.29)
    m1_tap(dc_wire["rp1"]["xg"], y_t1, y_t0)
    h.rect("locali", grid(dc_wire["bpra"]["xg"] - 0.085), grid(y_t0 - 0.085), grid(dc_wire["bpra"]["xg"] + 0.085), grid(y_t1 + 0.085))
    m1_tap(dc_wire["bpra"]["xg"], y_t0, y_t0)
    h.wire("metal1", [(x_qpa_pd, y_t0), (dc_wire["bpra"]["xg"], y_t0)], W_M1)

    # qpb.G on y_t1 -> hop over qpa on M2 up to x_c2_r_wall
    m1_tap(dc_wire["qpb"]["xg"], y_t1, y_t1)
    h.via1(dc_wire["qpb"]["xg"], y_t1)
    h.via1(x_c2_r_wall, y_t1)
    h.wire("metal2", [(dc_wire["qpb"]["xg"], y_t1), (x_c2_r_wall, y_t1)], W_M2)

    m1_hop(dc_wire["rp1"]["xd"], dc_wire["rp2"]["xg"])
    m1_tap(dc_wire["rp2"]["xd"], y_t2, y_t2)
    h.rect("locali", grid(dc_wire["bprb"]["xg"] - 0.085), grid(y_t1 - 0.085), grid(dc_wire["bprb"]["xg"] + 0.085), grid(y_t2 + 0.085))
    m1_tap(dc_wire["bprb"]["xg"], y_t2, y_t2)
    h.wire("metal1", [(dc_wire["rp2"]["xd"], y_t2), (dc_wire["bprb"]["xg"], y_t2)], W_M1)

    for xc in (wb_bpr["xd"], wa_bpr["xd"]):
        h.pad("viali", xc, 4.620, 0.17)
        h.pad("metal1", xc, 4.620, 0.24, 0.29)
    h.wire("metal1", [(wb_bpr["xd"], 4.620), (wa_bpr["xd"], 4.620)], W_M1)
    m1_hop(wa_bpr["xd"], dc_wire["opr"]["xg"])

    x_out_port = grid(x_right_tap + 0.940)
    m1_tap(dc_wire["opr"]["xd"], y_t1, y_t1)
    h.wire("metal1", [(dc_wire["opr"]["xd"], y_t1), (x_out_port, y_t1)], W_M1)

    return h, {
        "x_bp_g": dc_wire["bp"]["xg"],
        "x_bp_d": dc_wire["bp"]["xd"],
        "x_kbp_g": dc_wire["kbp"]["xg"],
        "x_krp_g": dc_wire["krp"]["xg"],
        "x_rawp": dc_wire["op"]["xd"],
        "y_gt_k": y_gt_k,
        "y_t0": y_t0,
        "y_t1": y_t1,
        "y_t2": y_t2,
        "x_c12_wall": x_c12_wall,
        "x_c2_r_wall": x_c2_r_wall,
        "x_cr2_n": x_cr2_n,
        "x_cr2_p": x_cr2_p,
        "x_c3_l_wall": x_c3_l_wall,
        "x_right_tap": x_right_tap,
        "x_out_port": x_out_port,
        "n_s_xs": sorted(set(all_n_s)),
        "p_s_xs": sorted(set(all_p_s)),
    }


def build_cml_to_cmos_r5(out: Path) -> dict:
    cell = "serdes_cml_to_cmos_r5_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    ana_half, am = r4.build_analog_half(w)
    # AC/Rfb Coupling Bay sits between x_ana_r_wall and x_dig_l_wall (>= 1.5um M3/capm.11 clearance)!
    x_bay_l = am["x_ana_r_wall"]
    x_bay_cx = grid(x_bay_l + 8.000)
    x_dig_l_wall = grid(x_bay_l + 17.100)
    dig_half, dm = build_digital_half_r5(w, x_dig_l_wall)

    c = Cell()
    c.include(ana_half, mirror_y=False)
    c.include(ana_half, mirror_y=True)
    c.include(dig_half, mirror_y=False)
    c.include(dig_half, mirror_y=True)

    # Single-layer MIM caps (w=9.0, l=5.5) + three physical resistor segments per side.
    mim_c = build_mim_cell(w, "mim90_55", 9.0, 5.5)
    rpo_c, rpo_pts = build_rpo_3leg(w, "rpo6_3", 6.0)
    y_mim_c = 3.600
    y_rpo_c = 6.500
    x_rpo_c = x_bay_cx

    for sgn in (+1, -1):
        # Mirror MIM in X so C2 (bottom M3 plate) faces LEFT toward Analog ap/an, C1 (top M4 plate) faces RIGHT!
        c.include(mim_c, dx=x_bay_cx, dy=grid(sgn * y_mim_c), mirror_x=True, mirror_y=(sgn < 0))
        c.include(rpo_c, dx=x_rpo_c, dy=grid(sgn * y_rpo_c), mirror_y=(sgn < 0))

    x_rail_l = 0.180
    x_dig_rail_r = grid(dm["x_right_tap"] + V_TAP_EDGE + 0.160)
    x_end = grid(dm["x_out_port"] + 0.450)
    x_wl, x_wr = -0.140, grid(max(x_dig_rail_r, x_end) + 0.250)

    # Wells: Analog (-13.65..+13.65) extends through AC/Rfb Bay (pwell holds poly resistors cleanly!), steps down at Digital
    x_ana_r_nwell = grid(am["x_ana_r_wall"] + V_TAP_WALL + 0.250)
    x_bay_r_well = grid(x_dig_l_wall + V_TAP_EDGE + 0.250)
    x_dig_well_l = grid(x_dig_l_wall - V_TAP_EDGE - 0.250)
    c.rect("pwell", x_wl, grid(-Y_A_TOP_GR - 0.250), am["x_ad"], grid(Y_A_TOP_GR + 0.250))
    c.rect("pwell", am["x_ad"], -Y_A_WELL, grid(am["x_ana_r_wall"] + 0.250), Y_A_WELL)
    c.rect("nwell", am["x_ad"], Y_A_WELL, x_ana_r_nwell, grid(Y_VDD1 + 0.450))
    c.rect("nwell", am["x_ad"], grid(-Y_VDD1 - 0.450), x_ana_r_nwell, -Y_A_WELL)
    # AC/Rfb Bay: continuous pwell between -Y_A_TOP_GR .. +Y_A_TOP_GR, outer VDD nwell strips at +-Y_VDD1
    c.rect("pwell", grid(am["x_ana_r_wall"] - 0.100), grid(-Y_A_TOP_GR - 0.250), x_bay_r_well, grid(Y_A_TOP_GR + 0.250))
    c.rect("nwell", grid(am["x_ana_r_wall"] - 0.100), grid(Y_VDD1 - 0.500), x_bay_r_well, grid(Y_VDD1 + 0.450))
    c.rect("nwell", grid(am["x_ana_r_wall"] - 0.100), grid(-Y_VDD1 - 0.450), x_bay_r_well, grid(-Y_VDD1 + 0.500))
    # Digital stepped wells (+-7.91)
    c.rect("pwell", x_dig_well_l, grid(-dm["y_t1"]), x_wr, grid(+dm["y_t1"]))
    c.rect("nwell", x_dig_well_l, grid(+dm["y_t1"]), x_wr, grid(Y_VDD_DIG + 0.450))
    c.rect("nwell", x_dig_well_l, grid(-Y_VDD_DIG - 0.450), x_wr, grid(-dm["y_t1"]))

    # Analog Guard Rings & Vertical NP Walls (unchanged from r4)
    xl = am["x_left_gr"]
    for sgn in (+1, -1):
        r4.draw_tap_h(c, "psubdiff", x_rail_l, grid(am["x_sf_gr"] + V_TAP_WALL), sgn * Y_A_TOP_GR, half_w=H_TAP_VSS)
        c.wire("metal1", [(x_rail_l, sgn * Y_A_TOP_GR), (grid(am["x_sf_gr"] + V_TAP_WALL), sgn * Y_A_TOP_GR)], W_PWR_M1)
        for xv in (xl, am["x_fp_vdd_drop_l"], am["cx_fp"], am["x_fp_vdd_drop"], am["x_sf_gr"]):
            pass
        for xv in (xl, am["x_fp_vdrop_l"], am["cx_fp"], am["x_fp_vdrop_r"], am["x_sf_gr"]):
            r4.viali_on_rail(c, xv, sgn * Y_A_TOP_GR)
        r4.draw_tap_v(c, "psubdiff", xl, 0.000 if sgn > 0 else -Y_A_TOP_GR, Y_A_TOP_GR if sgn > 0 else 0.000, half_w=V_TAP_EDGE)
        r4.draw_tap_v(c, "psubdiff", am["x_sf_gr"], 0.000 if sgn > 0 else -Y_A_TOP_GR, Y_A_TOP_GR if sgn > 0 else 0.000, half_w=V_TAP_WALL)
        if sgn > 0:
            r4.draw_np_wall_band(c, am["x_ana_l_wall"], Y_ANA_VSS, Y_A_T1, Y_VDD1, half_w=V_TAP_WALL)
            r4.draw_np_wall_band(c, am["x_ana_r_wall"], Y_ANA_VSS, Y_A_T1, Y_VDD1, half_w=V_TAP_WALL)
        else:
            r4.draw_np_wall_band(c, am["x_ana_l_wall"], Y_ANA_VSS, -Y_A_T1, -Y_VDD1, half_w=V_TAP_WALL)
            r4.draw_np_wall_band(c, am["x_ana_r_wall"], Y_ANA_VSS, -Y_A_T1, -Y_VDD1, half_w=V_TAP_WALL)

    # Digital Vertical NP walls
    for xw, hw_w in ((x_dig_l_wall, V_TAP_EDGE), (dm["x_c12_wall"], V_TAP_WALL), (dm["x_c2_r_wall"], V_TAP_WALL), (dm["x_c3_l_wall"], V_TAP_WALL), (dm["x_right_tap"], V_TAP_EDGE)):
        r4.draw_np_wall_band(c, xw, Y_ANA_VSS, +dm["y_t1"], +Y_VDD_DIG, half_w=hw_w)
        r4.draw_np_wall_band(c, xw, Y_ANA_VSS, -dm["y_t1"], -Y_VDD_DIG, half_w=hw_w)

    # Center Shared VSS Rail (0.000): psubdiff + M1 + continuous wide M2 + M4 (clear of M3 crossover at kbp/krp/cr1/cr2!)
    ana_walls = [xl, am["x_sf_gr"], am["x_ana_l_wall"], am["x_ana_r_wall"], am["x_fp_vdd_drop"]]
    dig_walls = [x_dig_l_wall, dm["x_c12_wall"], dm["x_c2_r_wall"], dm["x_c3_l_wall"], dm["x_right_tap"]]
    all_walls = ana_walls + dig_walls

    r4.draw_tap_h(c, "psubdiff", x_rail_l, x_dig_rail_r, Y_ANA_VSS, half_w=H_TAP_VSS)
    c.wire("metal1", [(x_rail_l, Y_ANA_VSS), (x_dig_rail_r, Y_ANA_VSS)], W_PWR_M1)
    c.wire("metal2", [(x_rail_l, Y_ANA_VSS), (x_dig_rail_r, Y_ANA_VSS)], 0.56)
    x_vss_ana_m3_l = grid(am["x_ana_l_wall"] + 0.780)
    x_vss_ana_m3_r = grid(am["x_ana_r_wall"] - 1.000)
    x_vss_dig_m3_l = grid(dm["x_c12_wall"] + 0.400)
    x_vss_dig_m3_r = grid(dm["x_c2_r_wall"] - 0.400)
    c.wire("metal3", [(x_vss_ana_m3_l, Y_ANA_VSS), (x_vss_ana_m3_r, Y_ANA_VSS)], 0.56)
    c.wire("metal3", [(x_vss_dig_m3_l, Y_ANA_VSS), (x_vss_dig_m3_r, Y_ANA_VSS)], 0.56)
    c.pad("metal3", x_dig_l_wall, Y_ANA_VSS, 0.56, 0.64)
    all_vss_via2_xs = [x_dig_l_wall]
    for sx in dm["n_s_xs"] + am["ana_n_s_xs"]:
        c.pad("viali", sx, Y_ANA_VSS, 0.17)
        if all(abs(sx - ax) > 0.75 for ax in all_walls):
            c.via1(sx, Y_ANA_VSS)
            if ((x_vss_ana_m3_l + 0.25 <= sx <= x_vss_ana_m3_r - 0.25) or (x_vss_dig_m3_l + 0.25 <= sx <= x_vss_dig_m3_r - 0.25)) and all(abs(sx - vx2) > 0.45 for vx2 in all_vss_via2_xs):
                c.via2(sx, Y_ANA_VSS)
                all_vss_via2_xs.append(sx)
    for k in range(50):
        vx = grid(xl + 0.85 + k * (dm["x_right_tap"] - xl - 1.70) / 49)
        if all(abs(vx - ax) > 0.75 for ax in all_walls) and all(abs(vx - sx) > 0.36 for sx in dm["n_s_xs"] + am["ana_n_s_xs"]):
            r4.viali_on_rail(c, vx, Y_ANA_VSS)
            c.via1(vx, Y_ANA_VSS)
            if ((x_vss_ana_m3_l + 0.25 <= vx <= x_vss_ana_m3_r - 0.25) or (x_vss_dig_m3_l + 0.25 <= vx <= x_vss_dig_m3_r - 0.25)) and all(abs(vx - vx2) > 0.45 for vx2 in all_vss_via2_xs):
                c.via2(vx, Y_ANA_VSS)
                all_vss_via2_xs.append(vx)

    # Analog + Bay VDD Rails (+-13.200) -> step down at x_dig_l_wall to Digital VDD Rails (+-7.460)
    x_ana_rail_r = grid(x_dig_l_wall + 0.200)
    x_ana_tap_r = grid(x_dig_l_wall)
    r4.draw_tap_h(c, "nsubdiff", grid(am["x_ana_l_wall"] - V_TAP_WALL), x_ana_tap_r, -Y_VDD1, half_w=H_TAP_VDD)
    r4.draw_tap_h(c, "nsubdiff", grid(am["x_ad"] + 0.200), x_ana_tap_r, +Y_VDD1, half_w=H_TAP_VDD)
    for sgn in (+1, -1):
        yv = sgn * Y_VDD1
        c.wire("metal1", [(x_rail_l, yv), (x_ana_rail_r, yv)], W_PWR_M1)
        c.wire("metal2", [(x_rail_l, yv), (x_ana_rail_r, yv)], W_PWR_M2)
        c.wire("metal3", [(x_rail_l, yv), (x_ana_rail_r, yv)], W_PWR_M3)
        c.via1(xl, yv); c.via2(xl, yv)
        for xfvd in (am["x_fp_vdd_drop_l"], am["x_fp_vdd_drop"]):
            c.via1(xfvd, yv); c.via2(xfvd, yv)
        for sx in am["ana_p_s_xs"]:
            r4.viali_on_rail(c, sx, yv); c.via1(sx, yv); c.via2(sx, yv)
        for k in range(10):
            vx = grid(am["x_ana_l_wall"] + 0.85 + k * (am["x_ana_r_wall"] - am["x_ana_l_wall"] - 1.70) / 9)
            if all(abs(vx - ax) > 0.75 for ax in ana_walls) and all(abs(vx - sx) > 0.42 for sx in am["ana_p_s_xs"]):
                r4.viali_on_rail(c, vx, yv); c.via1(vx, yv); c.via2(vx, yv)

    x_dig_vdd_l = grid(x_dig_l_wall - V_TAP_EDGE)
    for sgn in (+1, -1):
        yv = sgn * Y_VDD_DIG
        r4.draw_tap_h(c, "nsubdiff", x_dig_vdd_l, x_dig_rail_r, yv, half_w=H_TAP_VDD)
        c.wire("metal1", [(x_dig_vdd_l, yv), (x_dig_rail_r, yv)], W_PWR_M1)
        c.wire("metal2", [(x_dig_vdd_l, yv), (x_dig_rail_r, yv)], W_PWR_M2)
        c.wire("metal3", [(x_dig_l_wall, yv), (x_dig_rail_r, yv)], W_PWR_M3)
        for sx in dm["p_s_xs"]:
            c.pad("viali", sx, yv, 0.17)
            if all(abs(sx - ax) > 0.45 for ax in (x_dig_l_wall, dm["x_right_tap"])):
                c.via1(sx, yv); c.via2(sx, yv)
        for k in range(30):
            vx = grid(x_dig_l_wall + 0.85 + k * (dm["x_right_tap"] - x_dig_l_wall - 1.70) / 29)
            if all(abs(vx - ax) > 0.75 for ax in all_walls) and all(abs(vx - sx) > 0.42 for sx in dm["p_s_xs"]):
                r4.viali_on_rail(c, vx, yv); c.via1(vx, yv); c.via2(vx, yv)

    # Vertical Power Spines & M4 VDD/VSS
    for yv in (-Y_A_TOP_GR, Y_ANA_VSS, +Y_A_TOP_GR):
        c.via1(xl, yv)
    c.wire("metal2", [(xl, -Y_A_TOP_GR), (xl, +Y_A_TOP_GR)], 0.60)

    # Step-down M3+M4 VDD spine at x_dig_l_wall (+-13.20 -> +-7.46, clear of MIM caps!)
    for yv in (-Y_VDD1, +Y_VDD1, -Y_VDD_DIG, +Y_VDD_DIG):
        c.via1(x_dig_l_wall, yv)
        c.via2(x_dig_l_wall, yv)
        via3_pad_r5(c, x_dig_l_wall, yv)
    c.wire("metal3", [(x_dig_l_wall, -Y_VDD1), (x_dig_l_wall, -Y_VDD_DIG)], 0.80)
    c.wire("metal3", [(x_dig_l_wall, +Y_VDD_DIG), (x_dig_l_wall, +Y_VDD1)], 0.80)
    c.wire("metal4", [(x_dig_l_wall, -Y_VDD1), (x_dig_l_wall, -Y_VDD_DIG)], 1.00)
    c.wire("metal4", [(x_dig_l_wall, +Y_VDD_DIG), (x_dig_l_wall, +Y_VDD1)], 1.00)
    # Note M4 VDD bridge between top & bottom sits at xr_t (East Digital wall), NOT crossing y=0 at x_dig_l_wall!
    xr_t = dm["x_right_tap"]
    for yv in (-Y_VDD_DIG, +Y_VDD_DIG):
        c.via1(xr_t, yv); c.via2(xr_t, yv); via3_pad_r5(c, xr_t, yv)
    c.wire("metal3", [(xr_t, -Y_VDD_DIG), (xr_t, +Y_VDD_DIG)], 0.60)
    c.wire("metal4", [(xr_t, -Y_VDD_DIG), (xr_t, +Y_VDD_DIG)], 0.80)

    # Digital M4 VSS spine @ y=0 from x_dig_l_wall to x_vss_dig_m3_r
    c.via1(x_dig_l_wall, Y_ANA_VSS); c.via2(x_dig_l_wall, Y_ANA_VSS); via3_pad_r5(c, x_dig_l_wall, Y_ANA_VSS)
    x_vss_m4_r = grid(min(x_vss_dig_m3_r, xr_t - 1.500))
    c.wire("metal4", [(x_dig_l_wall, Y_ANA_VSS), (x_vss_m4_r, Y_ANA_VSS)], 0.80)
    for xv in (dm["x_c12_wall"] + 1.0, dm["x_c12_wall"] + 4.5, x_vss_m4_r - 0.4):
        xg = grid(xv)
        if x_dig_l_wall + 0.5 <= xg <= x_vss_m4_r:
            via3_pad_r5(c, xg, Y_ANA_VSS)

    for sgn in (+1, -1):
        ya, yd = sgn * Y_VDD1, sgn * Y_VDD_DIG
        c.wire("metal4", [(am["x_fp_vdd_drop_l"], ya), (x_dig_l_wall, ya)], 1.20)
        c.wire("metal4", [(x_dig_l_wall, yd), (xr_t, yd)], 1.20)
        for xv in (am["x_fp_vdd_drop_l"], am["x_fp_vdd_drop"], am["ana_p_s_xs"][1], am["ana_p_s_xs"][-2], x_dig_l_wall):
            xg = grid(xv)
            via3_pad_r5(c, xg, grid(ya - 0.24))
            via3_pad_r5(c, xg, grid(ya + 0.24))
        for xv in (x_dig_l_wall, grid(x_dig_l_wall + 5.0), grid(dm["x_c12_wall"] + 2.0), grid(dm["x_c2_r_wall"] - 1.5), xr_t):
            via3_pad_r5(c, xv, grid(yd - 0.24))
            via3_pad_r5(c, xv, grid(yd + 0.24))

    # -------------------------------------------------------------------------
    # Wire AC/Rfb Coupling Bay (ap/an -> XCac -> ap_ac/an_ac -> Xbp.G + XRfb -> bp/bn)
    # -------------------------------------------------------------------------
    for sgn in (+1, -1):
        # 1. ap/an from Domain B (am["x_ap_v"], +-Y_A_T2) -> M3 bottom plate C2 of XCac (x_bay_cx - 5.17, +-y_mim_c)
        x_c2 = grid(x_bay_cx - 5.170)  # mirrored X!
        y_c_mim = grid(sgn * y_mim_c)
        c.wire("metal1", [(am["x_ap_v"], sgn * Y_A_T2), (x_c2, sgn * Y_A_T2)], W_M1)
        c.via1(x_c2, sgn * Y_A_T2); c.via2(x_c2, sgn * Y_A_T2)
        c.wire("metal3", [(x_c2, sgn * Y_A_T2), (x_c2, y_c_mim)], W_M3)

        # 2. ap_ac from M4 top plate C1 of XCac (x_bay_cx + 0.73, +-y_mim_c) -> exit RIGHT >= 1.61um outside mimcap!
        x_c1 = grid(x_bay_cx + 0.730)
        x_apac_drop = grid(x_bay_cx + 7.100)
        c.wire("metal4", [(x_c1, y_c_mim), (x_apac_drop, y_c_mim)], 0.52)
        via3_pad_r5(c, x_apac_drop, y_c_mim)
        c.via2(x_apac_drop, y_c_mim)
        c.wire("metal2", [(x_apac_drop, y_c_mim), (x_apac_drop, sgn * dm["y_t1"])], W_M2)
        c.via1(x_apac_drop, sgn * dm["y_t1"])
        # Connect ap_ac right to bp.G on M1 @ +-dm["y_t1"] AND left to XRfb term A (R1_0)!
        c.wire("metal1", [(x_apac_drop, sgn * dm["y_t1"]), (dm["x_bp_g"], sgn * dm["y_t1"])], W_M1)
        x_ra = grid(x_rpo_c + rpo_pts["a"][0])
        y_ra = grid(sgn * (y_rpo_c + rpo_pts["a"][1]))
        # Run M2 from (x_apac_drop, y_c_mim) -> (x_ra, y_ra) -> via1 -> M1 into R1_0!
        c.wire("metal2", [(x_apac_drop, y_c_mim), (x_apac_drop, y_ra), (x_ra, y_ra)], W_M2)
        c.via1(x_ra, y_ra)

        # 3. XRfb term B (R2_2 -> bp/bn) -> M2 -> M1 @ +-dm["y_t0"] right into bp.D!
        x_rb = grid(x_rpo_c + rpo_pts["b"][0])
        y_rb = grid(sgn * (y_rpo_c + rpo_pts["b"][1]))
        c.via1(x_rb, y_rb)
        c.wire("metal2", [(x_rb, y_rb), (x_rb, sgn * dm["y_t0"]), (x_apac_drop - 0.80, sgn * dm["y_t0"])], W_M2)
        c.via1(x_apac_drop - 0.80, sgn * dm["y_t0"])
        # Note y_t0 track in [x_dig_l_wall .. bp.D] is completely open!
        c.wire("metal1", [(x_apac_drop - 0.80, sgn * dm["y_t0"]), (dm["x_bp_d"], sgn * dm["y_t0"])], W_M1)
        c.pad("viali", dm["x_bp_d"], sgn * dm["y_t0"], 0.17)
        c.pad("metal1", dm["x_bp_d"], sgn * dm["y_t0"], 0.24, 0.29)

    # Weak cross-coupled inverters kbp (bp<->bn) & krp (rawp<->rawn) M3 crossovers across y=0!
    yk = dm["y_gt_k"]
    for x_src, x_dst in ((dm["x_bp_d"], dm["x_kbp_g"]), (dm["x_rawp"], dm["x_krp_g"])):
        x_dn_m3 = grid(x_dst + 0.750)  # Top sig -> Bot gate (-yk), >= 0.35um clear of x_up_m3
        x_up_m3 = grid(x_dst)          # Bot sig -> Top gate (+yk)
        c.via1(x_src, +dm["y_t1"]); c.via1(x_dn_m3, +dm["y_t2"])
        c.wire("metal2", [(x_src, +dm["y_t1"]), (x_src, +dm["y_t2"]), (x_dn_m3, +dm["y_t2"])], W_M2)
        c.via2(x_dn_m3, +dm["y_t2"]); c.via2(x_dn_m3, -yk); c.via1(x_dn_m3, -yk)
        c.wire("metal3", [(x_dn_m3, -yk), (x_dn_m3, +dm["y_t2"])], W_M3)
        c.wire("metal1", [(min(x_dn_m3, x_dst), -yk), (max(x_dn_m3, x_dst), -yk)], W_M1)

        c.via1(x_src, -dm["y_t1"]); c.via1(x_up_m3, -dm["y_t2"])
        c.wire("metal2", [(x_src, -dm["y_t1"]), (x_src, -dm["y_t2"]), (x_up_m3, -dm["y_t2"])], W_M2)
        c.via2(x_up_m3, -dm["y_t2"]); c.via2(x_up_m3, +yk); c.via1(x_up_m3, +yk)
        c.wire("metal3", [(x_up_m3, -dm["y_t2"]), (x_up_m3, +yk)], W_M3)

    # vbias, cr1, cr2, and I/O ports (identical to r4)
    x_vb = am["x_vbias"]
    for yb in (-Y_A_T1, +Y_A_T1):
        c.via1(x_vb, yb); c.via2(x_vb, yb)
    c.wire("metal3", [(x_vb, -Y_A_T1), (x_vb, +Y_A_T1)], W_M3)
    c.pad("metal3", x_vb, +Y_A_T1, 0.40, 0.60)

    x1p, x1n = am["x_cr1_p"], am["x_cr1_n"]
    c.wire("metal1", [(am["x_sf_gr"], +Y_A_T0), (x1p, +Y_A_T0)], W_M1)
    c.wire("metal1", [(am["x_sf_gr"], -Y_A_T0), (x1n, -Y_A_T0)], W_M1)
    c.wire("metal1", [(x1n, +Y_A_T1), (am["x_ana_l_wall"], +Y_A_T1)], W_M1)
    c.wire("metal1", [(x1p, -Y_A_T1), (am["x_ana_l_wall"], -Y_A_T1)], W_M1)
    c.wire("metal1", [(x1p, +Y_A_T0), (am["x_ana_l_wall"], +Y_A_T0)], W_M1)
    c.wire("metal1", [(x1n, -Y_A_T0), (am["x_ana_l_wall"], -Y_A_T0)], W_M1)
    for x_cr, y_s, y_d in ((x1p, +Y_A_T0, -Y_A_T1), (x1n, -Y_A_T0, +Y_A_T1)):
        c.via1(x_cr, y_s); c.via2(x_cr, y_s); c.via1(x_cr, y_d); c.via2(x_cr, y_d)
        c.wire("metal3", [(x_cr, y_s), (x_cr, y_d)], W_M3)

    x2n, x2p = dm["x_cr2_n"], dm["x_cr2_p"]
    c.wire("metal1", [(dm["x_c2_r_wall"], +dm["y_t1"]), (x2p, +dm["y_t1"])], W_M1)
    c.wire("metal1", [(dm["x_c2_r_wall"], -dm["y_t1"]), (x2n, -dm["y_t1"])], W_M1)
    for x_cr, y_s, y_d in ((x2n, +dm["y_t0"], -dm["y_t1"]), (x2p, -dm["y_t0"], +dm["y_t1"])):
        c.via1(x_cr, y_s); c.via2(x_cr, y_s); c.via1(x_cr, y_d); c.via2(x_cr, y_d)
        c.wire("metal3", [(x_cr, y_s), (x_cr, y_d)], W_M3)

    x_inp, x_out = am["x_inp"], dm["x_out_port"]
    for xp, yp in ((x_inp, +Y_A_T2), (x_inp, -Y_A_T2), (x_out, +dm["y_t1"]), (x_out, -dm["y_t1"])):
        c.via1(xp, yp); c.via2(xp, yp); c.pad("metal3", xp, yp, 0.40, 0.60)

    c.port("inp", "metal3", x_inp, +Y_A_T2)
    c.port("inn", "metal3", x_inp, -Y_A_T2)
    c.port("outp", "metal3", x_out, +dm["y_t1"])
    c.port("outn", "metal3", x_out, -dm["y_t1"])
    c.port("vbias", "metal3", x_vb, +Y_A_T1)
    c.port("vdd", "metal4", x_dig_l_wall, +Y_VDD_DIG)
    c.port("vss", "metal4", x_dig_l_wall, Y_ANA_VSS)
    c.write(w / f"{cell}.mag")

    def inv_lines(inst: str, inp: str, outp: str, wn: float, wp: float) -> list[str]:
        return [
            f"X{inst}_n {outp} {inp} vss vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{inst}_p {outp} {inp} vdd vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
        ]

    def nand_lines(inst: str, a: str, b: str, outp: str, wn: float, wp: float) -> list[str]:
        return [
            f"X{inst}_nt {outp} {a} {inst}_mid vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{inst}_nb {inst}_mid {b} vss vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{inst}_pa {outp} {a} vdd vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
            f"X{inst}_pb {outp} {b} vdd vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
        ]

    ref_lines = [
        "* Physical LVS reference for serdes_cml_to_cmos_r5_pdk",
        f".subckt {cell} inp inn outp outn vbias vdd vss",
        "Xfp vdd inp fp vss sky130_fd_pr__nfet_01v8_lvt w=32 l=0.15",
        "Xfn vdd inn fn vss sky130_fd_pr__nfet_01v8_lvt w=32 l=0.15",
        "Xsp fp vbias vss vss sky130_fd_pr__nfet_01v8 w=3 l=0.5",
        "Xsn fn vbias vss vss sky130_fd_pr__nfet_01v8 w=3 l=0.5",
        "Xap_ip ap_mir fp ap_tail vss sky130_fd_pr__nfet_01v8_lvt w=16 l=0.15",
        "Xap_in ap fn ap_tail vss sky130_fd_pr__nfet_01v8_lvt w=16 l=0.15",
        "Xap_lp ap_mir ap_mir vdd vdd sky130_fd_pr__pfet_01v8 w=32 l=0.15",
        "Xap_ln ap ap_mir vdd vdd sky130_fd_pr__pfet_01v8 w=32 l=0.15",
        "Xap_t ap_tail vbias vss vss sky130_fd_pr__nfet_01v8 w=32 l=0.5",
        "Xan_ip an_mir fn an_tail vss sky130_fd_pr__nfet_01v8_lvt w=16 l=0.15",
        "Xan_in an fp an_tail vss sky130_fd_pr__nfet_01v8_lvt w=16 l=0.15",
        "Xan_lp an_mir an_mir vdd vdd sky130_fd_pr__pfet_01v8 w=32 l=0.15",
        "Xan_ln an an_mir vdd vdd sky130_fd_pr__pfet_01v8 w=32 l=0.15",
        "Xan_t an_tail vbias vss vss sky130_fd_pr__nfet_01v8 w=32 l=0.5",
        "XCac_p ap_ac ap sky130_fd_pr__cap_mim_m3_1 w=9 l=5.5",
        "XCac_n an_ac an sky130_fd_pr__cap_mim_m3_1 w=9 l=5.5",
        "XRfb_p0 ap_ac rfp1 vss sky130_fd_pr__res_high_po_0p35 l=6",
        "XRfb_p1 rfp1  rfp2 vss sky130_fd_pr__res_high_po_0p35 l=6",
        "XRfb_p2 rfp2  bp   vss sky130_fd_pr__res_high_po_0p35 l=6",
        "XRfb_n0 an_ac rfn1 vss sky130_fd_pr__res_high_po_0p35 l=6",
        "XRfb_n1 rfn1  rfn2 vss sky130_fd_pr__res_high_po_0p35 l=6",
        "XRfb_n2 rfn2  bn   vss sky130_fd_pr__res_high_po_0p35 l=6",
        *inv_lines("bp", "ap_ac", "bp", 6.0, 7.2),
        *inv_lines("bn", "an_ac", "bn", 6.0, 7.2),
        *inv_lines("kbp", "bn", "bp", 0.6, 1.2),
        *inv_lines("kbn", "bp", "bn", 0.6, 1.2),
        *inv_lines("op", "bp", "rawp", 3.6, 6.4),
        *inv_lines("on", "bn", "rawn", 3.6, 6.4),
        *inv_lines("krp", "rawn", "rawp", 0.6, 1.2),
        *inv_lines("krn", "rawp", "rawn", 0.6, 1.2),
        *inv_lines("dp1", "rawp", "dp1", 1.2, 3.2),
        *inv_lines("dp2", "dp1", "dp2", 1.2, 3.2),
        *inv_lines("dp3", "dp2", "dp3", 1.2, 3.2),
        *inv_lines("dn1", "rawn", "dn1", 1.2, 3.2),
        *inv_lines("dn2", "dn1", "dn2", 1.2, 3.2),
        *inv_lines("dn3", "dn2", "dn3", 1.2, 3.2),
        *nand_lines("set", "rawp", "dp3", "set_b", 4.5, 4.5),
        *nand_lines("rst", "rawn", "dn3", "reset_b", 4.5, 4.5),
        *nand_lines("qp", "set_b", "qn", "qp", 6.0, 9.0),
        *nand_lines("qn", "reset_b", "qp", "qn", 6.0, 9.0),
        *inv_lines("rp1", "qp", "rp1", 2.4, 7.2),
        *inv_lines("rp2", "rp1", "rp2", 1.5, 4.5),
        *inv_lines("rn1", "qn", "rn1", 2.4, 7.2),
        *inv_lines("rn2", "rn1", "rn2", 1.5, 4.5),
        *nand_lines("bpr", "qp", "rp2", "bp_r", 2.4, 3.6),
        *nand_lines("bnr", "qn", "rn2", "bn_r", 2.4, 3.6),
        *inv_lines("opr", "bp_r", "outp", 4.0, 8.0),
        *inv_lines("onr", "bn_r", "outn", 4.0, 8.0),
        f".ends {cell}",
        "",
    ]
    ref_path = w / f"{cell}_ref.spice"
    ref_path.write_text("\n".join(ref_lines))

    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"), str(w), cell, "--ref", str(ref_path)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    log = proc.stdout + proc.stderr
    (w / "check.log").write_text(log)
    if proc.returncode != 0:
        raise RuntimeError(f"{cell} failed checks:\n{log}")

    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"), str(w / f"{cell}.mag"), str(w / f"{cell}.png")],
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

    r = build_cml_to_cmos_r5(out)
    print(
        f"{r['cell']:36s} | DRC={r['drc_boxes']} | LVS={r['lvs_match']} | "
        f"PROP_ERR={r['lvs_property_errors']} | ports={len(r['exported_ports'])} | size={r['size_um']} um | area={r['area_um2']} um2",
        flush=True,
    )
    (out / "summary.json").write_text(json.dumps([r], indent=2) + "\n")
    if args.install_dir:
        inst = args.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "summary.json", inst / "summary.json")
        cdir = out / r["cell"]
        for ext in (".mag", ".png", "_ref.spice", "_lvs.spice", "_pex.spice"):
            src = cdir / f"{r['cell']}{ext}"
            if src.exists():
                shutil.copy2(src, inst / src.name)


if __name__ == "__main__":
    main()
