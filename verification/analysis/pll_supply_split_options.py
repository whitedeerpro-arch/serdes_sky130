"""Bounds for programmable LF splits, using the explicit 19-point supply fit.

Independent per-point tuning is an optimistic bound, not an implemented
calibration policy. No transistor simulation or design parameter update.
"""
import argparse
import json
from datetime import datetime, timezone

import numpy as np

from serdes_flow.project import ROOT
from pll_supply_choice import SEARCH, identity, module


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--search-summary", default=SEARCH)
    a = ap.parse_args()
    ss = module("trim_supply_split", "analog/pll/top/theory/supply_split.py")
    args = json.loads((ROOT / a.search_summary).read_text())["args"]
    others, inputs = [], [a.search_summary]
    for spec in args["other"].split(","):
        campaign, alpha = spec.rsplit(":", 1)
        path = campaign + "/summary.json"
        inputs.append(path)
        others.append((json.loads((ROOT / path).read_text())["rows"], float(alpha)))
    inputs += [campaign + "/summary.json" for campaign in args["base"].split(",")]
    fits = ss.fit(ss.rows(args["base"]), others, args["freq"])
    points = []
    for key, v in fits.items():
        h0 = ss.transfer(args["freq"], 0., v["cp"], v["cpv"], v["rz"], v["ci"])
        h1 = ss.transfer(args["freq"], 1., v["cp"], v["cpv"], v["rz"], v["ci"])
        base = v["kg"] + h0 * v["kl"]
        slope = (h1 - h0) * v["kl"]
        optimum = float(np.clip(-(base * slope.conjugate()).real / abs(slope) ** 2, 0., 1.))
        n = min(range(73), key=lambda n: abs(base + n / 72 * slope))
        points.append(dict(point=key, optimum_alpha=optimum,
                           optimal_k_hz_per_v=float(abs(base + optimum * slope)), trim_72=n,
                           trim_k_hz_per_v=float(abs(base + n / 72 * slope)),
                           base=[base.real, base.imag], slope=[slope.real, slope.imag]))
    def gain(point, alpha):
        return abs(complex(*point["base"]) + alpha * complex(*point["slope"]))
    n = min(range(73), key=lambda n: max(gain(p, n / 72) for p in points))
    groups = {}
    for p in points:
        process = p["point"].split("_")[0]
        rc = p["point"].split(":")[1]
        groups.setdefault(f"{process}:{rc}", []).append(p)
    grouped = []
    for group, rows in groups.items():
        code = min(range(73), key=lambda n: max(gain(p, n / 72) for p in rows))
        grouped.append(dict(group=group, points=len(rows), trim_72=code,
                            max_hz_per_v=float(max(gain(p, code / 72) for p in rows))))
    result = dict(inputs=[identity(p) for p in inputs],
                  code=[identity(__file__), identity("verification/analysis/pll_supply_choice.py"), identity("analog/pll/top/theory/supply_split.py")],
                  fixed_optimal_trim_72=n, fixed_max_hz_per_v=float(max(gain(p, n / 72) for p in points)),
                  independently_tuned_max_hz_per_v=max(p["optimal_k_hz_per_v"] for p in points),
                  quantized_independently_tuned_max_hz_per_v=max(p["trim_k_hz_per_v"] for p in points),
                  groupwise_bounds=grouped, points=points,
                  scope="Model-only optimistic bounds for the current 200 uA, 4.13 kohm, 18.38 pF network at 20 MHz",
                  limits=["19 fitted points only; no full PVT/RC/code or statistical coverage",
                          "Independent per-point alpha assumes knowledge of each operating condition; no calibration circuit or algorithm exists",
                          "Groupwise alpha also assumes knowledge of process and RC; group counts and missing conditions remain explicit",
                          "Does not include switch parasitics, noise, charge injection, multi-frequency optimum or sampled closed-loop response"])
    out = ROOT / "results/verification/pll_supply_split_options" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out.mkdir(parents=True)
    (out / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("Fixed", result["fixed_max_hz_per_v"] / 1e6, "independent", result["independently_tuned_max_hz_per_v"] / 1e6,
          "quantized", result["quantized_independently_tuned_max_hz_per_v"] / 1e6)
    print("Groupwise", [(g["group"], g["trim_72"], g["max_hz_per_v"] / 1e6) for g in grouped])
    print(out.relative_to(ROOT))


if __name__ == "__main__":
    main()
