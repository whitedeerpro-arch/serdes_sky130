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


def simplify_pwl(t, y, tolerance):
    """Subset a PWL trace with a bounded absolute voltage interpolation error.

    Douglas–Peucker in the time/voltage plane using vertical error. Checking
    original vertices bounds the whole original piecewise-linear trace, not
    just its retained points. Both endpoints remain present.
    """
    t, y = np.asarray(t), np.asarray(y)
    if (t.ndim != 1 or y.shape != t.shape or len(t) < 2 or np.any(np.diff(t) <= 0)
            or not np.all(np.isfinite(t)) or not np.all(np.isfinite(y))
            or not np.isfinite(tolerance) or tolerance < 0):
        raise ValueError('invalid PWL trace or tolerance')
    keep = {0, len(t)-1}
    stack = [(0, len(t)-1)]
    while stack:
        a, b = stack.pop()
        if b-a < 2:
            continue
        predicted = y[a]+(y[b]-y[a])*(t[a+1:b]-t[a])/(t[b]-t[a])
        error = np.abs(y[a+1:b]-predicted)
        k = int(np.argmax(error))
        if error[k] > tolerance:
            mid = a+1+k
            keep.add(mid)
            stack.extend(((a, mid), (mid, b)))
    selected = np.array(sorted(keep))
    return t[selected], y[selected]
