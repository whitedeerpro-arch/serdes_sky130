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


def test_confirmation_screen_uses_worst_cycle():
    import importlib.util
    from serdes_flow.project import ROOT

    path=ROOT/'verification/plotting/tx_clock_output_confirmation.py'
    spec=importlib.util.spec_from_file_location('confirmation_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    class Wave:
        t=np.linspace(0,10e-9,20001)
        amplitude=np.where((t>=4e-9)&(t<4.5e-9),.03,.09)
        y=amplitude*np.sin(2*np.pi*t/.5e-9)
        def __getitem__(self,name):
            return 1.5+(self.y if name=='c2gp' else -self.y)
    w=Wave();result=module.signal_metrics(w,1e-9,9e-9)
    assert result['difference_pp_v'] > .3
    assert result['cycle_amplitudes']['min_pp_v'] < .15
    assert result['clock_amplitude_screen_150_to_400mv'] is False
    assert result['clock_design_target_at_least_200mv'] is False
