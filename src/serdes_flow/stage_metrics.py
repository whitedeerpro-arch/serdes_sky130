"""Windowed stage telemetry and causal propagation delay from transient data."""
import numpy as np

from . import clock, waves


def window(t, y, start, stop):
    """Include interpolated endpoints; reject uncovered or non-finite windows."""
    t, y = np.asarray(t), np.asarray(y)
    if (t.ndim != 1 or y.shape != t.shape or len(t) < 2 or
            not np.all(np.isfinite(t)) or not np.all(np.isfinite(y)) or
            not np.all(np.diff(t) > 0) or not t[0] <= start < stop <= t[-1]):
        raise ValueError('invalid or uncovered telemetry window')
    use = (t > start) & (t < stop)
    return np.r_[start, t[use], stop], np.r_[np.interp(start, t, y), y[use], np.interp(stop, t, y)]


def telemetry(t, y, start, stop):
    tw, yw = window(t, y, start, stop)
    return dict(mean=float(waves.time_average(yw, tw)), minimum=float(yw.min()),
                maximum=float(yw.max()), peak_to_peak=float(np.ptp(yw)))


def headroom(t, drain, source, vdsat, start, stop):
    """VDS-VDSAT of an NMOS. A negative value is telemetry, not a new spec gate."""
    margin = np.asarray(drain) - np.asarray(source) - np.asarray(vdsat)
    out = telemetry(t, margin, start, stop)
    tw, mw = window(t, margin, start, stop)
    out['fraction_below_zero'] = float(waves.time_average((mw < 0).astype(float), tw))
    return out


def propagation(t, yin, yout, start, stop, max_delay):
    """Associate same-polarity output edges with unique causal input edges.

    No modulo-period wrapping. Missing intermediate input/output events and
    ambiguous associations fail rather than turning into a plausible delay.
    The caller chooses max_delay below the same-polarity clock period.
    """
    if max_delay <= 0 or start - max_delay < t[0] or stop > t[-1]:
        raise ValueError('invalid propagation window')
    result = {}
    for polarity, label in ((1, 'rising'), (-1, 'falling')):
        inp = clock.edges(t, yin, polarity, start - max_delay, stop)
        out = clock.edges(t, yout, polarity, start, stop)
        delays, indices = [], []
        for event in out:
            hits = np.flatnonzero((inp <= event) & (inp >= event - max_delay))
            if len(hits) != 1:
                raise ValueError(f'{label}: missing or ambiguous causal input')
            indices.append(int(hits[0])); delays.append(float(event - inp[hits[0]]))
        if len(delays) < 3 or not np.all(np.diff(indices) == 1):
            raise ValueError(f'{label}: insufficient, repeated or missing events')
        slopes = (np.interp(out + 5e-12, t, yout) - np.interp(out - 5e-12, t, yout)) / 10e-12
        result[label] = dict(events=len(delays), mean_s=float(np.mean(delays)),
                             min_s=min(delays), max_s=max(delays),
                             median_abs_slew_v_per_s=float(np.median(np.abs(slopes))),
                             input_times_s=inp[indices].tolist(), output_times_s=out.tolist(),
                             delays_s=delays)
    return result
