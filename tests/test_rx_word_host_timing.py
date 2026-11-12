"""Timing report parsing must retain negative slack and reject empty data."""
import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('host_timing',ROOT/'verification/digital/rx_word_host_timing.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)


def test_worst_path_preserves_violation():
    text='Startpoint: A\nEndpoint: B\n 0.13 slack (MET)\nStartpoint: C\nEndpoint: D\n -2.50 slack (VIOLATED)\n'
    assert a.worst_paths(text)==dict(startpoint='C',endpoint='D',slack_ns=-2.5,status='VIOLATED')
    with pytest.raises(ValueError):a.worst_paths('No paths found')


def test_area_rejects_unmapped_library_cells(tmp_path):
    lib=tmp_path/'x.lib';lib.write_text('    cell ("sky130_test") {\n        area : 3.5;\n')
    assert a.mapped_area(lib,{'sky130_test':2})==7
    with pytest.raises(ValueError):a.mapped_area(lib,{'missing':1})
