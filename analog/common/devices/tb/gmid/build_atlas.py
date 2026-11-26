#!/usr/bin/env python3
"""Build unified 5-corner real-BSIM4 SKY130A gm/ID table & visual design atlas.

Merges the signed-off 4-corner (`tt, ss, ff, fs`) SKY130A BSIM4 device cards with
the newly characterized `sf` corner card into one unified `GmIdTable` bundle,
runs multi-corner CMOS clock-inverter, diff-pair, and current-mirror gm/ID sizing
benchmarks, and renders a 4-panel visual cheat-sheet (`sky130_gmid_atlas.png`).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / "src"))
from serdes_flow import gmid  # noqa: E402

CARD_BASE = REPO / "results/analog/common/devices/gmid_card"
DEFAULT_OUT = REPO / "results/analog/common/devices/gmid_atlas_20261125"


def find_latest_corner_dirs() -> list[Path]:
    """Find latest real BSIM4 DeviceCard directory for each of tt/ss/ff/fs/sf."""
    found: dict[str, Path] = {}
    for camp in sorted(CARD_BASE.iterdir()):
        if not camp.is_dir():
            continue
        for cn in ("tt", "ss", "ff", "fs", "sf"):
            d = camp / cn
            if (d / "card.json").exists() and (d / "card.npz").exists():
                found[cn] = d
    return [found[cn] for cn in ("tt", "ss", "ff", "fs", "sf") if cn in found]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    corner_dirs = find_latest_corner_dirs()
    corners_found = [d.name for d in corner_dirs]
    print(f"Merging {len(corner_dirs)} real BSIM4 SKY130A DeviceCards: {corners_found}")
    for d in corner_dirs:
        print(f"  - {d.relative_to(REPO)}")

    tbl = gmid.GmIdTable.from_device_card_dirs(corner_dirs, vsb=0.0)
    bundle_dir = tbl.save(out / "sky130a_5corner_bsim4")
    print(f"Saved unified GmIdTable ({len(tbl)} curves) -> {bundle_dir.relative_to(REPO)}")

    # 1. Multi-corner CMOS 2.5 GHz clock inverter tradeoff (including FS/SF skew corners!)
    inv_conds = [
        ("tt", 1.80, 27.0),
        ("ss", 1.65, -40.0),
        ("ss", 1.65, 85.0),
        ("ff", 1.95, -40.0),
    ]
    if "fs" in corners_found:
        inv_conds.append(("fs", 1.65, 85.0))
    if "sf" in corners_found:
        inv_conds.append(("sf", 1.65, -40.0))

    inv_specs = [
        ("nfet_lvt(0.15) + pfet(0.15)", dict(n_dev="nfet_lvt", p_dev="pfet", l_n=0.15, l_p=0.15)),
        ("nfet_lvt(0.15) + pfet_lvt(0.35)", dict(n_dev="nfet_lvt", p_dev="pfet_lvt", l_n=0.15, l_p=0.35)),
        ("nfet(0.15) + pfet(0.15)", dict(n_dev="nfet", p_dev="pfet", l_n=0.15, l_p=0.15)),
        ("nfet_lvt + Hybrid 70% pfet(0.15)/30% lvt(0.35)", dict(n_dev="nfet_lvt", p_dev="pfet", l_n=0.15, l_p=0.15, p_alt_dev="pfet_lvt", l_p_alt=0.35, p_alt_frac=0.30)),
        ("nfet_lvt + Hybrid 50% pfet(0.15)/50% lvt(0.35)", dict(n_dev="nfet_lvt", p_dev="pfet", l_n=0.15, l_p=0.15, p_alt_dev="pfet_lvt", l_p_alt=0.35, p_alt_frac=0.50)),
    ]
    inv_results = {}
    print("\n=== 5-Corner CMOS Clock Inverter Sizing (Real BSIM4 gm/ID) ===")
    for label, kw in inv_specs:
        res = gmid.size_cmos_inverter(tbl, conditions=inv_conds, **kw)
        inv_results[label] = res
        print(
            f"  {label:48s} | Wp/Wn={res['opt_wp_over_wn']:4.2f} | "
            f"max|dVM|={res['worst_abs_vm_err_mv']:5.1f} mV (span {res['vm_err_span_mv']:5.1f}) | "
            f"worst tau_FO1={res['worst_tau_fo1_ps']:5.2f} ps | worst fT={res['worst_ft_eff_ghz']:4.1f} GHz"
        )

    # 2. Direct diff-pair & current-mirror gm/ID benchmark checks
    dp_res = gmid.size_diff_pair(
        tbl, device_model="nfet_lvt", l_um=0.15,
        gm_target_s=10.5e-3, gmid_target=10.7,
        vdd_nom=1.80, v_in_cm=1.05, r_load_ohm=500.0, c_load_f=240e-15,
    )
    cm_res = gmid.size_current_mirror(
        tbl, device_model="nfet", l_um=0.5,
        id_target_a=2.0e-3, gmid_target=10.0, vds_min_v=0.40,
    )
    print(f"\nDiff-pair check (gm=10.5 mS, gm/Id=10.7, L=0.15): W={dp_res['w_total_um']} um ({dp_res['nf']}x{dp_res['w_finger_um']}), min_hr={dp_res['worst_headroom_mv']} mV, min_Av={dp_res['min_av_db']} dB")
    print(f"Tail mirror check (Id=2.0 mA, gm/Id=10.0, L=0.50): W={cm_res['w_total_um']} um ({cm_res['nf']}x{cm_res['w_finger_um']}), min_margin={cm_res['worst_compliance_margin_mv']} mV, min_ro={cm_res['min_ro_kohm']} kOhm")

    # 3. Render 4-panel visual atlas
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9.5), dpi=160)
    gm_grid = np.linspace(5.0, 21.0, 65)

    # Panel (a): f_T vs gm/ID (TT 27 C solid, SS 85 C dashed)
    ax = axes[0, 0]
    curves_a = [
        ("nfet_lvt", 0.15, "#2563eb", "nfet_lvt L=0.15"),
        ("nfet",     0.15, "#0891b2", "nfet L=0.15"),
        ("pfet",     0.15, "#dc2626", "pfet L=0.15"),
        ("pfet_lvt", 0.35, "#d97706", "pfet_lvt L=0.35 (PDK min)"),
        ("nfet_lvt", 0.50, "#64748b", "nfet_lvt L=0.50"),
    ]
    for dev, l_um, col, lbl in curves_a:
        for cn, tc, ls in (("tt", 27.0, "-"), ("ss", 85.0, "--")):
            xs, ys = [], []
            for g in gm_grid:
                try:
                    op = tbl.lookup(float(g), l_um, device_model=dev, corner=cn, temp_c=tc, vds_v=0.9, min_id_w=5e-8)
                    if op["id_w"] >= 5e-8:
                        xs.append(g); ys.append(op["ft_hz"] / 1e9)
                except ValueError:
                    pass
            ax.plot(xs, ys, color=col, ls=ls, lw=2.0 if ls == "-" else 1.5,
                    label=f"{lbl}" if ls == "-" else None)
    ax.set_yscale("log")
    ax.set_xlabel("gm/ID (S/A)"); ax.set_ylabel("f_T (GHz)")
    ax.set_title("(a) Transit Frequency f_T vs gm/ID  (solid: TT 27°C, dashed: SS 85°C)")
    ax.grid(True, which="both", alpha=0.25); ax.legend(fontsize=8.5, loc="upper right")

    # Panel (b): Speed-Power FOM (gm/Id * f_T) and Intrinsic Gain (gm/gds) at TT 27 C
    ax = axes[0, 1]
    ax2 = ax.twinx()
    for dev, l_um, col, lbl in [
        ("nfet_lvt", 0.15, "#2563eb", "nfet_lvt 0.15"),
        ("pfet",     0.15, "#dc2626", "pfet 0.15"),
        ("pfet_lvt", 0.35, "#d97706", "pfet_lvt 0.35"),
        ("nfet_lvt", 0.50, "#10b981", "nfet_lvt 0.50"),
    ]:
        xs, fom, av = [], [], []
        for g in gm_grid:
            try:
                op = tbl.lookup(float(g), l_um, device_model=dev, corner="tt", temp_c=27.0, vds_v=0.9, min_id_w=5e-8)
                if op["id_w"] >= 5e-8:
                    xs.append(g); fom.append(g * op["ft_hz"] / 1e9); av.append(op["gm_gds"])
            except ValueError:
                pass
        ax.plot(xs, fom, color=col, lw=2.0, label=f"{lbl} (FOM)")
        ax2.plot(xs, av, color=col, lw=1.3, ls=":", alpha=0.85)
    ax.axvspan(10.0, 13.0, color="#dbeafe", alpha=0.35, label="5G HS sweet spot (10-13 S/A)")
    ax.set_xlabel("gm/ID (S/A)")
    ax.set_ylabel("(gm/ID) · f_T  (GHz·S/A)  [solid]")
    ax2.set_ylabel("Intrinsic Gain gm/gds (V/V)  [dotted]")
    ax.set_title("(b) Speed-Power Efficiency Peak & Intrinsic Gain (TT 27°C, Vds=0.9V)")
    ax.grid(True, alpha=0.25); ax.legend(fontsize=8, loc="upper right")

    # Panel (c): Current density Id/W across ALL 5 corners (nfet_lvt 0.15 & pfet 0.15)
    ax = axes[1, 0]
    cn_colors = {"tt": "#0f172a", "ss": "#dc2626", "ff": "#2563eb", "fs": "#16a34a", "sf": "#9333ea"}
    for cn in corners_found:
        xs_n, ys_n, xs_p, ys_p = [], [], [], []
        for g in gm_grid:
            try:
                op = tbl.lookup(float(g), 0.15, device_model="nfet_lvt", corner=cn, temp_c=27.0, vds_v=0.9, min_id_w=5e-8)
                if op["id_w"] >= 5e-8:
                    xs_n.append(g); ys_n.append(op["id_w"] * 1e6)
            except ValueError:
                pass
            try:
                op = tbl.lookup(float(g), 0.15, device_model="pfet", corner=cn, temp_c=27.0, vds_v=0.9, min_id_w=5e-8)
                if op["id_w"] >= 5e-8:
                    xs_p.append(g); ys_p.append(op["id_w"] * 1e6)
            except ValueError:
                pass
        ax.plot(xs_n, ys_n, color=cn_colors[cn], lw=1.9, label=f"nfet_lvt {cn.upper()}")
        ax.plot(xs_p, ys_p, color=cn_colors[cn], lw=1.4, ls="--")
    ax.set_yscale("log")
    ax.set_xlabel("gm/ID (S/A)"); ax.set_ylabel("ID / W  (µA / µm)")
    ax.set_title("(c) 5-Corner Current Density ID/W  (solid: nfet_lvt 0.15, dashed: pfet 0.15)")
    ax.grid(True, which="both", alpha=0.25); ax.legend(fontsize=8.5, ncol=2, loc="upper right")

    # Panel (d): 5-Corner CMOS Clock Inverter Pareto (worst tau_FO1 vs worst |dVM|)
    ax = axes[1, 1]
    short_names = [
        "nLVT + pSVT(0.15)",
        "nLVT + pLVT(0.35)",
        "nSVT + pSVT(0.15)",
        "Hybrid 70/30",
        "Hybrid 50/50",
    ]
    cols_d = ["#2563eb", "#dc2626", "#0891b2", "#16a34a", "#9333ea"]
    offsets_d = [
        (10, 12),    # nLVT + pSVT(0.15)
        (-95, -42),  # nLVT + pLVT(0.35)
        (-138, 12),  # nSVT + pSVT(0.15)
        (16, 18),    # Hybrid 70/30
        (16, -24),   # Hybrid 50/50
    ]
    for (lbl, res), sname, col, oxy in zip(inv_results.items(), short_names, cols_d, offsets_d):
        x = res["worst_tau_fo1_ps"]
        y = res["worst_abs_vm_err_mv"]
        ax.scatter([x], [y], s=140, color=col, zorder=5, edgecolor="#111827", lw=1.0)
        ax.annotate(
            f"{sname}\nWp/Wn={res['opt_wp_over_wn']:.2f}, fT={res['worst_ft_eff_ghz']:.1f}G",
            (x, y), xytext=oxy, textcoords="offset points", fontsize=8.2, color=col, fontweight="bold",
            arrowprops=dict(arrowstyle="-", color=col, lw=0.9, alpha=0.75),
        )
    ax.set_xlabel("Worst-Corner Intrinsic FO1 Delay τ_FO1 (ps)  [lower = faster]")
    ax.set_ylabel("Worst-Corner |V_M − VDD/2| (mV)  [lower = tighter duty]")
    ax.set_title("(d) 5-Corner CMOS Clock Inverter Tradeoff (TT/SS/FF/FS/SF, Real BSIM4)")
    ax.grid(True, alpha=0.25)
    ax.set_xlim(10, 56)
    ax.set_ylim(75, 240)

    fig.suptitle(
        f"SKY130A Real-BSIM4 5-Corner gm/ID Design Atlas ({'/'.join(c.upper() for c in corners_found)}, -40..+85°C)",
        fontsize=13, fontweight="bold", y=0.995,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.975])
    png_path = out / "sky130_gmid_atlas.png"
    fig.savefig(png_path, bbox_inches="tight")
    print(f"\nSaved visual atlas -> {png_path.relative_to(REPO)}")

    summary = {
        "corners": corners_found,
        "source_cards": [str(d.relative_to(REPO)) for d in corner_dirs],
        "bundle_dir": str(bundle_dir.relative_to(REPO)),
        "atlas_png": str(png_path.relative_to(REPO)),
        "curve_count": len(tbl),
        "cmos_inverter_5corner": inv_results,
        "diff_pair_example": dp_res,
        "current_mirror_example": cm_res,
    }
    (out / "atlas_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Saved summary -> {(out / 'atlas_summary.json').relative_to(REPO)}")


if __name__ == "__main__":
    main()
