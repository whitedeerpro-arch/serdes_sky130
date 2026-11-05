import json
import time

from serdes_flow import audit, mc, spice, watch


def test_mc_monitor_counts_rows_in_nested_campaign(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "ngspice_cwds", lambda: set())
    deck = mc.deck("monitor\nV1 a 0 1\nR1 a 0 1k", 3, lets={"v": "v(a)"})
    d = tmp_path / "mc/chunk00"
    spice.run(deck, d)
    state, n, total, why = watch.deck_state(d, set(), 4, time.time())
    assert (state, n, total) == ("done", 3, 3)
    line, finished = watch.probe(tmp_path, 4)
    assert finished and "3/3 cases" in line
    # Remove one whole row, preserving a syntactically valid table and exit 0.
    p = d / mc.MC_FILE
    p.write_text("\n".join(p.read_text().splitlines()[:-2]) + "\n")
    assert watch.deck_state(d, set(), 4, time.time())[0] == "FAIL"
    assert audit.inspect(d, set())["state"] == "incomplete_output"


def test_audit_rejects_short_wave_even_with_exit_zero(tmp_path):
    deck = """short result
V1 a 0 1
R1 a 0 1k
C1 a 0 1p
.control
set filetype=binary
tran 1p 5p
write wave.raw v(a)
quit
.endc
.end
"""
    d = tmp_path / "corner"
    spice.run(deck, d)
    assert audit.inspect(d, set())["state"] == "simulation_complete"
    (d / "tb.cir").write_text(deck.replace("tran 1p 5p", "tran 1p 10p"))
    (tmp_path / "plan.json").write_text(json.dumps(dict(decks={"corner": 1, "pending": 1})))
    report = audit.audit(tmp_path)
    assert report["not_started"] == ["pending"]
    assert report["states"] == {"incomplete_output": 1}
    assert report["attempts"][0]["output_failures"][0]["reason"] == "truncated"
