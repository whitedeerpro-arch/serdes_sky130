"""TT uses the bare passive section; do not discard its historical evidence."""
import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("rx_lineage", Path(__file__).resolve().parents[1] / "verification/work_packages/wp003_rx_lineage.py")
LINEAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LINEAGE)


def test_tt_bare_hh_section_counts_as_hh_not_tt_hh(monkeypatch):
    monkeypatch.setattr(LINEAGE, "CHECKS", [])
    monkeypatch.setattr(LINEAGE, "STRESS", ("tt_v1800_t27",))
    attempt = dict(path="fixed/tt", is_smoke=False, deck_path="fixed/tt/tb.cir", deck_matches_execution_sha256=True,
                   stimuli_matches_execution_sha256=True, facts=dict(readout=dict(divider=dict(whold_um=40)), bias_kind="real",
                   passive=dict(pdk_high_po_instances=1)), outputs=[dict(condition="tt_v1800_t27", library_section="hh", waveform=dict(status="pass"))])
    campaigns = [dict(path="fixed", conditions=[dict(condition="tt_v1800_t27", attempt_paths=["fixed/tt"], historical_summary={})], attempts=[attempt])]
    rows = LINEAGE.coverage(campaigns)
    assert rows[0]["resistor_corner"] == "hh" and rows[0]["status"] == "pass"
    assert rows[1]["resistor_corner"] == "ll" and rows[1]["status"] == "missing"
