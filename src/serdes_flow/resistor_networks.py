"""Legal explicit parallel resistor networks from a calibrated A+B*L+C/L card.

Lengths are micrometres and resistance is ohms. This plans geometry; it does
not change project netlists or certify DRC, matching, current or noise.
"""
import math

import numpy as np


def fit(lengths, resistances):
    lengths, resistances = np.asarray(lengths), np.asarray(resistances)
    if (lengths.ndim != 1 or lengths.shape != resistances.shape or len(lengths)<3 or
            np.any(lengths<=0) or not np.all(np.isfinite(lengths)) or
            not np.all(np.isfinite(resistances)) or np.any(resistances<=0)):
        raise ValueError('invalid resistor calibration')
    design = np.column_stack((np.ones_like(lengths), lengths, 1/lengths))
    coeff, _, rank, _ = np.linalg.lstsq(design,resistances,rcond=None)
    if rank!=3 or coeff[1]<=0 or coeff[2]<0:
        raise ValueError('calibration has no positive monotone long-length branch')
    return coeff.tolist(),float(np.max(np.abs(design@coeff-resistances)))


def resistance(length, coefficients):
    a,b,c=coefficients
    return a+b*length+c/length


def parallel(target, count, coefficients, *, minimum_length=.5, grid=.01):
    """Select the long positive root, then legal grid geometry; None if impossible.

    The contact voltage coefficient creates C/L; a head+slope extrapolation
    near minimum L can invent an impossible low resistance.
    """
    a,b,c=map(float,coefficients)
    if (not math.isfinite(target) or target<=0 or type(count) is not int or count<1 or
            not all(math.isfinite(x) for x in (a,b,c,minimum_length,grid)) or
            b<=0 or c<0 or minimum_length<=0 or grid<=0):
        raise ValueError('invalid parallel resistor request')
    lower=max(minimum_length,math.sqrt(c/b))
    if target*count<resistance(lower,coefficients): return None
    disc=(a-count*target)**2-4*b*c
    if disc<0: return None
    continuous=(count*target-a+math.sqrt(disc))/(2*b)
    lengths={max(math.ceil(lower/grid-1e-10),q)*grid for q in
             (math.floor(continuous/grid),math.ceil(continuous/grid))}
    length=min(lengths,key=lambda x:abs(resistance(x,coefficients)/count-target))
    actual=resistance(length,coefficients)/count
    return dict(parallel_count=count,length_um=float(length),continuous_length_um=continuous,
                predicted_resistance_ohm=float(actual),target_resistance_ohm=target,
                relative_error=float(actual/target-1),geometry_minimum_length_um=minimum_length,
                monotone_branch_lower_length_um=lower,length_grid_um=grid)


def instances(name, positive, negative, body, plan, *, card='2p85'):
    """Emit distinct physical instances, preserving independent device identity."""
    if card not in ('1p41','2p85'): raise ValueError('unsupported fixed-width card')
    length=plan['length_um'];count=plan['parallel_count']
    if length<plan['geometry_minimum_length_um'] or type(count) is not int or count<1:
        raise ValueError('illegal network geometry')
    return '\n'.join(f'X{name}_{i} {positive} {negative} {body} sky130_fd_pr__res_high_po_{card} l={length:.8f}'
                     for i in range(count))
