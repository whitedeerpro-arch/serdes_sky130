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


def feedback_lock(ref, fb, *, start, stop, period=4e-9, release=52e-9,
                  phase_tolerance=20e-12, frequency_tolerance=1e-4,
                  average_periods=16, final_edges=60, offset_edges=40):
    """Assess lock with complete edge history and one-to-one feedback pairing.

    Phase is relative to the final median, as in the native PLL benches. The
    frequency test uses full trailing windows; repeated/skipped feedback edges
    cannot pass even when a nearest-edge phase trace looks stationary. Short
    records are explicitly unassessed, rather than passing a shorter tail.
    """
    ref, fb = np.asarray(ref, dtype=float), np.asarray(fb, dtype=float)
    for values in (ref, fb):
        if (values.ndim != 1 or not np.all(np.isfinite(values)) or
                np.any(np.diff(values) <= 0)):
            raise ValueError('invalid edge sequence')
    if not start < stop or period <= 0 or min(average_periods, final_edges, offset_edges) < 1:
        raise ValueError('invalid lock measurement window')
    ref = ref[(ref > start) & (ref <= stop)]
    fb = fb[(fb >= start - period) & (fb <= stop)]
    out = dict(locked_at_end=False, lock_assessed=False, lock_status='insufficient_reference_window',
               reference_edges=len(ref), feedback_edges=len(fb), offset_s=None,
               capture_s=None, e_pp_last_s=None, final_frequency_error=None,
               final_pairing_errors=None)
    if len(ref) < final_edges + average_periods:
        return out
    out['lock_assessed'] = True
    if stop - ref[-1] > period * (1 + frequency_tolerance):
        return dict(out, lock_status='missing_reference_tail')
    if len(fb) < 2:
        return dict(out, lock_status='missing_feedback')
    right = np.clip(np.searchsorted(fb, ref), 1, len(fb) - 1)
    idx = np.where(np.abs(fb[right] - ref) < np.abs(fb[right - 1] - ref), right, right - 1)
    near = fb[idx]
    error = near - ref
    offset = float(np.median(error[-offset_edges:]))
    means = (near[average_periods:] - near[:-average_periods]) / average_periods
    consecutive = np.diff(idx) == 1
    valid = np.convolve(consecutive.astype(int), np.ones(average_periods, dtype=int), mode='valid') == average_periods
    bad = np.ones(len(ref), dtype=bool)
    bad[average_periods:] = ((np.abs(error[average_periods:] - offset) > phase_tolerance) |
                            (np.abs(means / period - 1) > frequency_tolerance) | ~valid)
    locked = bool(not bad[-final_edges:].any())
    return dict(out, locked_at_end=locked, lock_status='locked' if locked else 'not_locked',
                offset_s=offset, e_pp_last_s=float(np.ptp(error[-offset_edges:])),
                capture_s=float(max(0, ref[bad].max() - release)) if locked else None,
                final_frequency_error=float(np.max(np.abs(means[-final_edges:] / period - 1))),
                final_pairing_errors=int(np.count_nonzero(np.diff(idx[-final_edges - 1:]) != 1)))


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


def cycle_amplitudes(t, y, start, stop):
    """Differential peak-to-peak envelope over complete rising-edge cycles.

    A cycle is included only when both rising crossings are inside the requested
    window. Interpolated crossings bound each cycle; no partial cycle is padded.
    Return None if the window contains no complete cycle.
    """
    t = np.asarray(t)
    y = np.asarray(y)
    if (t.ndim != 1 or y.shape != t.shape or len(t) < 2 or
            not np.all(np.isfinite(t)) or not np.all(np.isfinite(y)) or
            not np.all(np.diff(t) > 0) or not np.isfinite(start) or
            not np.isfinite(stop) or start >= stop or start < t[0] or stop > t[-1]):
        raise ValueError('invalid or uncovered cycle-amplitude window')
    rising = edges(t, y, 1, start, stop)
    if len(rising) < 2:
        return None
    amplitudes = []
    for left, right in zip(rising, rising[1:]):
        inside = y[(t > left) & (t < right)]
        bounded = np.r_[np.interp(left, t, y), inside, np.interp(right, t, y)]
        amplitudes.append(float(np.ptp(bounded)))
    return dict(complete_cycles=len(amplitudes), min_pp_v=float(np.min(amplitudes)),
                max_pp_v=float(np.max(amplitudes)), mean_pp_v=float(np.mean(amplitudes)))


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
