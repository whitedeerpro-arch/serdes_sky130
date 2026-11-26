#!/usr/bin/env python3
"""SKY130A 5.0 GHz Arch C Complementary LC-VCO + 2.5 GHz Quadrature CML /2 PDK Layout Builder (v3 Low-Profile).

Ultra-low-profile 2-band RFIC floorplan matching the 248 um spiral inductor width 1:1
(cuts active macro height -42% from 178.4 um -> ~102 um and total macro height 439 -> ~355 um):
  - Band 1 (y = -23 .. +31, height ~54 um):
      * Center (|x| <= 66): Complementary -gm core + 2x6f varactors + fixed MIM + 15u common-centroid bank
      * West Wing (x in [-112..-72]): 2 pF tail bypass MIM (`Xctail`) + tail source (`Xtail`) directly below
      * East Wing (x in [+72..+112]): 1 pF gate LPF MIM (`Xcf_t`) + VCO bias (`Xrbias/Xrf_t/Xnbias`) +
                                      CML div2 bias diode (`Xrb1` horiz + `Xnb1`) tucked cleanly underneath
  - Band 2 (y = -68 .. -25, height ~43 um):
      * Center (|x| <= 44): Shoulder-to-shoulder Master/Slave 5->2.5 GHz CML /2 latches with tail FETs
                            (`Xtail_m/s`) placed side-by-side with clock switches (saving 10 um height!)
      * Flanks (x = +-54): `Xacp` & `Xacn` 8x8 um AC-coupling MIMs right beside Master/Slave
      * Bottom 2-row mirror-symmetric CM bias resistors (`Xrc_p` | `Xrc_n` on row A; `Xrc_hi` | `Xrc_lo` on row B)
        meeting at `vck_cm` at x = 0 (cutting 4-row resistor stack in half!)

Verified with Magic `drc(full) = 0` (active & full-hierarchy top), Netgen `LVS = MATCH` (159/159 devices,
0 prop err), 0.0% M5 inside active submacro, and full CPEX extraction.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Polygon as MplPolygon, Rectangle

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
sys.path.insert(0, str(REPO / "analog/rx/cmos_rx/layout"))

import rx_layout_common as rlc  # noqa: E402
from rx_layout_common import (  # noqa: E402
    Cell,
    PdkCache,
    N_STD,
    N_LVT,
    P_STD,
    P_LVT,
    MIM1,
    R_2P85,
    grid,
    viali_pad,
    via1_clean,
    via2_clean,
    via3_pad,
    locali_v,
    draw_tap_h,
    draw_tap_v,
    tie_mos_gates,
)

R_1P41 = "sky130_fd_pr__res_high_po_1p41"
VAR_LVT = "sky130_fd_pr__cap_var_lvt"

IND_MAG = REPO / "analog/pll/vco_5g/layout/variants/ind_sym_2n2_pdk/vco5g_ind_sym_2n2_pdk.mag"
IND_OCT_MAG = REPO / "analog/pll/vco_5g/layout/variants/ind_oct_2n5_pdk/vco5g_ind_oct_2n5_pdk.mag"
VARIANT_DIR = Path(__file__).resolve().parent / "variants" / "lc_vco_5g_pdk"
UNIFIED_VARIANT_DIR = Path(__file__).resolve().parent / "variants" / "lc_vco_5g_unified_pdk"
OCT_VARIANT_DIR = Path(__file__).resolve().parent / "variants" / "lc_vco_5g_oct_pdk"
RESULTS_DIR = REPO / "results" / "layout" / "vco_5g_macro_pdk"
UNIFIED_RESULTS_DIR = REPO / "results" / "layout" / "vco_5g_macro_unified_pdk"
OCT_RESULTS_DIR = REPO / "results" / "layout" / "vco_5g_macro_oct_pdk"
PLOT_MAG = REPO / "verification/layout/plot_mag.py"
REVIEW_CELL = REPO / "verification/layout/review_cell.py"
KLAYOUT_BIN = Path("/home/host/.local/bin/klayout")
KLAYOUT_DRC = Path("/home/host/.volare/sky130A/libs.tech/klayout/drc/sky130A_mr.drc")

BANK_BIT_MAP = [3, 3, 3, 3, 2, 2, 1, 0, 1, 2, 2, 3, 3, 3, 3]


def build_active_ref_spice(*, unified: bool = False, variant: str | None = None) -> str:
    v = variant or ("unified" if unified else "oct")
    is_uni = v in ("unified", "oct")
    cell_name = {
        "legacy": "vco5g_lc_active_div2_pdk",
        "unified": "vco5g_lc_active_div2_unified_pdk",
        "oct": "vco5g_lc_active_div2_oct_pdk",
    }[v]
    capw = {"legacy": 4.2, "unified": 4.0, "oct": 3.6}[v]
    wt, nft = (60.0, 12) if is_uni else (80.0, 16)
    ctail_top = "vdd" if is_uni else "tail"
    lines = [
        f"* Reference LVS SPICE for {cell_name} (100% SKY130A PDK devices)",
        f".subckt {cell_name} vp vn ip in qp qn vctrl b0 b1 b2 b3 vdd vss",
    ]
    if not is_uni:
        lines.extend([
            "Xcfix_p vp vss sky130_fd_pr__cap_mim_m3_1 w=3.0 l=3.0",
            "Xcfix_n vn vss sky130_fd_pr__cap_mim_m3_1 w=3.0 l=3.0",
        ])
    lines.extend([
        "Xmn1 vp vn tail vss sky130_fd_pr__nfet_01v8_lvt w=40.0 l=0.15 nf=16",
        "Xmn2 vn vp tail vss sky130_fd_pr__nfet_01v8_lvt w=40.0 l=0.15 nf=16",
        "Xmp1 vp vn vdd  vdd sky130_fd_pr__pfet_01v8_lvt w=64.0 l=0.35 nf=16",
        "Xmp2 vn vp vdd  vdd sky130_fd_pr__pfet_01v8_lvt w=64.0 l=0.35 nf=16",
    ])
    for k in range(6):
        lines.append(f"Xvarp_{k} vp vctrl vss sky130_fd_pr__cap_var_lvt w=5.2 l=0.5")
        lines.append(f"Xvarn_{k} vn vctrl vss sky130_fd_pr__cap_var_lvt w=5.2 l=0.5")
    for idx, bit in enumerate(BANK_BIT_MAP):
        sp, sn, en = f"sp_{idx}", f"sn_{idx}", f"b{bit}"
        lines.extend([
            f"Xcap_p_{idx} vp {sp} sky130_fd_pr__cap_mim_m3_1 w={capw} l={capw}",
            f"Xcap_n_{idx} vn {sn} sky130_fd_pr__cap_mim_m3_1 w={capw} l={capw}",
            f"Xsw_{idx} {sp} {en} {sn} vss sky130_fd_pr__nfet_01v8_lvt w=16.0 l=0.15 nf=4",
            f"Xon_p_{idx} {sp} {en} vss vss sky130_fd_pr__nfet_01v8 w=1.0 l=0.5 nf=1",
            f"Xon_n_{idx} {sn} {en} vss vss sky130_fd_pr__nfet_01v8 w=1.0 l=0.5 nf=1",
            f"Xoff_p_{idx} {sp} {en} vdd vdd sky130_fd_pr__pfet_01v8 w=1.0 l=0.5 nf=1",
            f"Xoff_n_{idx} {sn} {en} vdd vdd sky130_fd_pr__pfet_01v8 w=1.0 l=0.5 nf=1",
        ])
    lines.extend([
        f"Xtail tail vbias_f vss vss sky130_fd_pr__nfet_01v8 w={wt} l=0.5 nf={nft}",
        f"Xctail {ctail_top} vss sky130_fd_pr__cap_mim_m3_1 w=32.0 l=32.0",
        "Xrbias vdd vbias_lc vss sky130_fd_pr__res_high_po_1p41 l=9.8",
        "Xnbias vbias_lc vbias_lc vss vss sky130_fd_pr__nfet_01v8 w=6.0 l=0.5 nf=2",
        "Xrf_t vbias_lc vbias_f vss sky130_fd_pr__res_high_po_1p41 l=10.0",
        "Xcf_t vbias_f vss sky130_fd_pr__cap_mim_m3_1 w=22.0 l=22.0",
        "Xacp vp ckp sky130_fd_pr__cap_mim_m3_1 w=8.0 l=8.0",
        "Xacn vn ckn sky130_fd_pr__cap_mim_m3_1 w=8.0 l=8.0",
        "Xrb1 vdd vbias_d vss sky130_fd_pr__res_high_po_1p41 l=14.0",
        "Xnb1 vbias_d vbias_d vss vss sky130_fd_pr__nfet_01v8 w=6.0 l=0.35 nf=2",
        "Xrc_hi vdd vck_cm vss sky130_fd_pr__res_high_po_1p41 l=60.0",
        "Xrc_lo vck_cm vss vss sky130_fd_pr__res_high_po_1p41 l=96.0",
        "Xrc_p vck_cm ckp vss sky130_fd_pr__res_high_po_1p41 l=80.0",
        "Xrc_n vck_cm ckn vss sky130_fd_pr__res_high_po_1p41 l=80.0",
    ])
    for tag, dp, dn, qp, qn, ckp, ckn in [
        ("m", "qn", "qp", "ip", "in", "ckp", "ckn"),
        ("s", "ip", "in", "qp", "qn", "ckn", "ckp"),
    ]:
        lines.extend([
            f"X{tag}_rp1 vdd {qp} vss sky130_fd_pr__res_high_po_2p85 l=5.6",
            f"X{tag}_rp2 vdd {qp} vss sky130_fd_pr__res_high_po_2p85 l=5.6",
            f"X{tag}_rn1 vdd {qn} vss sky130_fd_pr__res_high_po_2p85 l=5.6",
            f"X{tag}_rn2 vdd {qn} vss sky130_fd_pr__res_high_po_2p85 l=5.6",
            f"X{tag}_dp {qp} {dp} {tag}_strk vss sky130_fd_pr__nfet_01v8_lvt w=16.0 l=0.15 nf=4",
            f"X{tag}_dn {qn} {dn} {tag}_strk vss sky130_fd_pr__nfet_01v8_lvt w=16.0 l=0.15 nf=4",
            f"X{tag}_hp {qp} {qn} {tag}_shld vss sky130_fd_pr__nfet_01v8_lvt w=14.0 l=0.15 nf=4",
            f"X{tag}_hn {qn} {qp} {tag}_shld vss sky130_fd_pr__nfet_01v8_lvt w=14.0 l=0.15 nf=4",
            f"X{tag}_ckp {tag}_strk {ckp} {tag}_tail vss sky130_fd_pr__nfet_01v8_lvt w=20.0 l=0.15 nf=4",
            f"X{tag}_ckn {tag}_shld {ckn} {tag}_tail vss sky130_fd_pr__nfet_01v8_lvt w=20.0 l=0.15 nf=4",
            f"X{tag}_tail {tag}_tail vbias_d vss vss sky130_fd_pr__nfet_01v8 w=36.0 l=0.35 nf=8",
        ])
    lines.append(f".ends {cell_name}\n")
    return "\n".join(lines)


def rot90_cell(src: Cell) -> Cell:
    out = Cell()
    for lyr, rects in src.rects.items():
        for x1, y1, x2, y2 in rects:
            out.rect(lyr, grid(-y2), grid(x1), grid(-y1), grid(x2))
    for lyr, x, y, nm in src.labels:
        out.labels.append((lyr, grid(-y), grid(x), nm))
    return out


def place_mos(
    c: Cell, cache: PdkCache, cx: float, dy: float, model: str, w_tot: float, l_f: float, nf: int,
    is_pmos: bool, y_gate: float, s_y: float, d_y: float, sd_w: float = 0.28,
) -> dict:
    cx, dy, y_gate, s_y, d_y = grid(cx), grid(dy), grid(y_gate), grid(s_y), grid(d_y)
    w_f = grid(w_tot / nf)
    mos, info = cache.build_mos(model, w_f, l_f, nf, dy, is_pmos)
    c.include(mos, dx=cx, dy=0.0)
    tie_mos_gates(c, cx, info, y_bar=y_gate, y_cont=y_gate, tap_xs=[cx])
    if nf >= 2:
        hw = grid(l_f / 2.0)
        gxs = [grid(cx + g) for g in info["g_xs"]]
        c.rect("poly", grid(min(gxs[0] - hw, cx - 0.135)), grid(y_gate - 0.170),
               grid(max(gxs[-1] + hw, cx + 0.135)), grid(y_gate + 0.170))
    s_xs = [grid(cx + x) for x in info["s_xs"]]
    d_xs = [grid(cx + x) for x in info["d_xs"]]
    c_y1, c_y2 = info["c_y1"], info["c_y2"]
    for xs, py in ((s_xs, s_y), (d_xs, d_y)):
        for x in xs:
            locali_v(c, x, min(c_y1, py - 0.085), max(c_y2, py + 0.085))
            viali_pad(c, x, py)
        if len(xs) > 1:
            c.wire("metal1", [(xs[0], py), (xs[-1], py)], sd_w)
    return {
        "cx": cx, "dy": dy, "g": (cx, y_gate),
        "s": (grid(0.5 * (s_xs[0] + s_xs[-1])), s_y),
        "d": (grid(0.5 * (d_xs[0] + d_xs[-1])), d_y),
        "s_xs": s_xs, "d_xs": d_xs,
        "x1": grid(cx + info["diff_x1"]), "x2": grid(cx + info["diff_x2"]),
        "y1": info["diff_y1"], "y2": info["diff_y2"],
    }


def place_mim(c: Cell, cache: PdkCache, cx: float, cy: float, w: float, l: float) -> dict:
    cx, cy = grid(cx), grid(cy)
    m = cache.device(MIM1, dict(w=w, l=l))
    b = m.bbox()
    c.include(m, dx=cx, dy=cy)
    v3_xs = [0.5 * (r[0] + r[2]) for r in m.rects["via3"]]
    v3_x = grid(cx + sum(v3_xs) / len(v3_xs))
    m4_top_rects = [r for r in m.rects["metal4"] if (r[2] - r[0]) > 1.0]
    tx1 = min(r[0] for r in m4_top_rects)
    tx2 = max(r[2] for r in m4_top_rects)
    top_x = grid(cx + 0.5 * (tx1 + tx2))
    return {
        "top_m4": (top_x, cy), "top_x1": grid(cx + tx1), "top_x2": grid(cx + tx2),
        "bot_m4": (v3_x, cy),
        "bot_m3_l": (grid(cx + b[0] + 0.30), cy),
        "bot_m3_r": (grid(cx + b[2] - 0.30), cy),
        "bot_m3_b": (cx, grid(cy + b[1] + 0.30)),
        "bot_m3_t": (cx, grid(cy + b[3] - 0.30)),
        "bbox": (grid(cx + b[0]), grid(cy + b[1]), grid(cx + b[2]), grid(cy + b[3])),
    }


def place_res(c: Cell, cache: PdkCache, model: str, length: float, cx: float, cy: float, horiz: bool = False) -> dict:
    cx, cy = grid(cx), grid(cy)
    raw = cache.device(model, dict(l=length))
    dev = rot90_cell(raw) if horiz else raw
    b = dev.bbox()
    c.include(dev, dx=cx, dy=cy)
    m1 = dev.rects["metal1"]
    if not horiz:
        pos = [r for r in m1 if 0.5 * (r[1] + r[3]) > 0]
        neg = [r for r in m1 if 0.5 * (r[1] + r[3]) < 0]
        p_hi = (cx, grid(cy + 0.5 * (min(r[1] for r in pos) + max(r[3] for r in pos))))
        p_lo = (cx, grid(cy + 0.5 * (min(r[1] for r in neg) + max(r[3] for r in neg))))
        sub_pts = [
            (grid(cx + b[0] + 0.30), grid(cy + b[1] + 0.265)),
            (grid(cx + b[0] + 0.30), grid(cy + b[3] - 0.265)),
            (grid(cx + b[2] - 0.30), grid(cy + b[1] + 0.265)),
            (grid(cx + b[2] - 0.30), grid(cy + b[3] - 0.265)),
        ]
        return {"hi": p_hi, "lo": p_lo, "sub": sub_pts, "bbox": (grid(cx + b[0]), grid(cy + b[1]), grid(cx + b[2]), grid(cy + b[3]))}
    else:
        pos = [r for r in m1 if 0.5 * (r[0] + r[2]) > 0]
        neg = [r for r in m1 if 0.5 * (r[0] + r[2]) < 0]
        p_r = (grid(cx + 0.5 * (min(r[0] for r in pos) + max(r[2] for r in pos))), cy)
        p_l = (grid(cx + 0.5 * (min(r[0] for r in neg) + max(r[2] for r in neg))), cy)
        sub_pts = [
            (grid(cx + b[0] + 0.265), grid(cy + b[1] + 0.30)),
            (grid(cx + b[0] + 0.265), grid(cy + b[3] - 0.30)),
            (grid(cx + b[2] - 0.265), grid(cy + b[1] + 0.30)),
            (grid(cx + b[2] - 0.265), grid(cy + b[3] - 0.30)),
        ]
        return {"left": p_l, "right": p_r, "sub": sub_pts, "bbox": (grid(cx + b[0]), grid(cy + b[1]), grid(cx + b[2]), grid(cy + b[3]))}


def place_varactor_6f(c: Cell, cache: PdkCache, cx: float, cy: float) -> dict:
    cx, cy = grid(cx), grid(cy)
    v = cache.device(VAR_LVT, dict(w=5.2, l=0.5, nf=6, guard=0))
    c.include(v, dx=cx, dy=cy)
    c.rect("nwell", grid(cx - 8.75), grid(cy - 3.28), grid(cx + 8.75), grid(cy + 3.28))
    gx1, gx2 = grid(cx - 9.45), grid(cx + 9.45)
    gy1, gy2 = grid(cy - 3.98), grid(cy + 3.98)
    draw_tap_h(c, "psubdiff", gx1, gx2, gy2, with_m1=True, m1_w=0.40)
    draw_tap_h(c, "psubdiff", gx1, gx2, gy1, with_m1=True, m1_w=0.40)
    draw_tap_v(c, "psubdiff", gx1, gy1, gy2, with_m1=True, m1_w=0.40)
    draw_tap_v(c, "psubdiff", gx2, gy1, gy2, with_m1=True, m1_w=0.40)
    gx_l, gx_r = grid(cx - 7.75), grid(cx + 7.75)
    gy_t, gy_b = grid(cy + 2.875), grid(cy - 2.875)
    c.wire("metal1", [(gx_l, gy_t), (gx_r, gy_t)], 0.24)
    c.wire("metal1", [(gx_l, gy_b), (gx_r, gy_b)], 0.24)
    c.wire("metal1", [(grid(cx - 8.35), cy), (grid(cx + 8.35), cy)], 0.44)
    return {
        "gate_top": (cx, gy_t), "gate_bot": (cx, gy_b), "vctrl": (cx, cy),
        "sub_l": (gx1, cy), "sub_r": (gx2, cy), "sub_bot": (cx, gy1),
        "bbox": (grid(gx1 - 0.20), grid(gy1 - 0.20), grid(gx2 + 0.20), grid(gy2 + 0.20)),
    }


def m1_to_m3(c: Cell, x: float, y: float) -> None:
    via1_clean(c, x, y)
    via2_clean(c, x, y)


def m1_to_m4(c: Cell, x: float, y: float) -> None:
    via1_clean(c, x, y)
    via2_clean(c, x, y)
    via3_pad(c, x, y)


def m2_to_m3(c: Cell, x: float, y: float) -> None:
    via2_clean(c, x, y)


# ---------------------------------------------------------------------------
# Ultra-Low-Profile 2-Band Active LC-VCO + Quadrature CML /2 (`vco5g_lc_active_div2_pdk`)
# ---------------------------------------------------------------------------

def build_active_div2_cell(cache: PdkCache, *, unified: bool = False, variant: str | None = None) -> tuple[Cell, dict]:
    c = Cell()
    v = variant or ("unified" if unified else "oct")
    unified = v in ("unified", "oct")
    capw = {"legacy": 4.2, "unified": 4.0, "oct": 3.6}[v]
    wt, nft = (60.0, 12) if unified else (80.0, 16)

    # Full inductor-matched width (~238 um) x ultra-short height (~104 um, -42% height vs v1!)
    X_VDD_L, X_VDD_R = -118.0, 118.0
    X_VSS_L, X_VSS_R = -114.5, 114.5
    Y_TOP = 32.0
    Y_BOT = -70.0

    for xv in (X_VDD_L, X_VDD_R):
        c.wire("metal4", [(xv, Y_BOT), (xv, Y_TOP)], 2.20)
    for xv in (X_VSS_L, X_VSS_R):
        c.wire("metal4", [(xv, Y_BOT), (xv, Y_TOP)], 2.20)
    c.wire("metal3", [(X_VDD_L, Y_TOP), (X_VDD_R, Y_TOP)], 1.80)
    c.wire("metal3", [(X_VSS_L, Y_BOT), (X_VSS_R, Y_BOT)], 1.80)
    for xv in (X_VDD_L, X_VDD_R):
        via3_pad(c, xv, Y_TOP)
        via3_pad(c, xv, Y_TOP - 0.60)
    for xv in (X_VSS_L, X_VSS_R):
        via3_pad(c, xv, Y_BOT)
        via3_pad(c, xv, Y_BOT + 0.60)

    # =========================================================================
    # BAND 1 CENTER (|x| <= 66, y = -23 .. +30.5): -gm Core + Varactors + Fixed MIM + 15u Bank
    # =========================================================================
    is_oct = (v == "oct")
    Y_TANK_M4 = 28.5
    Y_CORE_P = 22.0
    Y_CORE_N = 14.8
    x_core = 12.8 if is_oct else 10.0
    x_drain = 19.0 if is_oct else 16.0

    mp1 = place_mos(c, cache, -x_core, Y_CORE_P, P_LVT, 64.0, 0.35, 16, True,
                    y_gate=18.60, s_y=23.60, d_y=20.40, sd_w=0.44)
    mp2 = place_mos(c, cache, +x_core, Y_CORE_P, P_LVT, 64.0, 0.35, 16, True,
                    y_gate=18.60, s_y=23.60, d_y=20.40, sd_w=0.44)
    mn1 = place_mos(c, cache, -x_core, Y_CORE_N, N_LVT, 40.0, 0.15, 16, False,
                    y_gate=17.20, s_y=13.85, d_y=15.75, sd_w=0.44)
    mn2 = place_mos(c, cache, +x_core, Y_CORE_N, N_LVT, 40.0, 0.15, 16, False,
                    y_gate=17.20, s_y=13.85, d_y=15.75, sd_w=0.44)

    x_nw = 20.5 if is_oct else 20.8
    x_ntap = 19.5 if is_oct else 19.8
    c.rect("nwell", -x_nw, 19.30, +x_nw, 26.10)
    draw_tap_h(c, "nsubdiff", -x_ntap, +x_ntap, 25.20, with_m1=True, m1_w=0.50)
    for mp in (mp1, mp2):
        for sx in mp["s_xs"][::2]:
            c.wire("metal1", [(sx, 23.60), (sx, 25.20)], 0.24)
    for xv in ((-14.0, 0.0, 14.0) if is_oct else (-18.0, 0.0, 18.0)):
        via1_clean(c, xv, 25.20)
        c.wire("metal2", [(xv, 25.20), (xv, Y_TOP)], 0.80)
        m2_to_m3(c, xv, Y_TOP)

    # Row 1 local VSS M3 rail (only spanning |x| <= 70.5 so it NEVER touches Xctail/Xcf_t in the wings!)
    # Connects straight down on vertical M3 at x = +-70.5 to Bank VSS & Band 2 VSS!
    X_VSS_INN = 70.5
    if is_oct:
        # Place `Xtail` dead-center at (0.0, 14.0) directly between Xmn1 (-12.8) and Xmn2 (+12.8)!
        # Cuts high-Z `tail` trace from ~107 um (27.1 fF) down to a symmetric <4 um collinear bar!
        xtail = place_mos(c, cache, 0.0, 14.0, N_STD, wt, 0.50, nft, False,
                          y_gate=10.60, s_y=12.15, d_y=13.85, sd_w=0.56)
        # Unified psubdiff tap at y=9.20 directly beneath Xtail + Xmn1/2 -> M1 North at x=+-21.0 to Row 1 VSS M3 (12.50)!
        draw_tap_h(c, "psubdiff", -21.0, +21.0, 9.20, with_m1=True, m1_w=0.50)
        for sx in xtail["s_xs"][::2]:
            via1_clean(c, sx, 12.15)
            via1_clean(c, sx, 9.20)
            c.wire("metal2", [(sx, 9.20), (sx, 12.15)], 0.36)
        for sgn in (-1.0, +1.0):
            xv = sgn * 21.0
            c.wire("metal1", [(xv, 9.20), (xv, 12.50)], 0.50)
            m1_to_m3(c, xv, 12.50)
        c.wire("metal3", [(-X_VSS_INN, 12.50), (-21.0, 12.50)], 0.80)
        c.wire("metal3", [(+21.0, 12.50), (+X_VSS_INN, 12.50)], 0.80)
        # Collinear mirror-symmetric `tail` bar at y = 13.85 joining Xmn1.s <-> Xtail.d <-> Xmn2.s!
        c.wire("metal1", [(mn1["s_xs"][0], 13.85), (mn2["s_xs"][-1], 13.85)], 0.56)
        for xv in (-15.0, -10.5, -3.5, 0.0, +3.5, +10.5, +15.0):
            via1_clean(c, xv, 13.85)
        c.wire("metal2", [(-15.0, 13.85), (+15.0, 13.85)], 0.80)
    else:
        draw_tap_h(c, "psubdiff", -19.8, 19.8, 12.50, with_m1=True, m1_w=0.50)
        c.wire("metal3", [(-X_VSS_INN, 12.50), (-19.2, 12.50)], 0.80)
        c.wire("metal3", [(19.2, 12.50), (+X_VSS_INN, 12.50)], 0.80)
        for xv in (-19.2, 19.2):
            m1_to_m3(c, xv, 12.50)
        # `tail` M1/M2 bus at y = 13.85
        c.wire("metal1", [(mn1["s_xs"][0], 13.85), (mn2["s_xs"][-1], 13.85)], 0.48)
        for xv in (-13.0, -7.0, 7.0, 13.0):
            via1_clean(c, xv, 13.85)
        c.wire("metal2", [(-13.0, 13.85), (13.0, 13.85)], 0.80)

    # Cross-coupled drains & gates at x = +-x_drain
    c.wire("metal1", [(-x_core, 17.20), (-x_core, 18.60)], 0.36)
    c.wire("metal1", [(+x_core, 17.20), (+x_core, 18.60)], 0.36)
    for x_d, mp, mn in ((-x_drain, mp1, mn1), (+x_drain, mp2, mn2)):
        c.wire("metal1", [(x_d, 20.40), (mp["d"][0], 20.40)], 0.44)
        c.wire("metal1", [(x_d, 15.75), (mn["d"][0], 15.75)], 0.44)
        via1_clean(c, x_d, 20.40)
        via1_clean(c, x_d, 15.75)
        c.wire("metal2", [(x_d, 15.75), (x_d, Y_TANK_M4)], 1.20)
        m2_to_m3(c, x_d, Y_TANK_M4)
        via3_pad(c, x_d, Y_TANK_M4)
    m2_to_m3(c, -x_drain, 18.60)
    c.wire("metal3", [(-x_drain, 18.60), (+x_core, 18.60)], 0.48)
    m1_to_m3(c, +x_core, 18.60)
    m2_to_m3(c, +x_drain, 17.20)
    c.wire("metal3", [(-x_core, 17.20), (+x_drain, 17.20)], 0.48)
    m1_to_m3(c, -x_core, 17.20)

    # Differential 6-finger accumulation varactors at x = +-32.5, y = 20.2
    varp = place_varactor_6f(c, cache, -32.5, 20.2)
    varn = place_varactor_6f(c, cache, +32.5, 20.2)
    Y_VCTRL_BUS = 26.60
    for v_info, sgn in ((varp, -1.0), (varn, +1.0)):
        vx = v_info["gate_top"][0]
        xg = grid(vx + sgn * 3.10)
        m1_to_m4(c, xg, v_info["gate_top"][1])
        c.wire("metal4", [(xg, v_info["gate_top"][1]), (xg, Y_TANK_M4)], 0.80)
        gx_tie = grid(vx + sgn * 7.75)
        via1_clean(c, gx_tie, v_info["gate_top"][1])
        via1_clean(c, gx_tie, v_info["gate_bot"][1])
        c.wire("metal2", [(gx_tie, v_info["gate_bot"][1]), (gx_tie, v_info["gate_top"][1])], 0.36)
        sx_g = v_info["sub_l"][0] if sgn < 0 else v_info["sub_r"][0]
        c.wire("metal1", [(sx_g, 12.50), (sx_g, v_info["sub_bot"][1])], 0.44)
        m1_to_m3(c, sx_g, 12.50)
        via1_clean(c, vx, v_info["vctrl"][1])
        c.wire("metal2", [(vx, v_info["vctrl"][1]), (vx, Y_VCTRL_BUS)], 0.44)
        m2_to_m3(c, vx, Y_VCTRL_BUS)
    # `vctrl` runs East-West on M3 across center [-68..+32.5], then switches to M2 at x=-68.0 to pass cleanly UNDER Xctail!
    c.wire("metal3", [(-68.0, Y_VCTRL_BUS), (+32.5, Y_VCTRL_BUS)], 0.50)
    m2_to_m3(c, -68.0, Y_VCTRL_BUS)
    c.wire("metal2", [(-111.0, Y_VCTRL_BUS), (-68.0, Y_VCTRL_BUS)], 0.50)

    # Fixed MIM centering caps at x = +-47.5, y = 20.2 (omitted in unified variant to center 5.0 GHz mid-bank!)
    if not unified:
        cfix_p = place_mim(c, cache, -47.5, 20.2, 3.0, 3.0)
        cfix_n = place_mim(c, cache, +47.5, 20.2, 3.0, 3.0)
        for cf in (cfix_p, cfix_n):
            tx, ty = cf["top_m4"]
            c.wire("metal4", [(tx, ty), (tx, Y_TANK_M4)], 0.80)
            bx, by = cf["bot_m3_b"]
            c.wire("metal3", [(bx, 12.50), (bx, by)], 0.60)

    # Top horizontal M4 tank distribution rails at y = 28.5
    X_TANK_V = 66.8
    x_tank_in = 14.0 if is_oct else 16.0
    c.wire("metal4", [(-X_TANK_V, Y_TANK_M4), (-x_tank_in, Y_TANK_M4)], 1.60)
    c.wire("metal4", [(+x_tank_in, Y_TANK_M4), (+X_TANK_V, Y_TANK_M4)], 1.60)

    # 15-unit Common-Centroid 4-Bit Bank (y = -22.7 .. +10.2, PITCH_B = 8.4 -> x in [-58.8..+58.8])
    Y_VP_BANK_M4 = 10.20
    Y_MIM_P = 6.20
    Y_SP_V2 = 2.15
    Y_BANK_VSS = 0.65
    Y_BANK_N = -2.25
    Y_BITS = {0: -5.30, 1: -6.20, 2: -7.10, 3: -8.00}
    Y_BANK_P = -11.20
    Y_BANK_VDD = -12.85
    Y_SN_V2 = -14.70
    Y_MIM_N = -18.70
    Y_VN_BANK_M4 = -22.70

    PITCH_B = 8.4
    XS_BANK = [grid((i - 7) * PITCH_B) for i in range(15)]

    c.rect("nwell", XS_BANK[0] - 5.2, -13.80, XS_BANK[-1] + 5.2, -9.00)
    draw_tap_h(c, "psubdiff", XS_BANK[0] - 4.7, XS_BANK[-1] + 4.7, Y_BANK_VSS, with_m1=True, m1_w=0.44)
    draw_tap_h(c, "nsubdiff", XS_BANK[0] - 4.7, XS_BANK[-1] + 4.7, Y_BANK_VDD, with_m1=True, m1_w=0.44)
    for xv in (XS_BANK[0] - 4.4, XS_BANK[-1] + 4.4):
        m1_to_m3(c, xv, Y_BANK_VSS)
        m1_to_m3(c, xv, Y_BANK_VDD)

    # Vertical inner VSS M3 alleys at x = +-X_VSS_INN (+-70.5): M3 from y=+12.5 down to y=-21.0 (zero conflict
    # with b0..b3 M2 at -5.3..-8.0!), then drop cleanly on M2 from y=-24.0..Y_LATCH_VSS (-56.80) (zero conflict with M3 buses!).
    # Wait: pass vbias_f (M2 at -22.50) via M3 at x=+-70.5 -> keep X_VSS_INN on M3 down to y=-24.0 and switch to M2 at y=-24.0!
    # Vertical Bank VDD tie at x = +-64.2 uses M3 from Y_BANK_VDD (-12.85) down to Y_LATCH_VDD (-26.0) -> 0 conflict with vbias_f M2!
    for sgn in (-1.0, +1.0):
        xi = sgn * X_VSS_INN
        xb_end = XS_BANK[0] - 4.4 if sgn < 0 else XS_BANK[-1] + 4.4
        c.wire("metal3", [(min(xi, xb_end), Y_BANK_VSS), (max(xi, xb_end), Y_BANK_VSS)], 0.80)
        x_vdd_drop = grid(sgn * 64.2)
        c.wire("metal3", [(min(xb_end, x_vdd_drop), Y_BANK_VDD), (max(xb_end, x_vdd_drop), Y_BANK_VDD)], 0.60)
        c.wire("metal3", [(x_vdd_drop, -26.0), (x_vdd_drop, Y_BANK_VDD)], 0.60)

    # `b0..b3`: M3 inside Bank [-67.5..+61.3], drop to M2 at x = -67.5 and run West UNDER Xctail to West port x = -111.0!
    for bk, yb in Y_BITS.items():
        c.wire("metal3", [(-67.5, yb), (XS_BANK[-1] + 2.5, yb)], 0.34)
        m2_to_m3(c, -67.5, yb)
        c.wire("metal2", [(-111.0, yb), (-67.5, yb)], 0.34)

    # Bank M4 buses + vertical tank trunks at x = +-X_TANK_V (+-66.8)
    c.wire("metal4", [(-X_TANK_V, Y_VP_BANK_M4), (+62.0, Y_VP_BANK_M4)], 1.40)
    c.wire("metal4", [(-62.0, Y_VN_BANK_M4), (+X_TANK_V, Y_VN_BANK_M4)], 1.40)
    c.wire("metal4", [(-X_TANK_V, Y_VP_BANK_M4), (-X_TANK_V, Y_TANK_M4)], 1.50)
    c.wire("metal4", [(+X_TANK_V, Y_VN_BANK_M4), (+X_TANK_V, Y_TANK_M4)], 1.50)

    for idx, (xc, bit) in enumerate(zip(XS_BANK, BANK_BIT_MAP)):
        mp_cap = place_mim(c, cache, xc, Y_MIM_P, capw, capw)
        mn_cap = place_mim(c, cache, xc, Y_MIM_N, capw, capw)
        c.wire("metal4", [(mp_cap["top_m4"][0], mp_cap["top_m4"][1]), (mp_cap["top_m4"][0], Y_VP_BANK_M4)], 0.80)
        c.wire("metal4", [(mn_cap["top_m4"][0], Y_VN_BANK_M4), (mn_cap["top_m4"][0], mn_cap["top_m4"][1])], 0.80)

        sw = place_mos(c, cache, xc - 2.0, Y_BANK_N, N_LVT, 16.0, 0.15, 4, False,
                       y_gate=-4.65, s_y=-0.85, d_y=-3.65, sd_w=0.34)
        onp = place_mos(c, cache, xc + 1.0, Y_BANK_N, N_STD, 1.0, 0.50, 1, False,
                        y_gate=-4.65, s_y=-1.45, d_y=-3.05, sd_w=0.22)
        onn = place_mos(c, cache, xc + 2.6, Y_BANK_N, N_STD, 1.0, 0.50, 1, False,
                        y_gate=-4.65, s_y=-1.45, d_y=-3.05, sd_w=0.22)
        offp = place_mos(c, cache, xc + 1.0, Y_BANK_P, P_STD, 1.0, 0.50, 1, True,
                         y_gate=-9.75, s_y=-11.90, d_y=-10.50, sd_w=0.22)
        offn = place_mos(c, cache, xc + 2.6, Y_BANK_P, P_STD, 1.0, 0.50, 1, True,
                         y_gate=-9.75, s_y=-11.90, d_y=-10.50, sd_w=0.22)

        c.wire("metal1", [(onp["s"][0], -1.45), (onp["s"][0], Y_BANK_VSS)], 0.22)
        c.wire("metal1", [(onn["s"][0], -1.45), (onn["s"][0], Y_BANK_VSS)], 0.22)
        c.wire("metal1", [(offp["s"][0], -11.90), (offp["s"][0], Y_BANK_VDD)], 0.22)
        c.wire("metal1", [(offn["s"][0], -11.90), (offn["s"][0], Y_BANK_VDD)], 0.22)

        c.wire("metal1", [(sw["g"][0], -4.65), (onn["g"][0], -4.65)], 0.24)
        c.wire("metal1", [(xc - 2.0, -9.75), (offn["g"][0], -9.75)], 0.24)
        via1_clean(c, xc - 2.0, -4.65)
        via1_clean(c, xc - 2.0, -9.75)
        c.wire("metal2", [(xc - 2.0, -9.75), (xc - 2.0, -4.65)], 0.30)
        via2_clean(c, xc - 2.0, Y_BITS[bit])

        x_sp = grid(xc + 0.05)
        x_sn = grid(xc + 3.45)
        c.wire("metal3", [(x_sp, mp_cap["bot_m3_b"][1]), (x_sp, Y_SP_V2)], 0.36)
        m2_to_m3(c, x_sp, Y_SP_V2)
        c.wire("metal2", [(x_sp, -10.50), (x_sp, Y_SP_V2)], 0.34)
        c.wire("metal1", [(sw["s_xs"][-1], -0.85), (x_sp, -0.85)], 0.28)
        via1_clean(c, x_sp, -0.85)
        c.wire("metal1", [(x_sp, -3.05), (onp["d"][0], -3.05)], 0.24)
        via1_clean(c, x_sp, -3.05)
        c.wire("metal1", [(x_sp, -10.50), (offp["d"][0], -10.50)], 0.24)
        via1_clean(c, x_sp, -10.50)

        c.wire("metal3", [(mn_cap["bot_m3_t"][0], mn_cap["bot_m3_t"][1]), (mn_cap["bot_m3_t"][0], Y_SN_V2), (x_sn, Y_SN_V2)], 0.36)
        m2_to_m3(c, x_sn, Y_SN_V2)
        c.wire("metal2", [(x_sn, Y_SN_V2), (x_sn, -3.05)], 0.34)
        c.wire("metal1", [(sw["d_xs"][-1], -3.65), (x_sn, -3.65)], 0.28)
        via1_clean(c, x_sn, -3.65)
        c.wire("metal1", [(onn["d"][0], -3.05), (x_sn, -3.05)], 0.24)
        via1_clean(c, x_sn, -3.05)
        c.wire("metal1", [(offn["d"][0], -10.50), (x_sn, -10.50)], 0.24)
        via1_clean(c, x_sn, -10.50)

    # =========================================================================
    # BAND 1 WEST WING (x in [-112..-72], y = -22..+26): 2 pF `Xctail` + `Xtail`!
    # =========================================================================
    # `Xctail` (34.16 x 32.40) at (-93.5, +9.0) -> x in [-110.58..-76.42], y in [-7.20..+25.20]
    # Note: y_top = 25.20 is 1.4 um below Y_VCTRL_BUS (M2 at 26.60); M2 b0..b3 pass cleanly underneath at y=-5.3..-8.0!
    ctail = place_mim(c, cache, -93.5, 9.0, 32.0, 32.0)
    c.wire("metal3", [(X_VSS_L, 9.0), (ctail["bot_m3_l"][0], 9.0)], 1.20)
    via3_pad(c, X_VSS_L, 9.0)

    if is_oct:
        # `Xtail` is now placed dead-center at (0.0, 14.0) between Xmn1/Xmn2!
        # West Wing cleanly hosts the 2 pF local VDD-VSS decoupling cap `Xctail` (top M4 North to Y_TOP VDD M3 rail).
        tx_c = ctail["top_m4"][0]
        c.wire("metal4", [(tx_c, 22.0), (tx_c, Y_TOP)], 2.40)
        for dx_v in (-0.80, 0.0, +0.80):
            via3_pad(c, grid(tx_c + dx_v), Y_TOP)
    else:
        # `Xtail` tucked directly BELOW `Xctail` at (-93.5, -14.8)!
        xtail = place_mos(c, cache, -93.5, -14.8, N_STD, wt, 0.50, nft, False,
                          y_gate=-18.40, s_y=-16.60, d_y=-13.00, sd_w=0.60)
        draw_tap_h(c, "psubdiff", -104.0, -83.0, -20.00, with_m1=True, m1_w=0.50)
        for sx in xtail["s_xs"][::2]:
            via1_clean(c, sx, -16.60)
            via1_clean(c, sx, -20.00)
            c.wire("metal2", [(sx, -20.00), (sx, -16.60)], 0.34)
        # Tie Xtail VSS tap (-20.00) straight West to X_VSS_L (-114.5) on M3!
        m1_to_m3(c, -103.5, -20.00)
        c.wire("metal3", [(X_VSS_L, -20.00), (-103.5, -20.00)], 0.90)
        via3_pad(c, X_VSS_L, -20.00)

        if unified:
            # Unified Option B: Repurpose 2 pF `Xctail` as local VDD-VSS decoupling cap (top M4 North to Y_TOP VDD M3 rail!)
            tx_c = ctail["top_m4"][0]
            c.wire("metal4", [(tx_c, 22.0), (tx_c, Y_TOP)], 2.40)
            for dx_v in (-0.80, 0.0, +0.80):
                via3_pad(c, grid(tx_c + dx_v), Y_TOP)
            # Clean high-Z `tail` route directly from Xtail.d (-13.00) East -> x=-73.5 M4 North -> y=+13.85 M2 East to Xmn1/2.s!
            d_vias = sorted({xtail["d_xs"][0], xtail["cx"], xtail["d_xs"][-1]})
            for xv in d_vias:
                m1_to_m4(c, xv, -13.00)
            c.wire("metal4", [(d_vias[0], -13.00), (-73.5, -13.00), (-73.5, 13.85)], 1.20)
            via3_pad(c, -73.5, 13.85)
            via2_clean(c, -73.5, 13.85)
            c.wire("metal2", [(-73.5, 13.85), (-13.0, 13.85)], 1.00)
        else:
            # Legacy Option A: `tail` shorted to `Xctail` top_m4
            for xv in (-98.5, -93.5, -88.5):
                m1_to_m4(c, xv, -13.00)
            c.wire("metal4", [(-98.5, -13.00), (-88.5, -13.00)], 0.80)
            c.wire("metal4", [(ctail["top_m4"][0], -13.00), (ctail["top_m4"][0], 13.85)], 1.40)
            c.wire("metal4", [(ctail["top_m4"][0], 13.85), (ctail["top_m4"][0], 26.80), (-73.5, 26.80), (-73.5, 13.85)], 1.30)
            via3_pad(c, -73.5, 13.85)
            via2_clean(c, -73.5, 13.85)
            c.wire("metal2", [(-73.5, 13.85), (-13.0, 13.85)], 1.00)

    # =========================================================================
    # BAND 1 EAST WING (x in [+72..+112], y = -22..+26): `Xcf_t` + VCO Bias + CML Div2 Bias!
    # =========================================================================
    # `Xcf_t` (24.16 x 22.40) at (+98.5, +14.5) -> x in [+86.42..+110.58], y in [+3.30..+25.70]
    cft = place_mim(c, cache, 98.5, 14.5, 22.0, 22.0)
    c.wire("metal3", [(cft["bot_m3_r"][0], 14.5), (X_VSS_R, 14.5)], 1.00)
    via3_pad(c, X_VSS_R, 14.5)

    # `Xrbias` (+75.0, +15.0) & `Xrf_t` (+80.5, +15.0) vertical right beside Xcf_t; `Xnbias` (+77.5, +1.5) below them!
    rbias = place_res(c, cache, R_1P41, 9.8, 75.0, 15.0, horiz=False)
    rft = place_res(c, cache, R_1P41, 10.0, 80.5, 15.0, horiz=False)
    nbias = place_mos(c, cache, 77.5, 1.5, N_STD, 6.0, 0.50, 2, False,
                      y_gate=3.90, s_y=0.50, d_y=2.50, sd_w=0.30)
    draw_tap_h(c, "psubdiff", 72.5, 83.5, -1.20, with_m1=True, m1_w=0.44)
    for sx in nbias["s_xs"]:
        c.wire("metal1", [(sx, 0.50), (sx, -1.20)], 0.24)
    for res_d in (rbias, rft):
        for sx, sy in res_d["sub"][:2]:
            viali_pad(c, sx, sy)
            via1_clean(c, sx, sy)
            c.wire("metal2", [(sx, -1.20), (sx, sy)], 0.28)
            via1_clean(c, sx, -1.20)
    # Tie Xnbias VSS tap (-1.20) straight West to X_VSS_INN (+70.5)
    m1_to_m3(c, 73.0, -1.20)
    c.wire("metal3", [(+X_VSS_INN, -1.20), (73.0, -1.20)], 0.60)
    # Xrbias.hi -> VDD M3 up to Y_TOP = +32.0!
    m1_to_m3(c, rbias["hi"][0], rbias["hi"][1])
    c.wire("metal3", [(rbias["hi"][0], rbias["hi"][1]), (rbias["hi"][0], Y_TOP)], 0.50)
    # `vbias_lc`: rbias.lo -> rft.lo -> nbias.d + nbias.g
    y_lc = min(rbias["lo"][1], rft["lo"][1])
    c.wire("metal1", [(rbias["lo"][0], rbias["lo"][1]), (rbias["lo"][0], y_lc), (rft["lo"][0], y_lc), (rft["lo"][0], rft["lo"][1])], 0.34)
    c.wire("metal1", [(77.5, y_lc), (77.5, 2.50)], 0.34)
    c.wire("metal1", [(77.5, 3.90), (77.5, 2.50)], 0.34)
    # `vbias_f`: rft.hi -> Xcf_t top_m4 (strictly from WEST!) AND to Xtail.g!
    m1_to_m4(c, rft["hi"][0], rft["hi"][1])
    c.wire("metal4", [(rft["hi"][0], rft["hi"][1]), (rft["hi"][0], 14.5), (cft["top_m4"][0], 14.5)], 0.60)
    via1_clean(c, rft["hi"][0], rft["hi"][1])
    if is_oct:
        # Direct short `vbias_f` to centered Xtail.g (0.0, 10.60), strictly clear of Y_VP_BANK_M4 (y<=10.90, x<=62.0)!
        # M2 East -> x=83.8 South to y=10.60 -> M4 West across [72.0..83.8] (clears rbias/rft sub M2!)
        # -> M2 North to y=14.00 (clears Y_VP_BANK_M4 by 3.1 um & varn by 2.0 um!) -> West to x=22.5 -> step to y=11.65 -> (+6.4, 11.65) -> M1 to (0.0, 10.60)
        c.wire("metal2", [(rft["hi"][0], rft["hi"][1]), (83.8, rft["hi"][1]), (83.8, 10.60)], 0.36)
        m2_to_m3(c, 83.8, 10.60)
        via3_pad(c, 83.8, 10.60)
        c.wire("metal4", [(72.0, 10.60), (83.8, 10.60)], 0.44)
        via3_pad(c, 72.0, 10.60)
        m2_to_m3(c, 72.0, 10.60)
        c.wire("metal2", [(72.0, 10.60), (72.0, 14.00), (22.5, 14.00), (22.5, 11.65), (6.4, 11.65)], 0.36)
        via1_clean(c, 6.4, 11.65)
        c.wire("metal1", [(0.0, 10.60), (6.4, 10.60), (6.4, 11.65)], 0.30)
    else:
        c.wire("metal2", [(rft["hi"][0], rft["hi"][1]), (83.8, rft["hi"][1]), (83.8, -22.50), (-82.0, -22.50), (-82.0, -18.40)], 0.34)
        via1_clean(c, -82.0, -18.40)
        c.wire("metal1", [(-93.5, -18.40), (-82.0, -18.40)], 0.30)

    # CML Div2 Bias Diode tucked cleanly BELOW Xcf_t in East Wing (`Xrb1` horiz at (+96, -5.0), `Xnb1` at (+87, -12.5))!
    rb1 = place_res(c, cache, R_1P41, 14.0, 96.0, -5.0, horiz=True)
    nb1 = place_mos(c, cache, 87.0, -12.5, N_STD, 6.0, 0.35, 2, False,
                    y_gate=-10.00, s_y=-13.50, d_y=-11.50, sd_w=0.30)
    draw_tap_h(c, "psubdiff", 83.0, 108.0, -15.60, with_m1=True, m1_w=0.44)
    for sx in nb1["s_xs"]:
        c.wire("metal1", [(sx, -13.50), (sx, -15.60)], 0.24)
    for sx, sy in (rb1["sub"][0], rb1["sub"][2]):
        viali_pad(c, sx, sy)
        via1_clean(c, sx, sy)
        c.wire("metal2", [(sx, -15.60), (sx, sy)], 0.28)
        via1_clean(c, sx, -15.60)
    # Tie nb1 VSS tap (-15.60) straight East to X_VSS_R (+114.5) on M3!
    m1_to_m3(c, 107.0, -15.60)
    c.wire("metal3", [(107.0, -15.60), (X_VSS_R, -15.60)], 0.80)
    via3_pad(c, X_VSS_R, -15.60)
    # rb1.right -> VDD (X_VDD_R at y=-5.0)
    m1_to_m3(c, rb1["right"][0], rb1["right"][1])
    c.wire("metal3", [(rb1["right"][0], -5.0), (X_VDD_R, -5.0)], 0.50)
    via3_pad(c, X_VDD_R, -5.0)
    # `vbias_d`: rb1.left (+87.0, -5.0) -> nb1.g (-10.0) + nb1.d (-11.5) -> M3 East to x=+96.0 -> M2 South to Y_VBIASD (-48.2)!
    Y_VBIASD = -48.20
    c.wire("metal1", [(rb1["left"][0], -5.0), (87.0, -5.0), (87.0, -11.50)], 0.30)
    m1_to_m3(c, 87.0, -11.50)
    c.wire("metal3", [(87.0, -11.50), (96.0, -11.50)], 0.40)
    m2_to_m3(c, 96.0, -11.50)
    c.wire("metal2", [(96.0, Y_VBIASD), (96.0, -11.50)], 0.40)
    m2_to_m3(c, 96.0, Y_VBIASD)
    c.wire("metal3", [(-42.0, Y_VBIASD), (96.0, Y_VBIASD)], 0.44)

    # =========================================================================
    # BAND 2 (y = -68.5 .. -25.0): Compact CML /2 (Side-by-Side Tails!) + 2-Row Mirror CM Resistors
    # =========================================================================
    Y_LATCH_VDD = -26.00
    c.wire("metal3", [(X_VDD_L, Y_LATCH_VDD), (X_VDD_R, Y_LATCH_VDD)], 1.20)
    via3_pad(c, X_VDD_L, Y_LATCH_VDD)
    via3_pad(c, X_VDD_R, Y_LATCH_VDD)

    Y_LATCH_VSS = -56.80
    draw_tap_h(c, "psubdiff", -46.0, 46.0, Y_LATCH_VSS, with_m1=True, m1_w=0.60)
    c.wire("metal3", [(X_VSS_L, Y_LATCH_VSS), (X_VSS_R, Y_LATCH_VSS)], 1.20)
    via3_pad(c, X_VSS_L, Y_LATCH_VSS)
    via3_pad(c, X_VSS_R, Y_LATCH_VSS)
    # Inner VSS alleys (+-X_VSS_INN): M3 from +12.50 down to -24.00 (passes cleanly OVER b0..b3 M2 & vbias_f M2!),
    # then M2 from -24.00 down to Y_LATCH_VSS (-56.80) (passes cleanly UNDER Y_LATCH_VDD, Y_CKP/N, Y_VBIASD M3!)
    for sgn in (-1.0, +1.0):
        xi = sgn * X_VSS_INN
        c.wire("metal3", [(xi, -24.00), (xi, 12.50)], 0.80)
        m2_to_m3(c, xi, -24.00)
        c.wire("metal2", [(xi, Y_LATCH_VSS), (xi, -24.00)], 0.80)
        m2_to_m3(c, xi, Y_LATCH_VSS)
    for xv in (-24.0, -17.5, -11.0, 11.0, 17.5, 24.0):
        m1_to_m3(c, xv, Y_LATCH_VSS)

    # Flanking AC Coupling MIMs Xacp (-56.0, -35.0) & Xacn (+56.0, -35.0) -> bbox y in [-39.2..-30.8], > 4.8 um from Y_LATCH_VDD!
    acp = place_mim(c, cache, -56.0, -35.0, 8.0, 8.0)
    acn = place_mim(c, cache, +56.0, -35.0, 8.0, 8.0)
    # Ultra-short M4 drops from +-X_TANK_V (+-66.8) straight into Xacp/Xacn top_m4!
    c.wire("metal4", [(-X_TANK_V, Y_VP_BANK_M4), (-X_TANK_V, -28.0), (acp["top_m4"][0], -28.0), (acp["top_m4"][0], acp["top_m4"][1])], 1.10)
    c.wire("metal4", [(+X_TANK_V, Y_VN_BANK_M4), (+X_TANK_V, -28.0), (acn["top_m4"][0], -28.0), (acn["top_m4"][0], acn["top_m4"][1])], 1.10)

    # `ckp` & `ckn` M3 buses at y = -42.50 & -44.00 (> 3.3 um south of Xacp/Xacn bottom -39.20 -> 0 capm.11!)
    Y_CKP_BUS = -42.50
    Y_CKN_BUS = -44.00
    c.wire("metal3", [(acp["bot_m3_b"][0], acp["bot_m3_b"][1]), (acp["bot_m3_b"][0], Y_CKP_BUS), (+30.0, Y_CKP_BUS)], 0.60)
    c.wire("metal3", [(acn["bot_m3_b"][0], acn["bot_m3_b"][1]), (acn["bot_m3_b"][0], Y_CKN_BUS), (-30.0, Y_CKN_BUS)], 0.60)

    # Shoulder-to-shoulder Master (`xc = -17.5`) & Slave (`xc = +17.5`) Latches WITH SIDE-BY-SIDE TAIL FETS!
    latch_pins = {}
    for lname, xc, is_master, sgn_out in (("m", -17.5, True, -1.0), ("s", +17.5, False, +1.0)):
        rp1 = place_res(c, cache, R_2P85, 5.6, xc - 8.2, -32.2, horiz=False)
        rp2 = place_res(c, cache, R_2P85, 5.6, xc - 3.0, -32.2, horiz=False)
        rn1 = place_res(c, cache, R_2P85, 5.6, xc + 3.0, -32.2, horiz=False)
        rn2 = place_res(c, cache, R_2P85, 5.6, xc + 8.2, -32.2, horiz=False)
        for rd in (rp1, rp2, rn1, rn2):
            m1_to_m3(c, rd["hi"][0], rd["hi"][1])
            c.wire("metal3", [(rd["hi"][0], rd["hi"][1]), (rd["hi"][0], Y_LATCH_VDD)], 0.50)
        y_rsub = rp1["sub"][1][1]
        c.wire("metal1", [(grid(xc - 11.6), y_rsub), (grid(xc + 11.6), y_rsub)], 0.30)
        for rd in (rp1, rp2, rn1, rn2):
            for sx, sy in (rd["sub"][1], rd["sub"][3]):
                viali_pad(c, sx, sy)
        for sgn in (-1.0, 1.0):
            x_vss_sp = grid(xc + sgn * 11.6)
            via1_clean(c, x_vss_sp, y_rsub)
            c.wire("metal2", [(x_vss_sp, Y_LATCH_VSS), (x_vss_sp, y_rsub)], 0.44)
            m2_to_m3(c, x_vss_sp, Y_LATCH_VSS)

        y_qbar = rp1["lo"][1]  # ~ -36.00
        c.wire("metal1", [(rp1["lo"][0], y_qbar), (rp2["lo"][0], y_qbar)], 0.50)
        c.wire("metal1", [(rn1["lo"][0], y_qbar), (rn2["lo"][0], y_qbar)], 0.50)
        x_qp = grid(xc - 5.60)
        x_qn = grid(xc + 5.60)

        # Diff pairs at y = -44.2 (wf=4.0/3.5 -> y in [-46.2..-42.2])
        xdp = place_mos(c, cache, xc - 7.6, -44.2, N_LVT, 16.0, 0.15, 4, False,
                        y_gate=-41.50, s_y=-45.50, d_y=-42.90, sd_w=0.36)
        xhp = place_mos(c, cache, xc - 2.4, -44.2, N_LVT, 14.0, 0.15, 4, False,
                        y_gate=-41.50, s_y=-45.50, d_y=-42.90, sd_w=0.36)
        xhn = place_mos(c, cache, xc + 2.4, -44.2, N_LVT, 14.0, 0.15, 4, False,
                        y_gate=-41.50, s_y=-45.50, d_y=-42.90, sd_w=0.36)
        xdn = place_mos(c, cache, xc + 7.6, -44.2, N_LVT, 16.0, 0.15, 4, False,
                        y_gate=-41.50, s_y=-45.50, d_y=-42.90, sd_w=0.36)

        c.wire("metal1", [(xdp["d_xs"][0], -42.90), (xhp["d_xs"][-1], -42.90)], 0.44)
        c.wire("metal1", [(xhn["d_xs"][0], -42.90), (xdn["d_xs"][-1], -42.90)], 0.44)
        via1_clean(c, x_qp, -42.90)
        via1_clean(c, x_qp, y_qbar)
        c.wire("metal2", [(x_qp, -42.90), (x_qp, y_qbar)], 0.60)
        via1_clean(c, x_qn, -42.90)
        via1_clean(c, x_qn, y_qbar)
        c.wire("metal2", [(x_qn, -42.90), (x_qn, y_qbar)], 0.60)

        # Cross-couple hold gates at y = -37.2 & -38.5 on M2/M3
        via1_clean(c, xhp["g"][0], -41.50)
        c.wire("metal2", [(xhp["g"][0], -41.50), (xhp["g"][0], -37.2)], 0.34)
        m2_to_m3(c, xhp["g"][0], -37.2)
        c.wire("metal3", [(xhp["g"][0], -37.2), (x_qn, -37.2)], 0.36)
        m2_to_m3(c, x_qn, -37.2)

        via1_clean(c, xhn["g"][0], -41.50)
        c.wire("metal2", [(xhn["g"][0], -41.50), (xhn["g"][0], -38.5)], 0.34)
        m2_to_m3(c, xhn["g"][0], -38.5)
        c.wire("metal3", [(x_qp, -38.5), (xhn["g"][0], -38.5)], 0.36)
        m2_to_m3(c, x_qp, -38.5)

        # Mid-latch P+ tap at y = -47.90 (0 LU.2!)
        draw_tap_h(c, "psubdiff", xc - 11.6, xc + 11.6, -47.90, with_m1=True, m1_w=0.40)
        for sgn in (-1.0, 1.0):
            via1_clean(c, grid(xc + sgn * 11.6), -47.90)

        # Clock switches at y = -52.5 (wf=5.0 -> y in [-55.0..-50.0])
        xckp = place_mos(c, cache, xc - 4.8, -52.5, N_LVT, 20.0, 0.15, 4, False,
                         y_gate=-49.40, s_y=-54.20, d_y=-50.80, sd_w=0.44)
        xckn = place_mos(c, cache, xc + 4.8, -52.5, N_LVT, 20.0, 0.15, 4, False,
                         y_gate=-49.40, s_y=-54.20, d_y=-50.80, sd_w=0.44)

        c.wire("metal1", [(xhp["s_xs"][0], -45.50), (xhn["s_xs"][-1], -45.50)], 0.40)
        via1_clean(c, xc + 1.0, -45.50)
        c.wire("metal2", [(xc + 1.0, -45.50), (xc + 1.0, -50.80), (xckn["d"][0], -50.80)], 0.44)
        via1_clean(c, xckn["d"][0], -50.80)

        for x_s in (xdp["s"][0], xdn["s"][0]):
            via1_clean(c, x_s, -45.50)
            c.wire("metal2", [(x_s, -46.80), (x_s, -45.50)], 0.40)
            m2_to_m3(c, x_s, -46.80)
        c.wire("metal3", [(xdp["s"][0], -46.80), (xdn["s"][0], -46.80)], 0.50)
        m2_to_m3(c, xckp["d"][0], -46.80)
        c.wire("metal2", [(xckp["d"][0], -50.80), (xckp["d"][0], -46.80)], 0.44)
        via1_clean(c, xckp["d"][0], -50.80)

        x_ckl = grid(xc - 10.0)
        x_ckr = grid(xc + 10.0)
        c.wire("metal1", [(x_ckl, -49.40), (xckp["g"][0], -49.40)], 0.30)
        c.wire("metal1", [(xckn["g"][0], -49.40), (x_ckr, -49.40)], 0.30)
        via1_clean(c, x_ckl, -49.40)
        via1_clean(c, x_ckr, -49.40)
        y_l = Y_CKP_BUS if is_master else Y_CKN_BUS
        y_r = Y_CKN_BUS if is_master else Y_CKP_BUS
        c.wire("metal2", [(x_ckl, -49.40), (x_ckl, y_l)], 0.38)
        m2_to_m3(c, x_ckl, y_l)
        c.wire("metal2", [(x_ckr, -49.40), (x_ckr, y_r)], 0.38)
        m2_to_m3(c, x_ckr, y_r)

        # SIDE-BY-SIDE TAIL FET `Xtail_m/s` at x = +-40.5, y = -52.0 (SAVES 10 um HEIGHT!)
        x_tail_c = grid(sgn_out * 40.5)
        xt = place_mos(c, cache, x_tail_c, -52.0, N_STD, 36.0, 0.35, 8, False,
                       y_gate=Y_VBIASD, s_y=-53.40, d_y=-50.60, sd_w=0.50)
        # Connect xckp.s + xckn.s (-54.20) -> M1 horizontal bar -> M3 at y=-54.20 out to xt.d (-50.60) on M2!
        c.wire("metal1", [(xckp["s_xs"][0], -54.20), (xckn["s_xs"][-1], -54.20)], 0.60)
        x_t_exit = grid(xc + sgn_out * 4.8)
        m1_to_m3(c, x_t_exit, -54.20)
        x_t_land = grid(x_tail_c - sgn_out * 4.5)
        c.wire("metal3", [(min(x_t_exit, x_t_land), -54.20), (max(x_t_exit, x_t_land), -54.20)], 0.70)
        m2_to_m3(c, x_t_land, -54.20)
        c.wire("metal2", [(x_t_land, -54.20), (x_t_land, -50.60), (xt["d"][0], -50.60)], 0.60)
        via1_clean(c, xt["d"][0], -50.60)
        # xt.s (-53.40) -> Y_LATCH_VSS (-56.80) on M2
        for sx in xt["s_xs"][::2]:
            via1_clean(c, sx, -53.40)
            via1_clean(c, sx, Y_LATCH_VSS)
            c.wire("metal2", [(sx, Y_LATCH_VSS), (sx, -53.40)], 0.34)
        # xt.g (Y_VBIASD = -48.20) -> M3 bus directly (xt.s M2 is below -53.40, ZERO conflict!)
        m1_to_m3(c, xt["g"][0], Y_VBIASD)

        latch_pins[lname] = {
            "qp": (x_qp, y_qbar),
            "qn": (x_qn, y_qbar),
            "dp": (xdp["g"][0], -41.50),
            "dn": (xdn["g"][0], -41.50),
        }

    # Shortened cross-latch ring on 4 non-crossing M4 tracks (-35.8, -37.1, -38.4, -39.7);
    # South I/Q export columns sit right outside Master/Slave at x = (-33.5, -31.5, +31.5, +33.5)!
    m_p, s_p = latch_pins["m"], latch_pins["s"]
    ring_routes = [
        ("ip", m_p["qp"], s_p["dp"], -35.8, -33.5),
        ("in", m_p["qn"], s_p["dn"], -37.1, -31.5),
        ("qp", s_p["qp"], m_p["dn"], -38.4, +31.5),
        ("qn", s_p["qn"], m_p["dp"], -39.7, +33.5),
    ]
    iq_ports = {}
    for nm, (ox, oy), (ix, iy), y_m4, x_port in ring_routes:
        m2_to_m3(c, ox, y_m4)
        via3_pad(c, ox, y_m4)
        via1_clean(c, ix, iy)
        c.wire("metal2", [(ix, iy), (ix, y_m4)], 0.40)
        m2_to_m3(c, ix, y_m4)
        via3_pad(c, ix, y_m4)
        xs_all = [ox, ix, x_port]
        c.wire("metal4", [(min(xs_all), y_m4), (max(xs_all), y_m4)], 0.48)
        via3_pad(c, x_port, y_m4)
        m2_to_m3(c, x_port, y_m4)
        c.wire("metal2", [(x_port, -40.8), (x_port, y_m4)], 0.48)
        m2_to_m3(c, x_port, -40.8)
        via3_pad(c, x_port, -40.8)
        c.wire("metal4", [(x_port, Y_BOT), (x_port, -40.8)], 0.56)
        iq_ports[nm] = (x_port, Y_BOT)

    # =========================================================================
    # BOTTOM 2-ROW MIRROR-SYMMETRIC CM BIAS RESISTORS (y = -60.5 & -64.5 -> cuts 4 rows to 2!)
    # =========================================================================
    # Row A (y = -60.5): Xrc_p (l=80, left x=-48 -> [-90.9..-5.1]) | Xrc_n (l=80, right x=+48 -> [+5.1..+90.9])
    # Row B (y = -64.5): Xrc_hi (l=60, left x=-38 -> [-70.9..-5.1]) | Xrc_lo (l=96, right x=+56 -> [+5.1..+106.9])
    rc_p = place_res(c, cache, R_1P41, 80.0, -48.0, -60.5, horiz=True)
    rc_n = place_res(c, cache, R_1P41, 80.0, +48.0, -60.5, horiz=True)
    rc_hi = place_res(c, cache, R_1P41, 60.0, -38.0, -64.5, horiz=True)
    rc_lo = place_res(c, cache, R_1P41, 96.0, +56.0, -64.5, horiz=True)

    # Central `vck_cm` hub at x = 0 joining rc_p.right, rc_n.left, rc_hi.right, rc_lo.left!
    c.wire("metal1", [(rc_p["right"][0], -60.5), (rc_n["left"][0], -60.5)], 0.36)
    c.wire("metal1", [(rc_hi["right"][0], -64.5), (rc_lo["left"][0], -64.5)], 0.36)
    c.wire("metal1", [(0.0, -64.5), (0.0, -60.5)], 0.44)

    # Tie all 4 resistor psub corner tabs cleanly to Y_LATCH_VSS (-56.80) or Y_BOT (-70.0) using OUTER corners
    # (well away from Master/Slave VSS spines at x = +-5.9 -> 0 met2.2!)
    for rd, sub_idx, y_tie in ((rc_p, 1, Y_LATCH_VSS), (rc_n, 3, Y_LATCH_VSS), (rc_hi, 0, Y_BOT), (rc_lo, 2, Y_BOT)):
        sx, sy = rd["sub"][sub_idx]
        viali_pad(c, sx, sy)
        via1_clean(c, sx, sy)
        c.wire("metal2", [(sx, min(sy, y_tie)), (sx, max(sy, y_tie))], 0.30)
        m2_to_m3(c, sx, y_tie)

    # Connect `rc_p.left (-89.5, -60.5)` -> `ckp` M3 bus (-42.50) via M2 up along x = -89.5 -> East at y=-42.50!
    via1_clean(c, rc_p["left"][0], -60.5)
    c.wire("metal2", [(rc_p["left"][0], -60.5), (rc_p["left"][0], Y_CKP_BUS)], 0.44)
    m2_to_m3(c, rc_p["left"][0], Y_CKP_BUS)
    c.wire("metal3", [(rc_p["left"][0], Y_CKP_BUS), (acp["bot_m3_b"][0], Y_CKP_BUS)], 0.50)
    # Connect `rc_n.right (+89.5, -60.5)` -> `ckn` M3 bus (-44.00) via M2 up along x = +89.5 -> West at y=-44.00!
    via1_clean(c, rc_n["right"][0], -60.5)
    c.wire("metal2", [(rc_n["right"][0], -60.5), (rc_n["right"][0], Y_CKN_BUS)], 0.44)
    m2_to_m3(c, rc_n["right"][0], Y_CKN_BUS)
    c.wire("metal3", [(acn["bot_m3_b"][0], Y_CKN_BUS), (rc_n["right"][0], Y_CKN_BUS)], 0.50)
    # Connect `rc_hi.left (-69.5, -64.5)` -> VDD (X_VDD_L = -118.0) on M3!
    m1_to_m3(c, rc_hi["left"][0], -64.5)
    c.wire("metal3", [(X_VDD_L, -64.5), (rc_hi["left"][0], -64.5)], 0.50)
    via3_pad(c, X_VDD_L, -64.5)
    # Connect `rc_lo.right (+105.5, -64.5)` -> VSS (X_VSS_R = +114.5) on M3!
    m1_to_m3(c, rc_lo["right"][0], -64.5)
    c.wire("metal3", [(rc_lo["right"][0], -64.5), (X_VSS_R, -64.5)], 0.50)
    via3_pad(c, X_VSS_R, -64.5)

    # 13 exact ports
    c.port("vp", "metal4", -16.0, Y_TANK_M4)
    c.port("vn", "metal4", +16.0, Y_TANK_M4)
    for nm, (px, py) in iq_ports.items():
        c.port(nm, "metal4", px, py)
    c.port("vctrl", "metal2", -111.0, Y_VCTRL_BUS)
    for bk, yb in Y_BITS.items():
        c.port(f"b{bk}", "metal2", -111.0, yb)
    c.port("vdd", "metal4", X_VDD_L, 0.0)
    c.port("vss", "metal4", X_VSS_L, 0.0)

    meta = {
        "vp_xy": (-16.0, Y_TANK_M4), "vn_xy": (+16.0, Y_TANK_M4),
        "iq_ports": iq_ports, "vctrl_xy": (-111.0, Y_VCTRL_BUS),
        "bits_y": Y_BITS, "vdd_x": X_VDD_L, "vss_x": X_VSS_L,
        "y_top": Y_TOP, "y_bot": Y_BOT,
    }
    return c, meta


# ---------------------------------------------------------------------------
# Hierarchical Top-Level LC-VCO + Quadrature /2 Assembly (`vco5g_lc_div2_pdk`)
# ---------------------------------------------------------------------------

def build_hierarchical_top(
    work: Path, active_mag: Path, meta: dict, *, unified: bool = False, variant: str | None = None
) -> tuple[Path, dict]:
    v = variant or ("unified" if unified else "oct")
    is_oct = v == "oct"
    is_uni = v in ("unified", "oct")
    ind_src = IND_OCT_MAG if is_oct else IND_MAG
    if not ind_src.exists():
        raise FileNotFoundError(
            f"Inductor .mag not found for variant={v!r}: {ind_src}. "
            f"Use --variant oct for the signed-off octagonal inductor ({IND_OCT_MAG})."
        )
    ind_cell_name = ind_src.stem
    shutil.copy2(ind_src, work / f"{ind_cell_name}.mag")
    active_cell_name = active_mag.stem
    top_cell_name = {
        "legacy": "vco5g_lc_div2_pdk",
        "unified": "vco5g_lc_div2_unified_pdk",
        "oct": "vco5g_lc_div2_oct_pdk",
    }[v]

    # Square ind_sym_2n2: [-124..+124]^2 at IND_CY=158 -> y in [+34..+282], p/n at (+-16, +42), ct at (0, +274)
    # Octagonal ind_oct_2n5: [-133..+133]^2 at IND_CY=167 -> y in [+34..+300], p/n at (+-16, +42), ct at (0, +292)
    IND_CY = 167.0 if is_oct else 158.0
    X_RING_VDD = 136.0 if is_oct else 127.0
    Y_RING_N = 303.5 if is_oct else 285.5
    top = Cell()

    # 1. Ultra-short symmetric matched M5 tank feeds: inductor p/n (+-16, +42) -> active vp/vn (+-16, +28.5)
    for x_t in (-16.0, +16.0):
        top.wire("metal5", [(x_t, 26.8), (x_t, 43.5)], 4.00)
        top.rect("metal4", grid(x_t - 2.0), 26.70, grid(x_t + 2.0), 30.30)
        for dx in (-0.85, +0.85):
            top.pad("via4", grid(x_t + dx), 28.50, 1.18)

    # 2. Power ring policy:
    #    - In `oct` (floating `ct`, complementary push-pull), DO NOT wrap an unused closed M5 VDD ring
    #      around the octagonal inductor! Keeping the perimeter around the coil 100% metal-free eliminates
    #      any induced eddy-current loop (preserving full Q_5G=7.26) and shrinks die to 266 x 371.1 um!
    #      Active core already has wide M4 VDD_L/R (+-118) bridged by M3 at Y_TOP=+32.
    if not is_oct:
        if not is_uni:
            top.wire("metal5", [(0.0, 272.0), (0.0, Y_RING_N)], 4.00)
        top.wire("metal5", [(-X_RING_VDD, Y_RING_N), (+X_RING_VDD, Y_RING_N)], 4.00)
        for sgn in (-1.0, +1.0):
            xr = sgn * X_RING_VDD
            xa = sgn * 118.0
            top.wire("metal5", [(xr, 27.5), (xr, Y_RING_N)], 4.00)
            top.wire("metal5", [(min(xr, xa) - 1.5, 29.0), (max(xr, xa) + 1.5, 29.0)], 4.00)
            top.rect("metal4", grid(xa - 2.0), 26.5, grid(xa + 2.0), 31.5)
            for dy in (-1.0, +1.0):
                top.pad("via4", xa, grid(29.0 + dy), 1.18)

    # 3. Tie inductor P+ guard ring cleanly on M3 -> active VSS_L/R (+-114.5, +22)
    # Octagonal stepped guard ring has vertical 2 um M1 bar at x = +-116.0, y_local in [-96..-68] (y_world [+71..+99])
    xg_abs = 116.0 if is_oct else 123.0
    yg_tie = 76.0 if is_oct else 38.0
    for sgn in (-1.0, +1.0):
        xg = sgn * xg_abs
        xv = sgn * 114.5
        via1_clean(top, xg, yg_tie)
        via2_clean(top, xg, yg_tie)
        top.wire("metal3", [(xg, yg_tie), (xg, 22.0), (xv, 22.0)], 1.20)
        via3_pad(top, xv, 22.0)
        via3_pad(top, grid(xv + sgn * 0.70), 22.0)

    top.port("vp", "metal5", -16.0, 35.0)
    top.port("vn", "metal5", +16.0, 35.0)
    for nm, (px, py) in meta["iq_ports"].items():
        top.port(nm, "metal4", px, py)
    top.port("vctrl", "metal2", -111.0, meta["vctrl_xy"][1])
    for bk, yb in meta["bits_y"].items():
        top.port(f"b{bk}", "metal2", -111.0, yb)
    if is_oct:
        top.port("vdd", "metal4", -118.0, 0.0)
    else:
        top.port("vdd", "metal5", -X_RING_VDD, 100.0)
    top.port("vss", "metal4", -114.5, 0.0)

    top_mag = work / f"{top_cell_name}.mag"
    top.write(top_mag)
    text = top_mag.read_text()
    u_ind_y = int(round(IND_CY * 200))
    u_ind_h = 26600 if is_oct else 24800
    use_block = (
        f"use {ind_cell_name}  ind0\n"
        f"timestamp 0\n"
        f"transform 1 0 0 0 1 {u_ind_y}\n"
        f"box -{u_ind_h} -{u_ind_h} {u_ind_h} {u_ind_h}\n"
        f"use {active_cell_name}  act0\n"
        f"timestamp 0\n"
        f"transform 1 0 0 0 1 0\n"
        f"box -24000 -14500 24000 6800\n"
    )
    text = text.replace("<< ", use_block + "<< ", 1)
    top_mag.write_text(text)
    geom = {
        "ind_cell_name": ind_cell_name,
        "ind_cy": IND_CY,
        "x_ring_vdd": X_RING_VDD,
        "y_ring_n": Y_RING_N,
        "top_w": 266.0 if is_oct else round(2.0 * (X_RING_VDD + 2.0), 2),
        "top_y_max": 300.0 if is_oct else round(Y_RING_N + 2.0, 2),
    }
    return top_mag, geom


def run_full_drc_and_gds(mag_path: Path, work: Path, *, export_gds: bool = False) -> tuple[int, list[str], dict | None]:
    cell_name = mag_path.stem
    tcl = work / f"drc_{cell_name}.tcl"
    gds_path = work / f"{cell_name}.gds"
    gds_cmd = f"gds write {gds_path.name}\n" if export_gds else ""
    tcl.write_text(
        f"load {cell_name}\n"
        "select top cell\n"
        "drc style drc(full)\n"
        "drc on\n"
        "drc euclidean on\n"
        "drc check\n"
        "drc catchup\n"
        "set why [drc listall why]\n"
        "foreach {msg boxes} $why {\n"
        "    puts \"DRC_RULE: $msg | count=[llength $boxes] | sample=[lindex $boxes 0]\"\n"
        "}\n"
        f"{gds_cmd}"
        "quit -noprompt\n"
    )
    res = rlc.run_magic_bounded(tcl, work, timeout_s=240)
    (work / f"drc_{cell_name}.log").write_text(res.log)
    rules = [ln.strip() for ln in res.log.splitlines() if ln.strip().startswith("DRC_RULE:")]
    total = sum(int(re.search(r"count=(\d+)", r).group(1)) for r in rules if re.search(r"count=(\d+)", r))

    kl_info = None
    if export_gds and gds_path.exists() and KLAYOUT_BIN.exists() and KLAYOUT_DRC.exists():
        rpt = work / f"{cell_name}_klayout.lyrdb"
        kl_cmd = [
            str(KLAYOUT_BIN), "-b", "-r", str(KLAYOUT_DRC),
            "-rd", f"input={gds_path}", "-rd", f"report={rpt}", "-rd", "feol=true", "-rd", "beol=true",
        ]
        kp = subprocess.run(kl_cmd, cwd=work, capture_output=True, text=True, timeout=240)
        (work / f"klayout_{cell_name}.log").write_text(kp.stdout + "\n" + kp.stderr)
        if rpt.exists():
            rtxt = rpt.read_text(errors="ignore")
            items = re.findall(r"<item>.*?<category>(.*?)</category>", rtxt, re.S)
            by_cat: dict[str, int] = {}
            for cat in items:
                c = cat.strip().strip("'")
                by_cat[c] = by_cat.get(c, 0) + 1
            kl_info = {"status": "ok", "total_items": len(items), "by_category": by_cat}
        else:
            kl_info = {"status": f"rc={kp.returncode}", "total_items": -1}
    return total, rules, kl_info


def render_hierarchical_png(
    work: Path, top_mag: Path, active_mag: Path, png_path: Path, active_w: float, active_h: float, top_h: float,
    ind_cy: float = 167.0, *, unified: bool = False, variant: str | None = None, geom: dict | None = None,
) -> None:
    v = variant or ("unified" if unified else "oct")
    is_oct = v == "oct"
    is_uni = v in ("unified", "oct")
    ind_cell_name = geom["ind_cell_name"] if geom else ("vco5g_ind_oct_2n5_pdk" if is_oct else "vco5g_ind_sym_2n2_pdk")
    top_w = geom["top_w"] if geom else (276.0 if is_oct else 258.0)
    y_top_plot = (geom["top_y_max"] + 7.0) if geom else 294.0
    x_lim = (top_w / 2.0 + 10.0)
    palette = {
        "nwell":    ("#1e3a5f", 0.35, 1),
        "psubdiff": ("#2e7d32", 0.65, 2),
        "pdiff":    ("#d97706", 0.60, 3),
        "ndiff":    ("#2563eb", 0.60, 3),
        "poly":     ("#dc2626", 0.70, 4),
        "ppolyres": ("#c026d3", 0.80, 4),
        "metal1":   ("#3b82f6", 0.60, 5),
        "metal2":   ("#14b8a6", 0.72, 6),
        "metal3":   ("#f97316", 0.80, 7),
        "mimcap":   ("#facc15", 0.55, 8),
        "metal4":   ("#38bdf8", 0.82, 9),
        "metal5":   ("#f43f5e", 0.88, 10),
    }
    by_lyr: dict[str, list] = {k: [] for k in palette}

    def ingest(path: Path, dx: float = 0.0, dy: float = 0.0) -> None:
        lyr = None
        for ln in path.read_text(errors="ignore").splitlines():
            m = re.match(r"^<< (\S+) >>$", ln)
            if m:
                lyr = m.group(1) if m.group(1) in by_lyr else None
                continue
            if not lyr:
                continue
            if ln.startswith("rect "):
                parts = ln.split()
                if len(parts) == 5:
                    x1, y1, x2, y2 = (int(val) / 200.0 for val in parts[1:])
                    by_lyr[lyr].append(Rectangle((x1 + dx, y1 + dy), x2 - x1, y2 - y1))
            elif ln.startswith("tri "):
                parts = ln.split()
                if len(parts) == 6:
                    x1, y1, x2, y2 = (int(val) / 200.0 for val in parts[1:5])
                    ori = parts[5].lower()
                    x1, y1, x2, y2 = x1 + dx, y1 + dy, x2 + dx, y2 + dy
                    if ori == "sw":
                        pts = [(x1, y1), (x2, y1), (x1, y2)]
                    elif ori == "ne":
                        pts = [(x2, y2), (x1, y2), (x2, y1)]
                    elif ori == "nw":
                        pts = [(x1, y2), (x1, y1), (x2, y2)]
                    elif ori == "se":
                        pts = [(x2, y1), (x2, y2), (x1, y1)]
                    else:
                        continue
                    by_lyr[lyr].append(MplPolygon(pts, closed=True))

    ingest(work / f"{ind_cell_name}.mag", 0.0, ind_cy)
    ingest(active_mag, 0.0, 0.0)
    ingest(top_mag, 0.0, 0.0)

    fig, ax = plt.subplots(figsize=(9.4, 11.8), dpi=220)
    fig.patch.set_facecolor("#0b101b")
    ax.set_facecolor("#0f172a")
    for lyr, (col, alpha, z) in sorted(palette.items(), key=lambda kv: kv[1][2]):
        ps = by_lyr[lyr]
        if ps:
            ax.add_collection(PatchCollection(ps, facecolor=col, edgecolor="none", alpha=alpha, zorder=z))

    core_lbl = (
        "-gm Core + Centered Xtail + 2×6f Varactors"
        if is_oct else
        ("-gm Core + 2×6f Varactors (High-Z Tail)" if is_uni else "-gm Core + 2×6f Varactors + Fixed MIM")
    )
    ctail_lbl = "2 pF Local\nVDD–VSS Decap" if is_uni else "2 pF Tail\nBypass"
    dev_cnt = 157 if is_uni else 159
    capw_lbl = {"legacy": "4.2", "unified": "4.0", "oct": "3.6"}[v]
    title_cell = {"legacy": "vco5g_lc_div2_pdk", "unified": "vco5g_lc_div2_unified_pdk", "oct": "vco5g_lc_div2_oct_pdk"}[v]
    ind_lbl = (
        "45° Octagonal 3T met4||met5 Spiral\n228×228 µm · L=2.408 nH · Q₅G=7.26 · C_sub=410.5 fF"
        if is_oct else
        "3-Turn Symmetric met4||met5 Spiral\n210×210 µm · L=2.541 nH · C_sub=396.5 fF"
    )
    for x, y, txt in [
        (0, ind_cy, ind_lbl),
        (0, 20.5, core_lbl),
        (0, -6.5, f"1D Common-Centroid 4-Bit MIM Bank (15u, {capw_lbl}µm)"),
        (-93.5, 9, ctail_lbl),
        (98.5, 14.5, "1 pF Gate\nLPF"),
        (0, -45, "5.0 → 2.5 GHz Quadrature CML ÷2 (Side-by-Side Tails)"),
    ]:
        ax.text(x, y, txt, color="#f8fafc", fontsize=7.0, fontweight="bold", ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.16", facecolor="#0f172a", edgecolor="#64748b", alpha=0.82, lw=0.6), zorder=20)

    ax.set_xlim(-x_lim, x_lim)
    ax.set_ylim(-78, y_top_plot)
    ax.set_aspect("equal")
    ax.set_title(
        f"SKY130A 5.0 GHz Arch C LC-VCO + Quadrature CML ÷2 (`{title_cell}`)\n"
        f"Total {top_w:.0f} × {top_h:.1f} µm ({top_w*top_h/1e6:.4f} mm²) · Active {active_w:.1f} × {active_h:.1f} µm · {dev_cnt} Devices",
        color="#f8fafc", fontsize=9.4, fontweight="bold", pad=10,
    )
    ax.set_xlabel("X (µm)", color="#cbd5e1", fontsize=8.5)
    ax.set_ylabel("Y (µm)", color="#cbd5e1", fontsize=8.5)
    ax.tick_params(colors="#94a3b8", labelsize=8)
    for sp in ax.spines.values():
        sp.set_color("#334155")
    fig.savefig(png_path, dpi=220, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", choices=["legacy", "unified", "oct"], default="oct")
    ap.add_argument("--work-dir", type=Path, default=None)
    ap.add_argument("--install", action="store_true")
    args = ap.parse_args()

    v = args.variant
    is_oct = v == "oct"
    is_uni = v in ("unified", "oct")
    default_work = {"legacy": RESULTS_DIR, "unified": UNIFIED_RESULTS_DIR, "oct": OCT_RESULTS_DIR}[v]
    work = (args.work_dir or default_work).resolve()
    variant_dir = {"legacy": VARIANT_DIR, "unified": UNIFIED_VARIANT_DIR, "oct": OCT_VARIANT_DIR}[v]
    active_name = {
        "legacy": "vco5g_lc_active_div2_pdk",
        "unified": "vco5g_lc_active_div2_unified_pdk",
        "oct": "vco5g_lc_active_div2_oct_pdk",
    }[v]
    top_name = {
        "legacy": "vco5g_lc_div2_pdk",
        "unified": "vco5g_lc_div2_unified_pdk",
        "oct": "vco5g_lc_div2_oct_pdk",
    }[v]
    dev_cnt = 157 if is_uni else 159

    work.mkdir(parents=True, exist_ok=True)
    cache = PdkCache(work / "pdk_cache")

    print(f"[1/4] Building `{active_name}` ({dev_cnt} PDK devices, 0% M5, variant={v})...", flush=True)
    active_cell, meta = build_active_div2_cell(cache, variant=v)
    active_mag = work / f"{active_name}.mag"
    active_cell.write(active_mag)
    ref_spice = work / f"{active_name}_ref.spice"
    ref_spice.write_text(build_active_ref_spice(variant=v))
    ab = active_cell.bbox()
    aw, ah = round(ab[2] - ab[0], 3), round(ab[3] - ab[1], 3)
    print(f"      Active bbox: ({ab[0]:.2f}, {ab[1]:.2f})..({ab[2]:.2f}, {ab[3]:.2f}) -> {aw:.2f} x {ah:.2f} um ({aw*ah:.1f} um^2)", flush=True)

    print(f"[2/4] Running `review_cell.py` (Magic full DRC + Netgen LVS + CPEX) on `{active_name}`...", flush=True)
    rev_dir = work / "review_active"
    if rev_dir.exists():
        shutil.rmtree(rev_dir)
    subprocess.run(
        [sys.executable, str(REVIEW_CELL), "--output-dir", str(rev_dir), str(active_mag), str(ref_spice)],
        capture_output=True, text=True, timeout=240,
    )
    check_log = (rev_dir / "check.log").read_text() if (rev_dir / "check.log").exists() else ""
    drc_m = re.search(r"DRC_TOTAL\s+(\d+)", check_log)
    drc_tot = int(drc_m.group(1)) if drc_m else -1
    lvs_ok = "LVS_MATCH True" in check_log
    lvs_prop_err = "LVS_PROPERTY_ERRORS True" in check_log
    rev_sum = json.loads((rev_dir / "summary.json").read_text()) if (rev_dir / "summary.json").exists() else {}
    print(f"      Active review: DRC={drc_tot} LVS_MATCH={lvs_ok} PROP_ERR={lvs_prop_err} physical_passed={rev_sum.get('physical_passed')}", flush=True)
    if drc_tot != 0 or not lvs_ok or lvs_prop_err:
        for ln in check_log.splitlines():
            if any(k in ln for k in ("DRC_TOTAL", " | ", "LVS_", "Circuit 1", "Result:", "mismatch", "Property")):
                print("       ", ln, flush=True)

    print(f"[3/4] Assembling hierarchical `{top_name}` & running full-hierarchy Magic DRC{' + KLayout DRC' if is_oct else ''}...", flush=True)
    top_mag, geom = build_hierarchical_top(work, active_mag, meta, variant=v)
    top_drc, top_rules, kl_info = run_full_drc_and_gds(top_mag, work, export_gds=is_oct)
    print(f"      Top `{top_name}` full-hierarchy Magic DRC = {top_drc} | KLayout = {kl_info}", flush=True)
    for r in top_rules[:15]:
        print("       ", r, flush=True)

    top_h = round(geom["top_y_max"] - ab[1], 2)
    top_w = geom["top_w"]
    print("[4/4] Rendering PNGs...", flush=True)
    active_png = work / f"{active_name}.png"
    top_png = work / f"{top_name}.png"
    subprocess.run([sys.executable, str(PLOT_MAG), str(active_mag), str(active_png)], check=True, timeout=120)
    render_hierarchical_png(work, top_mag, active_mag, top_png, aw, ah, top_h, ind_cy=geom["ind_cy"], variant=v, geom=geom)

    ind_sum = (
        {
            "cell": "vco5g_ind_oct_2n5_pdk",
            "width_um": 266.0,
            "height_um": 266.0,
            "l_diff_nh": 2.408,
            "l_eff_5g_nh": 2.724,
            "q_5g": 7.26,
            "r_dc_tt_ohm": 3.065,
            "c_sub_total_ff": 410.49,
            "ct_floating": True,
        }
        if is_oct else
        {
            "cell": "vco5g_ind_sym_2n2_pdk",
            "width_um": 248.0,
            "height_um": 248.0,
            "l_diff_nh": 2.541,
            "r_dc_tt_ohm": 3.248,
            "c_sub_total_ff": 396.51,
            "ct_floating": is_uni,
        }
    )

    summary = {
        "variant": v,
        "cell": top_name,
        "active_submacro": {
            "cell": active_name,
            "width_um": aw,
            "height_um": ah,
            "area_um2": round(aw * ah, 2),
            "drc_total": drc_tot,
            "lvs_match": lvs_ok,
            "lvs_property_errors": lvs_prop_err,
            "physical_passed": rev_sum.get("physical_passed"),
            "ports": rev_sum.get("ports", []),
            "device_count_ref": dev_cnt,
            "parasitics": rev_sum.get("parasitics", {}),
        },
        "inductor_submacro": ind_sum,
        "top_macro": {
            "width_um": top_w,
            "height_um": top_h,
            "area_mm2": round(top_w * top_h / 1e6, 4),
            "drc_total": top_drc,
            "drc_rules": top_rules,
            "klayout_drc": kl_info,
        },
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Summary written to {work / 'summary.json'}", flush=True)

    if args.install and drc_tot == 0 and lvs_ok and not lvs_prop_err and top_drc == 0:
        variant_dir.mkdir(parents=True, exist_ok=True)
        for src, dst_name in [
            (active_mag, f"{active_name}.mag"),
            (ref_spice, f"{active_name}_ref.spice"),
            (active_png, f"{active_name}.png"),
            (top_mag, f"{top_name}.mag"),
            (work / f"{top_name}.gds", f"{top_name}.gds"),
            (top_png, f"{top_name}.png"),
            (work / "summary.json", "summary.json"),
        ]:
            if src.exists():
                shutil.copy2(src, variant_dir / dst_name)
        for extra in (f"{active_name}_lvs.spice", f"{active_name}_pex.spice"):
            p = rev_dir / extra
            if p.exists():
                shutil.copy2(p, variant_dir / extra)
        print(f"Installed signed-off `{top_name}` macro to {variant_dir}", flush=True)


if __name__ == "__main__":
    main()
