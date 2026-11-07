import numpy as np
import pytest

from serdes_flow.waves import shift_pwl


@pytest.mark.parametrize('offset', [-40e-12, 0., 60e-12])
def test_shift_preserves_full_piecewise_linear_error_bound(offset):
    t=np.array([0.,1e-9,1e-9+2e-23,1.05e-9,1.5e-9,6.5e-9])
    y=np.array([0.,0.,0.,.2,-.1,-.1])
    ts,ys=shift_pwl(t,y,offset)
    probe=np.unique(np.r_[np.linspace(0,t[-1],100001),np.clip(t+offset,0,t[-1]),ts])
    assert ts[0]==0 and ts[-1]==t[-1] and np.all(np.diff(ts)>0)
    assert np.max(abs(np.interp(probe,ts,ys)-np.interp(probe-offset,t,y)))<=1e-5


def test_time_quantization_cannot_hide_a_narrow_voltage_pulse():
    t=np.array([0.,1e-9,1e-9+2e-17,1e-9+4e-17,2e-9])
    with pytest.raises(ValueError,match='voltage interpolation bound'):
        shift_pwl(t,np.array([0.,0.,1.,0.,0.]),0.)
