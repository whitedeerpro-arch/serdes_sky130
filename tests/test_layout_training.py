"""Protect lesson inputs and reject the historical false-pass failure modes."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from serdes_flow.project import ROOT


@pytest.fixture
def lesson(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('layout_training_test', ROOT / 'verification/layout_training/run.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, 'ROOT', tmp_path)
    work = tmp_path / 'lesson'
    hashes = {}
    for relative in m.SNAPSHOTS:
        body = ('frozen ' + str(relative)).encode()
        hashes[str(relative)] = hashlib.sha256(body).hexdigest()
        for view in ('baseline', 'student'):
            target = work / view / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
    (work / 'runner.py').write_text('frozen runner')
    tech = tmp_path / 'tech'
    tech.write_text('fixed PDK')
    manifest = dict(schema=1, cell='inv_std', inputs_sha256=hashes,
                    pdk_files_sha256={str(tech): m.sha(tech)}, student_editable=[str(m.BUILDER)],
                    runner_sha256=m.sha(work / 'runner.py'))
    (work / 'manifest.json').write_text(json.dumps(manifest))
    return m, work, tech


@pytest.mark.parametrize('area', ['baseline_reference', 'student_reference', 'student_checker', 'PDK'])
def test_input_edits_are_rejected_before_any_tool_runs(lesson, monkeypatch, area):
    m, work, tech = lesson
    target = dict(baseline_reference=work / 'baseline' / m.REFERENCE,
                  student_reference=work / 'student' / m.REFERENCE,
                  student_checker=work / 'student' / m.CHECKER, PDK=tech)[area]
    target.write_text('changed input')
    monkeypatch.setattr(m, 'command', lambda *a, **kw: pytest.fail('a tool ran with changed input'))
    with pytest.raises(ValueError, match='changed'):
        m.execute(work, work / 'student')


def test_student_geometry_script_can_change_without_changing_reference(lesson):
    m, work, _ = lesson
    (work / 'student' / m.BUILDER).write_text('student contact edit')
    m.verify(work)


@pytest.mark.parametrize('check_exit,fields', [
    (1, 'DRC_TOTAL 0\nLVS_MATCH True  LVS_PROPERTY_ERRORS False\n'),
    (0, 'DRC_TOTAL 0\nLVS_MATCH True  LVS_PROPERTY_ERRORS True\n'),
    (0, 'LVS_MATCH True  LVS_PROPERTY_ERRORS False\n'),
])
def test_partial_or_failed_checker_never_becomes_a_pass(lesson, monkeypatch, check_exit, fields):
    m, work, _ = lesson

    def fake_command(args, cwd, log):
        if log.name == 'build.log':
            (work / 'student' / m.LAYOUT / 'inv_std.mag').write_text('fake geometry')
        output = fields if log.name == 'check.log' else ''
        log.write_text(output)
        return dict(returncode=check_exit if log.name == 'check.log' else 0,
                    log=str(log), argv=[str(v) for v in args]), output

    monkeypatch.setattr(m, 'command', fake_command)
    with pytest.raises(RuntimeError, match='verification failed'):
        m.execute(work, work / 'student')
    reports = list((work / 'attempts').glob('*/summary.json'))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text())['status'] == 'check_failed'
