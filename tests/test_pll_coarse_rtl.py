"""Executable regressions for coarse-code confirmation and synchronous clear."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMMON = ['digital/common/rtl/mon_sync.sv', 'digital/common/rtl/mon_persist.sv']


@pytest.mark.skipif(not shutil.which('iverilog') or not shutil.which('vvp'), reason='Icarus Verilog required')
@pytest.mark.parametrize('top,sources', [
    ('tb_mon_persist', ['digital/common/rtl/mon_persist.sv', 'digital/common/tb/tb_mon_persist.sv']),
    ('tb_pll_coarse_persist', COMMON + ['digital/pll/rtl/pll_coarse_ctrl.sv', 'digital/pll/tb/tb_pll_coarse_persist.sv']),
    ('tb_pll_coarse_ctrl', COMMON + ['digital/pll/rtl/pll_coarse_ctrl.sv', 'digital/pll/tb/tb_pll_coarse_ctrl.sv']),
])
def test_coarse_rtl(tmp_path, top, sources):
    executable = tmp_path / 'test.vvp'
    subprocess.run(['iverilog', '-g2012', '-s', top, '-o', str(executable), *sources],
                   cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)
    result = subprocess.run(['vvp', str(executable)], cwd=ROOT, check=True,
                            capture_output=True, text=True, timeout=60)
    assert 'PASS' in result.stdout and 'FAIL' not in result.stdout
