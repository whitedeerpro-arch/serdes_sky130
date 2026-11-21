"""Verify PDK-mapped RX CTLE (serdes_rx_ctle_pdk) over 45-corner PVT x 4 EQ codes.

    uv run python analog/rx/cmos_rx/tb/ctle/verify_ctle.py [stress | all | tags...] [--cm 0.8,0.9] [--cload 80f] [--resume DIR]

One ngspice run per process corner (max 2 concurrent workers) switching temp/VDD/EQ/CM in .control.
Checks BIAS v2 compatibility (serdes_bias_ctle_v2: 50 uA -> 8/0.5 LVT diode), tail & input headroom
(>= 50 mV), output CM range (for direct DC coupling into rx_dt_sampler), LF gain, 2 GHz gain,
peaking (dB), -3 dB BW, and power.
"""
import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import STRESS, Condition, grid45
from serdes_flow.project import ROOT

RESULTS = ROOT / "results/analog/rx/cmos_rx/ctle"
HEADROOM_GATE = 0.05

TEMPLATE = """\
RX CTLE PDK-mapped AC/DC characterization; static code @EQ_CODE@, input CM @INPUT_CM@
.lib "@MODEL_LIBRARY@" @CORNER@
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_primitives.spice"
.include "@PROJECT_ROOT@/analog/common/bias/spice/bias_v2.spice"
.include "@PROJECT_ROOT@/analog/rx/cmos_rx/spice/rx_ctle_pdk.spice"
Vdd vdd 0 @SUPPLY@
* BIAS v2 CTLE current (50 uA nominal) into real serdes_bias_ctle_v2 diode
Iref vdd vbias 50u
Xbias vbias 0 serdes_bias_ctle_v2
Vcm cm 0 @INPUT_CM@
Vdm dm 0 DC 0 AC 1
Eip inp cm dm 0 .5
Ein inn cm dm 0 -.5
Veq0 eq0 0 @EQ0_V@
Veq1 eq1 0 @EQ1_V@
Xterm inp inn cm 0 serdes_rx_term_pdk
Xeq inp inn op on eq0 eq1 vbias vdd 0 serdes_rx_ctle_pdk
* Load represents 8 quarter-rate rx_dt_sampler slicers (~10 fF each) or custom CLOAD
Cop op 0 @CLOAD@
Con on 0 @CLOAD@
.temp @TEMP_C@
.options reltol=1e-4 abstol=1p vntol=1u klu
.save v(inp) v(inn) v(op) v(on) v(cm) v(vdd) v(vbias) v(xeq.sp) v(xeq.sn) i(Vdd) i(Eip) i(Ein)
.control
set wr_singlescale
set wr_vecnames
@CASES@
quit
.endc
.end
"""


def read_tsv(path: Path):
    lines = path.read_text().strip().split("\n")
    names = lines[0].split()
    data = np.atleast_2d(np.loadtxt(lines[1:]))
    out, i = {}, 0
    while i < len(names):
        if i + 1 < len(names) and names[i + 1] == names[i]:
            out[names[i]] = data[:, i] + 1j * data[:, i + 1]
            i += 2
        else:
            out[names[i]] = data[:, i]
            i += 1
    return out


def case_name(c: Condition, code: int, cm: float) -> str:
    return f"{c.tag}_cm{round(cm * 1000)}_eq{code}"


def build_deck(cases, cload: str) -> str:
    c0, code0, cm0 = cases[0]
    blocks = []
    for c, code, cm in cases:
        name = case_name(c, code, cm)
        blocks.append("\n".join([
            f"* case {name}",
            f"option temp={c.temp}",
            f"alter Vdd dc={c.supply}",
            f"alter Veq0 dc={c.supply * (code & 1)}",
            f"alter Veq1 dc={c.supply * (code >> 1)}",
            f"alter Vcm dc={cm}",
            "op",
            "let cmout=(v(op)+v(on))/2",
            "let pcore=-v(vdd)*i(Vdd)",
            "let vdsat_tail=@m.xeq.xtp.xmos.msky130_fd_pr__nfet_01v8_lvt[vdsat]",
            "let vds_in=v(on)-v(xeq.sp)",
            "let vdsat_in=@m.xeq.xip.xmos.msky130_fd_pr__nfet_01v8_lvt[vdsat]",
            "let id_tail=@m.xeq.xtp.xmos.msky130_fd_pr__nfet_01v8_lvt[id]",
            f"wrdata {name}_op.tsv v(vbias) v(xeq.sp) v(xeq.sn) cmout pcore vdsat_tail vds_in vdsat_in id_tail",
            "ac dec 100 1meg 20g",
            "let gain=v(op,on)/v(inp,inn)",
            f"wrdata {name}_ac.tsv gain",
            "destroy all",
        ]))
    return spice.render(
        TEMPLATE,
        **spice.corner_values(c0),
        EQ_CODE=code0,
        INPUT_CM=cm0,
        EQ0_V=c0.supply * (code0 & 1),
        EQ1_V=c0.supply * (code0 >> 1),
        CLOAD=cload,
        CASES="\n".join(blocks),
    )


def analyse(d: Path, name: str) -> dict:
    op = read_tsv(d / f"{name}_op.tsv")
    g = {k: float(np.real(v[0])) for k, v in op.items()}
    ac = read_tsv(d / f"{name}_ac.tsv")
    f = np.real(ac[list(ac)[0]])
    gain = np.abs(ac["gain"])
    db = 20.0 * np.log10(np.maximum(gain, 1e-12))
    g0 = float(db[0])
    g2 = float(np.interp(2e9, f, db))
    below = np.where(db < g0 - 3.0)[0]
    bw = float(f[below[0]]) if len(below) else float("nan")
    head_tail = g["v(xeq.sp)"] - g["vdsat_tail"]
    head_in = g["vds_in"] - g["vdsat_in"]
    return dict(
        vsrc=g["v(xeq.sp)"],
        headroom_tail=head_tail,
        headroom_in=head_in,
        cm_out=g["cmout"],
        id_tail_ua=g["id_tail"] * 1e6,
        power_mw=g["pcore"] * 1e3,
        gain_lf_db=g0,
        gain_2g_db=g2,
        peaking_2g_db=g2 - g0,
        peak_max_db=float(db.max() - g0),
        bw3_ghz=bw / 1e9,
        ok=bool(head_tail >= HEADROOM_GATE and head_in >= HEADROOM_GATE),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["all"])
    ap.add_argument("--cm", default="1.05")
    ap.add_argument("--cload", default="80f")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    assert 1 <= a.workers <= 2, "Max 2 concurrent ngspice workers allowed"

    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    cms = [float(x) for x in a.cm.split(",")]
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)

    keys = [(c, code, cm) for c in conds for cm in cms for code in range(4)]
    by_proc = {}
    for k in keys:
        by_proc.setdefault(k[0].process, []).append(k)

    jobs = [
        (build_deck(cases, a.cload), camp / proc,
         dict(meta=dict(process=proc, cload=a.cload, cases=[case_name(*k) for k in cases])))
        for proc, cases in by_proc.items()
    ]
    todo = []
    for j in jobs:
        if (j[1] / "execution.json").exists():
            continue
        if j[1].exists() and not a.analyse_only:
            shutil.rmtree(j[1])
        todo.append(j)

    print(f"CTLE PDK: {len(keys)} cases in {len(jobs)} decks (cload={a.cload}): {len(jobs)-len(todo)} kept, {len(todo)} to run", flush=True)
    for ex in ([] if a.analyse_only else spice.run_many(todo, workers=a.workers, smoke=False)):
        assert ex.ok, (ex.run_dir, ex.log_failures)

    rows = [dict(condition=c.tag, eq=code, cm=cm, **analyse(camp / c.process, case_name(c, code, cm))) for c, code, cm in keys]
    (camp / "summary.json").write_text(json.dumps(rows, indent=1, default=float))

    # Print summary by EQ code across all corners + key corners
    ok_all = all(r["ok"] for r in rows)
    print(f"\n=== RX CTLE PDK Summary ({len(conds)} corners, cload={a.cload}) | ALL HEADROOM OK: {ok_all} ===")
    for eq in range(4):
        sub = [r for r in rows if r["eq"] == eq]
        print(
            f"EQ={eq}: LF={min(r['gain_lf_db'] for r in sub):+5.2f}..{max(r['gain_lf_db'] for r in sub):+5.2f} dB | "
            f"2G={min(r['gain_2g_db'] for r in sub):+5.2f}..{max(r['gain_2g_db'] for r in sub):+5.2f} dB | "
            f"Peak@2G={min(r['peaking_2g_db'] for r in sub):+5.2f}..{max(r['peaking_2g_db'] for r in sub):+5.2f} dB | "
            f"BW={min(r['bw3_ghz'] for r in sub):4.2f}..{max(r['bw3_ghz'] for r in sub):4.2f} GHz | "
            f"CMout={min(r['cm_out'] for r in sub):.3f}..{max(r['cm_out'] for r in sub):.3f} V | "
            f"P={min(r['power_mw'] for r in sub):.2f}..{max(r['power_mw'] for r in sub):.2f} mW"
        )
    print(f"Min headroom: tail={min(r['headroom_tail'] for r in rows)*1e3:.1f} mV, in={min(r['headroom_in'] for r in rows)*1e3:.1f} mV")
    print(f"Results: {camp.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
