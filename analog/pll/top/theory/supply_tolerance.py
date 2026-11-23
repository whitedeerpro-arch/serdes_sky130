"""VDD ripple the PLL tolerates: tone amplitude and white-noise density, from the VCO's supply sensitivity.

    uv run python analog/pll/top/theory/supply_tolerance.py [--kvdd 389e6] [--kvco 519e6] [--scales 1,2,4,6,8] [--dj 0.05] [--rj 3e-12]

A supply tone of amplitude A at f moves the VCO's frequency by A Kvdd, a phase deviation A Kvdd / f, and the loop
high-passes it (1 / (1 + L)).  Printed: the amplitude for --dj UI peak of the 2 GHz clock's time error, at the worst
frequency and at a few others; and the white density on VDD (one-sided, band 10 kHz .. 1 GHz) for --rj rms.  A CDR
would track only the slow part (analog/pll/top/theory/cdr_jitter.py), left out here.  Loop scaled as in pll_noise.py.
"""
import argparse

import numpy as np

from serdes_flow import pnoise

UI = 250e-12
F0 = 2e9


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kvdd", type=float, default=389e6)
    ap.add_argument("--kvco", type=float, default=519e6)
    ap.add_argument("--scales", default="1,2,4,6,8")
    ap.add_argument("--dj", type=float, default=0.05)
    ap.add_argument("--rj", type=float, default=3e-12)
    a = ap.parse_args()
    f = np.logspace(4, 9, 2001)
    show = (1e5, 1e6, 1e7, 1e8)
    target = a.dj * UI * 2 * np.pi * F0                       # rad, peak
    print(f"Kvdd {a.kvdd / 1e6:.0f} MHz/V, Kvco {a.kvco / 1e6:.0f} MHz/V; tone amplitude for {a.dj} UI peak, mV; white density for {a.rj * 1e12:.1f} ps rms, nV/sqrtHz")
    print(f"{'k':>4s} {'UGB MHz':>8s} | {'worst mV':>8s} {'at MHz':>7s} | " + " ".join(f"{q:>8.0e}" for q in show) + f" | {'nV/rtHz':>8s}")
    base = pnoise.Loop(kvco=a.kvco)
    for k in (float(x) for x in a.scales.split(",")):
        lp = pnoise.scaled_loop(base, k)
        ugb, _ = lp.unity_gain()
        gain = a.kvdd / f * np.abs(1 / (1 + lp.open_loop(f)))     # rad per volt, peak to peak of amplitude
        amp = target / gain
        i = int(np.argmin(amp))
        s = np.trapezoid(gain ** 2, f)                            # phase variance per (V^2/Hz), one-sided S_v
        dens = a.rj * 2 * np.pi * F0 / np.sqrt(s)
        print(f"{k:4.1f} {ugb / 1e6:8.2f} | {amp[i] * 1e3:8.2f} {f[i] / 1e6:7.2f} | " + " ".join(f"{np.interp(q, f, amp) * 1e3:8.2f}" for q in show) + f" | {dens * 1e9:8.0f}")


if __name__ == "__main__":
    main()
