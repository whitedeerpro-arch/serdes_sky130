"""Complex feedback measurements; source orientation is part of the contract."""
import numpy as np


def middlebrook(tv, ti):
    """Combine voltage and current injection at the same loop port.

    Vtest is input-minus-return; Tv=-Vreturn/Vinput. Itest injects +1 A
    into the input node, Vtest=0; Ti=I(Vtest)/(1-I(Vtest)), with I(Vtest)
    directed input->return. Includes the loading correction of dual injection.
    """
    tv,ti=np.asarray(tv),np.asarray(ti)
    return (tv*ti-1)/(tv+ti+2)


def unity_crossings(hz,gain):
    """All crossings, including upwards; interpolate on log magnitude/frequency."""
    hz=np.asarray(hz);gain=np.asarray(gain)
    if hz.ndim!=1 or hz.shape!=gain.shape or not np.all(np.isfinite(gain)) or not np.all(np.diff(hz)>0):
        raise ValueError('Invalid feedback spectrum')
    mag=np.abs(gain);phase=np.unwrap(np.angle(gain))*180/np.pi
    indices=np.flatnonzero(((mag[:-1]>=1)&(mag[1:]<1))|((mag[:-1]<1)&(mag[1:]>=1)))
    rows=[]
    for n in indices:
        a=np.log(mag[n])/(np.log(mag[n])-np.log(mag[n+1]))
        rows.append(dict(hz=float(np.exp(np.log(hz[n])*(1-a)+np.log(hz[n+1])*a)),
                         direction='down' if mag[n]>=1 else 'up',phase_deg=float(phase[n]*(1-a)+phase[n+1]*a),
                         pm_deg=float(180+phase[n]*(1-a)+phase[n+1]*a)))
    return rows
