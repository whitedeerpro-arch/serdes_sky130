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


def shift_pwl(t, y, offset_s, *, tolerance_v=1e-5, time_quantum_s=1e-16):
    """Shift a finite PWL on [0, t[-1]], holding its endpoint values outside.

    Quantize nearly coincident breakpoints before simplification. The final
    error is checked at every shifted original vertex and interval endpoint,
    so both quantization and simplification share the stated voltage bound.
    Positive offsets delay the waveform. This endpoint-hold behavior is for
    stimulus construction, never for extrapolating a measurement window.
    """
    t, y = np.asarray(t, dtype=float), np.asarray(y, dtype=float)
    if (t.ndim != 1 or y.shape != t.shape or len(t) < 2 or t[0] != 0
            or not np.all(np.isfinite(t)) or not np.all(np.isfinite(y))
            or np.any(np.diff(t) <= 0) or not np.isfinite(offset_s)
            or not np.isfinite(tolerance_v) or tolerance_v <= 0
            or not np.isfinite(time_quantum_s) or time_quantum_s <= 0
            or t[-1]/time_quantum_s > np.iinfo(np.int64).max/2):
        raise ValueError('invalid shifted PWL or error/time bound')
    stop = t[-1]
    moved = t + offset_s
    original = np.r_[0., moved[(moved > 0) & (moved < stop)], stop]
    quantized = np.unique(np.rint(original/time_quantum_s).astype(np.int64))*time_quantum_s
    grid = np.r_[0., quantized[(quantized > 0) & (quantized < stop)], stop]
    values = np.interp(grid-offset_s, t, y)
    out_t, out_y = simplify_pwl(grid, values, tolerance_v/2)
    # Include retained knots too: the error of two linear interpolants reaches
    # its maximum at a knot of either interpolant.
    check_t = np.unique(np.r_[original, out_t])
    error = np.max(np.abs(np.interp(check_t,out_t,out_y)-np.interp(check_t-offset_s,t,y)))
    if error > tolerance_v*(1+1e-9):
        raise ValueError('shifted PWL exceeds the voltage interpolation bound')
    return out_t, out_y
