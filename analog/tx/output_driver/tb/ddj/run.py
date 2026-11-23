"""Data-dependent jitter of the TX output stage alone: where the spread between the serializer output and the pad comes from.

    uv run python analog/tx/output_driver/tb/ddj/run.py [cond ...] [--variant name:k=v,k=v ...] [--edge 20e-12] [--pp 0.4]
    uv run python analog/tx/output_driver/tb/ddj/run.py --replay <bc id> [--points fs_v1650_t85,...] [--variant ...] [--allow-load-change]
    uv run python analog/tx/output_driver/tb/ddj/run.py --register <bc id> <full TX parallel_serializer campaign> ...

The DUT is serdes_tx_cml_line_driver_lowvt_enable with the full TX's 2 fF on qp/qn, pad (200 fF), package (0.3 ohm,
0.5 nH), AC coupling (10 nF), RLC16 channel and remote termination; real bias and PDK resistors (passive tt, as the
full-TX runs).  Two inputs:

* clean (default): the full-TX training + 256 payload bits with linear edges of --edge (0-100 %), --pp, common mode
  VDD - 0.12 V.  The stage's own data-dependent jitter.
* --replay: qp/qn of a registered full-TX run (config/boundary_conditions.json) as ideal voltage sources, PWL within
  0.2 mV.  The real serializer waveform, without its source impedance.  With the unchanged stage the pad and remote
  waveforms are compared with the full TX's (gate 5 mV over the sequence); a variant is measured only after that holds.

Both start balanced (qp = qn for 1 ns before the first value), so the AC coupling capacitors (1 us) hold no DC
differential, as in the full TX (remote mean within 7 mV of zero there).  Per node (input, isolation buffer output,
predriver output, pad, remote): spread on the UI grid and eye (serial.bit_mapping), training-phased margin and spread
(serial.check).  Variant keys: wiso wtiso riso wpre wtpre rpre wout wtout.  A variant that changes the isolation
buffer changes the load the replayed node was recorded with; it needs --allow-load-change and is marked so.
"""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, boundary, rcorner, serial, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings, simplify_pwl

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_ddj_ngspice.cir.in"
DRIVER = ROOT / "analog/tx/output_driver/spice/cml_line_driver_lowvt_enable.spice"
BUFFER = ROOT / "analog/common/cml_buffer/spice/cml_buffer.spice"
RESULTS = ROOT / "results/analog/tx/output_driver/ddj"
EXPECTED = ROOT / "analog/tx/serializer/tb/clock_states/serializer_expected.json"
UI = 250e-12
T0 = 2e-9
PAYLOAD = 256
NODES = ("input", "iso", "pre", "pad", "remote")
PWL_TOL_V = 2e-4
REPLAY_GATE_V = 5e-3
ISO_KEYS = ("wiso", "wtiso", "riso")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def driver_defaults():
    head = re.search(r"\.subckt\s+serdes_tx_cml_line_driver_lowvt_enable\b(.*?)\n(?!\+)", DRIVER.read_text(), re.S)[1]
    return dict(re.findall(r"(\w+)=(\S+)", head))


def input_load(params):
    """What qp/qn see: 2 fF each and the isolation buffer at its resolved size, with the cell files that define it."""
    p = {**driver_defaults(), **params}
    cut = (".subckt cut qp qn\nCqp qp 0 2f\nCqn qn 0 2f\n"
           f"Xiso qp qn ip in vbias vdd 0 serdes_cml_buffer wn={p['wiso']} wt={p['wtiso']} rload={p['riso']}\n.ends")
    sig = boundary.input_stage_signature(cut, "cut", ("qp", "qn"))
    return dict(**sig, cells={str(f.relative_to(ROOT)): sha(f) for f in (DRIVER, BUFFER)})


def load_changed(bc, params):
    """The resolved isolation buffer differs from the one the boundary was recorded with."""
    return input_load(params)["sha"] != bc["load"]["sha"]


def clean_bits():
    e = json.loads(EXPECTED.read_text())
    return [int(b) for b in e["bits"][: serial.TRAINING_BITS + PAYLOAD + 16]]


def balanced_start(cm, first, t_first, edge):
    return f"0 {cm:.5f} {t_first - 1e-9:.6e} {cm:.5f} {t_first - 1e-9 + edge:.6e} {first:.5f}"


def clean_stimuli(b, supply, pp, edge, cm_below=0.12):
    cm = supply - cm_below
    level = lambda x: (cm + (pp / 4 if x else -pp / 4), cm - (pp / 4 if x else -pp / 4))
    p, n = level(b[0])
    pts_p, pts_n = [balanced_start(cm, p, T0, edge)], [balanced_start(cm, n, T0, edge)]
    for k in range(1, len(b)):
        if b[k] != b[k - 1]:
            t = T0 + k * UI
            a, c = level(b[k - 1]), level(b[k])
            pts_p.append(f"{t - edge / 2:.6e} {a[0]:.5f} {t + edge / 2:.6e} {c[0]:.5f}")
            pts_n.append(f"{t - edge / 2:.6e} {a[1]:.5f} {t + edge / 2:.6e} {c[1]:.5f}")
    return pwl_lines("Vqp qp 0", pts_p) + pwl_lines("Vqn qn 0", pts_n)


def timed_stimuli(point, supply, pp, edge, cm_below):
    """Clean levels and linear edges, each centred on a crossing of the replayed qp - qn: its timing without its shape."""
    w = source_waves(point)
    y = w["qp"] - w["qn"]
    e, pol = crossings(w.t, y)
    cm = supply - cm_below
    hi, lo = (cm + pp / 4, cm - pp / 4), (cm - pp / 4, cm + pp / 4)
    first = hi if y[0] > 0 else lo
    pts_p, pts_n = [balanced_start(cm, first[0], w.t[0], edge)], [balanced_start(cm, first[1], w.t[0], edge)]
    for t, s in zip(e, pol):
        a, c = (lo, hi) if s > 0 else (hi, lo)
        pts_p.append(f"{t - edge / 2:.7e} {a[0]:.5f} {t + edge / 2:.7e} {c[0]:.5f}")
        pts_n.append(f"{t - edge / 2:.7e} {a[1]:.5f} {t + edge / 2:.7e} {c[1]:.5f}")
    return pwl_lines("Vqp qp 0", pts_p) + pwl_lines("Vqn qn 0", pts_n), float(w.t[-1])


def pwl_lines(head, pts):
    out = [f"{head} PWL("]
    for i in range(0, len(pts), 8):
        out.append("+ " + " ".join(pts[i:i + 8]))
    return "\n".join(out) + " )\n"


def source_waves(point):
    raw = ROOT / point["raw"]
    if sha(raw) != point["raw_sha256"]:
        raise ValueError(f"{raw}: changed since registration")
    return spice.Waves(raw)


def replay_stimuli(point):
    w = source_waves(point)
    t = w.t
    cm = float(w["qp"][0] + w["qn"][0]) / 2
    lines = ""
    for node in ("qp", "qn"):
        ts, ys = simplify_pwl(t, w[node], PWL_TOL_V)
        pts = [balanced_start(cm, ys[0], ts[0], 1e-9 - 1e-12)] + [f"{a:.7e} {v:.5f}" for a, v in zip(ts[1:], ys[1:])]
        lines += pwl_lines(f"V{node} {node} 0", pts)
    return lines, float(t[-1])


def register(bc_id, campaigns):
    points, revs = {}, set()
    for camp in campaigns:
        camp = (ROOT / camp).resolve()
        plan = json.loads((camp / "plan.json").read_text())
        summary = json.loads((camp / "summary.json").read_text())
        raw = camp / "run/waveforms.raw"
        revs.add((plan["clock_extra_2g"], plan["clock_output_wt"], plan["clock_output_r"]))
        points[plan["condition"]] = boundary.run_record(camp / "run", condition=plan["condition"], raw=str(raw.relative_to(ROOT)), raw_sha256=sha(raw),
                                                        summary_sha256=sha(camp / "summary.json"), plan_sha256=sha(camp / "plan.json"),
                                                        sequence_start_s=summary["sequence_start_s"], payload_bits=plan["payload_bits"])
    if len(revs) != 1:
        raise ValueError(f"campaigns differ in clock revision: {revs}")
    extra, wt, r = revs.pop()
    entry = dict(id=bc_id, kind="loaded_internal_port_voltage_replay",
                 description="Serializer output qp/qn of full-TX runs, replayed into the line driver alone (output-stage spread attribution).",
                 upstream=dict(module="tx.serializer", revision=f"extra2g={extra} clock_output wt={wt} r={r}", campaigns=[str((ROOT / c).resolve().relative_to(ROOT)) for c in campaigns]),
                 nodes=dict(inp="qp", inn="qn"), load=input_load({}),
                 processing=f"whole saved trace (from 8 ns), Douglas-Peucker PWL within {PWL_TOL_V * 1e3:.1f} mV; balanced (qp = qn = first common mode) until 1 ns before.",
                 validation=dict(state="per_run", waveform_error_gate_v=REPLAY_GATE_V, compared=["pad", "remote"]),
                 valid_while=["isolation buffer size and 2 fF qp/qn load unchanged (else --allow-load-change, recorded)",
                              "ideal voltage replay omits the serializer's source impedance: a changed stage input load does not feed back",
                              "unchanged-stage pad and remote within the gate of the full TX before variant conclusions",
                              "shared vbias kick-back from the clock and serializer tails is absent; it is part of what the gate checks"],
                 points=points)
    old = boundary.registry().get(bc_id)
    if old is None:
        boundary.register(entry)
    elif old != entry:
        raise ValueError(f"{bc_id} already registered with different content")
    print(f"{bc_id}: {sorted(points)}")


def deck(c, rc, params, cpad, lpkg, stop, camp):
    text = spice.render(TEMPLATE, **spice.corner_values(c), DRIVER=" ".join(f"{k}={v}" for k, v in params.items()), CPAD=cpad, LPKG=lpkg, STOP=f"{stop:.5e}")
    text = spice.skip_output_before(spice.binary_output(text), f"{T0 - 0.5e-9:.3e}")
    camp.mkdir(parents=True, exist_ok=True)
    return bias.section(rcorner.to_pdk(bias.real(text), camp), c.process, rc)


def analyse(w, seq):
    out = {}
    for node in NODES:
        y = w[node]
        m = serial.bit_mapping(w.t, y, seq)
        chk, _ = serial.check(w.t, y, seq, PAYLOAD)
        out[node] = dict(spread_ui=m["edge_spread_ui"], eye_v=m["eye_min_abs_v"], in_order=m["in_order"], margin_v=chk["minimum_signed_margin_v"],
                         check_spread_ui=chk["transition_spread_ui"], errors=chk["bit_errors"], functional=chk["functional"],
                         pp_v=float(np.ptp(y[w.t > seq.start_s + serial.TRAINING_BITS * seq.ui_s])))
    sel = w.t > seq.start_s
    out["power_w"] = float(np.mean(w["power"][sel]))
    return out


def replay_error(w, src, start):
    """Max |consumer - full TX| over the sequence, per compared node."""
    sel = src.t > start
    ts = src.t[sel]
    err = {}
    for node, (p, n) in dict(input=("qp", "qn"), pad=("lqp", "lqn"), remote=("lrp", "lrn")).items():
        ref = src[p][sel] - src[n][sel]
        err[node] = float(np.max(np.abs(np.interp(ts, w.t, w[node]) - ref)))
    return err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*")
    ap.add_argument("--register", metavar="BC_ID")
    ap.add_argument("--replay", metavar="BC_ID")
    ap.add_argument("--points", help="replay points, comma separated (default all)")
    ap.add_argument("--allow-load-change", action="store_true")
    ap.add_argument("--passive", default="tt")
    ap.add_argument("--variant", action="append", default=[])
    ap.add_argument("--edge", type=float, default=20e-12)
    ap.add_argument("--pp", type=float, default=0.4)
    ap.add_argument("--cm-below", type=float, default=0.12, help="clean input common mode below VDD, V")
    ap.add_argument("--timing-from", metavar="BC_ID", help="clean input with the crossing times of the replayed points")
    ap.add_argument("--cpad", default="200f")
    ap.add_argument("--lpkg", default="0.5n")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    if a.register:
        register(a.register, a.conds)
        return
    variants = {"r2": {}}
    for v in a.variant:
        name, kv = v.split(":", 1)
        variants[name] = dict(x.split("=") for x in kv.split(","))
    bc = None
    if a.replay and a.timing_from:
        raise ValueError("--replay or --timing-from, not both")
    if a.replay or a.timing_from:
        bc = boundary.get(a.replay or a.timing_from)
        conds = a.points.split(",") if a.points else sorted(bc["points"])
        if a.replay and (a.cpad != "200f" or a.lpkg != "0.5n" or a.passive != "tt"):
            raise ValueError("replay compares with the full TX: its pad, package and passive corner")
        for name, params in variants.items():
            if a.replay and load_changed(bc, params):
                boundary.check_load(a.replay, input_load(params), allow_mismatch=a.allow_load_change)
    else:
        conds = a.conds or ["fs_v1650_t85", "tt_v1800_t27", "ss_v1650_t-40"]
    mode = "replay" if a.replay else "timed" if a.timing_from else "clean"
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_{mode}" + a.tag)
    jobs, seqs = [], {}
    for tag in conds:
        c = Condition.parse(tag)
        if bc:
            point = bc["points"][tag]
            stim, stop = replay_stimuli(point) if a.replay else timed_stimuli(point, c.supply, a.pp, a.edge, a.cm_below)
            src = boundary.point_run(bc["id"], tag).parent / "summary.json"
            s = json.loads(src.read_text())
            if sha(src) != point["summary_sha256"]:
                raise ValueError(f"{tag}: source summary changed")
            words = [r["word"] for r in s["captures"] if r["payload_valid"]]
            seqs[tag] = serial.Sequence(np.array([(wd >> i) & 1 for wd in words for i in range(16)]), point["sequence_start_s"], UI)
        else:
            b = clean_bits()
            stim, stop = clean_stimuli(b, c.supply, a.pp, a.edge, a.cm_below), T0 + len(b) * UI
            seqs[tag] = serial.Sequence(np.asarray(b, dtype=int), T0, UI)
        for name, params in variants.items():
            d = camp / f"{tag}_{name}"
            d.mkdir(parents=True)
            (d / "stimuli.inc").write_text(stim)
            jobs.append((deck(c, a.passive, params, a.cpad, a.lpkg, stop, camp / "snap"), d / "run",
                         dict(files={"stimuli.inc": d / "stimuli.inc"}, timeout_s=3600,
                              meta=dict(condition=tag, passive=a.passive, variant=name, params=params, replay=a.replay, load_changed=bool(bc) and load_changed(bc, params),
                                        edge=None if a.replay else a.edge, pp=None if a.replay else a.pp, cm_below=None if a.replay else a.cm_below))))
    (camp / "plan.json").write_text(json.dumps(dict(mode=mode, replay=a.replay, timing_from=a.timing_from, cm_below=a.cm_below, boundary_sha256=hashlib.sha256(json.dumps(bc, sort_keys=True).encode()).hexdigest() if bc else None,
                                                    conds=conds, variants=variants, passive=a.passive, edge=a.edge, pp=a.pp, cpad=a.cpad, lpkg=a.lpkg,
                                                    sources={str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__).resolve(), TEMPLATE, DRIVER, BUFFER)}), indent=1))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    head = f"replay {a.replay}" if a.replay else (f"timing of {a.timing_from}, " if a.timing_from else "") + \
        f"clean input {a.pp * 1e3:.0f} mVpp, edges {a.edge * 1e12:.0f} ps, CM VDD - {a.cm_below * 1e3:.0f} mV"
    print(f"{head}; passive {a.passive}; spread UI / eye mV per node (bit_mapping); pad check margin mV; power mW")
    print(f"{'condition':15s} {'variant':10s} " + " ".join(f"{n:>11s}" for n in NODES) + f" {'pad mgn':>7s} {'pad pp':>6s} {'P mW':>5s}" + (" err pad/rem mV" if a.replay else ""))
    for tag in conds:
        for name in variants:
            p = camp / f"{tag}_{name}" / "run" / "waveforms.raw"
            if not p.exists():
                print(f"{tag:15s} {name:10s} missing", flush=True)
                continue
            w = spice.Waves(p)
            r = analyse(w, seqs[tag])
            if a.replay:
                r["replay_error_v"] = replay_error(w, source_waves(bc["points"][tag]), seqs[tag].start_s)
                r["replay_gate_v"] = REPLAY_GATE_V
                r["load_changed"] = load_changed(bc, variants[name])
            rows[f"{tag}:{name}"] = dict(params=variants[name], **r)
            line = f"{tag:15s} {name:10s} " + " ".join(f"{r[n]['spread_ui']:.3f}/{r[n]['eye_v'] * 1e3:4.0f}" for n in NODES) \
                + f" {r['pad']['margin_v'] * 1e3:7.1f} {r['pad']['pp_v'] * 1e3:6.0f} {r['power_w'] * 1e3:5.1f}"
            if a.replay:
                e = r["replay_error_v"]
                line += f" {e['pad'] * 1e3:6.1f}/{e['remote'] * 1e3:.1f}" + (" (load changed)" if r["load_changed"] else "")
            print(line, flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(mode=mode, replay=a.replay, timing_from=a.timing_from, rows=rows), indent=1, default=float))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
