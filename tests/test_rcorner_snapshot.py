import pytest

from serdes_flow import rcorner


def test_resistor_snapshot_refuses_silent_stale_dut(tmp_path, monkeypatch):
    monkeypatch.setattr(rcorner, "ROOT", tmp_path)
    src = tmp_path / "analog/cell.spice"
    src.parent.mkdir()
    src.write_text("R1 a b 1k\n")
    deck = f'test\n.include "{src}"\n'
    first = rcorner.to_pdk(deck, tmp_path / "campaign")
    assert rcorner.to_pdk(deck, tmp_path / "campaign") == first
    old = tmp_path / "campaign/pdk_resistors/analog/cell.spice"
    before = old.read_text()
    src.write_text("R1 a b 2k\n")
    with pytest.raises(ValueError, match="use a new campaign"):
        rcorner.to_pdk(deck, tmp_path / "campaign")
    assert old.read_text() == before
