"""Calibrated fixed-poly geometry with signed contact voltage coefficients.

The curve is A+B*L+C/L at one stated bias. C may have either sign. A chosen
length stays on the increasing branch and inside the measured length domain.
No PVT, layout or current qualification is implied by a geometric solution.
"""
import math

import numpy as np
from scipy.optimize import brentq

WIDTHS = {'1p41': 1.41, '2p85': 2.85, '5p73': 5.73}


def value(length, coefficients):
    a, b, c = coefficients
    return a + b * length + c / length


def calibrate(lengths, resistances):
    lengths, resistances = np.asarray(lengths, dtype=float), np.asarray(resistances, dtype=float)
    if (lengths.ndim != 1 or lengths.shape != resistances.shape or len(lengths) < 3
            or not np.all(np.isfinite(lengths)) or not np.all(np.isfinite(resistances))
            or np.any(lengths <= 0) or np.any(resistances <= 0) or len(np.unique(lengths)) != len(lengths)):
        raise ValueError('invalid fixed-poly calibration')
    design = np.column_stack((np.ones_like(lengths), lengths, 1 / lengths))
    coefficients, _, rank, _ = np.linalg.lstsq(design, resistances, rcond=None)
    if rank != 3 or coefficients[1] <= 0: raise ValueError('calibration has no increasing long-length branch')
    return dict(coefficients_ohm=coefficients.tolist(), domain_um=[float(min(lengths)), float(max(lengths))],
                max_error_ohm=float(np.max(abs(design @ coefficients - resistances))))


def parallel(target, count, curve, *, minimum_length=.5, grid=.01):
    if (not math.isfinite(target) or target <= 0 or type(count) is not int or count < 1
            or not math.isfinite(minimum_length) or minimum_length <= 0 or not math.isfinite(grid) or grid <= 0):
        raise ValueError('invalid fixed-poly geometry request')
    coefficients = np.asarray(curve['coefficients_ohm'], dtype=float)
    domain = np.asarray(curve['domain_um'], dtype=float)
    if (coefficients.shape != (3,) or domain.shape != (2,) or not np.all(np.isfinite(coefficients))
            or not np.all(np.isfinite(domain)) or domain[0] <= 0 or domain[1] <= domain[0]
            or coefficients[1] <= 0): raise ValueError('invalid calibrated length domain')
    _, b, c = coefficients
    lower = max(minimum_length, domain[0], math.sqrt(c / b) if c > 0 else domain[0])
    upper = domain[1]
    if lower >= upper or not value(lower, coefficients) <= target * count <= value(upper, coefficients):
        return None
    root = brentq(lambda length: value(length, coefficients) - target * count, lower, upper)
    candidates = [q * grid for q in (math.floor(root / grid), math.ceil(root / grid))
                  if lower - 1e-12 <= q * grid <= upper + 1e-12]
    if not candidates: return None
    length = min(candidates, key=lambda x: abs(value(x, coefficients) / count - target))
    actual = float(value(length, coefficients) / count)
    return dict(parallel_count=count, length_um=float(length), continuous_length_um=float(root),
                target_resistance_ohm=float(target), predicted_resistance_ohm=actual,
                relative_error=float(actual / target - 1), calibrated_domain_um=domain.tolist(),
                minimum_length_um=minimum_length, length_grid_um=grid)


def instances(name, positive, negative, body, geometry, card):
    if card not in WIDTHS: raise ValueError('unsupported fixed-poly width')
    length, count = geometry['length_um'], geometry['parallel_count']
    lo, hi = geometry['calibrated_domain_um']
    if type(count) is not int or count < 1 or not max(lo, geometry['minimum_length_um']) <= length <= hi:
        raise ValueError('geometry outside the calibrated legal domain')
    return '\n'.join(f'X{name}_{i} {positive} {negative} {body} sky130_fd_pr__res_high_po_{card} l={length:.8f}' for i in range(count))
