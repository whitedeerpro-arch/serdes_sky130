#!/usr/bin/env python3
"""Generate multi-angle comparison figure for TSPC / SAFF-TSPC reclocked /8 prescaler study."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow.project import ROOT

OUT_FIG = ROOT / "docs/figures/clocking/dividers/tspc_reclock_multiangle.png"


def _latest(glob_pat: str) -> dict:
    paths = sorted(ROOT.glob(glob_pat))
    assert paths, f"Missing {glob_pat}"
    return json.loads(paths[-1].read_text())


def main() -> None:
    d_arch = _latest("results/analog/pll/divider/tspc_study/20261120_arch_cmp/corners/analysis/*/summary.json")
    d_v7 = _latest("results/analog/pll/divider/tspc_study/20261120_saff_v7/corners/analysis/*/summary.json")
    d_rip = _latest("results/analog/pll/divider/tspc_study/20261120_multiangle/ripple_kd/analysis/*/summary.json")
    d_shmoo = _latest("results/analog/pll/divider/tspc_study/20261120_multiangle/freq_shmoo/analysis/*/summary.json")
    d_pl_v1 = _latest("results/analog/pll/divider/tspc_study/20261120_saff_v6_postlayout/postlayout/analysis/*/summary.json")
    d_pl_v2 = _latest("results/analog/pll/divider/tspc_study/20261120_saff_v7_pdk_v2/postlayout/analysis/*/summary.json")

    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9.0))
    plt.rcParams["axes.grid"] = True

    # Panel A: Max inter-stage skew across 9 hard corners (schematic, driven by r5_pdk v6 CPEX)
    ax = axes[0, 0]
    corners_9 = [
        "tt_v1800_t27", "ss_v1650_t-40", "ss_v1650_t85",
        "fs_v1650_t85", "fs_v1650_t-40", "sf_v1650_t-40",
        "sf_v1650_t85", "ff_v1950_t85", "ff_v1950_t-40",
    ]
    short_lbl = ["TT", "SS-40", "SS85", "FS85", "FS-40", "SF-40", "SF85", "FF85", "FF-40"]
    x = np.arange(len(corners_9))
    w = 0.26

    def _get_sk(rows, arch, c):
        for r in rows:
            if r.get("arch") == arch and r.get("condition") == c:
                return r.get("skew_ps", {}).get("max_abs_interstage", np.nan)
        return np.nan

    sk_rip = [_get_sk(d_arch["rows"], "cmos_ripple", c) for c in corners_9]
    sk_s4 = [_get_sk(d_arch["rows"], "cmos_sync_s4", c) for c in corners_9]
    sk_v7 = [_get_sk(d_v7["rows"], "saff_reclock", c) for c in corners_9]

    ax.bar(x - w, sk_rip, width=w, label="Ripple C2MOS (91-259 ps)", color="#d95f02", alpha=0.85)
    ax.bar(x, sk_s4, width=w, label="Sync S4 C2MOS (1.5-18.2 ps)", color="#7570b3", alpha=0.90)
    ax.bar(x + w, sk_v7, width=w, label="SAFF-TSPC Reclock v7 (2.2-10.5 ps)", color="#1b9e77", alpha=0.95)
    ax.axhline(35.0, color="crimson", ls="--", lw=1.2, label="35 ps gate")
    ax.set_yscale("log")
    ax.set_ylim(1.0, 400.0)
    ax.set_xticks(x)
    ax.set_xticklabels(short_lbl, fontsize=8.5)
    ax.set_ylabel("Max Inter-Stage Skew |q4-q2, q8-q4, q8-q2| (ps)")
    ax.set_title("(a) Inter-Stage Phase Alignment Across 9 Hard Corners")
    ax.legend(fontsize=7.8, loc="upper right")
    ax.grid(True, which="both", alpha=0.28)

    # Panel B: Dynamic 20 MHz 40 mVpp Host-Rail Supply Sensitivity Kd_dyn (ps/mV)
    ax = axes[0, 1]
    kd_corners = ["tt_v1800_t27", "fs_v1650_t85", "ss_v1650_t-40"]
    kd_lbl = ["TT 1.8V 27C", "FS 1.65V 85C", "SS 1.65V -40C"]
    xk = np.arange(len(kd_corners))
    wk = 0.20
    arch_list = [
        ("cmos_ripple", "Ripple C2MOS", "#d95f02"),
        ("cmos_sync_s4", "Sync S4 C2MOS", "#7570b3"),
        ("tspc9_reclock", "9T-TSPC Reclock", "#e7298a"),
        ("saff_reclock", "SAFF-TSPC Reclock", "#1b9e77"),
    ]
    for idx, (ak, albl, col) in enumerate(arch_list):
        vals = []
        for kc in kd_corners:
            hit = [r["kd_dyn_ps_per_mv"] for r in d_rip["summary"] if r["arch"] == ak and r["corner"] == kc]
            vals.append(hit[0] if hit else np.nan)
        bars = ax.bar(xk + (idx - 1.5) * wk, vals, width=wk, label=albl, color=col, alpha=0.9)
        for b, v in zip(bars, vals):
            if np.isfinite(v):
                ax.text(b.get_x() + b.get_width() / 2, v + 0.015, f"{v:.2f}", ha="center", va="bottom", fontsize=7.2)
    ax.set_xticks(xk)
    ax.set_xticklabels(kd_lbl, fontsize=9)
    ax.set_ylabel("Dynamic Supply-to-Phase Sensitivity |Kd| (ps/mV)")
    ax.set_ylim(0, 1.10)
    ax.set_title("(b) Host-Rail 20 MHz 40 mVpp Ripple Sensitivity on q8 (250 MHz)")
    ax.legend(fontsize=7.8, loc="upper left")
    ax.grid(True, alpha=0.28)

    # Panel C: Frequency Shmoo at SS 1.65 V -40 C hh (Ideal clk 0.5-3.2 GHz)
    ax = axes[1, 0]
    freqs = [0.50, 1.00, 2.00, 2.50, 2.80, 3.20]
    for ak, albl, col, mk in [
        ("cmos_sync_s4", "Sync S4 C2MOS (fmax=2.50G)", "#7570b3", "s"),
        ("tspc9_reclock", "9T-TSPC Reclock (fails >=2.0G)", "#e7298a", "^"),
        ("saff_reclock", "SAFF-TSPC Reclock (fmax=2.80G)", "#1b9e77", "o"),
    ]:
        ys, xs = [], []
        for f in freqs:
            nm = f"{ak}__ss_v1650_t-40_id_{f:.2f}G"
            hit = [r for r in d_shmoo["rows"] if r["name"] == nm]
            if hit:
                r = hit[0]
                sk = r.get("skew_ps", {}).get("max_abs_interstage", np.nan)
                if r.get("counter", {}).get("bad_steps", 99) == 0 and np.isfinite(sk) and sk < 250:
                    xs.append(f)
                    ys.append(sk)
        ax.plot(xs, ys, marker=mk, lw=2.0, ms=7, label=albl, color=col)
    ax.axhline(35.0, color="crimson", ls="--", lw=1.2, label="35 ps gate")
    ax.axvline(2.0, color="gray", ls=":", lw=1.1, label="2.0 GHz nominal")
    ax.set_xlabel("Input Clock Frequency at SS 1.65 V -40 C hh (GHz)")
    ax.set_ylabel("Max Inter-Stage Skew (ps)")
    ax.set_xlim(0.4, 3.3)
    ax.set_ylim(0, 60)
    ax.set_title("(c) Worst-Case Speed Shmoo (SS 1.65 V -40 C hh)")
    ax.legend(fontsize=7.8, loc="upper left")
    ax.grid(True, alpha=0.28)

    # Panel D: Post-Layout CPEX & RCX Improvement (v1 75um bus vs v2 interleaved 2.5um)
    ax = axes[1, 1]
    pl_c = ["tt_v1800_t27", "fs_v1650_t85", "sf_v1650_t-40", "ff_v1950_t85", "ss_v1800_t85", "ss_v1650_t85", "ss_v1650_t-40"]
    pl_lbl = ["TT", "FS85", "SF-40", "FF85", "SS1.8", "SS85", "SS-40"]
    xp = np.arange(len(pl_c))
    wp = 0.25

    def _pl_val(d, mode, c):
        for r in d["rows"]:
            if r.get("arch") == mode and r.get("condition") == c:
                return r.get("skew_ps", {}).get("max_abs_interstage", np.nan)
        return np.nan

    v1_cpex = [_pl_val(d_pl_v1, "cpex", c) for c in pl_c]
    v2_cpex = [_pl_val(d_pl_v2, "cpex", c) for c in pl_c]
    v2_rcxb = [_pl_val(d_pl_v2, "rcxboth", c) if c in ("tt_v1800_t27","fs_v1650_t85","sf_v1650_t-40","ff_v1950_t85","ss_v1650_t-40") else _pl_val(d_pl_v2, "rcx", c) for c in pl_c]

    ax.bar(xp - wp, v1_cpex, width=wp, label="v1 CPEX (long 75 um M3)", color="#fdae61", alpha=0.9)
    ax.bar(xp, v2_cpex, width=wp, label="v2 CPEX (interleaved 2.5 um)", color="#2b83ba", alpha=0.95)
    ax.bar(xp + wp, v2_rcxb, width=wp, label="v2 RCX / RCX_BOTH (5/5 PASS)", color="#1b9e77", alpha=0.95)
    ax.axhline(35.0, color="crimson", ls="--", lw=1.2, label="35 ps gate")
    ax.set_xticks(xp)
    ax.set_xticklabels(pl_lbl, fontsize=8.5)
    ax.set_ylabel("Max Inter-Stage Skew (ps)")
    ax.set_ylim(0, 180)
    ax.set_title("(d) Post-Layout CPEX & RCX Skew: v1 vs v2 Interleaved Layout")
    ax.legend(fontsize=7.8, loc="upper left")
    ax.grid(True, alpha=0.28)

    fig.suptitle("Multi-Angle Phase, Supply Sensitivity, Speed & Post-Layout Study: Equalized Nikolic SAFF-TSPC /8 Prescaler", fontsize=12, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    OUT_FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_FIG, dpi=180)
    plt.close(fig)
    print(f"Saved {OUT_FIG}")


if __name__ == "__main__":
    main()
