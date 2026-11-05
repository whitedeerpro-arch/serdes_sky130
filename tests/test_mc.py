"""MC reproducibility, completion and safe restart (real ngspice, small resistor decks)."""
import json

import numpy as np
import pytest

from serdes_flow import mc, spice

NET = """MC seed check
V1 in 0 1
R1 in out {1000 + agauss(0,100,1)}
R2 out 0 1k
"""


def test_seed_and_last_reload(tmp_path):
    deck = mc.deck(NET, 4, seed=1234, lets={"voltage": "v(out)"})
    old = deck.replace("  if mc_k < 4\n    mc_source\n  end", "  mc_source")
    for name, text in (("new", deck), ("old", old), ("again", deck)):
        assert spice.run(text, tmp_path / name).ok
    rows = mc.read(tmp_path / "new")
    assert rows == mc.read(tmp_path / "old") == mc.read(tmp_path / "again")
    assert len(set(mc.column(rows, "voltage"))) == 4
    assert mc.complete(tmp_path / "new", deck)


def test_transient_end_and_expected_missing_measurement(tmp_path):
    deck = mc.deck(NET, 2, analysis="tran 1p 10p\nmeas tran missing when v(out)=2 rise=1",
                   lets={"value": "missing"}, t_end=10e-12)
    spice.run(deck, tmp_path / "full")
    assert mc.complete(tmp_path / "full", deck)
    assert np.isnan(mc.read(tmp_path / "full")[0]["value"])
    spice.run(deck.replace("tran 1p 10p", "tran 1p 5p"), tmp_path / "short")
    assert not mc.complete(tmp_path / "short", deck)


def test_restart_and_changed_includes(tmp_path):
    inc = tmp_path / "cell.spice"
    inc.write_text("R2 out 0 1k\n")
    net = NET.replace("R2 out 0 1k", f'.include "{inc}"')
    deck = mc.deck(net, 3, lets={"voltage": "v(out)"})
    base = tmp_path / "campaign/chunk00"
    jobs = [(deck, base, {})]
    assert mc.run_many(jobs, workers=1) == [base]
    original = (base / "mc.tsv").read_text()
    assert mc.run_many(jobs, workers=1) == [base]
    # Simulate a timed-out run with a misleading, otherwise complete execution record.
    ex = json.loads((base / "execution.json").read_text())
    ex["timed_out"] = True
    (base / "execution.json").write_text(json.dumps(ex))
    retry = mc.run_many(jobs, workers=1)[0]
    assert retry.name == "chunk00.r2" and (base / "mc.tsv").read_text() == original
    assert mc.read(retry) == mc.read(base)
    assert mc.run_many(jobs, workers=1) == [retry]
    inc.write_text("R2 out 0 2k\n")
    with pytest.raises(ValueError, match="inputs changed"):
        mc.run_many(jobs, workers=1)


def test_short_rows_and_legacy_not_reused(tmp_path):
    deck = mc.deck(NET, 2, lets={"voltage": "v(out)"})
    base = tmp_path / "chunk"
    spice.run(deck, base)
    # Without a manifest the include content at the time of execution is unknowable.
    with pytest.warns(UserWarning, match="legacy inputs"):
        retry = mc.run_many([(deck, base, {})], workers=1)[0]
    assert retry.name == "chunk.r2"
    manifest = json.loads((tmp_path / "chunk.inputs.json").read_text())
    assert manifest["unverified_attempts"] == ["chunk"]
    (retry / "mc.tsv").write_text("scale voltage\n0 0.4\nscale voltage\n0")
    with pytest.raises(ValueError, match="incomplete MC row"):
        mc.read(retry)
    assert not mc.complete(retry, deck)
    # A broken authenticated retry must never fall back to the unauthenticated original.
    assert mc.run_many([(deck, base, {})], workers=1)[0].name == "chunk.r3"


@pytest.mark.parametrize("samples,per", [(0, 50), (1, 0), (-1, 1)])
def test_bad_chunk_sizes(samples, per):
    with pytest.raises(ValueError):
        mc.chunks(samples, 1, per)
