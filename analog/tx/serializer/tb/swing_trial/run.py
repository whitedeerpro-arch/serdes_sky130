"""Final-rank swing trial on TX r2: lower the latch/MUX load to bring internal
CML swings under the 400 mVpp upper bound.

    uv run python analog/tx/serializer/tb/swing_trial/run.py [rout...]

r2 has rout = 400 ohm: final 2:1 MUX load 400 ohm, A/B latch loads
0.75 * rout = 300 ohm, at TT ~466 / ~650 mVpp.  Same r2 ideal-edge bench and
data as the clock-state work (state 0); currents unchanged, so lower R means
lower swing, higher output common mode (more tail headroom) and smaller RC.
Reports per condition: in-order contract, order-free eye, internal swings,
mid-bit sag (value at 0.25 UI minus bit centre), final-rank tail headroom
(mean VDS - VDSAT) and serializer power.
"""
import importlib.util
import json
import sys
import time

import numpy as np

from serdes_flow import serial, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_spec = importlib.util.spec_from_file_location("cs", ROOT / "analog/tx/serializer/tb/clock_states/run.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

RESULTS = ROOT / "results/analog/tx/serializer/swing_trial"
CONDS = ["tt_v1800_t27", "ss_v1650_t-40", "ss_v1650_t85", "fs_v1650_t85"]
UI = 250e-12


def main(routs):
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs, keys = [], []
    for rout in routs:
        for tag in CONDS:
            c = Condition.parse(tag)
            dk = cs.deck(c, "72n").replace("rload=500 rout=400", f"rload=500 rout={rout}")
            assert f"rout={rout}" in dk
            dk = spice.skip_output_before(spice.binary_output(dk), "12n")
            d = camp / f"rout{rout}_{tag}"
            d.mkdir(parents=True)
            (d / "stimuli.inc").write_text(cs.stimuli(0, 0))
            jobs.append((dk, d / "run", dict(files={"stimuli.inc": d / "stimuli.inc"}, meta=dict(rout=rout, condition=tag))))
            keys.append((rout, c))
    for ex in spice.run_many(jobs):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    exp = json.loads((cs.HERE / "serializer_expected.json").read_text())
    seq = serial.Sequence.from_expected(exp)
    bits = np.array(exp["bits"])
    rows = []
    for (rout, c), (_, d, _) in zip(keys, jobs):
        w = spice.Waves(d / "waveforms.raw")
        t = w.t
        con, _ = serial.check(t, w["dout"], seq, 128)
        free = serial.bit_mapping(t, w["dout"], seq)
        far, _ = serial.check(t, w["line_rx"], seq, 128)
        k = np.arange(64, 192)
        sgn = 2 * bits[k] - 1
        at = lambda frac: np.interp(seq.start_s + (k + frac + con["training_delay_ui"]) * UI, t, w["dout"]) * sgn
        win = (t > 30e-9) & (t < 64e-9)
        head = {}
        for name, tail, sat in (("latchA", "v(xtree.xr4_0.xla.tail)", "@m.xtree.xr4_0.xla.xtail.xmos.msky130_fd_pr__nfet_01v8[vdsat]"),
                                ("finalmux", "v(xtree.xr4_0.xm.tail)", "@m.xtree.xr4_0.xm.xtail.xmos.msky130_fd_pr__nfet_01v8[vdsat]")):
            head[name] = float(np.mean(w[tail][win] - w[sat][win]) * 1e3)
        power = float(np.mean(w["pmux"][win] + w["plogic"][win]) * 1e3) if "plogic" in w else float(np.mean(w["pmux"][win]) * 1e3)
        row = dict(rout=rout, condition=c.tag, contract=con, draft=serial.meets_draft(con), far=far, order_free=free,
                   swing_mv=dict(latchA=float(np.ptp(w["latchA"][win]) * 1e3), g3a=float(np.ptp(w["g3a"][win]) * 1e3),
                                 dout=float(np.ptp(w["dout"][win]) * 1e3)),
                   sag_mv=float(np.mean(at(0.25) - at(0.5)) * 1e3), tail_headroom_mv=head, serializer_power_mw=power)
        rows.append(row)
        print(f"rout {rout:3d} {c.tag:14s} draft {row['draft']!s:5s} margin {con['minimum_signed_margin_v']*1e3:6.1f} mV "
              f"spread {con['transition_spread_ui']:.3f} | far {far['minimum_signed_margin_v']*1e3:6.1f} mV | swing latch/g3/out "
              f"{row['swing_mv']['latchA']:.0f}/{row['swing_mv']['g3a']:.0f}/{row['swing_mv']['dout']:.0f} | sag {row['sag_mv']:+.1f} | "
              f"tail VDS-VDSAT latch {head['latchA']:+.0f} mux {head['finalmux']:+.0f} mV | P {power:.1f} mW", flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2, default=float))


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1:]] or [400, 330, 270])
