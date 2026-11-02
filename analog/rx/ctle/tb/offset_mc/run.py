"""RX CTLE input-referred offset from local mismatch (Monte Carlo, operating point).

    uv run python analog/rx/ctle/tb/offset_mc/run.py [--samples 200] [--cond tt_v1800_t27] [--eq 3] [--ideal-r]

serdes_rx_ctle_rc at input common mode 1.05 V, both inputs equal; the cell resistors (loads,
degeneration) as high_po devices unless --ideal-r (serdes_flow.rcorner.to_pdk), library section
<corner>_mm.  Offset = output difference / DC gain; the gain comes from the same deck without
mismatch at +-5 mV input.  Sampler-referred: the CTLE offset adds to the sampler input offset
(tb/../sampler/tb/offset_mc), both eat the signed eye margin.
"""
import argparse
import json
import time

from serdes_flow import mc, rcorner, spice, stats
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

RESULTS = ROOT / "results/analog/rx/ctle/offset_mc"


def netlist(c, section, eq, workdir, ideal_r):
    text = "\n".join([f"CTLE offset MC ({section})", f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {section}',
                      f'.include "{ROOT}/analog/common/devices/spice/sky130_primitives.spice"',
                      f'.include "{ROOT}/analog/common/devices/spice/cmos_logic.spice"',
                      f'.include "{ROOT}/analog/rx/ctle/spice/rx_ctle_rc.spice"',
                      f"Vdd vdd 0 {c.supply}", "Iref vdd vbias 50u", "Xref vbias vbias 0 0 serdes_nfet_lvt w=8 l=0.5 nf=4",
                      "Vcm cm 0 1.05", "Vdm dm 0 0", "Eip inp cm dm 0 .5", "Ein inn cm dm 0 -.5",
                      f"Veq0 eq0 0 {c.supply * (eq & 1)}", f"Veq1 eq1 0 {c.supply * (eq >> 1)}",
                      "Xeq inp inn op on eq0 eq1 vbias vdd 0 serdes_rx_ctle_rc", f".temp {c.temp}",
                      ".options reltol=1e-5 abstol=1p vntol=1u klu"])
    return text if ideal_r else rcorner.to_pdk(text, workdir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--cond", default="tt_v1800_t27")
    ap.add_argument("--eq", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--ideal-r", action="store_true")
    a = ap.parse_args()
    c = Condition.parse(a.cond)
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ("_idealr" if a.ideal_r else ""))
    # DC gain without mismatch: +-5 mV
    g = mc.deck(netlist(c, c.process, a.eq, camp, a.ideal_r), 1, analysis="dc Vdm -0.005 0.005 0.01\nlet dif=v(op)-v(on)",
                lets={"gain": "(dif[1]-dif[0])/0.01"})
    spice.run(g, camp / "gain", timeout_s=600)
    gain = mc.read(camp / "gain")[0]["gain"]
    jobs = [(mc.deck(netlist(c, f"{c.process}_mm", a.eq, camp, a.ideal_r), n, seed=s, analysis="op", lets={"vos": "v(op)-v(on)"}),
             camp / f"chunk{k:02d}", dict(timeout_s=1200)) for k, s, n in mc.chunks(a.samples, a.seed, per=100)]
    spice.run_many(jobs, workers=4, smoke=False)
    rows = mc.read_all([j[1] for j in jobs])
    vin = mc.column(rows, "vos") / gain * 1e3
    s = stats.summary(vin)
    lo, hi = stats.tolerance(vin)
    out = dict(condition=c.tag, eq=a.eq, pdk_resistors=not a.ideal_r, dc_gain=gain, samples=len(rows),
               input_offset_mv=s, tol3_mv=[lo, hi])
    print(f"{c.tag} EQ{a.eq} {'ideal R' if a.ideal_r else 'PDK R'}: DC gain {gain:.3f}; input offset sigma {s['std']:.2f} mV "
          f"(mean {s['mean']:+.2f}, 3-sigma tolerance {lo:+.1f}..{hi:+.1f} mV, n {len(rows)})")
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
