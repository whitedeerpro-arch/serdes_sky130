"""Sampled timing boundaries; never silently assume a monotonic aperture."""
import math


def sampled_hold_boundary(observations):
    """Bracket failure -> old-data retention from (arrival offset seconds, bool).

    A bracket is a sampled deterministic boundary for one set of waveforms;
    it is not a statistical margin or a guarantee between sampled slew shapes.
    """
    points=list(observations)
    if not points or any(not math.isfinite(x) or not isinstance(y,bool) for x,y in points):
        raise ValueError('finite offsets and explicit boolean retention required')
    if len({x for x,y in points})!=len(points):
        raise ValueError('duplicate sampled offsets')
    points.sort(key=lambda pair:pair[0])
    failed=[x for x,y in points if not y];passed=[x for x,y in points if y]
    result=dict(last_failed_s=max(failed) if failed else None,first_passed_s=min(passed) if passed else None)
    if failed and passed:
        result['status']='bracketed' if max(failed)<min(passed) else 'nonmonotonic'
    else:
        result['status']='unbracketed'
    return result
