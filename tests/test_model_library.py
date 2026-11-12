"""Library reduction must preserve corner/shared data and reject incomplete inputs."""
from pathlib import Path
import pytest

from serdes_flow.model_library import build


def fixture(tmp):
    root = tmp / 'pdk'
    base = root / 'libs.tech/ngspice'
    base.mkdir(parents=True)
    (base/'sky130.lib.spice').write_text('.lib tt\n.param mc_mm_switch=0\n.include "common.spice"\n.include "sky130_fd_pr__nfet_01v8.model.spice"\n.include "sky130_fd_pr__pfet_01v8.model.spice"\n.endl tt\n.lib ff\n.param corner=99\n.endl ff\n')
    (base/'common.spice').write_text('.param corner=1\n.param shared=123\n')
    (base/'sky130_fd_pr__nfet_01v8.model.spice').write_text('.subckt sky130_fd_pr__nfet_01v8 d g s b\nRbody d s {shared*corner}\n.ends\n')
    (base/'sky130_fd_pr__pfet_01v8.model.spice').write_text('.subckt sky130_fd_pr__pfet_01v8 d g s b\nRbody d s 456\n.ends\n')
    return base/'sky130.lib.spice'


def test_corner_selection_keeps_shared_values_and_excludes_other_family(tmp_path):
    lib = fixture(tmp_path)
    original = lib.read_bytes()
    out = build(lib,'tt',['sky130_fd_pr__nfet_01v8'],tmp_path/'out')
    text = out.read_text()
    assert '.param corner=1' in text and '{shared*corner}' in text
    assert 'corner=99' not in text and '.subckt sky130_fd_pr__pfet' not in text
    assert '.include ' not in text and lib.read_bytes() == original


def test_unknown_primitive_or_section_cannot_produce_library(tmp_path):
    lib = fixture(tmp_path)
    for section,device in [('ss','nfet_01v8'),('tt','nfet_01v8_lvt'),('tt_mm','nfet_01v8')]:
        with pytest.raises(ValueError):build(lib,section,['sky130_fd_pr__'+device],tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_include_cycle_is_rejected(tmp_path):
    lib = fixture(tmp_path)
    (lib.parent/'common.spice').write_text('.include "common.spice"\n')
    with pytest.raises(ValueError,match='recursive'):
        build(lib,'tt',['sky130_fd_pr__nfet_01v8'],tmp_path/'out')
