"""A completed OP at the wrong forced voltage is not a handoff measurement."""
import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / 'analog/pll/coarse/tb/cp_handoff_mc/run.py'
spec = importlib.util.spec_from_file_location('cp_handoff_measurements', path)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def sample():
    return dict(midup=200e-6, middn=-210e-6, hiup=194e-6, hidn=-211e-6,
                plusup=192e-6, plusdn=-211.1e-6, vhi=1.23, vbg=1.22, vgi=1.05,
                vmid=.825, vathigh=1.23, vatplus=1.25)


@pytest.mark.parametrize('key,value', [('vathigh', .825), ('vatplus', 1.23),
                                      ('hiup', -194e-6), ('midup', float('nan'))])
def test_completed_op_with_wrong_boundary_or_current_is_invalid(key, value):
    row = sample()
    assert pilot.validate(row)
    row[key] = value
    assert not pilot.validate(row)
