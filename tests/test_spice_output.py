"""Binary raw output and tstart give the same waveforms as wrdata text."""
import numpy as np
import pytest

from serdes_flow import spice

DECK = """output format check
V1 in 0 PULSE(0 1 1n 10p 10p 2n 4n)
R1 in out 1k
C1 out 0 1p
.control
tran 1p 10n 0 5p
let vdiff=v(in)-v(out)
let vcopy=v(out)
let vMixed=v(in)
set wr_singlescale
set wr_vecnames
wrdata waveforms.tsv v(out) vdiff vcopy vMixed
quit
.endc
.end
"""


def test_binary_raw_matches_text(tmp_path):
    assert spice.run(DECK, tmp_path / "text").ok
    assert spice.run(spice.binary_output(DECK), tmp_path / "raw").ok
    assert (tmp_path / "raw/waveforms.raw").exists() and not (tmp_path / "raw/waveforms.tsv").exists()
    a = spice.Waves(tmp_path / "text/waveforms.tsv")
    b = spice.Waves(tmp_path / "raw/waveforms.tsv")       # resolves to the .raw
    assert a.names[:3] == b.names[:3] == ["time", "v(out)", "vdiff"]
    assert np.allclose(a.data, b.data, rtol=1e-8, atol=1e-15)
    # A plain copy of a node voltage is "vcopy" in text but "v(vcopy)" in binary raw.
    assert np.allclose(a["vcopy"], b["vcopy"]) and "vcopy" in b and "v(vcopy)" in a
    # Binary write lower-cases names; lookups use the spelling of the deck.
    assert np.allclose(a["vMixed"], b["vMixed"])
    assert (tmp_path / "raw/waveforms.raw").stat().st_size < (tmp_path / "text/waveforms.tsv").stat().st_size


def test_skip_output_before(tmp_path):
    deck = spice.skip_output_before(spice.binary_output(DECK), "6n")
    assert "tran 1p 10n 6n 5p" in deck
    assert spice.run(DECK, tmp_path / "full").ok and spice.run(deck, tmp_path / "late").ok
    full, late = spice.Waves(tmp_path / "full/waveforms.tsv"), spice.Waves(tmp_path / "late/waveforms.raw")
    assert late.t[0] >= 6e-9 - 1e-15 and len(late.t) < len(full.t)
    # Same circuit history: the late window matches the full run.
    assert np.allclose(np.interp(late.t, full.t, full["v(out)"]), late["v(out)"], atol=1e-6)


def test_rewrites_refuse_unexpected_decks():
    with pytest.raises(ValueError):
        spice.binary_output("no output here\n")
    with pytest.raises(ValueError):
        spice.skip_output_before("tran 1p 10n 1n 5p\n", "2n")
