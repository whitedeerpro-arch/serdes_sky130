import numpy as np
import pytest

from serdes_flow.waves import simplify_pwl


def test_pwl_error_bound_and_endpoints():
    t=np.linspace(0,3,3001)
    y=np.tanh((t-1.2)/.03)+.004*np.sin(49*t)
    ti,yi=simplify_pwl(t,y,1e-4)
    assert len(ti)<len(t)//4
    assert (ti[0],ti[-1],yi[0],yi[-1])==(t[0],t[-1],y[0],y[-1])
    assert np.max(np.abs(y-np.interp(t,ti,yi)))<=1e-4*(1+1e-10)
    # The difference of the original/reduced PWL is linear between original
    # knots; checking midpoints confirms the same bound there too.
    mid=(t[1:]+t[:-1])/2
    assert np.max(np.abs(np.interp(mid,t,y)-np.interp(mid,ti,yi)))<=1e-4*(1+1e-10)


def test_constant_and_invalid_pwl():
    ti,yi=simplify_pwl([0,1,2],[.5,.5,.5],0)
    assert ti.tolist()==[0,2] and yi.tolist()==[.5,.5]
    for t,y,tol in [([0,0],[0,1],0),([0,1],[0,np.nan],.1),([0,1],[0,1],-1)]:
        with pytest.raises(ValueError):simplify_pwl(t,y,tol)
