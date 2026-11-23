"""Delay sensitivity Kd of the PLL's host-domain timing cells (HV18 configuration: VCO / buffers / CP on a quiet 1.8 V).

    uv run python analog/pll/top/tb/host_timing/run.py [--points tt_v1800_t27:tt,...] [--dh 0.02] [--db 0.005]
        [--stop 30e-9] [--workers 2] [--resume C]

Open loop, one deck per point (docs/design/pll_loop.md "供电路径与HV18稳压", integration item 3).  The r5q frontend with
the VCO at the code table's 1.8 V entry (ideal ctrl), VCO and buffers on an ideal quiet 1.8 V with the tail line
through the 1 MOhm / 16 pF filter, the real PFD loaded by the steering CP (output held at Vctrl, CP on quiet).  The
host-domain cells (receivers, prescalers, feedback receiver, PFD, the reference driver) sit on their own source vh;
the bias reference and its copies stay on vdd, and the frontend's vbias pin is the real vbias plus a series source.
Five transients from the operating point: base, vh +-dh, host-cell vbias +-db.  Measured per run over the last half:
  fb path   t(DN rise at quiet / 2) - t(VCO v0p - v0n rising zero), modulo the VCO period (VCO -> prescaler -> fb0
            receiver -> PFD), unwrapped against the base run
  ref path  t(UP rise at quiet / 2) - t(ref rise at vh / 2) (reference edge 10 ps, swing 0..vh)
  to fb0    t(fb0 rise at vh / 2) - t(VCO zero), modulo the period (prescaler + feedback receiver without the PFD)
  to d08    t(d08p - d08n rising zero) - t(VCO zero), modulo the period (prescaler alone; campaigns from 2026-11-11 09 UTC)
  clock     t(cm0p rise at vh / 2) - t(VCO zero), modulo the period (full-rate receiver to TX, outside the loop)
Kd_h, Kd_b = central differences of the time to fb0 (medians over the window), s/V.  The PFD's own share does not come
out of this open loop: the ref / fb phase drifts between runs, and the second output of each period is a reset-width
glitch, so its threshold time is not the locked loop's; the open-loop PFD figures (fb side minus ref side) are printed
as a diagnostic only.  The loop sees Kd(f) = Kd_h + Kd_b * vbias/host(f) inside its bandwidth
(analog/pll/top/theory/ldo_supply_tolerance.py --host-timing).
"""
import argparse
import importlib.util
import json
import time

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_n = importlib.util.spec_from_file_location("native_k4", ROOT / "analog/pll/top/tb/native_k4/run.py")
nk = importlib.util.module_from_spec(_n)
_n.loader.exec_module(nk)
RESULTS = ROOT / "results/analog/pll/top/host_timing"
INCLUDES = [p for p in nk.INCLUDES if p != "analog/pll/top/spice/pll_core_r5k4.spice"] + [
    "analog/pll/top/spice/clock_frontend_r5q.spice", "analog/ldo/spice/ldo_passives.spice",
    "analog/ldo/spice/pll_bias_filter_r4.spice"]
PROBES = "v(xfe.v0p) v(xfe.v0n) v(ref) v(up) v(dn) v(fb0) v(cm0p) v(d08p) v(d08n)"
CP = "wn=20 wp=80 wsn=8 wsp=16 up_wn=2 up_wp=8 dn_wn=4 dn_wp=8 pnf=16 nnf=4 ntail=2 cdum=0.3p"
VQ = 1.8
TR = 10e-12


def runs(a):
    """(name, vh offset, vbias offset) per transient, in deck order."""
    return [("base", 0.0, 0.0), ("hp", a.dh, 0.0), ("hm", -a.dh, 0.0), ("bp", 0.0, a.db), ("bm", 0.0, -a.db)]


def deck(c, rc, code, vctrl, a, camp):
    lines = ["PLL host-domain timing sensitivity (open loop, quiet 1.8 V)", f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}']
    lines += [f'.include "{ROOT / p}"' for p in INCLUDES]
    lines += [f".param supply={c.supply}", "Vdd vdd 0 {supply}", "Vh vh 0 {supply}", f"Vq vq 0 {VQ}", "Vdummy vdum 0 {supply}",
              "Iref vdd vbias .85m", "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
              "Vdb vbfe vbias 0", "Xtail vbias vbq 0 serdes_pll_bias_lowpass_slow_r4",
              "In vb vbn 50u", "Ip vbp 0 50u", "Xbn vbn vbn 0 0 serdes_nfet w=5 l=1", "Xbp vbp vbp vq vq serdes_pfet w=20 l=1 nf=4",
              "Ibuf vdd ibuf 10u", f"Vctrl ctrl 0 {vctrl:.4f}", "Erst rst_b 0 vh 0 1",
              f"Vrefi refi 0 PULSE(0 1 2n {TR:.1e} {TR:.1e} {nk.TREF / 2 - TR:.4e} {nk.TREF:.4e})", "Bref ref 0 V=v(refi)*v(vh)"]
    lines += [f"Ecode{k} cfg{k} 0 vq 0 {code >> k & 1}" for k in range(4)]
    lines += ["Xfe ctrl cfg0 cfg1 cfg2 cfg3 vbfe vbq rst_b fb0 cm0p cm0n cm1p cm1n cm2p cm2n cm3p cm3n vh vq vdum 0 "
              "b0p b0n d02p d02n d04p d04n d08p d08n d22p d22n d24p d24n d32p d32n pll_clock_frontend_r5q",
              "Xpfd ref fb0 rst_b up dn vh 0 pll_pfd",
              f"Xcp up dn out vbn vbp ibuf vq 0 pll_cp_steer {CP}", f"Vout out 0 {vctrl:.4f}",
              "Ikick xfe.v0p xfe.v0n PWL(0 1u 20p 1u 21p 0)"]
    for k in range(4):
        for cell in ("rx", "fb"):
            lines += [f".nodeset v(xfe.x{cell}{k}.xrestore.qp)=0 v(xfe.x{cell}{k}.xrestore.qn)={{supply}}"]
        for sd in ("p", "n"):
            lines += [f".nodeset v(xfe.v{k}{sd})={VQ - .12:.3f} v(xfe.xvco.xv{k}{sd}.p2)={vctrl:.4f}"]
    lines += [f".temp {c.temp}", ".options reltol=1e-4 abstol=1p vntol=1u", f".save {PROBES}", ".control", "set num_threads=1"]
    for name, dh, db in runs(a):
        lines += [f"alter Vh dc={c.supply + dh:.4f}", f"alter Vdb dc={db:.4f}",
                  f"tran 2p {a.stop:.4e} {a.stop / 3:.4e} 2p", f"wrdata {name}.tsv {PROBES}", "destroy all"]
    lines += ["quit", ".endc", ".end"]
    text = spice.binary_output("\n".join(lines) + "\n")
    text = bias.real(text)
    old = "Ibuf vdd ibuf 10u"
    assert text.count(old) == 1
    text = text.replace(old, "XIbuf ibuf vgi_bias vdd serdes_bias_pcopy n=4")
    return bias.section(rcorner.to_pdk(text, camp), c.process, rc)


def crossings(t, v, level, rising=True):
    s = v - level
    i = np.where((s[:-1] < 0) & (s[1:] >= 0))[0] if rising else np.where((s[:-1] > 0) & (s[1:] <= 0))[0]
    return t[i] - s[i] * (t[i + 1] - t[i]) / (s[i + 1] - s[i])


def after(edges, ref):
    """For each edge in `edges`, its time after the latest `ref` edge before it (NaN when there is none)."""
    k = np.searchsorted(ref, edges) - 1
    out = np.full(len(edges), np.nan)
    ok = k >= 0
    out[ok] = edges[ok] - ref[k[ok]]
    return out


def measure(path, vh, stop):
    w = spice.Waves(path)
    t = w.t
    late = t > stop / 2
    t = t[late]
    vco = crossings(t, w["v(xfe.v0p)"][late] - w["v(xfe.v0n)"][late], 0.0)
    T = float(np.median(np.diff(vco)))
    dn = crossings(t, w["v(dn)"][late], VQ / 2)
    up = crossings(t, w["v(up)"][late], VQ / 2)
    ref = crossings(t, w["v(ref)"][late], vh / 2)
    cm = crossings(t, w["v(cm0p)"][late], vh / 2)
    f0 = crossings(t, w["v(fb0)"][late], vh / 2)
    d8 = crossings(t, w["v(d08p)"][late] - w["v(d08n)"][late], 0.0) if "v(d08p)" in w.names else np.array([])
    fb = after(dn, vco)
    pr = after(f0, vco)
    rp = after(up, ref)
    rp = rp[rp < 1e-9]                      # UP rises within 1 ns of its ref edge (a late UP after fb would not)
    ck = after(cm, vco)
    p8 = after(d8, vco)
    return dict(T=T, n_fb=int(np.isfinite(fb).sum()), fb=float(np.nanmedian(fb)), fb_sd=float(np.nanstd(fb)),
                d08=float(np.nanmedian(p8)) if len(p8) else float("nan"),
                n_pre=int(np.isfinite(pr).sum()), pre=float(np.nanmedian(pr)), pre_sd=float(np.nanstd(pr)),
                n_ref=len(rp), ref=float(np.median(rp)) if len(rp) else float("nan"), ck=float(np.nanmedian(ck)), ck_sd=float(np.nanstd(ck)))


def unwrap(x, x0, T):
    return x0 + ((x - x0 + T / 2) % T) - T / 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="tt_v1800_t27:tt,fs_v1650_t85:hh,ss_v1650_t-40:hh,fs_v1950_t-40:hh,ss_v1650_t85:hh,ff_v1950_t-40:ll")
    ap.add_argument("--dh", type=float, default=0.02)
    ap.add_argument("--db", type=float, default=0.005)
    ap.add_argument("--stop", type=float, default=30e-9)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume")
    a = ap.parse_args()
    table = json.loads((ROOT / "config/pll_code_table.json").read_text())["table"]
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    specs = a.points.split(",")

    def entry(spec):
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        key = f"{c.process}_v1800_t{c.temp}:{rc}"
        return c, rc, key, table[key]

    jobs = []
    for spec in specs:
        c, rc, key, e = entry(spec)
        d = camp / spec.replace(":", "_")
        if spice.case_output(d, "run", "bm.raw", a.stop) is not None:
            continue
        jobs.append((deck(c, rc, e["code"], e["vctrl"], a, camp / "snap"), spice.next_run_dir(d, "run"),
                     dict(timeout_s=3 * 3600, meta=dict(point=spec, vco_entry=key, code=e["code"], vctrl=e["vctrl"], dh=a.dh, db=a.db))))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    for spec in specs:
        c, rc, key, e = entry(spec)
        d = camp / spec.replace(":", "_")
        m = {}
        for name, dh, db in runs(a):
            p = spice.case_output(d, "run", f"{name}.raw", a.stop)
            if p is None:
                break
            m[name] = measure(p, c.supply + dh, a.stop)
        if len(m) < 5:
            print(f"{spec}: missing runs ({sorted(m)})")
            continue
        T = m["base"]["T"]
        for k in m:
            m[k]["fb"] = unwrap(m[k]["fb"], m["base"]["fb"], T)
            m[k]["ck"] = unwrap(m[k]["ck"], m["base"]["ck"], T)
            m[k]["pre"] = unwrap(m[k]["pre"], m["base"]["pre"], T)
            m[k]["d08"] = unwrap(m[k]["d08"], m["base"]["d08"], T)
        pfd = {k: (m[k]["fb"] - m[k]["pre"]) - m[k]["ref"] for k in m}
        pre = {k: m[k]["pre"] for k in m}
        r = dict(vco_entry=key, code=e["code"], vctrl=e["vctrl"], runs=m, f_vco=1 / T,
                 kd_h=(pre["hp"] - pre["hm"]) / (2 * a.dh), kd_b=(pre["bp"] - pre["bm"]) / (2 * a.db),
                 kd_h_lin=(pre["hp"] + pre["hm"] - 2 * pre["base"]) / 2, kd_b_lin=(pre["bp"] + pre["bm"] - 2 * pre["base"]) / 2,
                 kd_fb_h=(m["hp"]["fb"] - m["hm"]["fb"]) / (2 * a.dh), kd_ref_h=(m["hp"]["ref"] - m["hm"]["ref"]) / (2 * a.dh),
                 pfd_open_h=(pfd["hp"] - pfd["hm"]) / (2 * a.dh),
                 kd8_h=(m["hp"]["d08"] - m["hm"]["d08"]) / (2 * a.dh), kd8_b=(m["bp"]["d08"] - m["bm"]["d08"]) / (2 * a.db),
                 kck_h=(m["hp"]["ck"] - m["hm"]["ck"]) / (2 * a.dh), kck_b=(m["bp"]["ck"] - m["bm"]["ck"]) / (2 * a.db))
        rows[spec] = r
        print(f"{spec:18s} code {e['code']:2d} f {r['f_vco'] / 1e9:.4f} GHz | to fb0 {m['base']['pre'] * 1e12:6.1f} ps mod T (sd {m['base']['pre_sd'] * 1e12:.2f}, n {m['base']['n_pre']}) | "
              f"Kd_h {r['kd_h'] * 1e9:+.4f} ps/mV (curv {r['kd_h_lin'] * 1e12:+.2f} ps; prescaler {r['kd8_h'] * 1e9:+.4f})  Kd_b {r['kd_b'] * 1e9:+.4f} ps/mV of vbias (curv {r['kd_b_lin'] * 1e12:+.2f} ps; prescaler {r['kd8_b'] * 1e9:+.4f}) | "
              f"PFD open loop: fb side {(r['kd_fb_h'] - r['kd_h']) * 1e9:+.4f}, ref side {r['kd_ref_h'] * 1e9:+.4f}, net {r['pfd_open_h'] * 1e9:+.4f} (UP n {m['base']['n_ref']}) | "
              f"clock Kh {r['kck_h'] * 1e9:+.4f} Kb {r['kck_b'] * 1e9:+.4f} ps/mV", flush=True)
    camp.mkdir(parents=True, exist_ok=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
