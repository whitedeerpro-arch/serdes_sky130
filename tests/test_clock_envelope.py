import numpy as np
import pytest

from serdes_flow import clock


def test_weak_cycle_is_not_hidden_by_strong_cycles():
    t=np.linspace(0,6,6001)
    amplitude=np.where((t>=2)&(t<3),.05,.2)
    y=amplitude*np.sin(2*np.pi*t)
    result=clock.cycle_amplitudes(t,y,0,6)
    assert np.ptp(y)>.39
    assert result['min_pp_v'] == pytest.approx(.1,abs=.001)
    assert result['max_pp_v'] == pytest.approx(.4,abs=.001)
    assert result['complete_cycles'] >= 4


def test_partial_cycles_are_excluded_without_padding():
    t=np.linspace(0,5,5001);y=.2*np.sin(2*np.pi*t)
    result=clock.cycle_amplitudes(t,y,1.2,3.8)
    assert result['complete_cycles']==1
    assert result['min_pp_v']==pytest.approx(.4,abs=.001)


def test_no_complete_cycle_is_unmeasurable():
    t=np.linspace(0,1,1001)
    assert clock.cycle_amplitudes(t,np.ones_like(t),0,1) is None
    assert clock.cycle_amplitudes(t,np.sin(2*np.pi*t),.1,.9) is None


def test_window_cannot_extrapolate():
    t=np.array([0.,1.,2.]);y=np.array([0.,1.,0.])
    with pytest.raises(ValueError,match='uncovered'):
        clock.cycle_amplitudes(t,y,-.1,1.)
