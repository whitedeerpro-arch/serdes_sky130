"""Boundary-condition registry, input-stage signatures and the batch smoke test."""
import json

import pytest

from serdes_flow import boundary, spice

NET = """
.subckt dist s1p s1n s2p s2n o1p o1n vbias vdd vss
X{a} s1p s1n a1p a1n vbias vdd vss buf wn=20 wt=12 rload={r}
Xb a1p a1n o1p o1n vbias vdd vss buf wn=64 wt=64
+ rload=100
X{c} s2p s2n o2p o2n vbias vdd vss buf wn=20 wt=12 rload=400
.ends dist
"""
INPUTS = ("s1p", "s1n", "s2p", "s2n")


def sig(a="a1", r=400, c="c2"):
    return boundary.input_stage_signature(NET.format(a=a, r=r, c=c), "dist", INPUTS)


def test_signature_ignores_names_and_output_side():
    assert sig()["sha"] == sig(a="first", c="other")["sha"]
    assert len(sig()["stages"]) == 2                 # Xb does not touch an input port


def test_signature_sees_input_stage_change():
    assert sig()["sha"] != sig(r=600)["sha"]


def test_registry_roundtrip_and_load_check(tmp_path, monkeypatch):
    monkeypatch.setattr(boundary, "REGISTRY", tmp_path / "bc.json")
    run = tmp_path / "run"
    run.mkdir()
    entry = dict(id="x", kind="voltage_replay", load=dict(cell="dist", **sig()),
                 points={"tt": dict(run=str(run))})
    boundary.register(entry)
    assert boundary.check_load("x", sig())
    with pytest.raises(boundary.BoundaryMismatch):
        boundary.check_load("x", sig(r=600))
    assert not boundary.check_load("x", sig(r=600), allow_mismatch=True)
    with pytest.raises(boundary.BoundaryMismatch):
        boundary.register(entry)                       # no silent overwrite
    boundary.register(dict(entry, points={"ss": dict(run=str(run))}), extend=True)
    assert sorted(boundary.get("x")["points"]) == ["ss", "tt"]
    with pytest.raises(boundary.BoundaryMismatch):
        boundary.register(dict(entry, kind="other", points={"ff": dict(run=str(run))}), extend=True)
    assert json.loads((tmp_path / "bc.json").read_text())[0]["id"] == "x"


def test_spice_number_and_smoke_deck():
    assert spice.spice_number("72n") == pytest.approx(72e-9)
    assert spice.spice_number("1.5meg") == pytest.approx(1.5e6)
    deck = "a\ntran 4p 72n 12n 4p\nb\n"
    assert spice.smoke_deck(deck) == "a\ntran 4p 1.300000e-08 12n 4p\nb\n"
    assert spice.smoke_deck("tran 2p 16n 0 2p\n") == "tran 2p 1.000000e-09 0 2p\n"
