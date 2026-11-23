"""Divider start-state enumeration for TX r2 with its original clocking.

The four serializer clocks come from separate dividers: 250 MHz from the
branch-0 /8 (word clock), 500 MHz from the branch-2 /4, 1 GHz from the
branch-3 /2, 2 GHz straight from the VCO.  Relative to the word clock the
500 MHz divider can start in 4 states (0..3 VCO cycles late) and the 1 GHz
divider in 2.  Each state is reproduced exactly by delaying that clock's
frozen TT edge record by whole VCO cycles (500 ps) in the r2 bench; the
circuit, trims, data and every other source are unchanged.

    uv run python analog/tx/serializer/tb/clock_states/run.py grid [tags...]
    uv run python analog/tx/serializer/tb/clock_states/run.py long [tags...] [sAB...]

grid: all 8 states at each condition (default: the six stress conditions),
      128 payload bits.
table: export the measured permutation of every state (checked identical
      across conditions and nodes) for the TX remap RTL testbench.
window: timing windows.  One clock at a time (500 MHz, 1 GHz, 2 GHz) is moved
      by a fraction of a UI relative to the calibrated r2 position (taken
      modulo its own period, so the divider state is unchanged), 128 bits.
long: 1024 payload bits (300 ns record) for state (0, 0), or for the states
      given as sAB tokens (A = 500 MHz cycles late, B = 1 GHz cycles late).
Add "remap" to grid/long to pre-permute the parallel data with the inverse of
each state's measured permutation (what digital/tx/rtl/tx_word_remap does), so
the line pattern is the same in every state and the in-order contract applies.
"""
import json
import sys
import time
from itertools import product
from pathlib import Path

from serdes_flow import serial, spice
from serdes_flow.corners import STRESS, Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = ROOT / "analog/tx/serializer/tb/lowov_optimization/tb_serializer_lowov_ngspice.cir.in"
RESULTS = ROOT / "results/analog/tx/serializer/clock_states"
VCO_CYCLE = 500e-12
STATES = list(product(range(4), range(2)))      # (500 MHz cycles late, 1 GHz cycles late)
NODES = (("serializer", "dout"), ("pad", "line_tx"), ("far", "line_rx"))


def measured_permutation(c500, c1g):
    """Slot j -> input bit, from the exported table (digital/tx/tb/data)."""
    rows = [l.split() for l in PERMUTATIONS.read_text().splitlines() if not l.startswith("//")]
    return [int(x, 16) for x in rows[2 * c500 + c1g]]


def stimuli(c500, c1g, remap=False):
    """r2 stimuli with the 500 MHz / 1 GHz edge records delayed by whole VCO cycles.

    remap: input d[m[j]] carries the waveform originally meant for d[j], so slot
    j of the serial output carries the intended bit j.
    """
    shift = {"Vsrc500p": c500, "Vsrc500n": c500, "Vsrc1gp": c1g, "Vsrc1gn": c1g}
    m = measured_permutation(c500, c1g) if remap else list(range(16))
    out = []
    for line in (HERE / "r2_stimuli.inc").read_text().splitlines():
        name = line.split(" ", 1)[0]
        if name.startswith("Vd") and name[2:].isdigit():
            j, rest = int(name[2:]), line.split(" ", 3)[3]
            line = f"Vd{m[j]} d{m[j]} 0 {rest}"
        cycles = shift.get(line.split(" ", 1)[0], 0)
        if cycles:
            head, body = line.split("PWL(", 1)
            tok = body.rstrip(")").split()
            for i in range(2, len(tok), 2):          # every time point except t = 0
                tok[i] = f"{float(tok[i]) + cycles * VCO_CYCLE:.14e}"
            line = head + "PWL(" + " ".join(tok) + ")"
        out.append(line)
    return "\n".join(out) + "\n"


FULL_PERIOD = {"500": 2e-9, "1g": 1e-9, "2g": 0.5e-9}
SOURCES = {"500": ("Vsrc500p", "Vsrc500n"), "1g": ("Vsrc1gp", "Vsrc1gn"), "2g": ("Vsrc2gp", "Vsrc2gn")}
WINDOW_STEPS_UI = (-0.75, -0.5, -0.25, 0.25, 0.5, 0.75)


def shifted_stimuli(clk, shift_s):
    """r2 stimuli with one clock's edge record moved by shift_s (taken modulo its period)."""
    dt = shift_s % FULL_PERIOD[clk]
    out = []
    for line in (HERE / "r2_stimuli.inc").read_text().splitlines():
        if line.split(" ", 1)[0] in SOURCES[clk]:
            head, body = line.split("PWL(", 1)
            tok = body.rstrip(")").split()
            for i in range(2, len(tok), 2):
                tok[i] = f"{float(tok[i]) + dt:.14e}"
            line = head + "PWL(" + " ".join(tok) + ")"
        out.append(line)
    return "\n".join(out) + "\n"


def window(conds):
    camp = RESULTS / f"window_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    points = [(c, clk, ui) for c in conds for clk in SOURCES for ui in WINDOW_STEPS_UI]
    jobs = []
    for c, clk, ui in points:
        d = camp / f"{c.tag}_{clk}_{ui:+.2f}"
        d.mkdir(parents=True)
        (d / "stimuli.inc").write_text(shifted_stimuli(clk, ui * 250e-12))
        dk = spice.skip_output_before(spice.binary_output(deck(c, "72n")), "12n")
        jobs.append((dk, d / "run", dict(files={"stimuli.inc": d / "stimuli.inc"},
                                         meta=dict(condition=c.tag, clock=clk, shift_ui=ui))))
    for ex in spice.run_many(jobs):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for c, clk, ui in points:
        r = analyse(camp / f"{c.tag}_{clk}_{ui:+.2f}" / "run", 128)
        s = r["serializer"]
        rows.append(dict(condition=c.tag, clock=clk, shift_ui=ui, nodes=r))
        print(f"{c.tag:14s} {clk:3s} {ui:+.2f} UI  eye {s['order_free']['eye_min_abs_v']*1e3:6.1f} mV  spread "
              f"{s['order_free']['edge_spread_ui']:.3f}  {'IN ORDER' if s['order_free']['in_order'] else s['order_free']['mapping']}  "
              f"draft {serial.meets_draft(s['contract'])}", flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2))


def deck(c, stop):
    return spice.render(TEMPLATE, **spice.corner_values(c), STOP=stop, MAX_STEP="4p",
                        TAIL_SCALE=6, WSF=80, WSELECT=96, DRIVER_FILE="cml_line_driver_lowvt_enable.spice",
                        DRIVER_CELL="serdes_tx_cml_line_driver_lowvt_enable", DRIVER_PARAMS="wgatep=32")


def analyse(run_dir, payload):
    seq = serial.Sequence.from_expected(json.loads((HERE / "serializer_expected.json").read_text()))
    w = spice.Waves(run_dir / "waveforms.tsv")
    res = {}
    for node, vec in NODES:
        contract, _ = serial.check(w.t, w[vec], seq, payload)
        res[node] = dict(contract=contract, order_free=serial.bit_mapping(w.t, w[vec], seq))
    return res


def campaign(points, label, stop, payload, remap=False):
    camp = RESULTS / f"{label}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    jobs = []
    for c, (c500, c1g) in points:
        d = camp / f"{c.tag}_s{c500}{c1g}"
        d.mkdir(parents=True)
        (d / "stimuli.inc").write_text(stimuli(c500, c1g, remap))
        # Training starts at ~14.5 ns; nothing before 12 ns is analysed.
        dk = spice.skip_output_before(spice.binary_output(deck(c, stop)), "12n")
        jobs.append((dk, d / "run", dict(files={"stimuli.inc": d / "stimuli.inc"},
                    meta=dict(condition=c.tag, state_500=c500, state_1g=c1g, payload_bits=payload, remap=remap))))
    for ex in spice.run_many(jobs):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for c, (c500, c1g) in points:
        r = analyse(camp / f"{c.tag}_s{c500}{c1g}" / "run", payload)
        rows.append(dict(condition=c.tag, state=[c500, c1g], nodes=r))
        s = r["serializer"]
        print(f"{c.tag:15s} 500+{c500} 1G+{c1g}  eye {s['order_free']['eye_min_abs_v']*1e3:6.1f} mV"
              f"  spread {s['order_free']['edge_spread_ui']:.3f} UI"
              f"  far eye {r['far']['order_free']['eye_min_abs_v']*1e3:6.1f} mV"
              f"  {'IN ORDER' if s['order_free']['in_order'] else s['order_free']['mapping']}"
              f"  contract draft {serial.meets_draft(s['contract'])}", flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2))
    return rows


PERMUTATIONS = ROOT / "digital/tx/tb/data/serializer_state_permutations.hex"


def table():
    """One line per state index {c500, c1g}: 16 hex digits, slot j -> input bit."""
    camp = sorted(RESULTS.glob("grid_*"))[-1]
    seen = {}
    for r in json.loads((camp / "summary.json").read_text()):
        for node, _ in NODES:
            o = r["nodes"][node]["order_free"]
            m = tuple(range(16)) if o["in_order"] else tuple(o["mapping"])
            seen.setdefault(tuple(r["state"]), set()).add(m)
    assert len(seen) == 8 and all(len(v) == 1 for v in seen.values()), "mapping not unique per state"
    lines = [f"// {camp.relative_to(ROOT)}: slot j carries input bit m[j]; line = state {{c500[1:0], c1g}}"]
    for c500, c1g in sorted(seen, key=lambda s: s[0] * 2 + s[1]):
        m = next(iter(seen[(c500, c1g)]))
        assert sorted(m) == list(range(16))
        lines.append(" ".join(f"{x:x}" for x in m))
    PERMUTATIONS.write_text("\n".join(lines) + "\n")
    print(PERMUTATIONS.read_text())


if __name__ == "__main__":
    step = sys.argv[1]
    tags = [a for a in sys.argv[2:] if not (a.startswith("s") and a[1:].isdigit())]
    states = [(int(a[1]), int(a[2])) for a in sys.argv[2:] if a.startswith("s") and a[1:].isdigit()]
    remap = "remap" in tags
    tags = [a for a in tags if a != "remap"]
    conds = [Condition.parse(t) for t in tags] if tags else STRESS
    if step == "grid":
        campaign([(c, s) for c in conds for s in STATES], "grid_remap" if remap else "grid", "72n", 128, remap)
    elif step == "window":
        window(conds)
    elif step == "table":
        table()
    elif step == "long":
        campaign([(c, s) for c in conds for s in (states or [(0, 0)])], "long_remap" if remap else "long",
                 "300n", 1024, remap)
    else:
        sys.exit(f"unknown step {step}")
