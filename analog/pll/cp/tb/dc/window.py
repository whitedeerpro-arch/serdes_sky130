"""CP output window over 45 conditions x passive corners: where UP and DN still deliver their current.

    uv run python analog/pll/cp/tb/dc/window.py [--passive tt,hh,ll] [--droop 0.05] [--workers 4] [--analyse C]

tb_cp_dc_ngspice.cir.in, real bias, the CP at 50 uA (a scaled CP keeps its current density, so the window is the same).  DC sweep of the
output.  Window: around VDD / 2, UP and DN each within --droop of their current at VDD / 2.  UP / DN mismatch is reported apart and does
not bound the window: it is nearly constant over the output range (a bias copy offset, 11 % at SF 1.65 V -40 C ll from 0.6 to 1.2 V), and
in a PLL it gives a static phase offset and ripple, not a loss of charge.  One deck per MOS x passive corner.
"""
import argparse
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, spice
from serdes_flow.corners import grid45
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_cp_dc_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/cp/window"


def deck(process, rc, conds):
    text = spice.render(TEMPLATE, **{k: v for k, v in spice.corner_values(conds[0]).items()})
    text = re.sub(r"\.control.*?\.endc\n", "", text, flags=re.S)
    text = bias.section(bias.real(text), process, rc)
    lines = [".control", "set num_threads=1", "set filetype=binary"]
    for c in conds:
        lines += [f"option temp={c.temp}", f"alter Vdd dc={c.supply}", f"alter Vbias dc={c.supply}", f"dc Vout 0.1 {c.supply - 0.05:.3f} 0.01", f"write {c.tag}.raw i(Eu) i(Ed)", "destroy all"]
    text = text[: text.rindex(".end")]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def window(path, supply, droop):
    w = spice.Waves(path)
    v = w.t if hasattr(w, "t") else w["v(sweep)"]
    up, dn = np.abs(w["i(eu)"]), np.abs(w["i(ed)"])
    mid = int(np.argmin(np.abs(v - supply / 2)))
    ok = (np.abs(up / up[mid] - 1) <= droop) & (np.abs(dn / dn[mid] - 1) <= droop)
    lo = mid
    while lo > 0 and ok[lo - 1]:
        lo -= 1
    hi = mid
    while hi < len(v) - 1 and ok[hi + 1]:
        hi += 1
    return dict(lo=float(v[lo]), hi=float(v[hi]), up=float(up[mid]), dn=float(dn[mid]), mismatch=float(abs(up[mid] - dn[mid]) / ((up[mid] + dn[mid]) / 2)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passive", default="tt,hh,ll")
    ap.add_argument("--droop", type=float, default=0.05)
    ap.add_argument("--analyse", help="an existing campaign: analyse its sweeps, simulate nothing")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    camp = ROOT / a.analyse if a.analyse else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    groups = {}
    for rc in a.passive.split(","):
        for c in grid45():
            groups.setdefault((c.process, rc), []).append(c)
    jobs = [] if a.analyse else [(deck(p, rc, cs), camp / f"{p}_{rc}", dict(timeout_s=900, meta=dict(process=p, passive=rc))) for (p, rc), cs in groups.items()]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"deck {ex.run_dir.name}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    for (p, rc), cs in groups.items():
        for c in cs:
            f = camp / f"{p}_{rc}" / f"{c.tag}.raw"
            if f.exists():
                rows[f"{c.tag}:{rc}"] = dict(supply=c.supply, **window(f, c.supply, a.droop))
    print(f"{len(rows)} conditions; droop {a.droop}")
    for sup in (1.65, 1.8, 1.95):
        x = {k: v for k, v in rows.items() if v["supply"] == sup}
        i = max(x, key=lambda k: x[k]["lo"])
        j = min(x, key=lambda k: x[k]["hi"])
        print(f"VDD {sup}: lower edge at most {x[i]['lo']:.2f} V ({i}); upper edge at least {x[j]['hi']:.2f} V ({j}), VDD - {sup - x[j]['hi']:.2f}; current {min(v['up'] for v in x.values()) * 1e6:.1f}-{max(v['up'] for v in x.values()) * 1e6:.1f} uA")
    m = sorted(rows, key=lambda k: -rows[k]["mismatch"])[:4]
    print("largest UP / DN mismatch at VDD / 2:", [(k, f"{rows[k]['mismatch'] * 100:.1f} %") for k in m])
    (camp / "summary.json").write_text(json.dumps(dict(droop=a.droop, rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
