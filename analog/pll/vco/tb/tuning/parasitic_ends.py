"""VCO slow / fast range ends with layout parasitics on the phase nodes (4-bit bank x1.15, fixed-width high_po cards).

    uv run python analog/pll/vco/tb/tuning/parasitic_ends.py [--variants sch:0,sch:8,...] [--ends slow] [--workers 2] [--resume C]

Same bench and measurement as workmap.py / fixed_cards.py (ring + four buffers, real bias, 24 ns, frequency over the
last 5 ns), cards rcorner.to_pdk_fixed.  A variant is <unit>:<Cpar fF>:
  unit  sch      schematic bank unit (cap_bank_3b.spice pll_vco_cap_unit, switch drain area w x 0.29 um)
        pex      the first extracted unit (analog/pll/vco/layout pll_vco_cap_unit_pex.spice, 2026-11-12 03:36): bottom-plate
                 route detoured 7 um around the MIM, plate-vss 2.76 fF, two floating m3 pieces
        compact  that extraction with the bottom plate kept to the MIM's own met3 (plate-vss 0.7 fF estimated from the
                 extracted met3 area / perimeter), floating m3 removed; MIM fringe node-plate 0.845 fF and drain area
                 1.34 um2 as extracted
        compact_nf2  compact with the switch as two fingers sharing the drain (drain area halved, 0.67 um2)
  Cpar  lumped capacitance from each of the eight phase nodes to ground for everything else the layout adds (ring wiring,
        delay-stage output, varactor and buffer-input wiring)
  optional :rload:wt  re-centring candidate (delay-stage load and tail width; constant swing needs wt ~ 8000 / rload)
Slow end FS 85 C hh code 0 (window top VDD - 0.44 V), fast end SF ll code 15 (window floor 0.90 V).
"""
import argparse
import importlib.util
import json
import re
import time
import types
from pathlib import Path

import numpy as np

from serdes_flow import rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_w = importlib.util.spec_from_file_location("workmap", ROOT / "analog/pll/vco/tb/tuning/workmap.py")
wm = importlib.util.module_from_spec(_w)
_w.loader.exec_module(wm)
RESULTS = ROOT / "results/analog/pll/vco/parasitic_ends"
ENDS = {
    "slow": {"fs_v1650_t85:hh": (0, [0.90, 1.00, 1.10, 1.21]),
             "fs_v1800_t85:hh": (0, [1.00, 1.15, 1.25, 1.36]),
             "fs_v1950_t85:hh": (0, [1.10, 1.27, 1.40, 1.51])},
    "fast": {"sf_v1650_t-40:ll": (15, [0.80, 0.90, 1.00, 1.10]),
             "sf_v1800_t-40:ll": (15, [0.90, 1.00, 1.10, 1.20]),
             "sf_v1950_t-40:ll": (15, [0.90, 1.05, 1.20, 1.35]),
             "sf_v1800_t27:ll": (15, [0.90, 1.05, 1.20, 1.35])},
}
NODES = [f"v{k}{s}" for k in range(4) for s in "pn"]
UNITS = {
    "sch": None,
    "pex": """.subckt pll_vco_cap_unit_alt node en vss params: capw=2 capl=2 sw=1
X0 node plate sky130_fd_pr__cap_mim_m3_1 l=2.68 w=2.52
X1 plate en vss vss sky130_fd_pr__nfet_01v8 ad=1.34 pd=6.36 as=1.34 ps=6.36 w=2.68 l=0.15
Rdc plate vss 1T
C0 plate en 0.02426f
C1 fa plate 0.33017f
C2 plate fb 0.47525f
C3 fa node 0.01989f
C4 node fb 0.02241f
C5 node plate 0.84466f
C6 plate vss 2.75873f
C7 fb vss 0.04497f
C8 fa vss 0.22404f
Rfa fa vss 1T
Rfb fb vss 1T
.ends
""",
    "compact": """.subckt pll_vco_cap_unit_alt node en vss params: capw=2 capl=2 sw=1
X0 node plate sky130_fd_pr__cap_mim_m3_1 l=2.68 w=2.52
X1 plate en vss vss sky130_fd_pr__nfet_01v8 ad=1.34 pd=6.36 as=1.34 ps=6.36 w=2.68 l=0.15
Rdc plate vss 1T
C0 plate en 0.02426f
C5 node plate 0.84466f
C6 plate vss 0.7f
.ends
""",
    "compact_nf2": """.subckt pll_vco_cap_unit_alt node en vss params: capw=2 capl=2 sw=1
X0 node plate sky130_fd_pr__cap_mim_m3_1 l=2.68 w=2.52
X1 plate en vss vss sky130_fd_pr__nfet_01v8 nf=2 ad=0.67 pd=3.18 as=1.34 ps=6.36 w=2.68 l=0.15
Rdc plate vss 1T
C0 plate en 0.02426f
C5 node plate 0.84466f
C6 plate vss 0.7f
.ends
""",
}


def patch(text, unit, cpar, rload, wt):
    if UNITS[unit]:
        # the includes point at the resistor-mapping snapshot copies; inline them with the unit renamed
        for f, n, extra in (("cap_bank_3b", 7, UNITS[unit]), ("cap_bank_4b", 15, "")):
            m = re.findall(r'^\.include "([^"]*/analog/pll/vco/spice/' + f + r'\.spice)"$', text, re.M)
            assert len(m) == 1, f
            body = Path(m[0]).read_text()
            assert body.count(" pll_vco_cap_unit capw=") == n
            text = text.replace(f'.include "{m[0]}"', extra + body.replace(" pll_vco_cap_unit capw=", " pll_vco_cap_unit_alt capw="))
    old = "vbias vdd 0 pll_vco_ring4_4b"
    assert text.count(old) == 1
    par = (f" rload={rload:g}" if rload else "") + (f" wt={wt:g}" if wt else "")
    add = "".join(f"\nCpar_{n} {n} 0 {cpar:g}f" for n in NODES) if cpar else ""
    i = text.index(old) + len(old)
    j = text.index("\n", i)
    return text[:i] + par + text[i:j] + add + text[j:]


def parse(var):
    """unit:cpar[:rload:wt]"""
    x = var.split(":")
    return x[0], float(x[1]), (float(x[2]) if len(x) > 2 else None), (float(x[3]) if len(x) > 3 else None)


def vdir(var):
    unit, cpar, rload, wt = parse(var)
    return f"{unit}_c{cpar:g}" + (f"_r{rload:g}_wt{wt:g}" if rload else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="sch:0,sch:8,sch:16,compact:0,compact:8,pex:0")
    ap.add_argument("--ends", default="slow")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume")
    a = ap.parse_args()
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    points = {k: v for e in a.ends.split(",") for k, v in ENDS[e].items()}
    todo = []
    for spec, (code, vs) in points.items():
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        todo += [(rc, c, code, v) for v in vs]
    wm.rcorner = types.SimpleNamespace(to_pdk=rcorner.to_pdk_fixed)
    variants = a.variants.split(",")
    jobs = []    # one deck per variant x MOS x passive corner, all variants in one pool
    for var in variants:
        unit, cpar, rload, wt = parse(var)
        vc = camp / vdir(var)
        groups = {}
        for rc, c, code, v in todo:
            if spice.case_output(vc, f"{c.process}_{rc}", wm.name(c, code, v), wm.STOP) is None:
                groups.setdefault((c.process, rc), []).append((c, code, v))
        for (p, rc), pts in groups.items():
            text = patch(wm.deck(p, rc, pts, vc / "snap" / f"{p}_{rc}", 4), unit, cpar, rload, wt)
            jobs.append((text, spice.next_run_dir(vc, f"{p}_{rc}"), dict(timeout_s=60 * len(pts) + 600, meta=dict(variant=var, process=p, passive=rc, points=len(pts)))))
    print(f"{len(jobs)} decks", flush=True)
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"deck {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    out = {}
    print("f at the window end (GHz, and % from 2 GHz: + = 2 GHz reachable), Vctrl of 2 GHz, margin to the window end (mV; + inside)")
    for spec, (code, vs) in points.items():
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        slow = code == 0
        end = c.supply - 0.44 if slow else 0.90
        line = f"{spec:18s} code {code:2d} |"
        for var in variants:
            m = [wm.read(camp / vdir(var), rc, c, code, v) for v in vs]
            f = np.array([x[0] if x else np.nan for x in m])
            ok = np.isfinite(f)
            v2 = float(np.interp(2e9, f[ok], np.array(vs)[ok])) if ok.sum() >= 2 and f[ok].min() <= 2e9 <= f[ok].max() else float("nan")
            fend = float(np.interp(end, np.array(vs)[ok], f[ok])) if ok.sum() >= 2 else float("nan")
            margin = (end - v2) if slow else (v2 - end)
            reach = (fend / 2e9 - 1) * (1 if slow else -1)
            out.setdefault(spec, {})[var] = dict(vctrl=vs, f=[float(x) for x in f], v_2g=v2, f_end=fend, margin_v=margin, reach=reach)
            line += f" {var}: {fend / 1e9:.4f} GHz ({reach * 100:+.1f}%), 2G at {v2:.3f} V ({margin * 1e3:+.0f} mV) |"
        print(line, flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), points=points, rows=out), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
