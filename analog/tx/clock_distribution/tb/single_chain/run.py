"""Single-chain TX clock generation experiments.

    uv run python analog/tx/clock_distribution/tb/single_chain/run.py timing [tags...]

timing: one r3 prescaler on phase 0; reports when each tap (/2, /4, /8)
transitions relative to the rising edge of phase 0, i.e. where a retiming
flip-flop clocked by one of the eight VCO phases sees setup/hold.

sweep: for each of the eight phases, retime all three taps on that phase and
record setup/hold slack at the flip-flop clock (after its input follower) and
the tap-to-output latency.  Phase j < 4 is buffer j, j >= 4 is buffer j-4
inverted; with the ideal sources phase j lags phase 0 by j * 62.5 ps.

tx: full TX r2 (distribution, serializer, output driver, RLC16) clocked by the
retimed single chain.  Pass 1 runs clocks only and finds the 250 MHz falling
edge; pass 2 shifts the data words so that every word edge sits 78.3 ps after
a 250 MHz fall, exactly as in the TX PVT/optimization benches, then checks
the serializer, pad and far-end nodes with the training-only contract.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

from serdes_flow import clock, serial, spice
from serdes_flow.corners import STRESS, Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
RESULTS = ROOT / "results/analog/tx/clock_distribution/single_chain"
PERIOD = 500e-12


def timing(conds):
    camp = RESULTS / ("timing_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    jobs = []
    for c in conds:
        deck = spice.render(HERE / "tb_chain_timing_ngspice.cir.in", **spice.corner_values(c),
                            STOP="48n", INITIAL_STATE="")
        jobs.append((deck, camp / c.tag, dict(meta=dict(condition=c.tag, bench="chain_timing"))))
    for ex in spice.run_many(jobs):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for c in conds:
        w = spice.Waves(camp / c.tag / "waveforms.tsv")
        t, start = w.t, 24e-9
        ref = clock.edges(t, w["b0"], 1, start)
        row = dict(condition=c.tag)
        # Phase k rising edge relative to b0 rising (ps, mod period).
        for k in range(4):
            e = clock.edges(t, w[f"b{k}"], 1, start)
            row[f"b{k}_rise_ps"] = float(np.median((e - ref[0]) % PERIOD) * 1e12)
        for tap in ("d2", "d4", "d8"):
            stats = clock.period_stats(t, w[tap], start)
            edges = np.sort(np.concatenate([clock.edges(t, w[tap], p, start) for p in (1, -1)]))
            k = np.searchsorted(ref, edges) - 1
            off = (edges[k >= 0] - ref[k[k >= 0]]) * 1e12
            row[tap] = dict(frequency_ghz=stats["frequency_hz"] / 1e9, amplitude_mv=stats["amplitude_pp_v"] * 1e3,
                            delay_after_b0_rise_ps=[float(np.min(off)), float(np.max(off))])
        rows.append(row)
        print(c.tag, {k: (round(v, 1) if isinstance(v, float) else
                          {kk: [round(x, 1) for x in vv] if isinstance(vv, list) else round(vv, 3) for kk, vv in v.items()})
                      for k, v in row.items() if k != "condition"}, flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2))


TAPS = (("d2", "r2", 1e9), ("d4", "r4", 0.5e9), ("d8", "r8", 0.25e9))


def phase_nodes(j, prefix="b"):
    k = j % 4
    return (f"{prefix}{k}p", f"{prefix}{k}n") if j < 4 else (f"{prefix}{k}n", f"{prefix}{k}p")


def _after(times, x):
    i = np.searchsorted(times, x)
    return times[i] if i < len(times) else np.nan


def sweep(conds):
    camp = RESULTS / ("sweep_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    jobs = []
    for c in conds:
        for j in range(8):
            p, n = phase_nodes(j)
            deck = spice.render(HERE / "tb_retime_sweep_ngspice.cir.in", **spice.corner_values(c),
                                STOP="48n", INITIAL_STATE="", PHASE_P=p, PHASE_N=n)
            jobs.append((deck, camp / f"{c.tag}_ph{j}", dict(meta=dict(condition=c.tag, phase=j))))
    for ex in spice.run_many(jobs):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for c in conds:
        for j in range(8):
            w = spice.Waves(camp / f"{c.tag}_ph{j}" / "waveforms.tsv")
            t, start = w.t, 24e-9
            samp = clock.edges(t, w["ck"], -1, start)           # slave updates on clock fall
            row = dict(condition=c.tag, phase=j)
            for tap, out, f in TAPS:
                dt = np.sort(np.concatenate([clock.edges(t, w[tap], q, start - 5e-9) for q in (1, -1)]))
                prev = dt[np.searchsorted(dt, samp) - 1]
                nxt = np.array([_after(dt, x) for x in samp])
                ok = ~np.isnan(nxt)
                stats = clock.period_stats(t, w[out], start)
                lat = []
                for q in (1, -1):
                    src = clock.edges(t, w[tap], q, start - 5e-9)
                    for e in clock.edges(t, w[out], q, start):
                        k = np.searchsorted(src, e) - 1
                        if k >= 0:
                            lat.append(e - src[k])
                row[out] = dict(
                    frequency_ok=bool(stats and abs(stats["frequency_hz"] / f - 1) < 0.01),
                    amplitude_mv=stats["amplitude_pp_v"] * 1e3 if stats else None,
                    setup_ps=float(np.min(samp - prev) * 1e12),
                    hold_ps=float(np.min(nxt[ok] - samp[ok]) * 1e12),
                    latency_ps=[float(np.min(lat) * 1e12), float(np.max(lat) * 1e12)] if lat else None)
            rows.append(row)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2))
    for r in rows:
        print(r["condition"], r["phase"], " ".join(
            f"{o}:{'ok' if r[o]['frequency_ok'] else 'BAD'} s{r[o]['setup_ps']:.0f}/h{r[o]['hold_ps']:.0f}"
            f" L{r[o]['latency_ps'][0]:.0f}-{r[o]['latency_ps'][1]:.0f}" if r[o]["latency_ps"] else f"{o}:none"
            for o in ("r2", "r4", "r8")), flush=True)


# Old bench (frozen TT PLL edges): src250 falls at 2.42693 ns + 4 ns * k and
# each word edge follows a fall by 78.3 ps.
OLD_SRC250_FALL = 14.42688e-9

# Selected generator: retiming phase per tap and the wiring polarity of each
# clock into the distribution (True = p/n swapped).  Filled in from the sweep.
CONFIG = dict(ck250=4, ck500=3, ck1g=5, ph2g=2, flip250=False, flip500=False, flip1g=False,
              trims=dict(TRIM250=1e-13, TRIM500=5e-13, TRIM1G=1.6e-13, TRIM2G=2.7e-13))


def _pair(prefix, flip):
    p, n = f"{prefix}p", f"{prefix}n"
    return (n, p) if flip else (p, n)


def retimers(cfg):
    """Retimer chains: each tap passes through one flip-flop per listed phase.

    cfg["ck250"] etc. may be an int (one stage) or a list of phases; extra
    stages on the same phase add exactly one 2 GHz period of latency.
    """
    lines = []
    params = " ".join(f"{k}={v}" for k, v in cfg.get("retimer", {}).items())
    if cfg["ck250"] == "div500":
        # 250 MHz = /2 of the retimed 500 MHz (retimer cell as a toggle flip-flop);
        # div250_flip picks the toggling edge.
        clk = "r500n r500p" if cfg.get("div250_flip") else "r500p r500n"
        lines.append(f"Xr250 r250n r250p {clk} r250p r250n vbias vbias_rt vgen 0 serdes_cml_dff_lowov {params}")
    for out, tap, key in (("r250", "d08", "ck250"), ("r500", "d04", "ck500"), ("r1g", "d02", "ck1g")):
        if cfg[key] == "div500":
            continue
        phases = cfg[key] if isinstance(cfg[key], list) else [cfg[key]]
        src = f"{tap}p {tap}n"
        for i, k in enumerate(phases):
            dst = f"{out}p {out}n" if i == len(phases) - 1 else f"{out}_{i}p {out}_{i}n"
            name = f"X{out}" if i == len(phases) - 1 else f"X{out}_{i}"
            lines.append(f"{name} {src} {' '.join(phase_nodes(k, cfg.get('clock_prefix', 'b')))} {dst} vbias vbias_rt vgen 0 serdes_cml_dff_lowov {params}")
            src = dst
    return "\n".join(lines)


def _intermediate(cfg):
    names = []
    for out, key in (("r250", "ck250"), ("r500", "ck500"), ("r1g", "ck1g")):
        if isinstance(cfg[key], list):
            names += [f"{out}_{i}" for i in range(len(cfg[key]) - 1)]
    return names


def tx_deck(c, cfg, data, stop):
    s250, s500, s1g = _pair("r250", cfg["flip250"]), _pair("r500", cfg["flip500"]), _pair("r1g", cfg["flip1g"])
    if cfg.get("replica2g"):
        s2g = _pair("r2g", cfg.get("flip2g", False))
    else:
        s2g = phase_nodes(cfg["ph2g"])
    v = dict(spice.corner_values(c), STOP=stop, MAX_STEP="4p", INITIAL_STATE="",
             TAIL_SCALE=6, WSF=80, WSELECT=96, DRIVER_FILE="cml_line_driver_lowvt_enable.spice",
             DRIVER_CELL="serdes_tx_cml_line_driver_lowvt_enable", DRIVER_PARAMS="wgatep=32",
             RETIMERS=retimers(cfg) + "".join(f"\n.save v({n}p) v({n}n)" for n in _intermediate(cfg)),
             EXTRA_LETS="\n".join(f"let g{n}=v({n}p)-v({n}n)" for n in _intermediate(cfg)) or "*",
             EXTRA_WR=" ".join(f"g{n}" for n in _intermediate(cfg)),
             CK2G=" ".join(phase_nodes(cfg["ph2g"], cfg.get("clock_prefix", "b"))),
             RP_PARAMS=" ".join(f"{k}={v}" for k, v in cfg.get("retimer", {}).items() if k != "whold"),
             S250=" ".join(s250), S500=" ".join(s500), S1G=" ".join(s1g), S2G=" ".join(s2g),
             S250_P=s250[0], S250_N=s250[1], S500_P=s500[0], S500_N=s500[1],
             S1G_P=s1g[0], S1G_N=s1g[1], S2G_P=s2g[0], S2G_N=s2g[1], **cfg["trims"])
    return spice.render(HERE / "tb_tx_single_chain_ngspice.cir.in", **v), data


def _shift_pwl(text, dt):
    """Shift every PWL time point except t=0 by dt seconds."""
    out = []
    for line in text.splitlines():
        head, body = line.split("PWL(", 1)
        tok = body.rstrip(")").split()
        for i in range(2, len(tok), 2):
            tok[i] = f"{float(tok[i]) + dt:.14e}"
        out.append(head + "PWL(" + " ".join(tok) + ")")
    return "\n".join(out) + "\n"


def tx(conds, cfg=CONFIG, label="tx", stop="72n", payload=128):
    return tx_points([(c.tag, c, cfg) for c in conds], label, stop, payload)


def tx_points(points, label="tx", stop="72n", payload=128):
    """points: (name, condition, config) triples, all run in one campaign."""
    camp = RESULTS / (label + "_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    words = (HERE / "data_words.inc").read_text()
    static = "\n".join(l.split(" PWL(")[0] + " " + l.split("PWL(")[1].split()[1] for l in words.splitlines()) + "\n"
    jobs = []
    for name, c, cfg in points:
        deck, _ = tx_deck(c, cfg, static, "20n")
        d = camp / f"{name}_align"
        d.mkdir(parents=True)
        (d / "static_stimuli.inc").write_text(static)
        jobs.append((deck, d / "run", dict(files={"stimuli.inc": d / "static_stimuli.inc"},
                                            meta=dict(condition=c.tag, config=cfg, bench="tx_align"))))
    for ex in spice.run_many(jobs):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    shifts, jobs = {}, []
    for name, c, cfg in points:
        w = spice.Waves(camp / f"{name}_align/run/waveforms.tsv")
        falls = clock.edges(w.t, w["src250"], -1, 8e-9)
        dt = float((falls[np.argmin(abs(falls - OLD_SRC250_FALL))] - OLD_SRC250_FALL + 2e-9) % 4e-9 - 2e-9)
        shifts[name] = dt
        d = camp / name
        d.mkdir()
        (d / "data_stimuli.inc").write_text(_shift_pwl(words, dt))
        deck, _ = tx_deck(c, cfg, None, stop)
        jobs.append((deck, d / "run", dict(files={"stimuli.inc": d / "data_stimuli.inc"},
                                            meta=dict(condition=c.tag, config=cfg, data_shift_s=dt, bench="tx"))))
    for ex in spice.run_many(jobs):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    expected = json.loads((HERE / "serializer_expected.json").read_text())
    rows = []
    for name, c, cfg in points:
        w = spice.Waves(camp / name / "run/waveforms.tsv")
        seq = serial.Sequence.from_expected(dict(expected, start_s=expected["start_s"] + shifts[name]))
        nodes = {k: serial.check(w.t, w[v], seq, payload)[0] for k, v in
                 (("serializer", "dout"), ("pad", "line_tx"), ("far", "line_rx"))}
        ref = clock.edges(w.t, w["d250"], -1, 30e-9, 60e-9)
        phases = {}
        for v in ("d250", "d500", "d1g", "latchclk"):
            e = {q: clock.edges(w.t, w[v], q, 30e-9, 60e-9) for q in (1, -1)}
            phases[v] = {("rise" if q == 1 else "fall"): float((e[q][np.searchsorted(e[q], ref[0])] - ref[0]) / 250e-12)
                         for q in (1, -1)}
        win = (w.t >= 30e-9) & (w.t <= 60e-9)
        row = dict(name=name, condition=c.tag, config=cfg, data_shift_ps=shifts[name] * 1e12, nodes=nodes,
                   serializer_draft=serial.meets_draft(nodes["serializer"]), clock_phase_ui=phases,
                   generator_power_mw=float(np.trapezoid(w["pgen"][win], w.t[win]) / 30e-9 * 1e3))
        rows.append(row)
        n = nodes["serializer"]
        print(name, "draft", row["serializer_draft"], "func", all(x["functional"] for x in nodes.values()),
              f"ser {n['minimum_signed_margin_v']*1e3:.1f}mV {n['transition_spread_ui']}",
              f"far {nodes['far']['minimum_signed_margin_v']*1e3:.1f}mV",
              {k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in phases.items()},
              f"gen {row['generator_power_mw']:.2f} mW", flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2))
    return rows


if __name__ == "__main__":
    import os
    step, tags = sys.argv[1], sys.argv[2:]
    conds = [Condition.parse(t) for t in tags] if tags else STRESS
    if step == "tx":
        # TX_CONFIG='{"ph2g": 6, "trims": {...}}' overrides selected fields.
        cfg = dict(CONFIG, **json.loads(os.environ.get("TX_CONFIG", "{}")))
        sweep_key = os.environ.get("TX_SWEEP")   # e.g. TRIM500=0,2.5e-13,5e-13
        if sweep_key:
            key, vals = sweep_key.split("=")
            points = [(f"{c.tag}_{key}_{v}", c, dict(cfg, trims=dict(cfg["trims"], **{key: float(v)})))
                      for c in conds for v in vals.split(",")]
        else:
            points = [(c.tag, c, cfg) for c in conds]
        tx_points(points, label=os.environ.get("TX_LABEL", "tx"), stop=os.environ.get("TX_STOP", "72n"))
    else:
        {"timing": timing, "sweep": sweep}[step](conds)
