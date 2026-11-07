"""TX clock distribution v3 (synchronous counter) on the native r5 4-bit PLL frontend, real bias and PDK resistors.

    uv run python analog/tx/serializer/tb/native_clock/r5_v3.py probe cond:passive ... [--stop 46e-9] [--workers 4] [--dist-cfg JSON]
    uv run python analog/tx/serializer/tb/native_clock/r5_v3.py probe --resume CAMPAIGN [--analyse-only]

Open loop at the code and Vctrl of config/pll_code_table.json (no replay of recorded taps: the frontend and the distribution are in one deck, so a
resistor corner and the bias reach both).  Static data.  Reports the VCO frequency, the counter's function and timing (as clock_replay/counter.py),
the clock at the counter's gates against what tb/div2_map needs (215 mVpp), select-clock positions against the r2 targets, and clock power.
"""
import argparse
import importlib.util
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
RESULTS = ROOT / "results/analog/tx/serializer/native_r5_v3"
TABLE = ROOT / "config/pll_code_table.json"


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


native = _load("native_clock", HERE / "run.py")
counter = _load("counter", HERE.parent / "clock_replay" / "counter.py")
dist_v3 = counter.dist_v3


def deck(c, rc, code, vctrl, stop, save_from, dist_cfg, camp):
    text = spice.render(HERE / "tb_native_tx_ngspice.cir.in", **spice.corner_values(c), CODE=code, VCTRL=vctrl, STOP=f"{stop:.4e}", MAX_STEP="4p", INITIAL_STATE="", TAIL_SCALE=6, WSF=80,
                        WSELECT=96, DRIVER_FILE="cml_line_driver_lowvt_enable.spice", DRIVER_CELL="serdes_tx_cml_line_driver_lowvt_enable", DRIVER_PARAMS="wgatep=32", **native.trims())
    vecs = dist_v3.probe_vectors()
    def rep(a, b):
        nonlocal text
        assert text.count(a) == 1, a
        text = text.replace(a, b)
    rep(f'.include "{ROOT}/analog/pll/top/spice/clock_frontend_r4.spice"', f'.include "{ROOT}/analog/pll/vco/spice/cap_bank_4b.spice"\n.include "{ROOT}/analog/pll/vco/spice/vco_ring4_4b.spice"\n.include "{ROOT}/analog/pll/top/spice/clock_frontend_r5.spice"')
    rep(f'.include "{native.R2_DIST}"', dist_v3.netlist(dist_cfg))                      # inline: its includes must reach rcorner.to_pdk
    rep("Vcode0 cfg0 0 {(code-2*floor(code/2))*supply}", f"Vcode0 cfg0 0 {(code >> 0 & 1) * c.supply}")
    rep("Vcode1 cfg1 0 {(floor(code/2)-2*floor(code/4))*supply}", f"Vcode1 cfg1 0 {(code >> 1 & 1) * c.supply}")
    rep("Vcode2 cfg2 0 {floor(code/4)*supply}", f"Vcode2 cfg2 0 {(code >> 2 & 1) * c.supply}\nVcode3 cfg3 0 {(code >> 3 & 1) * c.supply}")
    rep("Xpll ctrl cfg0 cfg1 cfg2 vbias_pll", "Xpll ctrl cfg0 cfg1 cfg2 cfg3 vbias_pll")
    rep("p32p p32n pll_clock_frontend_r4", "p32p p32n pll_clock_frontend_r5")
    rep("wrdata waveforms.tsv ", "wrdata waveforms.tsv " + " ".join(vecs) + " ")
    rep(".control\n", ".save " + " ".join(vecs) + "\n.control\n")
    text = spice.skip_output_before(spice.binary_output(text), save_from)
    camp.mkdir(parents=True, exist_ok=True)
    return bias.section(rcorner.to_pdk(bias.real(text, supply="vcore"), camp), c.process, rc)


def analyse(run):
    w = spice.Waves(run / "waveforms.raw")
    if not np.isfinite(w.data).all():
        raise ValueError("nonfinite native waveform")
    t = w.t
    sel = t > t[-1] - 20e-9
    b = w["pb0"]
    e, p = crossings(t[sel], b[sel])
    r = e[p > 0]
    if len(r) < 4:
        raise ValueError("native source has fewer than four rising edges")
    f0 = (len(r) - 1) / (r[-1] - r[0])
    counter.WINDOW = (float(t[-1] - 20e-9), float(t[-1] - 0.5e-9))
    c = counter.check(w)
    pos = counter.positions(w, ui=1 / (2 * f0))
    ck = (w["v(xclocks.xcnt.ckp)"] - w["v(xclocks.xcnt.ckn)"])[sel]
    cm = ((w["v(xclocks.xcnt.ckp)"] + w["v(xclocks.xcnt.ckn)"]) / 2)[sel]
    amp = {k: float(np.ptp(w[v][sel])) for k, v in counter.replay.SER_VEC.items()}
    return dict(f0=float(f0), b0_pp=float(np.ptp(b[sel])), counter=c, position_error_ui=pos, ck_pp=float(np.ptp(ck)), ck_cm=float(np.mean(cm)), serializer_pp=amp, pclock_w=float(np.mean(w["pclock"][sel])))


def summarize(cases, output):
    """Save partial progress even when some decks have no complete waveform."""
    rows = {}
    for point, case, stop in cases:
        wave = spice.case_output(case, "run", "waveforms.raw", stop)
        attempts = sorted(case.glob("run*/execution.json"), key=lambda p: p.stat().st_mtime)
        ex = json.loads(attempts[-1].read_text()) if attempts else {}
        row = dict(state="missing", t_end_s=stop, execution=ex)
        if wave is not None:
            source_ex = wave.parent / "execution.json"
            if source_ex.exists():
                row["execution"] = json.loads(source_ex.read_text())
            try:
                row.update(state="measured", run=str(wave.parent.relative_to(ROOT)), metrics=analyse(wave.parent))
            except (ValueError, IndexError, KeyError) as err:
                row.update(state="analysis_error", error=str(err))
        elif ex.get("timed_out"):
            row["state"] = "timeout"
        rows[point] = row
    output.mkdir(parents=True, exist_ok=True)
    temp = output / "summary.json.tmp"
    temp.write_text(json.dumps(dict(rows=rows), indent=1, default=float, allow_nan=False) + "\n")
    temp.replace(output / "summary.json")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("probe",))
    ap.add_argument("points", nargs="*", help="cond:passive")
    ap.add_argument("--stop", type=float)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dist-cfg")
    ap.add_argument("--resume", help="reuse the original decks and stimuli; run only missing cases")
    ap.add_argument("--analyse-only", action="store_true", help="requires --resume; never starts ngspice")
    ap.add_argument("--case-timeout", type=float, default=3600)
    a = ap.parse_args()
    if not 1 <= a.workers <= 4:
        ap.error("--workers must be 1..4")
    if a.analyse_only and not a.resume:
        ap.error("--analyse-only requires --resume")
    if a.resume and (a.stop is not None or a.dist_cfg is not None):
        ap.error("resume preserves the original decks; use a new campaign to change --stop/--dist-cfg")
    jobs, cases = [], []
    if a.resume:
        camp = ROOT / a.resume
        if not camp.is_dir():
            ap.error(f"campaign does not exist: {camp}")
        decks = sorted(camp.glob("*/run/tb.cir"))
        available = {f"{p.parents[1].name.rsplit('_', 1)[0]}:{p.parents[1].name.rsplit('_', 1)[1]}": p for p in decks}
        points = a.points or list(available)
        if not points or set(points) - available.keys():
            ap.error("resume points must have original run/tb.cir decks")
        for point in points:
            original = available[point]
            d = original.parents[1]
            text = original.read_text()
            stop = spice.spice_number(re.search(r"^\s*tran\s+\S+\s+(\S+)", text, re.M)[1])
            cases.append((point, d, stop))
            if not a.analyse_only and spice.case_output(d, "run", "waveforms.raw", stop) is None:
                jobs.append((text, spice.next_run_dir(d, "run"), dict(files={"stimuli.inc": d / "stimuli.inc"},
                             timeout_s=a.case_timeout, meta=dict(point=point, resumed_from=str(original.relative_to(ROOT))))))
    else:
        if not a.points:
            ap.error("provide cond:passive points or --resume")
        stop = a.stop if a.stop is not None else 46e-9
        if stop < 40e-9:
            ap.error("--stop must be >=40 ns for the saved 20 ns measurement window")
        table = json.loads(TABLE.read_text())["table"]
        camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        camp.mkdir(parents=True, exist_ok=False)
        bits = json.loads(native.EXPECTED.read_text())["bits"]
        static = native.stimuli([0.0], bits)
        cfg = dist_v3.resolve(a.dist_cfg or "v3")
        for point in a.points:
            tag, rc = point.split(":")
            c, e = Condition.parse(tag), table[point]
            d = camp / f"{tag}_{rc}"
            d.mkdir()
            (d / "stimuli.inc").write_text(static)
            cases.append((point, d, stop))
            jobs.append((deck(c, rc, e["code"], e["vctrl"], stop, 20e-9, cfg, d / "snap"), d / "run",
                         dict(files={"stimuli.inc": d / "stimuli.inc"}, timeout_s=a.case_timeout,
                              meta=dict(point=point, **e, dist_cfg=a.dist_cfg or "v3"))))
        (camp / "plan.json").write_text(json.dumps(dict(decks={f"{d.name}/run": 1 for _, d, _ in cases}, points=a.points, stop=stop), indent=1))
    output = camp / "analysis" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    output.mkdir(parents=True, exist_ok=False)
    try:
        for ex in spice.run_many(jobs, workers=a.workers, smoke=True):
            if not ex.ok:
                print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
            summarize(cases, output)
    finally:
        rows = summarize(cases, output)
    for point, row in rows.items():
        if row["state"] != "measured":
            print(f"{point:22s} {row['state']}")
            continue
        r = row["metrics"]
        print(f"{point:22s} {r['f0'] / 1e9:.4f} GHz; counting={r['counter']['counting']}; "
              f"gate={r['ck_pp'] * 1e3:.1f} mVpp; Pclk={r['pclock_w'] * 1e3:.2f} mW")
    print(output.relative_to(ROOT))


if __name__ == "__main__":
    main()
