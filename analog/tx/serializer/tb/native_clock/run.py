"""TX r2 clocked by the native PLL r4 frontend, with the start-state detector.

    uv run python analog/tx/serializer/tb/native_clock/run.py probe [points...]
    uv run python analog/tx/serializer/tb/native_clock/run.py data [points...]

The VCO runs open loop at a fixed Vctrl near 2 GHz (operating points of the
r3/r4 native checks).  The four serializer clocks come straight from the
frontend taps (250 MHz = branch-0 /8, 500 MHz = branch-2 /4, 1 GHz = branch-3
/2, 2 GHz = inverted b0); no idealised edge record.

probe: static data, 40 ns.  VCO frequency, 250 MHz falls at the distribution
       input, detector code, and clock phases at the serializer inputs
       relative to the 250 MHz fall (r2 targets 0 / 0.150 / 0.316 / 0.279 UI).
data:  word k is applied 78.3 ps after the k-th 250 MHz fall after settling, as
       in the r2 bench; the UI is the measured VCO half period.  With REMAP=s
       the words are pre-permuted for state s of the measured r2 tables.
       Checks the in-order contract and the order-free eye/mapping.
Environment: TRIMS="250,500,1g,2g" in fF (default r2: 100,500,160,270).
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

from serdes_flow import clock, serial, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
RESULTS = ROOT / "results/analog/tx/serializer/native_clock"
EXPECTED = ROOT / "analog/tx/serializer/tb/clock_states/serializer_expected.json"
PERMUTATIONS = ROOT / "digital/tx/tb/data/serializer_state_permutations.hex"
POINTS = {  # name: (condition, coarse code, Vctrl) from the r3/r4 native operating points
    "tt": ("tt_v1800_t27", 5, 1.1791930525417336),
    "ss_cold": ("ss_v1650_t-40", 5, 1.112),
    "ss_hot": ("ss_v1650_t85", 6, 1.32),
    "fs_hot": ("fs_v1650_t85", 5, 1.10),
}
# The FS 1.65 V 85 C /8 settles late (r3: final /8 only after ~34-38 ns).
SETTLE = {"fs_hot": 45e-9}
WORD_DELAY = 78.3e-12
WORDS = 13                       # 4 training + 8 payload + 1 guard


def trims():
    v = [float(x) * 1e-15 for x in os.environ.get("TRIMS", "100,500,160,270").split(",")]
    return dict(TRIM250=v[0], TRIM500=v[1], TRIM1G=v[2], TRIM2G=v[3])


def deck(name, stop, tstart):
    tag, code, vctrl = POINTS[name]
    c = Condition.parse(tag)
    d = spice.render(HERE / "tb_native_tx_ngspice.cir.in", **spice.corner_values(c), CODE=code, VCTRL=vctrl,
                     STOP=stop, MAX_STEP="4p", INITIAL_STATE="", TAIL_SCALE=6, WSF=80, WSELECT=96,
                     DRIVER_FILE="cml_line_driver_lowvt_enable.spice",
                     DRIVER_CELL="serdes_tx_cml_line_driver_lowvt_enable", DRIVER_PARAMS="wgatep=32", **trims())
    return spice.skip_output_before(spice.binary_output(d), tstart), c


def stimuli(edges, bits, remap=None):
    """PWL sources d0..d15: word k on input i is bits[16k + i], switching at edges[k].

    remap: permutation m (slot j carries input m[j]); input m[j] then carries bit j.
    """
    m = remap or list(range(16))
    lines = []
    for j in range(16):
        vals = [bits[16 * k + j] for k in range(len(edges))]
        pts = [f"0 {'{supply}' if vals[0] else 0}"]
        for k in range(1, len(edges)):
            if vals[k] != vals[k - 1]:
                a, b = ("{supply}", 0) if vals[k - 1] else (0, "{supply}")
                pts.append(f"{edges[k] - 10e-12:.14e} {a} {edges[k] + 10e-12:.14e} {b}")
        lines.append(f"Vd{m[j]} d{m[j]} 0 PWL({' '.join(pts)})")
    return "\n".join(lines) + "\n"


def _phases(w, t0, t1):
    ref = clock.edges(w.t, w["d250"], -1, t0, t1)
    ui = None
    out = {}
    for v in ("d250", "d500", "d1g", "latchclk"):
        e = {q: clock.edges(w.t, w[v], q, t0, t1) for q in (1, -1)}
        out[v] = {"rise" if q == 1 else "fall": e[q][np.searchsorted(e[q], ref[0])] - ref[0] for q in (1, -1)}
    return ref, out


def probe(names):
    camp = RESULTS / f"probe_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    bits = json.loads(EXPECTED.read_text())["bits"]
    static = stimuli([0.0], bits)          # word 0 held for the whole run
    jobs = []
    for n in names:
        d = camp / n
        d.mkdir(parents=True)
        (d / "stimuli.inc").write_text(static)
        settle = SETTLE.get(n, 30e-9)
        dk, _ = deck(n, f"{(settle + 10e-9) * 1e9:.0f}n", f"{(settle - 10e-9) * 1e9:.0f}n")
        jobs.append((dk, d / "run", dict(files={"stimuli.inc": d / "stimuli.inc"}, meta=dict(point=n, trims=trims()))))
    for ex in spice.run_many(jobs, workers=4):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    return analyse_probe(camp, names)


def analyse_probe(camp, names):
    rows = []
    for n in names:
        _, c = deck(n, "40n", "20n")
        settle = SETTLE.get(n, 30e-9)
        w = spice.Waves(camp / n / "run/waveforms.raw")
        t0, t1 = settle - 2e-9, settle + 10e-9
        f = clock.period_stats(w.t, w["pb0"], t0, t1)["frequency_hz"]
        ui = 0.5 / f
        falls = clock.edges(w.t, w["src250"], -1, t0)
        ref, ph = _phases(w, t0, t1)
        tail = w.t > settle + 2e-9
        code = [int(np.mean(w["bit" + b][tail]) > c.supply / 2) for b in "abc"]
        static_ok = all(np.ptp(w["bit" + b][tail]) < 0.2 * c.supply for b in "abc")
        row = dict(point=n, condition=c.tag, vco_hz=f, ui_s=ui, src250_falls_s=falls.tolist(), code=code,
                   code_static=static_ok, phase_ui={k: {e: x / ui for e, x in v.items()} for k, v in ph.items()},
                   trims=trims())
        rows.append(row)
        print(f"{n:8s} VCO {f/1e9:.5f} GHz  code {''.join(map(str, code))} static {static_ok}  phases [UI, ref d250 fall]: "
              + "  ".join(f"{k} r{v['rise']:.3f}/f{v['fall']:.3f}" for k, v in row["phase_ui"].items()), flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2, default=float))
    return camp


def _latest_probes():
    """Most recent probe result per point."""
    probes = {}
    for pcamp in sorted(RESULTS.glob("probe_*")):
        f = pcamp / "summary.json"
        if f.exists():
            for r in json.loads(f.read_text()):
                probes[r["point"]] = dict(r, campaign=str(pcamp))
    return probes


def data(names, remap_state=None):
    probes = _latest_probes()
    camp = RESULTS / f"data_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    exp = json.loads(EXPECTED.read_text())
    remap = None
    if remap_state is not None:
        rows = [l.split() for l in PERMUTATIONS.read_text().splitlines() if not l.startswith("//")]
        remap = [int(x, 16) for x in rows[remap_state]]
    jobs, meta = [], {}
    for n in names:
        p = probes[n]
        assert p["trims"] == trims(), "probe was run with other trims"
        period = 16 * p["ui_s"]
        first = [x for x in p["src250_falls_s"] if x > SETTLE.get(n, 30e-9)][0]
        edges = [first + WORD_DELAY + k * period for k in range(WORDS)]
        stop = edges[-1] + period
        d = camp / n
        d.mkdir(parents=True)
        (d / "stimuli.inc").write_text(stimuli(edges, exp["bits"], remap))
        dk, _ = deck(n, f"{stop * 1e9:.3f}n", f"{(edges[0] - 4e-9) * 1e9:.3f}n")
        jobs.append((dk, d / "run", dict(files={"stimuli.inc": d / "stimuli.inc"},
                                         meta=dict(point=n, trims=trims(), remap_state=remap_state, probe=p["campaign"]))))
        meta[n] = (edges[0], p["ui_s"])
    for ex in spice.run_many(jobs, workers=4):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    out = []
    for n in names:
        t0, ui = meta[n]
        seq = serial.Sequence(np.asarray(exp["bits"][: 16 * WORDS], dtype=int), t0, ui)
        w = spice.Waves(camp / n / "run/waveforms.raw")
        r = dict(point=n, remap_state=remap_state, ui_s=ui, nodes={})
        for node, vec in (("serializer", "dout"), ("pad", "line_tx"), ("far", "line_rx")):
            r["nodes"][node] = dict(contract=serial.check(w.t, w[vec], seq, 128)[0],
                                    order_free=serial.bit_mapping(w.t, w[vec], seq))
        s = r["nodes"]["serializer"]
        print(f"{n:8s} remap {remap_state}  eye {s['order_free']['eye_min_abs_v']*1e3:.1f} mV  spread "
              f"{s['order_free']['edge_spread_ui']:.3f} UI  far eye {r['nodes']['far']['order_free']['eye_min_abs_v']*1e3:.1f} mV  "
              f"{'IN ORDER' if s['order_free']['in_order'] else s['order_free']['mapping']}  "
              f"contract draft {serial.meets_draft(s['contract'])}", flush=True)
        out.append(r)
    (camp / "summary.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    step, names = sys.argv[1], sys.argv[2:] or list(POINTS)
    if step == "probe":
        probe(names)
    elif step == "reanalyse_probe":
        analyse_probe(sorted(RESULTS.glob("probe_*"))[-1], names)
    elif step == "data":
        rs = os.environ.get("REMAP")
        data(names, int(rs) if rs else None)
    else:
        sys.exit(f"unknown step {step}")
