#!/usr/bin/env python3
"""Render layer-separated and hierarchy-organized layout screenshots into docs/figures/layout/."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "analog/layout/scripts"))
from layout_core import LAYER_STYLE, LayoutCanvas, load_mag_as_canvas  # noqa: E402

FEOL_LAYERS = {
    "pwell", "nwell", "psubdiff", "nsubdiff", "ndiff", "pdiff",
    "poly", "nmos", "nmoslvt", "pmos", "pmoslvt", "varactor",
    "xhrpoly", "ppolyres", "xpolycontact",
}
MEOL_LAYERS = {
    "locali", "polycont", "ndiffc", "pdiffc", "nsubdiffcont", "psubdiffcont",
    "viali", "mcon", "m1", "metal1",
}
BEOL_LAYERS = {
    "via1", "m2", "metal2", "via2", "m3", "metal3",
    "mimcap", "mimcapcontact", "via3", "m4", "metal4", "via4", "m5", "metal5",
}


def plot_canvas_subset(
    ax,
    canvas: LayoutCanvas,
    title: str,
    subtitle: str = "",
    allowed_layers: set[str] | None = None,
    show_labels: bool = True,
    show_cuts: bool = True,
    xlim: tuple[float, float] | None = None,
    ylim: tuple[float, float] | None = None,
) -> tuple[tuple[float, float], tuple[float, float]]:
    ax.set_facecolor("#ffffff")
    ordered = sorted(canvas.rects.keys(), key=lambda k: LAYER_STYLE.get(k, {}).get("z", 5))
    seen_labels = set()
    cut_layers = {"polycont", "ndiffc", "pdiffc", "nsubdiffcont", "psubdiffcont", "viali", "mcon"}
    for lyr in ordered:
        if allowed_layers is not None and lyr not in allowed_layers:
            continue
        if not show_cuts and lyr in cut_layers:
            continue
        st = LAYER_STYLE.get(lyr, dict(fc="#cbd5e1", ec="#64748b", alpha=0.5, z=5, label=lyr))
        lbl_name = st["label"]
        for (x1, y1, x2, y2) in canvas.rects[lyr]:
            lbl = lbl_name if lbl_name not in seen_labels else "_nolegend_"
            seen_labels.add(lbl_name)
            ax.add_patch(Rectangle(
                (x1, y1), x2 - x1, y2 - y1,
                facecolor=st["fc"], edgecolor=st.get("ec", "none"),
                linewidth=st.get("lw", 0.4), alpha=st["alpha"], zorder=st["z"], label=lbl,
            ))
    if show_labels:
        for _, lx, ly, nm in canvas.labels:
            ax.plot(lx, ly, "ko", markersize=3.0, zorder=25)
            ax.text(
                lx + 0.12, ly + 0.08, nm, fontsize=7.5, fontweight="bold", color="#0f172a",
                bbox=dict(boxstyle="round,pad=0.14", fc="#ffffff", ec="#94a3b8", alpha=0.88),
                zorder=26,
            )
    if xlim is None or ylim is None:
        bx1, by1, bx2, by2 = canvas.bbox()
        pad_x = max(0.8, (bx2 - bx1) * 0.06)
        pad_y = max(0.8, (by2 - by1) * 0.06)
        xlim = (bx1 - pad_x, bx2 + pad_x)
        ylim = (by1 - pad_y, by2 + pad_y)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", linewidth=0.45, color="#cbd5e1", alpha=0.7)
    ax.set_xlabel("x (um)", fontsize=8.5)
    ax.set_ylabel("y (um)", fontsize=8.5)
    ax.set_title(f"{title}\n{subtitle}" if subtitle else title, fontsize=9, fontweight="bold", pad=6)
    return xlim, ylim


def render_layer_stack(mag_path: Path, cell: str, out_png: Path, header: str) -> None:
    canvas = load_mag_as_canvas(mag_path, cell)
    fig, axes = plt.subplots(1, 4, figsize=(20, 6.4), dpi=150)
    tiers = [
        ("Composite (All Masks)", None, True),
        ("FEOL (Wells + Diff + Poly/Res)", FEOL_LAYERS, False),
        ("MEOL (Contacts + LI1 + M1)", MEOL_LAYERS, False),
        ("BEOL (Via1..3 + M2..M4 + MIM)", BEOL_LAYERS, True),
    ]
    bx1, by1, bx2, by2 = canvas.bbox()
    pad_x = max(0.8, (bx2 - bx1) * 0.08)
    pad_y = max(0.8, (by2 - by1) * 0.08)
    xl = (bx1 - pad_x, bx2 + pad_x)
    yl = (by1 - pad_y, by2 + pad_y)
    for ax, (title, subset, show_lbl) in zip(axes, tiers):
        plot_canvas_subset(ax, canvas, title, "", allowed_layers=subset,
                           show_labels=show_lbl, show_cuts=True, xlim=xl, ylim=yl)
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="lower center", ncol=7, fontsize=7.5, frameon=False)
    fig.suptitle(header, fontsize=11.5, fontweight="bold", y=0.98)
    fig.subplots_adjust(bottom=0.18, top=0.86, wspace=0.22)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out_png)


def render_grid(items: list[tuple[str, Path, str, str]], out_png: Path, sup: str, ncols: int = 2) -> None:
    nrows = (len(items) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(7.0 * ncols, 6.2 * nrows), dpi=150)
    axes_flat = list(axes.flat) if hasattr(axes, "flat") else [axes]
    seen_handles = {}
    for ax, (title, path, cell, sub) in zip(axes_flat, items):
        canvas = load_mag_as_canvas(path, cell)
        plot_canvas_subset(ax, canvas, title, sub, show_cuts=True)
        h, l = ax.get_legend_handles_labels()
        for hh, ll in zip(h, l):
            seen_handles.setdefault(ll, hh)
    for ax in axes_flat[len(items):]:
        ax.axis("off")
    if seen_handles:
        fig.legend(seen_handles.values(), seen_handles.keys(),
                   loc="lower center", ncol=6, fontsize=7.5, frameon=False)
    fig.suptitle(sup, fontsize=12, fontweight="bold", y=0.98)
    fig.subplots_adjust(bottom=0.18 if nrows == 1 else 0.14, top=0.84 if nrows == 1 else 0.90,
                        hspace=0.34, wspace=0.22)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out_png)


def render_hierarchy_and_parasitics(out_png: Path) -> None:
    data = json.loads((REPO / "docs/data/layout_migrated_parasitics.json").read_text())
    fig = plt.figure(figsize=(16.5, 8.8), dpi=150)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.15, 1.0], wspace=0.22)

    # Left panel: Layout Hierarchy Tree (Top Macros -> Sub-blocks -> Migrated PDK Leaves vs Blocked)
    ax_h = fig.add_subplot(gs[0, 0])
    ax_h.set_xlim(0, 100)
    ax_h.set_ylim(0, 100)
    ax_h.axis("off")
    ax_h.set_title("Layout Hierarchy & Gemini4 Argon Migration Coverage", fontsize=11, fontweight="bold", pad=8)

    def box(x, y, w, h, text, fc, ec, lw=1.2, fs=8.0, bold=False):
        p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6", fc=fc, ec=ec, lw=lw)
        ax_h.add_patch(p)
        ax_h.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                  fontsize=fs, fontweight="bold" if bold else "normal", color="#0f172a")

    # Tier labels
    for x, t in [(10, "Level 1: Module"), (40, "Level 2: Sub-Block"), (76, "Level 3: PDK Leaf (DRC=0)")]:
        ax_h.text(x, 96, t, ha="center", va="center", fontsize=9, fontweight="bold", color="#334155")

    blocks = [
        # (mod_y, mod_h, mod_txt, sub_y, sub_txt, leaf_list, leaf_fc, leaf_ec)
        (68, 22, "PLL Subsystem\n(VCO + Divider)",
         [(79, "VCO Core & Bank", ["varactor_clean", "cap_unit_r6_pdk", "cap_bank5_shared",
                                   "vco_delay_r6_pdk", "buffer_r6_pdk"]),
          (67, "Divider Latch\n(cml_latch: DRC 168->0)", ["pll_cml_latch_pdk (9 ports)"])],
         "#dcfce7", "#15803d"),
        (24, 38, "Bias & Bandgap\n(bias_dist + bg)",
         [(53, "CTLE + Mirror Copies\n(DRC 10/9/33 -> 0)", ["serdes_bias_ctle_pdk", "serdes_bias_pcopy_pdk",
                                                            "serdes_bias_pcopy_n20_pdk", "serdes_bias_pcopy_n85_pdk"]),
          (38, "CP + CML + BG OTA\n(DRC 22/22/63 -> 0)", ["serdes_bias_cp_pdk", "serdes_bias_cml_pdk", "serdes_bg_ota_pdk"]),
          (26, "Blocked / Redesign\n(topology/model)", ["serdes_bg_amp (85), ref_vbuf (275)", "pll_pfd (70), cp_steer (315)"])],
         "#dbeafe", "#1d4ed8"),
        (6, 13, "LDO / Power\n(MIM Decap)",
         [(8, "PDK MIM Arrays\n(DRC -> 0)", ["serdes_ldo_mim16 / 50 / 100_pdk"])],
         "#fef3c7", "#b45309"),
    ]
    for my, mh, mtxt, subs, fc, ec in blocks:
        box(2, my, 18, mh, mtxt, fc, ec, lw=1.5, fs=8.5, bold=True)
        for sy, stxt, leaves in subs:
            is_blk = "Blocked" in stxt
            sfc = "#fee2e2" if is_blk else fc
            sec = "#b91c1c" if is_blk else ec
            box(26, sy, 26, 9.5, stxt, sfc, sec, lw=1.1, fs=7.4, bold=True)
            ax_h.plot([20.6, 25.4], [my + mh / 2, sy + 4.7], color="#64748b", lw=1.0)
            leaf_txt = "\n".join(leaves)
            box(58, sy - 0.5, 40, 10.5, leaf_txt, "#f8fafc" if not is_blk else "#fff1f2", sec, lw=0.9, fs=7.0)
            ax_h.plot([52.6, 57.4], [sy + 4.7, sy + 4.7], color="#64748b", lw=1.0)

    # Right panel: Extracted Parasitic Capacitance Summary (no simulation)
    ax_p = fig.add_subplot(gs[0, 1])
    names = [r["cell"].replace("serdes_", "").replace("pll_", "") for r in data]
    cgnd = [max(r["total_substrate_cap_fF"], 0.01) for r in data]
    ccoup = [max(r["total_coupling_cap_fF"], 0.01) for r in data]
    y_pos = list(range(len(names)))
    h_bar = 0.36
    ax_p.barh([y - h_bar / 2 for y in y_pos], cgnd, height=h_bar, color="#2563eb", alpha=0.85,
              label="Total Node-to-Substrate Cap Cgnd (fF)")
    ax_p.barh([y + h_bar / 2 for y in y_pos], ccoup, height=h_bar, color="#f59e0b", alpha=0.85,
              label="Total Inter-Node Coupling Cap Ccouple (fF)")
    ax_p.set_xscale("log")
    ax_p.set_yticks(y_pos)
    ax_p.set_yticklabels(names, fontsize=8.0)
    ax_p.invert_yaxis()
    ax_p.set_xlabel("Extracted Capacitance (fF, log scale)", fontsize=9)
    ax_p.set_title("Extracted Basic Parasitics (14 Migrated DRC=0 Leaves, No Sim)", fontsize=10.5, fontweight="bold", pad=8)
    ax_p.grid(True, axis="x", linestyle=":", alpha=0.6)
    ax_p.legend(loc="upper right", fontsize=8, frameon=True)
    for y, g, c in zip(y_pos, [r["total_substrate_cap_fF"] for r in data], [r["total_coupling_cap_fF"] for r in data]):
        mx = max(g, c, 0.01)
        ax_p.text(mx * 1.15, y, f"{g:.1f} / {c:.1f} fF", va="center", fontsize=6.8, color="#334155")
    ax_p.set_xlim(0.1, 4500)

    fig.suptitle("SerDes Gemini4 Argon Layout Migration — Hierarchy & Parasitic Overview (2026-11-13)",
                 fontsize=12.5, fontweight="bold", y=0.98)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out_png)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bias-run", type=Path, default=REPO / "results/layout/bias_pdk/run8")
    ap.add_argument("--divider-run", type=Path, default=REPO / "results/layout/divider_pdk/run3")
    args = ap.parse_args()

    out_dir = REPO / "docs/figures/layout"
    par = {r["cell"]: r for r in json.loads((REPO / "docs/data/layout_migrated_parasitics.json").read_text())}

    # 1. Layer-separated stack views across PLL, Bias, LDO
    render_layer_stack(
        REPO / "analog/pll/vco/layout/variants/r6_pdk/pll_vco_delay_r6_pdk.mag",
        "pll_vco_delay_r6_pdk",
        out_dir / "pll/pll_delay_layer_stack.png",
        "Layer Stack Separation — pll_vco_delay_r6_pdk (FEOL / MEOL / BEOL)",
    )
    render_layer_stack(
        args.divider_run / "pll_cml_latch_pdk/pll_cml_latch_pdk.mag",
        "pll_cml_latch_pdk",
        out_dir / "pll/pll_cml_latch_layer_stack.png",
        "Layer Stack Separation — pll_cml_latch_pdk (FEOL / MEOL / BEOL)",
    )
    render_layer_stack(
        args.bias_run / "serdes_bias_cp_pdk/serdes_bias_cp_pdk.mag",
        "serdes_bias_cp_pdk",
        out_dir / "bias/bias_cp_layer_stack.png",
        "Layer Stack Separation — serdes_bias_cp_pdk (Common-Centroid DN-MN-MN-DN + Xdp)",
    )
    render_layer_stack(
        REPO / "analog/common/ldo/layout/variants/mim_pdk/serdes_ldo_mim16_pdk.mag",
        "serdes_ldo_mim16_pdk",
        out_dir / "ldo/ldo_mim16_layer_stack.png",
        "Layer Stack Separation — serdes_ldo_mim16_pdk (16 x 1pF PDK MIM Array)",
    )

    # 2. Bias Migrated Grid Part 1 & Part 2
    def bias_sub(c_name: str, extra: str) -> str:
        r = par[c_name]
        return f"DRC {r['drc_boxes']} | LVS PASS | Csub {r['total_substrate_cap_fF']:.2f} fF | {extra}"

    render_grid(
        [
            ("serdes_bias_ctle_pdk (nfet_01v8_lvt 8/0.5)",
             args.bias_run / "serdes_bias_ctle_pdk/serdes_bias_ctle_pdk.mag",
             "serdes_bias_ctle_pdk", bias_sub("serdes_bias_ctle_pdk", "2 ports")),
            ("serdes_bias_pcopy_pdk (pfet_01v8_lvt 4x 6/4)",
             args.bias_run / "serdes_bias_pcopy_pdk/serdes_bias_pcopy_pdk.mag",
             "serdes_bias_pcopy_pdk", bias_sub("serdes_bias_pcopy_pdk", "3 ports")),
            ("serdes_bias_pcopy_n20_pdk (2x10 folding)",
             args.bias_run / "serdes_bias_pcopy_n20_pdk/serdes_bias_pcopy_n20_pdk.mag",
             "serdes_bias_pcopy_n20_pdk", bias_sub("serdes_bias_pcopy_n20_pdk", "3 ports")),
            ("serdes_bias_pcopy_n85_pdk (5x17 folding)",
             args.bias_run / "serdes_bias_pcopy_n85_pdk/serdes_bias_pcopy_n85_pdk.mag",
             "serdes_bias_pcopy_n85_pdk", bias_sub("serdes_bias_pcopy_n85_pdk", "3 ports")),
        ],
        out_dir / "bias/bias_pcopy_ctle_pdk.png",
        "Bias Distribution Migrated PDK Leaves — CTLE & Current-Mirror Copies",
        ncols=2,
    )
    render_grid(
        [
            ("serdes_bias_cp_pdk (DN-MN-MN-DN + Xdp)",
             args.bias_run / "serdes_bias_cp_pdk/serdes_bias_cp_pdk.mag",
             "serdes_bias_cp_pdk", bias_sub("serdes_bias_cp_pdk", "4 ports")),
            ("serdes_bias_cml_pdk (nfet 5/0.5 + 5x 1pF MIM)",
             args.bias_run / "serdes_bias_cml_pdk/serdes_bias_cml_pdk.mag",
             "serdes_bias_cml_pdk", bias_sub("serdes_bias_cml_pdk", "2 ports")),
            ("serdes_bg_ota_pdk (Xt + Xa/Xb + Xla/Xlb)",
             args.bias_run / "serdes_bg_ota_pdk/serdes_bg_ota_pdk.mag",
             "serdes_bg_ota_pdk", bias_sub("serdes_bg_ota_pdk", "6 ports")),
        ],
        out_dir / "bias/bias_cp_cml_ota_pdk.png",
        "Bias & Bandgap OTA Migrated PDK Leaves — CP / CML MIM5 / OTA",
        ncols=2,
    )

    # 3. Gemini Raw vs Migrated PDK Side-by-Side Comparisons
    render_grid(
        [
            ("Gemini4 Argon Raw: serdes_bias_pcopy_n20",
             REPO / "analog/common/bias/layout/serdes_bias_pcopy_n20.mag",
             "serdes_bias_pcopy_n20", "Hand-drawn | DRC=9 (mcon.2/licon.2/via.2) | 0 ports"),
            ("Migrated PDK: serdes_bias_pcopy_n20_pdk",
             args.bias_run / "serdes_bias_pcopy_n20_pdk/serdes_bias_pcopy_n20_pdk.mag",
             "serdes_bias_pcopy_n20_pdk", "2x10 pfet_01v8_lvt PCell | DRC=0 | LVS=PASS | 3 ports"),
        ],
        out_dir / "overview/gemini_vs_pdk_pcopy_n20.png",
        "Gemini4 Argon Raw vs PDK-Clean Migration — serdes_bias_pcopy_n20",
        ncols=2,
    )
    render_grid(
        [
            ("Gemini4 Argon Raw: pll_cml_latch",
             REPO / "analog/pll/divider/layout/pll_cml_latch.mag",
             "pll_cml_latch", "Hand-drawn | DRC=168 (LU.2/poly.7/li.3/licon.1c) | 0 ports"),
            ("Migrated PDK: pll_cml_latch_pdk",
             args.divider_run / "pll_cml_latch_pdk/pll_cml_latch_pdk.mag",
             "pll_cml_latch_pdk", "PDK FETs + 2x high_po_2p85 | DRC=0 | LVS=PASS | 9 ports"),
        ],
        out_dir / "pll/gemini_vs_pdk_cml_latch.png",
        "Gemini4 Argon Raw vs PDK-Clean Migration — pll_cml_latch",
        ncols=2,
    )

    # 4. Module Hierarchy & Extracted Parasitics Overview
    render_hierarchy_and_parasitics(out_dir / "overview/gemini_migration_hierarchy.png")


if __name__ == "__main__":
    main()
