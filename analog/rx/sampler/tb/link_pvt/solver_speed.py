"""Solver settings vs runtime and result on the sampler link bench (one case per setting, run together).

    uv run python analog/rx/sampler/tb/link_pvt/solver_speed.py [--cases ss_v1650_t85:4,tt_v1800_t27:20]

Settings: reltol 1e-4 / 1e-3 and transient tmax 4 ps / 8 ps (the bench default is 1e-4 / 4 ps).
The four settings of one case run concurrently, so they see the same machine load.  A setting is
acceptable if the decision stream is identical (same error count at a code on the edge of the
eye) and the clock / input-buffer swings agree within ~1 %.
"""
import argparse
import importlib.util
import json
import time
from pathlib import Path

from serdes_flow import eye, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_s = importlib.util.spec_from_file_location("sampler_pvt", ROOT / "analog/rx/sampler/tb/link_pvt/pvt.py")
sp = importlib.util.module_from_spec(_s)
_s.loader.exec_module(sp)
RESULTS = ROOT / "results/analog/rx/sampler/link_pvt_solver"
SETTINGS = {"ref": ("1e-4", "4p"), "rt1e-3": ("1e-3", "4p"), "tmax8p": ("1e-4", "8p"), "both": ("1e-3", "8p")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="ss_v1650_t85:4,tt_v1800_t27:20")
    ap.add_argument("--dut", default="ac")
    a = ap.parse_args()
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True)
    stim, _ = sp.replay.stimuli("rx_c2_far_nominal@ctle_rc")
    (camp / "stimuli.inc").write_text(stim)
    dut = sp.dut(a.dut)
    bits = eye.prbs7(sp.link.NBITS)
    rows = []
    for item in a.cases.split(","):
        tag, code = item.split(":")
        c, code = Condition.parse(tag), int(code)
        jobs = []
        for name, (rt, tmax) in SETTINGS.items():
            d = sp.deck([(c, code)], dut)
            assert d.count(".options reltol=1e-4") == 1 and d.count(f"{sp.link.SAVE_FROM:.4e} 4p") == 1
            d = d.replace(".options reltol=1e-4", f".options reltol={rt}").replace(
                f"{sp.link.SAVE_FROM:.4e} 4p", f"{sp.link.SAVE_FROM:.4e} {tmax}")
            jobs.append((d, camp / f"{tag}_c{code:02d}_{name}", dict(files={"stimuli.inc": camp / "stimuli.inc"}, timeout_s=1800,
                                                                     meta=dict(setting=name, reltol=rt, tmax=tmax))))
        for (_, run_dir, kw), ex in zip(jobs, spice.run_many(jobs, workers=4, smoke=False)):
            r = sp.analyse_case(run_dir / f"{sp.case_name(c, code)}.raw", c, code, bits)
            rows.append(dict(r, condition=tag, setting=kw["meta"]["setting"], elapsed_s=ex.elapsed_s))
            print(f"{tag} c{code:02d} {kw['meta']['setting']:7s}: {ex.elapsed_s:6.1f} s  errors {r['errors']:2d}  "
                  f"ck {r['ck_pp']*1e3:6.1f}  inbuf {r['inbuf_pp']*1e3:6.1f} mVpp", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(dut=dut, settings=SETTINGS, rows=rows), indent=1, default=float))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
