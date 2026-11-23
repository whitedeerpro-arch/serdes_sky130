"""LF precharge buffer (B2, serdes_ref_pbuf) charging the PLL loop filter from 0 V, over PVT x R corner.

    uv run python analog/bias/tb/pbuf_pvt/run.py [--codes 0,7,15] [--rcorners tt,ll,hh] [--workers 3]
    uv run python analog/bias/tb/pbuf_pvt/run.py --leak        # gates off: leakage out of the loop filter

analog/bias/spice/bias_dist.spice.  The loop filter is pll_loop_filter_precharge (Cf 2 pF,
Rz 6.5 kOhm as PDK high_po via rcorner.to_pdk, Ci 40 pF), both state nodes from 0 V; en rises at
10 ns.  One deck per library section and code; supply and temperature in the control block.
Per condition: the tap voltage (target), the buffer output error at 1.2 us (v(z) - tap), the time
from en until v(z) stays within 10 mV / 1 mV of its final value, the peak supply current.  The
precharge window of the start-up supervisor is 128 reference cycles = 512 ns.
--leak: operating point with en low and the integrator node held at 0.95 / 1.35 V: the current the off
LVT precharge gates and the disabled buffer draw from the loop filter (static phase offset of the PLL =
I_leak / I_cp * T_ref).
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import rcorner, spice
from serdes_flow.corners import PROCESS, SUPPLY_V, TEMP_C, Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_pbuf_pvt_ngspice.cir.in"
RESULTS = ROOT / "results/analog/bias/pbuf_pvt"
T_EN, STOP, WINDOW = 10e-9, 1.2e-6, 512e-9


def section(proc, rc):
    if rc == "tt":
        return proc
    return rc if proc == "tt" else f"{proc}_{rc}"


def deck(proc, rc, code, workdir):
    text = spice.render(TEMPLATE, **spice.corner_values(Condition(proc, 1.8, 27)), SECTION=section(proc, rc), CODE=code)
    text = rcorner.to_pdk(text, workdir)
    lines = [".control", "set num_threads=1", "set filetype=binary"]
    for v in SUPPLY_V:
        for t in TEMP_C:
            n = f"{proc}_{rc}_c{code:02d}_v{round(v * 1000)}_t{t}"
            lines += [f"option temp={t}", f"alter Vdd dc={v}", f"tran 1n {STOP:.4e} 0 2n", "let idd=-i(Vdd)",
                      f"write {n}.raw v(z) v(ctrl) v(xpb.tap) v(pref) idd", "destroy all"]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def leak_deck(proc):
    text = spice.render(TEMPLATE, **spice.corner_values(Condition(proc, 1.8, 27)), SECTION=proc, CODE=7)
    en = next(l for l in text.splitlines() if l.startswith("Ben "))
    ic = next(l for l in text.splitlines() if l.startswith(".ic "))
    text = text.replace(en, "Ven en 0 0\nVz z 0 1.1").replace(ic, "")
    lines = [".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale"]
    for v in SUPPLY_V:
        for t in TEMP_C:
            for vz in (0.95, 1.35):
                lines += [f"option temp={t}", f"alter Vdd dc={v}", f"alter Vz dc={vz}", "op", "let il=i(Vz)",
                          f"wrdata {proc}_v{round(v * 1000)}_t{t}_z{round(vz * 100)}.tsv il", "destroy all"]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def leak(workers):
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_leak")
    for ex in spice.run_many([(leak_deck(p), camp / p, dict(timeout_s=600)) for p in PROCESS], workers=workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}")
    rows = []
    for f in sorted(camp.glob("*/*.tsv")):
        l = f.read_text().split("\n")
        rows.append(dict(case=f.stem, il_na=float(l[1].split()[-1]) * 1e9))
    (camp / "summary.json").write_text(json.dumps(rows, indent=1))
    for r in sorted(rows, key=lambda r: -abs(r["il_na"]))[:6]:
        print(f"  {r['case']:24s} {r['il_na']:+9.3f} nA")
    worst = max(abs(r["il_na"]) for r in rows)
    print(f"{len(rows)} cases, worst {worst:.3f} nA -> static phase offset {worst * 1e-9 / 50e-6 * 4e-9 * 1e12:.3f} ps at 50 uA, 250 MHz")
    print(camp.relative_to(ROOT))


def settle(t, v, final, tol):
    bad = np.where(np.abs(v - final) > tol)[0]
    return float(t[bad[-1]] - T_EN) if len(bad) else 0.0


def analyse(raw):
    w = spice.Waves(raw)
    t, z, ctrl, tap, idd = w.t, w["v(z)"], w["v(ctrl)"], w["v(xpb.tap)"], w["idd"]
    end = t > STOP - 50e-9
    zf, tapf = float(np.mean(z[end])), float(np.mean(tap[end]))
    return dict(tap=tapf, z_final=zf, error_mv=(zf - tapf) * 1e3, ctrl_minus_z_mv=float(np.mean(ctrl[end]) - zf) * 1e3,
                t10_ns=settle(t, z, zf, 10e-3) * 1e9, t1_ns=settle(t, z, zf, 1e-3) * 1e9,
                ctrl_t10_ns=settle(t, ctrl, zf, 10e-3) * 1e9, idd_peak_ma=float(np.max(idd)) * 1e3,
                idd_end_ma=float(np.mean(idd[end])) * 1e3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="0,7,15")
    ap.add_argument("--rcorners", default="tt,ll,hh")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--leak", action="store_true")
    a = ap.parse_args()
    if a.leak:
        return leak(a.workers)
    codes = [int(x) for x in a.codes.split(",")]
    rcs = a.rcorners.split(",")
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = [(deck(p, rc, c, camp), camp / f"{p}_{rc}_c{c:02d}", dict(timeout_s=3600, meta=dict(process=p, rcorner=rc, code=c)))
            for p in PROCESS for rc in rcs for c in codes]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}")
    rows = []
    for p in PROCESS:
        for rc in rcs:
            for c in codes:
                for v in SUPPLY_V:
                    for t in TEMP_C:
                        raw = camp / f"{p}_{rc}_c{c:02d}" / f"{p}_{rc}_c{c:02d}_v{round(v * 1000)}_t{t}.raw"
                        if raw.exists():
                            rows.append(dict(process=p, rcorner=rc, code=c, supply=v, temp=t, **analyse(raw)))
    (camp / "summary.json").write_text(json.dumps(rows, indent=1))
    print(f"{len(rows)} conditions x codes")
    for c in codes:
        sel = [r for r in rows if r["code"] == c]
        col = lambda k: np.array([r[k] for r in sel])
        print(f"  code {c:2d}: tap {col('tap').min():.4f}..{col('tap').max():.4f} V, error {col('error_mv').min():+.1f}..{col('error_mv').max():+.1f} mV,"
              f" t10 <= {col('t10_ns').max():.0f} ns, t1 <= {col('t1_ns').max():.0f} ns (window {WINDOW * 1e9:.0f}),"
              f" ctrl t10 <= {col('ctrl_t10_ns').max():.0f} ns, peak idd {col('idd_peak_ma').max():.2f} mA")
    late = [r for r in rows if r["t1_ns"] > WINDOW * 1e9]
    print(f"  {len(late)} cases slower than the window to 1 mV")
    for r in sorted(late, key=lambda r: -r["t1_ns"])[:8]:
        print(f"    {r['process']}_{r['rcorner']} code {r['code']} {r['supply']} V {r['temp']} C: t10 {r['t10_ns']:.0f} ns, t1 {r['t1_ns']:.0f} ns")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
