"""Prepare/resume 3 hot-code CP-edge VCO sweeps; no original campaign is modified.

    uv run python analog/pll/vco/tb/tuning/cp_edge_fill.py --check
    uv run python analog/pll/vco/tb/tuning/cp_edge_fill.py --prepare
    uv run python analog/pll/vco/tb/tuning/cp_edge_fill.py --resume results/analog/pll/vco/cp_edge_fill/<id>

--check renders in a temporary directory only. --prepare creates a new immutable
manifest and decks; only --resume invokes ngspice. One process by default.
"""
import argparse
import hashlib
import fcntl
import math
import os
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import workmap
from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT, model_library, pdk_installation_id

CP = ROOT / 'results/analog/pll/cp/window/20261106T021356Z/summary.json'
OUT = ROOT / 'results/analog/pll/vco/cp_edge_fill'
CASES = [('ff', 'tt', 7), ('ff', 'll', 12), ('fs', 'll', 7)]
STOP = 24e-9
START = 19e-9


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def points():
    cp = json.loads(CP.read_text())['rows']
    groups = {}
    for process, rc, code in CASES:
        c = Condition.parse(f'{process}_v1950_t85')
        edge = cp[f'{c.tag}:{rc}']['hi']
        volts = sorted({round(v, 3) for v in (0.85, 1.50, edge - 0.05, edge)})
        groups[f'{process}_{rc}'] = [(rc, c, code, v) for v in volts]
    return groups


def render(camp, name, pts):
    deck = workmap.deck(pts[0][1].process, pts[0][0], [(c, k, v) for _, c, k, v in pts], camp / 'snap' / name, bank=4)
    old = f'tran 2p {STOP:.4e} {workmap.START:.4e}'
    new = f'tran 2p {STOP:.4e} {START:.4e}'
    if deck.count(old) != len(pts):
        raise ValueError('unexpected workmap transient format')
    deck = deck.replace(old, new)
    assert deck.count(new) == len(pts) and 'set filetype=binary' in deck
    assert '.control' in deck and '.endc' in deck and 'cfg3' in deck
    return deck


def prepare(camp):
    camp.mkdir(parents=True, exist_ok=False)
    groups = points()
    decks = {}
    for name, pts in groups.items():
        deck = render(camp, name, pts)
        path = camp / 'prepared' / f'{name}.cir'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(deck)
        decks[name] = str(path.relative_to(camp))
    # Capture all project includes and their rendered PDK-resistor snapshots.
    includes = set()
    for rel in decks.values():
        for item in re.findall(r'^\.include\s+"([^"]+)"', (camp / rel).read_text(), re.M | re.I):
            includes.add(Path(item))
    # Rewritten cells must also be tied to their pre-rewrite source identities.
    for path in list(includes):
        marker = '/pdk_resistors/'
        if marker in str(path):
            includes.add(ROOT / str(path).split(marker, 1)[1])
    sources = includes | {CP, ROOT / 'config/pdk.toml', ROOT / 'config/tools.toml',
                          ROOT / 'analog/pll/vco/tb/tuning/workmap.py', Path(__file__).resolve(),
                          ROOT / 'src/serdes_flow/spice.py', ROOT / 'src/serdes_flow/waves.py',
                          ROOT / 'src/serdes_flow/bias.py', ROOT / 'src/serdes_flow/rcorner.py',
                          workmap.TEMPLATE, model_library()}
    identity = {str(p): sha(p) for p in sorted(sources)}
    # Snapshot project sources and config, alongside the rendered cell snapshots.
    archived = {}
    for source in sorted(sources):
        try:
            rel = source.relative_to(ROOT)
        except ValueError:
            continue  # PDK identity and library digest are recorded separately.
        if camp in source.parents:
            continue
        dest = camp / 'source' / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        archived[str(dest.relative_to(camp))] = sha(dest)
    manifest = {'schema': 1, 'pdk_installation_id': pdk_installation_id(),
                'stop_s': STOP, 'save_from_s': START, 'workers_max': 1,
                'input_sha256': identity, 'archived_source_sha256': archived, 'prepared_decks': {k: {'path': v, 'sha256': sha(camp / v)} for k, v in decks.items()},
                'cases': {k: [{'condition': c.tag, 'passive': rc, 'code': code, 'vctrl_v': v,
                               'raw': workmap.name(c, code, v)} for rc, c, code, v in pts] for k, pts in groups.items()}}
    (camp / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return manifest


def subset_deck(prepared, all_cases, missing):
    """Filter complete alter/tran/write blocks from the immutable prepared deck."""
    wanted = {x['raw'] for x in missing}
    prefix, control = prepared.split('\n.control\n', 1)
    header, body = control.split('set filetype=binary\n', 1)
    chunks = body.split('destroy all\n')
    assert len(chunks) == len(all_cases) + 1
    selected = []
    for case, chunk in zip(all_cases, chunks):
        assert f"write {case['raw']} " in chunk
        if case['raw'] in wanted:
            selected.append(chunk + 'destroy all\n')
    assert len(selected) == len(missing)
    return prefix + '\n.control\n' + header + 'set filetype=binary\n' + ''.join(selected) + chunks[-1]


def run_resume(camp):
    manifest = json.loads((camp / 'manifest.json').read_text())
    if manifest['pdk_installation_id'] != pdk_installation_id():
        raise RuntimeError('PDK installation changed')
    for path, digest in manifest['input_sha256'].items():
        if sha(path) != digest:
            raise RuntimeError(f'input changed: {path}')
    for path, digest in manifest['archived_source_sha256'].items():
        if sha(camp / path) != digest:
            raise RuntimeError(f'archived source changed: {path}')
    for info in manifest['prepared_decks'].values():
        if sha(camp / info['path']) != info['sha256']:
            raise RuntimeError('prepared deck changed')
    jobs = []
    missing_groups = []
    for name, cases in manifest['cases'].items():
        missing = [r for r in cases if spice.case_output(camp, name, r['raw'], STOP) is None]
        if not missing:
            continue
        prepared = (camp / manifest['prepared_decks'][name]['path']).read_text()
        deck = subset_deck(prepared, cases, missing)
        jobs.append((deck, spice.next_run_dir(camp, name), {'timeout_s': 600 + 60 * len(missing), 'meta': {'cases': missing}}))
        missing_groups.append((name, cases, missing))
    if jobs:
        name, cases, missing = missing_groups[0]
        prepared = (camp / manifest['prepared_decks'][name]['path']).read_text()
        one = subset_deck(prepared, cases, missing[:1])
        one = one.replace(f'tran 2p {STOP:.4e} {START:.4e}', 'tran 2p 1.001e-9 0')
        smoke_dir = spice.next_run_dir(camp, 'smoke')
        ex = spice.run(one, smoke_dir, timeout_s=660, meta={'purpose': '1.001 ns smoke from zero'})
        if not ex.ok or spice.case_output(camp, smoke_dir.name, missing[0]['raw'], 1.001e-9) is None:
            raise RuntimeError(f'smoke failed: {smoke_dir}')
        results = spice.run_many(jobs, workers=1, smoke=False)
        for ex in results:
            print(ex.run_dir, 'ok' if ex.ok else f'FAILED: {ex.log_failures}')
    report = {}
    for name, cases in manifest['cases'].items():
        samples = []
        for case in cases:
            path = spice.case_output(camp, name, case['raw'], STOP)
            value, error = None, None
            try:
                value = workmap.measure(path) if path else None
                if value is not None and (len(value) != 2 or not all(math.isfinite(float(x)) for x in value) or value[0] <= 0):
                    error, value = 'nonfinite or invalid measurement', None
            except Exception as exc:  # Preserve failed analysis as ungraded, including malformed waveforms.
                error = f'{type(exc).__name__}: {exc}'
                value = None
            if path and value is None and error is None:
                error = 'measurement returned None (insufficient crossings)'
            run_dir = path.parent if path else None
            execution = run_dir / 'execution.json' if run_dir else None
            deck_path = run_dir / 'tb.cir' if run_dir else None
            samples.append({**case, 'frequency_hz': float(value[0]) if value else None,
                            'swing_vpp': float(value[1]) if value else None, 'measurement_error': error,
                            'raw_path': str(path) if path else None, 'raw_sha256': sha(path) if path else None,
                            'execution_sha256': sha(execution) if execution and execution.is_file() else None,
                            'deck_sha256': sha(deck_path) if deck_path and deck_path.is_file() else None})
        valid = [r for r in samples if r['frequency_hz'] is not None]
        brackets = []
        for a, b in zip(samples, samples[1:]):
            if a['frequency_hz'] is None or b['frequency_hz'] is None:
                continue
            if min(a['frequency_hz'], b['frequency_hz']) <= 2e9 <= max(a['frequency_hz'], b['frequency_hz']):
                v = a['vctrl_v'] if a['frequency_hz'] == b['frequency_hz'] else a['vctrl_v'] + (2e9 - a['frequency_hz']) * (b['vctrl_v'] - a['vctrl_v']) / (b['frequency_hz'] - a['frequency_hz'])
                brackets.append({'voltage_interpolated_v': v, 'headroom_to_measured_cp_edge_v': cases[-1]['vctrl_v'] - v})
        report[name] = {'samples': samples, 'static_brackets': brackets, 'complete': len(valid) == len(cases)}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = camp / f'report_{stamp}.json'
    path.write_text(json.dumps({'scope': 'static 2 GHz bracket only; no startup or lock judgment', 'analysis_source_sha256': {str(Path(__file__).resolve()): sha(Path(__file__).resolve()), str(Path(workmap.__file__).resolve()): sha(workmap.__file__), str(ROOT / 'src/serdes_flow/waves.py'): sha(ROOT / 'src/serdes_flow/waves.py'), str(ROOT / 'src/serdes_flow/spice.py'): sha(ROOT / 'src/serdes_flow/spice.py')}, 'rows': report}, indent=2) + '\n')
    print(path)


def resume(camp):
    # A flock serializes cooperating runners; inspect process cwd as well so an
    # ngspice child orphaned by a killed parent cannot be overlapped.
    with (camp / '.resume.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('campaign resume already active') from exc
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():
                continue
            try:
                exe = os.readlink(proc / 'exe')
                cwd = Path(os.readlink(proc / 'cwd')).resolve()
                if 'ngspice' in Path(exe).name.lower() and (cwd == camp or camp in cwd.parents):
                    raise RuntimeError(f'live ngspice in campaign: pid {proc.name}')
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
        return run_resume(camp)


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--resume', type=Path)
    ap.add_argument('--workers', type=int, default=1, choices=[1])
    a = ap.parse_args()
    if a.check:
        with tempfile.TemporaryDirectory() as temp:
            m = prepare(Path(temp) / 'campaign')
            print('rendered', len(m['cases']), 'decks and', sum(map(len, m['cases'].values())), 'points; no ngspice')
    elif a.prepare:
        OUT.mkdir(parents=True, exist_ok=True)
        camp = OUT / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        prepare(camp)
        print(camp)
    else:
        camp = a.resume.resolve()
        if camp.parent != OUT.resolve():
            raise ValueError('resume must name a cp_edge_fill campaign')
        resume(camp)


if __name__ == '__main__':
    main()
