"""Jitter left at the RX sampler after the digital CDR, from the PLL's L(f) (pll_noise.py).

    uv run python analog/pll/top/theory/cdr_jitter.py --pll <pll_noise_*.json> [--ticks 1000000] [--edge 9e-12]

Bang-bang loop of digital/rx/rtl at one control tick (16 UI = 4 ns): up to 16 edges (random data), each votes
the sign of (phase error + edge noise); the sign of the sum drives the Q16 proportional and frequency paths
(KP 1/8, KI 1/2048 PI step), the phase debt issues +-1 PI step (1/32 UI) with `latency` ticks from the samples
to the applied code.  Input: far TX PLL minus own RX PLL, independent draws of the same L(f) up to the tick's
Nyquist rate.  Above it (too fast to track) the rest is added in power.  Edge noise stands for ISI and the
noise of each edge, measured spread <= 0.15 UI pp -> sigma ~ 9 ps.  Reports the error's rms, and the linear
high-pass corner that would leave the same rms.
"""
import argparse
import json

import numpy as np

UI = 250e-12
TICK = 4e-9
STEP = UI / 32
KP = 8192 / 65536
KI = 32 / 65536
FLIM = 32768 / 65536


def phase_series(rng, f_l, l_l, f0, n):
    """Time error [s] of a clock with one-sided L(f), n samples at the tick rate; f below the table: table's first slope."""
    df = 1 / (n * TICK)
    f = np.arange(1, n // 2 + 1) * df
    lo = f < f_l[0]
    slope = np.log10(l_l[1] / l_l[0]) / np.log10(f_l[1] / f_l[0])
    l = np.exp(np.interp(np.log(f), np.log(f_l), np.log(l_l)))
    l[lo] = l_l[0] * (f[lo] / f_l[0]) ** slope
    s = 2 * l / (2 * np.pi * f0) ** 2                                 # one-sided s^2 / Hz
    x = np.zeros(n // 2 + 1, complex)
    x[1:] = n * np.sqrt(s * df / 4) * (rng.standard_normal(n // 2) + 1j * rng.standard_normal(n // 2))
    return np.fft.irfft(x, n)


def run(t_in, rng, edge, latency, kp=KP, ki=KI):
    n = len(t_in)
    err = np.zeros(n)
    trans = rng.binomial(16, 0.5, n)
    noise = rng.standard_normal((n, 16)) * edge
    phase, debt, freq = 0.0, 0.0, 0.0
    pending = [0]
    votes = [0] * (latency - 1)
    for k in range(n):
        e = t_in[k] - phase
        err[k] = e
        m = trans[k]
        s = 0
        if m:
            total = int(np.sign(e + noise[k, :m]).sum())
            s = (total > 0) - (total < 0)
        votes.append(s)
        s = votes.pop(0)
        freq = min(FLIM, max(-FLIM, freq + ki * s))
        debt += freq + kp * s
        d = 0
        if debt >= 1:
            d, debt = 1, debt - 1
        elif debt <= -1:
            d, debt = -1, debt + 1
        pending.append(d)
        phase += pending.pop(0) * STEP
    return err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pll", required=True)
    ap.add_argument("--ticks", type=int, default=1 << 20)
    ap.add_argument("--edge", type=float, default=9e-12)
    ap.add_argument("--latency", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--kp", type=float, default=KP)
    ap.add_argument("--ki", type=float, default=KI)
    a = ap.parse_args()
    d = json.loads(open(a.pll).read())
    f_all, f0 = np.array(d["f"]), d["f0"]
    print(f"edge noise {a.edge * 1e12:.1f} ps, latency {a.latency} ticks, KP {a.kp:.4f} KI {a.ki:.6f}, {a.ticks} ticks ({a.ticks * TICK * 1e3:.1f} ms)")
    self_noise = run(np.zeros(a.ticks), np.random.default_rng(a.seed), a.edge, a.latency, a.kp, a.ki)[a.ticks // 16:]
    print(f"self noise (no input jitter): {self_noise.std() * 1e12:.2f} ps rms, peak {np.abs(self_noise).max() / UI:.3f} UI")
    print(f"{'k':>4s} {'UGB MHz':>8s} | {'PLL rms ps':>10s} {'in, TX-RX':>10s} {'err ps':>7s} {'above Nyq':>9s} {'total ps':>8s} {'UI':>7s} {'14.07s UI':>9s} | {'peak err UI':>11s} {'hp equiv MHz':>12s}")
    for r in d["rows"]:
        rng = np.random.default_rng(a.seed)
        l = np.array(r["total"])
        t_in = phase_series(rng, f_all, l, f0, a.ticks) - phase_series(rng, f_all, l, f0, a.ticks)
        err = run(t_in, rng, a.edge, a.latency, a.kp, a.ki)[a.ticks // 16:]
        err = err - err.mean()
        hi = f_all > 125e6
        s_hi = 2 * np.trapezoid(2 * l[hi], f_all[hi]) / (2 * np.pi * f0) ** 2      # both clocks
        tot = np.sqrt(err.var() + s_hi)
        # the corner of a first-order high-pass that leaves the same in-band rms
        fq = np.logspace(5, 8, 121)
        want = err.var()
        lo = ~hi
        gain = [2 * np.trapezoid(2 * l[lo] * (f_all[lo] / c) ** 2 / (1 + (f_all[lo] / c) ** 2), f_all[lo]) / (2 * np.pi * f0) ** 2 for c in fq]
        hp = float(np.interp(-want, -np.array(gain), fq))
        print(f"{r['k']:4.1f} {r['ugb'] / 1e6:8.2f} | {r['rms']['total'] * 1e12:10.2f} {t_in.std() * 1e12:10.2f} {err.std() * 1e12:7.2f} {np.sqrt(s_hi) * 1e12:9.2f} {tot * 1e12:8.2f} {tot / UI:7.4f} {14.07 * tot / UI:9.3f} | {np.abs(err).max() / UI:11.3f} {hp / 1e6:12.2f}", flush=True)


if __name__ == "__main__":
    main()
