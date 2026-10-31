"""TX r2 driven by recorded native PLL r4 clocks (shape at the corner, position chosen).

The PLL r4 frontend taps that feed the TX clock distribution (p08 = 250 MHz,
p24 = 500 MHz, p32 = 1 GHz, pb0 inverted = 2 GHz) are recorded single-ended
at each corner by `native_clock/run.py record`.  One 250 MHz period of each
tap is cut at steady state, time-scaled to exactly 4 ns (the VCO runs open
loop slightly off 2 GHz) and replayed as a periodic PWL source (r=0) in the
r2 TX bench in place of the idealised TT edge record.  Data sources, circuit
and trims are the r2 ones, so the in-order contract applies.

Alignment ("position"), per clock, by the edge centroid: circular mean of the
rising crossings and of the falling crossings minus half a period, so duty
error does not move it.
  calibrated  each clock on the centroid of its r2 ideal source -> tests clock
              quality (amplitude, edge rate, CM) at the r2 positions, state (0,0)
  native      all four shifted together by the 250 MHz alignment -> keeps the
              native relative positions; validates the replay against the full
              native runs (bits permuted; order-free eye)
  target      each clock placed so that its position at the serializer input
              equals the r2 calibration run (ideal sources) at the same corner:
              a 28 ns pass measures the error, the 72 ns pass uses the
              corrected sources.  Needed when the distribution changes, since
              its delay depends on the clock shape.
  fixed       one delay per clock, the same at every corner (what a fixed
              routing/trim gives), derived from a target campaign (--from):
              minimax over corners, modulo a VCO cycle for the divided clocks.
              Shows whether the corner drift of the native positions fits.

    uv run python analog/tx/serializer/tb/clock_replay/run.py calibrated [points...]
    uv run python analog/tx/serializer/tb/clock_replay/run.py native [points...]
    uv run python analog/tx/serializer/tb/clock_replay/run.py target [points...] [--dist F] [--trims a,b,c,d] [--label L]
    uv run python analog/tx/serializer/tb/clock_replay/run.py fixed --from <target label> [same --dist/--trims]

Replay drops the loading interaction of the TX distribution input on the
frontend taps (the recorded voltages already include it); valid while the
distribution input stage is unchanged.
"""
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

from serdes_flow import serial, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = ROOT / "analog/tx/serializer/tb/lowov_optimization/tb_serializer_lowov_ngspice.cir.in"
R2_STIMULI = ROOT / "analog/tx/serializer/tb/clock_states/r2_stimuli.inc"
EXPECTED = ROOT / "analog/tx/serializer/tb/clock_states/serializer_expected.json"
RECORDS = ROOT / "results/analog/tx/serializer/native_clock"
RESULTS = ROOT / "results/analog/tx/serializer/clock_replay"
POINTS = {"tt": "tt_v1800_t27", "ss_cold": "ss_v1650_t-40", "ss_hot": "ss_v1650_t85", "fs_hot": "fs_v1650_t85"}
WORD = 4e-9
PERIOD = {"250": 4e-9, "500": 2e-9, "1g": 1e-9, "2g": 0.5e-9}
# clock -> (recorded p tap, recorded n tap, replayed p source/node, replayed n source/node)
CLOCKS = {"250": ("p08p", "p08n", "Vsrc250p s250p", "Vsrc250n s250n"),
          "500": ("p24p", "p24n", "Vsrc500p s500p", "Vsrc500n s500n"),
          "1g": ("p32p", "p32n", "Vsrc1gp s1gp", "Vsrc1gn s1gn"),
          "2g": ("pb0n", "pb0p", "Vsrc2gp s2gp", "Vsrc2gn s2gn")}
SAMPLES = 2000                                  # per 4 ns period: 2 ps
NODES = (("serializer", "dout"), ("pad", "line_tx"), ("far", "line_rx"))
ANALYSIS = (14e-9, 63e-9)                       # training start .. end of 128 payload bits


def centroid(t, y, period, t0=None, t1=None):
    """Edge centroid phase in [0, period): rises, and falls minus half a period."""
    e, pol = crossings(t, y)
    keep = np.ones(len(e), bool) if t0 is None else (e >= t0) & (e <= t1)
    ph = np.where(pol[keep] > 0, e[keep], e[keep] - period / 2) / period
    return float(np.angle(np.mean(np.exp(2j * np.pi * ph))) / (2 * np.pi) % 1.0) * period


def _pwl(line):
    """(t, v) of an r2 source line; values are {supply+-x} expressions, taken at supply = 0."""
    body = line.split("PWL(", 1)[1].rstrip(")").split()
    t = np.array([float(x) for x in body[0::2]])
    v = np.array([float(eval(x.strip("{}").replace("supply", "0"))) for x in body[1::2]])
    return t, v


def ideal_centroids():
    lines = {l.split(" ", 1)[0]: l for l in R2_STIMULI.read_text().splitlines()}
    out = {}
    for clk, (_, _, sp, sn) in CLOCKS.items():
        tp, vp = _pwl(lines[sp.split()[0]])
        tn, vn = _pwl(lines[sn.split()[0]])
        t = np.union1d(tp, tn)
        out[clk] = centroid(t, np.interp(t, tp, vp) - np.interp(t, tn, vn), PERIOD[clk], *ANALYSIS)
    return out


def latest_record():
    return sorted(RECORDS.glob("record_2*"))[-1]


def cut_period(run_dir):
    """One steady-state 250 MHz period of every tap, resampled onto [0, 4 ns)."""
    meta = json.loads((run_dir / "execution.json").read_text())      # run meta is stored flat
    w = spice.Waves(run_dir / "waveforms.raw")
    e, pol = crossings(w.t, w["p08p"] - w["p08n"])
    falls = e[(pol < 0) & (e > meta["settle_s"] + 3e-9)]
    a, b = falls[0], falls[1]
    grid = np.arange(SAMPLES) / SAMPLES
    taps = {x: np.interp(a + grid * (b - a), w.t, w[x]) for c in CLOCKS.values() for x in c[:2]}
    seam = max(abs(np.interp(b, w.t, w[x]) - taps[x][0]) for x in taps)
    return taps, dict(cut_from_s=float(a), native_period_s=float(b - a), seam_v=float(seam))


def tap_centroids(taps):
    t = np.arange(SAMPLES) / SAMPLES * WORD
    out = {}
    for clk, (p, n, _, _) in CLOCKS.items():
        d = taps[p] - taps[n]                    # two periods so no crossing is lost at the seam
        out[clk] = centroid(np.r_[t, t + WORD], np.r_[d, d], PERIOD[clk])
    return out


def source_shifts(taps, mode, ideal):
    native = tap_centroids(taps)
    return {clk: (ideal["250" if mode == "native" else clk] - native["250" if mode == "native" else clk])
            % PERIOD["250" if mode == "native" else clk] for clk in CLOCKS}


def replay_sources(taps, shift):
    t = np.arange(SAMPLES) / SAMPLES * WORD
    lines, kept = [], {}
    for clk, (p, n, sp, sn) in CLOCKS.items():
        for tap, src in ((p, sp), (n, sn)):
            y = np.interp((t - shift[clk]) % WORD, t, taps[tap], period=WORD)
            tc, yc = np.r_[t, WORD], np.r_[y, y[0]]
            k = simplify(tc, yc)
            kept[src.split()[0]] = len(k)
            pts = " ".join(f"{tc[i]:.5e} {yc[i]:.5f}" for i in k)
            lines.append(f"{src} 0 PWL({pts}) r=0")
    return lines, dict(shift_s=shift, pwl_points=kept, pwl_tolerance_v=PWL_TOL)


PWL_TOL = 0.3e-3


def simplify(t, y, tol=PWL_TOL):
    """Indices of a piecewise-linear subset within tol of every sample (Douglas-Peucker).

    Dense 2 ps breakpoints force the solver onto 2 ps steps (4x slower);
    flat stretches need few points, edges keep theirs."""
    keep = np.zeros(len(t), bool)
    keep[[0, -1]] = True
    stack = [(0, len(t) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        line = y[a] + (y[b] - y[a]) * (t[a + 1:b] - t[a]) / (t[b] - t[a])
        err = np.abs(y[a + 1:b] - line)
        i = int(np.argmax(err))
        if err[i] > tol:
            m = a + 1 + i
            keep[m] = True
            stack += [(a, m), (m, b)]
    return np.where(keep)[0]


def stimuli(taps, shift):
    clock_lines, info = replay_sources(taps, shift)
    data = [l for l in R2_STIMULI.read_text().splitlines() if re.match(r"Vd\d+ ", l)]
    return "\n".join(data + clock_lines) + "\n", info


R2_TRIMS = (100, 500, 160, 270)                 # fF: 250, 500, 1g, 2g
DIST_CELL = "analog/tx/clock_distribution/spice/cml_clock_distribution_tx_lowov.spice"


def deck(c, stop="72n", dist=None, trims=R2_TRIMS, **over):
    """r2 bench; dist = replacement file defining serdes_cml_clock_distribution_tx_lowov."""
    params = dict(STOP=stop, MAX_STEP="4p", TAIL_SCALE=6, WSF=80, WSELECT=96,
                  DRIVER_FILE="cml_line_driver_lowvt_enable.spice",
                  DRIVER_CELL="serdes_tx_cml_line_driver_lowvt_enable", DRIVER_PARAMS="wgatep=32")
    params.update(over)
    d = spice.render(TEMPLATE, **spice.corner_values(c), **params)
    old = ".param trim250=1e-13 trim500=5e-13 trim1g=1.6000000000000003e-13 trim2g=2.7e-13"
    assert old in d
    d = d.replace(old, ".param " + " ".join(f"trim{k}={v}f" for k, v in zip(("250", "500", "1g", "2g"), trims)))
    if dist:
        assert DIST_CELL in d
        d = d.replace(str(ROOT / DIST_CELL), str(Path(dist).resolve()))
    return spice.skip_output_before(spice.binary_output(d), "12n")


def analyse(run_dir, payload=128):
    seq = serial.Sequence.from_expected(json.loads(EXPECTED.read_text()))
    w = spice.Waves(run_dir / "waveforms.raw")
    res = {}
    for node, vec in NODES:
        contract, _ = serial.check(w.t, w[vec], seq, payload)
        res[node] = dict(contract=contract, order_free=serial.bit_mapping(w.t, w[vec], seq))
    return res


SER_VEC = {"250": "d250", "500": "d500", "1g": "d1g", "2g": "ds"}


def serializer_centroids(waves, t0, t1):
    return {clk: centroid(waves.t, waves[v], PERIOD[clk], t0, t1) for clk, v in SER_VEC.items()}


def wrap(x, period):
    return (x + period / 2) % period - period / 2


def target_centroids(name):
    """Serializer-input clock positions of the r2 calibration run (ideal sources) at this corner."""
    grid = sorted((ROOT / "results/analog/tx/serializer/clock_states").glob("grid_2*"))[-1]
    return serializer_centroids(spice.Waves(grid / f"{POINTS[name]}_s00" / "run/waveforms.tsv"), 20e-9, 60e-9)


def _run(camp, names, shifts, taps, stop, infos, opts):
    jobs = []
    for n in names:
        text, info = stimuli(taps[n], shifts[n])
        d = camp / n
        d.mkdir(parents=True)
        (d / "stimuli.inc").write_text(text)
        infos[n].update(info)
        jobs.append((deck(Condition.parse(POINTS[n]), stop, opts.get("dist"), opts.get("trims", R2_TRIMS)),
                     d / "run", dict(files={"stimuli.inc": d / "stimuli.inc"},
                                     meta=dict(point=n, **{k: str(v) for k, v in opts.items()}, **infos[n]))))
    for ex in spice.run_many(jobs, workers=4):
        assert ex.ok, (ex.run_dir, ex.log_failures)


VCO_CYCLE = 500e-12


def fixed_shifts(target_label, names, taps, ideal, opts, late=None):
    """One fixed delay per clock, the same at every corner, from a target campaign.

    d[n][k]: extra delay clock k needs at corner n relative to the native routing
    (all clocks moved by the 250 MHz alignment), taken modulo a VCO cycle for the
    divided clocks (whole cycles are divider start states, handled by the remap).
    F[k] is the minimax centre over the corners; the residual d - F is the position
    error a fixed setting leaves.  Sources are placed at target - residual, i.e.
    state (0, 0) with the fixed-setting position error, so bits stay in order.
    """
    tcamp = sorted(RESULTS.glob(f"{target_label}_2*"))[-1]
    rows = {r["point"]: r for r in json.loads((tcamp / "summary.json").read_text())}
    want = {k: str(v) for k, v in opts.items()}
    for n in names:
        assert rows[n]["opts"] == want, f"{tcamp.name} was run with {rows[n]['opts']}, not {want}"
    mod = {k: WORD if k == "250" else VCO_CYCLE for k in CLOCKS}
    d = {}
    for n in names:
        s_nat = source_shifts(taps[n], "native", ideal)["250"]
        d[n] = {k: wrap(rows[n]["replay"]["shift_s"][k] - s_nat, mod[k]) for k in CLOCKS}
    F = {}
    for k in CLOCKS:
        ph = np.array([d[n][k] for n in names]) / mod[k]
        c = float(np.angle(np.mean(np.exp(2j * np.pi * ph))) / (2 * np.pi)) * mod[k]
        r = [wrap(d[n][k] - c, mod[k]) for n in names]
        F[k] = c + (max(r) + min(r)) / 2 + (late or {}).get(k, 0.0)
    shifts, residual = {}, {}
    for n in names:
        residual[n] = {k: wrap(d[n][k] - F[k], mod[k]) for k in CLOCKS}
        shifts[n] = {k: (rows[n]["replay"]["shift_s"][k] - residual[n][k]) % WORD for k in CLOCKS}
    info = dict(target_campaign=str(tcamp.relative_to(ROOT)), fixed_delay_vs_native_s=F, late_s=late or {})
    return shifts, residual, info


def campaign(mode, names, target_label=None, late=None, **opts):
    """mode: calibrated | native | target (serializer-input positions = r2 calibration run)
    | fixed (one delay per clock for all corners, from a target campaign)."""
    rec = latest_record()
    ideal = ideal_centroids()
    label = opts.pop("label", None) or mode
    camp = RESULTS / f"{label}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    taps, infos, shifts = {}, {}, {}
    for n in names:
        taps[n], cut = cut_period(rec / n / "run")
        infos[n] = dict(record=str(rec.relative_to(ROOT)), cut=cut, mode=mode)
        shifts[n] = source_shifts(taps[n], "native" if mode == "native" else "calibrated", ideal)
    if mode == "fixed":
        shifts, residual, info = fixed_shifts(target_label, names, taps, ideal, opts, late)
        for n in names:
            infos[n].update(info, position_residual_s=residual[n])
            print(f"{n:8s} fixed-setting residual " + "  ".join(f"{k} {residual[n][k] / 250e-12:+.3f}" for k in CLOCKS)
                  + " UI", flush=True)
    if mode == "target":
        # Short run at the calibrated source positions, then move each source by the
        # serializer-input error.  Distribution delay depends on the clock shape, so
        # aligning at the source is not enough once the distribution changes.
        _run(camp / "pass1", names, shifts, taps, "28n", {n: dict(infos[n]) for n in names}, opts)
        for n in names:
            got = serializer_centroids(spice.Waves(camp / "pass1" / n / "run/waveforms.raw"), 14e-9, 28e-9)
            want = target_centroids(n)
            err = {k: wrap(got[k] - want[k], PERIOD[k]) for k in CLOCKS}
            infos[n]["pass1_error_s"] = err
            shifts[n] = {k: (shifts[n][k] - err[k]) % WORD for k in CLOCKS}
    _run(camp, names, shifts, taps, "72n", infos, opts)
    rows = []
    for n in names:
        w = spice.Waves(camp / n / "run/waveforms.raw")
        r = analyse(camp / n / "run")
        got = serializer_centroids(w, 20e-9, 60e-9)
        want = target_centroids(n)
        pos = {k: wrap(got[k] - want[k], PERIOD[k]) / 250e-12 for k in CLOCKS}
        amp = {k: float(np.ptp(w[v][(w.t > 20e-9) & (w.t < 60e-9)])) for k, v in SER_VEC.items()}
        rows.append(dict(point=n, mode=mode, opts={k: str(v) for k, v in opts.items()}, replay=infos[n],
                         serializer_clock_offset_ui=pos, serializer_clock_pp_v=amp, nodes=r))
        s, f = r["serializer"], r["far"]
        print(f"{n:8s} {label:12s} | serializer margin {s['contract']['minimum_signed_margin_v']*1e3:6.1f} mV spread "
              f"{s['contract']['transition_spread_ui'] or float('nan'):.3f} draft {serial.meets_draft(s['contract'])!s:5s}"
              f" | order-free {s['order_free']['eye_min_abs_v']*1e3:6.1f} mV {s['order_free']['edge_spread_ui']:.3f} UI"
              f" {'in order' if s['order_free']['in_order'] else 'permuted'}"
              f" | far {f['order_free']['eye_min_abs_v']*1e3:6.1f} mV {f['order_free']['edge_spread_ui']:.3f} UI"
              f" | clk pp " + "/".join(f"{amp[k]*1e3:.0f}" for k in CLOCKS)
              + " mV, offset " + "/".join(f"{pos[k]:+.2f}" for k in CLOCKS) + " UI", flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2, default=float))
    print(camp.relative_to(ROOT))
    return camp


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("calibrated", "native", "target", "fixed"))
    ap.add_argument("points", nargs="*")
    ap.add_argument("--dist", help="file defining serdes_cml_clock_distribution_tx_lowov")
    ap.add_argument("--trims", help="fF for 250,500,1g,2g (default r2 100,500,160,270)")
    ap.add_argument("--label")
    ap.add_argument("--from", dest="target_label", help="fixed: label of the target campaign to derive from")
    ap.add_argument("--late", action="append", default=[],
                    help="fixed: CLK=UI extra delay of one clock at every corner (e.g. 2g=0.1)")
    a = ap.parse_args()
    late = {k: float(v) * 250e-12 for k, v in (x.split("=") for x in a.late)}
    opts = dict(label=a.label)
    if a.dist:
        opts["dist"] = a.dist
    if a.trims:
        opts["trims"] = tuple(float(x) for x in a.trims.split(","))
    campaign(a.mode, a.points or list(POINTS), target_label=a.target_label, late=late, **opts)
