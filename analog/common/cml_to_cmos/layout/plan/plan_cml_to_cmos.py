#!/usr/bin/env python3
"""Generate floorplan comparison & detailed column map for CML-to-CMOS Receiver:
- Panel 1 (1:1 scale): Legacy v1 Layout (134.87 x 71.00 um = 9,575.77 um^2) vs Plan C2 (47.50 x 28.40 um = 1,349.00 um^2, -85.9%)
- Panel 2 (Zoomed detail): Plan C2 100%-Filled Strip Architecture (Xfp stacked over Xsp+Xtail to fill the top-left void!)
"""
from __future__ import annotations

import json
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as patches

OUT_DIR = Path(__file__).resolve().parent


def draw_box(
    ax,
    x0: float,
    y0: float,
    w: float,
    h: float,
    label: str = "",
    fc: str = "#dbeafe",
    ec: str = "#1e3a8a",
    lw: float = 1.1,
    fontsize: float = 7.0,
    alpha: float = 0.90,
    ls: str = "-",
    text_color: str = "#0f172a",
) -> None:
    r = patches.Rectangle(
        (x0, y0), w, h, facecolor=fc, edgecolor=ec, linewidth=lw, linestyle=ls, alpha=alpha
    )
    ax.add_patch(r)
    if label:
        ax.text(
            x0 + w / 2,
            y0 + h / 2,
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            color=text_color,
            weight="bold",
        )


# Columns from Xip rightward (where Upper Row = PMOS in N-Well, Lower Row = NMOS in P-Well)
# Left of Xip (x = 1.20 .. 9.60):
#   - Lower Row (NMOS): [Ndum (2.11) | Xsp (2.46, l=0.5) | Xtail (4.83, w=2x4, l=0.5)] -> abutted width = 2.11 + 2.46 + 4.83 - 2*0.51 = 8.38 um
#   - Upper Row (LVT NMOS under VDD rail!): [Ndum_sf | Xfp (7.43, w=2x10 LVT, D=VDD, S=fp)] -> width = 8.38 um!
RIGHT_COLUMNS = [
    ("Xip", "Xip LVT\n(w=2x3)", "Xlp\n(w=2x4)", 3.59, True),
    ("Xin", "Xin LVT\n(w=2x3)", "Xln\n(w=2x4)", 3.59, True),
    ("Xbp", "Xbp.n\n(1.8)", "Xbp.p\n(1.8x2)", 2.63, False),
    ("Xop", "Xop.n\n(2x2)", "Xop.p\n(2x6)", 4.55, False),
    ("Xdp1", "dp1.n\n(0.5)", "dp1.p\n(1.5)", 2.11, False),
    ("Xdp2", "dp2.n\n(0.5)", "dp2.p\n(1.5)", 2.11, False),
    ("Xdp3", "dp3.n\n(0.5)", "dp3.p\n(1.5)", 2.11, False),
    ("Xset", "set.n\n(2x2 cg0)", "set.p\n(1.5x4)", 3.59, False),
    ("Xqp", "qp.n\n(2x4 cg0)", "qp.p\n(2x6)", 4.55, False),
    ("Xrp1", "rp1.n\n(2.0)", "rp1.p\n(2x3)", 3.11, False),
    ("Xrp2", "rp2.n\n(1.0)", "rp2.p\n(1.5x2)", 2.63, False),
    ("Xbpr", "bpr.n\n(2x2 cg0)", "bpr.p\n(1.5x4)", 3.59, False),
    ("Xopr", "opr.n\n(2x2)", "opr.p\n(2x4)", 3.59, False),
    ("DumR", "Ndum\n(nf=1)", "Pdum\n(nf=1)", 2.11, False),
]


def compute_layout() -> tuple[list[dict], list[dict], float]:
    overlap = 0.51
    # Left analog block: Lower row has Ndum (2.11) + Xsp (2.46) + Xtail (4.83)
    left_n = []
    x_cur = 1.20
    for nm, lbl, w in [
        ("DumL", "Ndum\n(nf=1)", 2.11),
        ("Xsp", "Xsp\n(w=2,l=.5)", 2.46),
        ("Xtail", "Xtail\n(w=2x4,l=.5)", 4.83),
    ]:
        left_n.append({"name": nm, "lbl": lbl, "x0": round(x_cur, 3), "w": w, "cx": round(x_cur + w / 2, 3)})
        x_cur += w - overlap

    # Leave 0.45 um well clearance between Upper Xfp (P-well) and Xlp (N-well)
    x_cur = round(x_cur + overlap + 0.45, 3)

    right_cols = []
    for name, n_lbl, p_lbl, w, is_ana in RIGHT_COLUMNS:
        right_cols.append(
            {
                "name": name,
                "n_lbl": n_lbl,
                "p_lbl": p_lbl,
                "x0": round(x_cur, 3),
                "w": w,
                "cx": round(x_cur + w / 2, 3),
                "is_ana": is_ana,
            }
        )
        x_cur += w - overlap

    total_w = round(x_cur + overlap + 1.20, 2)
    return left_n, right_cols, total_w


def main() -> None:
    left_n, right_cols, total_w = compute_layout()
    total_h = 28.40

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(15.5, 11.2), gridspec_kw={"height_ratios": [1.05, 1.35]}
    )
    fig.patch.set_facecolor("white")

    # =========================================================================
    # PANEL 1: 1:1 Scale Footprint Comparison (v1 134.87 x 71.00 vs Plan C2)
    # =========================================================================
    ax1.set_title(
        f"1:1 Physical Scale Comparison: v1 Baseline (134.87 × 71.00 µm = 9,575.8 µm²)  vs.  Plan C2 ({total_w:.1f} × {total_h:.1f} µm = {total_w*total_h:,.0f} µm², -85.5% Area)",
        fontsize=11.0,
        weight="bold",
        color="#0f172a",
        pad=10,
    )

    draw_box(ax1, 0.0, -35.5, 134.87, 71.0, "", fc="#f8fafc", ec="#64748b", lw=1.5, ls="--")
    draw_box(
        ax1,
        2.0,
        11.5,
        130.0,
        14.5,
        "v1 Upper Routing Canyon (20.6 µm gap for only 4 active tracks!)",
        fc="#fee2e2",
        ec="#dc2626",
        lw=1.0,
        ls=":",
        fontsize=8.0,
        text_color="#991b1b",
    )
    draw_box(
        ax1,
        2.0,
        -26.0,
        130.0,
        14.5,
        "v1 Lower Routing Canyon (20.6 µm gap)",
        fc="#fee2e2",
        ec="#dc2626",
        lw=1.0,
        ls=":",
        fontsize=8.0,
        text_color="#991b1b",
    )
    draw_box(
        ax1,
        2.0,
        -5.5,
        130.0,
        11.0,
        "v1 Split Center VSS Dead Zone (11.0 µm gap between P/N NMOS rows)",
        fc="#fef3c7",
        ec="#d97706",
        lw=1.0,
        ls=":",
        fontsize=8.0,
        text_color="#92400e",
    )
    for col_idx in range(16):
        cx = 5.0 + col_idx * 8.0
        draw_box(ax1, cx - 1.3, 6.4, 2.6, 4.5, "", fc="#93c5fd", ec="#1d4ed8", lw=0.8)
        draw_box(ax1, cx - 1.3, -10.9, 2.6, 4.5, "", fc="#93c5fd", ec="#1d4ed8", lw=0.8)
        if col_idx >= 3:
            draw_box(ax1, cx - 1.3, 26.8, 2.6, 4.5, "", fc="#fdba74", ec="#c2410c", lw=0.8)
            draw_box(ax1, cx - 1.3, -31.3, 2.6, 4.5, "", fc="#fdba74", ec="#c2410c", lw=0.8)
    ax1.text(
        67.4,
        33.2,
        "v1 Isolated Islands: 6.5–7.0 µm column pitch due to horizontal M1 gate whiskers (-1.55 µm)",
        ha="center",
        va="center",
        fontsize=8.0,
        color="#334155",
        weight="bold",
    )

    # Plan C2 at 1:1 scale on the right
    x_c2 = 146.0
    draw_box(ax1, x_c2, -total_h / 2, total_w, total_h, "", fc="#ecfdf5", ec="#047857", lw=2.0)
    draw_box(
        ax1,
        x_c2 + 0.8,
        0.0,
        total_w - 1.6,
        4.10,
        "P-Half NMOS Strip (w_f ≤ 2.0u)",
        fc="#93c5fd",
        ec="#1d4ed8",
        fontsize=7.0,
    )
    draw_box(
        ax1,
        x_c2 + 0.8,
        -4.10,
        total_w - 1.6,
        4.10,
        "N-Half NMOS Strip (Mirrored)",
        fc="#93c5fd",
        ec="#1d4ed8",
        fontsize=7.0,
    )
    draw_box(
        ax1,
        x_c2 + 0.8,
        4.10,
        total_w - 1.6,
        2.90,
        "2.9 µm 4-Track Channel",
        fc="#fef08a",
        ec="#ca8a04",
        fontsize=6.5,
    )
    draw_box(
        ax1,
        x_c2 + 0.8,
        -7.00,
        total_w - 1.6,
        2.90,
        "2.9 µm 4-Track Channel",
        fc="#fef08a",
        ec="#ca8a04",
        fontsize=6.5,
    )
    draw_box(
        ax1,
        x_c2 + 0.8,
        7.00,
        8.4,
        4.19,
        "Xfp LVT",
        fc="#6ee7b7",
        ec="#047857",
        fontsize=6.5,
    )
    draw_box(
        ax1,
        x_c2 + 0.8,
        -11.19,
        8.4,
        4.19,
        "Xfn LVT",
        fc="#6ee7b7",
        ec="#047857",
        fontsize=6.5,
    )
    draw_box(
        ax1,
        x_c2 + 9.5,
        7.00,
        total_w - 10.3,
        4.19,
        "P-Half PMOS Strip",
        fc="#fdba74",
        ec="#c2410c",
        fontsize=7.0,
    )
    draw_box(
        ax1,
        x_c2 + 9.5,
        -11.19,
        total_w - 10.3,
        4.19,
        "N-Half PMOS Strip",
        fc="#fdba74",
        ec="#c2410c",
        fontsize=7.0,
    )
    ax1.text(
        x_c2 + total_w / 2,
        total_h / 2 + 3.5,
        f"Plan C2 (1:1 Scale)\n{total_w:.1f} × {total_h:.1f} µm = {total_w*total_h:,.0f} µm²\n(-85.5% Area vs. v1!)",
        ha="center",
        va="bottom",
        fontsize=9.0,
        color="#047857",
        weight="bold",
    )

    ax1.set_xlim(-4.0, 202.0)
    ax1.set_ylim(-39.0, 39.0)
    ax1.set_aspect("equal")
    ax1.set_xlabel("x (µm) — 1:1 Physical Scale", fontsize=9.0)
    ax1.set_ylabel("y (µm)", fontsize=9.0)
    ax1.grid(True, linestyle=":", alpha=0.35)

    # =========================================================================
    # PANEL 2: Zoomed Detailed Architecture of Plan C2
    # =========================================================================
    ax2.set_title(
        f"Plan C2 Detailed Column Map ({total_w:.1f} × {total_h:.1f} µm): Xfp/Xfn Folded into Top/Bot-Left Void (100% Corner-to-Corner Fill!)",
        fontsize=11.0,
        weight="bold",
        color="#0f172a",
        pad=10,
    )

    draw_box(ax2, 0.0, -14.2, total_w, 28.4, "", fc="#f8fafc", ec="#0f172a", lw=1.6)

    # Top/Bottom VDD Guard-Ring & M1/M2 Rails + Center Shared VSS Spine
    draw_box(
        ax2,
        0.5,
        11.2,
        total_w - 1.0,
        1.1,
        "Top VDD M1/M2 Rail (y = +11.75 µm) — Feeds Xfp Drain Directly + PMOS N-Well Guard-Ring",
        fc="#fecaca",
        ec="#b91c1c",
        fontsize=7.5,
        text_color="#7f1d1d",
    )
    draw_box(
        ax2,
        0.5,
        -12.3,
        total_w - 1.0,
        1.1,
        "Bottom VDD M1/M2 Rail (y = -11.75 µm) — Feeds Xfn Drain Directly + PMOS N-Well Guard-Ring",
        fc="#fecaca",
        ec="#b91c1c",
        fontsize=7.5,
        text_color="#7f1d1d",
    )
    draw_box(
        ax2,
        0.5,
        -0.55,
        total_w - 1.0,
        1.1,
        "Shared Center VSS Spine (y = 0.00 µm): P-Half & N-Half NMOS Guard-Rings Abut Back-to-Back",
        fc="#cbd5e1",
        ec="#334155",
        fontsize=7.8,
        text_color="#0f172a",
    )

    # Upper & Lower 4-Track Channels
    for sign, name in ((+1, "P-Half 4-Track M1/M2 Channel (0.32 µm uniform width)"), (-1, "N-Half 4-Track M1/M2 Channel (Mirrored)")):
        y0 = 4.35 if sign > 0 else -7.35
        draw_box(ax2, 0.8, y0, total_w - 1.6, 3.00, "", fc="#fef9c3", ec="#ca8a04", lw=1.0, alpha=0.75)
        for ty in (4.80, 5.50, 6.20, 6.90):
            yy = sign * ty
            ax2.plot([1.2, total_w - 1.2], [yy, yy], color="#eab308", lw=1.0, ls="--", alpha=0.8)
        ax2.text(
            total_w / 2 + 2.0,
            sign * 5.85,
            name,
            ha="center",
            va="center",
            fontsize=7.4,
            color="#854d0e",
            weight="bold",
            bbox=dict(boxstyle="round,pad=0.15", fc="#fef9c3", ec="none", alpha=0.85),
        )

    # 1. Draw Left Analog Block:
    # Lower Row: [DumL | Xsp | Xtail]
    for col in left_n:
        x0, w = col["x0"], col["w"]
        fc_n = "#e2e8f0" if col["name"] == "DumL" else "#fde68a"
        ec_n = "#475569" if col["name"] == "DumL" else "#b45309"
        draw_box(ax2, x0, 0.55, w, 3.80, col["lbl"], fc=fc_n, ec=ec_n, fontsize=6.1)
        draw_box(ax2, x0 + 0.25, 3.95, w - 0.5, 0.32, "", fc="#dc2626", ec="#991b1b", lw=0.6)
        draw_box(ax2, x0, -4.35, w, 3.80, col["lbl"].replace("Xsp", "Xsn"), fc=fc_n, ec=ec_n, fontsize=6.1)
        draw_box(ax2, x0 + 0.25, -4.27, w - 0.5, 0.32, "", fc="#dc2626", ec="#991b1b", lw=0.6)

    # Upper Row above [DumL | Xsp | Xtail]: [Dum_sf | Xfp (LVT w=2x10, D=VDD, S=fp)]
    draw_box(ax2, 1.20, 7.35, 1.60, 3.85, "Ndum\n(nf=1)", fc="#e2e8f0", ec="#475569", fontsize=5.8)
    draw_box(ax2, 1.20, -11.20, 1.60, 3.85, "Ndum\n(nf=1)", fc="#e2e8f0", ec="#475569", fontsize=5.8)
    draw_box(
        ax2,
        2.80,
        7.35,
        6.78,
        3.85,
        "Xfp LVT SF (w=2x10)\n[D=VDD, S=fp, G=inp]\nFills Top-Left Void!",
        fc="#6ee7b7",
        ec="#047857",
        fontsize=5.9,
    )
    draw_box(ax2, 3.10, 7.43, 6.18, 0.32, "", fc="#dc2626", ec="#991b1b", lw=0.6)
    draw_box(
        ax2,
        2.80,
        -11.20,
        6.78,
        3.85,
        "Xfn LVT SF (w=2x10)\n[D=VDD, S=fn, G=inn]\nFills Bot-Left Void!",
        fc="#6ee7b7",
        ec="#047857",
        fontsize=5.9,
    )
    draw_box(ax2, 3.10, -7.75, 6.18, 0.32, "", fc="#dc2626", ec="#991b1b", lw=0.6)
    ax2.text(5.40, 12.85, "Xfp over [Xsp+Xtail]", ha="center", va="center", fontsize=6.8, weight="bold", color="#047857")

    # 2. Draw Right Columns (Xip .. DumR)
    for col in right_cols:
        x0, w = col["x0"], col["w"]
        fc_n = "#bfdbfe" if col["is_ana"] else "#dbeafe"
        ec_n = "#1d4ed8" if col["is_ana"] else "#2563eb"
        fc_p = "#fed7aa" if col["is_ana"] else "#ffedd5"
        ec_p = "#c2410c" if col["is_ana"] else "#ea580c"
        if col["name"].startswith("Dum"):
            fc_n, ec_n = "#e2e8f0", "#475569"
            fc_p, ec_p = "#e2e8f0", "#475569"

        draw_box(ax2, x0, 0.55, w, 3.80, col["n_lbl"], fc=fc_n, ec=ec_n, fontsize=6.0)
        draw_box(ax2, x0 + 0.25, 3.95, w - 0.5, 0.32, "", fc="#dc2626", ec="#991b1b", lw=0.6)

        draw_box(ax2, x0, -4.35, w, 3.80, col["n_lbl"], fc=fc_n, ec=ec_n, fontsize=6.0)
        draw_box(ax2, x0 + 0.25, -4.27, w - 0.5, 0.32, "", fc="#dc2626", ec="#991b1b", lw=0.6)

        draw_box(ax2, x0, 7.35, w, 3.85, col["p_lbl"], fc=fc_p, ec=ec_p, fontsize=6.0)
        draw_box(ax2, x0 + 0.25, 7.43, w - 0.5, 0.32, "", fc="#dc2626", ec="#991b1b", lw=0.6)

        draw_box(ax2, x0, -11.20, w, 3.85, col["p_lbl"], fc=fc_p, ec=ec_p, fontsize=6.0)
        draw_box(ax2, x0 + 0.25, -7.75, w - 0.5, 0.32, "", fc="#dc2626", ec="#991b1b", lw=0.6)

        gx = x0 + w * 0.35
        ax2.plot([gx, gx], [4.10, 7.55], color="#0284c7", lw=1.6)
        ax2.plot([gx, gx], [-7.55, -4.10], color="#0284c7", lw=1.6)

        ax2.text(col["cx"], 12.85, col["name"], ha="center", va="center", fontsize=6.8, weight="bold", color="#1e293b")

    # Two symmetric M3 vertical cross-overs
    x_cr1 = right_cols[0]["x0"] - 0.22
    ax2.plot([x_cr1 - 0.22, x_cr1 - 0.22], [-5.5, 5.5], color="#dc2626", lw=2.4)
    ax2.plot([x_cr1 + 0.22, x_cr1 + 0.22], [-5.5, 5.5], color="#dc2626", lw=2.4)
    ax2.text(
        x_cr1,
        0.0,
        "M3 Cross 1\nfp ↔ fn",
        ha="center",
        va="center",
        fontsize=6.5,
        weight="bold",
        color="white",
        bbox=dict(boxstyle="round,pad=0.2", fc="#dc2626", ec="#7f1d1d", lw=1.0),
    )

    x_cr2 = right_cols[8]["x0"] - 0.15
    ax2.plot([x_cr2 - 0.22, x_cr2 - 0.22], [-6.5, 6.5], color="#dc2626", lw=2.4)
    ax2.plot([x_cr2 + 0.22, x_cr2 + 0.22], [-6.5, 6.5], color="#dc2626", lw=2.4)
    ax2.text(
        x_cr2,
        0.0,
        "M3 Cross 2\nqp ↔ qn",
        ha="center",
        va="center",
        fontsize=6.5,
        weight="bold",
        color="white",
        bbox=dict(boxstyle="round,pad=0.2", fc="#dc2626", ec="#7f1d1d", lw=1.0),
    )

    for yp, lbl in ((7.6, "inp"), (-7.6, "inn"), (3.95, "vbias")):
        ax2.plot(0.4, yp, "s", color="#dc2626", markersize=6)
        ax2.text(0.1, yp, lbl, ha="right", va="center", fontsize=8.0, weight="bold", color="#dc2626")
    for yp, lbl in ((5.5, "outp"), (-5.5, "outn")):
        ax2.plot(total_w - 0.4, yp, "s", color="#dc2626", markersize=6)
        ax2.text(total_w - 0.1, yp, lbl, ha="left", va="center", fontsize=8.0, weight="bold", color="#dc2626")

    ax2.set_xlim(-2.8, total_w + 2.8)
    ax2.set_ylim(-14.8, 14.8)
    ax2.set_aspect("equal")
    ax2.set_xlabel("x (µm) — Zoomed Plan C2 Detail", fontsize=9.0)
    ax2.set_ylabel("y (µm)", fontsize=9.0)
    ax2.grid(True, linestyle=":", alpha=0.35)

    plt.tight_layout()
    out_png = OUT_DIR / "cml_to_cmos_plan.png"
    fig.savefig(out_png, dpi=220)
    plt.close(fig)

    plan_json = {
        "cell": "serdes_cml_to_cmos_pvt_candidate_pdk",
        "v1_size_um": [134.87, 71.00],
        "v1_area_um2": 9575.77,
        "plan_c2_size_um": [total_w, total_h],
        "plan_c2_area_um2": round(total_w * total_h, 2),
        "area_reduction_pct": round((1.0 - (total_w * total_h) / 9575.77) * 100.0, 1),
        "left_n": left_n,
        "right_columns": right_cols,
    }
    (OUT_DIR / "cml_to_cmos_plan.json").write_text(json.dumps(plan_json, indent=2) + "\n")
    print(f"Saved {out_png} ({total_w} x {total_h} um = {total_w*total_h:.1f} um^2)")


if __name__ == "__main__":
    main()
