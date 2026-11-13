"""Reject the Gemini varactor false pass: matching devices, no exported pins."""
import importlib.util
import sys
from types import SimpleNamespace

import pytest

from serdes_flow.project import ROOT


@pytest.mark.parametrize("header,expected", [
    (".subckt device", 1),
    ("* Top level circuit device", 1),
    (".subckt device a b", 0),
    (".subckt device a\n+ b params: size=1", 0),
])
def test_unique_graph_match_also_requires_exported_interface(tmp_path, monkeypatch, capsys, header, expected):
    spec = importlib.util.spec_from_file_location("layout_check_ports", ROOT / "verification/layout/check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "device_lvs.spice").write_text(
        header + "\nX0 a b sky130_fd_pr__cap_mim_m3_1 w=2 l=2\n.ends\n"
    )
    ref = tmp_path / "reference.spice"
    ref.write_text(".subckt device a b\nX0 a b sky130_fd_pr__cap_mim_m3_1 w=2 l=2\n.ends\n")
    monkeypatch.setattr(module, "drc", lambda *args: (0, ""))
    monkeypatch.setattr(module, "extract", lambda *args: None)
    monkeypatch.setattr(module.mu, "netgen", lambda *args: SimpleNamespace(stdout="Circuits match uniquely."))
    monkeypatch.setattr(sys, "argv", ["check.py", str(tmp_path), "device", "--ref", str(ref)])
    with pytest.raises(SystemExit) as result:
        module.main()
    assert result.value.code == expected
    assert "LVS_EXPORTED_PORTS" in capsys.readouterr().out
