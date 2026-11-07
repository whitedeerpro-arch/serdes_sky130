"""Code and Vctrl per condition from a VCO working region, into config/pll_code_table.json.

    uv run python analog/pll/vco/tb/tuning/code_table.py <workmap campaign> [--vmin 0.9] [--headroom 0.45]

Among the codes that cross 2 GHz between the simulated Vctrl points, keeps those with Vctrl inside vmin .. VDD - headroom and takes the one with
the steepest local tuning, so the loop gain spreads less; if none is inside, the one nearest the window.  An open-loop operating point for benches
(linear between 250 mV points, so about 1 % in frequency): a bench that needs 2 GHz exactly measures its own period.
"""
import argparse
import json

import numpy as np

from serdes_flow.corners import Condition
from serdes_flow.project import ROOT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign")
    ap.add_argument("--vmin", type=float, default=0.9)
    ap.add_argument("--headroom", type=float, default=0.45)
    a = ap.parse_args()
    src = json.loads((ROOT / a.campaign / "summary.json").read_text())
    vs = src["vs"]
    out, inside = {}, 0
    for key, r in src["rows"].items():
        c = Condition.parse(key.split(":")[0])
        hi = c.supply - a.headroom
        options = []
        for k in r["usable"]:
            f = r["f"][str(k)]
            i = 0 if min(f[0], f[1]) <= 2e9 <= max(f[0], f[1]) else 1
            kv = (f[i + 1] - f[i]) / (vs[i + 1] - vs[i])
            options.append((k, vs[i] + (2e9 - f[i]) / kv, kv))
        ok = [o for o in options if a.vmin <= o[1] <= hi]
        inside += bool(ok)
        k, v, kv = max(ok, key=lambda o: o[2]) if ok else min(options, key=lambda o: max(a.vmin - o[1], o[1] - hi))
        out[key] = dict(code=k, vctrl=round(float(v), 3), kvco=round(float(kv)))
    kvs = np.array([x["kvco"] for x in out.values()]) / 1e6
    print(f"{len(out)} conditions, {inside} inside {a.vmin} V .. VDD - {a.headroom} V; Kvco {kvs.min():.0f}-{kvs.max():.0f} MHz/V, below 500: {(kvs < 500).sum()}, below 300: {(kvs < 300).sum()}")
    print("lowest:", sorted((v["kvco"] // 1000000, k, v["code"], v["vctrl"]) for k, v in out.items())[:5])
    (ROOT / "config/pll_code_table.json").write_text(json.dumps(dict(source=a.campaign, vs=vs, table=out), indent=1) + "\n")


if __name__ == "__main__":
    main()
