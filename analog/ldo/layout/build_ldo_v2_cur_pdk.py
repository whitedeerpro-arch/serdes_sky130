#!/usr/bin/env python3
"""Build and verify the LDO v2 Current-Mode Bias Input PDK layout (`v2_cur_pdk`).

Fixes the BIAS v2 (`serdes_bias_top_v2_pdk`) vs LDO v2 (`serdes_pll_supply_hv18_v2_pdk`)
interface mismatch:
  - `serdes_bias_top_v2_pdk` keeps high-Z `vgi` locked internally and exports 10 uA
    current-mode outputs `i_ldo0` / `i_ldo1` (4x 8/4 `pfet_01v8_lvt`).
  - Legacy `serdes_pll_supply_hv18_v2_pdk` expected voltage pin `vgi` and instantiated
    a redundant BIAS v1 `serdes_bias_pcopy_pdk` (w=24/4, -25% vs v2 w=32/4).
  - `serdes_pll_supply_hv18_v2_cur_pdk` removes `Xcopy` (`p_copy`) and routes West
    current-mode port `i_ldo` directly along `y_trk_ib` into `serdes_ldo_hv18_core_v2`'s
    local 1:1 unit-finger-matched 5 V NMOS diode mirror (`Xnb` 30/2 nf=6 -> `Xnr` 30/2 nf=6,
    `Xpre_sink` 9/2 nf=3, and shutdown clamp `Xboff` 10/0.5).

Preserves 100% of LDO v2's verified 60.00 pF stacked+fused MIM2 bay, HV PMOS pre-regulator,
47-bar common-centroid divider, active 0.15 um overshoot clamp, and low-IR NVT power stage.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "verification/layout"))
sys.path.insert(0, str(HERE))

from geometry import Cell, pdk_device  # noqa: E402
import build_ldo_v2_pdk as v2  # noqa: E402

SPICE_DIR = REPO / "analog/ldo/spice"

PROD_PORTS = ["vin", "host", "quiet", "bg", "i_ldo", "enable", "t0", "t1", "t2", "t3", "t4", "t5", "vss"]
PROBE_PORTS = ["vin", "host", "quiet", "bg", "i_ldo", "enable", "t0", "t1", "t2", "t3", "t4", "t5", "fb_return", "fb_input", "vss"]


def make_reference_spice_cur(out_path: Path, cell_name: str, is_probe: bool) -> Path:
    src_name = "serdes_pll_supply_hv18_v2_cur_probe" if is_probe else "serdes_pll_supply_hv18_v2_cur"
    ports = PROBE_PORTS if is_probe else PROD_PORTS
    pll_sp = (SPICE_DIR / "pll_supply_hv18_v2_cur.spice").read_text()
    pll_sp = re.sub(
        r"^Xinv\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+serdes_cmos_inv\b[^\n]*$",
        "Xinv_n \\2 \\1 \\4 \\4 sky130_fd_pr__nfet_01v8 w=1 l=0.15\n"
        "Xinv_p \\2 \\1 \\3 \\3 sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        pll_sp, flags=re.M,
    )
    pll_sp = re.sub(
        r"^Xrefgate\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+serdes_cmos_tgate\s+wn=2\s+wp=4\b[^\n]*$",
        "Xrefgate_n \\1 \\3 \\2 \\6 sky130_fd_pr__nfet_01v8 w=2 l=0.15\n"
        "Xrefgate_p \\1 \\4 \\2 \\5 sky130_fd_pr__pfet_01v8 w=4 l=0.15",
        pll_sp, flags=re.M,
    )
    pll_sp = re.sub(
        r"^(X\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+serdes_nfet\s+w=([0-9.]+)\s+l=([0-9.]+)\s*$",
        r"\1 \2 \3 \4 \5 sky130_fd_pr__nfet_01v8 w=\6 l=\7",
        pll_sp, flags=re.M,
    )
    chunks = [
        f"* LVS reference netlist for {cell_name}",
        v2._make_1level_passives_spice(),
        (SPICE_DIR / "ldo_hv18_core_v2.spice").read_text(),
        pll_sp,
        f".subckt {cell_name} " + " ".join(ports),
        f"Xtop " + " ".join(ports) + f" {src_name}",
        f".ends {cell_name}",
        "",
    ]
    out_path.write_text("\n".join(chunks))
    return out_path


def render_png_cur(mag: Path, out_png: Path, title: str) -> None:
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

    fig, ax = plt.subplots(figsize=(18, max(7.6, 18 * h / max(w, 1.0))), dpi=180)
    ax.set_facecolor("white")

    present = set()
    for layer, rx1, ry1, rx2, ry2 in rects:
        if layer not in pm.COLORS:
            continue
        present.add(layer)
        is_mim = layer in ("mimcap", "mimcap2")
        alpha = 0.28 if is_mim else (0.62 if layer in ("m1", "m2", "m3", "m4", "m5") else 0.90)
        ec = "#d97706" if layer == "mimcap" else ("#059669" if layer == "mimcap2" else "none")
        ax.add_patch(
            Rectangle(
                (rx1, ry1), rx2 - rx1, ry2 - ry1,
                facecolor=pm.COLORS[layer],
                edgecolor=ec, linewidth=0.7 if is_mim else 0.0,
                hatch="//" if is_mim else None,
                alpha=alpha, zorder=pm.Z[layer],
            )
        )

    for zx, lbl in [(92, "Zone 1: 60 pF Stacked MIM2 Bay + Under-MIM Passives / Divider / Clamp (Current-Mode i_ldo)"),
                    (230, "Zone 2: EA + Pre-Reg\n(Xnb/Xnr 1:1 Mirror)"),
                    (282, "Zone 3: Power\nXcas | Xpass")]:
        ax.text(zx, y2 + 2.2, lbl, color="#1e3a8a", fontsize=8.5, ha="center", va="bottom", fontweight="bold", zorder=110)

    west_stagger = {"enable": (-10.5, +4.2), "bg": (-10.5, +0.8), "host": (-10.5, -2.6), "i_ldo": (-10.5, -6.0)}
    for nm, px, py in labels:
        ax.plot(px, py, "o", color="#111827", markersize=4.0, markeredgecolor="#ffffff", markeredgewidth=0.6, zorder=105)
        if nm in west_stagger:
            dx_l, dy_l = west_stagger[nm]
            ax.annotate(
                nm, xy=(px, py), xytext=(px + dx_l, py + dy_l),
                color="#111827", fontsize=7.5, fontweight="bold", ha="right", va="center", zorder=110,
                arrowprops=dict(arrowstyle="-", color="#2563eb", lw=0.9),
                bbox=dict(boxstyle="round,pad=0.14", facecolor="#ffffff", edgecolor="#2563eb", alpha=0.95),
            )
        else:
            ax.text(
                px, py, f" {nm}", color="#111827", fontsize=8.0, fontweight="bold", zorder=110,
                bbox=dict(boxstyle="round,pad=0.14", facecolor="#ffffff", edgecolor="#2563eb", alpha=0.92),
            )

    ax.set_xlim(x1 - 24, x2 + 26)
    ax.set_ylim(y1 - 11, y2 + 11)
    ax.set_aspect("equal")
    ax.set_xlabel("X (µm)")
    ax.set_ylabel("Y (µm)")
    ax.grid(True, lw=0.25, alpha=0.35)
    ax.set_title(f"{title}  ({w:.1f} × {h:.1f} µm = {w*h:,.0f} µm²)", fontsize=12, fontweight="bold")
    legend_keys = [k for k in pm.COLORS if k in present]
    handles = [Rectangle((0, 0), 1, 1, facecolor=pm.COLORS[k],
                         edgecolor="#d97706" if k == "mimcap" else ("#059669" if k == "mimcap2" else "none"),
                         hatch="//" if k in ("mimcap", "mimcap2") else None) for k in legend_keys]
    ax.legend(handles, legend_keys, fontsize=6.2, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0.0, ncol=1)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def count_floating_poly(cell_obj: Cell) -> int:
    """Count poly islands with zero overlap against polycont, gates, or ppolyres."""
    polys = cell_obj.rects.get("poly", [])
    anchors = []
    for lay in ("polycont", "nmos", "nmoslvt", "pmos", "pmoslvt", "mvnmos", "mvnnmos", "mvpmos", "ppolyres", "xpolycontact", "varactor"):
        anchors.extend(cell_obj.rects.get(lay, []))
    if not polys:
        return 0
    # Build connected components of touching/overlapping poly rects
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

    # Spatial sort by x1
    order = sorted(range(n), key=lambda k: polys[k][0])
    for idx_a in range(n):
        i = order[idx_a]
        ax1, ay1, ax2, ay2 = polys[i]
        for idx_b in range(idx_a + 1, n):
            j = order[idx_b]
            bx1, by1, bx2, by2 = polys[j]
            if bx1 > ax2 + 1e-6:
                break
            if not (by2 < ay1 - 1e-6 or by1 > ay2 + 1e-6):
                union(i, j)

    comp_anchored: dict[int, bool] = {find(i): False for i in range(n)}
    for i, (px1, py1, px2, py2) in enumerate(polys):
        ri = find(i)
        if comp_anchored[ri]:
            continue
        for ax1, ay1, ax2, ay2 in anchors:
            if not (ax2 < px1 - 1e-6 or ax1 > px2 + 1e-6 or ay2 < py1 - 1e-6 or ay1 > py2 + 1e-6):
                comp_anchored[ri] = True
                break
    return sum(1 for v in comp_anchored.values() if not v)


def build_supply_v2_cur(out: Path, is_probe: bool, extract_rcx: bool = True) -> dict:
    """Build complete flat LDO v2 current-mode supply macro (DRC=0, LVS=MATCH, 0 floating poly)."""
    grid = v2.grid
    via2_clean = v2.via2_clean
    via3_single = v2.via3_single
    via3_array = v2.via3_array
    via34_pillar_v = v2.via34_pillar_v
    via4_array = v2.via4_array
    draw_pwell_guard_h = v2.draw_pwell_guard_h
    draw_pwell_guard_v = v2.draw_pwell_guard_v
    place_stacked_mim = v2.place_stacked_mim
    strap_mos_5v_multirow = v2.strap_mos_5v_multirow
    strap_mos_5v_single = v2.strap_mos_5v_single
    strap_mos_5v_single_dummies = v2.strap_mos_5v_single_dummies
    strap_1v8_m2 = v2.strap_1v8_m2
    place_res_snake = v2.place_res_snake
    place_res_single = v2.place_res_single
    place_rdiv_cc26 = v2.place_rdiv_cc26
    place_rdiv_trim21 = v2.place_rdiv_trim21

    cell = "serdes_pll_supply_hv18_v2_cur_probe_pdk" if is_probe else "serdes_pll_supply_hv18_v2_cur_pdk"
    work = out / cell
    work.mkdir(parents=True, exist_ok=True)
    pwork = out / "_prims_shared"
    pwork.mkdir(exist_ok=True)

    specs = {
        "nvt_25x2": ("sky130_fd_pr__nfet_05v0_nvt", dict(w=10.0, l=0.9, nf=25, m=2, poverlap=0, conn_gates=1, guard=1)),
        "nvt_15x2": ("sky130_fd_pr__nfet_05v0_nvt", dict(w=10.0, l=0.9, nf=15, m=2, poverlap=0, conn_gates=1, guard=1)),
        "pre_p":    ("sky130_fd_pr__pfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=15, m=2, conn_gates=1, guard=1)),
        "pre_d":    ("sky130_fd_pr__pfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=15, m=4, conn_gates=1, guard=1)),
        "p2_150":   ("sky130_fd_pr__pfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=15, m=2, conn_gates=1, guard=1)),
        "pt_120":   ("sky130_fd_pr__pfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=12, m=2, conn_gates=1, guard=1)),
        "pl_60":    ("sky130_fd_pr__pfet_g5v0d10v5", dict(w=5.0, l=1.0, nf=14, m=1, conn_gates=0, guard=0)),
        "pd_30":    ("sky130_fd_pr__pfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=6,  m=1, conn_gates=1, guard=1)),
        "nb_30":    ("sky130_fd_pr__nfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=6,  m=1, conn_gates=1, guard=1)),
        "nl_20":    ("sky130_fd_pr__nfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=6,  m=1, conn_gates=0, guard=0)),
        "pre_sink": ("sky130_fd_pr__nfet_g5v0d10v5", dict(w=3.0, l=2.0, nf=3,  m=1, conn_gates=1, guard=1)),
        "n2_90":    ("sky130_fd_pr__nfet_g5v0d10v5", dict(w=5.0,  l=0.5, nf=18, m=1, conn_gates=1, guard=1)),
        "off_10":   ("sky130_fd_pr__nfet_g5v0d10v5", dict(w=5.0,  l=0.5, nf=2,  m=1, conn_gates=1, guard=1)),
        "rref32":   ("sky130_fd_pr__res_high_po_0p35", dict(w=0.5, l=75.640, nx=32, m=1, guard=1)),
        "rpreoff24":("sky130_fd_pr__res_high_po_0p35", dict(w=0.5, l=75.640, nx=24, m=1, guard=1)),
        "rf8":      ("sky130_fd_pr__res_high_po_0p35", dict(w=0.5, l=75.640, nx=8,  m=1, guard=1)),
        "rf5":      ("sky130_fd_pr__res_high_po_0p35", dict(w=0.5, l=75.640, nx=5,  m=1, guard=1)),
        "rdiv26":   ("sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=11.425, nx=28, m=1, guard=1)),
        "rdiv21":   ("sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=11.425, nx=23, m=1, guard=1)),
        "r12k":     ("sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=36.660, nx=1, m=1, guard=1)),
        "r5k":      ("sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=14.580, nx=1, m=1, guard=1)),
        "clamp_144":("sky130_fd_pr__nfet_01v8", dict(w=4.0, l=0.15, nf=18, m=2, conn_gates=1, guard=1)),
        "clp2_96":  ("sky130_fd_pr__pfet_01v8", dict(w=6.0, l=0.15, nf=16, m=1, conn_gates=1, guard=1)),
        "cln1_56":  ("sky130_fd_pr__nfet_01v8", dict(w=4.0, l=0.15, nf=14, m=1, conn_gates=1, guard=1)),
        "clnref_24":("sky130_fd_pr__nfet_01v8", dict(w=4.0, l=0.15, nf=6,  m=1, conn_gates=1, guard=1)),
        "n_w4_nf2": ("sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=2,  m=1, conn_gates=1, guard=1)),
        "p_w4_nf2": ("sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.15, nf=2,  m=1, conn_gates=1, guard=1)),
        "sw_n20":   ("sky130_fd_pr__nfet_01v8", dict(w=5.0, l=0.15, nf=4,  m=1, conn_gates=1, guard=1)),
        "n_w2":     ("sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=1,  m=1, conn_gates=1, guard=1)),
        "n_w1":     ("sky130_fd_pr__nfet_01v8", dict(w=1.0, l=0.15, nf=1,  m=1, conn_gates=1, guard=1)),
        "p_w2":     ("sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.15, nf=1,  m=1, conn_gates=1, guard=1)),
        "p_w4":     ("sky130_fd_pr__pfet_01v8", dict(w=4.0, l=0.15, nf=1,  m=1, conn_gates=1, guard=1)),
    }
    prims: dict[str, Cell] = {}
    for nm, (mdl, par) in specs.items():
        pmag = pwork / f"{nm}.mag"
        p = Cell.read(pmag) if pmag.exists() else pdk_device(pwork, nm, mdl, par)
        p.rects.pop("checkpaint", None)
        prims[nm] = p

    top = Cell()

    # ZONE 1: 60.00 pF Stacked + Fused MIM1/MIM2 Bay
    m_ccas = place_stacked_mim(top, pwork, "ccas", 29.415, 2, 3, dx_c=33.4,  dy_c=+0.5,  shared_vss=True, a_off=7.9, b3_off=2.0, b5_off=5.5)
    m_cref = place_stacked_mim(top, pwork, "cref", 29.415, 1, 3, dx_c=87.6,  dy_c=+4.5,  shared_vss=True, a_off=1.9, b3_off=2.0, b5_off=2.5)
    m_cva  = place_stacked_mim(top, pwork, "cva",  29.415, 2, 2, dx_c=144.3, dy_c=-15.4, shared_vss=True, a_off=1.9, b3_off=2.0, b5_off=2.5)
    m_cout = place_stacked_mim(top, pwork, "cout", 29.415, 2, 1, dx_c=144.3, dy_c=+36.15, shared_vss=True, a_off=2.2, b3_off=1.9, b5_off=2.6)

    m_chp  = place_stacked_mim(top, pwork, "chp",  22.195, 1, 1, dx_c=194.2, dy_c=+38.7, shared_vss=False, a_off=1.5, b3_off=1.8, b5_off=2.5, pillar_dx=2.8)
    m_cpre = place_stacked_mim(top, pwork, "cpre", 22.195, 1, 1, dx_c=194.2, dy_c=+10.9, shared_vss=False, a_off=1.6, b3_off=1.8, b5_off=2.5, pillar_dx=2.8)
    m_cc   = place_stacked_mim(top, pwork, "cc",   15.600, 1, 1, dx_c=193.2, dy_c=-13.5, shared_vss=False, a_off=1.6, b3_off=1.8, b5_off=2.5, pillar_dx=3.2)
    m_cghf = place_stacked_mim(top, pwork, "cghf", 15.600, 1, 1, dx_c=193.2, dy_c=-34.5, shared_vss=False, a_off=1.6, b3_off=1.8, b5_off=2.5, pillar_dx=3.6)
    m_cbp  = place_stacked_mim(top, pwork, "cbp",  13.500, 1, 1, dx_c=193.2, dy_c=-54.4, shared_vss=False, a_off=1.6, b3_off=1.8, b5_off=2.5, pillar_dx=2.8)
    m_cff  = place_stacked_mim(top, pwork, "cff",  13.500, 1, 1, dx_c=87.6,  dy_c=-54.8, shared_vss=False, a_off=1.8, b3_off=1.8, b5_off=2.5, pillar_dx=3.0)

    x_vss_west = -5.30
    x_vss_mid  = 105.4
    y_vss_m3_bot = -48.8
    y_vss_m5_top = +54.3
    top.wire("metal3", [(x_vss_west, y_vss_m3_bot), (m_ccas["b3_pts"][-1][0], y_vss_m3_bot)], 1.2)
    top.wire("metal3", [(m_cref["b3_pts"][0][0], m_cref["yb3"]), (x_vss_mid, m_cref["yb3"])], 1.2)
    top.wire("metal3", [(x_vss_mid, y_vss_m3_bot), (m_cva["b3_pts"][-1][0], y_vss_m3_bot)], 1.2)
    top.wire("metal5", [(x_vss_west, y_vss_m5_top), (175.0, y_vss_m5_top)], 1.8)
    y_vss_m5_east = +55.92
    top.wire("metal5", [(175.0, y_vss_m5_top), (175.0, y_vss_m5_east), (251.5, y_vss_m5_east)], 1.6)
    for mm in (m_ccas, m_cva):
        for bx, _ in mm["b3_pts"]:
            top.wire("metal3", [(bx, mm["yb3"]), (bx, y_vss_m3_bot)], 1.2)
    for mm in (m_ccas, m_cref, m_cout):
        for bx, _ in mm["b5_pts"]:
            top.wire("metal5", [(bx, mm["yb5"]), (bx, y_vss_m5_top)], 1.6)
    top.wire("metal5", [(x_vss_mid, m_cva["yb5"]), (m_cva["b5_pts"][-1][0], m_cva["yb5"])], 1.6)
    top.wire("metal3", [(x_vss_mid, m_cout["yb3"]), (m_cout["b3_pts"][-1][0], m_cout["yb3"])], 1.6)
    top.wire("metal3", [(x_vss_west, y_vss_m3_bot), (x_vss_west, y_vss_m5_top)], 1.6)
    top.wire("metal5", [(x_vss_west, y_vss_m3_bot), (x_vss_west, y_vss_m5_top)], 1.6)
    via34_pillar_v(top, x_vss_west, +53.5)
    via34_pillar_v(top, x_vss_west, -50.2)
    top.wire("metal3", [(x_vss_mid, -51.4), (x_vss_mid, y_vss_m5_top)], 1.6)
    top.wire("metal5", [(x_vss_mid, -51.4), (x_vss_mid, y_vss_m5_top)], 1.6)
    for y_mv in (+53.5, +18.8):
        top.rect("metal3", grid(x_vss_mid - 0.8), grid(y_mv - 0.8), grid(x_vss_mid + 0.8), grid(y_mv + 0.8))
        top.rect("metal4", grid(x_vss_mid - 0.8), grid(y_mv - 0.8), grid(x_vss_mid + 0.8), grid(y_mv + 0.8))
        for vx in (-0.35, 0.35):
            for vy in (-0.35, 0.35):
                top.pad("via3", grid(x_vss_mid + vx), grid(y_mv + vy), 0.32)
        top.pad("via4", x_vss_mid, y_mv, 1.18)
    via34_pillar_v(top, x_vss_mid, -51.4)

    # Under-MIM passives, matched divider, active clamp & south control (Xcopy removed!)
    p_rcas    = place_res_snake(top, prims["rf8"],        8, dx=11.0,  dy=+2.5, reverse=True)
    p_rref    = place_res_snake(top, prims["rref32"],    32, dx=43.0,  dy=+2.5)
    p_rpreoff = place_res_snake(top, prims["rpreoff24"], 24, dx=84.5,  dy=+2.5)
    p_rpre    = place_res_snake(top, prims["rf8"],        8, dx=109.0, dy=+2.5)
    p_rcl_arr = place_res_snake(top, prims["rf5"],        5, dx=124.5, dy=+2.5, split_idx=4)

    p_rdiv_top = place_rdiv_cc26(top, prims["rdiv26"], dx=163.5, dy=-11.5)
    p_rdiv_bot = place_rdiv_trim21(top, prims["rdiv21"], dx=163.5, dy=-37.0)

    p_cl_r1   = place_res_single(top, prims["r12k"], dx=150.0, dy=+24.8)
    p_cl_r2   = place_res_single(top, prims["r5k"],  dx=164.5, dy=+12.5)
    p_clamp   = strap_1v8_m2(top, prims["clamp_144"], "ndiffc", dx=181.5, dy=+38.0, tie_sb=True)
    p_cl_p2   = strap_1v8_m2(top, prims["clp2_96"],   "pdiffc", dx=181.5, dy=+25.0, tie_sb=True)
    p_cl_n1   = strap_1v8_m2(top, prims["cln1_56"],   "ndiffc", dx=181.5, dy=+14.5, tie_sb=True)
    p_cl_nref = strap_1v8_m2(top, prims["clnref_24"], "ndiffc", dx=181.5, dy=+5.5,  tie_sb=True)
    p_cl_en   = strap_1v8_m2(top, prims["p_w4_nf2"],  "pdiffc", dx=194.5, dy=+25.0, tie_sb=True)
    p_cl_off  = strap_1v8_m2(top, prims["n_w4_nf2"],  "ndiffc", dx=194.5, dy=+14.5, tie_sb=True)
    p_cl_off2 = strap_1v8_m2(top, prims["n_w4_nf2"],  "ndiffc", dx=194.5, dy=+5.5,  tie_sb=True)
    p_rzero   = place_res_single(top, prims["r5k"], dx=203.5, dy=-22.5)

    y_south_dev = -52.5
    p_tg_n  = strap_1v8_m2(top, prims["n_w2"], "ndiffc", dx=5.0,  dy=y_south_dev, tie_sb=False)
    p_tg_p  = strap_1v8_m2(top, prims["p_w4"], "pdiffc", dx=13.5, dy=y_south_dev, tie_sb=False)
    p_inv_n = strap_1v8_m2(top, prims["n_w1"], "ndiffc", dx=22.0, dy=y_south_dev, tie_sb=True)
    p_inv_p = strap_1v8_m2(top, prims["p_w2"], "pdiffc", dx=30.0, dy=y_south_dev, tie_sb=True)
    p_rst_n = strap_1v8_m2(top, prims["n_w2"], "ndiffc", dx=38.0, dy=y_south_dev, tie_sb=True)
    # NOTE: Redundant v1 Xcopy (p_copy @ x=55.0) removed; i_ldo feeds Xnb/Xnr/Xpre_sink/Xboff directly!

    p_boff = strap_mos_5v_single(top, prims["off_10"], "mvndiffc", dx=112.0, dy=-53.2, tie_sb=True)
    p_off  = strap_mos_5v_single(top, prims["off_10"], "mvndiffc", dx=119.5, dy=-53.2, tie_sb=True)
    p_n2   = strap_mos_5v_single(top, prims["n2_90"],  "mvndiffc", dx=131.5, dy=-53.2, tie_sb=True)

    sw_xs = [147.0, 153.0, 159.0, 165.0, 171.0, 177.0]
    p_sws = [strap_1v8_m2(top, prims["sw_n20"], "ndiffc", dx=sx, dy=-53.4, tie_sb=(k == 0)) for k, sx in enumerate(sw_xs)]

    # ZONE 2: EA & HV PMOS Pre-Regulator
    x_ea = 230.2
    p_pre_p = strap_mos_5v_multirow(top, prims["pre_p"], "mvpdiffc", dx=x_ea, dy=+48.6, tie_sb=True)
    top.rect("nwell", grid(x_ea - 19.6), -42.4, grid(x_ea + 19.6), +38.6)
    p_pre_d = strap_mos_5v_multirow(top, prims["pre_d"],  "mvpdiffc", dx=x_ea, dy=+25.1, tie_sb=True)
    p_p2    = strap_mos_5v_multirow(top, prims["p2_150"], "mvpdiffc", dx=x_ea, dy=+4.2,  tie_sb=True)
    p_pt    = strap_mos_5v_multirow(top, prims["pt_120"], "mvpdiffc", dx=x_ea, dy=-10.4, tie_sb=True)

    p_pl_a = strap_mos_5v_single_dummies(top, prims["pl_60"], "mvpdiffc", dx=grid(x_ea - 9.7), dy=-21.8, tie_outer_to_s=False)
    p_pr_a = strap_mos_5v_single_dummies(top, prims["pl_60"], "mvpdiffc", dx=grid(x_ea + 9.7), dy=-21.8, tie_outer_to_s=False)
    p_pr_b = strap_mos_5v_single_dummies(top, prims["pl_60"], "mvpdiffc", dx=grid(x_ea - 9.7), dy=-30.0, tie_outer_to_s=False)
    p_pl_b = strap_mos_5v_single_dummies(top, prims["pl_60"], "mvpdiffc", dx=grid(x_ea + 9.7), dy=-30.0, tie_outer_to_s=False)

    p_pd = strap_mos_5v_single(top, prims["pd_30"], "mvpdiffc", dx=grid(x_ea - 9.0), dy=-38.2, tie_sb=True)
    ntap_x1, ntap_x2, ntap_y = grid(x_ea + 2.0), grid(x_ea + 18.0), -38.2
    top.rect("mvnsubdiff", ntap_x1, grid(ntap_y - 0.5), ntap_x2, grid(ntap_y + 0.5))
    top.rect("mvnsubdiffcont", grid(ntap_x1 + 0.2), grid(ntap_y - 0.17), grid(ntap_x2 - 0.2), grid(ntap_y + 0.17))
    top.rect("locali", ntap_x1, grid(ntap_y - 0.5), ntap_x2, grid(ntap_y + 0.5))
    top.rect("metal1", ntap_x1, grid(ntap_y - 0.5), ntap_x2, grid(ntap_y + 0.5))
    for nx_t in (grid(x_ea + 4.0), grid(x_ea + 10.0), grid(x_ea + 16.0)):
        top.pad("viali", nx_t, ntap_y, 0.17)
        top.via1(nx_t, ntap_y)
    top.wire("metal2", [(grid(x_ea + 4.0), ntap_y), (249.6, ntap_y)], 0.48)
    via2_clean(top, 249.6, ntap_y)

    y_ea_gb = -43.9
    draw_pwell_guard_h(top, grid(x_ea - 19.0), grid(x_ea + 19.0), y_ea_gb, h=1.00)

    p_nb       = strap_mos_5v_single(top, prims["nb_30"],    "mvndiffc", dx=grid(x_ea - 10.0), dy=-48.6, tie_sb=True)
    p_nr       = strap_mos_5v_single(top, prims["nb_30"],    "mvndiffc", dx=grid(x_ea + 10.0), dy=-48.6, tie_sb=True)
    p_nl       = strap_mos_5v_single_dummies(top, prims["nl_20"], "mvndiffc", dx=217.6, dy=-56.4, tie_outer_to_s=True)
    p_nm       = strap_mos_5v_single_dummies(top, prims["nl_20"], "mvndiffc", dx=232.6, dy=-56.4, tie_outer_to_s=True)
    p_pre_sink = strap_mos_5v_single(top, prims["pre_sink"], "mvndiffc", dx=245.1, dy=-56.4, tie_sb=True)

    # ZONE 3: Guard Barrier + East IO-Edge NVT Power Stage
    y_vss_south = -63.8
    x_vgb = 251.5
    draw_pwell_guard_v(top, x_vgb, -60.5, +50.0, w=1.20, m3_y1=y_vss_south)

    pwr_ys = [+38.0, +12.5, -13.0, -38.5]
    x_cas = 269.0
    x_pass = 296.0
    p_cas = [strap_mos_5v_multirow(top, prims["nvt_25x2"], "mvndiffc", dx=x_cas, dy=py, tie_sb=False) for py in pwr_ys]
    p_pass = [strap_mos_5v_multirow(top, prims["nvt_15x2"], "mvndiffc", dx=x_pass, dy=py, tie_sb=False, m3_gate=False) for py in pwr_ys]

    # --- 1. POWER PLATE: vin ---
    x_vin_p1, x_vin_p2 = 258.0, 274.0
    top.rect("metal4", x_vin_p1, -48.0, x_vin_p2, +49.6)
    top.rect("metal5", x_vin_p1, -48.0, x_vin_p2, +56.0)
    for pc in p_cas:
        dy_b = pc["d_bus_y"]
        for xv in (260.0, 264.0, 268.0, 272.0):
            top.via2(xv, dy_b)
            via3_array(top, xv, dy_b, nx=2, ny=2)
    for yv4 in (-43.0, -23.0, -3.0, +17.0, +37.0, +47.5):
        via4_array(top, 266.0, yv4, nx=4, ny=1, pitch=2.4)
    via2_clean(top, x_ea, p_pre_p["s_bus_y"])
    via3_array(top, x_ea, p_pre_p["s_bus_y"], nx=2, ny=1)
    top.wire("metal4", [(x_ea, p_pre_p["s_bus_y"]), (x_ea, +42.0), (x_vin_p1 + 2.0, +42.0)], 1.4)
    top.wire("metal5", [m_cpre["b"], (x_vin_p1 + 2.0, m_cpre["b"][1])], 1.8)
    y_vin_m2 = +49.6
    for pt in (p_rcas["a"], p_rpreoff["a"]):
        top.wire("metal2", [pt, (pt[0], y_vin_m2)], 0.44)
    top.wire("metal2", [(p_rcas["a"][0], y_vin_m2), (210.0, y_vin_m2)], 0.48)
    via2_clean(top, 210.0, y_vin_m2)
    top.wire("metal3", [(210.0, y_vin_m2), (210.0, +42.2)], 0.48)
    via2_clean(top, 210.0, +42.2)
    top.wire("metal2", [(210.0, +42.2), (p_pre_p["s_xs"][0], +42.2), (p_pre_p["s_xs"][0], p_pre_p["s_bus_y"])], 0.48)

    # --- 2. POWER BRIDGE: mid ---
    for pc, pp in zip(p_cas, p_pass):
        for xm in (278.5, 281.5):
            top.via2(xm, pc["s_bus_y"])
            top.wire("metal3", [(xm, pc["s_bus_y"]), (xm, pp["d_bus_y"])], 1.40)
        for xp_m in (288.0, 292.0, 296.0, 300.0):
            top.via2(xp_m, pp["d_bus_y"])
        top.wire("metal3", [(278.5, pp["d_bus_y"]), (300.0, pp["d_bus_y"])], 1.60)
        top.wire("metal3", [(259.0, pc["s_bus_y"]), (281.5, pc["s_bus_y"])], 1.40)
    top.wire("metal3", [(281.5, p_cas[-1]["s_bus_y"]), (281.5, p_pass[0]["d_bus_y"])], 1.60)

    # --- 3. POWER PLATE: quiet + Kelvin sense ---
    x_q_p1, x_q_p2 = 288.0, 305.5
    top.rect("metal4", x_q_p1, -49.5, x_q_p2, +54.5)
    top.rect("metal5", x_q_p1, -49.5, x_q_p2, +54.5)
    for pp in p_pass:
        sy_b = pp["s_bus_y"]
        for xq in (290.0, 294.0, 298.0, 302.0):
            for dx_v2 in (-0.45, 0.0, +0.45):
                top.via2(grid(xq + dx_v2), sy_b)
            via3_array(top, xq, sy_b, nx=3, ny=2)
    for yv4 in (-45.0, -25.0, -10.0, 0.0, +15.0, +35.0, +49.5):
        via4_array(top, 297.5, yv4, nx=5, ny=1, pitch=2.4)

    y_q_m4 = grid(m_cout["ya"])
    for ax_c, ay_c in m_cout["a_pts"]:
        top.wire("metal4", [(ax_c, ay_c), (ax_c, y_q_m4)], 1.4)
    top.wire("metal4", [(m_cout["a_left"][0], y_q_m4), (x_q_p1 + 2.0, y_q_m4)], 1.8)
    top.wire("metal3", [(179.0, y_q_m4), (208.4, y_q_m4)], 1.6)
    for xq_m3 in (180.0, 189.0, 198.0, 206.0):
        via3_array(top, xq_m3, y_q_m4, nx=2, ny=2)
    top.wire("metal3", [(217.5, y_q_m4), (246.5, y_q_m4)], 1.6)
    for xq_m3 in (218.5, 226.0, 234.0, 241.0, 245.5):
        via3_array(top, xq_m3, y_q_m4, nx=2, ny=2)
    top.wire("metal3", [(256.8, y_q_m4), (288.0, y_q_m4)], 1.6)
    for xq_m3 in (258.0, 266.0, 274.0, 282.0, 287.0):
        via3_array(top, xq_m3, y_q_m4, nx=2, ny=2)
    x_q_up = grid(m_chp["b"][0] - 0.8)
    top.wire("metal3", [(x_q_up, m_chp["b"][1]), (x_q_up, y_q_m4)], 1.6)
    via3_array(top, x_q_up, y_q_m4, nx=3, ny=2)
    x_q_cl = x_q_up
    for dy_v2 in (-0.6, 0.0, +0.6, +1.2):
        via2_clean(top, x_q_cl, grid(p_clamp["D"][1] + dy_v2))
    top.wire("metal2", [(p_clamp["D"][0], p_clamp["D"][1]), (x_q_cl, p_clamp["D"][1])], 2.0)
    top.wire("metal2", [(p_clamp["d_xs"][0], p_clamp["D"][1]), (p_clamp["d_xs"][-1], p_clamp["D"][1])], 1.2)
    top.wire("metal3", [(x_q_cl, grid(p_clamp["D"][1] + 1.2)), (x_q_cl, grid(p_cl_p2["S"][1] - 0.6))], 1.4)
    for dy_p2 in (-0.45, 0.0, +0.45):
        via2_clean(top, x_q_cl, grid(p_cl_p2["S"][1] + dy_p2))
    top.wire("metal2", [(p_cl_p2["S"][0], p_cl_p2["S"][1]), (x_q_cl, p_cl_p2["S"][1])], 1.20)
    top.wire("metal2", [p_cl_en["S"], (p_cl_en["S"][0], p_cl_p2["S"][1])], 0.40)
    top.wire("metal2", [p_cl_r1["R1"], (p_cl_r1["R1"][0], +45.4), (p_clamp["D"][0], +45.4), p_clamp["D"]], 0.44)

    y_kelv_tap = -48.5
    via3_single(top, 304.8, y_kelv_tap)
    via2_clean(top, 304.8, y_kelv_tap)
    y_kelv_m2 = -62.7
    top.wire("metal2", [(304.8, y_kelv_tap), (304.8, y_kelv_m2), (m_cff["b"][0], y_kelv_m2)], 0.44)
    via2_clean(top, m_cff["b"][0], y_kelv_m2)
    top.wire("metal3", [(m_cff["b"][0], y_kelv_m2), m_cff["b"]], 0.60)
    x_kelv_up = 139.2
    via2_clean(top, x_kelv_up, y_kelv_m2)
    top.wire("metal3", [(x_kelv_up, y_kelv_m2), (x_kelv_up, -50.2)], 0.44)
    via2_clean(top, x_kelv_up, -50.2)
    top.wire("metal2", [(x_kelv_up, -50.2), (x_kelv_up, p_rdiv_top["quiet"][1]), p_rdiv_top["quiet"]], 0.44)

    # --- 4. POWER GROUND: vss ---
    top.wire("metal4", [(x_vss_west, y_vss_south), (305.0, y_vss_south)], 1.6)
    top.wire("metal3", [(x_vss_west, y_vss_south), (72.0, y_vss_south)], 1.4)
    top.wire("metal3", [(220.0, y_vss_south), (305.0, y_vss_south)], 1.4)
    for xv_s in (x_vss_west, 70.0, 222.0, x_vgb, 304.0):
        via3_array(top, xv_s, y_vss_south, nx=2, ny=2)
    top.wire("metal3", [(x_vss_west, y_vss_south), (x_vss_west, y_vss_m3_bot)], 1.4)
    top.wire("metal4", [(x_vss_mid, -51.4), (x_vss_mid, y_vss_south)], 1.6)
    top.wire("metal3", [m_cghf["b"], (m_cghf["b"][0], y_ea_gb)], 1.0)
    via2_clean(top, m_cghf["b"][0], y_ea_gb)
    top.wire("metal2", [(m_cghf["b"][0], y_ea_gb), (x_ea - 19.0, y_ea_gb)], 0.80)

    for pc, pp in zip(p_cas, p_pass):
        yb = pc["B"][1]
        top.wire("metal2", [(x_vgb, yb), pc["B"], (285.2, yb)], 0.52)
        top.via1(285.2, yb)
        top.wire("metal1", [(285.2, yb), (287.8, yb)], 0.52)
        top.via1(287.8, yb)
        top.wire("metal2", [(287.8, yb), pp["B"]], 0.52)

    top.wire("metal2", [(x_ea - 19.0, y_ea_gb), (x_vgb, y_ea_gb)], 0.80)
    for pm in (p_nb, p_nr, p_pre_sink):
        top.wire("metal2", [pm["B"], (x_vgb, pm["B"][1])], 0.48)
    top.wire("metal2", [p_nl["S"], (x_vgb, p_nl["S"][1])], 0.56)

    y_hr_b = -44.5
    top.wire("metal2", [(x_vss_west, y_hr_b), (135.5, y_hr_b)], 0.52)
    via2_clean(top, x_vss_west, y_hr_b)
    for pr in (p_rcas, p_rref, p_rpreoff, p_rpre, p_rcl_arr):
        top.wire("metal2", [pr["B"], (pr["B"][0], y_hr_b)], 0.40)

    y_sw_vss = -57.24
    top.wire("metal2", [(x_vss_west, y_sw_vss), (180.0, y_sw_vss)], 0.36)
    via2_clean(top, x_vss_west, y_sw_vss)
    for pm in (p_tg_n, p_inv_n, p_rst_n, p_boff, p_off, p_n2, *p_sws):
        top.wire("metal2", [pm["B"], (pm["B"][0], y_sw_vss)], 0.34)

    top.wire("metal2", [p_rdiv_bot["vss"], (p_rdiv_bot["vss"][0], -45.36), (141.5, -45.36), (141.5, y_sw_vss)], 0.42)
    top.wire("metal2", [p_rdiv_bot["B"], (141.5, p_rdiv_bot["B"][1])], 0.42)
    top.wire("metal2", [p_rdiv_top["B"], (135.5, p_rdiv_top["B"][1]), (135.5, y_hr_b)], 0.44)
    top.wire("metal2", [p_rzero["B"], (210.8, p_rzero["B"][1]), (210.8, y_ea_gb), (x_ea - 19.0, y_ea_gb)], 0.44)

    x_cl_vss = 210.4
    y_cl_gnd = p_clamp["S_right"][1]
    top.wire("metal2", [(x_cl_vss, y_ea_gb), (x_cl_vss, y_cl_gnd)], 0.56)
    top.wire("metal2", [(x_cl_vss, p_cl_n1["B"][1]), (x_cl_vss, y_cl_gnd)], 1.20)
    top.wire("metal2", [(x_cl_vss, y_ea_gb), (x_ea - 19.0, y_ea_gb)], 0.56)
    top.wire("metal2", [p_clamp["S"], (x_cl_vss, y_cl_gnd)], 2.20)
    for dy_v in (-1.2, -0.6, 0.0, +0.6, +1.2):
        via2_clean(top, x_cl_vss, grid(y_cl_gnd + dy_v))
    via3_array(top, x_cl_vss, y_cl_gnd, nx=1, ny=5, pitch=0.60)
    top.wire("metal4", [(x_cl_vss, y_cl_gnd), (x_vgb, y_cl_gnd)], 2.80)
    via3_array(top, x_vgb, y_cl_gnd, nx=2, ny=4, pitch=0.60)
    top.wire("metal4", [(x_vgb, -47.0), (x_vgb, +21.5)], 2.20)
    for y_r in (-45.0, -25.0, -5.0, +15.0, +20.0):
        via3_array(top, x_vgb, y_r, nx=2, ny=2)
    top.wire("metal5", [(x_vgb, +18.0), (x_vgb, grid(y_vss_m5_east - 0.7))], 3.00)
    via4_array(top, x_vgb, y_cl_gnd, nx=1, ny=2, pitch=2.1)
    via4_array(top, x_vgb, +19.2, nx=1, ny=1)
    y_vss_m5_south = -63.50
    top.wire("metal5", [(x_vgb, grid(y_vss_m5_south + 0.4)), (x_vgb, +3.6)], 3.00)
    for yv_g in (+1.5, -20.0, -43.0):
        via4_array(top, x_vgb, yv_g, nx=1, ny=2, pitch=2.1)
    top.wire("metal5", [(x_vgb, y_vss_m5_south), (304.5, y_vss_m5_south)], 2.20)
    top.wire("metal4", [(x_vgb, y_vss_m5_south), (304.5, y_vss_m5_south)], 2.20)
    via4_array(top, x_vgb, y_vss_m5_south, nx=2, ny=1, pitch=2.1)
    via4_array(top, 303.0, y_vss_m5_south, nx=2, ny=1, pitch=2.1)
    top.wire("metal2", [p_cl_n1["B"], (x_cl_vss, p_cl_n1["B"][1])], 1.00)
    for pm in (p_cl_nref, p_cl_off, p_cl_off2):
        top.wire("metal2", [pm["B"], (x_cl_vss, pm["B"][1])], 0.38)
    top.wire("metal2", [p_cl_r2["R2"], (p_cl_r2["R2"][0], +2.5), (x_cl_vss, +2.5)], 0.44)
    top.wire("metal2", [p_cl_r2["B"], (p_cl_r2["B"][0], +2.5)], 0.44)
    top.wire("metal2", [p_cl_r1["B"], (p_cl_r1["B"][0], +2.5), (p_cl_r2["B"][0], +2.5)], 0.42)

    # --- 5. HV PRE-REGULATOR NETS: pre_d, pre_g, va ---
    via2_clean(top, p_pre_d["gx"], p_pre_d["d_bus_y"])
    top.wire("metal3", [(p_pre_d["gx"], p_pre_d["g_ys"][0]), (p_pre_d["gx"], p_pre_d["d_bus_y"])], 0.52)
    x_pred_m3 = p_pre_d["d_xs"][-1]
    via2_clean(top, x_pred_m3, p_pre_d["d_bus_y"])
    top.wire("metal3", [(x_pred_m3, p_pre_d["d_bus_y"]), (x_pred_m3, p_pre_sink["D"][1])], 0.48)
    via2_clean(top, x_pred_m3, p_pre_sink["D"][1])
    top.wire("metal2", [(x_pred_m3, p_pre_sink["D"][1]), p_pre_sink["D"]], 0.44)
    y_pred_m2 = +47.3
    top.wire("metal2", [p_rpreoff["b"], (p_rpreoff["b"][0], y_pred_m2), (p_rpre["a"][0], y_pred_m2), p_rpre["a"]], 0.40)
    top.wire("metal2", [(p_rpre["a"][0], y_pred_m2), (212.4, y_pred_m2)], 0.40)
    via2_clean(top, 212.4, y_pred_m2)
    via2_clean(top, 212.8, p_pre_d["d_bus_y"])
    top.wire("metal3", [(212.4, y_pred_m2), (212.5, y_pred_m2), (212.5, +38.8), (212.8, +38.8), (212.8, p_pre_d["d_bus_y"])], 0.36)
    top.wire("metal2", [(212.8, p_pre_d["d_bus_y"]), p_pre_d["D"]], 0.48)

    y_preg_m2 = +46.2
    top.wire("metal2", [p_rpre["b"], (p_rpre["b"][0], y_preg_m2), (211.3, y_preg_m2)], 0.40)
    via2_clean(top, 211.3, y_preg_m2)
    top.wire("metal3", [(211.8, m_cpre["ya"]), (211.8, +41.2), (211.3, +41.2), (211.3, p_pre_p["g_ys"][0]), (p_pre_p["gx"], p_pre_p["g_ys"][0])], 0.36)
    via3_single(top, 211.8, m_cpre["ya"])
    top.wire("metal4", [m_cpre["a"], (211.8, m_cpre["ya"])], 0.56)

    x_va_m3 = 249.6
    for pm_va in (p_pre_p, p_pre_d, p_p2, p_pt):
        y_t = pm_va["d_bus_y"] if pm_va is p_pre_p else pm_va["s_bus_y"]
        via2_clean(top, x_va_m3, y_t)
        top.wire("metal2", [(pm_va["d_xs"][-1] if pm_va is p_pre_p else pm_va["s_xs"][-1], y_t), (x_va_m3, y_t)], 0.56)
    top.wire("metal2", [p_pd["S"], (x_va_m3, p_pd["S"][1])], 0.48)
    via2_clean(top, x_va_m3, p_pd["S"][1])
    for pq_l in (p_pl_a, p_pr_b):
        yd = pq_l["dum_l"][1]
        top.wire("metal2", [pq_l["dum_l"], (x_va_m3, yd)], 0.44)
        via2_clean(top, x_va_m3, yd)
    top.wire("metal3", [(x_va_m3, p_pd["S"][1]), (x_va_m3, p_pre_p["d_bus_y"])], 0.90)
    y_va_m4_pass = +25.4
    top.wire("metal4", [m_cva["a"], (178.34, m_cva["ya"]), (178.34, y_va_m4_pass), (180.5, y_va_m4_pass)], 0.40)
    top.wire("metal4", [(180.5, y_va_m4_pass), (x_va_m3, y_va_m4_pass)], 0.60)
    via3_array(top, x_va_m3, y_va_m4_pass, nx=2, ny=2)
    top.wire("metal3", [m_cbp["b"], (m_cbp["b"][0], -50.5)], 0.64)
    via3_single(top, m_cbp["b"][0], -50.5)
    top.wire("metal4", [(m_cbp["b"][0], -50.5), (x_va_m3, -50.5)], 0.64)
    via3_single(top, x_va_m3, -50.5)
    top.wire("metal3", [(x_va_m3, -50.5), (x_va_m3, p_pd["S"][1])], 0.64)

    # --- 6. CASCODE GATE: casg ---
    gx_cas = p_cas[0]["gx"]
    top.wire("metal3", [(gx_cas, p_cas[-1]["g_ys"][0]), (gx_cas, p_cas[0]["g_ys"][-1])], 0.56)
    y_casg_m4 = grid(m_ccas["ya"])
    top.wire("metal4", [(p_rcas["b"][0], y_casg_m4), (gx_cas, y_casg_m4)], 0.80)
    via3_array(top, gx_cas, y_casg_m4, nx=2, ny=2)
    top.wire("metal3", [(gx_cas, p_cas[0]["g_ys"][-1]), (gx_cas, y_casg_m4)], 0.56)
    top.wire("metal2", [p_rcas["b"], (p_rcas["b"][0], y_casg_m4)], 0.44)
    via2_clean(top, p_rcas["b"][0], y_casg_m4)
    via3_single(top, p_rcas["b"][0], y_casg_m4)

    # --- 7. REFERENCE PATH & SOUTH CONTROL BUSES ---
    y_trk_en   = -57.84
    y_trk_bg   = -58.36
    y_trk_host = -59.40
    y_trk_off  = -59.92
    y_trk_rloc = -60.44
    y_trk_gate = -60.96
    y_trk_x    = -61.48
    y_trk_ib   = -62.00  # Direct West current-mode input port i_ldo!

    def drop_to_m2_track(pt: tuple[float, float], y_trk: float, x_off: float = 0.0) -> float:
        x0 = grid(pt[0] + x_off)
        if abs(x_off) > 0.01:
            top.wire("metal2", [pt, (x0, pt[1])], 0.28)
        via2_clean(top, x0, pt[1])
        top.wire("metal3", [(x0, pt[1]), (x0, y_trk)], 0.34)
        via2_clean(top, x0, y_trk)
        return x0

    # bg
    drop_to_m2_track(p_tg_n["D"], y_trk_bg, x_off=+0.1)
    x_bg_r = drop_to_m2_track(p_tg_p["D"], y_trk_bg, x_off=+0.1)
    top.wire("metal2", [(-5.4, y_trk_bg), (x_bg_r, y_trk_bg)], 0.28)

    # ref_start
    for p_tg in (p_tg_n, p_tg_p):
        xs = grid(p_tg["S"][0] + 2.2)
        top.wire("metal2", [p_tg["S"], (xs, p_tg["S"][1]), (xs, -49.0)], 0.30)
    top.wire("metal2", [(grid(p_tg_n["S"][0] + 2.2), -49.0), (20.5, -49.0), (20.5, -46.0)], 0.38)
    top.via1(20.5, -46.0)
    top.wire("metal1", [(20.5, -46.0), (20.5, -43.0)], 0.38)
    top.via1(20.5, -43.0)
    top.wire("metal2", [(20.5, -43.0), (20.5, +43.5), (p_rref["a"][0], +43.5), p_rref["a"]], 0.38)

    # ref_local
    x_rloc_al = 69.0
    top.wire("metal4", [m_cref["a"], (x_rloc_al, m_cref["ya"])], 0.60)
    via3_single(top, x_rloc_al, m_cref["ya"])
    top.wire("metal2", [p_rref["b"], (p_rref["b"][0], +44.0), (x_rloc_al, +44.0)], 0.42)
    via2_clean(top, x_rloc_al, +44.0)
    top.wire("metal3", [(x_rloc_al, m_cref["ya"]), (x_rloc_al, y_trk_rloc)], 0.44)
    via2_clean(top, x_rloc_al, y_trk_rloc)
    x_rst_d = drop_to_m2_track(p_rst_n["D"], y_trk_rloc, x_off=+0.1)
    x_rloc_ea = 216.2
    top.wire("metal2", [(x_rst_d, y_trk_rloc), (x_rloc_ea, y_trk_rloc)], 0.28)
    via2_clean(top, x_rloc_ea, y_trk_rloc)
    top.wire("metal3", [(x_rloc_ea, y_trk_rloc), (x_rloc_ea, grid(p_pr_a["G"][1] + 1.10))], 0.40)
    for ppr, dy_r in ((p_pr_a, +1.10), (p_pr_b, +0.30)):
        yr = grid(ppr["G"][1] + dy_r)
        via2_clean(top, x_rloc_ea, yr)
        top.wire("metal2", [(x_rloc_ea, yr), (ppr["G"][0], yr), ppr["G"]], 0.34)

    # host (no p_copy -> terminates cleanly at p_inv_p["B"])
    drop_to_m2_track(p_tg_p["B"], y_trk_host, x_off=-1.0)
    x_h2 = drop_to_m2_track(p_inv_p["B"], y_trk_host, x_off=-1.0)
    top.wire("metal2", [(-5.4, y_trk_host), (x_h2, y_trk_host)], 0.28)

    # enable
    drop_to_m2_track(p_tg_n["G"], y_trk_en, x_off=+1.3)
    drop_to_m2_track(p_inv_n["G"], y_trk_en, x_off=+1.3)
    x_e3 = drop_to_m2_track(p_inv_p["G"], y_trk_en, x_off=+1.3)
    top.wire("metal2", [(-5.4, y_trk_en), (x_e3, y_trk_en)], 0.28)

    # off
    drop_to_m2_track(p_inv_n["D"], y_trk_off, x_off=+0.1)
    drop_to_m2_track(p_inv_p["D"], y_trk_off, x_off=+0.1)
    x_o3 = drop_to_m2_track(p_tg_p["G"], y_trk_off, x_off=+1.3)
    drop_to_m2_track(p_rst_n["G"], y_trk_off, x_off=+1.3)
    drop_to_m2_track(p_boff["G"], y_trk_off, x_off=-0.8)
    drop_to_m2_track(p_off["G"], y_trk_off, x_off=-0.8)
    x_cl_off_bus = 199.2
    top.wire("metal2", [(x_o3, y_trk_off), (x_cl_off_bus, y_trk_off), (x_cl_off_bus, -2.0)], 0.30)
    top.via1(x_cl_off_bus, -2.0)
    top.wire("metal1", [(x_cl_off_bus, -2.0), (x_cl_off_bus, p_cl_en["G"][1])], 0.36)
    for pcl_o in (p_cl_off2, p_cl_off, p_cl_en):
        top.via1(x_cl_off_bus, pcl_o["G"][1])
        top.wire("metal2", [pcl_o["G"], (x_cl_off_bus, pcl_o["G"][1])], 0.34)

    # i_ldo (= ibias): straight West perimeter port at (-5.4, y_trk_ib) -> Xboff.D, Xnb.D/G, Xnr.G, Xpre_sink.G!
    drop_to_m2_track(p_boff["D"], y_trk_ib, x_off=+1.5)
    drop_to_m2_track(p_nb["D"], y_trk_ib, x_off=+1.5)
    drop_to_m2_track(p_nb["G"], y_trk_ib, x_off=+2.8)
    for pt_ib in (p_nr["G"], p_pre_sink["G"]):
        drop_to_m2_track(pt_ib, y_trk_ib, x_off=0.0)
    top.wire("metal2", [(-5.4, y_trk_ib), (p_pre_sink["G"][0], y_trk_ib)], 0.30)

    # --- 8. ERROR AMPLIFIER INTERNAL NETS ---
    x_bp_m3 = 218.5
    top.wire("metal2", [p_nr["D"], (p_nr["D"][0], -45.3), (x_bp_m3, -45.3)], 0.38)
    via2_clean(top, x_bp_m3, -45.3)
    top.wire("metal3", [(x_bp_m3, -45.3), (x_bp_m3, p_p2["g_ys"][-1])], 0.44)
    for pt_bp in (p_pd["D"], p_pd["G"]):
        top.wire("metal2", [pt_bp, (x_bp_m3, pt_bp[1])], 0.38)
        via2_clean(top, x_bp_m3, pt_bp[1])
    top.wire("metal3", [(x_bp_m3, p_pt["g_ys"][0]), (p_pt["gx"], p_pt["g_ys"][0])], 0.44)
    top.wire("metal3", [(x_bp_m3, p_p2["g_ys"][0]), (p_p2["gx"], p_p2["g_ys"][0])], 0.44)
    via3_single(top, x_bp_m3, m_cbp["ya"])
    top.wire("metal4", [m_cbp["a"], (x_bp_m3, m_cbp["ya"])], 0.56)

    x_tail_m3 = x_ea
    for pq in (p_pl_a, p_pr_a, p_pr_b, p_pl_b):
        top.wire("metal2", [pq["S"], (x_tail_m3, pq["S"][1])], 0.44)
        via2_clean(top, x_tail_m3, pq["S"][1])
    via2_clean(top, x_tail_m3, p_pt["d_bus_y"])
    top.wire("metal3", [(x_tail_m3, p_pl_b["S"][1]), (x_tail_m3, p_pt["d_bus_y"])], 0.52)

    x_d_m3 = 221.5
    for pd_pt in (p_pl_a["D"], p_nl["D"], p_nl["G"], p_nm["G"]):
        top.wire("metal2", [pd_pt, (x_d_m3, pd_pt[1])], 0.38)
        via2_clean(top, x_d_m3, pd_pt[1])
    plb_r = (p_pl_b["d_xs"][-1], p_pl_b["D"][1])
    top.wire("metal2", [plb_r, (plb_r[0], -30.2), (x_d_m3, -30.2)], 0.38)
    via2_clean(top, x_d_m3, -30.2)
    top.wire("metal3", [(x_d_m3, p_nl["D"][1]), (x_d_m3, p_pl_a["D"][1])], 0.44)

    x_x_m3 = 236.5
    for px_pt in (p_pr_a["D"], p_nm["D"]):
        top.wire("metal2", [px_pt, (x_x_m3, px_pt[1])], 0.38)
        via2_clean(top, x_x_m3, px_pt[1])
    prb_r = (p_pr_b["d_xs"][-1], p_pr_b["D"][1])
    top.wire("metal2", [prb_r, (prb_r[0], -29.2), (x_x_m3, -29.2)], 0.38)
    via2_clean(top, x_x_m3, -29.2)
    top.wire("metal3", [(x_x_m3, y_trk_x), (x_x_m3, p_pr_a["D"][1])], 0.44)
    via2_clean(top, x_x_m3, y_trk_x)
    top.wire("metal1", [p_rzero["R1"], (209.2, p_rzero["R1"][1]), (209.2, -34.5), (211.4, -34.5)], 0.38)
    top.via1(211.4, -34.5)
    top.wire("metal2", [(211.4, -34.5), (x_x_m3, -34.5)], 0.38)
    via2_clean(top, x_x_m3, -34.5)
    x_n2g = drop_to_m2_track(p_n2["G"], y_trk_x, x_off=-1.2)
    top.wire("metal2", [(x_n2g, y_trk_x), (x_x_m3, y_trk_x)], 0.30)

    top.wire("metal2", [p_rzero["R2"], (208.5, p_rzero["R2"][1])], 0.40)
    via2_clean(top, 208.5, p_rzero["R2"][1])
    top.wire("metal3", [(208.5, p_rzero["R2"][1]), (208.5, m_cc["ya"])], 0.44)
    via3_single(top, 208.5, m_cc["ya"])
    top.wire("metal4", [m_cc["a"], (208.5, m_cc["ya"])], 0.56)

    gx_pass = p_pass[0]["gx"]
    x_gpass_m2 = 286.2
    top.wire("metal2", [(x_gpass_m2, -52.2), (x_gpass_m2, p_pass[0]["g_ys"][-1])], 0.48)
    for pp in p_pass:
        for gy in pp["g_ys"]:
            top.via1(x_gpass_m2, gy)
            top.wire("metal1", [(x_gpass_m2, gy), (gx_pass, gy)], 0.24)
    x_gt_m3 = 211.9
    top.wire("metal2", [p_p2["D"], (x_gt_m3, p_p2["d_bus_y"])], 0.48)
    via2_clean(top, x_gt_m3, p_p2["d_bus_y"])
    top.wire("metal4", [m_cc["b"], (x_gt_m3, m_cc["b"][1])], 0.56)
    via3_single(top, x_gt_m3, m_cc["b"][1])
    via3_single(top, x_gt_m3, m_cghf["ya"])
    top.wire("metal4", [m_cghf["a"], (x_gt_m3, m_cghf["ya"])], 0.56)
    x_offd = drop_to_m2_track(p_off["D"], y_trk_gate, x_off=+0.5)
    drop_to_m2_track(p_n2["D"],  y_trk_gate, x_off=+1.0)
    top.wire("metal2", [(x_offd, y_trk_gate), (x_gt_m3, y_trk_gate)], 0.34)
    via2_clean(top, x_gt_m3, y_trk_gate)
    top.wire("metal3", [(x_gt_m3, y_trk_gate), (x_gt_m3, p_p2["d_bus_y"])], 0.46)
    y_gt_br = -52.2
    x_gt_step = 253.8
    via3_array(top, x_gt_m3, y_gt_br, nx=1, ny=2)
    top.wire("metal4", [(x_gt_m3, y_gt_br), (x_gt_step, y_gt_br)], 0.64)
    via3_single(top, x_gt_step, y_gt_br)
    via2_clean(top, x_gt_step, y_gt_br)
    top.wire("metal2", [(x_gt_step, y_gt_br), (x_gpass_m2, y_gt_br)], 0.56)

    # --- 9. FEEDBACK DIVIDER, TRIM SWITCHES, CFF & LOOP-BREAK PORTS ---
    top.wire("metal2", [p_rdiv_top["n5"], (p_rdiv_top["n5"][0], -23.8), (p_rdiv_bot["n5"][0], -23.8), p_rdiv_bot["n5"]], 0.42)
    for k in range(5):
        xm = grid((p_sws[k]["D_right"][0] + p_sws[k + 1]["S"][0]) / 2.0)
        top.wire("metal2", [p_sws[k]["D_right"], (xm, p_sws[k]["D_right"][1]), (xm, p_sws[k + 1]["S"][1]), p_sws[k + 1]["S"]], 0.32)
    for k in range(6):
        tap_pt = p_rdiv_bot[f"n{k}"]
        sw_d = p_sws[k]["D_right"]
        yk = grid(-46.0 - k * 0.56)
        top.wire("metal2", [tap_pt, (tap_pt[0], yk), (sw_d[0], yk), sw_d], 0.28)

    y_trim_port = -64.5
    x_fbret_p = 180.4
    top.wire("metal4", [m_cff["a"], (100.5, m_cff["ya"]), (100.5, -47.8), (x_fbret_p, -47.8)], 0.50)
    via3_single(top, x_fbret_p, -47.8)
    via2_clean(top, x_fbret_p, -47.8)
    top.wire("metal2", [p_rdiv_top["fb_return"], (x_fbret_p, p_rdiv_top["fb_return"][1]), (x_fbret_p, -47.8)], 0.42)
    top.wire("metal3", [(x_fbret_p, -47.8), (x_fbret_p, y_trim_port)], 0.44)

    x_fbin_p = 213.0
    top.wire("metal3", [(x_fbin_p, y_trim_port), (x_fbin_p, grid(p_pl_a["G"][1] + 0.60))], 0.40)
    for ppl, dy_f in ((p_pl_a, +0.60), (p_pl_b, +1.10)):
        yf = grid(ppl["G"][1] + dy_f)
        via2_clean(top, x_fbin_p, yf)
        top.wire("metal2", [(x_fbin_p, yf), (ppl["G"][0], yf), ppl["G"]], 0.34)

    if not is_probe:
        top.wire("metal3", [(x_fbret_p, y_trim_port), (x_fbin_p, y_trim_port)], 0.48)

    # --- 10. ACTIVE OVERSHOOT CLAMP ---
    top.wire("metal2", [p_cl_en["D"], (192.2, p_cl_en["D"][1]), (192.2, +30.0), (p_rcl_arr["a"][0], +30.0), p_rcl_arr["a"]], 0.36)
    top.wire("metal2", [p_cl_nref["D"], (p_cl_nref["D"][0], p_cl_nref["G"][1]), p_cl_nref["G"]], 0.34)
    top.wire("metal2", [p_rcl_arr["mid"], (128.5, p_rcl_arr["mid"][1]), (128.5, +32.0)], 0.36)
    top.via1(128.5, +32.0)
    top.wire("metal1", [(128.5, +32.0), (128.5, +14.0)], 0.36)
    top.via1(128.5, +14.0)
    top.wire("metal2", [(128.5, +14.0), (128.5, p_cl_nref["D"][1]), p_cl_nref["D"]], 0.36)
    top.wire("metal2", [p_rcl_arr["b"], (130.5, p_rcl_arr["b"][1]), (130.5, +4.5)], 0.36)
    top.via1(130.5, +4.5)
    top.wire("metal1", [(130.5, +4.5), (130.5, +8.5)], 0.36)
    top.via1(130.5, +8.5)
    top.wire("metal2", [(130.5, +8.5), (130.5, p_cl_n1["G"][1]), p_cl_n1["G"], (192.2, p_cl_n1["G"][1]), (192.2, p_cl_off["D"][1]), p_cl_off["D"]], 0.36)
    x_chpa_m3 = 215.2
    top.wire("metal4", [m_chp["a"], (x_chpa_m3, m_chp["ya"])], 0.50)
    via3_single(top, x_chpa_m3, m_chp["ya"])
    top.wire("metal3", [(x_chpa_m3, m_chp["ya"]), (x_chpa_m3, p_cl_off["D"][1]), (208.0, p_cl_off["D"][1])], 0.42)
    via2_clean(top, 208.0, p_cl_off["D"][1])
    top.wire("metal2", [(208.0, p_cl_off["D"][1]), p_cl_off["D"]], 0.36)
    top.wire("metal2", [p_cl_r1["R2"], (152.8, p_cl_r1["R2"][1])], 0.40)
    top.via1(152.8, p_cl_r1["R2"][1])
    top.wire("metal1", [(152.8, p_cl_r1["R2"][1]), (152.8, +20.0)], 0.40)
    top.via1(152.8, +20.0)
    top.wire("metal2", [(152.8, +20.0), (174.0, +20.0), (174.0, p_cl_p2["G"][1]), p_cl_p2["G"]], 0.56)
    top.wire("metal2", [p_cl_n1["D"], (174.0, p_cl_n1["D"][1])], 0.56)
    for dx_v in (-0.22, +0.22):
        top.via1(grid(174.0 + dx_v), p_cl_n1["D"][1])
        top.via1(grid(174.0 + dx_v), +20.0)
    top.wire("metal1", [(174.0, p_cl_n1["D"][1]), (174.0, +20.0)], 0.72)
    top.wire("metal2", [p_cl_r2["R1"], (p_cl_r2["R1"][0], +28.5)], 0.40)
    top.via1(p_cl_r2["R1"][0], +28.5)
    top.wire("metal1", [(p_cl_r2["R1"][0], +28.5), (p_cl_r2["R1"][0], +31.5)], 0.40)
    top.via1(p_cl_r2["R1"][0], +31.5)
    top.wire("metal2", [(p_cl_r2["R1"][0], +31.5), (191.0, +31.5)], 0.56)
    top.wire("metal2", [p_cl_p2["D_right"], (187.5, p_cl_p2["D_right"][1]), (187.5, +28.5)], 0.64)
    for dx_v in (-0.22, +0.22):
        top.via1(grid(187.5 + dx_v), +28.5)
        top.via1(grid(187.5 + dx_v), +31.5)
    top.wire("metal1", [(187.5, +28.5), (187.5, +31.5)], 0.76)
    top.wire("metal2", [(175.0, +31.5), (175.0, p_clamp["G"][1]), p_clamp["G"]], 0.64)
    top.wire("metal2", [p_cl_off2["D"], (191.0, p_cl_off2["D"][1])], 0.36)
    top.via1(191.0, p_cl_off2["D"][1])
    top.wire("metal1", [(191.0, p_cl_off2["D"][1]), (191.0, +31.5)], 0.36)
    top.via1(191.0, +31.5)

    # --- 11. TRIM BIT PERIMETER ROUTING ---
    for k in range(6):
        gx, gy = p_sws[k]["G"]
        via2_clean(top, gx, gy)
        top.wire("metal3", [(gx, gy), (gx, y_trim_port)], 0.40)

    # EXPORT ALL 13 PRODUCTION (OR 15 PROBE) PORTS
    top.port("vin",    "metal5", 266.0, +55.7)
    top.port("host",   "metal2", -5.4,  y_trk_host)
    top.port("quiet",  "metal5", 305.0, 0.0)
    top.port("bg",     "metal2", -5.4,  y_trk_bg)
    top.port("i_ldo",  "metal2", -5.4,  y_trk_ib)
    top.port("enable", "metal2", -5.4,  y_trk_en)
    for k in range(6):
        top.port(f"t{k}", "metal3", p_sws[k]["G"][0], y_trim_port)
    if is_probe:
        top.port("fb_return", "metal3", x_fbret_p, y_trim_port)
        top.port("fb_input",  "metal3", x_fbin_p,  y_trim_port)
    top.port("vss",    "metal4", 304.5, y_vss_south)

    mag = work / f"{cell}.mag"
    top.write(mag)
    ref = make_reference_spice_cur(work / f"{cell}_ref.spice", cell, is_probe=is_probe)
    rec = v2.run_drc_lvs_pex_rcx(work, cell, ref, extract_rcx=extract_rcx)
    rec["floating_poly"] = count_floating_poly(top)
    rec["is_probe"] = is_probe
    rec["expected_ports"] = PROBE_PORTS if is_probe else PROD_PORTS
    rec["ports_exact_match"] = rec["exported_ports"] == rec["expected_ports"]

    title = f"{cell} | DRC={rec['drc_total']}, LVS={'MATCH' if rec['lvs_match'] else 'FAIL'}"
    render_png_cur(mag, work / f"{cell}.png", title)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--install-dir", type=Path, default=None)
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--no-rcx", action="store_true")
    args = ap.parse_args()

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    records = []
    rec_probe = build_supply_v2_cur(out, is_probe=True, extract_rcx=not args.no_rcx)
    records.append(rec_probe)
    print(json.dumps({k: v for k, v in rec_probe.items() if k != "parasitics"}, indent=2), flush=True)

    if not args.probe_only:
        rec_prod = build_supply_v2_cur(out, is_probe=False, extract_rcx=not args.no_rcx)
        records.append(rec_prod)
        print(json.dumps({k: v for k, v in rec_prod.items() if k != "parasitics"}, indent=2), flush=True)

    summary = {
        "architecture": "LDO v2 Current-Mode Bias Input (i_ldo -> local 1:1 Xnb/Xnr 30/2 NMOS mirror, BIAS v2 i_ldo0 compatible)",
        "bias_interface": "Direct 10 uA current-mode input i_ldo from serdes_bias_top_v2_pdk.i_ldo0 (vgi removed, redundant v1 Xcopy removed)",
        "total_mim_pf": 60.0,
        "macros": records,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    if args.install_dir:
        inst = args.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "summary.json", inst / "summary.json")
        for r in records:
            cname = r["cell"]
            cdir = out / cname
            for ext in (".mag", ".png", "_ref.spice", "_lvs.spice", "_pex.spice", "_rcx.spice"):
                src = cdir / f"{cname}{ext}"
                if src.exists():
                    shutil.copy2(src, inst / src.name)


if __name__ == "__main__":
    main()
