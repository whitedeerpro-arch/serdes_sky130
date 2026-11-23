"""RX CTLE eye over PVT by replaying a recorded C2 far-end voltage (fast path of link_eye/pvt.py).

    uv run python analog/rx/ctle/tb/link_eye/replay.py record --from CAMPAIGN --tx nominal
    uv run python analog/rx/ctle/tb/link_eye/replay.py pvt [stress | all | tags...] --bc ID [--resume C] [--analyse-only]
    uv run python analog/rx/ctle/tb/link_eye/replay.py validate --replay C --link C

record:   registers the far-end voltage of the full-link TT run (EQ code 2) of CAMPAIGN as a
          boundary condition, with the CTLE input-stage signature as its load.
pvt:      the CTLE alone at every condition and EQ code, driven by the recorded voltage
          (legs = vcm +- diff/2); same eye analysis and gate as the full link.
validate: eye height / width differences replay - full link at the common cases.

The full link spends ~2 min per case in the 920-cell C2 model; the replay runs the CTLE only.
What the replay drops: the variation of the CTLE input capacitance with the RX corner, which
loads the channel end (checked by `validate`).
"""
import argparse
import importlib.util
import json
import shutil
import time
from pathlib import Path

import numpy as np

from serdes_flow import boundary, spice
from serdes_flow.corners import STRESS, Condition, grid45
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
_s = importlib.util.spec_from_file_location("link_pvt", HERE / "pvt.py")
link = importlib.util.module_from_spec(_s)
_s.loader.exec_module(link)
TEMPLATE = HERE / "tb_rx_ctle_far_replay_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/ctle/far_replay_pvt"
CTLE = ROOT / "analog/rx/ctle/spice/rx_ctle_rc.spice"
CONSUMER, INPUTS = "serdes_rx_ctle_rc", ("inp", "inn")
REC_CASE = ("tt_v1800_t27", 2)
PWL_TOL = 0.2e-3


def signature():
    return boundary.input_stage_signature(CTLE.read_text(), CONSUMER, INPUTS)


def simplify(t, y, tol=PWL_TOL):
    """Douglas-Peucker on a sampled waveform (indices kept)."""
    keep = np.zeros(len(t), bool)
    keep[[0, -1]] = True
    stack = [(0, len(t) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = y[a] + (y[b] - y[a]) * (t[a + 1:b] - t[a]) / (t[b] - t[a])
        i = int(np.argmax(np.abs(y[a + 1:b] - seg))) + a + 1
        if abs(y[i] - seg[i - a - 1]) > tol:
            keep[i] = True
            stack += [(a, i), (i, b)]
    return np.nonzero(keep)[0]


def record(campaign, tx):
    camp = ROOT / campaign
    meta = json.loads((camp / "summary.json").read_text())
    c, code = Condition.parse(REC_CASE[0]), REC_CASE[1]
    run = camp / c.process
    name = link.case_name(c, code)
    assert spice.has_waves(run, name), f"no {name} in {run}"
    ex = json.loads((run / "execution.json").read_text())
    bc_id = f"rx_c2_far_{meta['tx']}@ctle_rc"
    boundary.register(dict(
        id=bc_id, kind="recorded_node_voltage",
        description=f"Far-end differential voltage of C2_loss6 driven by the ideal '{meta['tx']}' TX "
                    f"({link.TX[meta['tx']]}), terminated 2 x 50 ohm to vcm {meta['vcm']} V and loaded by the "
                    f"real CTLE input at {REC_CASE[0]}, EQ code {code}; PRBS7, {link.NBITS} bits from t0 = {link.T0} s.",
        upstream=dict(module="verification/models/channel C2_loss6 + rx termination", revision="link_eye/pvt.py",
                      provenance=str(camp.relative_to(ROOT))),
        nodes={"rx_diff": "CTLE inputs rxp/rxn (legs vcm +- rx_diff/2)"},
        load=signature(),
        points={REC_CASE[0]: dict(condition=REC_CASE[0], run=str(run.relative_to(ROOT)), case=name, vcm=meta["vcm"],
                                  git_revision=ex.get("git_revision"), deck_sha256=ex.get("deck_sha256"))},
        processing=f"rx_diff resampled, Douglas-Peucker {PWL_TOL * 1e3} mV, held at its first saved value before "
                   f"{link.SAVE_FROM} s; common mode taken as vcm (AC-coupled link, CM noise dropped).",
        validation=None,
        valid_while=["CTLE input stage == load.sha (serdes_rx_ctle_rc inp/inn)", "termination 2 x 50 ohm to the same vcm",
                     "channel C2_loss6 and the ideal TX model unchanged"]))
    print("registered", bc_id)


def stimuli(bc_id):
    bc = boundary.get(bc_id)
    (point,) = bc["points"].values()
    w = spice.Waves(ROOT / point["run"] / f"{point['case']}.raw")
    t, d = w.t, w["rx_diff"]
    k = simplify(t, d)
    vcm = point["vcm"]
    pts = [(0.0, d[0])] + [(t[i], d[i]) for i in k]
    lines = []
    for leg, s in (("p", 0.5), ("n", -0.5)):
        lines.append(f"Vfar{leg} rx{leg} 0 PWL(" + " ".join(f"{a:.6e} {vcm + s * b:.6f}" for a, b in pts) + ")")
    return "\n".join(lines) + "\n", len(k)


def deck(cases):
    c0, code0 = cases[0]
    text = spice.render(TEMPLATE, **spice.corner_values(c0), EQ0_V=c0.supply * (code0 & 1),
                        EQ1_V=c0.supply * (code0 >> 1), CASES="@CASES@")
    blocks = []
    for c, code in cases:
        n = link.case_name(c, code)
        blocks.append("\n".join([f"* case {n}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}",
                                 f"alter Veq0 dc={c.supply * (code & 1)}", f"alter Veq1 dc={c.supply * (code >> 1)}",
                                 f"tran 2p {link.STOP:.4e} {link.SAVE_FROM:.4e} 4p",
                                 "let rx_diff=v(rxp)-v(rxn)", "let ctle_diff=v(op)-v(on)",
                                 "let ctle_cm=(v(op)+v(on))/2", "let pcore=-v(vdd)*i(Vdd)",
                                 f"write {n}.raw rx_diff ctle_diff ctle_cm pcore", "destroy all"]))
    return text.replace("@CASES@", "\n".join(blocks))


def pvt(conds, bc_id, resume=None, analyse_only=False):
    boundary.check_load(bc_id, signature())
    camp = (ROOT / resume) if resume else RESULTS / f"{bc_id.split('@')[0]}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    camp.mkdir(parents=True, exist_ok=True)
    stim, npts = stimuli(bc_id)
    (camp / "stimuli.inc").write_text(stim)
    bits = __import__("serdes_flow.eye", fromlist=["prbs7"]).prbs7(link.NBITS)
    keys = [(c, code) for c in conds for code in range(4)]
    by_proc = {}
    for k in keys:
        by_proc.setdefault(k[0].process, []).append(k)
    jobs = [(deck(cases), camp / proc, dict(files={"stimuli.inc": camp / "stimuli.inc"},
                                            meta=dict(process=proc, bc=bc_id, pwl_points=npts,
                                                      cases=[link.case_name(*k) for k in cases])))
            for proc, cases in by_proc.items()]
    todo = []
    for j in jobs:
        if (j[1] / "execution.json").exists():
            continue
        if j[1].exists() and not analyse_only:
            shutil.rmtree(j[1])
        todo.append(j)
    print(f"{len(keys)} cases in {len(jobs)} decks: {len(jobs) - len(todo)} kept, {len(todo)} to run", flush=True)
    for ex in ([] if analyse_only else spice.run_many(todo, workers=4, smoke=False)):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = [dict(condition=c.tag, eq=code, **link.analyse(camp / c.process, link.case_name(c, code), bits)) for c, code in keys]
    best = {}
    for r in rows:
        if r["condition"] not in best or r["height"] > best[r["condition"]]["height"]:
            best[r["condition"]] = r
    (camp / "summary.json").write_text(json.dumps(dict(bc=bc_id, rows=rows, best={k: v["eq"] for k, v in best.items()}),
                                                  indent=1, default=float))
    print(f"{'condition':15s} | CTLE eye per EQ code 0..3 (mV / UI) | best")
    for c in conds:
        rs = [r for r in rows if r["condition"] == c.tag]
        b = best[c.tag]
        print(f"{c.tag:15s} | " + "  ".join(f"{r['height']*1e3:5.0f}/{r['width']:.2f}" for r in rs)
              + f" | eq{b['eq']} {'ok' if b['ok'] else 'FAIL'}  CM {b['ctle_cm']:.2f} V  pp {b['ctle_pp']*1e3:.0f} mV")
    print(camp.relative_to(ROOT))
    return camp


def validate(replay_camp, link_camp):
    a = {(r["condition"], r["eq"]): r for r in json.loads((ROOT / replay_camp / "summary.json").read_text())["rows"]}
    b = {(r["condition"], r["eq"]): r for r in json.loads((ROOT / link_camp / "summary.json").read_text())["rows"]}
    common = sorted(set(a) & set(b))
    dh = [a[k]["height"] - b[k]["height"] for k in common]
    dw = [a[k]["width"] - b[k]["width"] for k in common]
    for k in common:
        print(f"{k[0]:15s} eq{k[1]}  replay {a[k]['height']*1e3:6.1f} mV/{a[k]['width']:.2f}  link {b[k]['height']*1e3:6.1f} mV/{b[k]['width']:.2f}")
    print(f"{len(common)} cases: height replay-link {min(dh)*1e3:+.1f}..{max(dh)*1e3:+.1f} mV, width {min(dw):+.2f}..{max(dw):+.2f} UI")
    return dict(cases=len(common), height_mv=(min(dh) * 1e3, max(dh) * 1e3), width_ui=(min(dw), max(dw)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("record", "pvt", "validate"))
    ap.add_argument("conds", nargs="*", default=["stress"])
    ap.add_argument("--from", dest="src")
    ap.add_argument("--tx", default="nominal")
    ap.add_argument("--bc")
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    ap.add_argument("--replay")
    ap.add_argument("--link")
    a = ap.parse_args()
    if a.step == "record":
        record(a.src, a.tx)
    elif a.step == "pvt":
        conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
        pvt(conds, a.bc, a.resume, a.analyse_only)
    else:
        validate(a.replay, a.link)


if __name__ == "__main__":
    main()
