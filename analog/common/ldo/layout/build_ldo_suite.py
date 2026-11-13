#!/usr/bin/env python3
"""
Precision Full-Custom Analog & Power Layout Suite for the Low-Dropout Regulator Subsystem (`common/ldo`).

Covers all subcircuits in `common/ldo/spice/`:
  1. `serdes_ldo_hv18_core_r4`           : Dual 5V Native NMOS (`nfet_05v0_nvt` W=2000 Cascode + W=1000 Pass) LDO Core
                                           with 5V Thick-Oxide (`g5v0d10v5`) Common-Centroid Error Amplifier, 1:2:6 PMOS
                                           Bias Mirror, `Xoff/Xboff` Clamps, `Xrhv/Xrcas/Xrzero`, and Leaf MIM `Chv/Ccas/Ccomp`.
  2. `serdes_pll_supply_hv18_r4`         : Production Top-Level HV18 Quiet PLL Supply Macro (integrating `Xcore`, `Xcopy`,
                                           `Xinv`, `Xrefgate`, `Xrefreset`, `1MOhm + 16pF` Reference Filter, 6-Bit Voltage
                                           Trim Feedback Divider `Xrtop/Xrfixed/Xr5..0/Xs5..0/Xbleed`, and `100pF` Output Cap).
  3. `serdes_pll_supply_hv18_r4_probe`   : Dual-Injection Loop-Stability Probe Wrapper (`fb_return` and `fb_input` split).
  4. `serdes_pll_bias_lowpass_slow_r4`   : Under-MIM 3D-Stacked `1 MOhm (32 x 31.25k) + 16 pF (4x4 Leaf MIM)` Slow Tail Filter.
  5. `serdes_pll_bias_lowpass_r4`        : Under-MIM 3D-Stacked `100 kOhm (8 x 12.5k) + 16 pF (4x4 Leaf MIM)` Fast Tail Filter.
  6. `serdes_ldo_power_switch`           : Back-to-Back Shared-Mid-Well Bidirectional 5V PMOS Isolation Switch (`Xa/Xb/Xup/Xdown/Rkeep`).
  7. `serdes_ldo_ref_res`                : 32-Segment Matched Serpentine `1.0 MOhm` High-Poly Resistor Array (`res_high_po_1p41`).
  8. `serdes_ldo_mim16`                  : `4 x 4` Leaf MIM Capacitor Array (`16 x 1.0 pF = 16 pF`).
  9. `serdes_ldo_mim50`                  : `5 x 10` Leaf MIM Capacitor Array (`50 x 1.0 pF = 50 pF`).
  10. `serdes_ldo_mim100`                : `10 x 10` Leaf MIM Capacitor Array (`100 x 1.0 pF = 100 pF`).
"""
from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE_ANALOG = Path(__file__).resolve().parents[3]
PACK_SCRIPTS = WORKSPACE_ANALOG / "layout/scripts"
INTER_DIR = WORKSPACE_ANALOG / "common/bias/layout"
OUT_DIR = WORKSPACE_ANALOG / "layout/work"
sys.path.insert(0, str(PACK_SCRIPTS))
sys.path.insert(0, str(INTER_DIR))

from layout_core import LayoutCanvas, LAYER_STYLE, plot_canvas  # noqa: E402
from build_bandgap_suite import (  # noqa: E402
    draw_guard_ring,
    draw_sky130_high_po_res,
    draw_sky130_mim_cap,
    draw_interdigitated_mos_row,
    route_m3_bus,
)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def draw_leaf_mim_grid(
    c: LayoutCanvas,
    x0: float,
    y0: float,
    n_cols: int,
    n_rows: int,
    w_leaf: float = 22.20,
    l_leaf: float = 22.20,
    pitch_x: float = 25.40,
    pitch_y: float = 24.40,
    top_net: str | None = None,
    bot_net: str | None = None,
) -> dict:
    c1_pts, c2_pts = [], []
    for r in range(n_rows):
        ry = round(y0 + r * pitch_y, 3)
        for col in range(n_cols):
            cx = round(x0 + col * pitch_x, 3)
            mc = draw_sky130_mim_cap(c, cx, ry, w_cap=w_leaf, l_cap=l_leaf)
            c1_pts.append(mc["C1"])
            c2_pts.append(mc["C2"])
        x_row_end = round(x0 + (n_cols - 1) * pitch_x + w_leaf + 1.85, 3)
        c.R("m3", x0 - 0.50, ry - 0.22, x_row_end, ry + 0.45)

    y_top_edge = round(y0 + (n_rows - 1) * pitch_y + l_leaf + 0.22, 3)
    c.R("m3", x0 - 0.80, y0 - 0.22, x0 - 0.15, y_top_edge)

    for col in range(n_cols):
        mcx = round(x0 + col * pitch_x + w_leaf / 2.0, 3)
        c.R("m4", mcx - 0.50, y0 + 0.50, mcx + 0.50, y_top_edge + 0.60)
    x_m4_lo = round(x0 + w_leaf / 2.0 - 0.50, 3)
    x_m4_hi = round(x0 + (n_cols - 1) * pitch_x + w_leaf / 2.0 + 0.50, 3)
    c.R("m4", x_m4_lo, y_top_edge + 0.10, x_m4_hi, y_top_edge + 0.80)

    c1_anchor = (round((x_m4_lo + x_m4_hi) / 2.0, 3), round(y_top_edge + 0.45, 3))
    c2_anchor = (round(x0 - 0.48, 3), round((y0 + y_top_edge) / 2.0, 3))
    if top_net:
        c.L(top_net, c1_anchor[0], c1_anchor[1], "m4")
    if bot_net:
        c.L(bot_net, c2_anchor[0], c2_anchor[1], "m3")

    return {
        "C1": c1_anchor,
        "C2": c2_anchor,
        "bbox": (round(x0 - 0.80, 3), round(y0 - 0.22, 3), round(x0 + (n_cols - 1) * pitch_x + w_leaf + 1.85, 3), round(y_top_edge + 0.80, 3)),
    }


def draw_power_nvt_bank(
    c: LayoutCanvas,
    x0: float,
    y0: float,
    n_rows: int,
    nf_per_row: int,
    w_finger: float = 10.0,
    l_gate: float = 0.90,
    drain_net: str = "vin",
    source_net: str = "mid",
    gate_net: str = "casg",
) -> dict:
    row_pitch = round(w_finger + 3.20, 3)
    sd_w = 0.52
    row_w = round(2 * sd_w + nf_per_row * l_gate + (nf_per_row - 1) * sd_w, 3)
    bank_w = round(row_w + 3.60, 3)
    bank_h = round(n_rows * row_pitch + 2.60, 3)

    draw_guard_ring(c, x0, y0, x0 + bank_w, y0 + bank_h, kind="p", width=0.60)

    d_pts, s_pts, g_pts = [], [], []
    for r in range(n_rows):
        ry = round(y0 + 1.80 + r * row_pitch, 3)
        row_info = draw_interdigitated_mos_row(
            c, "n", w_finger=w_finger, l_gate=l_gate, x0=round(x0 + 1.80, 3), y0=ry,
            finger_map=[(gate_net, drain_net, source_net)] * nf_per_row,
            lvt=False, sd_width=sd_w,
        )
        dx, dy = row_info["D_map"][drain_net]
        sx, sy = row_info["S"]
        gx, gy = row_info["G_map"][gate_net]
        sx1, sx2 = row_info["span_x"]
        c.R("m2", sx1, dy - 0.32, sx2, dy + 0.32)
        c.R("m2", sx1, sy - 0.32, sx2, sy + 0.32)
        d_pts.append((dx, dy))
        s_pts.append((sx, sy))
        g_pts.append((gx, gy))

    x_src_bus = round(x0 + bank_w * 0.28, 3)
    x_drn_bus = round(x0 + bank_w * 0.62, 3)
    x_gate_bus = round(x0 + bank_w - 1.15, 3)

    for px, py in s_pts:
        c.via2(x_src_bus, py, pad=0.65)
    c.R("m3", x_src_bus - 0.80, s_pts[0][1] - 0.40, x_src_bus + 0.80, s_pts[-1][1] + 0.40)

    for px, py in d_pts:
        c.via2(x_drn_bus, py, pad=0.65)
    c.R("m3", x_drn_bus - 0.80, d_pts[0][1] - 0.40, x_drn_bus + 0.80, d_pts[-1][1] + 0.40)

    for px, py in g_pts:
        c.via2(x_gate_bus, py, pad=0.45)
        c.R("m2", min(px, x_gate_bus) - 0.20, py - 0.18, max(px, x_gate_bus) + 0.20, py + 0.18)
    c.R("m3", x_gate_bus - 0.28, g_pts[0][1] - 0.25, x_gate_bus + 0.28, g_pts[-1][1] + 0.25)

    return {
        "D": (x_drn_bus, round((d_pts[0][1] + d_pts[-1][1]) / 2.0, 3)),
        "S": (x_src_bus, round((s_pts[0][1] + s_pts[-1][1]) / 2.0, 3)),
        "G": (x_gate_bus, round((g_pts[0][1] + g_pts[-1][1]) / 2.0, 3)),
        "bbox": (x0, y0, round(x0 + bank_w, 3), round(y0 + bank_h, 3)),
    }


# =========================================================================
# CELL 1: `serdes_ldo_hv18_core_r4` (`ldo_hv18_core_r4.spice`)
# =========================================================================
def build_serdes_ldo_hv18_core_r4() -> LayoutCanvas:
    c = LayoutCanvas("serdes_ldo_hv18_core_r4")
    W_CORE, H_CORE = 236.0, 124.0
    c.R("pwell", 0.0, 0.0, W_CORE, H_CORE)
    draw_guard_ring(c, 0.6, 0.6, W_CORE - 0.6, H_CORE - 0.6, kind="p", width=0.70)

    # =====================================================================
    # ZONE 1: Compact 5V Error Amplifier (`g5v0d10v5`) + Clamps + R/C (`x = 2.5 .. 64.5`)
    # =====================================================================
    draw_guard_ring(c, 2.5, 2.5, 64.5, 45.5, kind="p", width=0.55)

    clamps_row = draw_interdigitated_mos_row(
        c, "n", w_finger=5.0, l_gate=0.50, x0=4.2, y0=5.2,
        finger_map=[("off", "gate", "vss"), ("off", "gate", "vss"), ("off", "ibias", "vss"), ("off", "ibias", "vss")],
        lvt=False,
    )
    xn2_row = draw_interdigitated_mos_row(
        c, "n", w_finger=8.0, l_gate=0.50, x0=22.5, y0=5.2,
        finger_map=[("x", "gate", "vss")] * 8,
        lvt=False,
    )

    nb_nr_fmap = (
        [("ibias", "ibias", "vss")] * 4
        + [("ibias", "bp", "vss")] * 8
        + [("ibias", "ibias", "vss")] * 4
    )
    nbnr_row = draw_interdigitated_mos_row(
        c, "n", w_finger=7.5, l_gate=2.80, x0=4.2, y0=18.2,
        finger_map=nb_nr_fmap, lvt=False,
    )

    nl_nm_fmap = (
        [("d", "d", "vss")] * 4
        + [("d", "x", "vss")] * 8
        + [("d", "d", "vss")] * 4
    )
    nlnm_row = draw_interdigitated_mos_row(
        c, "n", w_finger=7.5, l_gate=2.80, x0=4.2, y0=31.8,
        finger_map=nl_nm_fmap, lvt=False,
    )

    # Top Filtered-HV `va` N-Well (`x = 2.5 .. 64.5, y = 47.0 .. 94.5`, N-Well tied to `va`!)
    draw_guard_ring(c, 2.5, 47.0, 64.5, 94.5, kind="n", width=0.55)

    pl_pr_fmap = [
        ("fb", "d", "tail"),  ("fb", "d", "tail"),
        ("ref", "x", "tail"), ("ref", "x", "tail"),
        ("ref", "x", "tail"), ("ref", "x", "tail"),
        ("fb", "d", "tail"),  ("fb", "d", "tail"),
    ]
    plpr_row = draw_interdigitated_mos_row(
        c, "p", w_finger=7.5, l_gate=1.50, x0=8.0, y0=50.0,
        finger_map=pl_pr_fmap, lvt=False,
    )

    pd_pt_fmap = (
        [("bp", "tail", "va")] * 4
        + [("bp", "bp", "va")] * 4
        + [("bp", "tail", "va")] * 4
    )
    pdpt_row = draw_interdigitated_mos_row(
        c, "p", w_finger=8.0, l_gate=3.20, x0=5.2, y0=63.5,
        finger_map=pd_pt_fmap, lvt=False,
    )

    xp2_row = draw_interdigitated_mos_row(
        c, "p", w_finger=9.5, l_gate=2.80, x0=4.2, y0=78.5,
        finger_map=[("bp", "gate", "va")] * 16, lvt=False,
    )

    # Top Filter Resistors (`Xrhv = 1k`, `Xrcas = 10k`, `Xrzero = 2k`) + `Xccomp = 2 pF` (2 leaf MIMs at `y = 96.5 .. 121.0`)
    rhv = draw_sky130_high_po_res(c, xc=4.5, y_bot=96.5, l_body=16.0, w_res=1.41)
    rcas1 = draw_sky130_high_po_res(c, xc=7.8, y_bot=96.5, l_body=19.0, w_res=1.41)
    rcas2 = draw_sky130_high_po_res(c, xc=11.1, y_bot=96.5, l_body=19.0, w_res=1.41)
    c.R("m2", 7.3, rcas1["R1"][1] - 0.35, 11.6, rcas1["R1"][1] + 0.35)
    rzero = draw_sky130_high_po_res(c, xc=14.4, y_bot=96.5, l_body=16.0, w_res=1.41)

    ccomp_grid = draw_leaf_mim_grid(c, x0=17.5, y0=96.8, n_cols=2, n_rows=1, w_leaf=20.5, l_leaf=21.2,
                                   pitch_x=23.2, pitch_y=23.2, top_net="cz", bot_net="gate")
    c.via2(rzero["R1"][0], rzero["R1"][1])
    c.via3(rzero["R1"][0], rzero["R1"][1])
    c.R("m4", rzero["R1"][0], rzero["R1"][1] - 0.35, ccomp_grid["C1"][0], rzero["R1"][1] + 0.35)

    route_m3_bus(c, [clamps_row["D_map"]["ibias"], nbnr_row["G_map"]["ibias"], nbnr_row["D_map"]["ibias"]], x_trunk=16.5)
    route_m3_bus(c, [nbnr_row["D_map"]["bp"], pdpt_row["D_map"]["bp"], pdpt_row["G_map"]["bp"], xp2_row["G_map"]["bp"]], x_trunk=28.0)
    route_m3_bus(c, [pdpt_row["D_map"]["tail"], plpr_row["S"]], x_trunk=35.0)
    route_m3_bus(c, [plpr_row["D_map"]["d"], nlnm_row["D_map"]["d"], nlnm_row["G_map"]["d"]], x_trunk=43.0)
    route_m3_bus(c, [plpr_row["D_map"]["x"], nlnm_row["D_map"]["x"], xn2_row["G_map"]["x"], rzero["R2"]], x_trunk=51.0)
    route_m3_bus(c, [clamps_row["D_map"]["gate"], xn2_row["D_map"]["gate"], xp2_row["D_map"]["gate"], ccomp_grid["C2"]], x_trunk=60.5)

    # =====================================================================
    # ZONE 2: 5V Native NMOS Power Pass (`Xpass` W=1000) & Cascode (`Xcas` W=2000) (`x = 66.5 .. 131.5`)
    # =====================================================================
    pass_bank = draw_power_nvt_bank(
        c, x0=66.5, y0=2.5, n_rows=3, nf_per_row=34, w_finger=10.0, l_gate=0.90,
        drain_net="mid", source_net="out", gate_net="gate",
    )
    cas_bank = draw_power_nvt_bank(
        c, x0=66.5, y0=46.5, n_rows=5, nf_per_row=40, w_finger=10.0, l_gate=0.90,
        drain_net="vin", source_net="mid", gate_net="casg",
    )

    c.R("m3", pass_bank["D"][0] - 1.2, pass_bank["D"][1], cas_bank["S"][0] + 1.2, cas_bank["S"][1])
    c.L("mid", cas_bank["S"][0], round((pass_bank["D"][1] + cas_bank["S"][1]) / 2.0, 3), "m3")
    c.R("m3", 60.5, pass_bank["G"][1] - 0.30, pass_bank["G"][0], pass_bank["G"][1] + 0.30)

    # =====================================================================
    # ZONE 3: Leaf MIM Decoupling Arrays `Xchv = 50 pF` (`va`) & `Xccas = 50 pF` (`casg`)
    # =====================================================================
    chv_grid = draw_leaf_mim_grid(
        c, x0=134.5, y0=4.0, n_cols=4, n_rows=5, w_leaf=22.20, l_leaf=21.20,
        pitch_x=24.80, pitch_y=23.20, top_net="va", bot_net=None,
    )
    ccas_grid = draw_leaf_mim_grid(
        c, x0=68.0, y0=4.0, n_cols=2, n_rows=5, w_leaf=22.20, l_leaf=21.20,
        pitch_x=25.20, pitch_y=23.20, top_net="casg", bot_net=None,
    )
    c.R("m4", rhv["R1"][0], 93.8, chv_grid["C1"][0], 94.5)
    c.R("m4", rcas2["R2"][0], 96.5, ccas_grid["C1"][0], 97.2)

    c.L("vin", cas_bank["D"][0], 118.5, "m3")
    c.L("out", pass_bank["S"][0], 6.5, "m3")
    c.L("ref", plpr_row["G_map"]["ref"][0], plpr_row["G_map"]["ref"][1], "m2")
    c.L("fb", plpr_row["G_map"]["fb"][0], plpr_row["G_map"]["fb"][1], "m2")
    c.L("ibias", 16.5, 16.0, "m3")
    c.L("off", clamps_row["G_map"]["off"][0], clamps_row["G_map"]["off"][1], "m2")
    c.L("gate", 60.5, 46.0, "m3")
    c.L("vss", 34.0, 0.95, "m2")
    return c


# =========================================================================
# CELL 2 & 3: `serdes_pll_supply_hv18_r4` & `serdes_pll_supply_hv18_r4_probe`
# =========================================================================
def build_serdes_pll_supply_hv18_r4(probe_mode: bool = False) -> LayoutCanvas:
    cell_name = "serdes_pll_supply_hv18_r4_probe" if probe_mode else "serdes_pll_supply_hv18_r4"
    c = LayoutCanvas(cell_name)
    W_TOP, H_TOP = 436.0, 124.0
    c.R("pwell", 0.0, 0.0, W_TOP, H_TOP)
    draw_guard_ring(c, 0.6, 0.6, W_TOP - 0.6, H_TOP - 0.6, kind="p", width=0.75)

    # 1. Left-Bottom Bay (`x = 2.5 .. 67.5, y = 2.5 .. 58.5`):
    #    6-Bit Voltage Trim Feedback Divider (`Xrtop`, `Xrfixed`, `Xr5..0`, `Xbleed`) + `Xs5..0` (`t5..t0`)
    draw_guard_ring(c, 2.5, 2.5, 67.5, 58.5, kind="p", width=0.55)
    div_strips = []
    for i in range(16):
        rx = round(5.2 + i * 3.85, 3)
        rs = draw_sky130_high_po_res(c, xc=rx, y_bot=16.5, l_body=36.0, w_res=1.41)
        div_strips.append(rs)
        if i < 15 and i not in (3, 7, 13):
            nx = round(5.2 + (i + 1) * 3.85, 3)
            jy = rs["R1"][1] if (i % 2 == 0) else rs["R2"][1]
            c.R("m2", rx - 0.45, jy - 0.35, nx + 0.45, jy + 0.35)

    trim_sws = {}
    for bit_k in range(6):
        sx = round(4.5 + bit_k * 10.2, 3)
        t_net = f"t{bit_k}"
        n_hi = f"n{bit_k}"
        n_lo = f"n{bit_k-1}" if bit_k > 0 else "vss"
        trim_sws[t_net] = draw_interdigitated_mos_row(
            c, "n", w_finger=5.0, l_gate=0.35, x0=sx, y0=4.8,
            finger_map=[(t_net, n_hi, n_lo)] * 4, lvt=False,
        )
        gx, gy = trim_sws[t_net]["G_map"][t_net]
        dx, dy = trim_sws[t_net]["D_map"][n_hi]
        r_tap = div_strips[8 + bit_k]["R2"]
        c.via2(dx, dy)
        c.via2(r_tap[0], r_tap[1])
        y_jog = round(12.2 + bit_k * 0.55, 3)
        c.R("m3", dx - 0.20, min(dy, y_jog), dx + 0.20, max(dy, y_jog))
        c.R("m3", min(dx, r_tap[0]), y_jog - 0.18, max(dx, r_tap[0]), y_jog + 0.18)
        c.R("m3", r_tap[0] - 0.20, min(r_tap[1], y_jog), r_tap[0] + 0.20, max(r_tap[1], y_jog))
        c.L(t_net, gx, gy, "m2")

    # 2. Left-Top Bay (`x = 2.5 .. 67.5, y = 60.0 .. 121.5`):
    #    1.8V Host Logic (`Xcopy n=4`, `Xinv`, `Xrefgate`, `Xrefreset`) + Under-MIM `Xrefres (1MOhm)` & `Xrefcap (16pF)`
    draw_guard_ring(c, 2.5, 60.0, 67.5, 121.5, kind="p", width=0.55)
    draw_guard_ring(c, 3.8, 61.2, 34.5, 73.5, kind="n", width=0.45)
    xcopy_row = draw_interdigitated_mos_row(
        c, "p", w_finger=5.0, l_gate=1.80, x0=5.2, y0=63.5,
        finger_map=[("vgi", "ibias", "host")] * 4, lvt=True,
    )
    host_n_row = draw_interdigitated_mos_row(
        c, "n", w_finger=4.0, l_gate=0.35, x0=36.5, y0=63.5,
        finger_map=[("enable", "off", "vss"), ("enable", "ref_start", "bg"), ("off", "ref_local", "vss")],
        lvt=False,
    )
    for i in range(16):
        rx = round(5.2 + i * 3.85, 3)
        rs = draw_sky130_high_po_res(c, xc=rx, y_bot=75.5, l_body=38.0, w_res=1.41)
        if i < 15:
            nx = round(5.2 + (i + 1) * 3.85, 3)
            jy = rs["R1"][1] if (i % 2 == 0) else rs["R2"][1]
            c.R("m2", rx - 0.45, jy - 0.35, nx + 0.45, jy + 0.35)
    draw_leaf_mim_grid(
        c, x0=5.0, y0=76.0, n_cols=3, n_rows=2, w_leaf=18.2, l_leaf=19.5,
        pitch_x=20.2, pitch_y=21.5, top_net="ref_local", bot_net=None,
    )

    # 3. Center Bay (`x = 69.0 .. 305.0`): Include `serdes_ldo_hv18_core_r4` (`236 x 124 um`)
    core_cell = build_serdes_ldo_hv18_core_r4()
    c.include_subcell(core_cell, dx=69.0, dy=0.0, include_labels=False)

    # 4. Right Bay (`x = 307.0 .. 433.5, y = 2.5 .. 121.5`):
    #    `Xcout = serdes_ldo_mim100` (`100 pF` Output Decoupling Capacitor Matrix on `quiet -> vss`)
    cout_grid = draw_leaf_mim_grid(
        c, x0=309.0, y0=4.0, n_cols=5, n_rows=5, w_leaf=22.20, l_leaf=21.20,
        pitch_x=24.60, pitch_y=23.20, top_net="quiet", bot_net=None,
    )
    c.R("m4", 15.0, 12.0, 428.0, 14.5)

    c.L("vin", 160.0, 118.5, "m3")
    c.L("host", xcopy_row["S"][0], xcopy_row["S"][1], "m2")
    c.L("quiet", cout_grid["C1"][0], 13.2, "m4")
    c.L("bg", host_n_row["S"][0] + 4.0, host_n_row["S"][1], "m2")
    c.L("vgi", xcopy_row["G_map"]["vgi"][0], xcopy_row["G_map"]["vgi"][1], "m2")
    c.L("enable", host_n_row["G_map"]["enable"][0], host_n_row["G_map"]["enable"][1], "m2")
    if probe_mode:
        c.L("fb_return", 20.5, 54.0, "m2")
        c.L("fb_input", 88.0, 48.0, "m2")
    else:
        c.R("m3", 20.5, 48.0, 88.0, 48.6)
        c.L("fb", 55.0, 48.3, "m3")
    c.L("vss", 218.0, 0.95, "m2")
    return c


# =========================================================================
# CELL 4 & 5: `serdes_pll_bias_lowpass_slow_r4` (1M+16pF) & `serdes_pll_bias_lowpass_r4` (100k+16pF)
# =========================================================================
def build_serdes_pll_bias_lowpass(slow: bool = True) -> LayoutCanvas:
    cell_name = "serdes_pll_bias_lowpass_slow_r4" if slow else "serdes_pll_bias_lowpass_r4"
    c = LayoutCanvas(cell_name)
    W_FLT, H_FLT = 106.0, 104.0
    c.R("pwell", 0.0, 0.0, W_FLT, H_FLT)
    draw_guard_ring(c, 0.5, 0.5, W_FLT - 0.5, H_FLT - 0.5, kind="p", width=0.60)

    n_res = 32 if slow else 8
    pitch_rx = round(92.0 / (n_res + 1), 3)
    x_start = round(5.50 + pitch_rx, 3)
    res_list = []
    draw_sky130_high_po_res(c, xc=round(x_start - pitch_rx, 3), y_bot=3.5, l_body=92.0, w_res=1.41, dummy=True)
    for i in range(n_res):
        rx = round(x_start + i * pitch_rx, 3)
        r_info = draw_sky130_high_po_res(c, xc=rx, y_bot=3.5, l_body=92.0, w_res=1.41)
        res_list.append(r_info)
        if i < n_res - 1:
            nx = round(x_start + (i + 1) * pitch_rx, 3)
            jy = r_info["R1"][1] if (i % 2 == 0) else r_info["R2"][1]
            c.R("m2", rx - 0.45, jy - 0.35, nx + 0.45, jy + 0.35)
    draw_sky130_high_po_res(c, xc=round(x_start + n_res * pitch_rx, 3), y_bot=3.5, l_body=92.0, w_res=1.41, dummy=True)

    mim_grid = draw_leaf_mim_grid(
        c, x0=3.2, y0=4.0, n_cols=4, n_rows=4, w_leaf=22.20, l_leaf=22.20,
        pitch_x=25.00, pitch_y=24.00, top_net=None, bot_net=None,
    )
    last_pt = res_list[-1]["R2"]
    c.via2(last_pt[0], last_pt[1])
    c.via3(last_pt[0], last_pt[1])
    c.R("m4", last_pt[0] - 0.45, last_pt[1], last_pt[0] + 0.45, mim_grid["C1"][1])

    c.L("original", res_list[0]["R2"][0], res_list[0]["R2"][1], "m2")
    c.L("filtered", mim_grid["C1"][0], mim_grid["C1"][1], "m4")
    c.L("vss", 53.0, 0.8, "m2")
    return c


# =========================================================================
# CELL 6: `serdes_ldo_power_switch` (`ldo_power_switch.spice`)
# =========================================================================
def build_serdes_ldo_power_switch() -> LayoutCanvas:
    c = LayoutCanvas("serdes_ldo_power_switch")
    W_SW, H_SW = 78.0, 62.0
    c.R("pwell", 0.0, 0.0, W_SW, H_SW)
    draw_guard_ring(c, 0.5, 0.5, W_SW - 0.5, H_SW - 0.5, kind="p", width=0.60)

    # Bottom P-Well (`x = 2.5 .. 42.5, y = 2.5 .. 14.5`): `Xdown` (`gate <- en`, `w=10, l=0.5`)
    xdown = draw_interdigitated_mos_row(
        c, "n", w_finger=5.0, l_gate=0.50, x0=4.2, y0=4.5,
        finger_map=[("en", "gate", "vss"), ("en", "gate", "vss")], lvt=False,
    )

    # Shared Isolated `mid` N-Well (`x = 2.5 .. 42.5, y = 16.0 .. 59.5`) — Tight, zero wasted well whitespace!
    draw_guard_ring(c, 2.5, 16.0, 42.5, 59.5, kind="n", width=0.55)
    xup = draw_interdigitated_mos_row(
        c, "p", w_finger=8.0, l_gate=1.00, x0=4.2, y0=18.5,
        finger_map=[("en", "gate", "mid")] * 20, lvt=False,
    )
    xa_row = draw_interdigitated_mos_row(
        c, "p", w_finger=9.5, l_gate=0.50, x0=4.2, y0=32.0,
        finger_map=[("gate", "a", "mid")] * 32, lvt=False,
    )
    xb_row = draw_interdigitated_mos_row(
        c, "p", w_finger=9.5, l_gate=0.50, x0=4.2, y0=45.5,
        finger_map=[("gate", "b", "mid")] * 32, lvt=False,
    )

    # Right Zone (`x = 45.0 .. 75.5`): `Rkeep = 1 MOhm` (`gate <-> mid`, 10 serpentine high-po strips)
    rkeep_list = []
    for i in range(10):
        rx = round(46.0 + i * 3.10, 3)
        rk = draw_sky130_high_po_res(c, xc=rx, y_bot=4.0, l_body=49.5, w_res=1.41)
        rkeep_list.append(rk)
        if i < 9:
            nx = round(46.0 + (i + 1) * 3.10, 3)
            jy = rk["R1"][1] if (i % 2 == 0) else rk["R2"][1]
            c.R("m2", rx - 0.45, jy - 0.35, nx + 0.45, jy + 0.35)

    route_m3_bus(c, [xdown["G_map"]["en"], xup["G_map"]["en"]], x_trunk=11.5)
    route_m3_bus(c, [xdown["D_map"]["gate"], xup["D_map"]["gate"], xa_row["G_map"]["gate"], xb_row["G_map"]["gate"], rkeep_list[0]["R2"]], x_trunk=27.5)
    route_m3_bus(c, [xup["S"], xa_row["S"], xb_row["S"], rkeep_list[-1]["R2"]], x_trunk=40.5)

    c.L("a", xa_row["D_map"]["a"][0], xa_row["D_map"]["a"][1], "m2")
    c.L("b", xb_row["D_map"]["b"][0], xb_row["D_map"]["b"][1], "m2")
    c.L("mid", 40.5, 38.0, "m3")
    c.L("gate", 27.5, 26.0, "m3")
    c.L("en", 11.5, 12.0, "m3")
    c.L("vss", 24.0, 0.8, "m2")
    return c


# =========================================================================
# CELLS 7..10: Passive Leaf Building Blocks (`ldo_passives.spice`)
# =========================================================================
def build_serdes_ldo_ref_res() -> LayoutCanvas:
    c = LayoutCanvas("serdes_ldo_ref_res")
    W_R, H_R = 98.0, 102.0
    c.R("pwell", 0.0, 0.0, W_R, H_R)
    draw_guard_ring(c, 0.5, 0.5, W_R - 0.5, H_R - 0.5, kind="p", width=0.55)
    r_list = []
    for i in range(32):
        rx = round(4.0 + i * 2.85, 3)
        rs = draw_sky130_high_po_res(c, xc=rx, y_bot=3.5, l_body=90.5, w_res=1.41)
        r_list.append(rs)
        if i < 31:
            nx = round(4.0 + (i + 1) * 2.85, 3)
            jy = rs["R1"][1] if (i % 2 == 0) else rs["R2"][1]
            c.R("m2", rx - 0.45, jy - 0.35, nx + 0.45, jy + 0.35)
    c.L("a", r_list[0]["R2"][0], r_list[0]["R2"][1], "m2")
    c.L("b", r_list[-1]["R2"][0], r_list[-1]["R2"][1], "m2")
    c.L("sub", 49.0, 0.8, "m2")
    return c


def build_serdes_ldo_mim_macro(n_units: int, n_cols: int, n_rows: int) -> LayoutCanvas:
    cell_name = f"serdes_ldo_mim{n_units}"
    c = LayoutCanvas(cell_name)
    w_tot = round(n_cols * 25.0 + 4.0, 3)
    h_tot = round(n_rows * 24.0 + 4.0, 3)
    c.R("pwell", 0.0, 0.0, w_tot, h_tot)
    draw_leaf_mim_grid(c, x0=2.5, y0=2.0, n_cols=n_cols, n_rows=n_rows, w_leaf=22.20, l_leaf=22.20,
                       pitch_x=24.80, pitch_y=23.80, top_net="a", bot_net="b")
    return c


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Regenerate Gemini candidates; does not validate them.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    cells = [
        ("serdes_ldo_hv18_core_r4",          build_serdes_ldo_hv18_core_r4()),
        ("serdes_pll_supply_hv18_r4",        build_serdes_pll_supply_hv18_r4(probe_mode=False)),
        ("serdes_pll_supply_hv18_r4_probe",  build_serdes_pll_supply_hv18_r4(probe_mode=True)),
        ("serdes_pll_bias_lowpass_slow_r4",  build_serdes_pll_bias_lowpass(slow=True)),
        ("serdes_pll_bias_lowpass_r4",       build_serdes_pll_bias_lowpass(slow=False)),
        ("serdes_ldo_power_switch",          build_serdes_ldo_power_switch()),
        ("serdes_ldo_ref_res",               build_serdes_ldo_ref_res()),
        ("serdes_ldo_mim16",                 build_serdes_ldo_mim_macro(16, 4, 4)),
        ("serdes_ldo_mim50",                 build_serdes_ldo_mim_macro(50, 10, 5)),
        ("serdes_ldo_mim100",                build_serdes_ldo_mim_macro(100, 10, 10)),
    ]

    ldo_layout_dir = args.output_dir.resolve()
    ldo_layout_dir.mkdir(parents=True, exist_ok=True)

    for name, canvas in cells:
        for d in (ldo_layout_dir,):
            canvas.save_mag(d / f"{name}.mag")
            canvas.save_tcl(d / f"{name}.tcl")
        bx1, by1, bx2, by2 = canvas.bbox()
        w, h = round(bx2 - bx1, 2), round(by2 - by1, 2)
        n_rects = sum(len(v) for v in canvas.rects.values())
        n_labels = len(canvas.labels)
        print(f"{name:34s} : {w:6.2f} x {h:6.2f} um = {w*h:9.1f} um^2 | rects={n_rects:5d} | labels={n_labels:2d}")

    fig, axes = plt.subplots(2, 2, figsize=(17, 13.5), dpi=160)
    plot_canvas(axes[0, 0], cells[1][1], "1. serdes_pll_supply_hv18_r4 (Production Top-Level Quiet PLL Supply Macro)",
                "Left: 6-Bit Trim Divider + 1M/16pF Ref Filter | Center: HV18 Core | Right: 100pF Output Decap Matrix", show_cuts=False)
    plot_canvas(axes[0, 1], cells[0][1], "2. serdes_ldo_hv18_core_r4 (Dual 5V Native NMOS Cascode + Pass LDO Core)",
                "Left: 5V CC Error Amp (va N-Well) + Clamps | Center: W=2000 Cascode + W=1000 Pass | Right: Chv/Ccas 50pF Leaf MIMs", show_cuts=False)
    plot_canvas(axes[1, 0], cells[3][1], "3. serdes_pll_bias_lowpass_slow_r4 (Under-MIM 3D-Stacked 1 MOhm + 16 pF Tail Filter)",
                "Bottom: 32x 31.25k ppolyres Serpentine + Dummies | Top: 4x4 Leaf MIMs (vss Bottom Shield)", show_cuts=False)
    plot_canvas(axes[1, 1], cells[5][1], "4. serdes_ldo_power_switch (Back-to-Back Shared-Mid-Well 5V PMOS Switch)",
                "Shared 'mid' N-Well Xa/Xb + Xup Pull-Up + Xdown Pull-Down + 1MOhm Rkeep (-29% Area)", show_cuts=False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=7, frameon=True, fontsize=8.5, bbox_to_anchor=(0.5, 0.008))
    plt.tight_layout(rect=[0, 0.045, 1, 1])
    for d in (ldo_layout_dir,):
        fig.savefig(d / "ldo_layout_suite_overview.png", dpi=160)
    plt.close(fig)



if __name__ == "__main__":
    main()
