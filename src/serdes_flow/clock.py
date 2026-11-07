"""Clock measurements from differential waveforms (zero crossings)."""
import numpy as np

from .waves import crossings


def edges(t, y, polarity=1, start=None, stop=None):
    """Crossing times of one polarity (+1 rising, -1 falling) inside [start, stop]."""
    times, pol = crossings(t, y)
    times = times[pol == polarity]
    if start is not None:
        times = times[times >= start]
    if stop is not None:
        times = times[times <= stop]
    return times


def period_stats(t, y, start=None, stop=None, min_cycles=3):
    """Mean frequency, period spread and duty cycle from rising/falling edges.

    Returns None when fewer than `min_cycles` full periods exist: a missing
    clock is "not measurable", never a 0 Hz reading.
    """
    rise = edges(t, y, 1, start, stop)
    fall = edges(t, y, -1, start, stop)
    if len(rise) < min_cycles + 1:
        return None
    periods = np.diff(rise)
    highs = [f - r for r in rise[:-1] for f in fall[(fall > r) & (fall < r + periods.max())][:1]]
    return dict(
        cycles=len(periods),
        frequency_hz=float(1 / periods.mean()),
        period_mean_s=float(periods.mean()),
        period_pp_s=float(np.ptp(periods)),
        period_rms_s=float(periods.std()),
        duty=float(np.mean(highs) / periods.mean()) if highs else None,
        amplitude_pp_v=float(np.ptp(y[(t >= rise[0]) & (t <= rise[-1])])),
    )


def relative_phase(t, y_ref, y, ref_polarity=1, polarity=1, start=None, stop=None):
    """Delay of each `y` edge after the nearest preceding `y_ref` edge, in seconds.

    Use for divider state checks (which reference edge a divided clock toggles
    on) and for multi-phase spacing.
    """
    ref = edges(t, y_ref, ref_polarity, start, stop)
    sig = edges(t, y, polarity, start, stop)
    sig = sig[sig > ref[0]] if len(ref) else sig
    k = np.searchsorted(ref, sig) - 1
    return sig - ref[k]


def binary_counter(t, bits, active_edges, start, stop):
    """Check an up-counter, LSB first, halfway between consecutive active edges.

    Fixed delays can sample clk->q during a PVT-dependent transition. Only
    complete edge intervals inside the measurement window are sampled. This
    checks the state sequence; it does not grade setup/hold or output glitches.
    """
    active_edges = np.asarray(active_edges)
    a, b = active_edges[:-1], active_edges[1:]
    use = (a >= start) & (b <= stop)
    sample = (a[use] + b[use]) / 2
    states = np.zeros(len(sample), dtype=int)
    for i, bit in enumerate(bits):
        states |= (np.interp(sample, t, bit) > 0).astype(int) << i
    steps = np.diff(states) % (1 << len(bits))
    bad = np.flatnonzero(steps != 1)
    return dict(counting=bool(len(steps) and not len(bad)),
                samples=len(sample), invalid_steps=bad.tolist(),
                states=states.tolist(), sample_times_s=sample.tolist())
