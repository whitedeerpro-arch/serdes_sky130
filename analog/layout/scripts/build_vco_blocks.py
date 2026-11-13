#!/usr/bin/env python3
"""
Generate VCO building blocks with RF/Analog interdigitated strip electrodes:
  1. mos_array_pro: Full-height S/D strip electrodes (licon+li1+viali+M1) + Top Drain Comb / Bottom Source Comb
  2. pll_vco_varactor: 4-finger LVT varactor (4 x W=5.2, L=0.5)
  3. pll_vco_delay_stage: Differential CML delay stage (Mp/Mn nf=8x5.0 LVT, Tail nf=4x6.3, 2x2 parallel high_po loads)
  4. serdes_cml_buffer: First-stage CML buffer (Mp/Mn nf=4x3.0 LVT, Tail nf=4x3.0, 2x1 high_po loads)
  5. pll_vco_cap_unit & pll_vco_cap_bank (both 4-bit 4x4 and 5-bit 8x4 binary column-slice arrays)
"""
from __future__ import annotations
import sys
from pathlib import Path
import matplotlib.pyplot as plt

ANALOG = Path(__file__).resolve().parents[2]
INTER_DIR = Path(__file__).resolve().parent
PACK_DIR = ANALOG / "layout/work/serdes_vco_lf_layout_pack"
sys.path.insert(0, str(INTER_DIR))

from layout_core import LayoutCanvas, load_mag_as_canvas, plot_canvas

VCO_DEV_DIR = ANALOG / "pll/vco/layout"


def draw_comb_mos(
    c: LayoutCanvas,
    kind: str,
    w_finger: float,
    nf: int,
    l_gate: float,
    x0: float,
    y0: float,
    lvt: bool = False,
    drain_side: str = "top",      # "top" or "bottom" comb for odd fingers (D)
    gate_strap: str = "bottom",   # "top", "bottom", or "both"
    dummy_ends: bool = True,
    sd_width: float = 0.48,
) -> dict:
    """
    Draw a textbook multi-finger MOSFET with:
      - Full-height vertical strip electrodes (licon + li1 + viali + M1) along every S/D finger
      - Odd fingers (Drain) pulled out to a horizontal M1 comb bus on `drain_side` (outside channel!)
      - Even fingers (Source) pulled out to a horizontal M1 comb bus on the opposite side (outside channel!)
      - Zero horizontal M1 crossing over the active channel!
      - Gate poly fingers strapped onto an M2 gate bus via polycont+li1+viali+m1+via1 outside the S/D comb.
    """
    nd_layer = "ndiff" if kind == "n" else "pdiff"
    cut_layer = "ndiffc" if kind == "n" else "pdiffc"
    mark_layer = ("nmoslvt" if lvt else "nmos") if kind == "n" else ("pmoslvt" if lvt else "pmos")

    pitch = round(sd_width + l_gate, 3)
    end_sd = sd_width
    total_w = round(end_sd * 2 + nf * l_gate + (nf - 1) * sd_width, 3)
    y1, y2 = round(y0, 3), round(y0 + w_finger, 3)

    # 1. Continuous active diffusion strip
    c.R(nd_layer, x0, y1, x0 + total_w, y2)

    # Comb bus vertical positions (outside active region!)
    y_top_comb1, y_top_comb2 = round(y2 + 0.28, 3), round(y2 + 0.68, 3)
    y_bot_comb1, y_bot_comb2 = round(y1 - 0.68, 3), round(y1 - 0.28, 3)

    # Gate poly extension beyond the comb buses (routed on poly, then M1/M2 strap outside comb)
    gy1 = round(y_bot_comb1 - 0.52, 3) if gate_strap in ("bottom", "both") else round(y1 - 0.22, 3)
    gy2 = round(y_top_comb2 + 0.52, 3) if gate_strap in ("top", "both") else round(y2 + 0.22, 3)

    # 2. Gate poly fingers + channel recognition layer
    gate_xs = []
    for i in range(nf):
        gx1 = round(x0 + end_sd + i * pitch, 3)
        gx2 = round(gx1 + l_gate, 3)
        gcx = round((gx1 + gx2) / 2.0, 3)
        gate_xs.append(gcx)
        c.R("poly", gx1, gy1, gx2, gy2)
        c.R(mark_layer, gx1, y1, gx2, y2)

    # Optional dummy poly shields on left/right outer edges of active
    if dummy_ends:
        for d_gx in (round(x0 - 0.28, 3), round(x0 + total_w + 0.13, 3)):
            c.R("poly", d_gx, round(y1 - 0.18, 3), round(d_gx + 0.15, 3), round(y2 + 0.18, 3))

    # Gate contact bar (continuous horizontal poly bridge outside comb + contacts + M1/M2 strap)
    g_port = (gate_xs[0], round((y1 + y2) / 2.0, 3))
    if gate_strap in ("top", "both"):
        g_y1, g_y2 = round(y_top_comb2 + 0.18, 3), round(y_top_comb2 + 0.54, 3)
        g_cy = round((g_y1 + g_y2) / 2.0, 3)
        gx_min, gx_max = round(gate_xs[0] - 0.22, 3), round(gate_xs[-1] + 0.22, 3)
        c.R("poly", gx_min, g_y1, gx_max, g_y2)
        c.R("locali", gx_min, g_y1, gx_max, g_y2)
        c.R("m1", gx_min, g_y1, gx_max, g_y2)
        for gcx in gate_xs:
            c.sq("polycont", gcx, g_cy, 0.17)
            c.sq("viali", gcx, g_cy, 0.17)
        g_port = (round((gx_min + gx_max) / 2.0, 3), g_cy)

    if gate_strap in ("bottom", "both"):
        g_y1, g_y2 = round(y_bot_comb1 - 0.54, 3), round(y_bot_comb1 - 0.18, 3)
        g_cy = round((g_y1 + g_y2) / 2.0, 3)
        gx_min, gx_max = round(gate_xs[0] - 0.22, 3), round(gate_xs[-1] + 0.22, 3)
        c.R("poly", gx_min, g_y1, gx_max, g_y2)
        c.R("locali", gx_min, g_y1, gx_max, g_y2)
        c.R("m1", gx_min, g_y1, gx_max, g_y2)
        for gcx in gate_xs:
            c.sq("polycont", gcx, g_cy, 0.17)
            c.sq("viali", gcx, g_cy, 0.17)
        if gate_strap == "bottom":
            g_port = (round((gx_min + gx_max) / 2.0, 3), g_cy)

    # 3. Full-height vertical S/D Strip Electrodes + Comb Buses
    # Number of vertical contacts per finger along channel height w_finger:
    n_cuts = max(1, int((w_finger - 0.24 - 0.17) / 0.36) + 1)
    span_y = (n_cuts - 1) * 0.36
    cut_y0 = round((y1 + y2) / 2.0 - span_y / 2.0, 3)
    cut_ys = [round(cut_y0 + k * 0.36, 3) for k in range(n_cuts)]

    s_xs, d_xs = [], []
    for i in range(nf + 1):
        if i == 0:
            sx = round(x0 + end_sd / 2.0, 3)
        elif i == nf:
            sx = round(x0 + total_w - end_sd / 2.0, 3)
        else:
            sx = round(x0 + end_sd + i * pitch - sd_width / 2.0, 3)

        is_drain = (i % 2 == 1)
        if is_drain:
            d_xs.append(sx)
            go_top = (drain_side == "top")
        else:
            s_xs.append(sx)
            go_top = (drain_side != "top")

        # Vertical strip electrode extent: runs across active [y1+0.06, y2-0.06] and extends into its comb bus!
        strip_y1 = round(y1 + 0.08, 3) if go_top else y_bot_comb1
        strip_y2 = y_top_comb2 if go_top else round(y2 - 0.08, 3)
        c.R("locali", sx - 0.14, strip_y1, sx + 0.14, strip_y2)
        c.R("m1", sx - 0.14, strip_y1, sx + 0.14, strip_y2)
        for cy in cut_ys:
            c.sq(cut_layer, sx, cy, 0.17)
            c.sq("viali", sx, cy, 0.17)

    # Top and bottom horizontal M1 + M2 comb trunks
    top_xs = d_xs if drain_side == "top" else s_xs
    bot_xs = s_xs if drain_side == "top" else d_xs

    top_x1, top_x2 = round(min(top_xs) - 0.20, 3), round(max(top_xs) + 0.20, 3)
    bot_x1, bot_x2 = round(min(bot_xs) - 0.20, 3), round(max(bot_xs) + 0.20, 3)
    c.R("locali", top_x1, y_top_comb1, top_x2, y_top_comb2)
    c.R("m1", top_x1, y_top_comb1, top_x2, y_top_comb2)
    c.R("m2", top_x1, y_top_comb1, top_x2, y_top_comb2)
    for tx in top_xs:
        c.via1(tx, round((y_top_comb1 + y_top_comb2) / 2.0, 3), pad=0.34)

    c.R("locali", bot_x1, y_bot_comb1, bot_x2, y_bot_comb2)
    c.R("m1", bot_x1, y_bot_comb1, bot_x2, y_bot_comb2)
    c.R("m2", bot_x1, y_bot_comb1, bot_x2, y_bot_comb2)
    for bx in bot_xs:
        c.via1(bx, round((y_bot_comb1 + y_bot_comb2) / 2.0, 3), pad=0.34)

    top_mid = (round((top_x1 + top_x2) / 2.0, 3), round((y_top_comb1 + y_top_comb2) / 2.0, 3))
    bot_mid = (round((bot_x1 + bot_x2) / 2.0, 3), round((y_bot_comb1 + y_bot_comb2) / 2.0, 3))

    return {
        "D": top_mid if drain_side == "top" else bot_mid,
        "S": bot_mid if drain_side == "top" else top_mid,
        "G": g_port,
        "bbox": (x0, gy1, round(x0 + total_w, 3), gy2),
        "active_bbox": (x0, y1, round(x0 + total_w, 3), y2),
        "top_span": (top_x1, top_x2, y_top_comb1, y_top_comb2),
        "bot_span": (bot_x1, bot_x2, y_bot_comb1, y_bot_comb2),
    }


def build_varactor_cell() -> LayoutCanvas:
    c = LayoutCanvas("pll_vco_varactor")
    W_CELL, H_CELL = 8.80, 9.60
    Y_ACT1, Y_ACT2 = 2.20, 7.40
    X_ACT1, X_ACT2 = 1.65, 7.15
    gate_cxs = [2.60, 3.80, 5.00, 6.20]
    sd_cxs = [2.00, 3.20, 4.40, 5.60, 6.80]

    c.R("pwell", 0.00, 0.00, W_CELL, H_CELL)
    c.R("nwell", 1.20, 1.30, 7.60, 8.30)
    c.R("nsubdiff", X_ACT1, Y_ACT1, X_ACT2, Y_ACT2)

    for gx in gate_cxs:
        c.R("poly", gx - 0.25, 1.60, gx + 0.25, 8.00)
        c.R("varactor", gx - 0.25, Y_ACT1, gx + 0.25, Y_ACT2)
        for gcy in (1.85, 7.75):
            c.sq("polycont", gx, gcy, 0.17)
            c.sq("viali", gx, gcy, 0.17)

    for layer in ("locali", "m1"):
        c.R(layer, 1.25, 1.65, 7.55, 2.05)
        c.R(layer, 1.25, 7.55, 7.55, 7.95)
        c.R(layer, 1.25, 1.65, 1.55, 7.95)
        c.R(layer, 7.25, 1.65, 7.55, 7.95)
    c.R("m1", 1.05, 4.50, 1.55, 5.10)
    c.R("m1", 7.25, 4.50, 7.75, 5.10)

    contact_ys = [round(4.80 + k * 0.36, 3) for k in range(-6, 7)]
    for sx in sd_cxs:
        c.R("locali", sx - 0.17, 2.30, sx + 0.17, 7.30)
        c.R("m1", sx - 0.16, 2.30, sx + 0.16, 7.30)
        for cy in contact_ys:
            c.sq("nsubdiffcont", sx, cy, 0.17)
            c.sq("viali", sx, cy, 0.17)
        for vcy in (2.64, 6.96):
            c.sq_wh("m1", sx, vcy, 0.38, 0.38)
            c.sq("via1", sx, vcy, 0.26)
            c.sq_wh("m2", sx, vcy, 0.38, 0.38)
        c.R("m2", sx - 0.18, 1.05, sx + 0.18, 8.55)

    c.R("m2", 1.82, 1.05, 6.98, 1.45)
    c.R("m2", 1.82, 8.15, 6.98, 8.55)

    for x1, y1, x2, y2 in [(0.25, 0.25, 8.55, 0.75), (0.25, 8.85, 8.55, 9.35),
                           (0.25, 0.25, 0.75, 9.35), (8.05, 0.25, 8.55, 9.35)]:
        c.R("psubdiff", x1, y1, x2, y2)
        c.R("locali", x1 + 0.06, y1 + 0.06, x2 - 0.06, y2 - 0.06)
        c.R("m1", x1 + 0.05, y1 + 0.05, x2 - 0.05, y2 - 0.05)

    for k in range(19):
        cx = round(0.50 + k * 0.433, 3)
        if cx <= 8.30:
            for cy in (0.50, 9.10):
                c.sq("psubdiffcont", cx, cy, 0.17)
                c.sq("viali", cx, cy, 0.17)
    for k in range(1, 19):
        cy = round(0.50 + k * 0.45, 3)
        if cy <= 8.65:
            for cx in (0.50, 8.30):
                c.sq("psubdiffcont", cx, cy, 0.17)
                c.sq("viali", cx, cy, 0.17)

    for dx in (0.95, 7.85):
        c.R("poly", dx - 0.15, 0.35, dx + 0.15, 9.25)
        for dcy in (0.50, 9.10):
            c.sq("polycont", dx, dcy, 0.17)
            c.R("locali", min(dx - 0.17, 0.50), dcy - 0.17, max(dx + 0.17, 8.30 if dx > 4 else 0.70), dcy + 0.17)

    c.L("node", 1.25, 4.80, "m1")
    c.L("vctrl", 4.40, 8.35, "m2")
    c.L("vss", 0.50, 0.50, "m1")
    return c


def draw_high_po_res(c: LayoutCanvas, xc: float, y_bot: float, l_body: float, w_res: float = 2.85) -> dict:
    """
    Draw a clean 3-terminal sky130_fd_pr__res_high_po_2p85 (or 1p41) resistor strip with
    top R1 (VDD side) and bottom R2 (Drain/Output side) multi-contact M1+M2 terminals.
    """
    hw = w_res / 2.0
    head_h = 2.10
    total_h = round(l_body + 2 * head_h, 3)
    y1, y2 = round(y_bot, 3), round(y_bot + total_h, 3)

    c.R("poly", xc - hw, y1, xc + hw, y2)
    c.R("xhrpoly", xc - hw - 0.20, y1, xc + hw + 0.20, y2)

    # Bottom terminal R2 and Top terminal R1 contact arrays
    r2_cy = round(y1 + 1.00, 3)
    r1_cy = round(y2 - 1.00, 3)
    n_rcuts = max(2, int((w_res - 0.40) / 0.40))
    span_x = (n_rcuts - 1) * 0.40
    for term_cy in (r2_cy, r1_cy):
        c.R("xpolycontact", xc - hw + 0.18, term_cy - 0.65, xc + hw - 0.18, term_cy + 0.65)
        c.R("locali", xc - hw + 0.12, term_cy - 0.70, xc + hw - 0.12, term_cy + 0.70)
        c.R("m1", xc - hw + 0.10, term_cy - 0.72, xc + hw - 0.10, term_cy + 0.72)
        c.R("m2", xc - hw + 0.10, term_cy - 0.50, xc + hw - 0.10, term_cy + 0.50)
        for ix in range(n_rcuts):
            cut_x = round(xc - span_x / 2.0 + ix * 0.40, 3)
            for dy in (-0.32, 0.32):
                c.sq("polycont", cut_x, round(term_cy + dy, 3), 0.17)
                c.sq("viali", cut_x, round(term_cy + dy, 3), 0.17)
            c.via1(cut_x, term_cy, pad=0.36)

    return {"R1": (xc, r1_cy), "R2": (xc, r2_cy), "bbox": (xc - hw, y1, xc + hw, y2)}


def build_cml_stage(
    cell_name: str,
    pair_nf: int,
    pair_wf: float,
    tail_nf: int,
    tail_wf: float,
    tail_l: float,
    load_l: float,
    n_loads_per_side: int,
    out_a: str,
    out_b: str,
) -> LayoutCanvas:
    """
    Build a strictly mirror-symmetric CML stage (`pll_vco_delay_stage` or `serdes_cml_buffer`):
      - Bottom row: Centered Tail current source (`Xtail`: nf x tail_wf, l=tail_l), Drain Comb on top (`tail`), Source Comb on bottom (`vss`)
      - Middle row: Symmetric Differential Pair (`Xmp` on left, `Xmn` on right: pair_nf x pair_wf, l=0.15 LVT),
        with Drain Comb on TOP (going straight up into loads!) and Source Comb on BOTTOM (merged directly into `tail` node!)
      - Top row: High-poly load resistors (`Xrp1..n` above `Xmp`, `Xrn1..n` above `Xmn`), R2 on bottom (tied to Drain Comb = `outp/outn`),
        R1 on top (tied to top horizontal `vdd` M2/M3 rail)
      - Full perimeter P+ substrate guard ring (`vss`).
    """
    c = LayoutCanvas(cell_name)

    # Calculate geometry widths so left/right are 100% symmetric around X_MID = 12.0
    X_MID = 12.00
    pair_pitch = 0.48 + 0.15
    pair_w = round(0.48 * 2 + pair_nf * 0.15 + (pair_nf - 1) * 0.48, 3)
    tail_pitch = 0.48 + tail_l
    tail_w = round(0.48 * 2 + tail_nf * tail_l + (tail_nf - 1) * 0.48, 3)

    gap_pairs = 2.20
    x_mp = round(X_MID - gap_pairs / 2.0 - pair_w, 3)
    x_mn = round(X_MID + gap_pairs / 2.0, 3)
    x_tail = round(X_MID - tail_w / 2.0, 3)

    y_tail = 2.20
    y_pair = round(y_tail + tail_wf + 2.80, 3)
    y_load = round(y_pair + pair_wf + 1.80, 3)

    # Draw Tail (Drain on top -> 'tail', Source on bottom -> 'vss', Gate at bottom -> 'vbias')
    tail_info = draw_comb_mos(
        c, "n", tail_wf, tail_nf, tail_l, x_tail, y_tail,
        lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=True
    )

    # Draw Differential Pair Mp (left) and Mn (right)
    # Drain on TOP -> out_a / out_b, Source on BOTTOM -> 'tail', Gate at bottom -> 'inp' / 'inn'
    mp_info = draw_comb_mos(
        c, "n", pair_wf, pair_nf, 0.15, x_mp, y_pair,
        lvt=True, drain_side="top", gate_strap="bottom", dummy_ends=True
    )
    mn_info = draw_comb_mos(
        c, "n", pair_wf, pair_nf, 0.15, x_mn, y_pair,
        lvt=True, drain_side="top", gate_strap="bottom", dummy_ends=True
    )

    # Connect Tail Drain Comb (top of Tail) to Mp & Mn Source Combs (bottom of Mp/Mn) via wide symmetric M2 H-bar ('tail' node)
    y_tail_bus = round((tail_info["D"][1] + mp_info["S"][1]) / 2.0, 3)
    c.R("m2", mp_info["S"][0] - 0.35, y_tail_bus - 0.30, mn_info["S"][0] + 0.35, y_tail_bus + 0.30)
    c.R("m2", mp_info["S"][0] - 0.35, y_tail_bus - 0.30, mp_info["S"][0] + 0.35, mp_info["S"][1] + 0.15)
    c.R("m2", mn_info["S"][0] - 0.35, y_tail_bus - 0.30, mn_info["S"][0] + 0.35, mn_info["S"][1] + 0.15)
    c.R("m2", tail_info["D"][0] - 0.45, tail_info["D"][1] - 0.15, tail_info["D"][0] + 0.45, y_tail_bus + 0.30)
    c.L("tail", X_MID, y_tail_bus, "m2")

    # Route inp / inn from Mp/Mn Gate straps out to left/right M3 input pins
    for g_info, side_dir, pin_nm in ((mp_info, -1, "inp"), (mn_info, 1, "inn")):
        gx, gy = g_info["G"]
        c.via1(gx, gy, pad=0.38)
        c.via2(gx, gy, pad=0.42)
        px_out = round(x_mp - 1.40, 3) if side_dir < 0 else round(x_mn + pair_w + 1.40, 3)
        c.R("m3", min(gx, px_out) - 0.20, gy - 0.20, max(gx, px_out) + 0.20, gy + 0.20)
        c.L(pin_nm, px_out, gy, "m3")

    # Route vbias from Tail Gate strap out to left M3 pin
    tgx, tgy = tail_info["G"]
    c.via1(tgx, tgy, pad=0.38)
    c.via2(tgx, tgy, pad=0.42)
    vb_x = round(x_mp - 1.40, 3)
    c.R("m3", vb_x - 0.20, tgy - 0.20, tgx + 0.20, tgy + 0.20)
    c.L("vbias", vb_x, tgy, "m3")

    # Draw High-Poly Load Resistors directly above Mp and Mn Drain Combs
    r1_ys = []
    for p_info, out_nm in ((mp_info, out_a), (mn_info, out_b)):
        dx, dy = p_info["D"]
        if n_loads_per_side == 1:
            load_xs = [dx]
        else:
            load_xs = [round(dx - 1.85, 3), round(dx + 1.85, 3)]
        r2_list, r1_list = [], []
        for lx in load_xs:
            res = draw_high_po_res(c, lx, y_load, load_l, w_res=2.85)
            r2_list.append(res["R2"])
            r1_list.append(res["R1"])
            r1_ys.append(res["R1"][1])
        # Tie R2 terminals together and straight down on wide M2 to Drain Comb ('outp' / 'outn')
        r2_y = r2_list[0][1]
        rx_min = min(p[0] for p in r2_list) - 0.50
        rx_max = max(p[0] for p in r2_list) + 0.50
        c.R("m2", rx_min, r2_y - 0.35, rx_max, r2_y + 0.35)
        c.R("m2", dx - 0.45, dy - 0.15, dx + 0.45, r2_y + 0.35)
        c.via2(dx, round((dy + r2_y) / 2.0, 3), pad=0.48)
        c.L(out_nm, dx, round((dy + r2_y) / 2.0, 3), "m2")

        # Tie R1 terminals up to VDD rail
        r1_y = r1_list[0][1]
        c.R("m2", rx_min, r1_y - 0.35, rx_max, r1_y + 0.35)
        c.R("m2", dx - 0.45, r1_y, dx + 0.45, r1_y + 1.60)

    # Top VDD M2 + M3 Power Bus & Bottom VSS M1 + M2 Ground Bus + Full P+ Guard Ring
    y_vdd = round(max(r1_ys) + 1.35, 3)
    x_left_gr = round(x_mp - 2.40, 3)
    x_right_gr = round(x_mn + pair_w + 2.40, 3)
    y_bot_gr = 0.30
    y_top_gr = round(y_vdd + 0.90, 3)

    c.R("pwell", x_left_gr - 0.25, y_bot_gr - 0.25, x_right_gr + 0.25, y_top_gr + 0.25)

    # VDD horizontal bus at top
    c.R("m2", x_left_gr + 0.60, y_vdd - 0.40, x_right_gr - 0.60, y_vdd + 0.40)
    c.R("m3", x_left_gr + 0.60, y_vdd - 0.40, x_right_gr - 0.60, y_vdd + 0.40)
    c.via2(X_MID, y_vdd, pad=0.50)
    c.L("vdd", X_MID, y_vdd, "m3")

    # Full P+ substrate guard ring (vss) around the cell + connection to Tail Source Comb
    gr_w = 0.50
    for gx1, gy1, gx2, gy2 in [
        (x_left_gr, y_bot_gr, x_right_gr, y_bot_gr + gr_w),
        (x_left_gr, y_top_gr - gr_w, x_right_gr, y_top_gr),
        (x_left_gr, y_bot_gr, x_left_gr + gr_w, y_top_gr),
        (x_right_gr - gr_w, y_bot_gr, x_right_gr, y_top_gr),
    ]:
        c.R("psubdiff", gx1, gy1, gx2, gy2)
        c.R("locali", gx1 + 0.05, gy1 + 0.05, gx2 - 0.05, gy2 - 0.05)
        c.R("m1", gx1 + 0.05, gy1 + 0.05, gx2 - 0.05, gy2 - 0.05)

    # Connect Tail Source Comb straight down to bottom VSS guard ring
    tsx, tsy = tail_info["S"]
    c.R("m1", tsx - 0.50, y_bot_gr + 0.10, tsx + 0.50, tsy + 0.15)
    c.R("m2", tsx - 0.50, y_bot_gr + 0.10, tsx + 0.50, tsy + 0.15)
    c.R("m2", x_left_gr, y_bot_gr, x_right_gr, y_bot_gr + gr_w)
    c.via1(tsx, y_bot_gr + 0.25, pad=0.38)
    c.L("vss", tsx, y_bot_gr + 0.25, "m2")

    return c


def build_cap_unit_cell() -> LayoutCanvas:
    """
    Build `pll_vco_cap_unit`:
      - Top: MIM 2.0 x 2.0 (or 2.35 x 2.5) capacitor (`capm` top plate = `node` on M4, `m3` bottom plate = `plate`)
      - Bottom: Folded 2-finger NMOS switch (`nf=2, w_finger=1.25/0.75, l=0.15`) sharing central Drain strip electrode (`plate`)
        and outer Source strip electrodes (`vss`), with bottom Gate strap (`en`) and P+ guard tap (`vss`).
    """
    c = LayoutCanvas("pll_vco_cap_unit")
    c.R("pwell", 0.00, 0.00, 7.60, 9.60)

    # 1. Bottom: 2-finger folded NMOS switch (center finger = shared Drain 'plate', outer fingers = Source 'vss')
    sw = draw_comb_mos(
        c, "n", w_finger=1.60, nf=2, l_gate=0.15, x0=2.30, y0=2.10,
        lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=True, sd_width=0.48
    )

    # Bottom VSS rail + P+ substrate tap bar (y in [0.20, 0.60], well below gate strap at y=1.06!)
    c.R("psubdiff", 0.40, 0.20, 7.20, 0.60)
    c.R("locali", 0.45, 0.25, 7.15, 0.55)
    c.R("m1", 0.40, 0.20, 7.20, 0.60)
    c.R("m2", 0.40, 0.20, 7.20, 0.60)
    for k in range(14):
        cx = round(0.75 + k * 0.46, 3)
        c.sq("psubdiffcont", cx, 0.40, 0.17)
        c.sq("viali", cx, 0.40, 0.17)
    # Tie switch Source Comb (y=1.62) to right-side M2 ground drop down to VSS rail (avoiding gate strap at y=1.06)
    sx, sy = sw["S"]
    c.R("m2", sx, sy - 0.18, 5.40, sy + 0.18)
    c.R("m2", 5.05, 0.25, 5.45, sy + 0.18)

    # Switch Gate ('en') brought out cleanly to left M2/M3 landing pad at (1.25, 1.06)
    gx, gy = sw["G"]
    c.via1(gx, gy, pad=0.34)
    c.R("m2", 1.05, gy - 0.18, gx + 0.18, gy + 0.18)
    c.via2(1.25, gy, pad=0.40)

    # 2. Top: MIM Capacitor (M3 bottom plate -> 'plate', CAPM + M4 top plate -> 'node')
    c.R("m3", 2.10, 5.10, 5.90, 8.90)
    c.R("mimcap", 2.40, 5.40, 5.40, 8.60)
    for mcx in (3.10, 3.90, 4.70):
        for mcy in (6.10, 7.00, 7.90):
            c.sq("mimcapcontact", mcx, mcy, 0.20)
            c.sq("via3", mcx, mcy, 0.32)
    c.R("m4", 2.70, 5.70, 6.80, 8.30)

    # Connect MIM bottom plate (M3) down to Switch Drain Comb ('plate' on M2) at y = 4.55
    dx, dy = sw["D"]
    c.R("m2", dx - 0.25, dy, dx + 0.25, 5.35)
    c.via2(dx, 5.22, pad=0.42)

    c.L("node", 6.50, 7.00, "m4")
    c.L("plate", dx, 4.65, "m2")
    c.L("en", 1.25, gy, "m3")
    c.L("vss", 0.80, 0.40, "m2")
    return c


def build_cap_bank_array(nbits: int = 4) -> LayoutCanvas:
    """
    Build `pll_vco_cap_bank` using the 2^N Binary Column-Slice Floorplan:
      - For 4-bit (15 units, 1:2:4:8 on b0..b3): 4 rows x 4 columns (16 slots = 15 active + 1 dummy at (0,0))
          Col 0: row 0 = dummy(vss), row 1 = b0 (1), row 2..3 = b1 (2)
          Col 1: row 0..3 = b2 (4)
          Col 2 & Col 3: row 0..3 = b3 (8)
      - For 5-bit (31 units, 1:2:4:8:16 on b0..b4): 8 rows x 4 columns (32 slots = 31 active + 1 dummy at (0,0))
          Col 0: row 0 = dummy(vss), row 1 = b0 (1), row 2..3 = b1 (2), row 4..7 = b2 (4)
          Col 1: row 0..7 = b3 (8)
          Col 2 & Col 3: row 0..7 = b4 (16)
    Notice why this floorplan is 100% immune to cross-column bit shorts:
      Every bit occupies a strictly contiguous vertical segment of its column's M3 `en` spine!
      Zero horizontal cross-column `en` wires are needed between different bits!
    """
    cell_name = f"pll_vco_cap_bank_{nbits}b"
    c = LayoutCanvas(cell_name)
    unit = build_cap_unit_cell()

    n_rows = 4 if nbits == 4 else 8
    n_cols = 4
    pitch_x, pitch_y = 8.40, 9.60

    # Bit assignment for (row, col)
    def slot_bit(r: int, col: int) -> str:
        if nbits == 4:
            if col == 0:
                if r == 0: return "vss"   # dummy cell tied to vss
                if r == 1: return "b0"
                return "b1"
            elif col == 1:
                return "b2"
            else:
                return "b3"
        else:
            if col == 0:
                if r == 0: return "vss"   # dummy cell tied to vss
                if r == 1: return "b0"
                if r in (2, 3): return "b1"
                return "b2"
            elif col == 1:
                return "b3"
            else:
                return "b4"

    # Place all units in the grid
    for col in range(n_cols):
        for r in range(n_rows):
            dx, dy = round(col * pitch_x, 3), round(r * pitch_y, 3)
            c.include_subcell(unit, dx=dx, dy=dy, include_labels=False)

    total_w = round(n_cols * pitch_x, 3)
    total_h = round(n_rows * pitch_y, 3)

    # 1. Continuous VSS ground grid (M2 horizontal row rails + left/right vertical M2 ground spines)
    c.R("m2", 0.20, 0.20, 0.85, total_h - 0.35)
    c.R("m2", total_w - 0.85, 0.20, total_w - 0.20, total_h - 0.35)
    for r in range(n_rows):
        ry = round(r * pitch_y + 0.40, 3)
        c.R("m2", 0.20, ry - 0.22, total_w - 0.20, ry + 0.22)
    c.L("vss", 0.50, 0.45, "m2")

    # 2. Pure M4 RF Tank ('node') Vertical Column Trunks + Top Horizontal M4 Collector Bus
    # Each unit's MIM top plate already exits on M4 at x = col*pitch_x + 6.50, y in [5.20..7.80]
    # No VIA2 or M2 is touched -> zero possibility of shorting to 'plate'!
    y_node_top = round(total_h + 0.60, 3)
    for col in range(n_cols):
        nx = round(col * pitch_x + 6.50, 3)
        c.R("m4", nx - 0.35, 5.20, nx + 0.35, y_node_top + 0.35)
    c.R("m4", 6.15, y_node_top - 0.40, round((n_cols - 1) * pitch_x + 6.85, 3), y_node_top + 0.40)
    c.L("node", round(total_w / 2.0, 3), y_node_top, "m4")

    # 3. Contiguous Vertical M3 Spines for b0..b3/b4 along each column's `en` track (x = col*pitch_x + 1.25)
    # Tie dummy slot (0,0) `en` to VSS at bottom-left
    c.R("m2", 0.40, 0.45, 1.45, 1.15)

    # Col 0 segmented vertical M3 spines:
    en_x0 = 1.25
    en_y_off = 1.06
    # b0: row 1 only -> bring out to left M3 pin
    y_b0 = round(1 * pitch_y + en_y_off, 3)
    c.R("m3", -0.60, y_b0 - 0.22, en_x0 + 0.22, y_b0 + 0.22)
    c.L("b0", -0.40, y_b0, "m3")

    # b1: rows 2..3 contiguous vertical M3 spine in Col 0
    y_b1_1, y_b1_2 = round(2 * pitch_y + en_y_off, 3), round(3 * pitch_y + en_y_off, 3)
    c.R("m3", en_x0 - 0.22, y_b1_1 - 0.22, en_x0 + 0.22, y_b1_2 + 0.22)
    c.R("m3", -0.60, y_b1_2 - 0.22, en_x0 + 0.22, y_b1_2 + 0.22)
    c.L("b1", -0.40, y_b1_2, "m3")

    if nbits == 4:
        # Col 1 (rows 0..3): b2 contiguous vertical M3 spine
        en_x1 = round(1 * pitch_x + 1.25, 3)
        yb_lo, yb_hi = round(0 * pitch_y + en_y_off, 3), round(3 * pitch_y + en_y_off, 3)
        c.R("m3", en_x1 - 0.22, yb_lo - 0.22, en_x1 + 0.22, total_h + 1.60)
        c.L("b2", en_x1, round(total_h + 1.40, 3), "m3")

        # Col 2 & Col 3 (rows 0..3): b3 contiguous vertical M3 spines bridged at top on M3
        en_x2 = round(2 * pitch_x + 1.25, 3)
        en_x3 = round(3 * pitch_x + 1.25, 3)
        for ex in (en_x2, en_x3):
            c.R("m3", ex - 0.22, yb_lo - 0.22, ex + 0.22, total_h + 1.60)
        c.R("m3", en_x2 - 0.22, total_h + 1.20, en_x3 + 0.22, total_h + 1.65)
        c.L("b3", round((en_x2 + en_x3) / 2.0, 3), round(total_h + 1.42, 3), "m3")
    else:
        # 5-bit: Col 0 rows 4..7 = b2
        y_b2_1, y_b2_2 = round(4 * pitch_y + en_y_off, 3), round(7 * pitch_y + en_y_off, 3)
        c.R("m3", en_x0 - 0.22, y_b2_1 - 0.22, en_x0 + 0.22, total_h + 1.60)
        c.L("b2", en_x0, round(total_h + 1.40, 3), "m3")

        # Col 1 rows 0..7 = b3
        en_x1 = round(1 * pitch_x + 1.25, 3)
        yb_lo = round(0 * pitch_y + en_y_off, 3)
        c.R("m3", en_x1 - 0.22, yb_lo - 0.22, en_x1 + 0.22, total_h + 1.60)
        c.L("b3", en_x1, round(total_h + 1.40, 3), "m3")

        # Col 2 & Col 3 rows 0..7 = b4
        en_x2 = round(2 * pitch_x + 1.25, 3)
        en_x3 = round(3 * pitch_x + 1.25, 3)
        for ex in (en_x2, en_x3):
            c.R("m3", ex - 0.22, yb_lo - 0.22, ex + 0.22, total_h + 1.60)
        c.R("m3", en_x2 - 0.22, total_h + 1.20, en_x3 + 0.22, total_h + 1.65)
        c.L("b4", round((en_x2 + en_x3) / 2.0, 3), round(total_h + 1.42, 3), "m3")

    return c


if __name__ == "__main__":
    for sub in ("01_varactor", "02_delay_stage_and_buffer", "03_cap_bank"):
        (PACK_DIR / sub).mkdir(parents=True, exist_ok=True)

    # 1. Varactor
    var_c = build_varactor_cell()
    var_c.save_tcl(PACK_DIR / "01_varactor/pll_vco_varactor.tcl")
    var_c.save_mag(PACK_DIR / "01_varactor/pll_vco_varactor.mag")

    # 2. Delay Stage (r6: 2 parallel loads per side) & CML Buffer (1 load per side)
    ds_c = build_cml_stage(
        "pll_vco_delay_stage",
        pair_nf=8, pair_wf=5.0, tail_nf=4, tail_wf=6.3, tail_l=0.50,
        load_l=4.77, n_loads_per_side=2, out_a="outp", out_b="outn"
    )
    ds_c.save_tcl(PACK_DIR / "02_delay_stage_and_buffer/pll_vco_delay_stage.tcl")
    ds_c.save_mag(PACK_DIR / "02_delay_stage_and_buffer/pll_vco_delay_stage.mag")

    buf_c = build_cml_stage(
        "serdes_cml_buffer",
        pair_nf=4, pair_wf=3.0, tail_nf=4, tail_wf=3.0, tail_l=0.50,
        load_l=4.22, n_loads_per_side=1, out_a="outn", out_b="outp"
    )
    buf_c.save_tcl(PACK_DIR / "02_delay_stage_and_buffer/serdes_cml_buffer.tcl")
    buf_c.save_mag(PACK_DIR / "02_delay_stage_and_buffer/serdes_cml_buffer.mag")

    # Render Delay Stage & Buffer figure
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 7.5), dpi=170)
    plot_canvas(
        ax1, ds_c,
        f"pll_vco_delay_stage ({ds_c.bbox()[2]-ds_c.bbox()[0]:.1f} x {ds_c.bbox()[3]-ds_c.bbox()[1]:.1f} um)",
        "Comb Strip Electrodes (nf=8x5um LVT) + Dual Loads (2x l=4.77)"
    )
    plot_canvas(
        ax2, buf_c,
        f"serdes_cml_buffer ({buf_c.bbox()[2]-buf_c.bbox()[0]:.1f} x {buf_c.bbox()[3]-buf_c.bbox()[1]:.1f} um)",
        "Comb Strip Electrodes (nf=4x3um LVT) + High-Po Loads (l=4.22)"
    )
    handles, labels = ax1.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=7, frameon=True, fontsize=8.5, bbox_to_anchor=(0.5, 0.01))
    plt.tight_layout(rect=[0, 0.06, 1, 1])
    fig.savefig(PACK_DIR / "02_delay_stage_and_buffer/vco_delay_stage_and_buffer.png", dpi=170)
    plt.close(fig)

    # 3. Cap Unit & Cap Bank (4b and 5b)
    cu_c = build_cap_unit_cell()
    cu_c.save_tcl(PACK_DIR / "03_cap_bank/pll_vco_cap_unit.tcl")
    cu_c.save_mag(PACK_DIR / "03_cap_bank/pll_vco_cap_unit.mag")

    cb4_c = build_cap_bank_array(nbits=4)
    cb4_c.save_tcl(PACK_DIR / "03_cap_bank/pll_vco_cap_bank_4b.tcl")
    cb4_c.save_mag(PACK_DIR / "03_cap_bank/pll_vco_cap_bank_4b.mag")

    cb5_c = build_cap_bank_array(nbits=5)
    cb5_c.save_tcl(PACK_DIR / "03_cap_bank/pll_vco_cap_bank_5b.tcl")
    cb5_c.save_mag(PACK_DIR / "03_cap_bank/pll_vco_cap_bank_5b.mag")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 7.5), dpi=170)
    plot_canvas(
        ax1, cu_c,
        f"pll_vco_cap_unit ({cu_c.bbox()[2]-cu_c.bbox()[0]:.1f} x {cu_c.bbox()[3]-cu_c.bbox()[1]:.1f} um)",
        "MIM Top Plate -> M4 'node', Bottom Plate -> M3/M2 'plate', 2-Finger Folded Switch -> 'vss'"
    )
    plot_canvas(
        ax2, cb4_c,
        f"pll_vco_cap_bank_4b (4x4 Binary Column-Slice Grid, {cb4_c.bbox()[2]-cb4_c.bbox()[0]:.1f} x {cb4_c.bbox()[3]-cb4_c.bbox()[1]:.1f} um)",
        "Col0: Dummy+b0(1)+b1(2) | Col1: b2(4) | Col2-3: b3(8) -> Zero Cross-Column 'en' Shorts!"
    )
    handles, labels = ax2.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=7, frameon=True, fontsize=8.5, bbox_to_anchor=(0.5, 0.01))
    plt.tight_layout(rect=[0, 0.06, 1, 1])
    fig.savefig(PACK_DIR / "03_cap_bank/vco_cap_unit_and_bank.png", dpi=170)
    plt.close(fig)
    print("Built VCO sub-blocks successfully.")
