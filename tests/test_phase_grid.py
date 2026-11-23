import numpy as np
import pytest
from serdes_flow.phase_grid import spacing

ORDER=[(0,1),(1,-1),(2,1),(3,-1),(0,-1),(1,1),(2,-1),(3,1)]


@pytest.mark.parametrize("skew",[0,8e-12,-8e-12])
def test_spacing_wraps_near_zero_and_preserves_actual_skew(skew):
    period=500e-12
    t=np.arange(0,12e-9,0.25e-12)
    delays=np.array([0,-3*period/8,period/4,-period/8])
    delays[0]+=skew
    y=[np.sin(2*np.pi*(t-d)/period) for d in delays]
    result=spacing(t,y,ORDER,start=2e-9,stop=10e-9)
    assert result is not None
    assert result['error_pp_s']==pytest.approx(abs(skew),abs=.02e-12)
    assert result['period_s']==pytest.approx(period,rel=1e-8)


def test_missing_phase_is_not_graded_as_zero_error():
    t=np.linspace(0,10e-9,10000)
    y=[np.sin(2*np.pi*t/500e-12),np.zeros(len(t))]
    assert spacing(t,y,[(0,1),(1,1)],start=2e-9,stop=8e-9) is None
