import json
import time
from pathlib import Path

import pytest
from serdes_flow import watch


def plan(path, data):
    (path/'plan.json').write_text(json.dumps(data))


def deck(path, text='write one.raw v(a)\n', *, outputs=(), complete=True):
    path.mkdir(parents=True, exist_ok=True)
    (path/'tb.cir').write_text(text)
    for name in outputs:(path/name).write_text('data')
    if complete:(path/'execution.json').write_text(json.dumps({'exit_code':0,'timed_out':False}))


def test_full_plan_waiting_and_smoke_is_active_not_a_main_case(tmp_path,monkeypatch):
    plan(tmp_path,{'mode':'probe','stop_s':48e-9})
    smoke=tmp_path/'smoke';deck(smoke,outputs=['one.raw'],complete=False)
    monkeypatch.setattr(watch,'ngspice_cwds',lambda:{smoke.resolve()})
    line,finished=watch.probe(tmp_path,4)
    assert 'WAITING' in line and '0/1 cases' in line and not finished
    monkeypatch.setattr(watch,'ngspice_cwds',lambda:set())
    line,finished=watch.probe(tmp_path,4)
    assert 'WAITING' in line and not finished
    deck(tmp_path/'run',outputs=['one.raw'])
    line,finished=watch.probe(tmp_path,4)
    assert '1/1 cases' in line and finished


def test_count_plan_and_deduplicated_resumed_cases(tmp_path,monkeypatch):
    monkeypatch.setattr(watch,'ngspice_cwds',lambda:set())
    plan(tmp_path,{'decks':{'ff':2,'tt':1}})
    deck(tmp_path/'ff','write a.raw v(a)\nwrite b.raw v(a)\n',outputs=['a.raw','b.raw'])
    deck(tmp_path/'ff.r2','write b.raw v(a)\n',outputs=['b.raw'])
    deck(tmp_path/'foo.smoke',outputs=['one.raw'])
    deck(tmp_path/'pilot.r2',outputs=['one.raw'])
    line,finished=watch.probe(tmp_path,4)
    assert '2/3 cases' in line and '1 queued' in line and not finished


def test_prepared_paths_count_writes_and_reject_escaping_paths(tmp_path,monkeypatch):
    monkeypatch.setattr(watch,'ngspice_cwds',lambda:set())
    (tmp_path/'prepared').mkdir()
    (tmp_path/'prepared'/'x.cir').write_text('write a.raw v(a)\nwrdata b.tsv v(b)\nwrite a.raw v(a)\n')
    plan(tmp_path,{'decks':{'case':'prepared/x.cir'}})
    line,finished=watch.probe(tmp_path,4)
    assert '0/2 cases' in line and 'WAITING' in line and not finished
    plan(tmp_path,{'decks':{'case':'../outside.cir'}})
    with pytest.raises(ValueError,match='escapes campaign'):watch.probe(tmp_path,4)
    plan(tmp_path,{'decks':{'case':str(tmp_path/'prepared/x.cir')}})
    with pytest.raises(ValueError,match='relative'):watch.probe(tmp_path,4)


def test_no_plan_counts_write_and_wrdata_without_reading_output(tmp_path,monkeypatch):
    monkeypatch.setattr(watch,'ngspice_cwds',lambda:set())
    deck(tmp_path/'corner','write a.raw v(a)\nwrdata b.tsv v(b)\n',outputs=['a.raw','b.tsv'])
    line,finished=watch.probe(tmp_path,4)
    assert '2/2 cases' in line and finished


def test_mc_retains_row_counting(tmp_path,monkeypatch):
    monkeypatch.setattr(watch,'ngspice_cwds',lambda:set())
    monkeypatch.setattr(watch.mc,'read',lambda d:[1,2,3])
    d=tmp_path/'mc';deck(d,'dowhile mc_k < 3\nwrdata mc.tsv v(a)\n',outputs=['mc.tsv'])
    assert watch.deck_state(d,set(),4,time.time())[:3]==('done',3,3)
