"""PI linearity under unit-current mismatch: propagation from the device card (no SPICE MC).

    uv run python analog/rx/pi/theory/pi_mismatch.py [--sigma 0.02] [--samples 20000]

Model of serdes_pi_rotator: 8 anchors 45 deg apart; per mixer 8 equal unit currents, thermometer code
c = 8 q + f puts f units on anchor B and 8 - f on anchor A (roles swap in odd sectors, the same
units serve every sector); output phase = zero crossing of the weighted anchor sum.  Anchors either
sinusoidal or the bench shape 0.1 tanh(sin / 0.25).  Unit current errors are independent normal with
sigma (default 2 %: tail nfet W 1.5 x L 0.5 um, A_VT 5.45 mV um -> single-device sigma(Vth) 4.5 mV
at gm/Id ~3.8 = 1.7 %, plus ~1 % for beta).  Per sample: INL (best straight line over the 64 codes,
UI = 180 deg of the 2 GHz clock), DNL (LSB = 1/32 UI), monotonicity; two independent mixers give the
D -> E spacing error (difference of their phases at the same code).
Gate (docs/design/rx_pi_sampler.md): monotonic, |INL| <= 0.02 UI.
"""
import argparse

import numpy as np

from serdes_flow import stats


def phases(weights_a, weights_b, shape, n=1440):
    """Delay (deg, 0..45 within the sector) of the weighted sum of anchor A (0 deg) and B (45 deg later),
    per code (arrays of A and B weight sums)."""
    t = np.linspace(-np.pi / 2, 3 * np.pi / 2, n, endpoint=False)
    wave = (lambda x: np.sin(x)) if shape == "sin" else (lambda x: np.tanh(np.sin(x) / 0.25))
    a, b = wave(t), wave(t - np.pi / 4)
    out = []
    for wa, wb in zip(weights_a, weights_b):
        y = wa * a + wb * b
        i = np.where((y[:-1] < 0) & (y[1:] >= 0))[0][0]
        f = y[i] / (y[i] - y[i + 1])
        out.append(np.degrees(t[i] + f * (t[1] - t[0])))
    return np.array(out)


def rotate(units, shape):
    """Phase (deg) of all 64 codes for one mixer with unit currents `units` (8).  In sector q the code
    f = 0..7 moves f units from anchor A_q to B_q; even sectors move units 0, 1, .. in order, odd
    sectors 7, 6, .. (thermometer re-use of the same units across sector changes)."""
    ph = []
    for q in range(8):
        order = list(range(8)) if q % 2 == 0 else list(range(7, -1, -1))
        wa = [np.sum(units[order[f:]]) for f in range(8)]
        wb = [np.sum(units[order[:f]]) for f in range(8)]
        ph += list(q * 45 + phases(np.array(wa), np.array(wb), shape))
    return np.array(ph)


def inl_dnl(ph):
    codes = np.arange(len(ph))
    fit = np.polyval(np.polyfit(codes, ph, 1), codes)
    inl_ui = (ph - fit) / 180.0
    step = np.diff(ph)
    dnl = step / (360.0 / 64) - 1
    return inl_ui, dnl, step


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sigma", type=float, default=0.02)
    ap.add_argument("--samples", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    for shape in ("sin", "tanh"):
        nominal = rotate(np.ones(8), shape)
        inl0, dnl0, _ = inl_dnl(nominal)
        worst_inl, worst_dnl, nonmono, spacing = [], [], 0, []
        for _ in range(a.samples):
            u1, u2 = 1 + a.sigma * rng.standard_normal(8), 1 + a.sigma * rng.standard_normal(8)
            p1, p2 = rotate(u1, shape), rotate(u2, shape)
            inl, dnl, step = inl_dnl(p1)
            worst_inl.append(np.max(np.abs(inl)) - np.max(np.abs(inl0)))
            worst_dnl.append(np.max(np.abs(dnl)))
            nonmono += int(np.any(step <= 0))
            spacing.append(np.max(np.abs((p2 - p1) - (nominal - nominal))) / 180.0)
        wi, wd, sp = np.array(worst_inl), np.array(worst_dnl), np.array(spacing)
        n = len(wi)
        print(f"{shape:4s}: nominal max|INL| {np.max(np.abs(inl0)):.4f} UI, max|DNL| {np.max(np.abs(dnl0)):.3f} LSB")
        print(f"      mismatch sigma {a.sigma:.1%}, {n} samples: added max|INL| 99.7th pct {np.percentile(wi, 99.7):+.4f} UI;"
              f" max|DNL| 99.7th pct {np.percentile(wd, 99.7):.3f} LSB; non-monotonic {nonmono}/{n}"
              f" (95 % upper bound {stats.yield_ci(n - nonmono, n)[0]:.4f} pass)")
        print(f"      D->E spacing error (two mixers, worst code): 99.7th pct {np.percentile(sp, 99.7):.4f} UI ({np.percentile(sp, 99.7) * 250:.2f} ps)")


if __name__ == "__main__":
    main()
