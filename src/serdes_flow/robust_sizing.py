"""Small deterministic building blocks for robust sizing studies."""
import numpy as np


def pareto_mask(values):
    """Keep nondominated rows when every objective is minimized.

    Equal rows both survive: neither strictly improves the other.
    This does not assume convexity or assign weights to objectives.
    """
    x = np.asarray(values, dtype=float)
    if x.ndim != 2 or x.shape[1] == 0 or not np.isfinite(x).all():
        raise ValueError('Expected a finite matrix with objective columns')
    return np.array([not np.any(np.all(x <= row, axis=1) &
                               np.any(x < row, axis=1)) for row in x], dtype=bool)


def power_widths(total_um, alpha=1., units=(1, 2, 4, 8, 16), floors_um=None):
    """Allocate total width proportional to units**alpha, with active floors.

    Floors fix a bit's minimum width; the remaining budget is redistributed
    over the other bits. Actual PCell finger/grid choices remain separate.
    """
    units = np.asarray(units, dtype=float)
    floors = np.zeros_like(units) if floors_um is None else np.asarray(floors_um, dtype=float)
    if (units.ndim != 1 or not len(units) or floors.shape != units.shape or
        not np.isfinite(units).all() or not np.isfinite(floors).all() or
        not np.isfinite(total_um) or not np.isfinite(alpha) or
        np.any(units <= 0) or np.any(floors < 0) or total_um < floors.sum()):
        raise ValueError('Invalid or infeasible width budget/floors')
    result = floors.copy()
    active = np.ones(len(units), dtype=bool)
    while np.any(active):
        budget = total_um-result[~active].sum()
        logs = alpha*np.log(units[active])
        weights = np.exp(logs-np.max(logs))
        trial = budget*weights/weights.sum()
        hit = trial < floors[active]
        if not np.any(hit):
            result[active] = trial
            break
        active[np.flatnonzero(active)[hit]] = False
    return result
