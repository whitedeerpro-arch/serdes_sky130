"""Host supply -> VCO tail-bias line, small signal, in the regulated-rail partition (PLL closure step 7).

    uv run python analog/pll/vco/tb/bias_path_ac/run.py [--points tt_v1800_t27:tt,...] [--workers 2] [--resume C]

The psrr_lf `host` deck of each point (4-bit VCO + buffers at the code-table code, real loop filter, steering CP off,
bias reference and every PMOS current copy on node host, everything else on vdd), with the transient replaced by an
operating point and an AC sweep (1 kHz .. 100 MHz, 40 / decade) of host at 1 V: vbias / host (the VCO and buffer tail
line), vgi_bias / host (the PMOS copies' gate line) and vbg / host.  The VCO does not oscillate in the operating point;
the bias network does not depend on it.  The frequency-modulation side is not simulated here: the split psrr_lf runs at
4 MHz (results/analog/pll/vco/psrr_lf/20261110T091040Z) give K_host / (vbias / host) = 2.94 GHz/V (FS 1.95 V -40 C hh)
and 2.64 GHz/V (TT), both real to 0.1 deg: the host path is the tail-line ripple times a quasi-static kb.  Analysed by
analog/pll/top/theory/ldo_supply_tolerance.py.  No transient, so no smoke run.
"""
import argparse
import importlib.util
import json
import re
import time

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_p = importlib.util.spec_from_file_location("psrr_lf", ROOT / "analog/pll/vco/tb/psrr_lf/run.py")
pl = importlib.util.module_from_spec(_p)
_p.loader.exec_module(pl)
RESULTS = ROOT / "results/analog/pll/vco/bias_path_ac"
POINTS = ",".join(sorted(json.loads(pl.TABLE.read_text())["table"]))
VECS = ("vbias", "vgi_bias", "bias_vbg")


def deck(c, rc, code, vctrl, snap):
    text = pl.deck(c, rc, code, vctrl, "host", 4e6, 1e-3, 1e-7, snap)
    src = re.compile(rf"^Vhost host 0 DC {c.supply} SIN\(.*$", re.M)
    assert len(src.findall(text)) == 1
    text = src.sub(f"Vhost host 0 DC {c.supply} AC 1", text)
    text = re.sub(r"^\.save .*$", "", text, flags=re.M)
    i, j = text.index(".control"), text.index(".endc")
    ctl = ".control\nset num_threads=1\nop\nprint " + " ".join(f"v({v})" for v in VECS) + \
          "\nac dec 40 1e3 1e8\nwrdata ac.txt " + " ".join(f"v({v})" for v in VECS) + "\nquit\n"
    return text[:i] + ctl + text[j:]


def done(d):
    e = d / "execution.json"
    return e.exists() and (d / "ac.txt").exists() and json.loads(e.read_text()).get("exit_code") == 0


def read(d):
    """f and complex v / host per vector (wrdata: f, re, im per vector)."""
    x = np.loadtxt(d / "ac.txt")
    return x[:, 0], {v: x[:, 3 * k + 1] + 1j * x[:, 3 * k + 2] for k, v in enumerate(VECS)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default=POINTS)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume")
    a = ap.parse_args()
    table = json.loads(pl.TABLE.read_text())["table"]
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    plan = [(s, *s.split(":")) for s in a.points.split(",")]
    jobs = []
    for spec, cond, rc in plan:
        d = camp / f"{cond}_{rc}"
        if done(d):
            continue
        if d.exists():
            d = spice.next_run_dir(camp, f"{cond}_{rc}")
        row = table[spec]
        jobs.append((deck(Condition.parse(cond), rc, row["code"], row["vctrl"], camp / "snap" / f"{cond}_{rc}"), d,
                     dict(timeout_s=900, meta=dict(point=spec, code=row["code"], vctrl=row["vctrl"]))))
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}", flush=True)
    rows = {}
    show = (1e4, 1e5, 2e5, 3e5, 1e6, 4e6, 2e7)
    print("|vbias / host| mV/V at " + " ".join(f"{x / 1e6:g}" for x in show) + " MHz; |vgi / host| min")
    for spec, cond, rc in plan:
        good = sorted(d for d in camp.glob(f"{cond}_{rc}*") if d.is_dir() and done(d))
        if not good:
            continue
        f, v = read(good[-1])
        rows[spec] = dict(run=str(good[-1].relative_to(ROOT)), f=f.tolist(),
                          **{f"{n}_re": v[n].real.tolist() for n in VECS}, **{f"{n}_im": v[n].imag.tolist() for n in VECS})
        print(f"  {spec:18s} " + " ".join(f"{np.interp(x, f, abs(v['vbias'])) * 1e3:6.1f}" for x in show) +
              f"   {abs(v['vgi_bias']).min():.3f}", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows)))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
