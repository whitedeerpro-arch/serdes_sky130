"""PLL engineering lock screen: windowed unwrapped phase and sustained hold."""
import numpy as np


def screen(ref, fb, *, start, stop, period, window_cycles=32, stride_cycles=8,
           frequency_tolerance=1e-4, phase_span=20e-12, hold=320e-9):
    """Apply the project screen to rising edges; retain every tested window.

    Windows are anchored at the final reference edge and stepped backwards so
    the final complete interval is tested. Continuous feedback edge count is
    interpolated at reference edges (at most one period of end extrapolation);
    it is never folded modulo a period. Nearest-edge pairing also has to be
    one-to-one, preventing extra or missing feedback edges from hiding in a
    window average. A short record is unassessed, never a shorter lock hold.
    """
    ref, fb = np.asarray(ref, dtype=float), np.asarray(fb, dtype=float)
    for x in (ref, fb):
        if x.ndim != 1 or not np.all(np.isfinite(x)) or np.any(np.diff(x) <= 0):
            raise ValueError('invalid rising-edge sequence')
    if not start < stop or period <= 0 or hold <= 0 or min(window_cycles, stride_cycles) < 1:
        raise ValueError('invalid PLL screen parameters')
    ref = ref[(ref > start) & (ref <= stop)]
    fb = fb[(fb >= start-period) & (fb <= stop)]
    out = dict(locked=False, assessed=False, status='insufficient_hold_record',
               reference_edges=len(ref), feedback_edges=len(fb), hold_s=0.,
               hold_start_s=None, windows=[])
    if len(ref) <= window_cycles or ref[-1]-ref[0] < hold*(1-1e-9):
        return out
    out['assessed'] = True
    if stop-ref[-1] > period*(1+frequency_tolerance):
        return dict(out, status='missing_reference_tail')
    if len(fb) < 2:
        return dict(out, status='missing_feedback')
    # A working clock must produce an edge at least once per nominal period
    # through the recorded endpoint. A stopped tail cannot be extrapolated.
    if stop-fb[-1] > period*(1+frequency_tolerance):
        return dict(out, status='missing_feedback_tail')
    count = np.interp(ref, fb, np.arange(len(fb), dtype=float))
    left, right = ref < fb[0], ref > fb[-1]
    count[left] = (ref[left]-fb[0])/(fb[1]-fb[0])
    count[right] = len(fb)-1+(ref[right]-fb[-1])/(fb[-1]-fb[-2])
    phase = count*period-(ref-ref[0])
    right_idx = np.clip(np.searchsorted(fb, ref), 1, len(fb)-1)
    pair = np.where(np.abs(fb[right_idx]-ref) < np.abs(fb[right_idx-1]-ref), right_idx, right_idx-1)
    windows = []
    for first in range(len(ref)-window_cycles-1, -1, -stride_cycles):
        last = first+window_cycles
        freq = (count[last]-count[first])*period/(ref[last]-ref[first])-1
        span = float(np.ptp(phase[first:last+1]))
        missing = int(np.count_nonzero(np.diff(pair[first:last+1]) != 1))
        windows.append(dict(start_s=float(ref[first]), end_s=float(ref[last]),
                            relative_frequency_error=float(freq), phase_span_s=span,
                            pairing_errors=missing,
                            passed=bool(abs(freq)<=frequency_tolerance and span<=phase_span and missing==0)))
    windows.reverse()
    hold_start = None
    for w in reversed(windows):
        if not w['passed']:
            break
        hold_start = w['start_s']
    duration = float(ref[-1]-hold_start) if hold_start is not None else 0.
    locked = duration >= hold*(1-1e-9)
    return dict(out, windows=windows, locked=locked, status='locked' if locked else 'not_locked',
                hold_s=duration, hold_start_s=hold_start)
