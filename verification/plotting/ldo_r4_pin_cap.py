"""Verify/publish the selected extra quiet-pin capacitance endpoint, no simulation."""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from ldo_r4 import ROOT, FIG, load, sha, span


def main(base_path, endpoint_path, crossed_path):
    base, bp = load(base_path)
    endpoint, ep = load(endpoint_path)
    crossed, cp = load(crossed_path)
    zero = [r for r in base["rows"] if r["ac"]]
    if len(zero) != 255 or len(endpoint["rows"]) != 255 or len(crossed["rows"]) != 170:
        raise ValueError("Unexpected boundary coverage")
    for p in (ep, cp):
        if p["extra_pin_capacitance_pf"] != 100 or p["parent_grid_sha256"] != sha(base_path):
            raise ValueError("Wrong capacitance or grid parent")
        if p["cell_sha256"] != bp["cell_sha256"]:
            raise ValueError("Different DUT")
    for rel, h in bp["cell_sha256"].items():
        if sha(ROOT / rel) != h: raise ValueError("Current DUT differs")
    key = lambda r: (r["mos"], r["rc"], r["hv_v"], r["host_v"], r["temp_c"], r["load_ma"])
    reference = {key(r): r for r in zero}
    combined = endpoint["rows"] + crossed["rows"]
    if len({key(r) for r in combined}) != 425:
        raise ValueError("Duplicate coordinates")
    dc_delta = []
    for row in combined:
        if not row["ac"] or len(row["crossings"]) != 1 or row["crossings"][0]["direction"] != "down":
            raise ValueError("Unexpected crossings")
        k = list(key(row)); k[1] = {"hl": "hh", "lh": "ll"}.get(k[1], k[1])
        original = reference[tuple(k)]
        if row["trim"] != original["trim"]: raise ValueError("Code retuned")
        dc_delta.append(abs(row["vout_v"] - original["vout_v"]))
    if max(dc_delta) > 1e-6:
        raise ValueError("Changing only capacitance moved DC output unexpectedly")
    fallback = sum((ROOT / r / "simulator.log").read_text().count("Transient op started") for r in {x["run"] for x in combined})
    if fallback: raise ValueError("AC operating point needs separate certification")
    rc_stats = {}
    for rc in ("ll", "tt", "hh", "hl", "lh"):
        rs = [r for r in combined if r["rc"] == rc]
        if len(rs) != 85: raise ValueError("Expected5MOS x17boundary conditions per RC")
        rc_stats[rc] = dict(pm_deg=[min(r["crossings"][0]["pm_deg"] for r in rs), max(r["crossings"][0]["pm_deg"] for r in rs)], psrr_20mhz_db=span(rs, "psrr_20mhz_db"))
    stats = dict(extra_pf=100, ac_points=425, per_rc=rc_stats,
                 pm_deg=[min(r["crossings"][0]["pm_deg"] for r in combined), max(r["crossings"][0]["pm_deg"] for r in combined)],
                 psrr_20mhz_db=span(combined, "psrr_20mhz_db"), max_dc_delta_v=max(dc_delta), optran_fallback_count=fallback)
    inputs = {k: dict(summary=str(p.relative_to(ROOT)), sha256=sha(p), campaign=d["campaign"]) for k, p, d in [("base", base_path, base), ("endpoint", endpoint_path, endpoint), ("crossed", crossed_path, crossed)]}
    cols = ["mos", "rc", "hv_v", "host_v", "temp_c", "load_ma", "trim", "vout_v", "psrr_20mhz_db", "run", "stem"]
    rows = [[r[c] for c in cols] + [r["crossings"][0]["hz"], r["crossings"][0]["pm_deg"]] for r in combined]
    data = dict(revision="hv18_r4", scope="Additional100pF ideal quiet-to-ground endpoint across5MOS x5RC x17boundary/nominal points. No pad/ESD/package/PEX, ESR sweep, intermediate-C interval or full startup/load qualification.", inputs=inputs, statistics=stats, columns=cols + ["crossing_hz", "pm_deg"], rows=rows, generator_sha256=sha(Path(__file__)))
    output = ROOT / "docs/data/ldo_r4_pin_cap.json"
    output.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    (ROOT / "results/catalog/ldo_r4_pin_cap.json").write_text(json.dumps(dict(data=str(output.relative_to(ROOT)), sha256=sha(output), inputs=inputs, statistics=stats), indent=2) + "\n")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), layout="constrained")
    for offset, rows_, label, color in [(-.12, zero, "No added C (255 points)", "#176c8c"), (.12, combined, "+100 pF (425 points)", "#d27732")]:
        for n, rc in enumerate(rc_stats):
            rs = [r for r in rows_ if r["rc"] == rc]
            if not rs: continue
            for ax, vals in [(axes[0], [r["crossings"][0]["pm_deg"] for r in rs]), (axes[1], [r["psrr_20mhz_db"] for r in rs])]:
                lo, hi = min(vals), max(vals)
                ax.errorbar(n + offset, (lo + hi) / 2, yerr=(hi - lo) / 2, fmt="none", color=color, lw=3, capsize=5, label=label if n == 0 else None)
    for ax in axes:
        ax.set_xticks(range(5), list(rc_stats)); ax.set_xlabel("PDK passive corner (first letter R, second C)"); ax.grid(alpha=.2); ax.legend(fontsize=8)
    axes[0].set(ylabel="Dual-injection phase margin (deg)", title="Full range over stated boundary points", ylim=(50, 90))
    axes[1].set(ylabel="20 MHz HV rejection (dB)", title="Same per-model code retained; real BG and R/MIM")
    fig.suptitle("HV18 r4 quiet pin: selected100pF endpoint, including crossed RC corners", fontsize=12)
    fig.savefig(FIG / "ldo_r4_pin_cap_pvt.png", dpi=160); plt.close(fig)
    print(json.dumps(dict(statistics=stats, inputs=inputs), indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--endpoint", type=Path, required=True)
    ap.add_argument("--crossed", type=Path, required=True)
    a = ap.parse_args()
    main(a.base.resolve(), a.endpoint.resolve(), a.crossed.resolve())
