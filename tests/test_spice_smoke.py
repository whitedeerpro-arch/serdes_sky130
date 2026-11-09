import pytest

from serdes_flow import spice


def test_smoke_shortens_each_tran_and_preserves_options():
    deck = 'tran 1p 20n 3n 5p uic\ntran 2p 30n 12n 4p\ntran 1p 2n uic\n'
    assert spice.smoke_deck(deck) == (
        'tran 1p 4.000000e-09 3n 5p uic\n'
        'tran 2p 1.300000e-08 12n 4p\n'
        'tran 1p 1.000000e-09 uic\n'
    )


def test_multitran_missing_vector_fails_smoke(tmp_path):
    deck = '''smoke
V1 in 0 1
R1 in 0 1k
.control
tran 10p 5n 1n 20p
wrdata first.tsv v(in)
tran 10p 6n 2n 20p
wrdata second.tsv v(missing)
quit
.endc
.end
'''
    with pytest.raises(spice.SmokeTestFailed):
        spice.run_many([(deck, tmp_path / 'run', {})], workers=1)
    assert (tmp_path / 'run.smoke/first.tsv').stat().st_size > 0
    assert not (tmp_path / 'run').exists()


@pytest.mark.parametrize('created', [[], ['first.tsv'], ['first.tsv', 'second.tsv']])
def test_smoke_rejects_missing_or_empty_output(tmp_path, monkeypatch, created):
    deck = 'tran 1p 5n\nwrdata first.tsv v(x)\nwrite second.tsv v(x)\n'
    def fake_run(deck, directory, **kwargs):
        directory.mkdir()
        for name in created:
            (directory / name).write_text('' if name == 'second.tsv' else 'data')
        return spice.Execution(directory, 0, 0)
    monkeypatch.setattr(spice, 'run', fake_run)
    with pytest.raises(spice.SmokeTestFailed, match='second.tsv'):
        spice.run_many([(deck, tmp_path / 'run', {})], workers=1)


def test_dynamic_output_is_explicitly_rejected(tmp_path):
    with pytest.raises(spice.SmokeTestFailed, match='dynamic'):
        spice.run_many([('tran 1p 2n\nwrdata $filename v(x)\n', tmp_path / 'run', {})])


def test_single_tran_smoke_passes(tmp_path):
    deck = '''smoke
V1 in 0 1
R1 in 0 1k
.control
tran 10p 2n
wrdata out.tsv v(in)
quit
.endc
.end
'''
    assert spice.run_many([(deck, tmp_path / 'run', {})], workers=1)[0].ok
    assert not (tmp_path / 'run.smoke').exists()
