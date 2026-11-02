"""GTKWave view of one readout_deser case: clocks, counter / strobes, converted lanes, the 16-UI words.

    uv run python analog/rx/sampler/tb/readout_deser/view.py CAMPAIGN [CONDITION] [--code 20] [--open]

Writes <case dir>/view/<case>.vcd and view.tcl.  Groups: word clock and strobes (logic), clock phases
(logic + ckq analog), converted CML->CMOS lanes (analog), the word bus data[15:0] in chronological
order (bit 0 oldest, combinational from the 32 outputs by the EXPECTED map), the word sampled at w
rising next to the PRBS7 word expected at the fitted start (run.py word_check) and a mismatch flag,
then the 32 raw outputs.  --open starts GTKWave detached (same GTK environment fix as
verification/mixed_signal/view.sh).
"""
import argparse
import importlib.util
import os
import subprocess
from pathlib import Path

import numpy as np

from serdes_flow import eye, spice, vcd
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

_s = importlib.util.spec_from_file_location("readout_deser", Path(__file__).resolve().parent / "run.py")
run = importlib.util.module_from_spec(_s)
_s.loader.exec_module(run)
sp = run.sp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign")
    ap.add_argument("condition", nargs="?", default="tt_v1800_t27")
    ap.add_argument("--code", type=int, default=20)
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()
    camp = ROOT / a.campaign
    name = f"{a.condition}_c{a.code:02d}"
    raw = spice.case_output(camp, a.condition, f"{name}.raw")
    if raw is None:
        raise SystemExit(f"no waveform for {name} in {camp}")
    w = spice.Waves(raw)
    t = w.t
    vdd = float(np.median(w["v(vdd)"]))
    outs = run.outputs()
    lv = {o: vcd.Bit(o, w[f"v({o})"], vdd).levels() for o in outs}
    data_bits = {i: o for o, i in run.EXPECTED.items()}
    edge_bits = {run.EXPECTED[f"{run.EDGE_OF[o.split('_')[0]]}_{o.split('_')[1]}"]: o for o in outs if o.split("_")[0] in run.EDGE_OF}
    data_bus = sum(lv[data_bits[i]] << i for i in range(16))
    edge_bus = sum(lv[edge_bits[i]] << i for i in range(16))

    # words at w rising: sampled value, and the PRBS7 word expected at the fitted start
    bits = eye.prbs7(sp.link.NBITS)
    r = run.analyse(raw, run.Condition.parse(a.condition), a.code, bits)
    we, wp = crossings(t, w["v(w)"], level=vdd / 2)
    wr = we[wp > 0]
    t_from = sp.link.T0 + (sp.link.WARM + 6) * sp.link.UI
    n0 = int(np.sum(wr < t_from))                 # w edges before the analysed window
    word, expect, bad = np.zeros(len(t), np.int64), np.zeros(len(t), np.int64), np.zeros(len(t), np.int64)
    for k, x in enumerate(wr):
        i = np.searchsorted(t, x)
        sampled = int(data_bus[min(i, len(t) - 1)])
        j = r["start"] + 16 * (k - n0)
        graded = k >= n0 and j + 16 <= len(bits)      # same words as run.py grades; others show 0
        exp = sum(int(bits[j + b]) << b for b in range(16)) if graded else 0
        word[i:], expect[i:] = sampled, exp
        bad[i:] = int(graded and sampled != exp)

    sig = [vcd.Bit("w", w["v(w)"], vdd), vcd.Bit("j0", w["v(xro.xwc.j0)"], vdd), vcd.Bit("j1", w["v(xro.xwc.j1)"], vdd)]
    sig += [vcd.Bit(s, w[f"v(xro.{s})"], vdd) for s in ("st_q", "st_m", "st_qb", "st_mb")]
    sig += [vcd.Bit(c, w[f"v(xro.{c})"], vdd) for c in ("ckq", "ckm", "ckqb", "ckmb")] + [vcd.Real("ckq_v", w["v(xro.ckq)"])]
    sig += [vcd.Real(f"r{l}", w[f"v(xro.r{l})"]) for l in run.LANES]
    sig += [vcd.Bus("data", 16, data_bus), vcd.Bus("edge_after", 16, edge_bus), vcd.Bus("word_at_w", 16, word),
            vcd.Bus("word_expected", 16, expect), vcd.Bus("mismatch", 1, bad)]
    sig += [vcd.Bus(o, 1, lv[o]) for o in outs]
    d = raw.parent / "view"
    d.mkdir(exist_ok=True)
    path = vcd.write(d / f"{name}.vcd", t, sig)
    groups = [("word clock / counter / strobes", [(s, None) for s in ("w", "j0", "j1", "st_q", "st_m", "st_qb", "st_mb")]),
              ("clock phases", [(c, None) for c in ("ckq", "ckm", "ckqb", "ckmb")] + [("ckq_v", "analog")]),
              ("converted lanes (analog)", [(f"r{l}", "analog") for l in run.LANES]),
              ("words: bit0 oldest", [("data", "hex"), ("edge_after", "hex"), ("word_at_w", "hex"),
                                      ("word_expected", "hex"), ("mismatch", None)]),
              ("raw outputs <lane>_<k>", [(o, None) for o in outs])]
    tcl = d / "view.tcl"
    tcl.write_text(vcd.tcl_view(groups, markers=[("A", t_from * 1e12, "analysis window")]))
    print(f"{path.relative_to(ROOT)}  ({path.stat().st_size / 1e6:.1f} MB)  data/edge errors {r['data_errors']}/{r['edge_errors']}")
    cmd = ["gtkwave", str(path), "--script", str(tcl)]
    print("view: env -u GTK_PATH GTK_MODULES= GTK2_RC_FILES=/dev/null " + " ".join(cmd))
    if a.open:
        env = {k: v for k, v in os.environ.items() if k != "GTK_PATH"}
        env.update(GTK_MODULES="", GTK2_RC_FILES="/dev/null")
        with open(d / "gtkwave.log", "w") as log:
            subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


if __name__ == "__main__":
    main()
