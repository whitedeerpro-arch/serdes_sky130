"""Ideal-edge replay of native r4 clock positions plus one common re-centring correction."""
import json, time, importlib.util
import numpy as np
from serdes_flow import spice, serial
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
spec = importlib.util.spec_from_file_location("cs", ROOT / "analog/tx/serializer/tb/clock_states/run.py")
cs = importlib.util.module_from_spec(spec); spec.loader.exec_module(cs)
UI = 250e-12
# Fine offsets of the native r4 clocks from the r2 calibration (UI, relative to 250 MHz), and the
# detected start state at each corner (from the native probes).
native = {"tt_v1800_t27": ((-0.165, -0.332, -0.374), (3, 1)), "ss_v1650_t-40": ((-0.241, -0.522, -0.625), (1, 1)),
          "ss_v1650_t85": ((-0.312, -0.646, -0.788), (3, 0)), "fs_v1650_t85": ((-0.250, -0.577, -0.756), (2, 1))}
# Centre each adjacent-rank relation on the middle of its corner spread.
o = np.array([v[0] for v in native.values()])
rel = np.column_stack([o[:, 0], o[:, 1] - o[:, 0], o[:, 2] - o[:, 1]])
mid = (rel.max(0) + rel.min(0)) / 2
c500 = -mid[0]; c1g = c500 - mid[1]; c2g = c1g - mid[2]
print("correction (UI) 500 %+.3f 1g %+.3f 2g %+.3f; adjacent-relation residual <= %s UI" % (c500, c1g, c2g, np.round((rel.max(0) - rel.min(0)) / 2, 3)))
SRC = {"500": ("Vsrc500p", "Vsrc500n", 2e-9), "1g": ("Vsrc1gp", "Vsrc1gn", 1e-9), "2g": ("Vsrc2gp", "Vsrc2gn", 0.5e-9)}
camp = ROOT / "results/analog/tx/serializer/clock_states" / ("recenter_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
jobs = []
for tag, (off, (s500, s1g)) in native.items():
    fine = dict(zip(("500", "1g", "2g"), (off[0] + c500, off[1] + c1g, off[2] + c2g)))
    lines = []
    for line in cs.stimuli(s500, s1g, remap=True).splitlines():
        name = line.split(" ", 1)[0]
        for k, (p, n, per) in SRC.items():
            if name in (p, n):
                head, body = line.split("PWL(", 1); tok = body.rstrip(")").split()
                dt = (fine[k] * UI) % per
                for i in range(2, len(tok), 2): tok[i] = f"{float(tok[i]) + dt:.14e}"
                line = head + "PWL(" + " ".join(tok) + ")"
        lines.append(line)
    d = camp / tag; d.mkdir(parents=True); (d / "stimuli.inc").write_text("\n".join(lines) + "\n")
    c = Condition.parse(tag)
    jobs.append((spice.skip_output_before(spice.binary_output(cs.deck(c, "72n")), "12n"), d / "run",
                 dict(files={"stimuli.inc": d / "stimuli.inc"}, meta=dict(fine_ui=fine, state=[s500, s1g]))))
    print(tag, "positions vs r2 calibration after correction:", {k: round(v, 3) for k, v in fine.items()})
for ex in spice.run_many(jobs): assert ex.ok, ex.log_failures
seq = serial.Sequence.from_expected(json.loads((cs.HERE / "serializer_expected.json").read_text()))
for tag in native:
    w = spice.Waves(camp / tag / "run/waveforms.raw")
    con, _ = serial.check(w.t, w["dout"], seq, 128); far, _ = serial.check(w.t, w["line_rx"], seq, 128)
    print(f"{tag:14s} draft {serial.meets_draft(con)!s:5s} margin {con['minimum_signed_margin_v']*1e3:6.1f} mV spread {con['transition_spread_ui']} far {far['minimum_signed_margin_v']*1e3:.1f} mV")
