"""Oscillator phase noise from a phase impulse response, and linear PLL noise synthesis.

ngspice has no PSS / PNOISE.  The impulse response h(x) [rad/C] of each noise site comes from a transient
with charge pulses at phase x of the cycle (Hajimiri-Lee: h = Gamma / q_max).  One-sided PSDs throughout,
L(df) in dBc/Hz single sideband, small angle.

A stationary white current of one-sided PSD S at a site, modulated by the bias as alpha(x) (cyclostationary
noise: S(x) = S alpha(x)^2), makes the phase a random walk with
    L(df) = (S / 2) <(h alpha)^2> / (2 pi df)^2
Slow noise (flicker, or a bias line) sees only the mean of the response:
    L(df) = (S(df) / 2) <h alpha>^2 / (2 pi df)^2
Uncorrelated sites add in power; sites that move together (a bias line into every tail) add in amplitude
before squaring.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .waves import crossings

K_B = 1.380649e-23


def pulse_train(t0: float, period: float, count: int, charge: float, width: float = 2e-12, edge: float = 1e-12) -> tuple[str, np.ndarray]:
    """PWL text of `count` trapezoid current pulses of the given charge, and their centre times."""
    amp = charge / (width + edge)
    pts, centres = ["0 0"], []
    for k in range(count):
        s = t0 + k * period
        pts += [f"{s:.5e} 0", f"{s + edge:.5e} {amp:.5e}", f"{s + edge + width:.5e} {amp:.5e}", f"{s + 2 * edge + width:.5e} 0"]
        centres.append(s + edge + width / 2)
    return "PWL(" + " ".join(pts) + ")", np.array(centres)


@dataclass
class Impulse:
    x: np.ndarray          # phase of the pulse in the cycle, 0..1 after a rising crossing, sorted
    h: np.ndarray          # rad / C, phase advance positive
    period: float

    def at(self, x):
        """Periodic interpolation."""
        return np.interp(np.asarray(x) % 1.0, self.x, self.h, period=1.0)


def impulse_response(t: np.ndarray, y: np.ndarray, pulses: np.ndarray, charge: float, fit: int = 4) -> Impulse:
    """h(x) from one transient: crossings of y, pulses far enough apart for the ring to settle between them.

    Around every pulse, the rising crossings are fitted over the last `fit` periods before it and the last
    `fit` before the next pulse; the phase jump is their offset at the common period.
    """
    e, pol = crossings(t, y)
    r = e[pol > 0]
    if len(r) < 2 * fit + 2:
        raise ValueError("too few crossings")
    per = []
    for p in pulses:
        k = np.searchsorted(r, p)
        if k >= fit:
            per.append(np.polyfit(np.arange(fit), r[k - fit:k], 1)[0])
    period = float(np.median(per))
    xs, hs = [], []
    for j, p in enumerate(pulses[:-1]):
        k, nxt = np.searchsorted(r, p), np.searchsorted(r, pulses[j + 1])
        if k < fit or nxt - k < fit + 3:
            continue
        before = r[k - fit:k] - period * np.arange(k - fit, k)
        after = r[nxt - fit:nxt] - period * np.arange(nxt - fit, nxt)
        dt = float(np.mean(after) - np.mean(before))
        xs.append((p - r[k - 1]) / period % 1.0)
        hs.append(-2 * np.pi * dt / period / charge)
    o = np.argsort(xs)
    return Impulse(np.array(xs)[o], np.array(hs)[o], period)


def period_mean(x: np.ndarray, y: np.ndarray, n: int = 256) -> float:
    g = (np.arange(n) + 0.5) / n
    return float(np.mean(np.interp(g, x, y, period=1.0)))


def white_coefficient(imp: Impulse, alpha=None, n: int = 256) -> float:
    """<(h alpha)^2> [rad^2 / C^2]; alpha: callable of the phase x, default 1."""
    g = (np.arange(n) + 0.5) / n
    a = 1.0 if alpha is None else alpha(g)
    return float(np.mean((imp.at(g) * a) ** 2))


def slow_coefficient(imp: Impulse, alpha=None, n: int = 256) -> float:
    """<h alpha> [rad / C]."""
    g = (np.arange(n) + 0.5) / n
    a = 1.0 if alpha is None else alpha(g)
    return float(np.mean(imp.at(g) * a))


def dbc(l_linear):
    return 10 * np.log10(l_linear)


def l_white(psd, coeff, df):
    """L(df), linear; psd one-sided A^2/Hz, coeff = white_coefficient."""
    return psd / 2 * coeff / (2 * np.pi * df) ** 2


def l_slow(psd_at_df, mean_h, df):
    """L(df), linear; psd_at_df one-sided A^2/Hz at df, mean_h = slow_coefficient."""
    return psd_at_df / 2 * mean_h ** 2 / (2 * np.pi * df) ** 2


def rms_jitter(df, l_linear, f0, lo=None, hi=None):
    """RMS time jitter [s] from L(df), integrating 2 L(df) over [lo, hi]."""
    df, l_linear = np.asarray(df), np.asarray(l_linear)
    s = (df >= (lo if lo is not None else df[0])) & (df <= (hi if hi is not None else df[-1]))
    return float(np.sqrt(2 * np.trapezoid(l_linear[s], df[s])) / (2 * np.pi * f0))


@dataclass
class Loop:
    """Charge-pump PLL, loop filter Cf || (Rz + Ci), linear model.  kvco in Hz/V, delay = PFD sampling delay [s]."""
    icp: float = 50e-6
    rz: float = 6.5e3
    ci: float = 40e-12
    cf: float = 2e-12
    kvco: float = 480e6
    n: int = 8
    delay: float = 2e-9

    def z(self, f):
        s = 2j * np.pi * np.asarray(f, float)
        return (1 + s * self.rz * self.ci) / (s * (self.ci + self.cf) * (1 + s * self.rz * self.ci * self.cf / (self.ci + self.cf)))

    def open_loop(self, f):
        s = 2j * np.pi * np.asarray(f, float)
        return self.icp * self.z(f) * self.kvco / (s * self.n) * np.exp(-s * self.delay)     # (Icp / 2 pi) Z (2 pi Kvco / s) / N

    def unity_gain(self):
        f = np.logspace(4, 9, 5001)
        g = np.abs(self.open_loop(f))
        k = np.argmax(g < 1)
        return float(f[k]), float(180 + np.degrees(np.angle(self.open_loop(f[k]))))

    def rz_noise_to_ctrl(self, f):
        """v(ctrl) per volt of Rz's series noise source."""
        s = 2j * np.pi * np.asarray(f, float)
        return 1 / (1 + s * self.rz * self.cf + self.cf / self.ci)


def bias_line_l(f, s_v, kb, fc=None, r=0.0, t=300.0):
    """L(f) from a bias line's noise s_v(f) [V^2/Hz] into a VCO of sensitivity kb [Hz/V].

    fc, r: first-order RC between the line and the VCO's tail gates, corner fc, series resistor r (its own thermal
    noise goes through the same low-pass).
    """
    f = np.asarray(f, float)
    if fc:
        s_v = (s_v + 4 * K_B * t * r) / (1 + (f / fc) ** 2)
    return s_v * (kb / f) ** 2 / 2


def cp_sampled_psd(f, s_i, duty, f_white=1e8):
    """CP current noise seen by the loop: the switches gate it at the reference rate.

    The white part folds and averages to duty * S; slow noise (flicker) only sees the mean of the window, duty^2 * S.
    The white level is read at f_white, above the flicker corner.
    """
    white = float(np.interp(f_white, f, s_i))
    return duty * white + duty ** 2 * np.maximum(np.asarray(s_i) - white, 0.0)


def synthesize(f, loop: Loop, l_vco, inband_floor_dbc=None, cp_psd=None, t=300.0, l_bias=None):
    """Output L(f) per source, linear.  l_vco: free-running VCO L(f); l_bias: the bias line's, as bias_line_l.

    inband_floor_dbc: L at the output, in band, of reference + PFD + divider (a white phase-noise floor already
    multiplied by N).  cp_psd: one-sided CP output current noise PSD while the CP is on, times its duty (scalar or per f).
    """
    ol = loop.open_loop(f)
    high = 1 / (1 + ol)
    low = ol / (1 + ol)
    out = {"VCO": np.abs(high) ** 2 * l_vco}
    if l_bias is not None:
        out["bias line"] = np.abs(high) ** 2 * l_bias
    if inband_floor_dbc is not None:
        out["reference, PFD, divider"] = np.abs(low) ** 2 * 10 ** (inband_floor_dbc / 10) * np.ones_like(f)
    if cp_psd is not None:
        out["CP"] = np.abs(low) ** 2 * (2 * np.pi * loop.n / loop.icp) ** 2 * cp_psd / 2
    s_r = 4 * K_B * t * loop.rz
    vctrl = np.abs(loop.rz_noise_to_ctrl(f)) ** 2 * s_r
    out["loop filter Rz"] = np.abs(high) ** 2 * vctrl * (loop.kvco / f) ** 2 / 2
    out["total"] = sum(out.values())
    return out


def scaled_loop(loop: Loop, k: float, by: str = "icp") -> Loop:
    """Same pole / zero ratios with the crossing k times higher, Rz kept: C / k, and Icp * k (or Kvco, Rz)."""
    if by == "icp":
        return Loop(loop.icp * k, loop.rz, loop.ci / k, loop.cf / k, loop.kvco, loop.n, loop.delay)
    raise ValueError(by)
