import importlib.util
import subprocess
import sys
from types import SimpleNamespace

import pytest

from serdes_flow import spice
from serdes_flow.project import ROOT

spec = importlib.util.spec_from_file_location('boundary_readonly_tests', ROOT/'verification/analysis/vco_boundary_readonly.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_reader_guard_allows_reading_and_existing_directories(tmp_path):
    source = tmp_path/'input.txt'
    source.write_text('unchanged')
    previous = sys.getprofile()
    with audit.ReadOnlyVerification(tmp_path, SimpleNamespace(ROOT=ROOT)):
        assert source.read_text() == 'unchanged'
        tmp_path.mkdir(exist_ok=True)
    assert sys.getprofile() is previous
    assert source.read_text() == 'unchanged'


@pytest.mark.parametrize('operation', ['write', 'mkdir', 'spice', 'subprocess'])
def test_reader_guard_rejects_side_effects_before_they_happen(tmp_path, operation):
    target = tmp_path/'must_not_exist'
    previous = sys.getprofile()
    with pytest.raises((RuntimeError, PermissionError)):
        with audit.ReadOnlyVerification(tmp_path, SimpleNamespace(ROOT=ROOT)):
            if operation == 'write': target.write_text('forbidden')
            elif operation == 'mkdir': target.mkdir()
            elif operation == 'spice': spice.run('never executed', target)
            else: subprocess.run(['/bin/true'], check=True)
    assert not target.exists()
    assert sys.getprofile() is previous
