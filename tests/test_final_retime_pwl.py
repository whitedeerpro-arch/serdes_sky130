import importlib.util

import numpy as np

from serdes_flow.project import ROOT

spec=importlib.util.spec_from_file_location('final_retime_pwl',ROOT/'analog/tx/input_register/tb/final_retime/window.py')
flow=importlib.util.module_from_spec(spec);spec.loader.exec_module(flow)


def test_shifted_sources_merge_near_coincident_knots_without_changing_voltage():
    # Observed failure: independent source knots only 9e-23 s apart forced an
    # unresolvable solver step. The source shape must survive normalization.
    t=np.array([0.,2.297298430599581e-12,4.297298430601849e-12,
                82.2972984306903e-12,84.29729843069257e-12,flow.STOP])
    a=np.array([0.,.04,0.,0.,0.,0.])
    b=np.array([0.,0.,0.,.04,0.,0.])
    ta,ya=flow.shifted_pwl(t,a,0.)
    tb,yb=flow.shifted_pwl(t,b,-80e-12)
    assert np.min(np.diff(np.unique(np.r_[ta,tb])))>=.99*flow.TIME_GRID
    for times,values,original,shift in ((ta,ya,a,0.),(tb,yb,b,-80e-12)):
        points=np.r_[0.,(t+shift)[(t+shift>0)&(t+shift<flow.STOP)],flow.STOP]
        expected=np.interp(points-shift,t,original)
        assert np.max(np.abs(np.interp(points,times,values)-expected))<=flow.TOL
