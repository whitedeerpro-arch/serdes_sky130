"""Clock frontend r6q against the r5q arrangement (full dummies) around the same VCO r6: is the light dummy enough?

    uv run python analog/pll/top/tb/frontend_r6/run.py [--points tt_v1800_t27:tt:12:1.1,...] [--variants lean,full]
        [--workers 2] [--resume C]

Open loop, ideal ctrl, one deck per point and variant; one supply for both domains (the 1.8 V-direct configuration),
separate sources so the currents can be read.  Real bias, fixed-width resistor cards.
  lean  pll_clock_frontend_r6q: prescaler + feedback receiver on b0, pll_frontend_dummy_load on b1..3
  full  the r5q arrangement with the r6 ring: on every buffer output a full-rate receiver and a /8 prescaler with its
        feedback receiver (three of them biased dummies with a DFF load)
Measured over 9..21 ns (2 ps step): VCO frequency and swing; the eight phases at the VCO nodes and at the buffer
outputs (rising and falling zero crossings of the four differential signals, deviation from the ideal 45 deg grid in
ps, after removing the mean); buffer output swings; fb0 frequency / 8 check; average currents of the host and quiet
supplies.  The question for the light dummy: phase-grid deviation and frequency against `full`, and the current saved.
"""
import argparse
import importlib.util
import json
import re
import time

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_n = importlib.util.spec_from_file_location("native_k4", ROOT / "analog/pll/top/tb/native_k4/run.py")
nk = importlib.util.module_from_spec(_n)
_n.loader.exec_module(nk)
RESULTS = ROOT / "results/analog/pll/top/frontend_r6"
DROP = ("pll_core_r5k4.spice", "clock_frontend_r5.spice", "cap_bank_4b.spice", "vco_ring4_4b.spice", "pfd_cmos.spice", "charge_pump",
        "passive_rc")
INCLUDES = [p for p in nk.INCLUDES if not any(d in p for d in DROP)] + [
    "analog/pll/vco/spice/cap_bank_5b.spice", "analog/pll/vco/spice/vco_delay_r6.spice", "analog/pll/vco/spice/vco_ring4_r6.spice",
    "analog/pll/top/spice/clock_frontend_r6q.spice"]
STOP, START = 21e-9, 9e-9      # settled from 7 ns (vco r6 speed_check); 12 ns window = three fb0 periods
NODES = [f"{p}{k}{s}" for p in "vb" for k in range(4) for s in "pn"]


def full_frontend():
    """pll_clock_frontend_r5q with the r6 ring (5 code bits, the wiring allowance inside the ring)."""
    t = (ROOT / "analog/pll/top/spice/clock_frontend_r5q.spice").read_text()
    t = t.replace("pll_clock_frontend_r5q", "pll_clock_frontend_r6full").replace("ctrl cfg0 cfg1 cfg2 cfg3 vbias vbias_q rst_b", "ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vbias vbias_q rst_b")
    old = "cfg0 cfg1 cfg2 cfg3 vbias_q vdd_q vss pll_vco_ring4_4b"
    assert t.count(old) == 1
    t = t.replace(old, "cfg0 cfg1 cfg2 cfg3 cfg4 vbias_q vdd_q vss pll_vco_ring4_r6")
    t, n = re.subn(r"^Cw\d[pn] .*\n", "", t, flags=re.M)
    assert n == 8
    # expose the buffer outputs under the names of the lean frontend's ports
    return t


def deck(c, rc, code, vctrl, variant, camp):
    lines = ["PLL clock frontend r6: light dummies against full dummies (open loop)", f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}']
    lines += [f'.include "{ROOT / p}"' for p in INCLUDES]
    if variant == "full":
        lines += full_frontend().splitlines()
    lines += [f".param supply={c.supply}", "Vdd vdd 0 {supply}", "Vh vh 0 {supply}", "Vq vq 0 {supply}", "Vdum vdum 0 {supply}",
              "Iref vdd vbias .85m", "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
              f"Vctrl ctrl 0 {vctrl:.4f}", "Erst rst_b 0 vh 0 1"]
    lines += [f"Ecode{k} cfg{k} 0 vq 0 {code >> k & 1}" for k in range(5)]
    if variant == "lean":
        lines += ["Xfe ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vbias vbias fb0 vh vq 0 b0p b0n b1p b1n b2p b2n b3p b3n d02p d02n d04p d04n d08p d08n "
                  "pll_clock_frontend_r6q"]
        bn = {f"b{k}{s}": f"b{k}{s}" for k in range(4) for s in "pn"}
    else:
        lines += ["Xfe ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vbias vbias rst_b fb0 cm0p cm0n cm1p cm1n cm2p cm2n cm3p cm3n vh vq vdum 0 "
                  "b0p b0n d02p d02n d04p d04n d08p d08n d22p d22n d24p d24n d32p d32n pll_clock_frontend_r6full"]
        bn = {f"b{k}{s}": ("b0" + s if k == 0 else f"xfe.b{k}{s}") for k in range(4) for s in "pn"}
    probes = [f"v(xfe.{n})" if n[0] == "v" else f"v({bn[n]})" for n in NODES] + ["v(fb0)", "i(Vh)", "i(Vq)", "i(Vdum)"]
    lines += ["Ikick xfe.v0p xfe.v0n PWL(0 1u 20p 1u 21p 0)"]
    for k in range(4):
        for sd in "pn":
            lines += [f".nodeset v(xfe.v{k}{sd})={{supply-0.12}}"]
    lines += [f".temp {c.temp}", ".options reltol=1e-4 abstol=1p vntol=1u", ".save " + " ".join(probes), ".control", "set num_threads=1",
              f"tran 2p {STOP:.4e} {START:.4e} 2p", "wrdata out.tsv " + " ".join(probes), "quit", ".endc", ".end"]
    text = bias.real(spice.binary_output("\n".join(lines) + "\n"))
    return bias.section(rcorner.to_pdk_fixed(text, camp), c.process, rc), probes


def zero(t, y, rising):
    s = y if rising else -y
    i = np.where((s[:-1] < 0) & (s[1:] >= 0))[0]
    return t[i] - s[i] * (t[i + 1] - t[i]) / (s[i + 1] - s[i])


def grid_dev(t, sig, T):
    """Deviation (s) of the eight phases from a 45 deg grid: d0+, d1-, d2+, d3-, d0-, d1+, d2-, d3+ (architecture.md)."""
    order = [(0, True), (1, False), (2, True), (3, False), (0, False), (1, True), (2, False), (3, True)]
    ref = zero(t, sig[0], True)
    ph = []
    for k, rising in order:
        e = zero(t, sig[k], rising)
        d = [(x - ref[np.searchsorted(ref, x) - 1]) % T for x in e if np.searchsorted(ref, x) > 0]
        d = np.array(d)
        d = np.where(d > 0.95 * T, d - T, d)
        ph.append(float(np.median(d)))
    dev = np.array(ph) - np.arange(8) * T / 8
    return dev - dev.mean()


def measure(path, probes):
    w = spice.Waves(path)
    t = w.t
    col = dict(zip(NODES, probes[:16]))
    v = [w[col[f"v{k}p"]] - w[col[f"v{k}n"]] for k in range(4)]
    b = [w[col[f"b{k}p"]] - w[col[f"b{k}n"]] for k in range(4)]
    e = zero(t, v[0], True)
    T = float(np.median(np.diff(e)))
    fb = zero(t, w["v(fb0)"] - 0.5 * float(np.max(w["v(fb0)"])), True)
    trap = getattr(np, "trapezoid", None) or np.trapz
    cur = {k: float(-trap(w[f"i({k})"], t) / (t[-1] - t[0])) for k in ("vh", "vq", "vdum")}
    return dict(f=1 / T, vco_swing=[float(np.ptp(x)) for x in v], buf_swing=[float(np.ptp(x)) for x in b],
                vco_dev_s=grid_dev(t, v, T).tolist(), buf_dev_s=grid_dev(t, b, T).tolist(),
                buf_delay_s=[float(np.median([(x - e[np.searchsorted(e, x) - 1]) % T for x in zero(t, b[0], True) if np.searchsorted(e, x) > 0]))],
                fb_ratio=float(np.median(np.diff(fb)) / T) if len(fb) > 2 else None, i_host=cur["vh"] + cur["vdum"], i_quiet=cur["vq"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="tt_v1800_t27:tt:12:1.1,fs_v1650_t85:hh:0:1.21,sf_v1650_t-40:ll:31:0.9,ss_v1650_t-40:hh:6:1.1,ff_v1950_t-40:ll:28:1.1")
    ap.add_argument("--variants", default="lean,full")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume")
    a = ap.parse_args()
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs, probes = [], {}
    for spec in a.points.split(","):
        cond, rc, code, v = spec.split(":")
        c = Condition.parse(cond)
        for var in a.variants.split(","):
            d = camp / f"{cond}_{rc}" / var
            text, probes[var] = deck(c, rc, int(code), float(v), var, camp / "snap")
            if spice.case_output(d, "run", "out.raw", STOP) is None:
                jobs.append((text, spice.next_run_dir(d, "run"), dict(timeout_s=3600, meta=dict(point=spec, variant=var))))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    for spec in a.points.split(","):
        cond, rc, code, v = spec.split(":")
        for var in a.variants.split(","):
            p = spice.case_output(camp / f"{cond}_{rc}" / var, "run", "out.raw", STOP)
            if p is None:
                print(f"{spec} {var}: missing")
                continue
            m = measure(p, probes[var])
            rows.setdefault(spec, {})[var] = m
            print(f"{spec:28s} {var:5s} f {m['f'] / 1e9:.4f} GHz, VCO {np.mean(m['vco_swing']) * 1e3:.0f} mVpp, phase grid +-{np.max(np.abs(m['vco_dev_s'])) * 1e12:.2f} ps | "
                  f"buffers {min(m['buf_swing']) * 1e3:.0f}-{max(m['buf_swing']) * 1e3:.0f} mVpp, grid +-{np.max(np.abs(m['buf_dev_s'])) * 1e12:.2f} ps | "
                  f"fb0 period / VCO {m['fb_ratio']} | host {m['i_host'] * 1e3:.2f} mA, quiet {m['i_quiet'] * 1e3:.2f} mA", flush=True)
    camp.mkdir(parents=True, exist_ok=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
