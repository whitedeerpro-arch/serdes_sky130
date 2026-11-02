"""RX CMOS readout over PVT: C2 replay -> CTLE -> PI-clocked samplers -> CMOS pair alignment.

    uv run python analog/rx/sampler/tb/readout_pvt/pvt.py [stress | tags...] --codes-from SAMPLER_CAMPAIGN
        [--cells old,r4] [--dut stock|ac] [--param K=V ...] [--code N] [--bc ID] [--resume C] [--analyse-only]

The PI code per condition is the centre of the sampler window measured by sampler/tb/link_pvt
(SAMPLER_CAMPAIGN summary).  Two alignment cells: the current serdes_rx_cmos_pair_align (clock
through serdes_cml_to_cmos) and the r4 variant (serdes_cml_to_cmos_r4, the PLL I-04 fix).
Decoding: the aligned CMOS outputs ad0/ad1 are read just before each next rising edge of the
CMOS clock `ck`; the pairs are concatenated (either order) and compared with the PRBS7 at the
best bit offset.  Pass = no error.  --dut / --param select the sampler variant as in link_pvt (default
stock); --code N uses one PI code for every condition instead of the campaign centres (a sampler
window that passes at every code reports centre 0, which sits next to the eye crossing; code 20
is the centre of every full sweep so far).
"""
import argparse
import importlib.util
import json
import shutil
import time
from pathlib import Path

import numpy as np

from serdes_flow import boundary, eye, spice
from serdes_flow.corners import STRESS, Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
_s = importlib.util.spec_from_file_location("sampler_pvt", ROOT / "analog/rx/sampler/tb/link_pvt/pvt.py")
sp = importlib.util.module_from_spec(_s)
_s.loader.exec_module(sp)
TEMPLATE = HERE / "tb_rx_readout_link_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/sampler/readout_pvt"
CELLS = {"old": "serdes_rx_cmos_pair_align", "r4": "serdes_rx_cmos_pair_align_r4"}


def deck(cases, cell, dut_text=sp.DUTS["stock"]):
    c0, code0 = cases[0]
    ctl = "\n".join(f"{k} {k[1]}{k[2]} 0 {v}" for k, v in sp.pi.bits(code0, c0.supply).items())
    text = spice.render(TEMPLATE, **spice.corner_values(c0), EQ0_V=c0.supply, EQ1_V=c0.supply,
                        CONTROL_SOURCES=ctl, ALIGN_CELL=CELLS[cell], DUT=dut_text, CASES="@CASES@")
    blocks = []
    for c, code in cases:
        n = sp.case_name(c, code)
        blocks.append("\n".join([f"* case {n}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}", f"alter Vref dc={c.supply}",
                                 f"alter Veq0 dc={c.supply}", f"alter Veq1 dc={c.supply}"]
                                + [f"alter {k} dc={v}" for k, v in sp.pi.bits(code, c.supply).items()]
                                + [f"tran 2p {sp.link.STOP:.4e} {sp.link.SAVE_FROM:.4e} 4p",
                                   "let ckd=v(xdut.cdp)-v(xdut.cdn)", "let d0=v(d0p)-v(d0n)", "let d1=v(d1p)-v(d1n)",
                                   "let ckc=v(xalign.ckp)-v(xalign.ckn)", "let power=-v(vdd)*i(Vdd)",
                                   f"write {n}.raw ckd d0 d1 ckc v(ck) v(ad0) v(ad1) v(vdd) power", "destroy all"]))
    return text.replace("@CASES@", "\n".join(blocks))


def analyse_case(d, c, code, bits):
    w = spice.Waves(Path(d) / f"{sp.case_name(c, code)}.raw")
    vdd = float(np.mean(w["v(vdd)"]))
    e, pol = crossings(w.t, w["v(ck)"], level=vdd / 2)
    rises = e[pol > 0]
    t_from = sp.link.T0 + (sp.link.WARM + 6) * sp.link.UI
    pairs = [(int(np.interp(b - 50e-12, w.t, w["v(ad0)"]) > vdd / 2), int(np.interp(b - 50e-12, w.t, w["v(ad1)"]) > vdd / 2))
             for a, b in zip(rises[:-1], rises[1:]) if a >= t_from]
    best = None
    for order in ((0, 1), (1, 0)):
        seq = [p[i] for p in pairs for i in order]
        nerr, j0 = sp.errors(seq, bits)
        if best is None or nerr < best[0]:
            best = (nerr, j0, order)
    sel = w.t > t_from
    ck_lo, ck_hi = float(np.min(w["v(ck)"][sel])), float(np.max(w["v(ck)"][sel]))
    return dict(condition=c.tag, code=code, errors=int(best[0]), pairs=len(pairs), order=list(best[2]),
                ck_cycles=int(len(rises)), ck_low_v=ck_lo, ck_high_v=ck_hi,
                conv_out_pp=float(np.ptp(w["ckc"][sel])), power_mw=float(np.mean(w["power"][sel]) * 1e3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["stress"])
    ap.add_argument("--codes-from")
    ap.add_argument("--code", type=int)
    ap.add_argument("--dut", choices=sorted(sp.DUTS), default="stock")
    ap.add_argument("--param", action="append", default=[])
    ap.add_argument("--cells", default="old,r4")
    ap.add_argument("--bc", default="rx_c2_far_nominal@ctle_rc")
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    conds = STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    if a.code is not None:
        centre = {c.tag: a.code for c in conds}
    else:
        centre = {r["condition"]: r["centre_code"] for r in json.loads((ROOT / a.codes_from / "summary.json").read_text())["rows"]}
    dut_text = sp.dut(a.dut, dict(p.split("=", 1) for p in a.param))
    cells = a.cells.split(",")
    boundary.check_load(a.bc, sp.replay.signature())
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)
    stim, _ = sp.replay.stimuli(a.bc)
    (camp / "stimuli.inc").write_text(stim)
    bits = eye.prbs7(sp.link.NBITS)
    keys = [(c, centre[c.tag]) for c in conds if centre.get(c.tag) is not None]
    jobs = []
    for cell in cells:
        by_proc = {}
        for k in keys:
            by_proc.setdefault(k[0].process, []).append(k)
        jobs += [(deck(cases, cell, dut_text), camp / f"{cell}_{proc}", dict(files={"stimuli.inc": camp / "stimuli.inc"},
                                                                     meta=dict(cell=CELLS[cell], bc=a.bc, dut=dut_text, cases=[sp.case_name(*k) for k in cases])))
                 for proc, cases in by_proc.items()]
    todo = []
    for j in jobs:
        if (j[1] / "execution.json").exists():
            continue
        if j[1].exists() and not a.analyse_only:
            shutil.rmtree(j[1])
        todo.append(j)
    print(f"{len(keys)} conditions x {len(cells)} cells in {len(jobs)} decks: {len(todo)} to run", flush=True)
    for ex in ([] if a.analyse_only else spice.run_many(todo, workers=4, smoke=False)):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    print(f"{'condition':15s} code | " + " | ".join(f"{cell}: errors/pairs, ck low..high V, converter output pp mV" for cell in cells))
    for c, code in keys:
        rs = {cell: analyse_case(camp / f"{cell}_{c.process}", c, code, bits) for cell in cells}
        rows.append(dict(condition=c.tag, code=code, cells=rs))
        print(f"{c.tag:15s} {code:4d} | " + " | ".join(
            f"{r['errors']:2d}/{r['pairs']}, {r['ck_low_v']:.2f}..{r['ck_high_v']:.2f}, {r["conv_out_pp"]*1e3:.0f}" for r in rs.values()))
    (camp / "summary.json").write_text(json.dumps(dict(bc=a.bc, codes_from=a.codes_from, code=a.code, dut=dut_text, rows=rows), indent=1, default=float))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
