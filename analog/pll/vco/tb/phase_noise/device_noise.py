"""Drain current noise of the VCO's devices from ngspice .noise, per condition and bias.

    uv run python analog/pll/vco/tb/phase_noise/device_noise.py [--cond tt_v1800_t27]

Input device (LVT W 40 L 0.15 nf 8) and tail device (W 20 L 0.5 nf 4), drain through a noiseless 100 ohm sense
resistor: S_id(f) = S_v(f) / R^2.  Reported: gm, Id, gamma = S_id(1 GHz) / (4 k T gm), and the flicker
coefficient K = (S_id(f) - S_id(1 GHz)) f at 100 kHz and 1 MHz.
"""
import argparse
import json
import time

import numpy as np

from serdes_flow import pnoise, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

RESULTS = ROOT / "results/analog/pll/vco/phase_noise_device"
DEV = {"in": ("sky130_fd_pr__nfet_01v8_lvt", 40, 0.15, 8), "tail": ("sky130_fd_pr__nfet_01v8", 20, 0.5, 4)}
GRID = {"in": [(vgs, 0.6) for vgs in (0.35, 0.45, 0.55, 0.65, 0.8)], "tail": [(vgs, 0.7) for vgs in (0.75, 0.85, 0.95, 1.05)]}


def deck(c, name):
    model, w, l, nf = DEV[name]
    vals = spice.corner_values(c)
    geom = (f"w={w} l={l} nf={nf} ad={int((nf + 1) / 2) * (w / nf) * 0.29} as={int((nf + 2) / 2) * (w / nf) * 0.29}"
            f" pd={2 * int((nf + 1) / 2) * (w / nf + 0.29)} ps={2 * int((nf + 2) / 2) * (w / nf + 0.29)}")
    head = f"""{name} device drain noise
.lib "{vals['MODEL_LIBRARY']}" {vals['CORNER']}
Vd vdr 0 1
Rs vdr d 100 noisy=0
Vg g 0 0.5 ac 1
Xm d g 0 0 {model} {geom}
.temp {c.temp}
.options sparse
.control
set num_threads=1
set wr_vecnames
set wr_singlescale
"""
    lines = []
    for k, (vgs, vds) in enumerate(GRID[name]):
        lines += [f"alter Vg dc={vgs}", f"alter Vd dc={vds}", "op", f"print i(Vd) > b{k}.txt", "destroy all",
                  "noise v(d) Vg dec 5 1k 2g", "setplot previous", "print onoise_spectrum > s%d.txt" % k, "destroy all"]
        lines += [f"alter Vd dc={vds + 0.01}", "op", f"print i(Vd) > b{k}a.txt", f"alter Vg dc={vgs + 0.01}", f"alter Vd dc={vds}", "op", f"print i(Vd) > b{k}b.txt", "destroy all"]
    return head + "\n".join(lines + ["quit", ".endc", ".end", ""])


def read_i(p):
    for line in p.read_text().splitlines():
        if "=" in line:
            return abs(float(line.split("=")[1]))
    raise ValueError(p)


def read_spectrum(p):
    """Frequency and values from the table `print` writes."""
    rows = []
    for line in p.read_text().splitlines():
        t = line.split()
        if len(t) == 3 and t[0].isdigit():
            rows.append((float(t[1]), float(t[2])))
    return np.array(rows).T


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cond", default="tt_v1800_t27")
    a = ap.parse_args()
    c = Condition.parse(a.cond)
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_{c.tag}")
    jobs = [(deck(c, n), camp / n, dict(timeout_s=900)) for n in DEV]
    for ex in spice.run_many(jobs, workers=1, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:3]}")
    T = c.temp + 273.15
    out = dict(condition=c.tag, devices={})
    for n in DEV:
        rows = []
        for k, (vgs, vds) in enumerate(GRID[n]):
            d = camp / n
            i0, ig = read_i(d / f"b{k}.txt"), read_i(d / f"b{k}b.txt")
            gm = (ig - i0) / 0.01
            f, s = read_spectrum(d / f"s{k}.txt")
            sid = s ** 2 / 100 ** 2
            s_th = float(np.interp(1e9, f, sid))
            k_100k = float((np.interp(1e5, f, sid) - s_th) * 1e5)
            k_1m = float((np.interp(1e6, f, sid) - s_th) * 1e6)
            rows.append(dict(vgs=vgs, vds=vds, id=i0, gm=gm, s_1g=s_th, gamma=s_th / (4 * pnoise.K_B * T * gm), k_100k=k_100k, k_1m=k_1m))
            print(f"{n:5s} Vgs {vgs:.2f}: Id {i0 * 1e6:7.1f} uA gm {gm * 1e3:6.2f} mS gamma {rows[-1]['gamma']:.2f} K(100k) {k_100k:.3e} K(1M) {k_1m:.3e} A2", flush=True)
        out["devices"][n] = rows
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
