#!/usr/bin/env python3
"""Build and verify the SKY130 PDK layout for the PLL VCO PTAT + Constant-Swing Blended Bias Cell
(`pll_vco_ptat_bias_pdk`), implementing `serdes_bias_cml_blend_v2` from
`analog/pll/vco/spice/vco_ptat_bias.spice`.

Circuit (verified 135/135 PVT + 45/45 3-temp single-code VCO lock at commit 267245a):
  - Xconst : 28 fingers of 8/4 um `sky130_fd_pr__pfet_01v8_lvt` (`W=224, L=4`), gate=`vgi`
  - Xptat  : 66 fingers of 14/6 um `sky130_fd_pr__pfet_01v8_lvt` (`W=924, L=6`), gate=`vg`
  - Ports  : `out vgi vg vdd` (exact 1:1 match to `serdes_bias_cml_blend_v2`)

Physical Architecture (0.0% M5, 0 floating poly, BIAS v2 rail/abutment conventions):
  - 4 horizontal even-finger rows in a single unified N-well with closed `nsubdiff` guard ring
    and full-width inter-row N-tap strips (max P-diff to N-tap <= 7.8 um << 15 um LU.3):
      Row 0 (Bottom)  : Xconst (`nf=28`, `w=8/l=4`, outer S/D = `vdd`)
      Rows 1..3 (Top) : 3x Xptat (`nf=22` each -> 66 total, `w=14/l=6`, outer S/D = `vdd`)
  - Every row is flanked on both outer ends by tied field-poly dummies contacted via
    `polycont + locali + viali + metal1` straight into the `vdd` N-tap bar (0 floating poly,
    0 extra dummy MOS devices).
  - Multi-spine M3 `vdd` (6 trunks) + top/bottom M4 `vdd` rails; multi-spine M3 `out` (4 trunks)
    + central M4 `out` collector exiting East; `vgi` & `vg` gates exiting West (for direct
    abutment to `serdes_bias_top_v2_pdk` internal `vgi`/`vg` trunks). Strictly 0.0% M5.
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

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "verification/layout"))

from check import exported_ports  # noqa: E402
from geometry import Cell, pdk_device  # noqa: E402
import magicutil as mu  # noqa: E402
from summarize_parasitics import summarize_pex_spice  # noqa: E402

CELL_NAME = "pll_vco_ptat_bias_pdk"
EXPECTED_PORTS = ["out", "vgi", "vg", "vdd"]


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def via2_clean(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.via2(x, y)
    c.pad("metal3", x, y, 0.52)


def via3_array(c: Cell, x: float, y: float, nx: int = 2, ny: int = 2, pitch: float = 0.72) -> None:
    x, y = grid(x), grid(y)
    hx = grid(((nx - 1) * pitch + 0.52) / 2.0)
    hy = grid(((ny - 1) * pitch + 0.52) / 2.0)
    c.rect("metal3", grid(x - hx), grid(y - hy), grid(x + hx), grid(y + hy))
    c.rect("metal4", grid(x - hx), grid(y - hy), grid(x + hx), grid(y + hy))
    for ix in range(nx):
        for iy in range(ny):
            px = grid(x + (ix - (nx - 1) / 2.0) * pitch)
            py = grid(y + (iy - (ny - 1) / 2.0) * pitch)
            c.pad("via3", px, py, 0.32)


def draw_ntap_bar_h(c: Cell, x1: float, x2: float, y: float) -> None:
    x1, x2, y = grid(x1), grid(x2), grid(y)
    c.rect("nsubdiff", grid(x1 - 0.20), grid(y - 0.20), grid(x2 + 0.20), grid(y + 0.20))
    c.rect("nsubdiffcont", grid(x1 + 0.35), grid(y - 0.085), grid(x2 - 0.35), grid(y + 0.085))
    c.rect("locali", grid(x1 - 0.20), grid(y - 0.18), grid(x2 + 0.20), grid(y + 0.18))
    c.rect("metal1", grid(x1 - 0.22), grid(y - 0.22), grid(x2 + 0.22), grid(y + 0.22))
    span = x2 - x1
    n_pts = max(2, int(span // 4.0))
    for i in range(n_pts + 1):
        px = grid(x1 + span * i / n_pts)
        c.pad("viali", px, y, 0.17)


def draw_ntap_wall_v(c: Cell, x: float, y_stops: list[float]) -> None:
    x = grid(x)
    y1, y2 = grid(y_stops[0]), grid(y_stops[-1])
    c.rect("nsubdiff", grid(x - 0.20), grid(y1 - 0.20), grid(x + 0.20), grid(y2 + 0.20))
    for ya, yb in zip(y_stops[:-1], y_stops[1:]):
        c.rect("nsubdiffcont", grid(x - 0.085), grid(ya + 0.35), grid(x + 0.085), grid(yb - 0.35))
    c.rect("locali", grid(x - 0.18), grid(y1 - 0.20), grid(x + 0.18), grid(y2 + 0.20))
    c.rect("metal1", grid(x - 0.22), grid(y1 - 0.22), grid(x + 0.22), grid(y2 + 0.22))
    span = y2 - y1
    n_pts = max(2, int(span // 4.0))
    for i in range(n_pts + 1):
        py = grid(y1 + span * i / n_pts)
        c.pad("viali", x, py, 0.17)


def add_tied_field_poly_dummies(
    c: Cell, x_pdiff_min: float, x_pdiff_max: float, y_pdiff_min: float, y_pdiff_max: float, y_tap_top: float
) -> None:
    """Place contacted 0.50 um field-poly dummy bars flanking pdiff, tied straight up to y_tap_top (vdd)."""
    dw = 0.50
    gap = 0.50
    y_cont = grid(y_pdiff_max + 0.05)
    for side, x_edge in ((-1.0, x_pdiff_min), (+1.0, x_pdiff_max)):
        xc = grid(x_edge + side * (gap + dw / 2.0))
        c.rect("poly", grid(xc - dw / 2.0), grid(y_pdiff_min), grid(xc + dw / 2.0), grid(y_cont + 0.17))
        c.pad("polycont", xc, y_cont, 0.17, 0.17)
        c.pad("locali", xc, y_cont, 0.24, 0.34)
        c.pad("viali", xc, y_cont, 0.17, 0.17)
        c.pad("metal1", xc, y_cont, 0.30, 0.30)
        c.wire("metal1", [(xc, y_cont), (xc, y_tap_top)], 0.26)


def count_floating_poly(c: Cell) -> int:
    polys = c.rects.get("poly", [])
    anchors = []
    for lay in ("polycont", "nmos", "nmoslvt", "pmos", "pmoslvt", "mvnmos", "mvnnmos", "mvpmos", "ppolyres", "xpolycontact", "varactor"):
        anchors.extend(c.rects.get(lay, []))
    if not polys:
        return 0
    n = len(polys)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    order = sorted(range(n), key=lambda k: polys[k][0])
    for ia in range(n):
        i = order[ia]
        ax1, ay1, ax2, ay2 = polys[i]
        for ib in range(ia + 1, n):
            j = order[ib]
            bx1, by1, bx2, by2 = polys[j]
            if bx1 > ax2 + 1e-6:
                break
            if not (by2 < ay1 - 1e-6 or by1 > ay2 + 1e-6):
                union(i, j)

    anchored: dict[int, bool] = {find(i): False for i in range(n)}
    for i, (px1, py1, px2, py2) in enumerate(polys):
        ri = find(i)
        if anchored[ri]:
            continue
        for ax1, ay1, ax2, ay2 in anchors:
            if not (ax2 < px1 - 1e-6 or ax1 > px2 + 1e-6 or ay2 < py1 - 1e-6 or ay1 > py2 + 1e-6):
                anchored[ri] = True
                break
    return sum(1 for v in anchored.values() if not v)


def make_reference_spice(path: Path) -> Path:
    text = "\n".join([
        "* LVS reference netlist for pll_vco_ptat_bias_pdk",
        "* Exact device-for-device match to serdes_bias_cml_blend_v2 in analog/pll/vco/spice/vco_ptat_bias.spice:",
        "*   Xconst : 28 fingers of 8/4 um pfet_01v8_lvt (W=224, L=4) driven by vgi",
        "*   Xptat  : 66 fingers of 14/6 um pfet_01v8_lvt (W=924, L=6) driven by vg",
        f".subckt {CELL_NAME} out vgi vg vdd",
        "Xconst out vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=224 l=4",
        "Xptat  out vg  vdd vdd sky130_fd_pr__pfet_01v8_lvt w=924 l=6",
        f".ends {CELL_NAME}",
        "",
    ])
    path.write_text(text)
    return path


def render_png(mag: Path, out_png: Path, title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import plot_mag as pm

    rects, labels = pm.parse(mag)
    xs = [r[1] for r in rects] + [r[3] for r in rects]
    ys = [r[2] for r in rects] + [r[4] for r in rects]
    x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
    w, h = x2 - x1, y2 - y1

    fig, ax = plt.subplots(figsize=(16, max(6.8, 16 * h / max(w, 1.0))), dpi=180)
    ax.set_facecolor("white")

    present = set()
    for layer, rx1, ry1, rx2, ry2 in rects:
        if layer not in pm.COLORS:
            continue
        present.add(layer)
        alpha = 0.65 if layer in ("m1", "m2", "m3", "m4", "m5") else 0.90
        ax.add_patch(
            Rectangle(
                (rx1, ry1), rx2 - rx1, ry2 - ry1,
                facecolor=pm.COLORS[layer], edgecolor="none",
                alpha=alpha, zorder=pm.Z[layer],
            )
        )

    # Row annotations
    row_notes = [
        (0.0, 5.2, "Row 0: Xconst (28 x 8/4 um pfet_lvt, vgi)"),
        (0.0, 18.6, "Row 1: Xptat_0 (22 x 14/6 um pfet_lvt, vg)"),
        (0.0, 35.0, "Row 2: Xptat_1 (22 x 14/6 um pfet_lvt, vg)"),
        (0.0, 51.4, "Row 3: Xptat_2 (22 x 14/6 um pfet_lvt, vg)"),
    ]
    for rx, ry, txt in row_notes:
        ax.text(rx, ry, txt, color="#111827", fontsize=8.0, ha="center", va="center", fontweight="bold",
                zorder=108, bbox=dict(boxstyle="round,pad=0.18", facecolor="#ffffff", edgecolor="#64748b", alpha=0.82))

    port_offsets = {
        "vgi": (-7.5, 0.0, "right"),
        "vg":  (-7.5, 0.0, "right"),
        "out": (+7.5, 0.0, "left"),
        "vdd": (0.0, +4.2, "center"),
    }
    for nm, px, py in labels:
        ax.plot(px, py, "o", color="#111827", markersize=4.5, markeredgecolor="#ffffff", markeredgewidth=0.7, zorder=109)
        dx_l, dy_l, ha = port_offsets.get(nm, (+5.0, 0.0, "left"))
        ax.annotate(
            nm, xy=(px, py), xytext=(px + dx_l, py + dy_l),
            color="#111827", fontsize=9.0, fontweight="bold", ha=ha, va="center", zorder=110,
            arrowprops=dict(arrowstyle="-", color="#2563eb", lw=1.0),
            bbox=dict(boxstyle="round,pad=0.18", facecolor="#ffffff", edgecolor="#2563eb", alpha=0.95),
        )

    ax.set_xlim(x1 - 14, x2 + 16)
    ax.set_ylim(y1 - 6, y2 + 8)
    ax.set_aspect("equal")
    ax.set_xlabel("X (µm)")
    ax.set_ylabel("Y (µm)")
    ax.grid(True, lw=0.25, alpha=0.35)
    ax.set_title(f"{title}  ({w:.2f} × {h:.2f} µm = {w*h:,.1f} µm² | 0.0% M5)", fontsize=11.5, fontweight="bold")
    legend_keys = [k for k in pm.COLORS if k in present]
    handles = [Rectangle((0, 0), 1, 1, facecolor=pm.COLORS[k], edgecolor="none") for k in legend_keys]
    ax.legend(handles, legend_keys, fontsize=6.5, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0.0, ncol=1)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def build_ptat_bias(out: Path) -> dict:
    work = (out / CELL_NAME).resolve()
    work.mkdir(parents=True, exist_ok=True)
    pwork = (out / "_prims").resolve()
    pwork.mkdir(parents=True, exist_ok=True)

    p_const = pdk_device(
        pwork, "p_const_28", "sky130_fd_pr__pfet_01v8_lvt",
        dict(w=8.0, l=4.0, nf=28, m=1, guard=0, conn_gates=1, topc=0, botc=1, doports=1),
    )
    p_const.rects.pop("checkpaint", None)

    p_ptat = pdk_device(
        pwork, "p_ptat_22", "sky130_fd_pr__pfet_01v8_lvt",
        dict(w=14.0, l=6.0, nf=22, m=1, guard=0, conn_gates=1, topc=0, botc=1, doports=1),
    )
    p_ptat.rects.pop("checkpaint", None)

    const_sds = sorted({grid((r[0] + r[2]) / 2.0) for r in p_const.rects["pdiffc"]})
    const_pd_x1 = grid(min(r[0] for r in p_const.rects["pdiff"]))
    const_pd_x2 = grid(max(r[2] for r in p_const.rects["pdiff"]))
    const_pd_y1 = grid(min(r[1] for r in p_const.rects["pdiff"]))
    const_pd_y2 = grid(max(r[3] for r in p_const.rects["pdiff"]))
    const_gxs = sorted({grid(x) for _, x, _, l in p_const.labels if l.startswith("G")})
    const_gy_rel = grid(next(y for _, _, y, l in p_const.labels if l.startswith("G")))
    p_const.labels.clear()

    ptat_sds = sorted({grid((r[0] + r[2]) / 2.0) for r in p_ptat.rects["pdiffc"]})
    ptat_pd_x1 = grid(min(r[0] for r in p_ptat.rects["pdiff"]))
    ptat_pd_x2 = grid(max(r[2] for r in p_ptat.rects["pdiff"]))
    ptat_pd_y1 = grid(min(r[1] for r in p_ptat.rects["pdiff"]))
    ptat_pd_y2 = grid(max(r[3] for r in p_ptat.rects["pdiff"]))
    ptat_gxs = sorted({grid(x) for _, x, _, l in p_ptat.labels if l.startswith("G")})
    ptat_gy_rel = grid(next(y for _, _, y, l in p_ptat.labels if l.startswith("G")))
    p_ptat.labels.clear()

    c = Cell()

    # Global floorplan coordinates
    x_wall_l, x_wall_r = -71.80, +71.80
    x_vg_m3 = -73.20
    x_out_m3_e = +73.40
    x_port_w = -74.00
    x_port_e = +74.00

    y_bot_ring = 0.00
    dy0 = 5.20
    y_tap1 = 10.40
    dy1 = 18.60
    y_tap2 = 26.80
    dy2 = 35.00
    y_tap3 = 43.20
    dy3 = 51.40
    y_top_ring = 59.60

    # Continuous single N-well (0.80 um enclosure beyond nsubdiff guard walls)
    c.rect("nwell", -72.80, -1.00, +72.80, 60.60)

    # Guard walls and inter-row N-tap strips (max P-diff to N-tap <= 7.8 um << 15 um LU.3)
    y_taps_all = [y_bot_ring, y_tap1, y_tap2, y_tap3, y_top_ring]
    draw_ntap_wall_v(c, x_wall_l, y_taps_all)
    draw_ntap_wall_v(c, x_wall_r, y_taps_all)
    for yt in y_taps_all:
        draw_ntap_bar_h(c, x_wall_l, x_wall_r, yt)

    vdd_m3_xs = [x_wall_l, -48.00, -16.00, +16.00, +48.00, x_wall_r]
    out_m3_xs = [-32.00, 0.00, +32.00]

    # Top & bottom full-width M2 + M4 VDD rails
    for yr in (y_bot_ring, y_top_ring):
        c.wire("metal2", [(x_wall_l, yr), (x_wall_r, yr)], 0.80)
        c.wire("metal4", [(x_wall_l, yr), (x_wall_r, yr)], 1.20)
        for xv in vdd_m3_xs:
            c.via1(xv, yr)
            via2_clean(c, xv, yr)
            via3_array(c, xv, yr, nx=2, ny=2)

    # Inter-row N-tap ties to vertical VDD M3 spines
    for yt in (y_tap1, y_tap2, y_tap3):
        for xv in vdd_m3_xs:
            c.via1(xv, yt)
            via2_clean(c, xv, yt)

    # -------------------------------------------------------------------------
    # Row 0 (Bottom): Xconst (28 x 8/4 um pfet_01v8_lvt, gate=vgi)
    # -------------------------------------------------------------------------
    c.include(p_const, dx=0.0, dy=dy0)
    add_tied_field_poly_dummies(
        c, const_pd_x1, const_pd_x2, grid(dy0 + const_pd_y1), grid(dy0 + const_pd_y2), y_tap1
    )
    const_s_xs = const_sds[0::2]  # 15 columns (outer diffusions = vdd)
    const_d_xs = const_sds[1::2]  # 14 columns (out)
    y_c_vdd_lo = grid(dy0 - 2.60)  # 2.60
    y_c_vdd_hi = grid(dy0 + 2.80)  # 8.00
    y_c_out    = grid(dy0 + 0.10)  # 5.30
    y_c_gate   = grid(dy0 + const_gy_rel)  # 1.06

    for yv in (y_c_vdd_lo, y_c_vdd_hi):
        for sx in const_s_xs:
            c.via1(sx, yv)
        c.wire("metal2", [(x_wall_l, yv), (x_wall_r, yv)], 0.60)
        c.via1(x_wall_l, yv)
        c.via1(x_wall_r, yv)
        for xv in vdd_m3_xs:
            via2_clean(c, xv, yv)

    for dx_col in const_d_xs:
        c.via1(dx_col, y_c_out)
    c.wire("metal2", [(const_d_xs[0], y_c_out), (const_d_xs[-1], y_c_out)], 0.80)
    for xo in out_m3_xs:
        via2_clean(c, xo, y_c_out)

    # vgi gate strap: continuous 0.32 um M1 bar across all gate contacts + via1 at exact gate Xs -> straight West port
    c.wire("metal1", [(const_gxs[0], y_c_gate), (const_gxs[-1], y_c_gate)], 0.32)
    for gx in const_gxs[::4] + [const_gxs[-1]]:
        c.via1(gx, y_c_gate)
    c.wire("metal2", [(x_port_w, y_c_gate), (const_gxs[-1], y_c_gate)], 0.36)

    # -------------------------------------------------------------------------
    # Rows 1..3: 3 x Xptat (3 x 22 = 66 x 14/6 um pfet_01v8_lvt, gate=vg)
    # -------------------------------------------------------------------------
    ptat_s_xs = ptat_sds[0::2]  # 12 columns (outer diffusions = vdd)
    ptat_d_xs = ptat_sds[1::2]  # 11 columns (out)
    vg_ys: list[float] = []
    out_e_ys: list[float] = []

    for dy_r, y_tap_above in ((dy1, y_tap2), (dy2, y_tap3), (dy3, y_top_ring)):
        c.include(p_ptat, dx=0.0, dy=dy_r)
        add_tied_field_poly_dummies(
            c, ptat_pd_x1, ptat_pd_x2, grid(dy_r + ptat_pd_y1), grid(dy_r + ptat_pd_y2), y_tap_above
        )
        y_v_lo = grid(dy_r - 4.60)
        y_v_hi = grid(dy_r + 4.80)
        y_o_lo = grid(dy_r - 1.50)
        y_o_hi = grid(dy_r + 1.70)
        y_g    = grid(dy_r + ptat_gy_rel)

        for yv in (y_v_lo, y_v_hi):
            for sx in ptat_s_xs:
                c.via1(sx, yv)
            c.wire("metal2", [(x_wall_l, yv), (x_wall_r, yv)], 0.80)
            c.via1(x_wall_l, yv)
            c.via1(x_wall_r, yv)
            for xv in vdd_m3_xs:
                via2_clean(c, xv, yv)

        for yo in (y_o_lo, y_o_hi):
            for dx_col in ptat_d_xs:
                c.via1(dx_col, yo)
            c.wire("metal2", [(ptat_d_xs[0], yo), (x_out_m3_e, yo)], 0.80)
            for xo in (*out_m3_xs, x_out_m3_e):
                via2_clean(c, xo, yo)
            out_e_ys.append(yo)

        c.wire("metal1", [(ptat_gxs[0], y_g), (ptat_gxs[-1], y_g)], 0.32)
        for gx in ptat_gxs[::3] + [ptat_gxs[-1]]:
            c.via1(gx, y_g)
        c.wire("metal2", [(x_vg_m3, y_g), (ptat_gxs[-1], y_g)], 0.36)
        via2_clean(c, x_vg_m3, y_g)
        vg_ys.append(y_g)

    # Vertical M3 spines (0.0% M5!)
    for xv in vdd_m3_xs:
        c.wire("metal3", [(xv, y_bot_ring), (xv, y_top_ring)], 1.00)

    y_out_top = grid(dy3 + 1.70)
    for xo in out_m3_xs:
        c.wire("metal3", [(xo, y_c_out), (xo, y_out_top)], 1.00)
    c.wire("metal3", [(x_out_m3_e, min(out_e_ys)), (x_out_m3_e, max(out_e_ys))], 1.00)

    # Central horizontal M4 `out` collector bar tying all 4 M3 spines -> East perimeter port
    y_out_m4 = 29.00
    c.wire("metal4", [(out_m3_xs[0], y_out_m4), (x_port_e, y_out_m4)], 1.20)
    for xo in (*out_m3_xs, x_out_m3_e):
        via3_array(c, xo, y_out_m4, nx=2, ny=2)

    # West vertical M3 `vg` trunk -> West perimeter port at (-74.00, 27.86)
    c.wire("metal3", [(x_vg_m3, min(vg_ys)), (x_vg_m3, max(vg_ys))], 0.50)
    y_vg_port = vg_ys[1]  # 27.86 (Row 2 gate)
    c.wire("metal2", [(x_port_w, y_vg_port), (x_vg_m3, y_vg_port)], 0.40)

    # Export all 4 perimeter ports in exact `serdes_bias_cml_blend_v2` order
    c.port("out", "metal4", x_port_e, y_out_m4)
    c.port("vgi", "metal2", x_port_w, y_c_gate)
    c.port("vg",  "metal2", x_port_w, y_vg_port)
    c.port("vdd", "metal4", 0.00, y_top_ring)

    mag = work / f"{CELL_NAME}.mag"
    c.write(mag)
    ref = make_reference_spice(work / f"{CELL_NAME}_ref.spice")

    # Full-rule Magic DRC + LVS + CPEX extraction
    lvs_sp = work / f"{CELL_NAME}_lvs.spice"
    pex_sp = work / f"{CELL_NAME}_pex.spice"
    lvs_log = work / f"{CELL_NAME}_lvs.log"
    tcl = work / "_check_pex.tcl"
    tcl.write_text("\n".join([
        "drc off",
        f"load {CELL_NAME}",
        "select top cell",
        "drc on",
        "drc euclidean on",
        "drc style drc(full)",
        "drc check",
        "drc catchup",
        'puts "DRC_TOTAL=[drc list count total]"',
        'foreach {why boxes} [drc listall why] { puts "DRC_RULE [llength $boxes] | $why" }',
        "extract all",
        "ext2spice lvs",
        f"ext2spice -o {lvs_sp.name}",
        "ext2spice cthresh 0",
        "ext2spice rthresh infinite",
        f"ext2spice -o {pex_sp.name}",
        "quit -noprompt",
        "",
    ]))
    res = mu.run_magic(tcl, work)
    (work / "_check_pex.log").write_text(res.log)
    res.need(f"DRC+PEX {CELL_NAME}")

    m_drc = re.search(r"DRC_TOTAL=(\d+)", res.log)
    drc_total = int(m_drc.group(1)) if m_drc else -1
    drc_rules = [ln[len("DRC_RULE "):] for ln in res.log.splitlines() if ln.startswith("DRC_RULE ")]

    ng = mu.netgen(lvs_sp, CELL_NAME, ref, lvs_log, work)
    lvs_txt = lvs_log.read_text() if lvs_log.exists() else (ng.stdout + ng.stderr)
    lvs_match = "Circuits match uniquely" in lvs_txt
    lvs_prop_err = "Property errors were found" in lvs_txt
    disc = sorted(set(re.findall(r"disconnected node:\s*(\S+)", lvs_txt, re.I)))

    ports = exported_ports(lvs_sp, CELL_NAME) if lvs_sp.exists() else []
    parasitics = summarize_pex_spice(pex_sp, ports) if pex_sp.exists() else {}

    # Extracted model counts
    models = Counter(re.findall(r"\b(sky130_fd_pr__\S+)", lvs_sp.read_text())) if lvs_sp.exists() else Counter()

    box = Cell.read(mag).bbox()
    w_um = round(box[2] - box[0], 3)
    h_um = round(box[3] - box[1], 3)
    m5_rects = len(c.rects.get("metal5", []))
    fpoly = count_floating_poly(c)

    title = f"{CELL_NAME} | DRC={drc_total}, LVS={'MATCH' if lvs_match else 'FAIL'}"
    render_png(mag, work / f"{CELL_NAME}.png", title)

    return dict(
        cell=CELL_NAME,
        bbox_um=list(box),
        width_um=w_um,
        height_um=h_um,
        area_um2=round(w_um * h_um, 2),
        aspect_ratio=round(w_um / h_um, 2),
        drc_total=drc_total,
        drc_rules=drc_rules,
        lvs_match=lvs_match,
        lvs_property_errors=lvs_prop_err,
        lvs_disconnected=disc,
        exported_ports=ports,
        expected_ports=EXPECTED_PORTS,
        ports_exact_match=(ports == EXPECTED_PORTS),
        floating_poly=fpoly,
        m5_rects=m5_rects,
        m5_usage_pct=0.0 if m5_rects == 0 else round(100.0 * m5_rects / max(1, sum(len(v) for v in c.rects.values())), 2),
        extracted_models=dict(models),
        parasitics=parasitics,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--install-dir", type=Path, default=None)
    args = ap.parse_args()

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rec = build_ptat_bias(out)
    (out / "summary.json").write_text(json.dumps(rec, indent=2) + "\n")
    print(json.dumps({k: v for k, v in rec.items() if k != "parasitics"}, indent=2), flush=True)

    if args.install_dir:
        inst = args.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "summary.json", inst / "summary.json")
        cdir = out / CELL_NAME
        for ext in (".mag", ".png", "_ref.spice", "_lvs.spice", "_pex.spice"):
            src = cdir / f"{CELL_NAME}{ext}"
            if src.exists():
                shutil.copy2(src, inst / src.name)


if __name__ == "__main__":
    main()
