#!/usr/bin/env python3
"""Generate 1:1 physical floorplan comparison for Integrated [Buffer + Clock SF + /2 Divider]:
- Current Compact (Plan A+I): 233.66 x 44.84 um = 10,477 um^2 (showing the 3 whitespace regions)
- Integrated Plan J1 (Left-Column [SF + Buf] Fusion + In-Cell Routing): 182.0 x 34.80 um = 6,334 um^2 (-39.5%)
- Integrated Plan J2 (Center-Symmetric [Master | SF+Buf | Slave] + Shared Res Dummies): 174.0 x 34.80 um = 6,055 um^2 (-42.2%)
"""
from __future__ import annotations

from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as patches

OUT_DIR = Path(__file__).resolve().parent


def draw_box(ax, x0, y0, w, h, label="", fc="#dbeafe", ec="#1e3a8a", lw=1.2, fontsize=7.5, alpha=0.88, ls="-", text_color="#0f172a"):
    r = patches.Rectangle((x0, y0), w, h, facecolor=fc, edgecolor=ec, linewidth=lw, linestyle=ls, alpha=alpha)
    ax.add_patch(r)
    if label:
        ax.text(x0 + w / 2, y0 + h / 2, label, ha="center", va="center", fontsize=fontsize, color=text_color, weight="bold")


def draw_stage_j1(ax, x0, stage_name, has_buf=True, is_first=False):
    """Draw one integrated stage in Plan J1: [ (SF + Buf/Bias) | Master | Slave ] within y = [-3.1, +30.9]."""
    # Left fused column: width = 14.8 um (x0 .. x0 + 14.8)
    w_col = 14.8
    # Bottom row (y = -2.3 .. +2.3): L=0.50u standard-Vt NMOS
    if has_buf:
        draw_box(ax, x0 + 0.6, -2.3, w_col - 1.2, 4.6, "Xsp + Xt_buf + Xsn\n(L=0.5u, w=4+12+4)", fc="#fde68a", ec="#b45309", fontsize=6.5)
    else:
        draw_box(ax, x0 + 0.6, -2.3, w_col - 1.2, 4.6, "Xsp+Xsn + Xsink+Xref\n(L=0.5u Bias+SF sinks)", fc="#fde68a", ec="#b45309", fontsize=6.2)

    # Rows 2 & 3 (y = 3.1 .. 15.6): Xfn & Xfp (w=80 LVT SFs)
    draw_box(ax, x0 + 0.8, 3.1, w_col - 1.6, 6.0, "Xfn (LVT SF w=80)\nL=0.15u, nf=16", fc="#bfdbfe", ec="#1d4ed8", fontsize=6.5)
    draw_box(ax, x0 + 0.8, 9.4, w_col - 1.6, 6.0, "Xfp (LVT SF w=80)\nL=0.15u, nf=16", fc="#bfdbfe", ec="#1d4ed8", fontsize=6.5)

    if has_buf:
        # Row 4 (y = 15.8 .. 20.6): Buffer input diff pair Xp | Xn (w=24 LVT)
        draw_box(ax, x0 + 1.2, 15.8, w_col - 2.4, 4.8, "Buf Xp | Xn\n(LVT w=24, nf=8)", fc="#bbf7d0", ec="#15803d", fontsize=6.5)
        # Row 5 (y = 21.0 .. 30.5): Buffer load resistors [Rdum | R0 | R1 | Rdum]
        draw_box(ax, x0 + 0.4, 21.0, w_col - 0.8, 9.5, "Buf Load Resistors\n[Rdum | R0 | R1 | Rdum]\n(l=4.14, 600Ω)", fc="#f5d0fe", ec="#86198f", fontsize=6.3)
    else:
        # First stage (/2): Top half holds Xbias 2x2 PMOS Mirror Quad (w=60, L=0.5u)!
        draw_box(ax, x0 + 0.4, 16.2, w_col - 0.8, 14.0, "Xbias 2x2 PMOS Quad\nXpd | Xpm (w=60, L=0.5u)\n[Fills SF top void!]", fc="#fed7aa", ec="#c2410c", fontsize=6.5)

    # Master & Slave Latches (2 x 22.84 um = 45.68 um)
    for idx, l_nm in enumerate(("Master", "Slave")):
        lx = x0 + w_col + idx * 22.84
        lw = 22.84
        draw_box(ax, lx, -3.1, lw, 34.0, "", fc="#f8fafc", ec="#475569", lw=1.0, alpha=0.5)
        draw_box(ax, lx + 0.6, -2.3, lw - 1.2, 4.6, f"{l_nm} Xtail (w=72, L=0.5u)", fc="#fde68a", ec="#b45309", fontsize=6.5)
        draw_box(ax, lx + 1.0, 3.3, lw - 2.0, 5.2, f"{l_nm} Xct | Xch (w=64 LVT)", fc="#93c5fd", ec="#1d4ed8", fontsize=6.5)
        draw_box(ax, lx + 1.5, 9.0, lw - 3.0, 5.4, f"{l_nm} Xhp | Xhn (Hold LVT)", fc="#a5f3fc", ec="#0e7490", fontsize=6.5)
        draw_box(ax, lx + 4.5, 14.9, lw - 9.0, 5.6, f"{l_nm} Xdp | Xdn\n(Data w=20)", fc="#bbf7d0", ec="#15803d", fontsize=6.2)
        draw_box(ax, lx + 2.0, 21.0, lw - 4.0, 9.5, f"{l_nm} Load\n[Rdum | Rn | Rp | Rdum]", fc="#f5d0fe", ec="#86198f", fontsize=6.3)

    total_w = w_col + 2 * 22.84
    ax.text(x0 + total_w / 2, 31.6, f"{stage_name} ({total_w:.1f}×34.8µm)", ha="center", va="bottom", fontsize=8.0, weight="bold", color="#0f172a")
    return total_w


def draw_stage_j2(ax, x0, stage_name, has_buf=True):
    """Draw one integrated stage in Plan J2: Center-Symmetric [ Master | (SF + Buf/Bias) | Slave ] with shared dummy resistors."""
    lw = 21.20
    w_mid = 14.80
    # Master (left), Mid (SF+Buf), Slave (right)
    for idx, l_nm in ((0, "Master"), (2, "Slave")):
        lx = x0 + (0.0 if idx == 0 else (lw + w_mid))
        draw_box(ax, lx, -3.1, lw, 34.0, "", fc="#f8fafc", ec="#475569", lw=1.0, alpha=0.5)
        draw_box(ax, lx + 0.5, -2.3, lw - 1.0, 4.6, f"{l_nm} Xtail (w=72, L=0.5u)", fc="#fde68a", ec="#b45309", fontsize=6.3)
        draw_box(ax, lx + 0.8, 3.3, lw - 1.6, 5.2, f"{l_nm} Xct | Xch (w=64)", fc="#93c5fd", ec="#1d4ed8", fontsize=6.3)
        draw_box(ax, lx + 1.2, 9.0, lw - 2.4, 5.4, f"{l_nm} Xhp | Xhn (Hold)", fc="#a5f3fc", ec="#0e7490", fontsize=6.3)
        draw_box(ax, lx + 4.0, 14.9, lw - 8.0, 5.6, f"{l_nm} Xdp | Xdn", fc="#bbf7d0", ec="#15803d", fontsize=6.2)

    mx = x0 + lw
    if has_buf:
        draw_box(ax, mx + 0.4, -2.3, w_mid - 0.8, 4.6, "Xsp+Xt_buf+Xsn\n(L=0.5u)", fc="#fde68a", ec="#b45309", fontsize=6.2)
    else:
        draw_box(ax, mx + 0.4, -2.3, w_mid - 0.8, 4.6, "Xsp+Xsn+Xsink+Xref\n(L=0.5u)", fc="#fde68a", ec="#b45309", fontsize=6.0)

    draw_box(ax, mx + 0.6, 3.1, w_mid - 1.2, 6.0, "Xfn (SF w=80)\n<- Sym ckn ->", fc="#bfdbfe", ec="#1d4ed8", fontsize=6.3)
    draw_box(ax, mx + 0.6, 9.4, w_mid - 1.2, 6.0, "Xfp (SF w=80)\n<- Sym ckp ->", fc="#bfdbfe", ec="#1d4ed8", fontsize=6.3)

    if has_buf:
        draw_box(ax, mx + 1.0, 15.8, w_mid - 2.0, 4.8, "Buf Xp | Xn (w=24)", fc="#bbf7d0", ec="#15803d", fontsize=6.2)
        # Continuous shared-dummy resistor row across Master + Buf + Slave!
        draw_box(ax, x0 + 1.2, 21.0, 2 * lw + w_mid - 2.4, 9.5,
                 "Shared-Dummy 10-Resistor Array: [Rdum | M_Rn | M_Rp | Rdum_shared | Buf_R0 | Buf_R1 | Rdum_shared | S_Rn | S_Rp | Rdum]",
                 fc="#f5d0fe", ec="#86198f", fontsize=6.4)
    else:
        draw_box(ax, x0 + 1.2, 21.0, lw - 2.0, 9.5, "Master Load\n[Rdum|Rn|Rp|Rdum]", fc="#f5d0fe", ec="#86198f", fontsize=6.0)
        draw_box(ax, mx + 0.4, 16.2, w_mid - 0.8, 14.0, "Xbias PMOS Quad\n(w=60, L=0.5u)", fc="#fed7aa", ec="#c2410c", fontsize=6.3)
        draw_box(ax, mx + w_mid + 0.8, 21.0, lw - 2.0, 9.5, "Slave Load\n[Rdum|Rn|Rp|Rdum]", fc="#f5d0fe", ec="#86198f", fontsize=6.0)

    total_w = 2 * lw + w_mid
    ax.text(x0 + total_w / 2, 31.6, f"{stage_name} ({total_w:.1f}×34.8µm)", ha="center", va="bottom", fontsize=8.0, weight="bold", color="#0f172a")
    return total_w


def main():
    fig, axes = plt.subplots(3, 1, figsize=(18, 15.5), dpi=160)
    plt.subplots_adjust(hspace=0.34, left=0.05, right=0.98, top=0.94, bottom=0.04)

    # -----------------------------------------------------------------------
    # Panel 1: Current Compact Layout (233.66 x 44.84 um = 10,477 um^2)
    # -----------------------------------------------------------------------
    ax = axes[0]
    ax.set_title("1. Current Layout (Plan A + I): 233.66 × 44.84 µm = 10,477 µm² — Highlighting the 3 Whitespace Regions (Red Hatched)", fontsize=11, weight="bold", pad=10)
    # Draw outer routing channels (wasted height)
    draw_box(ax, -39.6, 30.9, 233.66, 5.6, "WASTED TOP ROUTING CHANNEL (y = +30.9 .. +36.5 µm, 4 M3 tracks outside VDD rail = 1,308 µm²)", fc="#fee2e2", ec="#dc2626", ls="--", fontsize=8, text_color="#991b1b")
    draw_box(ax, -39.6, -8.6, 233.66, 5.5, "WASTED BOTTOM ROUTING CHANNEL (y = -8.6 .. -3.1 µm, 4 M3 tracks outside VSS rail = 1,285 µm²)", fc="#fee2e2", ec="#dc2626", ls="--", fontsize=8, text_color="#991b1b")

    # Xbias
    draw_box(ax, -38.4, -3.1, 14.8, 34.0, "Xbias\n15.6×34.8", fc="#fed7aa", ec="#c2410c", fontsize=7.5)
    # X2, X4, X8 + Xb24, Xb48
    for dx_div, nm in ((0.0, "X2 (/2)"), (79.5, "X4 (/4)"), (159.0, "X8 (/8)")):
        # SF col (-21.7 .. -11.4)
        draw_box(ax, dx_div - 21.7, -3.1, 10.3, 19.5, f"{nm}\nSF + Sinks\n(y=-3..16.4)", fc="#bfdbfe", ec="#1d4ed8", fontsize=7)
        draw_box(ax, dx_div - 21.7, 16.4, 10.3, 14.5, "VOID #1\nEmpty above SF\n(10.3×14.5 µm)", fc="#fecaca", ec="#dc2626", ls="--", fontsize=6.8, text_color="#991b1b")
        draw_box(ax, dx_div - 11.4, -3.1, 45.68, 34.0, f"{nm} Master + Slave Latches\n(45.7 × 34.0 µm)", fc="#e2e8f0", ec="#334155", fontsize=8)

    for dx_b, bnm in ((46.0, "Xb24"), (125.5, "Xb48")):
        draw_box(ax, dx_b - 8.2, 21.0, 16.4, 9.9, f"{bnm} Load Res\n(16.4×9.9 µm)", fc="#f5d0fe", ec="#86198f", fontsize=7)
        draw_box(ax, dx_b - 4.5, 11.5, 9.0, 5.0, f"{bnm} Xp/Xn", fc="#bbf7d0", ec="#15803d", fontsize=6.5)
        draw_box(ax, dx_b - 2.0, 2.5, 4.0, 4.5, "Xt", fc="#fde68a", ec="#b45309", fontsize=6.5)
        draw_box(ax, dx_b - 8.2, -3.1, 16.4, 14.5, "VOID #2\n>65% Empty\nunder Buf Res", fc="#fecaca", ec="#dc2626", ls="--", fontsize=6.8, text_color="#991b1b", alpha=0.55)

    ax.axhline(30.9, color="#1d4ed8", lw=2.0, label="VDD M1 Rail (+30.9 µm)")
    ax.axhline(-3.1, color="#0f172a", lw=2.0, label="VSS M1 Rail (-3.1 µm)")
    ax.set_xlim(-45, 200)
    ax.set_ylim(-11, 40)
    ax.set_ylabel("y (µm)")
    ax.grid(True, linestyle=":", alpha=0.4)

    # -----------------------------------------------------------------------
    # Panel 2: Integrated Plan J1 ([ (SF + Buf/Bias) | Master | Slave ])
    # -----------------------------------------------------------------------
    ax = axes[1]
    ax.set_title("2. Integrated Plan J1 (Left-Fused [SF + Buf/Bias] Column + Over-the-Cell M3/M4 Routing): 183.5 × 34.8 µm = 6,386 µm² (-39.0% Area)", fontsize=11, weight="bold", pad=10)
    x_cur = -39.6
    w1 = draw_stage_j1(ax, x_cur, "Stage 1: [ (SF + Xbias) | Master(/2) | Slave(/2) ]", has_buf=False, is_first=True)
    x_cur += w1 + 1.0
    w2 = draw_stage_j1(ax, x_cur, "Stage 2: [ (SF + Xb24) | Master(/4) | Slave(/4) ]", has_buf=True)
    x_cur += w2 + 1.0
    w3 = draw_stage_j1(ax, x_cur, "Stage 3: [ (SF + Xb48) | Master(/8) | Slave(/8) ]", has_buf=True)
    ax.axhline(30.9, color="#1d4ed8", lw=2.2)
    ax.axhline(-3.1, color="#0f172a", lw=2.2)
    ax.text(146.0, 28.0, "In-Cell M3/M4: mp/mn/qp/qn\n(over resistors, zero top overhang)", fontsize=7.5, color="#991b1b", weight="bold")
    ax.text(146.0, -0.5, "In-Cell M3/M4: ckp/ckn/vbias\n(zero bottom overhang)", fontsize=7.5, color="#991b1b", weight="bold")
    ax.set_xlim(-45, 200)
    ax.set_ylim(-11, 40)
    ax.set_ylabel("y (µm)")
    ax.grid(True, linestyle=":", alpha=0.4)

    # -----------------------------------------------------------------------
    # Panel 3: Integrated Plan J2 (Center-Symmetric [ Master | (SF + Buf) | Slave ])
    # -----------------------------------------------------------------------
    ax = axes[2]
    ax.set_title("3. Integrated Plan J2 (Center-Symmetric [Master | SF+Buf | Slave] + Shared Dummy Resistors): 173.6 × 34.8 µm = 6,041 µm² (-42.3% Area)", fontsize=11, weight="bold", pad=10)
    x_cur = -39.6
    w1 = draw_stage_j2(ax, x_cur, "Stage 1: [ Master(/2) | (SF+Xbias) | Slave(/2) ]", has_buf=False)
    x_cur += w1 + 1.0
    w2 = draw_stage_j2(ax, x_cur, "Stage 2: [ Master(/4) | (SF+Xb24) | Slave(/4) ]", has_buf=True)
    x_cur += w2 + 1.0
    w3 = draw_stage_j2(ax, x_cur, "Stage 3: [ Master(/8) | (SF+Xb48) | Slave(/8) ]", has_buf=True)
    ax.axhline(30.9, color="#1d4ed8", lw=2.2)
    ax.axhline(-3.1, color="#0f172a", lw=2.2)
    ax.set_xlim(-45, 200)
    ax.set_ylim(-11, 40)
    ax.set_xlabel("x (µm) — Identical 1:1 Scale Across All 3 Panels", fontsize=9.5, weight="bold")
    ax.set_ylabel("y (µm)")
    ax.grid(True, linestyle=":", alpha=0.4)

    out_png = OUT_DIR / "divider_integrated_plan.png"
    fig.savefig(out_png, bbox_inches="tight")
    print(f"Saved {out_png}")


if __name__ == "__main__":
    main()
