"""Frozen local includes survive source moves and reject changed resume inputs."""
import importlib.util
from pathlib import Path

import pytest

from serdes_flow import project


def test_recursive_include_snapshot_and_changed_resume(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("layout_review_sim", project.ROOT / "verification/layout/review_sim.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.project, "ROOT", tmp_path)
    src = tmp_path / "source folder"
    src.mkdir()
    (src / "leaf.spice").write_text(".subckt leaf a b\nR0 a b 1k\n.ends\n")
    (src / "top.spice").write_text('.include "leaf.spice"\n.subckt top a b\nX0 a b leaf\n.ends\n')
    out = tmp_path / "campaign"
    deck = f'Title\n.include "{src / "top.spice"}"\n.end\n'
    frozen = module.freeze_includes(deck, out)
    assert str(src) not in frozen
    snapshots = sorted((out / "inputs").glob("*.spice"))
    assert len(snapshots) == 2
    assert all(str(src) not in p.read_text() for p in snapshots)
    assert module.freeze_includes(deck, out) == frozen
    (src / "leaf.spice").write_text(".subckt leaf a b\nR0 a b 2k\n.ends\n")
    with pytest.raises(ValueError, match="Frozen include changed"):
        module.freeze_includes(deck, out)
    assert any("1k" in p.read_text() for p in snapshots)
