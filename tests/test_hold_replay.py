import importlib.util
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from serdes_flow import project,spice

spec=importlib.util.spec_from_file_location('hold_replay',project.ROOT/'analog/tx/input_register/tb/hold_aperture/run.py')
hold=importlib.util.module_from_spec(spec)
spec.loader.exec_module(hold)


def test_shifted_pwl_stays_ordered_and_respects_error_bound():
    t=np.linspace(0,hold.STOP,3001)
    y=np.tanh((t-4.8e-9)/10e-12)
    for shift in (-.15e-9,.2e-9):
        ti,yi=hold.pwl(t,y,shift)
        assert ti[0]==0 and ti[-1]==hold.STOP and np.all(np.diff(ti)>0)
        assert np.max(np.abs(np.interp(t-shift,t,y)-np.interp(t,ti,yi)))<=hold.PWL_TOL_V*(1+1e-8)


def test_long_alter_uses_vector_and_drives_the_actual_source(tmp_path):
    executable=project.ngspice()
    if shutil.which(executable) is None:pytest.skip('ngspice unavailable')
    t=np.linspace(0,hold.STOP,1001)
    y=.5+.4*np.sin(2*np.pi*t/(.17e-9))
    commands=hold.alter_pwl('probe',t,y)
    assert any('replay_pwl=vector(' in x for x in commands)
    deck='\n'.join(['long PWL control regression','Vprobe n 0 PWL(0 0 10n 0)','Rload n 0 1k',
        '.control','set num_threads=1','set filetype=binary',*commands,
        f'tran 1p {hold.STOP:.12e} 0 1p','write probe.raw v(n)','quit','.endc','.end'])
    (tmp_path/'tb.cir').write_text(deck)
    result=subprocess.run([executable,'-b','tb.cir'],cwd=tmp_path,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'too many args' not in (result.stdout+result.stderr)
    w=spice.Waves(tmp_path/'probe.raw')
    assert w.t[-1]>=hold.STOP*(1-1e-7)
    assert np.max(np.abs(w['n']-np.interp(w.t,t,y)))<=hold.PWL_TOL_V+1e-6
