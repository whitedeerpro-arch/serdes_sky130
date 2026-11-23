"""Boundary integration check: pll_sync_prescaler8_2stack inside pll_clock_frontend_r6q.

    uv run python analog/pll/top/tb/frontend_r6/run_sync2_cmp.py --workers 4

Compares the VCO + extraction buffers + prescaler + feedback receiver frontend across key PVT points
for three variants:
  r3_lean   baseline pll_clock_frontend_r6q (pll_cml_prescaler8 + wck=64 dummy)
  sync2_r3d pll_sync_prescaler8_2stack on b0 + existing wck=64 dummy on b1..3 (shows b0 unloading effect)
  sync2_eq  pll_sync_prescaler8_2stack on b0 + matched 20um diff-pair dummy on b1..3 (balanced 8-phase grid)

Note: Ikick on divider taps is DISABLED for sync2 variants to prove deterministic startup from Cseed=2f.
"""
import argparse
import importlib.util
import json
import re
import time

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_fr = importlib.util.spec_from_file_location("frontend_r6", ROOT / "analog/pll/top/tb/frontend_r6/run.py")
fr = importlib.util.module_from_spec(_fr)
_fr.loader.exec_module(fr)

RESULTS = ROOT / "results/analog/pll/top/frontend_r6_sync2"
SYNC2_INC = ROOT / "analog/pll/divider/spice/sync_prescaler8_2stack.spice"

SYNC2_DUMMY = """
* Matched input-capacitance dummy matching pll_sync_prescaler8_2stack Xckpre (wn=20 nfin=4 wt=12 nft=4 rload=850)
.subckt pll_sync2_dummy_load clkp clkn vbias vdd vss
Xdum clkp clkn outp outn vbias vdd vss sync2_buf wn=20 nfin=4 wt=12 nft=4 rload=850
.ends pll_sync2_dummy_load
"""


def build_deck(c: Condition, rc: str, code: int, vctrl: float, variant: str, camp):
    text, probes = fr.deck(c, rc, code, vctrl, "lean", camp)
    if variant == "r3_lean":
        return text, probes
    # Inject sync_prescaler8_2stack include and optional balanced dummy regardless of rcorner snapshot path
    text, n1 = re.subn(
        r'^(\.include\s+"[^"]*cml_prescaler8\.spice")',
        rf'\1\n.include "{SYNC2_INC}"',
        text,
        count=1,
        flags=re.M,
    )
    assert n1 == 1
    # Remove artificial Ikick pulses on d02/d04/d08 for sync2 to verify self-starting
    text = re.sub(r"^Ikickd0[248] .*\n", "", text, flags=re.M)
    # Build modified frontend subckt text inside deck snapshot
    fe = (ROOT / "analog/pll/top/spice/clock_frontend_r6q.spice").read_text()
    fe = fe.replace("pll_clock_frontend_r6q", "pll_clock_frontend_r6q_sync2")
    fe = fe.replace("pll_cml_prescaler8", "pll_sync_prescaler8_2stack")
    if variant == "sync2_eq":
        fe = fe.replace("pll_frontend_dummy_load wck={wck}", "pll_sync2_dummy_load")
        fe = SYNC2_DUMMY + "\n" + fe
    fe_path = camp / f"frontend_{variant}.spice"
    camp.mkdir(parents=True, exist_ok=True)
    fe_path.write_text(fe)
    text, n2 = re.subn(r'^\.include\s+"[^"]*clock_frontend_r6q\.spice"', f'.include "{fe_path}"', text, count=1, flags=re.M)
    assert n2 == 1
    text = text.replace("pll_clock_frontend_r6q", "pll_clock_frontend_r6q_sync2")
    return text, probes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--points",
        default="tt_v1800_t27:tt:12:1.1,fs_v1650_t85:hh:0:1.21,ss_v1650_t-40:hh:6:1.1,ff_v1950_t-40:ll:28:1.1,ff_v1950_t85:ll:28:1.1",
    )
    ap.add_argument("--variants", default="r3_lean,sync2_eq")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    a = ap.parse_args()
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)
    jobs, probes = [], {}
    for spec in a.points.split(","):
        cond, rc, code, v = spec.split(":")
        c = Condition.parse(cond)
        for var in a.variants.split(","):
            d = camp / f"{cond}_{rc}" / var
            text, probes[var] = build_deck(c, rc, int(code), float(v), var, camp / "snap")
            if spice.case_output(d, "run", "out.raw", fr.STOP) is None:
                jobs.append((text, spice.next_run_dir(d, "run"), dict(timeout_s=3600, meta=dict(point=spec, variant=var))))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    for spec in a.points.split(","):
        cond, rc, code, v = spec.split(":")
        for var in a.variants.split(","):
            p = spice.case_output(camp / f"{cond}_{rc}" / var, "run", "out.raw", fr.STOP)
            if p is None:
                print(f"{spec:28s} {var:9s} MISSING")
                continue
            m = fr.measure(p, probes[var])
            rows.setdefault(spec, {})[var] = m
            bd = np.array(m["buf_dev_s"])
            m["b0_late_s"] = float(bd[[0, 4]].mean() - bd[[1, 2, 3, 5, 6, 7]].mean())
            print(
                f"{spec:28s} {var:9s} f={m['f']/1e9:.4f}G VCO={np.mean(m['vco_swing'])*1e3:4.0f}mV grid=+-{np.max(np.abs(m['buf_dev_s']))*1e12:.2f}ps "
                f"buf={min(m['buf_swing'])*1e3:3.0f}-{max(m['buf_swing'])*1e3:3.0f}mV b0_late={m['b0_late_s']*1e12:+.2f}ps "
                f"fb_div={m['fb_ratio'] or 0:.4f} I_host={m['i_host']*1e3:.2f}mA",
                flush=True,
            )
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows), indent=1))
    print(camp.relative_to(ROOT), flush=True)


if __name__ == "__main__":
    main()
