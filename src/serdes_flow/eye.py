"""Signed eye of a waveform carrying a known bit sequence (PRBS stimuli, channel / CTLE / sampler nodes).

    bits = prbs7(127)
    src = nrz_pwl(bits, ui, t0, ramp, v_lo, v_hi)          # [(t, v), ...] for a PWL source
    e = signed_eye(t, y, bits, ui, t0, first_bit=40)

`signed_eye` finds the latency (output bit k is the input bit k delayed by `latency`),
then, at every phase of the UI, the signed margin min_k (y(t_k) * s_k) over the analysed
bits (s_k = +1 for a one, -1 for a zero).  Height = that margin at the best phase; width =
the contiguous phase span around the best phase where the margin stays above
`width_threshold` (default 0: the decision threshold).  A wrong latency or polarity gives
a negative height, so a closed or misaligned eye cannot pass silently.
"""
import numpy as np


def prbs7(n, seed=0x7F):
    """x^7 + x^6 + 1, period 127."""
    s, out = seed & 0x7F, []
    for _ in range(n):
        b = ((s >> 6) ^ (s >> 5)) & 1
        s = ((s << 1) | b) & 0x7F
        out.append(b)
    return out


def nrz_pwl(bits, ui, t0, ramp, v_lo, v_hi):
    """Piecewise-linear NRZ: bit k occupies [t0 + k*ui, t0 + (k+1)*ui), transitions centred on
    the bit boundary with total ramp time `ramp`."""
    level = lambda b: v_hi if b else v_lo
    pts = [(0.0, level(bits[0]))]
    for k in range(1, len(bits)):
        if bits[k] != bits[k - 1]:
            tb = t0 + k * ui
            pts += [(tb - ramp / 2, level(bits[k - 1])), (tb + ramp / 2, level(bits[k]))]
    return pts


def _sample(t, y, times):
    return np.interp(times, t, y)


def find_latency(t, y, bits, ui, t0, first_bit, n_bits, max_latency):
    """Latency (s) maximising the correlation of the output with the ideal NRZ of the bits."""
    s = 2 * np.asarray(bits[first_bit:first_bit + n_bits], dtype=float) - 1
    best, best_l = -np.inf, 0.0
    for lat in np.arange(0.0, max_latency, ui / 20):
        tk = t0 + lat + (np.arange(first_bit, first_bit + n_bits) + 0.5) * ui
        if tk[-1] > t[-1]:
            break
        c = float(np.dot(_sample(t, y, tk), s))
        if c > best:
            best, best_l = c, lat
    return best_l


def signed_eye(t, y, bits, ui, t0, first_bit=0, n_bits=None, max_latency=None, phases=100, width_threshold=0.0):
    t, y = np.asarray(t), np.asarray(y)
    n_bits = n_bits or (len(bits) - first_bit)
    max_latency = max_latency if max_latency is not None else 16 * ui
    while n_bits > 8 and t0 + max_latency + (first_bit + n_bits) * ui > t[-1]:
        n_bits -= 1
    lat = find_latency(t, y, bits, ui, t0, first_bit, n_bits, max_latency)
    s = 2 * np.asarray(bits[first_bit:first_bit + n_bits], dtype=float) - 1
    ph = (np.arange(phases) + 0.5) / phases - 0.5               # -0.5 .. 0.5 UI around the latency guess
    margin = np.array([float(np.min(_sample(t, y, t0 + lat + (np.arange(first_bit, first_bit + n_bits) + 0.5 + p) * ui) * s))
                       for p in ph])
    i = int(np.argmax(margin))
    lo = i
    while lo > 0 and margin[lo - 1] > width_threshold:
        lo -= 1
    hi = i
    while hi < phases - 1 and margin[hi + 1] > width_threshold:
        hi += 1
    width = (hi - lo + 1) / phases if margin[i] > width_threshold else 0.0
    return dict(height_v=float(margin[i]), width_ui=float(width), phase_ui=float(ph[i]),
                latency_s=float(lat + ph[i] * ui), bits=int(n_bits), profile=margin.tolist())
