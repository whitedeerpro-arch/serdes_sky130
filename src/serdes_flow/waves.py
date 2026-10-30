"""Measurements on sampled (non-uniform time step) waveforms."""
import numpy as np


def crossings(t, y, level=0.0):
    """Linearly interpolated level crossings.

    Returns (times, polarity) where polarity is +1 for rising, -1 for falling.
    A sample exactly at the level counts once, on the step that reaches it.
    """
    y = np.asarray(y) - level
    k = np.where(((y[:-1] < 0) & (y[1:] >= 0)) | ((y[:-1] > 0) & (y[1:] <= 0)))[0]
    times = t[k] - y[k] * (t[k + 1] - t[k]) / (y[k + 1] - y[k])
    return times, np.where(y[k + 1] > y[k], 1, -1)


def time_average(y, t):
    """Trapezoidal time average; use for power and common mode on variable steps."""
    return float(np.trapezoid(y, t) / (t[-1] - t[0]))


def window(t, start, stop):
    """Boolean mask selecting start <= t <= stop."""
    return (t >= start) & (t <= stop)
