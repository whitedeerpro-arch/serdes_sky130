"""Look at TX waveforms before and after the output stage (no simulation).

Two kinds of saved r2-bench runs:

* ideal - clock_states grid, state (0, 0): the r2 calibration bench.  The four
  clock sources are one frozen TT edge record (400 mVpp, 20 ps edges, CM
  VDD - 0.17 V) at every corner; distribution, serializer and driver are at
  the corner.  Bits are in order; sampling phase from training bits.
* native - native_clock data campaign: the same TX clocked by the PLL r4
  frontend at the corner (VCO open loop at a fixed Vctrl).  Not remapped, so
  bits are permuted; the sampling phase comes from the payload crossings
  (serial.bit_mapping) and the eye is order-free.

Nodes: serializer = dout (qp - qn, input of the line driver), pad = line_tx
(driver output), far = line_rx (after RLC channel and 100 ohm termination).

Figures:
  eyes.png       2-UI eyes (full eye at 0, half eyes at +-1 UI) per run and node
  words.png      3 payload words, time domain, serializer and far
  final_rank.png inside the final latched 2:1 during 16 UI: output, latch
                 outputs, latch clock, total mux load current
                 (2 vmux - qp - qn) / rload, output CM, mux tail node
  clocks.png     (when both kinds are given) the four clocks at the serializer
                 inputs over one word, aligned on the 250 MHz fall; ideal vs native

    uv run python analog/tx/serializer/tb/waveform_view/view.py                # ideal, 4 corners
    uv run python analog/tx/serializer/tb/waveform_view/view.py compare        # ideal vs native
"""
import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import serial, spice
from serdes_flow.clock import edges
from serdes_flow.project import ROOT

EXPECTED = ROOT / "analog/tx/serializer/tb/clock_states/serializer_expected.json"
SERIALIZER = ROOT / "results/analog/tx/serializer"
RESULTS = SERIALIZER / "waveform_view"
NODES = (("serializer", "dout"), ("pad", "line_tx"), ("far", "line_rx"))
EYE_NODES = ("serializer", "far")
IDEAL_TAGS = {"tt": "tt_v1800_t27", "ss_cold": "ss_v1650_t-40", "ss_hot": "ss_v1650_t85", "fs_hot": "fs_v1650_t85"}
PAYLOAD = 128
WORDS = 3
FINAL_RANK = (("dout", "out diff V"), ("latchA", "latch A V"), ("latchB", "latch B V"),
              ("latchclk", "latch clk V"), ("imu", "load I A"), ("cmout", "out CM V"),
              ("v(xtree.xr4_0.xm.tail)", "mux tail V"))
CLOCKS = (("d250", "250M"), ("d500", "500M"), ("d1g", "1G"), ("ds", "2G"))
INK, MUTED, IDEAL, NATIVE = "#222222", "#888888", "#9a9a9a", "#2a6fb0"


@dataclass
class Run:
    name: str
    kind: str                 # "ideal" | "native"
    t: np.ndarray
    w: spice.Waves
    seq: serial.Sequence
    centres: dict             # node -> bit-centre times (payload starts at index TRAINING_BITS)
    metrics: dict             # node -> (eye or margin V, spread UI, errors or mapping note)


def _native_module():
    spec = importlib.util.spec_from_file_location("native_run", ROOT / "analog/tx/serializer/tb/native_clock/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_ideal(name, run_dir):
    seq = serial.Sequence.from_expected(json.loads(EXPECTED.read_text()))
    w = spice.Waves(run_dir / "waveforms.tsv")
    centres, metrics = {}, {}
    for node, vec in NODES:
        m, d = serial.check(w.t, w[vec], seq, PAYLOAD)
        centres[node] = np.asarray(d["sample_time_s"])
        metrics[node] = (m["minimum_signed_margin_v"], m["transition_spread_ui"], f"err {m['bit_errors']}")
    return Run(name, "ideal", w.t, w, seq, centres, metrics)


def load_native(name, run_dir, native):
    meta = json.loads((run_dir / "execution.json").read_text())
    probe = {r["point"]: r for r in json.loads((Path(meta["probe"]) / "summary.json").read_text())}[name]
    first = [x for x in probe["src250_falls_s"] if x > native.SETTLE.get(name, 30e-9)][0]
    bits = json.loads(EXPECTED.read_text())["bits"][: 16 * native.WORDS]
    seq = serial.Sequence(np.asarray(bits, dtype=int), first + native.WORD_DELAY, probe["ui_s"])
    w = spice.Waves(run_dir / "waveforms.raw")
    centres, metrics = {}, {}
    n = np.arange(len(bits))
    for node, vec in NODES:
        o = serial.bit_mapping(w.t, w[vec], seq)
        centres[node] = seq.start_s + (n + o["sampling_phase_ui"] + 0.5) * seq.ui_s
        metrics[node] = (o["eye_min_abs_v"], o["edge_spread_ui"], "in order" if o["in_order"] else "permuted")
    return Run(name, "native", w.t, w, seq, centres, metrics)


def _label(run):
    return f"{run.name} {run.kind}"


def eye(ax, run, node, colour):
    ui, t, y = run.seq.ui_s, run.t, run.w[dict(NODES)[node]]
    first = serial.TRAINING_BITS
    for k in range(first, first + PAYLOAD, 2):
        c = run.centres[node][k]
        sel = (t >= c - 1.05 * ui) & (t <= c + 1.05 * ui)
        ax.plot((t[sel] - c) / ui, y[sel], color=colour, lw=0.8, alpha=0.35)
    v, spread, note = run.metrics[node]
    kind = "margin" if run.kind == "ideal" else "|eye|"
    ax.set_title(f"{node}: {kind} {v*1e3:.1f} mV; {spread:.3f} UI; {note}", fontsize=8, color=INK)
    ax.set_xlim(-1, 1)
    for x in (-0.5, 0.5):
        ax.axvline(x, color=MUTED, lw=0.5, ls=":")
    ax.axhline(0, color=MUTED, lw=0.5)


def words(ax, run, node, show_bits):
    ui, t, y = run.seq.ui_s, run.t, run.w[dict(NODES)[node]]
    c = run.centres[node]
    first = serial.TRAINING_BITS
    t0 = c[first] - 0.5 * ui
    sel = (t >= t0 - 2 * ui) & (t <= t0 + (16 * WORDS + 2) * ui)
    ax.plot((t[sel] - t0) / ui, y[sel], color=NATIVE, lw=1.0)
    for b in range(16 * WORDS + 1):
        ax.axvline(b, color=MUTED, lw=0.6 if b % 16 == 0 else 0.25, ls="-" if b % 16 == 0 else ":")
    ax.axhline(0, color=MUTED, lw=0.5)
    ax.set_xlim(-1, 16 * WORDS + 1)
    if show_bits:                      # sampled bits (what the node carries, in either kind)
        top = ax.get_ylim()[1]
        s = np.interp(c[first:first + 16 * WORDS], t, y) > 0
        for b, bit in enumerate(s):
            ax.text(b + 0.5, top * 0.92, str(int(bit)), ha="center", va="top", fontsize=6, color=MUTED)


def final_rank(axes, run):
    ui, t = run.seq.ui_s, run.t
    first = serial.TRAINING_BITS + 18
    t0 = run.centres["serializer"][first] - 0.5 * ui
    sel = (t >= t0) & (t <= t0 + 16 * ui)
    for ax, (vec, _) in zip(axes, FINAL_RANK):
        ax.plot((t[sel] - t0) / ui, run.w[vec][sel], color=NATIVE, lw=1.0)
        for b in range(17):
            ax.axvline(b, color=MUTED, lw=0.3, ls=":")


def clocks(ax_col, run, colour, label):
    """Serializer clock inputs over one word, t = 0 at a 250 MHz fall inside the payload."""
    ui, t = run.seq.ui_s, run.t
    mid = run.centres["serializer"][serial.TRAINING_BITS + 32]
    ref = edges(t, run.w["d250"], -1, mid)[0]
    sel = (t >= ref - 2 * ui) & (t <= ref + 18 * ui)
    for ax, (vec, _) in zip(ax_col, CLOCKS):
        ax.plot((t[sel] - ref) / ui, run.w[vec][sel], color=colour, lw=1.1, label=label)
        ax.axhline(0, color=MUTED, lw=0.4)


def save(fig, out, name, dpi=110):
    fig.tight_layout()
    fig.savefig(out / name, dpi=dpi)
    plt.close(fig)


def figures(runs, out):
    fig, axes = plt.subplots(len(runs), len(EYE_NODES), figsize=(8, 2.5 * len(runs)), sharex=True, sharey=True,
                             squeeze=False)
    for i, run in enumerate(runs):
        for j, node in enumerate(EYE_NODES):
            eye(axes[i, j], run, node, NATIVE if run.kind == "native" else "#2a6fb0")
        axes[i, 0].set_ylabel(f"{_label(run)}\ndiff V", fontsize=8)
    for ax in axes[-1]:
        ax.set_xlabel("UI (bit centred, neighbours' half eyes at ±1)", fontsize=8)
    fig.suptitle(f"TX r2, {PAYLOAD} payload bits; ideal: in-order margin, native: order-free |eye|", fontsize=9)
    save(fig, out, "eyes.png", 120)

    fig, axes = plt.subplots(2 * len(runs), 1, figsize=(12, 1.8 * 2 * len(runs)), sharex=True, squeeze=False)
    for i, run in enumerate(runs):
        for j, node in enumerate(EYE_NODES):
            words(axes[2 * i + j, 0], run, node, show_bits=(j == 0))
            axes[2 * i + j, 0].set_ylabel(f"{_label(run)}\n{node}", fontsize=7)
    axes[-1, 0].set_xlabel(f"UI from first payload bit ({WORDS} words; thick lines = word boundaries; "
                           "digits = sampled bits)", fontsize=8)
    save(fig, out, "words.png")

    fig, axes = plt.subplots(len(FINAL_RANK), len(runs), figsize=(3.3 * len(runs), 1.5 * len(FINAL_RANK)),
                             sharex=True, squeeze=False)
    for j, run in enumerate(runs):
        final_rank(axes[:, j], run)
        axes[0, j].set_title(_label(run), fontsize=8)
        axes[-1, j].set_xlabel("UI", fontsize=8)
    for i, (_, name) in enumerate(FINAL_RANK):
        axes[i, 0].set_ylabel(name, fontsize=8)
    fig.suptitle("Final latched 2:1 (xtree.xr4_0), payload bits 18..33", fontsize=9)
    save(fig, out, "final_rank.png", 100)

    pairs = {}
    for run in runs:
        pairs.setdefault(run.name, {})[run.kind] = run
    pairs = {k: v for k, v in pairs.items() if len(v) == 2}
    if pairs:
        fig, axes = plt.subplots(len(CLOCKS), len(pairs), figsize=(4.2 * len(pairs), 1.7 * len(CLOCKS)),
                                 sharex=True, squeeze=False)
        for j, (name, kinds) in enumerate(pairs.items()):
            clocks(axes[:, j], kinds["ideal"], IDEAL, "ideal TT source")
            clocks(axes[:, j], kinds["native"], NATIVE, "native PLL r4")
            axes[0, j].set_title(name, fontsize=9)
            axes[-1, j].set_xlabel("UI from 250 MHz fall", fontsize=8)
        for i, (_, name) in enumerate(CLOCKS):
            axes[i, 0].set_ylabel(f"{name} diff V", fontsize=8)
        axes[0, 0].legend(fontsize=7, loc="lower right", frameon=False)
        fig.suptitle("Clocks at the serializer inputs (after the on-chip distribution)", fontsize=9)
        save(fig, out, "clocks.png", 105)


def main(argv):
    runs = []
    if argv[:1] == ["compare"]:
        native = _native_module()
        grid = sorted((SERIALIZER / "clock_states").glob("grid_2*"))[-1]
        camp = sorted((SERIALIZER / "native_clock").glob("data_2*"))[-1]
        names = [n for n in IDEAL_TAGS if (camp / n / "run").exists()]
        for n in names:
            runs.append(load_ideal(n, grid / f"{IDEAL_TAGS[n]}_s00" / "run"))
            runs.append(load_native(n, camp / n / "run", native))
        sources = [str(grid.relative_to(ROOT)), str(camp.relative_to(ROOT))]
    else:
        grid = sorted((SERIALIZER / "clock_states").glob("grid_2*"))[-1]
        runs = [load_ideal(n, grid / f"{tag}_s00" / "run") for n, tag in IDEAL_TAGS.items()]
        sources = [str(grid.relative_to(ROOT))]

    out = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out.mkdir(parents=True)
    figures(runs, out)
    summary = [dict(name=r.name, kind=r.kind, ui_s=r.seq.ui_s,
                    nodes={n: dict(zip(("eye_or_margin_v", "spread_ui", "note"), r.metrics[n])) for n, _ in NODES})
               for r in runs]
    (out / "summary.json").write_text(json.dumps(dict(sources=sources, runs=summary), indent=2, default=float))
    for r in runs:
        print(f"{_label(r):16s}", "  ".join(f"{n}: {r.metrics[n][0]*1e3:6.1f} mV {r.metrics[n][1]:.3f} UI"
                                            for n, _ in NODES))
    print(out.relative_to(ROOT))


if __name__ == "__main__":
    main(sys.argv[1:])
