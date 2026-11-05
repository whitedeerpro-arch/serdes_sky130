"""VCO phase noise and PLL jitter at one condition, every input measured there: real bias, PDK resistors.

    uv run python analog/pll/vco/tb/phase_noise/corner.py --cond ss_v1650_t85 --rpdk hh [--code 6] [--scales 1,2,4]

Steps, each skipped if its result exists under results/analog/pll/vco/phase_noise_corner/<cond>_r<rc>/ (a VM reboot
loses only the running deck):
  tune      code and Vctrl for 2.00 GHz (f at 1.1 V, 1.3 V; +-1 code until 2 GHz is inside 0.7-1.5 V; secant)
  isf       isf.py at that point
  device    device_noise.py at the condition
  vco_pn    vco_pn.py (R thermal at the corner's value)
  kb, kvdd, kvco  slow.py: VCO sensitivities to the bias line, supply and (local, +-10 mV) control line
  cp, bias  cp/tb/noise, dist_noise at the condition
  pll       analog/pll/top/theory/pll_noise.py with the Kvco from tune
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_vco_isf_ngspice.cir.in"
OUT = ROOT / "results/analog/pll/vco/phase_noise_corner"
GUESS = {"tt": 5, "ss": 6, "ff": 4, "sf": 6, "fs": 5}


def f_at(c, code, vctrl, rc, work):
    """Free-running frequency at (code, Vctrl), real bias."""
    cfg = {f"CFG{k}": (c.supply if (code >> k) & 1 else 0) for k in range(3)}
    text = spice.render(TEMPLATE, **spice.corner_values(c), VCTRL=f"{vctrl:.4f}", INJECT="", PROBES="", TSTEP="1p", STOP="30n", SAVE_FROM="20n", OUT="f.raw", **cfg)
    work.mkdir(parents=True, exist_ok=True)
    text = bias.section(rcorner.to_pdk(bias.real(text), work), c.process, rc)
    d = work / f"c{code}_v{round(vctrl * 1000)}"
    if not (d / "f.raw").exists():
        d = spice.next_run_dir(work, d.name)
        ex = spice.run(text, d, timeout_s=900)
        # FF cold: the varactor model's cosh overflows during gmin stepping and the operating point still converges
        if not ex.ok and not (d / "f.raw").exists():
            raise RuntimeError(f"{d}: {ex.log_failures[:3]}")
    w = spice.Waves(d / "f.raw")
    e, p = crossings(w.t, w["v(v0p)"] - w["v(v0n)"])
    r = e[p > 0][-12:]
    return (len(r) - 1) / (r[-1] - r[0])


def tune(c, rc, work, code, start_v=None):
    """Code and Vctrl for 2 GHz.  Vctrl up -> f up; code up -> f down.  start_v: stay on this code, secant from there."""
    if start_v is not None:
        pts = [(start_v, f_at(c, code, start_v, rc, work)), (start_v + 0.1, f_at(c, code, start_v + 0.1, rc, work))]
        kv = (pts[1][1] - pts[0][1]) / 0.1
        print(f"  code {code}: f({start_v:.3f}) {pts[0][1] / 1e9:.4f} f({start_v + 0.1:.3f}) {pts[1][1] / 1e9:.4f} GHz", flush=True)
        v = start_v + (2.0e9 - pts[0][1]) / kv
        for _ in range(5):
            v = round(float(np.clip(v, 0.4, 1.6)), 3)
            f3 = f_at(c, code, v, rc, work)
            pts.append((v, f3))
            print(f"  code {code}: f({v:.3f}) {f3 / 1e9:.4f} GHz", flush=True)
            if abs(f3 - 2.0e9) < 15e6:
                break
            near = sorted(pts, key=lambda q: abs(q[1] - 2.0e9))[:2]
            if near[0][0] == near[1][0]:
                raise RuntimeError(f"code {code}: 2 GHz is outside 0.4-1.6 V (f({v:.3f}) {f3 / 1e9:.4f} GHz)")
            v = near[0][0] + (2.0e9 - near[0][1]) * (near[0][0] - near[1][0]) / (near[0][1] - near[1][1])
        else:
            raise RuntimeError(f"code {code}: not within 15 MHz after 5 tries, last f({pts[-1][0]:.3f}) {pts[-1][1] / 1e9:.4f} GHz")
        return dict(code=code, vctrl=v, kvco=float(kv), f=float(f3))
    for _ in range(6):
        f1, f2 = f_at(c, code, 1.1, rc, work), f_at(c, code, 1.3, rc, work)
        kv = (f2 - f1) / 0.2
        v = 1.1 + (2.0e9 - f1) / kv
        print(f"  code {code}: f(1.1) {f1 / 1e9:.4f} f(1.3) {f2 / 1e9:.4f} GHz, 2 GHz at {v:.3f} V", flush=True)
        if v < 0.7:
            code += 1
        elif v > 1.5:
            code -= 1
        else:
            # the varactor curve is far from straight: secant through the two nearest points, until within 15 MHz
            pts = [(1.1, f1), (1.3, f2)]
            for _ in range(5):
                v = round(float(np.clip(v, 0.6, 1.6)), 3)
                f3 = f_at(c, code, v, rc, work)
                pts.append((v, f3))
                print(f"  code {code}: f({v:.3f}) {f3 / 1e9:.4f} GHz", flush=True)
                if abs(f3 - 2.0e9) < 15e6:
                    break
                near = sorted(pts, key=lambda q: abs(q[1] - 2.0e9))[:2]
                slope = (near[0][1] - near[1][1]) / (near[0][0] - near[1][0])
                v = near[0][0] + (2.0e9 - near[0][1]) / slope
            return dict(code=code, vctrl=v, kvco=float(kv), f=float(f3))
    raise RuntimeError("no code found")


def call(args):
    print("  $ " + " ".join(str(a) for a in args[3:])[:150], flush=True)
    r = subprocess.run(args, capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        raise RuntimeError(r.stdout[-800:] + r.stderr[-800:])
    return r.stdout


def last_path(text):
    return text.strip().split()[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cond", required=True)
    ap.add_argument("--rpdk", default="tt")
    ap.add_argument("--code", type=int)
    ap.add_argument("--scales", default="1,2,4,6,8")
    ap.add_argument("--start-v", type=float, help="keep --code, search Vctrl from here")
    ap.add_argument("--settle", type=float, default=8e-9, help="isf.py --settle")
    ap.add_argument("--tag", default="", help="suffix of the state directory and ISF campaign, one per VCO revision")
    a = ap.parse_args()
    c = Condition.parse(a.cond)
    base = OUT / f"{c.tag}_r{a.rpdk}{a.tag}"
    base.mkdir(parents=True, exist_ok=True)
    state_p = base / "state.json"
    st = json.loads(state_p.read_text()) if state_p.exists() else {}

    def save():
        state_p.write_text(json.dumps(st, indent=1))

    py = [sys.executable, "-u"]
    t0 = time.time()
    if "tune" not in st:
        st["tune"] = tune(c, a.rpdk, base / "tune", a.code if a.code is not None else GUESS[c.process], a.start_v)
        save()
    print(f"{c.tag} R {a.rpdk}: {st['tune']}", flush=True)
    code, vctrl = st["tune"]["code"], st["tune"]["vctrl"]
    if "isf" not in st:
        o = call(py + [str(HERE / "isf.py"), "--cond", c.tag, "--vctrl", str(vctrl), "--code", str(code), "--bias", "real", "--rpdk", a.rpdk, "--tag", f"_r{a.rpdk}{a.tag}", "--settle", str(a.settle), "--period", f"{1 / st['tune']['f']:.6e}"])
        print(o[-400:], flush=True)
        st["isf"] = o.strip().split()[-1]
        save()
    if "device" not in st:
        st["device"] = last_path(call(py + [str(HERE / "device_noise.py"), "--cond", c.tag]))
        save()
    pn = ROOT / st["isf"] / "phase_noise.json"
    if not pn.exists():
        print(call(py + [str(HERE / "vco_pn.py"), "--isf", st["isf"], "--device", st["device"]]), flush=True)
    stop = f"{max(20e-9, a.settle + 12e-9):.4g}"     # slow.py measures over the last 10 ns
    for name, site, amt in (("kb", "bias", "1e-3"), ("kvdd", "vdd", "5e-3"), ("kvco", "ctrl", "10e-3")):
        if name not in st:
            try:
                o = call(py + [str(HERE / "slow.py"), "--isf", st["isf"], "--site", site, "--current", amt, "--stop", stop])
            except RuntimeError:        # the bandgap start-up sometimes fails on one operating point; another step size takes another Newton path
                o = call(py + [str(HERE / "slow.py"), "--isf", st["isf"], "--site", site, "--current", f"{float(amt) * 1.3:.4g}", "--stop", stop])
            st[name] = float(re.search(r"df/dV ([-+0-9.e]+) Hz/V", o)[1])
            save()
    if "cp" not in st:
        st["cp"] = last_path(call(py + [str(ROOT / "analog/pll/cp/tb/noise/run.py"), "--cond", c.tag, "--vout", str(vctrl), "--rcorner", a.rpdk]))
        save()
    if "bias" not in st:
        st["bias"] = last_path(call(py + [str(ROOT / "analog/common/bias/tb/dist_noise/run.py"), "--process", c.process, "--supply", str(c.supply), "--temps", str(c.temp), "--rcorner", a.rpdk]))
        save()
    print(f"Kvco {st['kvco'] / 1e6:.0f} MHz/V (1.1-1.3 V secant {st['tune']['kvco'] / 1e6:.0f}), Kb {st['kb'] / 1e9:.2f} GHz/V, Kvdd {st['kvdd'] / 1e6:.0f} MHz/V", flush=True)
    bc = f"{c.process}_v{round(c.supply * 1000)}_t{c.temp}"
    print(call(py + [str(ROOT / "analog/pll/top/theory/pll_noise.py"), "--vco", st["isf"], "--cpn", st["cp"], "--bias", st["bias"], "--bias-cond", bc, "--kvco", str(st["kvco"]),
                     "--kb", str(abs(st["kb"])), "--scales", a.scales, "--tag", "kloc"]), flush=True)
    print(f"{time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
