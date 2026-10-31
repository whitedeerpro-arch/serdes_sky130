"""Look at TX waveforms before and after the output stage (no simulation).

Reads existing r2-bench runs (serializer node `dout` = qp - qn, far end
`line_rx` after driver + RLC channel + 100 ohm termination) and draws:

* eyes.png  - 2-UI eye folded on even payload bits (full even eye at 0, odd
              half eyes at +-1 UI), sampling phase from training bits only,
              same convention as docs/figures/tx/optimization/
              tx_optimization_before_after_eyes.png;
* words.png - time domain of the first WORDS payload words at both nodes,
              expected bits printed under the serializer trace;
* final_rank.png - inside the final latched 2:1 over 16 UI (a run of ones
              then zeros): output, both latch outputs, latch clock, total mux
              load current (2 vmux - qp - qn) / rload, output CM, mux tail node.
              Constant data should give constant load current; a dip at every
              select edge is current diverted into internal node capacitance.

    uv run python analog/tx/serializer/tb/waveform_view/view.py [run_dir ...]

With no arguments: state (0, 0) of the latest clock_states grid campaign at
TT, SS/1.65 V/-40 C, SS/1.65 V/85 C and FS/1.65 V/85 C (the rows of the r2
before/after figure).  Output goes to results/analog/tx/serializer/waveform_view/.
"""
import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import serial, spice
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
EXPECTED = ROOT / "analog/tx/serializer/tb/clock_states/serializer_expected.json"
RESULTS = ROOT / "results/analog/tx/serializer/waveform_view"
NODES = (("serializer", "dout"), ("far", "line_rx"))
DEFAULT_TAGS = ("tt_v1800_t27", "ss_v1650_t-40", "ss_v1650_t85", "fs_v1650_t85")
PAYLOAD = 128
WORDS = 3
INK, MUTED, TRACE = "#222222", "#888888", "#2a6fb0"


def default_runs():
    grid = sorted((ROOT / "results/analog/tx/serializer/clock_states").glob("grid_2*"))[-1]
    return [grid / f"{tag}_s00" / "run" for tag in DEFAULT_TAGS]


def label(run_dir):
    meta = json.loads((run_dir / "execution.json").read_text()).get("meta", {})
    return meta.get("condition", run_dir.parent.name)


FINAL_RANK = (("dout", "out diff V"), ("latchA", "latch A V"), ("latchB", "latch B V"),
              ("latchclk", "latch clk V"), ("imu", "load I A"), ("cmout", "out CM V"),
              ("v(xtree.xr4_0.xm.tail)", "mux tail V"))
FINAL_RANK_FIRST = serial.TRAINING_BITS + 18     # payload bits 18..33: 1-run, 0-run


def measure(run_dir, seq):
    w = spice.Waves(run_dir / "waveforms.tsv")
    out = {}
    for node, vec in NODES:
        m, d = serial.check(w.t, w[vec], seq, PAYLOAD)
        out[node] = dict(t=w.t, y=w[vec], metrics=m, centres=np.asarray(d["sample_time_s"]))
    out["internal"] = {vec: w[vec] for vec, _ in FINAL_RANK}
    return out


def final_rank(axes, res, seq):
    ui, t = seq.ui_s, res["serializer"]["t"]
    t0 = res["serializer"]["centres"][FINAL_RANK_FIRST] - 0.5 * ui
    sel = (t >= t0) & (t <= t0 + 16 * ui)
    for ax, (vec, name) in zip(axes, FINAL_RANK):
        ax.plot((t[sel] - t0) / ui, res["internal"][vec][sel], color=TRACE, lw=1.0)
        for b in range(17):
            ax.axvline(b, color=MUTED, lw=0.3, ls=":")
    top = axes[0].get_ylim()[1]
    for b in range(16):
        axes[0].text(b + 0.5, top * 0.9, str(seq.bits[FINAL_RANK_FIRST + b]), ha="center", fontsize=7, color=MUTED)


def eye(ax, r, seq):
    ui, t, y = seq.ui_s, r["t"], r["y"]
    first = serial.TRAINING_BITS
    for k in range(first, first + PAYLOAD, 2):
        c = r["centres"][k]
        sel = (t >= c - 1.05 * ui) & (t <= c + 1.05 * ui)
        ax.plot((t[sel] - c) / ui, y[sel], color=TRACE, lw=0.8, alpha=0.35)
    m = r["metrics"]
    ax.set_title(f"{m['minimum_signed_margin_v']*1e3:.1f} mV; {m['transition_spread_ui']:.3f} UI; "
                 f"err {m['bit_errors']}", fontsize=9, color=INK)
    ax.set_xlim(-1, 1)
    for x in (-0.5, 0.5):
        ax.axvline(x, color=MUTED, lw=0.5, ls=":")
    ax.axhline(0, color=MUTED, lw=0.5)


def words(ax, r, seq, show_bits):
    ui, t, y = seq.ui_s, r["t"], r["y"]
    first = serial.TRAINING_BITS
    c0 = r["centres"][first]
    t0, t1 = c0 - 0.5 * ui, c0 + (16 * WORDS - 0.5) * ui
    sel = (t >= t0 - 2 * ui) & (t <= t1 + 2 * ui)
    ax.plot((t[sel] - t0) / ui, y[sel], color=TRACE, lw=1.0)
    for b in range(0, 16 * WORDS + 1):
        ax.axvline(b, color=MUTED, lw=0.6 if b % 16 == 0 else 0.25, ls="-" if b % 16 == 0 else ":")
    ax.axhline(0, color=MUTED, lw=0.5)
    ax.set_xlim(-1, 16 * WORDS + 1)
    if show_bits:
        top = ax.get_ylim()[1]
        for b in range(16 * WORDS):
            ax.text(b + 0.5, top * 0.92, str(seq.bits[first + b]), ha="center", va="top", fontsize=6, color=MUTED)


def main(runs):
    seq = serial.Sequence.from_expected(json.loads(EXPECTED.read_text()))
    data = [(label(r), measure(r, seq)) for r in runs]
    out = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out.mkdir(parents=True)

    fig, axes = plt.subplots(len(data), 2, figsize=(8, 2.6 * len(data)), sharex=True, sharey=True, squeeze=False)
    for i, (name, res) in enumerate(data):
        for j, (node, _) in enumerate(NODES):
            eye(axes[i, j], res[node], seq)
            if i == 0:
                axes[i, j].annotate(node, (0.5, 1.22), xycoords="axes fraction", ha="center",
                                    fontweight="bold", fontsize=10, color=INK)
        axes[i, 0].set_ylabel(f"{name}\ndiff V", fontsize=9)
    for ax in axes[-1]:
        ax.set_xlabel("UI (even bit centred, odd half eyes at ±1)", fontsize=8)
    fig.suptitle(f"TX r2, {PAYLOAD} payload bits, sampling phase from training only", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "eyes.png", dpi=130)

    fig, axes = plt.subplots(2 * len(data), 1, figsize=(12, 1.9 * 2 * len(data)), sharex=True, squeeze=False)
    for i, (name, res) in enumerate(data):
        for j, (node, _) in enumerate(NODES):
            ax = axes[2 * i + j, 0]
            words(ax, res[node], seq, show_bits=(j == 0))
            ax.set_ylabel(f"{name}\n{node}", fontsize=8)
    axes[-1, 0].set_xlabel(f"UI from first payload bit ({WORDS} words; thick lines = word boundaries)", fontsize=8)
    fig.suptitle("TX r2 serializer node and far end, time domain", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "words.png", dpi=110)

    fig, axes = plt.subplots(len(FINAL_RANK), len(data), figsize=(3.4 * len(data), 1.5 * len(FINAL_RANK)),
                             sharex=True, squeeze=False)
    for j, (name, res) in enumerate(data):
        final_rank(axes[:, j], res, seq)
        axes[0, j].set_title(name, fontsize=9)
        axes[-1, j].set_xlabel("UI (bit boundaries dotted)", fontsize=8)
    for i, (_, name) in enumerate(FINAL_RANK):
        axes[i, 0].set_ylabel(name, fontsize=8)
    fig.suptitle("Final latched 2:1 (xtree.xr4_0) during a run of ones then zeros", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "final_rank.png", dpi=105)

    summary = {name: {node: res[node]["metrics"] for node, _ in NODES} for name, res in data}
    (out / "summary.json").write_text(json.dumps(dict(runs=[str(r.relative_to(ROOT)) for r in runs],
                                                      metrics=summary), indent=2))
    for name, res in data:
        print(name, "  ".join(f"{node}: {res[node]['metrics']['minimum_signed_margin_v']*1e3:.1f} mV "
                              f"{res[node]['metrics']['transition_spread_ui']:.3f} UI "
                              f"pp {res[node]['metrics']['differential_pp_v']*1e3:.0f} mV" for node, _ in NODES))
    print(out.relative_to(ROOT))


if __name__ == "__main__":
    main([Path(a).resolve() for a in sys.argv[1:]] or default_runs())
