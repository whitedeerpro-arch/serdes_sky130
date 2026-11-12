"""Functional integration of physical RX word map, alignment and host CDC."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which('iverilog') or not shutil.which('vvp'),reason='Icarus required')
def test_host_path(tmp_path):
    out=tmp_path/'test.vvp'
    sources=[f'digital/rx/rtl/{x}.sv' for x in ('rx_word_map','rx_word_align16','rx_async_word_fifo','rx_word_host_path')]
    sources+=['digital/rx/tb/tb_rx_word_host_path.sv']
    subprocess.run(['iverilog','-g2012','-s','tb_rx_word_host_path','-o',str(out),*sources],cwd=ROOT,check=True,capture_output=True,text=True,timeout=30)
    p=subprocess.run(['vvp',str(out)],cwd=ROOT,check=True,capture_output=True,text=True,timeout=30)
    assert 'PASS' in p.stdout and 'FAIL' not in p.stdout
