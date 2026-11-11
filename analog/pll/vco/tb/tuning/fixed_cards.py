"""4-bit VCO range ends with the layout-equivalent (fixed-width) high_po cards against the generic card.

    uv run python analog/pll/vco/tb/tuning/fixed_cards.py [--workers 2] [--resume C]

The circuit simulations map every resistor to the generic `sky130_fd_pr__res_high_po` (rcorner.to_pdk), whose resistor
corners are +-12.5 %.  Layout extracts fixed-width cards (rcorner.to_pdk_fixed: 2p85 for the CML loads, 1p41 for the
bandgap / r_ref), same value at tt / 27 C but about +-15 % (short loads +-17.5 %) at hh / ll and a different temperature
slope.  The 4-bit bank uses its whole range (docs/design/pll_vco.md: slow end FS 85 C hh at code 0, fast end SF -40 C ll
at code 15 with 7 mV to the 0.90 V window floor), so this checks the ends: same bench and measurement as workmap.py
(ring + four buffers, real bias, 24 ns, frequency over the last 5 ns) at the end codes, both mappings.  Prints f(Vctrl)
and the Vctrl of 2 GHz against the window [0.90 V, VDD - 0.44 V].
"""
import argparse
import importlib.util
import json
import time
import types

import numpy as np

from serdes_flow import rcorner
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_w = importlib.util.spec_from_file_location("workmap", ROOT / "analog/pll/vco/tb/tuning/workmap.py")
wm = importlib.util.module_from_spec(_w)
_w.loader.exec_module(wm)
RESULTS = ROOT / "results/analog/pll/vco/fixed_cards"
POINTS = {   # condition:rc -> (code, Vctrl list)
    "sf_v1650_t-40:ll": (15, [0.80, 0.90, 1.00, 1.10]),
    "sf_v1800_t-40:ll": (15, [0.90, 1.00, 1.10, 1.20]),
    "sf_v1950_t-40:ll": (15, [0.90, 1.05, 1.20, 1.35]),
    "sf_v1800_t27:ll": (15, [0.90, 1.05, 1.20, 1.35]),
    "fs_v1650_t85:hh": (0, [0.90, 1.00, 1.10, 1.21]),
    "fs_v1800_t85:hh": (0, [1.00, 1.15, 1.25, 1.36]),
    "fs_v1950_t85:hh": (0, [1.10, 1.27, 1.40, 1.51]),
}
MAPS = {"generic": rcorner.to_pdk, "fixed": rcorner.to_pdk_fixed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume")
    ap.add_argument("--scales", default="", help="also run the fixed cards with the bank unit capacitance scaled, e.g. 1.08,1.12 "
                                                  "(capw, capl x sqrt(s), switch W x s)")
    ap.add_argument("--sw-exp", type=float, default=1.0, help="switch W scales as s**sw_exp (1: same RC per unit)")
    a = ap.parse_args()
    scales = [float(x) for x in a.scales.split(",") if x]
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    todo = []
    for spec, (code, vs) in POINTS.items():
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        todo += [(rc, c, code, v) for v in vs]
    maps = dict(MAPS)
    base_deck = wm.deck
    for name, fn in MAPS.items():
        wm.rcorner = types.SimpleNamespace(to_pdk=fn)
        wm.run_points(camp / name, todo, a.workers, bank=4)
    for sc in scales:
        name = f"fixed_bank{sc:g}" + (f"_sw{a.sw_exp:g}" if a.sw_exp != 1 else "")
        maps[name] = None
        par = f"capw={2.35 * sc ** 0.5:.4f} capl={2.5 * sc ** 0.5:.4f} sw={2.5 * sc ** a.sw_exp:.4f}"

        def deck(*args, _par=par, **kw):
            t = base_deck(*args, **kw)
            old = "vbias vdd 0 pll_vco_ring4_4b"
            assert t.count(old) == 1
            return t.replace(old, f"{old} {_par}")
        wm.deck = deck
        wm.rcorner = types.SimpleNamespace(to_pdk=rcorner.to_pdk_fixed)
        wm.run_points(camp / name, todo, a.workers, bank=4)
    wm.deck, wm.rcorner = base_deck, rcorner
    out = {}
    for spec, (code, vs) in POINTS.items():
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        top = c.supply - 0.44
        row = {}
        line = f"{spec:18s} code {code:2d}, window [0.90, {top:.2f}] |"
        for name in maps:
            m = [wm.read(camp / name, rc, c, code, v) for v in vs]
            f = np.array([x[0] if x else np.nan for x in m])
            ok = np.isfinite(f)
            v2 = float(np.interp(2e9, f[ok], np.array(vs)[ok])) if ok.sum() >= 2 and (f[ok].min() <= 2e9 <= f[ok].max()) else float("nan")
            row[name] = dict(vctrl=vs, f=[float(x) for x in f], v_2g=v2)
            fs = " ".join(f"{x / 1e9:.4f}" for x in f)
            line += f" {name}: {fs} GHz -> 2 GHz at {v2:.3f} V |"
        g, x = row["generic"], row["fixed"]
        i = len(vs) // 2
        row["f_ratio_mid"] = x["f"][i] / g["f"][i]
        out[spec] = row
        print(line + f" fixed/generic f at {vs[i]:.2f} V: {row['f_ratio_mid']:.4f}", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(points=POINTS, rows=out), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
