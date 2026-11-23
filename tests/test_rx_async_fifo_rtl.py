"""Asynchronous word transport with independent clock phases and reset epochs."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which('iverilog') or not shutil.which('vvp'), reason='Icarus Verilog required')
@pytest.mark.parametrize('address_bits', [1, 2, 4])
def test_async_word_fifo(tmp_path, address_bits):
    executable = tmp_path / 'fifo.vvp'
    subprocess.run(['iverilog', '-g2012', '-s', 'tb_rx_async_word_fifo',
                    '-P', f'tb_rx_async_word_fifo.ADDR_BITS={address_bits}', '-o', str(executable),
                    'digital/rx/rtl/rx_async_word_fifo.sv', 'digital/rx/tb/tb_rx_async_word_fifo.sv'],
                   cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)
    result = subprocess.run(['vvp', str(executable)], cwd=ROOT, check=True,
                            capture_output=True, text=True, timeout=30)
    assert 'PASS' in result.stdout and 'FAIL' not in result.stdout
