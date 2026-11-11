"""PFD from sky130_fd_sc_hd standard cells against the custom pll_pfd, with the k = 4 steering CP (layout choice, T3+).

    uv run python analog/pll/pfd/tb/pfd_cp_sc/run.py [--points tt_v1800_t27:1.15,...] [--variants custom,sc] [--workers 2]

Same bench and measurement as analog/pll/pfd/tb/pfd_cp_mc (net CP charge per 4 ns period over a phase list near zero,
CP output held at Vctrl, real bias), nominal models (no mismatch).  Variants of the PFD instance:
  custom  pll_pfd (analog/pll/pfd/spice/pfd_cmos.spice): two reset DFFs, NAND, two inverters with 5 fF each, AND with
          rst_b, output inverters 2/4 then 4/8 um
  sc      the same structure from library cells: dfrtp_1 x 2, nand2_1, inv_1 x 2 (no added capacitance), and2_1, output
          inv_2 then inv_4
  sc_dly  sc with the reset path lengthened by one dlygate4sd1_1 after the two inverters
  sc8     sc with stronger output inverters (inv_4 then inv_8; the custom output stage is 4 / 8 um regular-Vt)
The library netlists carry no junction areas (the custom cells' wrappers estimate them), so their delays are somewhat
optimistic until extraction.  Reported: dead-zone check (gain over +-5 ps / over +-40 ps), zero-charge phase, gain near
zero, UP / DN pulse width at zero phase.
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

_m = importlib.util.spec_from_file_location("pfd_cp_mc", ROOT / "analog/pll/pfd/tb/pfd_cp_mc/run.py")
pm = importlib.util.module_from_spec(_m)
_m.loader.exec_module(pm)
RESULTS = ROOT / "results/analog/pll/pfd/pfd_cp_sc"
SC_LIB = "/home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice"
SC = """.subckt pll_pfd_sc ref fb rst_b up dn vdd vss
Xup ref vdd clear_b vss vss vdd vdd qu sky130_fd_sc_hd__dfrtp_1
Xdn fb vdd clear_b vss vss vdd vdd qd sky130_fd_sc_hd__dfrtp_1
Xdetect qu qd vss vss vdd vdd request_b sky130_fd_sc_hd__nand2_1
Xd1 request_b vss vss vdd vdd rd1 sky130_fd_sc_hd__inv_1
Xd2 rd1 vss vss vdd vdd rd2 sky130_fd_sc_hd__inv_1
{dly}Xclear rst_b {rdx} vss vss vdd vdd clear_b sky130_fd_sc_hd__and2_1
Xub1 qu vss vss vdd vdd ub sky130_fd_sc_hd__inv_2
Xub2 ub vss vss vdd vdd up sky130_fd_sc_hd__inv_4
Xdb1 qd vss vss vdd vdd db sky130_fd_sc_hd__inv_2
Xdb2 db vss vss vdd vdd dn sky130_fd_sc_hd__inv_4
.ends pll_pfd_sc
"""
VARIANTS = {
    "custom": None,
    "sc": SC.format(dly="", rdx="rd2"),
    "sc_dly": SC.format(dly="Xd3 rd2 vss vss vdd vdd rd3 sky130_fd_sc_hd__dlygate4sd1_1\n", rdx="rd3"),
    "sc8": SC.format(dly="", rdx="rd2").replace("vdd ub sky130_fd_sc_hd__inv_2", "vdd ub sky130_fd_sc_hd__inv_4")
          .replace("vdd db sky130_fd_sc_hd__inv_2", "vdd db sky130_fd_sc_hd__inv_4")
          .replace("vdd up sky130_fd_sc_hd__inv_4", "vdd up sky130_fd_sc_hd__inv_8").replace("vdd dn sky130_fd_sc_hd__inv_4", "vdd dn sky130_fd_sc_hd__inv_8"),
}


def deck(c, vout, variant):
    text = pm.netlist(c, vout)
    text, n = re.subn(r'^(\.lib\s+"[^"]+"\s+)(\w+)_mm\s*$', lambda m: m[1] + m[2], text, count=1, flags=re.M)
    assert n == 1
    if VARIANTS[variant]:
        old = "Xpfd ref fb rst_b up dn vdd 0 pll_pfd"
        assert text.count(old) == 1
        text = text.replace(old, "Xpfd ref fb rst_b up dn vdd 0 pll_pfd_sc")
        last = max(i for i, l in enumerate(text.splitlines()) if l.lower().startswith(".include"))
        lines = text.splitlines()
        lines[last + 1:last + 1] = [f'.include "{SC_LIB}"'] + VARIANTS[variant].splitlines()
        text = "\n".join(lines) + "\n"
    ana, tend = pm.analysis(c)
    names = [f"q{i}" for i in range(len(pm.PHASES))] + ["upw", "dnw"]
    ctl = [".control", "set num_threads=1"] + ana.splitlines() + [f"echo RES {k} ${k}" for k in []] + \
          [f"print {' '.join(names)}", "quit", ".endc"]
    text = text.replace(".end\n", "") if text.rstrip().endswith(".end") else text
    return text + "\n".join(ctl) + "\n.end\n", tend


def parse(log):
    vals = {}
    for k, v in re.findall(r"^(q\d+|upw|dnw)\s*=\s*([-+0-9.eE]+)", log, re.M):
        vals[k] = float(v)
    return vals


def summarize(v):
    ph = np.array(pm.PHASES)
    q = np.array([v[f"q{i}"] for i in range(len(ph))])
    s = np.where(np.diff(np.sign(q)) > 0)[0]
    a, b = np.polyfit(ph, q, 1)
    zero = float(np.interp(0.0, q[s[0]:s[0] + 2], ph[s[0]:s[0] + 2])) if len(s) else float(-b / a)
    i5, j5 = pm.PHASES.index(-5e-12), pm.PHASES.index(5e-12)
    gain = (q[j5] - q[i5]) / 10e-12
    gout = (q[-1] - q[0]) / (ph[-1] - ph[0])
    return dict(zero_s=zero, gain_a=float(gain), gain_ratio=float(gain / gout), upw_s=v.get("upw"), dnw_s=v.get("dnw"),
                q_fc=[float(x * 1e15) for x in q])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="tt_v1800_t27:1.15,ss_v1650_t-40:1.0,ff_v1950_t85:1.3,ff_v1950_t-40:1.3,sf_v1650_t-40:1.0,"
                                        "fs_v1650_t85:1.15,ss_v1650_t85:1.0")
    ap.add_argument("--variants", default="custom,sc,sc_dly")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    specs, variants = a.points.split(","), a.variants.split(",")
    jobs = []
    for spec in specs:
        cond, v = spec.split(":")
        c = Condition.parse(cond)
        for var in variants:
            text, tend = deck(c, float(v), var)
            jobs.append((text, camp / cond / var, dict(timeout_s=1800, meta=dict(point=spec, variant=var))))
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    out = {}
    print("zero-charge phase ps | gain(+-5)/gain(+-40) | gain uA | UP / DN width ps at zero phase")
    for spec in specs:
        cond, _ = spec.split(":")
        line = f"{spec:20s}"
        for var in variants:
            log = (camp / cond / var / "simulator.log").read_text(errors="replace")
            v = parse(log)
            if len(v) < len(pm.PHASES) + 2:
                line += f" | {var}: missing"
                continue
            r = summarize(v)
            out.setdefault(spec, {})[var] = r
            line += (f" | {var}: {r['zero_s'] * 1e12:+6.1f} ps, ratio {r['gain_ratio']:.2f}, {r['gain_a'] * 1e6:4.0f} uA, "
                     f"UP {r['upw_s'] * 1e12:4.0f} / DN {r['dnw_s'] * 1e12:4.0f} ps")
        print(line, flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), phases=pm.PHASES, rows=out), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
