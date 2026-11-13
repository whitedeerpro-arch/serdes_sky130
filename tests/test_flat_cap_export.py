"""Regression: cap top and MOS gate self-capacitances must keep their nets."""
import importlib.util
from pathlib import Path
import sys

import pytest

from serdes_flow.project import ROOT
from serdes_flow.spice import spice_number

spec = importlib.util.spec_from_file_location("flat_cap_export", ROOT / "verification/layout/flat_cap_export.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def inputs(tmp_path, extra=""):
    ext = tmp_path / "cell.ext"
    ext.write_text('scale 1000 1 500000\n'
                   'node "q" 0 200 0 0 m4\n'
                   'node "g" 0 900 0 0 m2\n'
                   'node "plate" 0 1000 0 0 m3\n'
                   'substrate "vss" 0 0 0 0 m2\n'
                   'cap "q" "plate" 400\n'
                   'device csubckt dummy\n' + extra)
    lvs = tmp_path / "lvs.spice"
    lvs.write_text('.subckt cell q g vss\nXc q plate cap w=2 l=2\nXn plate g vss vss mos w=1.5 l=.15\n.ends\n')
    return ext, lvs, tmp_path / "cap.spice"


def test_preserves_top_gate_plate_ground_and_coupling(tmp_path):
    ext, lvs, out = inputs(tmp_path)
    result = module.export(ext, lvs, out)
    assert result['self_fF'] == pytest.approx(dict(q=.2, g=.9, plate=1., vss=0))
    caps = {frozenset(line.split()[1:3]):float(line.split()[3])
            for line in out.read_text().splitlines() if line.startswith('Cpex')}
    assert caps == pytest.approx({frozenset(['q','vss']):.2e-15, frozenset(['g','vss']):.9e-15,
        frozenset(['plate','vss']):1e-15, frozenset(['q','plate']):.4e-15}, abs=1e-27)
    assert 'Xn plate g vss vss mos w=1.5 l=.15' in out.read_text()


@pytest.mark.parametrize('extra', ['use child inst\n', 'equiv "q" "p"\n',
                                  'device rsubckt resistor\n'])
def test_unsupported_mapping_fails_closed(tmp_path, extra):
    ext, lvs, out = inputs(tmp_path, extra)
    with pytest.raises(ValueError):
        module.export(ext, lvs, out)
    assert not out.exists()


@pytest.mark.parametrize("hierarchy", ["on", "off"])
def test_installed_magic_preserves_device_gate_and_top_caps(tmp_path, hierarchy):
    """Exercise both ext2hier.c and ext2spice.c, not just our Python parser."""
    sys.path.insert(0, str(ROOT / "verification/layout"))
    import magicutil as mu
    if not Path(mu.MAGIC).is_file() or not mu.RCFILE.is_file():
        pytest.skip("Local Magic/PDK not installed")
    (tmp_path / "unit.ext").write_text((ROOT / "tests/fixtures/layout/switch_mim.ext").read_text())
    script = tmp_path / "export.tcl"
    script.write_text(f"cd {tmp_path}\next2spice lvs\next2spice hierarchy {hierarchy}\n"
                      "ext2spice cthresh 0\next2spice -o matrix.spice unit.ext\nquit -noprompt\n")
    result = mu.run_magic(script, tmp_path)
    result.need("known capacitance injection")
    caps = {frozenset(line.split()[1:3]): spice_number(line.split()[3])*1e15
            for line in (tmp_path / "matrix.spice").read_text().splitlines() if line.startswith("C")}
    assert caps[frozenset(["node", "vss"])] == pytest.approx(.2)
    assert caps[frozenset(["en", "vss"])] == pytest.approx(.9)
    assert caps[frozenset(["a_n33_n75#", "vss"])] == pytest.approx(1.)
    assert caps[frozenset(["node", "a_n33_n75#"])] == pytest.approx(.40643)
