"""Tone extraction on adaptive transient grids with explicit covered windows."""
import numpy as np


def tone(t, y, hz, start, stop):
    """Complex peak phasor from a time-weighted DC/trend/sin/cos fit.

    Interpolate the exact endpoints; quadrature weights prevent dense solver
    samples near switching edges from dominating. Phasor origin is `start`;
    y = Re(phasor * exp(j*2*pi*hz*(t-start))) + DC + linear trend.
    """
    t, y = np.asarray(t, float), np.asarray(y, float)
    if (t.ndim != 1 or y.shape != t.shape or len(t)<4 or
            not np.all(np.isfinite(t)) or not np.all(np.isfinite(y)) or
            np.any(np.diff(t)<=0) or not np.isfinite(hz) or hz<=0 or
            not t[0]<=start<stop<=t[-1]):
        raise ValueError('invalid or uncovered tone window')
    inside=(t>start)&(t<stop)
    x=np.r_[start,t[inside],stop]
    values=np.interp(x,t,y)
    phase=2*np.pi*hz*(x-start)
    basis=np.column_stack([np.ones(len(x)),(x-start)/(stop-start),np.cos(phase),np.sin(phase)])
    dt=np.diff(x)
    weight=np.r_[dt[0]/2,(dt[:-1]+dt[1:])/2,dt[-1]/2]
    coef=np.linalg.lstsq(basis*np.sqrt(weight[:,None]),values*np.sqrt(weight),rcond=None)[0]
    residual=values-basis@coef
    return dict(phasor=complex(coef[2],-coef[3]),dc=float(coef[0]),
                trend=float(coef[1]),residual_rms=float(np.sqrt(np.sum(weight*residual**2)/np.sum(weight))))
