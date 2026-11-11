"""Isolated, reproducible layout lesson using a snapshot of the existing inverter.

prepare copies inputs; run rebuilds and invokes the unchanged DRC/LVS checker;
fault-demo removes the drain connection in a separate copy. No ngspice launch.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from serdes_flow.project import ROOT

LAYOUT = Path('analog/common/layout_practice')
BUILDER = LAYOUT / 'build_inv_std.py'
REFERENCE = LAYOUT / 'inv_std_ref.spice'
CHECKER = Path('verification/layout/check.py')
SEED = Path(__file__).resolve().parent / 'seed'
SEED_FILES = (BUILDER, REFERENCE, CHECKER, Path('verification/layout/magicutil.py'),
              Path('verification/layout/plot_mag.py'))
SNAPSHOTS = (*SEED_FILES, Path('config/pdk.toml'),
             Path('docs/layout/tasks.md'), Path('docs/layout/cookbook.md'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_id():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:8]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def prepare():
    import tomllib
    out = ROOT / 'results/layout_training/ds01' / run_id()
    out.mkdir(parents=True)
    hashes = {}
    origin = json.loads((SEED / 'ORIGIN.json').read_text())
    frozen = {r['snapshot']: r['sha256'] for r in origin['files']}
    for relative in SNAPSHOTS:
        source = (SEED if relative in SEED_FILES else ROOT) / relative
        body = source.read_bytes()
        hashes[str(relative)] = hashlib.sha256(body).hexdigest()
        if relative in SEED_FILES and hashes[str(relative)] != frozen[str(relative)]:
            raise ValueError('teaching seed identity changed: ' + str(relative))
        if relative == REFERENCE and not all(s in body.decode() for s in
                ('.subckt inv_std d g vdd vss', 'nfet_01v8 w=4 l=0.15', 'pfet_01v8 w=8 l=0.15')):
            raise ValueError('training reference has changed; mentor must review the new exercise')
        for view in ('baseline', 'student'):
            target = out / view / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        if source.read_bytes() != body:
            raise ValueError('input changed during preparation')
    pdk = tomllib.loads((ROOT / 'config/pdk.toml').read_text())['pdk']
    pdk_root = Path(pdk['path'])
    fingerprints = {str(pdk_root / rel): sha(pdk_root / rel) for rel in
                    (pdk['magic_rc'], 'libs.tech/magic/sky130A.tech', pdk['netgen_setup'])}
    manifest = dict(schema=1, lesson='DS-01', cell='inv_std', created_utc=datetime.now(timezone.utc).isoformat(),
                    source_root=str(ROOT), inputs_sha256=hashes, pdk_files_sha256=fingerprints,
                    seed_origin_sha256=sha(SEED / 'ORIGIN.json'),
                    student_editable=[str(BUILDER)], reference=str(REFERENCE),
                    scope='Local-host layout exercise; frozen checker/reference; no production DUT changes or circuit signoff.',
                    runner_sha256=sha(Path(__file__).resolve()))
    shutil.copyfile(__file__, out / 'runner.py')
    write_json(out / 'manifest.json', manifest)
    print(out.relative_to(ROOT))
    print('Run: uv run python verification/layout_training/run.py run ' + str(out.relative_to(ROOT)))
    return out


def verify(work):
    manifest = json.loads((work / 'manifest.json').read_text())
    if manifest['schema'] != 1 or manifest['cell'] != 'inv_std':
        raise ValueError('unexpected lesson identity')
    if sha(work / 'runner.py') != manifest['runner_sha256']:
        raise ValueError('prepared runner snapshot changed')
    for relative, expected in manifest['inputs_sha256'].items():
        if sha(work / 'baseline' / relative) != expected:
            raise ValueError('baseline changed: ' + relative)
        if relative not in manifest['student_editable'] and sha(work / 'student' / relative) != expected:
            raise ValueError('student changed a read-only input: ' + relative)
    for path, expected in manifest['pdk_files_sha256'].items():
        if sha(Path(path)) != expected:
            raise ValueError('PDK changed: ' + path)
    return manifest


def command(args, cwd, log):
    p = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True, timeout=1800)
    body = p.stdout + p.stderr
    log.write_text(body)
    return dict(argv=[str(a) for a in args], returncode=p.returncode, log=str(log)), body


def execute(work, view_root, expected_failure=False):
    manifest = verify(work)
    attempt = work / 'attempts' / run_id()
    attempt.mkdir(parents=True)
    shutil.copyfile(__file__, attempt / 'runner.py')
    target = view_root / LAYOUT
    build, output = command([sys.executable, view_root / BUILDER], work, attempt / 'build.log')
    if build['returncode'] != 0 or not (target / 'inv_std.mag').is_file():
        write_json(attempt / 'summary.json', dict(status='build_failed', build=build))
        raise RuntimeError('build failed: ' + build['log'])
    check, output = command([sys.executable, work / 'baseline' / CHECKER, target, 'inv_std',
                             '--ref', work / 'baseline' / REFERENCE], work, attempt / 'check.log')
    # Do not turn a failed run into success by grepping a partial log. All
    # three fields AND the process return code are required for a pass.
    import re
    flags = dict(DRC_TOTAL=(int(m[1]) if (m := re.search(r'^DRC_TOTAL (\d+)$', output, re.M)) else None),
                 LVS_MATCH=(m[1] == 'True' if (m := re.search(r'LVS_MATCH (True|False)', output)) else None),
                 LVS_PROPERTY_ERRORS=(m[1] == 'True' if (m := re.search(r'LVS_PROPERTY_ERRORS (True|False)', output)) else None))
    passed = check['returncode'] == 0 and flags == dict(DRC_TOTAL=0, LVS_MATCH=True, LVS_PROPERTY_ERRORS=False)
    expected_open = (check['returncode'] != 0 and flags['DRC_TOTAL'] == 0
                     and flags['LVS_MATCH'] is False and flags['LVS_PROPERTY_ERRORS'] is False
                     and re.search(r'Circuit 1 contains\s+5 nets,\s+Circuit 2 contains\s+4 nets', output) is not None)
    plotting, _ = command([sys.executable, work / 'baseline/verification/layout/plot_mag.py',
                            target / 'inv_std.mag', attempt / 'layout.png'], work, attempt / 'plot.log')
    files = [view_root / BUILDER, target / 'inv_std.mag', work / 'baseline' / REFERENCE,
             target / 'inv_std_lvs.spice', target / 'inv_std_pex.spice']
    result = dict(status=('expected_open_detected' if expected_failure and expected_open else
                          'layout_checks_pass' if passed and not expected_failure else 'check_failed'),
                  view=str(view_root.relative_to(work)), build=build, check=check, plot=plotting, fields=flags,
                  runner_sha256=sha(attempt / 'runner.py'),
                  files_sha256={str(p.relative_to(work)): sha(p) for p in files if p.exists()},
                  reference_sha256=manifest['inputs_sha256'][str(REFERENCE)],
                  scope='DRC/LVS training only; no current capacity, PVT, timing, noise or complete extracted-RC qualification.')
    write_json(attempt / 'summary.json', result)
    verify(work)
    print(output)
    print('TRAINING_RESULT', result['status'])
    print('EVIDENCE', attempt.relative_to(ROOT))
    if result['status'] == 'check_failed':
        raise RuntimeError('layout verification failed; see ' + str(attempt))
    return attempt, result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='action', required=True)
    commands.add_parser('prepare')
    for name in ('run', 'verify', 'fault-demo'):
        c = commands.add_parser(name)
        c.add_argument('workspace', type=Path)
        if name == 'run':
            c.add_argument('--view', choices=('baseline', 'student'), default='student')
    a = p.parse_args()
    if a.action == 'prepare':
        prepare()
        return
    work = a.workspace.resolve()
    verify(work)
    if a.action == 'verify':
        print('INPUTS_UNCHANGED True')
    elif a.action == 'run':
        execute(work, work / a.view)
    else:
        fault = work / 'faults' / run_id()
        shutil.copytree(work / 'baseline', fault)
        path = fault / BUILDER
        text = path.read_text()
        original = '    t.append(f"R m1 4.01 2.80 4.29 13.70")'
        if text.count(original) != 1:
            raise ValueError('drain-route demonstration no longer matches the seed')
        path.write_text(text.replace(original, '    # Teaching fault: drain connection deliberately omitted.'))
        execute(work, fault, expected_failure=True)


if __name__ == '__main__':
    main()
