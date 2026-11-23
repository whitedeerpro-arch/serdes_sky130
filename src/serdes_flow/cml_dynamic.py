"""Differential/common-mode surrogate for a fixed loaded CML buffer.

This bounded seven-parameter model is for local waveform interpolation. It
contains no device sizing rule, mismatch model or confidence interval.
"""
import numpy as np
from scipy.signal import lfilter


PARAMETERS = ("A0_V", "g0", "tau_ps", "delay_ps", "kcm_per_V", "k2_per_V2", "kg_per_V")
LOWER = np.array([.05, .2, 1., 0., -20., -20., -20.])
UPPER = np.array([.6, 10., 120., 80., 20., 20., 20.])


def drive(t, differential, common_mode, vdd, parameters, *, cm_ref, d2_ref):
    """Return (differential, common-mode) without observed-output resets.

    Inputs are uniformly sampled voltages. Explicit delay applies to all input
    quantities; the initial state is the first target, then the preceding input
    history settles the filter. Evaluate only after sufficient settling history.
    """
    t = np.asarray(t, dtype=float)
    signals = [np.asarray(y, dtype=float) for y in (differential, common_mode, vdd)]
    p = np.asarray(parameters, dtype=float)
    if (t.ndim != 1 or len(t) < 3 or any(y.shape != t.shape for y in signals)
            or p.shape != (7,) or not np.all(np.isfinite(p))
            or np.any(p < LOWER) or np.any(p > UPPER)
            or not np.isfinite(cm_ref) or not np.isfinite(d2_ref)
            or not np.all(np.isfinite(t)) or any(not np.all(np.isfinite(y)) for y in signals)):
        raise ValueError("invalid waveform/model parameters")
    dt = float(t[1] - t[0])
    if dt <= 0 or not np.allclose(np.diff(t), dt, rtol=1e-9, atol=1e-20):
        raise ValueError("model needs a strictly increasing uniform time grid")
    a0, g0, tau_ps, delay_ps, kcm, k2, kg = p
    d, cm, supply = [np.interp(t - delay_ps * 1e-12, t, y) for y in signals]
    amplitude = a0 * np.exp(kcm * (cm - cm_ref) + k2 * (d * d - d2_ref))
    gain = g0 * np.sqrt(amplitude / a0) * np.exp(kg * (cm - cm_ref))
    target_d = amplitude * np.tanh(gain * d / amplitude)
    target_cm = supply - amplitude / 2
    alpha = np.exp(-dt / (tau_ps * 1e-12))
    return tuple(lfilter([1 - alpha], [1, -alpha], y, zi=[alpha * y[0]])[0]
                 for y in (target_d, target_cm))
