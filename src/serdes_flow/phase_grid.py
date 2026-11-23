"""Deterministic multiphase clock spacing; separate from random jitter."""
from __future__ import annotations

import numpy as np
from .clock import edges


def spacing(t, signals, order, *, start, stop, min_cycles=3):
    """Error of ordered edge phases from an equally spaced period grid.

    order is [(signal index, rising +1/falling -1), ...]. Missing/stopped
    phases are unmeasurable. Each delay is wrapped around its expected grid
    location before taking the median, so a small negative phase near zero
    does not become one full period of error. Common phase is removed.
    """
    reference=edges(t,signals[order[0][0]],order[0][1],start,stop)
    if len(reference)<min_cycles+1:return None
    period=float((reference[-1]-reference[0])/(len(reference)-1))
    errors,counts=[],[]
    for i,(index,polarity) in enumerate(order):
        signal=edges(t,signals[index],polarity,start,stop)
        if len(signal)<min_cycles+1:return None
        k=np.searchsorted(reference,signal,side="right")-1
        valid=(k>=0)&(k<len(reference)-1)
        if np.count_nonzero(valid)<min_cycles:return None
        delay=signal[valid]-reference[k[valid]]
        expected=i*period/len(order)
        error=(delay-expected+period/2)%period-period/2
        errors.append(float(np.median(error)));counts.append(int(len(error)))
    centered=np.asarray(errors)-np.mean(errors)
    return dict(period_s=period,phase_error_s=centered.tolist(),
                error_pp_s=float(np.ptp(centered)),max_abs_error_s=float(np.max(np.abs(centered))),
                complete_edge_counts=counts)
