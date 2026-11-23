"""PLL supply-tone tolerance and added jitter, today's single rail and behind the HV18 LDO (PLL closure step 7).

    uv run python analog/pll/top/theory/ldo_supply_tolerance.py [--ldo r4] [--alpha 0.6667] [--kb 2.94e9] [--dj 0.05]
        [--ref-filter 10e3] [--bias-rc 10e3,100e3]     (ideal RCs; the r3 study used both)

Per fitted supply point (supply_split.py, 20 MHz decompositions) and frequency, two paths into the VCO frequency:
  quiet  VCO + buffers + CP + LF on the rail they sit on: K_q(f) = Kg + H(f) Kl at LF split --alpha, minus the 20 MHz
         value of the bias path below (the 20 MHz fit holds it inside Kg)
  bias   the tail line vbias, made by the host bias reference and its PMOS copy: K_b(f) = kb vbias / host (f), the
         small-signal transfer of each point's own bias network (bias_path_ac) times --kb; the split psrr_lf runs at
         4 MHz give K_host / (vbias / host) = 2.94 (FS 1.95 V -40 C hh) and 2.64 GHz/V (TT), real to 0.1 deg
and the supply model's LF and CP follow --loop (Rz, Ci, k; the checks use the measured k = 4 LF).  The loop's error
transfer |1 / (1 + L)| of the same condition and RC section (loop_design.py plant set at the
code-table code, LF sections rc / hl / lh, worst of them; all usable codes of the condition if the table code is outside
the plant window), current loop --loop, control node + --c-extra.  Tolerance = tone amplitude (peak) for --dj UI peak
time error of the 2 GHz clock; no CDR (it tracks only below ~0.1 MHz).  Rows (worst point at each frequency):
  direct        one rail for everything (today; the 1.8 V-only configuration): |K_q + K_b|
  direct_flat   the same with K frequency independent apart from H(f) (the earlier model, for comparison)
  direct_tail   direct with r4's 1 MOhm / 16 pF tail filter (vbias -> R -> C -> VCO / buffer tail gates; measured
                vbias_q / vbias at 3 PLL points, the others take the one passing most at 1 MHz)
  direct_vbX    the same with an ideal first-order RC of corner X
  hv_3v3        3.3 V input through the LDO onto the quiet rail (measured transfer, worst of the --ldo grid: r4 255,
                r3 135 real-reference points): h_vin |K_q|
  host          host 1.8 V: into the quiet rail through the LDO (vbg x 1 / beta; r4 includes its 1 MOhm / 16 pF
                reference RC) and directly through the tail line: |K_b| + h_host |K_q| (magnitudes added: the LDO
                phase is not matched to the PLL point)
  host_tail     host with the r4 tail filter: the r4 proposal as a whole
  host_rcX, host_rcX_vbY   ideal RCs on the LDO reference / tail line (r3 study)
Noise, 1 kHz .. 200 MHz (worst point).  r4: the quiet rail's output noise (r4_dc_noise, real BG, PDK passives, 2 and
10 mA, worst of six conditions) through K_q, and the filtered tail line's noise (same campaign) through kb; they share
the BG, so the two are added linearly as the bound.  r3: core noise (ideal reference) and vbg noise (bias dist_noise)
x 1 / beta rolled off at --f-ldo.  Without the tail filter the bias network's own vbias noise is part of the existing
PLL noise budget and not repeated here.

Checks printed against psrr_lf measurements (CHECKS): 12 MHz (23 / 36 split, 3 points), 4 MHz (12 / 18, 4 points) and
the 4 MHz host / quiet split (2 points).  Kg and Kl are frequency independent (quasi-static VCO); the LDO transfer is
the worst of its own grid at every frequency, not matched to the PLL condition.  Host paths into the quiet domain other
than the LDO and the tail line (CP bias copies, code drivers, divider, clock receivers) are not included, except
with --host-timing: the in-loop host timing cells' delay sensitivity reaches the output through the closed-loop
transfer |L / (1 + L)| and is added in magnitude to the host rows (*_kd) and to the direct row (direct_kd).  Per supply
point, VCO edge shift per volt of host Kd(f) = Kd_pfd - Kd_h - Kd_b vbias / host (f) with the point's own measurement
(host_timing: VCO -> fb0 delay vs host and vs the host cells' vbias, or with --kd-part prescaler only VCO -> d08;
--pfd-cp: PFD + CP zero-charge phase vs host, 0 if not given); points without a measurement take
|Kd_pfd| + |Kd_h| + |Kd_b| |vbias / host| of the worst measured.
"""
import argparse
import glob
import importlib.util
import json
import time

import numpy as np

from serdes_flow import spice
from serdes_flow.project import ROOT


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, ROOT / path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


ss = _load("supply_split", "analog/pll/top/theory/supply_split.py")
ld = _load("loop_design", "analog/pll/top/theory/loop_design.py")
lp = _load("loop_psrr", "analog/pll/top/theory/loop_psrr.py")
OUT = ROOT / "results/analog/pll/top/ldo_supply_tolerance"
REG = "results/analog/ldo/regulation/20261110T073605.249951Z_4cbaf4bf"     # r3: real bandgap + current copy
DYN = "results/analog/ldo/dynamic/20261110T073954.902636Z_326ca852"        # r3: core noise, ideal reference
BIAS_NOISE = "results/analog/bias/dist_noise"
R4 = "results/analog/ldo/r4/20261110T112415.433032Z_31c78a41"              # r4: 255 AC points, real BG, PDK passives
R4_NOISE = "results/analog/ldo/r4_dc_noise/20261110T120141.651192Z_9a75685f"
R4_TAIL = "results/analog/ldo/r4_bias_filter/20261110T113540.869125Z_59f58e7a"   # 1 MOhm / 16 pF tail filter
BIAS_AC = "results/analog/pll/vco/bias_path_ac/20261110T101744Z"
CHECKS = [("results/analog/pll/vco/psrr_lf/20261109T203223Z", 23 / 36), ("results/analog/pll/vco/psrr_lf/20261110T081042Z", 12 / 18),
          ("results/analog/pll/vco/psrr_lf/20261110T091040Z", 12 / 18)]
TABLE = ROOT / "config/pll_code_table.json"
F0, UI, INV_BETA = 2e9, 250e-12, 120 / 82
SHOW = (1e5, 2e5, 3e5, 5e5, 1e6, 2e6, 3e6, 5e6, 8e6, 1.2e7, 2e7, 5e7)


def envelope(paths, f, reader):
    """Worst |value| over files at each f (log interpolation)."""
    out = np.zeros_like(f)
    for p in paths:
        x, y = reader(p)
        out = np.maximum(out, np.exp(np.interp(np.log(f), np.log(x), np.log(np.maximum(y, 1e-30)))))
    return out


def tsv(p):
    d = np.loadtxt(p, skiprows=1)
    return d[:, 0], np.hypot(d[:, 1], d[:, 2])


def onoise(p):
    w = spice.Waves(p)
    return np.asarray(w.t), np.asarray(w["onoise_spectrum"])


def vbg_noise(f):
    out = np.zeros_like(f)
    for s in sorted(glob.glob(str(ROOT / BIAS_NOISE / "*" / "summary.json"))):
        for c in json.loads(open(s).read())["conditions"].values():
            x, y = np.array(c["vbg"]["f"]), np.array(c["vbg"]["v"])
            out = np.maximum(out, np.exp(np.interp(np.log(f), np.log(x), np.log(y))))
    return out


def tail_line(row, f):
    """vbias / host, complex, at f (log-f interpolation of the AC sweep)."""
    x = np.log(np.array(row["f"]))
    return np.interp(np.log(f), x, row["vbias_re"]) + 1j * np.interp(np.log(f), x, row["vbias_im"])


def lowpass(f, fc):
    return 1 / (1 + 1j * np.asarray(f) / fc)


def tail_filters(f):
    """r4 tail filter, vbias_q / vbias (complex) at f, per measured PLL point (key cond:rc)."""
    out = {}
    for p in sorted(glob.glob(str(ROOT / R4_TAIL / "*" / "ac.tsv"))):
        d = np.loadtxt(p, skiprows=1)
        t = (d[:, 3] + 1j * d[:, 4]) / (d[:, 1] + 1j * d[:, 2])
        x = np.log(d[:, 0])
        cond, rc = p.split("/")[-2].rsplit("_", 1)
        out[f"{cond}:{rc}"] = np.interp(np.log(f), x, t.real) + 1j * np.interp(np.log(f), x, t.imag)
    return out


def ldo_inputs(name, f, f_ldo):
    """Measured LDO transfers (worst |.| of the grid) and noise spectra on the quiet rail ('q') or the tail line ('b')."""
    if name == "r3":
        n_vbg = vbg_noise(f) * INV_BETA / np.abs(1 + 1j * f / f_ldo)
        return dict(h_vin=envelope(sorted(glob.glob(str(ROOT / REG / "*" / "*_supply.tsv"))), f, tsv),
                    h_host=envelope(sorted(glob.glob(str(ROOT / REG / "*" / "*_host.tsv"))), f, tsv),
                    noise={"LDO core (ideal ref)": ("q", envelope(sorted(glob.glob(str(ROOT / DYN / "*" / "noise.raw"))), f, onoise)),
                           "vbg x 1/beta": ("q", n_vbg)}, n_vbg=n_vbg, tail={})
    return dict(h_vin=envelope(sorted(glob.glob(str(ROOT / R4 / "*" / "*_hv.tsv"))), f, tsv),
                h_host=envelope(sorted(glob.glob(str(ROOT / R4 / "*" / "*_host.tsv"))), f, tsv),
                noise={"quiet (r4, 2 / 10 mA)": ("q", envelope(sorted(glob.glob(str(ROOT / R4_NOISE / "*" / "hv*_noise.raw"))), f, onoise)),
                       "tail line, filtered": ("b", envelope(sorted(glob.glob(str(ROOT / R4_NOISE / "*" / "tail_noise.raw"))), f, onoise))},
                n_vbg=None, tail=tail_filters(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha", type=float, default=12 / 18, help="LF split: fraction of Ci to the rail")
    ap.add_argument("--kb", type=float, default=2.94e9, help="VCO frequency per V on the tail line, Hz/V")
    ap.add_argument("--ldo", default="r4", choices=("r3", "r4"), help="measured LDO data set")
    ap.add_argument("--ref-filter", default="", help="ideal RC corners added on the LDO reference, Hz (r3: 10e3)")
    ap.add_argument("--bias-rc", default="", help="ideal RC corners on the tail line, Hz (r3: 10e3,100e3)")
    ap.add_argument("--f-ldo", type=float, default=4.12e6, help="LDO loop crossover for the reference gain roll-off")
    ap.add_argument("--dj", type=float, default=0.05, help="UI peak per tone")
    ap.add_argument("--rj", type=float, default=3e-12, help="rms for the white-density figure")
    ap.add_argument("--c-extra", type=float, default=150e-15)
    ap.add_argument("--loop", default="4,4.13e3,18.38e-12,0", help="k, Rz, Ci, Cf")
    ap.add_argument("--host-timing", default="", help="host_timing campaign(s), comma separated, later ones win per point")
    ap.add_argument("--kd-part", default="total", choices=("total", "prescaler"),
                    help="prescaler: only the VCO -> d08 share (feedback receiver balanced or on quiet)")
    ap.add_argument("--pfd-cp", default="", help="host_timing_pfd_cp campaign (PFD + CP balance point vs host)")
    a = ap.parse_args()
    f = np.logspace(3, np.log10(2e8), 700)
    target = a.dj * UI * 2 * np.pi * F0                       # rad peak
    ref_rc = [float(x) for x in a.ref_filter.split(",") if x and float(x) > 0]
    bias_rc = [float(x) for x in a.bias_rc.split(",") if x and float(x) > 0]

    fits = ss.fit(ss.rows(lp.BASES), [(json.loads((ROOT / c / "summary.json").read_text())["rows"], float(x))
                                      for c, x in (s.rsplit(":", 1) for s in lp.SPLITS.split(","))], 20e6)
    bias = json.loads((ROOT / BIAS_AC / "summary.json").read_text())["rows"]
    missing = sorted(set(fits) - set(bias))
    assert not missing, f"no bias_path_ac data for {missing}"
    k, rz, ci, cf = (float(x) for x in a.loop.split(","))
    p = ld.plants(ld.WORKMAP, ld.CPWIN, 1.0, 0.39, ld.CtrlLoad(lp.CTRL_LOAD, a.c_extra))
    s = 2j * np.pi * f[None, :]
    R, Ci, Cf = rz * p["rf"][:, None], ci * p["cf"][:, None], cf * p["cf"][:, None] + p["cctrl"][:, None]
    z = (1 + s * R * Ci) / (s * (Ci + Cf) * (1 + s * R * Ci * Cf / (Ci + Cf)))
    e = 1 / (1 + ld.ICP0 * k * p["g"][:, None] * z / (s * ld.N) * np.exp(-s * 2e-9))
    err, comp = np.abs(e), np.abs(1 - e)
    kd = None
    if a.host_timing:
        kr = {}
        for c in a.host_timing.split(","):
            kr.update(json.loads((ROOT / c / "summary.json").read_text())["rows"])
        if a.kd_part == "prescaler":
            kr = {q: dict(r, kd_h=r["kd8_h"], kd_b=r["kd8_b"]) for q, r in kr.items() if "kd8_h" in r and np.isfinite(r["kd8_h"])}
        kp = json.loads((ROOT / a.pfd_cp / "summary.json").read_text())["rows"] if a.pfd_cp else {}
        kd = {q: (kp[q]["kd_pfd"] if q in kp else 0.0, r["kd_h"], r["kd_b"]) for q, r in kr.items()}
        worst = (max([abs(r["kd_pfd"]) for r in kp.values()] or [0.0]), max(abs(r["kd_h"]) for r in kr.values()),
                 max(abs(r["kd_b"]) for r in kr.values()))
    table = json.loads(TABLE.read_text())["table"]

    def quiet(v, x, alpha, brow, lf=(ss.RZ, ss.CI, 4.0)):
        """K_q at frequencies x, Hz/V: the 20 MHz fit without its bias-path share, for an LF of (Rz, Ci) and a CP of
        scale k (output capacitance + 3.4 fF per unit of k above 4, half of it to the rail, as loop_psrr.py)."""
        x = np.atleast_1d(x)
        d = 3.4e-15 * (lf[2] - 4)
        return np.array([v["kg"] + ss.transfer(q, alpha, v["cp"] + d, v["cpv"] + d / 2, v["rz"] * lf[0] / ss.RZ, v["ci"] * lf[1] / ss.CI)
                         * v["kl"] for q in x]) - a.kb * tail_line(brow, 20e6)

    print(f"checks against psrr_lf (MHz/V, real / quad), kb {a.kb / 1e9:g} GHz/V:")
    for camp, alpha in CHECKS:
        for key, row in json.loads((ROOT / camp / "summary.json").read_text())["rows"].items():
            cond, rc, tag = key.split(":")
            var, fm = tag.split("_")[0], float(tag.split("_")[1][:-1]) * 1e6
            if f"{cond}:{rc}" not in fits:
                continue
            kq, kbv = quiet(fits[f"{cond}:{rc}"], fm, alpha, bias[f"{cond}:{rc}"])[0], a.kb * tail_line(bias[f"{cond}:{rc}"], fm)
            m = dict(lf=kq + kbv, host=kbv, quiet=kq)[var] / 1e6
            meas = complex(row["k_real"], row["k_quad"]) / 1e6
            print(f"  {cond + ':' + rc:18s} {var:5s} {fm / 1e6:4g} MHz  meas {meas.real:7.1f} {meas.imag:6.1f} |{abs(meas):5.1f}|  "
                  f"model {m.real:7.1f} {m.imag:6.1f} |{abs(m):5.1f}|  {100 * (abs(m) / abs(meas) - 1):+5.1f} %")

    li = ldo_inputs(a.ldo, f, a.f_ldo)
    h_vin, h_host, tails = li["h_vin"], li["h_host"], li["tail"]
    noise_in = dict(li["noise"])
    for fc in ref_rc if li["n_vbg"] is not None else ():
        noise_in[f"vbg x 1/beta, rc {fc / 1e3:g} kHz"] = ("q", li["n_vbg"] * np.abs(lowpass(f, fc)))
    # unmeasured points take the measured tail filter that passes most at 1 MHz
    tail_worst = max(tails.values(), key=lambda t: abs(np.interp(1e6, f, np.abs(t)))) if tails else None

    per = {}
    for key, v in fits.items():
        code = table[key]["code"]
        idx = [i for i, l in enumerate(p["label"]) if l.startswith(f"{key} code {code} LF ")]
        idx = idx or [i for i, l in enumerate(p["label"]) if l.startswith(f"{key} code ")]
        S = err[idx].max(axis=0)
        Tc = comp[idx].max(axis=0)
        kq = quiet(v, f, a.alpha, bias[key], (rz, ci, k))
        kb = a.kb * tail_line(bias[key], f)
        kflat = np.abs(kq + a.kb * tail_line(bias[key], 20e6))
        K = dict(direct=np.abs(kq + kb), direct_flat=kflat)
        tail = tails.get(key, tail_worst)
        if tail is not None:
            K["direct_tail"] = np.abs(kq + kb * tail)
        for fb in bias_rc:
            K[f"direct_vb{fb / 1e3:g}k"] = np.abs(kq + kb * lowpass(f, fb))
        K["hv_3v3"] = h_vin * np.abs(kq)
        K["host"] = np.abs(kb) + h_host * np.abs(kq)
        if tail is not None:
            K["host_tail"] = np.abs(kb * tail) + h_host * np.abs(kq)
        for fc in ref_rc:
            rc = np.abs(lowpass(f, fc))
            K[f"host_rc{fc / 1e3:g}k"] = np.abs(kb) + h_host * rc * np.abs(kq)
            for fb in bias_rc:
                K[f"host_rc{fc / 1e3:g}k_vb{fb / 1e3:g}k"] = np.abs(kb * lowpass(f, fb)) + h_host * rc * np.abs(kq)
        if kd is not None:                                 # delay path as an equivalent |K|: 2 pi F0 Kd |T| = |K| S / f
            vb = tail_line(bias[key], f)
            kdv = np.abs(kd[key][0] - kd[key][1] - kd[key][2] * vb) if key in kd else worst[0] + worst[1] + worst[2] * np.abs(vb)
            kdd = 2 * np.pi * F0 * kdv * Tc * f / S
            for n in [n for n in K if n.startswith("host") or n == "direct"]:
                K[f"{n}_kd"] = K[n] + kdd
            K["kd_only"] = kdd
        gq = np.abs(kq) / f * S                            # rad peak per V peak on the quiet rail
        gb = a.kb / f * S                                  # ... on the tail line
        per[key] = dict(code=code, K=K, tol={n: target / (x / f * S) for n, x in K.items()},
                        noise={n: float(np.sqrt(np.trapezoid((d * (gq if w == "q" else gb)) ** 2, f)) / (2 * np.pi * F0))
                               for n, (w, d) in noise_in.items()},
                        white=float(a.rj * 2 * np.pi * F0 / np.sqrt(np.trapezoid(gq ** 2, f))))

    names = list(next(iter(per.values()))["K"])
    print(f"{len(per)} supply points, split {a.alpha:.4f}, loop k {k:g} Rz {rz / 1e3:g} k Ci {ci * 1e12:g} p; tolerance, mV peak for {a.dj} UI peak (worst point):")
    print(f"  {'':20s} " + " ".join(f"{x / 1e6:>6g}" for x in SHOW) + "   worst    MHz  point")
    summary = {}
    for n in names:
        env = np.min([r["tol"][n] for r in per.values()], axis=0)
        i = int(np.argmin(env))
        who = min(per, key=lambda q: per[q]["tol"][n][i])
        summary[n] = dict(worst_v=float(env[i]), at_hz=float(f[i]), point=who, at={f"{x:g}": float(np.interp(x, f, env)) for x in SHOW})
        print(f"  {n:20s} " + " ".join(f"{np.interp(x, f, env) * 1e3:6.1f}" for x in SHOW) + f" {env[i] * 1e3:7.1f} {f[i] / 1e6:6.2f}  {who}")
    print(f"  {'LDO 3.3 V dB':20s} " + " ".join(f"{20 * np.log10(np.interp(x, f, h_vin)):6.1f}" for x in SHOW))
    print(f"  {'LDO host dB':20s} " + " ".join(f"{20 * np.log10(np.interp(x, f, h_host)):6.1f}" for x in SHOW))
    lo = f < 1e6
    print("per point, direct: worst tolerance mV at MHz; below 1 MHz; peak |K| below 1 MHz (MHz/V at MHz); host worst")
    for key, r in sorted(per.items(), key=lambda q: q[1]["tol"]["direct"].min()):
        t, th, kk = r["tol"]["direct"], r["tol"].get("host_tail", r["tol"]["host"]), r["K"]["direct"]
        i, j, m = int(np.argmin(t)), int(np.argmin(np.where(lo, t, np.inf))), int(np.argmax(np.where(lo, kk, 0)))
        print(f"  {key:18s} code {r['code']:2d}: {t[i] * 1e3:5.1f} at {f[i] / 1e6:5.2f};  {t[j] * 1e3:5.1f} at {f[j] / 1e6:4.2f};  "
              f"{kk[m] / 1e6:4.0f} at {f[m] / 1e6:4.2f};  host {th.min() * 1e3:5.1f} at {f[int(np.argmin(th))] / 1e6:4.2f}")
    noise = {n: max(r["noise"][n] for r in per.values()) for n in noise_in}
    print(f"white density on the quiet rail for {a.rj * 1e12:g} ps rms (worst point): {min(r['white'] for r in per.values()) * 1e9:.0f} nV/rtHz")
    print("added PLL rms jitter, 1 kHz-200 MHz, no CDR (worst point), ps: " + ", ".join(f"{n} {v * 1e12:.3f}" for n, v in noise.items())
          + f"; linear sum {sum(noise.values()) * 1e12:.3f}")
    camp = OUT / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True)
    (camp / "summary.json").write_text(json.dumps(dict(
        args=vars(a), kd_s_per_v=dict(points=kd, worst=worst) if kd else None, inputs=dict(**(dict(regulation=REG, dynamic=DYN, bias_noise=BIAS_NOISE) if a.ldo == "r3" else
                                     dict(regulation=R4, noise=R4_NOISE, tail_filter=R4_TAIL, tail_measured=sorted(tails))),
                                  bias_ac=BIAS_AC, checks=CHECKS, supply_bases=lp.BASES, splits=lp.SPLITS),
        tolerance=summary, noise_rms_s=noise, white_v_rthz=min(r["white"] for r in per.values()),
        points={q: dict(code=r["code"], **{f"worst_{n}_v": float(r["tol"][n].min()) for n in names},
                        **{f"at_{n}_hz": float(f[int(np.argmin(r["tol"][n]))]) for n in names}) for q, r in per.items()}), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
