#!/usr/bin/env python3
"""Render hierarchical SKY130A full-chip silicon layout (`serdes_4g_top_pdk.mag`) to high-res PNG.

Expands all 20 real signed-off analog `.mag` subcells (with exact Magic transforms),
renders the `serdes_digital_top_v3` standard-cell macro footprint, all 224 damped
MIM1+MIM2 decap tiles, P+ isolation guard moats, segmented M5 perimeter power rings,
and all top-level inter-macro M2/M3/M4/M5 routing onto a dark silicon die canvas.
"""
from __future__ import annotations

import argparse
from dataclasses import replace as dc_replace
import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import plan_chip_floorplan as pcf  # noqa: E402

U = 200.0

# High-contrast EDA dark-substrate and publication light-paper palettes
LAYER_STYLES = {
    "dark": {
        "nwell":      ("#243044", 0.35, 1),
        "psubdiff":   ("#2e7d32", 0.60, 2),
        "mvpsubdiff": ("#2e7d32", 0.60, 2),
        "nsubdiff":   ("#15803d", 0.55, 2),
        "mvnsubdiff": ("#15803d", 0.55, 2),
        "pdiff":      ("#b45309", 0.58, 3),
        "ndiff":      ("#1d4ed8", 0.58, 3),
        "mvpdiff":    ("#d97706", 0.68, 3),
        "mvndiff":    ("#2563eb", 0.68, 3),
        "nbase":      ("#f59e0b", 0.72, 3),
        "nmos":       ("#60a5fa", 0.78, 4),
        "pmos":       ("#fb923c", 0.78, 4),
        "scnmos":     ("#60a5fa", 0.78, 4),
        "scpmoshvt":  ("#fb923c", 0.78, 4),
        "nmoslvt":    ("#22d3ee", 0.88, 4),
        "pmoslvt":    ("#e879f9", 0.88, 4),
        "mvnmos":     ("#818cf8", 0.85, 4),
        "mvnnmos":    ("#818cf8", 0.85, 4),
        "mvpmos":     ("#fbbf24", 0.85, 4),
        "varactor":   ("#a3e635", 0.88, 4),
        "poly":       ("#dc2626", 0.65, 5),
        "ppolyres":   ("#c026d3", 0.75, 5),
        "xpolyres":   ("#c026d3", 0.75, 5),
        "locali":     ("#7c3aed", 0.42, 6),
        "metal1":     ("#3b82f6", 0.58, 7),
        "metal2":     ("#14b8a6", 0.72, 8),
        "metal3":     ("#f97316", 0.78, 9),
        "mimcap":     ("#facc15", 0.42, 10),
        "metal4":     ("#38bdf8", 0.84, 11),
        "mimcap2":    ("#34d399", 0.45, 12),
        "metal5":     ("#f43f5e", 0.90, 13),
    },
    "light": {
        "nwell":      ("#dbeafe", 0.42, 1),
        "psubdiff":   ("#16a34a", 0.62, 2),
        "mvpsubdiff": ("#16a34a", 0.62, 2),
        "nsubdiff":   ("#15803d", 0.55, 2),
        "mvnsubdiff": ("#15803d", 0.55, 2),
        "pdiff":      ("#d97706", 0.55, 3),
        "ndiff":      ("#2563eb", 0.55, 3),
        "mvpdiff":    ("#b45309", 0.68, 3),
        "mvndiff":    ("#1d4ed8", 0.68, 3),
        "nbase":      ("#ca8a04", 0.72, 3),
        "nmos":       ("#1d4ed8", 0.78, 4),
        "pmos":       ("#c2410c", 0.78, 4),
        "scnmos":     ("#1d4ed8", 0.78, 4),
        "scpmoshvt":  ("#c2410c", 0.78, 4),
        "nmoslvt":    ("#0891b2", 0.90, 4),
        "pmoslvt":    ("#c026d3", 0.90, 4),
        "mvnmos":     ("#4338ca", 0.85, 4),
        "mvnnmos":    ("#4338ca", 0.85, 4),
        "mvpmos":     ("#a16207", 0.85, 4),
        "varactor":   ("#65a30d", 0.88, 4),
        "poly":       ("#dc2626", 0.60, 5),
        "ppolyres":   ("#a21caf", 0.78, 5),
        "xpolyres":   ("#a21caf", 0.78, 5),
        "locali":     ("#7c3aed", 0.38, 6),
        "metal1":     ("#2563eb", 0.52, 7),
        "metal2":     ("#0d9488", 0.76, 8),
        "metal3":     ("#ea580c", 0.82, 9),
        "mimcap":     ("#eab308", 0.45, 10),
        "metal4":     ("#0284c7", 0.86, 11),
        "mimcap2":    ("#10b981", 0.44, 12),
        "metal5":     ("#be123c", 0.90, 13),
    },
}

THEME_CHROME = {
    "dark": {
        "fig_bg": "#0b101b",
        "ax_bg": "#0f172a",
        "die_bg": "#111827",
        "die_ec": "#475569",
        "dig_bg": "#172554",
        "dig_ec": "#60a5fa",
        "dig_row": "#1e3a8a",
        "dig_pg": "#38bdf8",
        "macro_ec": "#e2e8f0",
        "dig_macro_ec": "#93c5fd",
        "lbl_fg": "#f8fafc",
        "lbl_bg": "#0f172a",
        "lbl_ec": "#475569",
        "ann_bg": "#0b101b",
        "pwr_col": "#fb7185",
        "hs_col": "#38bdf8",
        "moat_col": "#4ade80",
        "decap_col": "#facc15",
        "title_fg": "#f8fafc",
        "axis_fg": "#cbd5e1",
        "tick_fg": "#94a3b8",
        "spine_ec": "#334155",
        "leg_ec": "#e2e8f0",
        "leg_fg": "#e2e8f0",
    },
    "light": {
        "fig_bg": "#ffffff",
        "ax_bg": "#f8fafc",
        "die_bg": "#ffffff",
        "die_ec": "#64748b",
        "dig_bg": "#eff6ff",
        "dig_ec": "#1d4ed8",
        "dig_row": "#bfdbfe",
        "dig_pg": "#0284c7",
        "macro_ec": "#0f172a",
        "dig_macro_ec": "#1d4ed8",
        "lbl_fg": "#0f172a",
        "lbl_bg": "#ffffff",
        "lbl_ec": "#64748b",
        "ann_bg": "#ffffff",
        "pwr_col": "#be123c",
        "hs_col": "#0369a1",
        "moat_col": "#15803d",
        "decap_col": "#b45309",
        "title_fg": "#0f172a",
        "axis_fg": "#1e293b",
        "tick_fg": "#334155",
        "spine_ec": "#94a3b8",
        "leg_ec": "#334155",
        "leg_fg": "#0f172a",
    },
}

LAYER_STYLE = LAYER_STYLES["dark"]


def parse_mag_rects(path: Path) -> dict[str, list[tuple[float, float, float, float]]]:
    layer = None
    out: dict[str, list[tuple[float, float, float, float]]] = {}
    for line in path.read_text(errors="ignore").splitlines():
        m = re.match(r"^<< (\S+) >>$", line)
        if m:
            lyr = m.group(1)
            layer = lyr if lyr in LAYER_STYLE else None
            continue
        if layer and line.startswith("rect "):
            parts = line.split()
            if len(parts) == 5:
                x1, y1, x2, y2 = (int(v) / U for v in parts[1:])
                if (x2 - x1) >= 0.25 or (y2 - y1) >= 0.25:
                    out.setdefault(layer, []).append((x1, y1, x2, y2))
    return out


def parse_top_uses(path: Path) -> list[dict]:
    uses = []
    cur = None
    for line in path.read_text(errors="ignore").splitlines():
        if line.startswith("use "):
            parts = line.split()
            cur = {"cell": parts[1], "inst": parts[2] if len(parts) > 2 else parts[1], "array": None, "tf": (1, 0, 0, 0, 1, 0)}
            uses.append(cur)
        elif cur is not None:
            if line.startswith("array "):
                p = list(map(int, line.split()[1:]))
                cur["array"] = (p[0], p[1], p[2] / U, p[3], p[4], p[5] / U)
            elif line.startswith("transform "):
                p = list(map(int, line.split()[1:]))
                cur["tf"] = (p[0], p[1], p[2] / U, p[3], p[4], p[5] / U)
            elif line.startswith("<< "):
                cur = None
    return uses


def apply_tf(tf, x1: float, y1: float, x2: float, y2: float) -> tuple[float, float, float, float]:
    a, b, c, d, e, f = tf
    xs = (a * x1 + b * y1 + c, a * x2 + b * y1 + c, a * x1 + b * y2 + c, a * x2 + b * y2 + c)
    ys = (d * x1 + e * y1 + f, d * x2 + e * y1 + f, d * x1 + e * y2 + f, d * x2 + e * y2 + f)
    return min(xs), min(ys), max(xs), max(ys)


def render_chip_top(work_dir: Path, out_png: Path, theme: str = "dark") -> None:
    layer_style = LAYER_STYLES[theme]
    ch = THEME_CHROME[theme]
    top_mag = work_dir / "serdes_4g_top_pdk.mag"
    summary_json = work_dir / "summary.json"
    summary = json.loads(summary_json.read_text()) if summary_json.exists() else {}

    inv = pcf.load_inventory()
    lpf_rel = "analog/ldo/layout/variants/bias_filter_stacked_pdk/serdes_pll_bias_lowpass_stacked_pdk.mag"
    v32_def = "digital/pnr/variants/hd_pnr_v3p2_cmos_rx/serdes_digital_top_v3/serdes_digital_top_v3.def"
    v32_sum = "digital/pnr/variants/hd_pnr_v3p2_cmos_rx/serdes_digital_top_v3/summary.json"
    has_stacked_lpf = (work_dir / "serdes_pll_bias_lowpass_stacked_pdk.mag").exists() and (REPO / lpf_rel).exists()
    if has_stacked_lpf:
        inv["bias_lpf_slow"] = pcf.parse_mag("bias_lpf_slow", lpf_rel, "serdes_pll_bias_lowpass_stacked_pdk", internal_cap_pf=16.0)
    saff_v2_rel = "analog/pll/divider/layout/variants/saff_reclock_2g_v2_pdk/pll_saff_reclock_prescaler8_2g_v2_cand_pdk.mag"
    has_saff_v2 = (work_dir / "pll_saff_reclock_prescaler8_2g_v2_cand_pdk.mag").exists() and (REPO / saff_v2_rel).exists()
    if has_saff_v2:
        inv["div8_saff"] = pcf.parse_mag("div8_saff", saff_v2_rel, "pll_saff_reclock_prescaler8_2g_v2_cand_pdk")
    has_v32 = (REPO / v32_def).exists() and (REPO / v32_sum).exists() and summary.get("routed_top_nets", 0) >= 100
    if has_v32:
        inv["digital_top_v3"] = pcf.parse_digital_def("digital_top_v3", v32_def, v32_sum)
    macros, decaps, _ = pcf.build_floorplan(inv)
    if not (work_dir / "serdes_bias_ctle_v2_pdk.mag").exists():
        macros = [m for m in macros if m.inst != "bias_ctle_v2"]
    for m in macros:
        if m.inst == "bias_lpf_slow" and has_stacked_lpf:
            m.orient = "R90"
            m.x, m.y = 194.0, 280.0
        elif m.inst == "digital_top_v3" and has_v32:
            m.x = round(845.1 - m.w, 2)
            m.y = round(601.4 - m.h, 2)
    uses = parse_top_uses(top_mag)
    insts_in_top = {u["inst"] for u in uses}
    macros = [m for m in macros if m.inst in insts_in_top]
    kpi_by_inst = {
        km["inst"]: km for km in summary.get("floorplan_kpi", {}).get("macros", [])
        if isinstance(km, dict) and "inst" in km
    }
    for m in macros:
        km = kpi_by_inst.get(m.inst)
        if km and "placed_rect_um" in km:
            x1, y1, x2, y2 = km["placed_rect_um"]
            m.x, m.y = float(x1), float(y1)
            m.raw = dc_replace(m.raw, width_um=float(x2 - x1), height_um=float(y2 - y1))
            m.orient = "R0"
    has_tx_v44 = "v4p4_pdk" in str(kpi_by_inst.get("tx_sst_top", {}).get("source", ""))
    has_rx_v23 = "v2p3_pdk" in str(kpi_by_inst.get("rx_cmos_top", {}).get("source", ""))
    has_bias_ptat = "v2_ptat_pdk" in str(kpi_by_inst.get("bias_top_v2", {}).get("source", ""))

    # Collect geometry by layer across top + all analog subcells + decap arrays
    by_layer: dict[str, list[Rectangle]] = {k: [] for k in layer_style}
    top_rects = parse_mag_rects(top_mag)
    for lyr, rlist in top_rects.items():
        for x1, y1, x2, y2 in rlist:
            by_layer[lyr].append(Rectangle((x1, y1), x2 - x1, y2 - y1))

    # Cache parsed subcell rects
    sub_cache: dict[str, dict[str, list[tuple[float, float, float, float]]]] = {}
    for uinfo in uses:
        cname = uinfo["cell"]
        if cname == "serdes_digital_top_v3":
            continue
        if cname not in sub_cache:
            mpath = work_dir / f"{cname}.mag"
            sub_cache[cname] = parse_mag_rects(mpath) if mpath.exists() else {}
        srects = sub_cache[cname]
        tf = uinfo["tf"]
        arr = uinfo["array"]
        if arr is None:
            for lyr, rlist in srects.items():
                for x1, y1, x2, y2 in rlist:
                    tx1, ty1, tx2, ty2 = apply_tf(tf, x1, y1, x2, y2)
                    by_layer[lyr].append(Rectangle((tx1, ty1), tx2 - tx1, ty2 - ty1))
        else:
            xlo, xhi, xsep, ylo, yhi, ysep = arr
            for ix in range(xlo, xhi + 1):
                for iy in range(ylo, yhi + 1):
                    dx, dy = ix * xsep, iy * ysep
                    for lyr in ("ndiff", "mvndiff", "nmos", "mvnmos", "poly", "mimcap", "mimcap2", "metal5", "metal4", "metal3", "metal2", "ppolyres"):
                        for x1, y1, x2, y2 in srects.get(lyr, ()):
                            tx1, ty1, tx2, ty2 = apply_tf(tf, x1, y1, x2, y2)
                            by_layer[lyr].append(Rectangle((tx1 + dx, ty1 + dy), tx2 - tx1, ty2 - ty1))

    fig, ax = plt.subplots(figsize=(15.5, 11.2), dpi=260)
    fig.patch.set_facecolor(ch["fig_bg"])
    ax.set_facecolor(ch["ax_bg"])

    # Core die boundary
    ax.add_patch(Rectangle((0, 0), 845.4, 601.4, facecolor=ch["die_bg"], edgecolor=ch["die_ec"], linewidth=1.2, linestyle="--", zorder=0))

    # Digital macro rendered with structured std-cell row stripes + M4/M5 power mesh texture
    dig = next(m for m in macros if m.inst == "digital_top_v3")
    ax.add_patch(Rectangle((dig.x, dig.y), dig.w, dig.h, facecolor=ch["dig_bg"], edgecolor=ch["dig_ec"], linewidth=1.1, zorder=2))
    row_patches = [Rectangle((dig.x + 2, dig.y + 4 + i * 5.44), dig.w - 4, 2.2) for i in range(int((dig.h - 8) // 5.44))]
    ax.add_collection(PatchCollection(row_patches, facecolor=ch["dig_row"], edgecolor="none", alpha=0.60, zorder=3))
    pg_patches = [Rectangle((dig.x + 12 + i * 28.0, dig.y + 2), 1.8, dig.h - 4) for i in range(int((dig.w - 20) // 28.0))]
    ax.add_collection(PatchCollection(pg_patches, facecolor=ch["dig_pg"], edgecolor="none", alpha=0.25, zorder=4))

    # Draw all physical layers in Z-order using PatchCollection for speed
    for lyr, (color, alpha, z) in sorted(layer_style.items(), key=lambda kv: kv[1][2]):
        patches = by_layer.get(lyr, [])
        if not patches:
            continue
        ax.add_collection(PatchCollection(patches, facecolor=color, edgecolor="none", alpha=alpha, zorder=z))

    # Crisp macro outlines + compact readable labels
    m_by_inst = {m.inst: m for m in macros}
    tx_m = m_by_inst.get("tx_sst_top")
    rx_m = m_by_inst.get("rx_cmos_top")
    bias_m = m_by_inst.get("bias_top_v2")
    short_labels = {
        "ldo_v2_cur": "HV18 LDO v2_cur\n312×121 µm",
        "bias_top_v2": (
            f"BIAS v2_ptat\n{bias_m.w:.0f}×{bias_m.h:.0f} µm"
            if (has_bias_ptat and bias_m) else "BIAS v2\n176×152 µm"
        ),
        "vco_ptat_bias": "PTAT 28/66",
        "bias_lpf_slow": "Stacked Bias LPF\n106×59 µm (-40%)" if has_stacked_lpf else "Bias LPF",
        "bias_cml_vco": "CML\nBias",
        "pfd_sc_dly": "PFD",
        "bias_cp_v2": "CPb",
        "cp_v4": "CP v4.1",
        "lf_k4_fused": "Fused LF\n98×65 µm",
        "vco_r6_sym9": "2 GHz Ring VCO r6\n109×80 µm",
        "cml2cmos_0": "C2C 0",
        "cml2cmos_1": "C2C 1",
        "cml2cmos_2": "C2C 2",
        "cml2cmos_3": "C2C 3",
        "bias_cml_host": "Host\nBias",
        "div8_saff": "SAFF-TSPC ÷8 v2" if has_saff_v2 else "SAFF-TSPC ÷8",
        "tx_qdiv2": "TX 8-Ph QDiv2",
        "tx_sst_top": (
            f"TX CMOS+SST v4.4\n{tx_m.w:.0f}×{tx_m.h:.0f} µm (4 Gb/s)"
            if (has_tx_v44 and tx_m) else "TX CMOS+SST v4.3\n151×233 µm (4 Gb/s)"
        ),
        "rx_cmos_top": (
            f"RX CTLE+PI+Smp v2.3\n{rx_m.w:.0f}×{rx_m.h:.0f} µm (4 Gb/s)"
            if (has_rx_v23 and rx_m) else "RX CTLE+PI+Smp v2.2\n195×245 µm (4 Gb/s)"
        ),
        "digital_top_v3": (
            f"Unified Digital Top v3.2\n{dig.w:.0f}×{dig.h:.0f} µm · Direct CMOS RX\nCDR · PRBS · Cal · Telemetry"
            if has_v32
            else "Unified Digital Top v3.1\n338×307 µm · 4,932 std cells\nCDR · PRBS · Cal · Telemetry"
        ),
    }
    for m in macros:
        ec = ch["dig_macro_ec"] if m.inst == "digital_top_v3" else ch["macro_ec"]
        ax.add_patch(Rectangle((m.x, m.y), m.w, m.h, facecolor="none", edgecolor=ec, linewidth=0.95, alpha=0.90, zorder=20))
        lbl = short_labels.get(m.inst)
        if lbl:
            fs = 9.0 if m.w * m.h > 25000 else (7.2 if m.w * m.h > 4500 else 5.8)
            ax.text(
                m.x + 0.5 * m.w, m.y + 0.5 * m.h, lbl,
                color=ch["lbl_fg"], fontsize=fs, fontweight="bold", ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.22", facecolor=ch["lbl_bg"], edgecolor=ch["lbl_ec"], alpha=0.86, lw=0.6),
                zorder=25,
            )

    n_decap = summary.get("decap_tiles_total", 0)
    is_v8 = bool(summary.get("v8_power_decap"))
    decap_lbl = f"Hybrid MIM+MOS\nDecap ({n_decap}x)" if is_v8 else f"Damped MIM\nDecap ({n_decap}x)"
    decap_title = f"{n_decap} Hybrid MIM+MOS Decap Tiles" if is_v8 else f"{n_decap} Damped MIM Decap Tiles"
    is_v4_pdn = any(x1 < -25.0 for x1, _, _, _ in top_rects.get("metal5", ()))
    # Annotate key top-level rails & South HS pad exits
    if is_v4_pdn:
        annots = [
            (-33, 520, "VDD_HV33\n14 µm", ch["pwr_col"]),
            (-33, 315, "VDD_BIAS\n6 µm", ch["pwr_col"]),
            (-33, 105, "VDD_Q\n12 µm", ch["pwr_col"]),
            (334, 308, "VDD_Q\n14µm Direct", ch["pwr_col"]),
            (420, 642, "VDD_A (12 µm)", ch["pwr_col"]),
            (680, 642, "VDD_D (10 µm)", ch["pwr_col"]),
            (906, 140, "VDD_RX\n12 µm", ch["pwr_col"]),
            (431, -34, "VDD_TX (12 µm)", ch["pwr_col"]),
            (473, -58, "TX_PAD_P/N", ch["hs_col"]),
            (668, -58, "RX_IN_N/P", ch["hs_col"]),
            (355, 520, "P+ Quiet\nMoat", ch["moat_col"]),
            (622, 108, decap_lbl, ch["decap_col"]),
        ]
    else:
        annots = [
            (-18, 520, "VDD_HV33", ch["pwr_col"]),
            (-18, 315, "VDD_BIAS", ch["pwr_col"]),
            (-18, 105, "VDD_Q", ch["pwr_col"]),
            (420, 626, "VDD_A", ch["pwr_col"]),
            (680, 626, "VDD_D", ch["pwr_col"]),
            (892, 140, "VDD_RX", ch["pwr_col"]),
            (431, -24, "VDD_TX", ch["pwr_col"]),
            (473, -38, "TX_PAD_P/N", ch["hs_col"]),
            (668, -38, "RX_IN_N/P", ch["hs_col"]),
            (355, 520, "P+ Quiet\nMoat", ch["moat_col"]),
            (622, 108, decap_lbl, ch["decap_col"]),
        ]
    for x, y, txt, col in annots:
        ax.text(x, y, txt, color=col, fontsize=7.5, fontweight="bold", ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.15", facecolor=ch["ann_bg"], edgecolor=col, alpha=0.90, lw=0.65), zorder=30)

    # Legend strip
    legend_items = [
        ("M5 Power & Bridges", layer_style["metal5"][0]),
        ("M4 Clocks & Data", layer_style["metal4"][0]),
        ("M3 Inter-Macro Signal", layer_style["metal3"][0]),
        ("M2 Local / Digital Pins", layer_style["metal2"][0]),
        ("LVT NMOS (nmoslvt)", layer_style["nmoslvt"][0]),
        ("LVT PMOS (pmoslvt)", layer_style["pmoslvt"][0]),
        ("HV 5V FET (mv*)", layer_style["mvnmos"][0]),
        ("Stacked MIM1+MIM2", layer_style["mimcap"][0]),
        ("P+ Isolation Moat", layer_style["psubdiff"][0]),
    ]
    handles = [Rectangle((0, 0), 1, 1, facecolor=c, edgecolor=ch["leg_ec"], lw=0.4) for _, c in legend_items]
    ax.legend(handles, [n for n, _ in legend_items], loc="upper left", bbox_to_anchor=(0.0, -0.045),
              ncol=5, frameon=False, fontsize=8.3, labelcolor=ch["leg_fg"])

    drc_val = summary.get("top_drc_total")
    drc_str = f"Magic DRC = {drc_val}" if drc_val is not None else "Pre-DRC Connectivity Audit"
    gds_bytes = summary.get("gds_bytes") or 0
    gds_str = f" · Merged GDSII {gds_bytes / 1048576.0:.2f} MB" if gds_bytes > 0 else ""
    n_nets = summary.get("routed_top_nets", 0)
    conn = summary.get("top_connectivity") or {}
    conn_str = (
        f" · {conn.get('decap_banks_connected', 0)}/{conn.get('decap_banks_total', 12)} Decap Tied · 0 Shorts"
        if conn and not conn.get("shorts") and not conn.get("opens") else ""
    )
    ax.set_title(
        f"SKY130A 1.8 V 4 Gb/s NRZ SerDes Full-Chip Physical Assembly (serdes_4g_top_pdk)\n"
        f"Core 845.4 × 601.4 µm (0.508 mm²) · {len(macros)} Signed-Off Macros · {decap_title} · "
        f"{n_nets} Routed Top Nets{conn_str} · {drc_str}{gds_str}",
        color=ch["title_fg"], fontsize=10.8, fontweight="bold", pad=12,
    )
    if is_v4_pdn:
        ax.set_xlim(-56, 934)
        ax.set_ylim(-68, 656)
    else:
        ax.set_xlim(-38, 922)
        ax.set_ylim(-50, 642)
    ax.set_aspect("equal")
    ax.set_xlabel("X (µm)", color=ch["axis_fg"], fontsize=9.5)
    ax.set_ylabel("Y (µm)", color=ch["axis_fg"], fontsize=9.5)
    ax.tick_params(colors=ch["tick_fg"], labelsize=8.5)
    for sp in ax.spines.values():
        sp.set_color(ch["spine_ec"])

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=260, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[plot_chip_top] Saved ({theme}) {out_png} ({out_png.stat().st_size/1024:.1f} KB)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=REPO / "docs/figures/layout/serdes_4g_top_pdk_20261123.png")
    ap.add_argument("--theme", choices=("dark", "light", "both"), default="both",
                    help="Render dark silicon, light publication paper, or both (default: both)")
    args = ap.parse_args()
    out_base = args.out.resolve()
    if args.theme == "both":
        render_chip_top(args.work_dir.resolve(), out_base, theme="dark")
        out_light = out_base.with_name(f"{out_base.stem}_light{out_base.suffix}")
        render_chip_top(args.work_dir.resolve(), out_light, theme="light")
    else:
        render_chip_top(args.work_dir.resolve(), out_base, theme=args.theme)


if __name__ == "__main__":
    main()
