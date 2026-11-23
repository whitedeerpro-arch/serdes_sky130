"""Loaded TX capture cell timing, real bias and PDK R; no serializer signoff.

uv run python analog/tx/serializer/tb/ingress_card/run.py [--conditions tags,...] [--workers 2] [--resume CAMPAIGN]

Both existing lean and reset CMOS DFFs drive actual CMOS/CML converters and
first-rank mux input devices. The mux output is a 5 fF proxy; clock pins see
ideal 30 ps ramps. Setup/hold apertures and physical clock fanout are unmeasured.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime, timezone

import numpy as np

from serdes_flow import bias, clock, rcorner, spice
from serdes_flow.corners import Condition, STRESS, boundary_first
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
STOP = 24e-9


def name(c, selected):
    return f"{c.tag}_{'selected' if selected else 'unselected'}.raw"


def deck(points, destination, smoke=False):
    c = points[0][0]
    blocks = []
    for cond, selected in points:
        blocks += [f"option temp={cond.temp}", f"alter Vdd dc={cond.supply}",
                   f"alter Vselect dc={-1 if selected else 1}",
                   f"tran 2p {1e-9 if smoke else STOP:.8e} 0 2p",
                   f"write {name(cond, selected)} v(d) v(clk_l) v(clk_r) v(q_l) v(q_r) v(cp_l) v(cn_l) v(cp_r) v(cn_r) v(vdd) i(Bcl) i(Bcr)",
                   "destroy all"]
    text = spice.render(HERE / "tb_ingress_ngspice.cir.in", **spice.corner_values(c), CASES="\n".join(blocks))
    if not smoke:
        # Every case starts from t=0; only save the relevant measurement interval.
        text = re.sub(r"^(tran \S+ \S+) 0 (\S+)$", r"\1 3n \2", text, flags=re.M)
    return bias.section(rcorner.to_pdk(bias.real(text), destination), c.process, "tt")


def measure(path):
    w = spice.Waves(path)
    if w.t[-1] < STOP * (1 - 1e-7):
        raise ValueError("truncated waveform")
    vdd = float(np.mean(w["vdd"]))
    rows = {}
    for cell, suffix, current in (("lean", "l", "bcl"), ("reset", "r", "bcr")):
        ck, q = w[f"clk_{suffix}"], w[f"q_{suffix}"]
        ds = w[f"cp_{suffix}"] - w[f"cn_{suffix}"]
        ce = clock.edges(w.t, ck - vdd / 2, start=4e-9, stop=22e-9)
        captures = []
        for e in ce:
            expected = bool(np.interp(e - .1e-9, w.t, w["d"]) > vdd / 2)
            polarity = 1 if expected else -1
            qe = clock.edges(w.t, q - vdd / 2, polarity, start=e, stop=e + 1e-9)
            de = clock.edges(w.t, ds, polarity, start=e, stop=e + 1e-9)
            qv = float(np.interp(e + 1e-9, w.t, q))
            dv = float(np.interp(e + 1e-9, w.t, ds))
            use = (w.t >= e - 60e-12) & (w.t <= e + 400e-12)
            charge = float(np.trapezoid(w[f"i({current})"][use], w.t[use]))
            captures.append(dict(clock_edge_s=float(e), expected=int(expected),
                                 tcq_s=float(qe[0] - e) if len(qe) else None,
                                 clock_to_cml_s=float(de[0] - e) if len(de) else None,
                                 q_sample_v=qv, cml_sample_v=dv,
                                 q_functional=bool(qv > .8 * vdd if expected else qv < .2 * vdd),
                                 cml_sign_correct=bool(dv > 0 if expected else dv < 0),
                                 clock_edge_charge_c=charge, clock_charge_equivalent_cap_f=abs(charge) / vdd))
        valid = len(captures) == 5 and all(x["tcq_s"] is not None and x["clock_to_cml_s"] is not None and x["q_functional"] and x["cml_sign_correct"] for x in captures)
        rows[cell] = dict(functional=valid, captures=captures,
                          tcq_min_ps=min((x["tcq_s"] * 1e12 for x in captures if x["tcq_s"] is not None), default=None),
                          tcq_max_ps=max((x["tcq_s"] * 1e12 for x in captures if x["tcq_s"] is not None), default=None),
                          clock_to_cml_min_ps=min((x["clock_to_cml_s"] * 1e12 for x in captures if x["clock_to_cml_s"] is not None), default=None),
                          clock_to_cml_max_ps=max((x["clock_to_cml_s"] * 1e12 for x in captures if x["clock_to_cml_s"] is not None), default=None))
    return rows


def summarize(camp, conds):
    rows = []
    for c in conds:
        for selected in (True, False):
            path = spice.case_output(camp, c.process, name(c, selected), STOP)
            row = dict(condition=c.tag, selected=selected, passive="tt", status="missing")
            if path:
                try:
                    row.update(status="measured", waveform=str(path.relative_to(ROOT)), metrics=measure(path))
                except (ValueError, KeyError) as error:
                    row.update(status="analysis_error", error=str(error))
            rows.append(row)
    result = dict(scope="Loaded ingress component card only; ideal 30ps clock pins, 2fF q wire, real bias/PDK R tt, 5fF first-mux output proxy; no setup/hold, fanout, mismatch or full serializer acceptance", rows=rows)
    temp = camp / "summary.json.tmp"
    temp.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    temp.replace(camp / "summary.json")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--conditions", help="comma-separated condition tags; default six STRESS conditions")
    p.add_argument("--workers", type=int, choices=(1, 2), default=2)
    p.add_argument("--resume", type=Path)
    a = p.parse_args()
    sources = [Path(__file__), HERE / "tb_ingress_ngspice.cir.in", ROOT / "src/serdes_flow/bias.py", ROOT / "src/serdes_flow/rcorner.py"]
    sources += list((ROOT / "analog/common/devices/spice").glob("*.spice"))
    sources += [ROOT / "analog/common/cmos_to_cml/spice/cmos_to_cml_data.spice", ROOT / "analog/common/cml_mux/spice/cml_lowov_cells.spice"]
    sources += [ROOT / x for x in bias.BIAS_INC]
    identity = {str(x.relative_to(ROOT)): hashlib.sha256(x.read_bytes()).hexdigest() for x in sources}
    camp = a.resume.resolve() if a.resume else ROOT / "results/analog/tx/ingress_card" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    camp.mkdir(parents=True, exist_ok=True)
    plan_file = camp / "plan.json"
    if plan_file.exists():
        plan = json.loads(plan_file.read_text())
        if plan["sources"] != identity or (a.conditions and a.conditions.split(",") != plan["conditions"]):
            raise ValueError("changed inputs; use a new campaign")
        conds = [Condition.parse(x) for x in plan["conditions"]]
    else:
        if a.resume:
            raise ValueError("no original plan to resume")
        conds = boundary_first([Condition.parse(x) for x in a.conditions.split(",")] if a.conditions else STRESS)
        plan_file.write_text(json.dumps(dict(conditions=[c.tag for c in conds], sources=identity, stop_s=STOP, workers=a.workers), indent=2) + "\n")
    print(camp, flush=True)
    groups = {}
    for c in conds:
        for selected in (True, False):
            if spice.case_output(camp, c.process, name(c, selected), STOP) is None:
                groups.setdefault(c.process, []).append((c, selected))
    if groups:
        c0 = conds[0]
        smoke = spice.run(deck([(c0, True)], camp / "snap/smoke", smoke=True), spice.next_run_dir(camp, "smoke"), timeout_s=120, meta=dict(stage="smoke", condition=c0.tag))
        if not smoke.ok or spice.case_output(camp, "smoke", name(c0, True), 1e-9) is None:
            raise RuntimeError(f"smoke failed: {smoke.run_dir}")
        jobs = [(deck(points, camp / "snap" / proc), spice.next_run_dir(camp, proc), dict(timeout_s=120 + 90 * len(points), meta=dict(cases=[(c.tag, s) for c, s in points]))) for proc, points in groups.items()]
        try:
            # An explicit, bounded same-DUT smoke has completed above.
            for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
                print(ex.run_dir.name, ex.exit_code, round(ex.elapsed_s, 1), flush=True)
        finally:
            summarize(camp, conds)
    result = summarize(camp, conds)
    print(json.dumps(dict(measured=sum(r["status"] == "measured" for r in result["rows"]), rows=len(result["rows"]),
                          functional=sum(r["status"] == "measured" and all(v["functional"] for v in r["metrics"].values()) for r in result["rows"]))), flush=True)


if __name__ == "__main__":
    main()
