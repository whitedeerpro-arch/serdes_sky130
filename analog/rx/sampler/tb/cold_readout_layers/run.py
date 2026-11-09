"""Prepare and resume fixed FS cold RX layered OP diagnostics; no functional grading.

--prepare snapshots the historical deck's declared cell closure and stimuli.
--check verifies provenance and decks without ngspice. --resume runs sequentially.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import uuid

from serdes_flow import boundary, project, spice, watch

ROOT = project.ROOT
SOURCE = ROOT / 'results/analog/rx/sampler/readout_deser/20261105T195801Z_ac_trim32_realbias_rhh'
ORIGINAL = SOURCE / 'fs_v1650_t-40/tb.cir'
STIMULUS = ORIGINAL.parent / 'stimuli.inc'
EXECUTION = ORIGINAL.parent / 'execution.json'
OUT = ROOT / 'results/analog/rx/sampler/cold_readout_layers'
BC = 'rx_c2_far_nominal@ctle_rc'
LAYERS = ('ctle', 'pi', 'sampler', 'readout')
SOLVERS = ('sparse', 'klu')
BASIC = ['bias_vbg', 'vgi_bias', 'vbias', 'vctle', 'op', 'on']
EXTRA = [[], ['dp', 'dn', 'ep', 'en'], ['d0p', 'd0n', 'rkp', 'rkn'], ['w', 'xro.ckq', 'xro.ckqb']]
CURRENTS = {'iref': 'i(Vbias_i0)', 'icml': '@m.xref.xd.xmos.msky130_fd_pr__nfet_01v8[id]',
            'ictle': '@m.xcbias.xmos.msky130_fd_pr__nfet_01v8_lvt[id]', 'idd': 'i(Vdd)'}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def pdk_manifest():
    root = project.model_library().parents[2]
    files = sorted(p for d in (root/'libs.tech/ngspice', root/'libs.ref/sky130_fd_pr/spice')
                   for p in d.rglob('*') if p.is_file())
    if not files:
        raise ValueError('PDK model tree missing')
    return {str(p): sha(p) for p in files}


def instances(text):
    return {line.split()[0].lower(): line for line in text.splitlines()
            if line and line[0].lower() in 'xvibcr' and not line.startswith('*')}


def make_deck(folder, original, layer, solver, includes):
    # Preserve all top-level controls/sources, only remove not-yet-loaded DUTs,
    # their explicit output capacitors, and kick when its Xro nodes do not exist.
    body = original.split('.control', 1)[0]
    lines = []
    removed = []
    for line in body.splitlines():
        low = line.lower()
        name = low.split()[0] if low.split() else ''
        discard = ((layer < 1 and name == 'xpi') or (layer < 2 and name == 'xdut')
                   or (layer < 3 and (name == 'xro' or name == 'ikick'))
                   or (layer < 2 and re.fullmatch(r'c[de][01][pn]', name) is not None)
                   or (layer < 3 and (re.fullmatch(r'c(?:a|b|ae|be)[01]_[0-3]', name) is not None or name == 'cw')))
        if discard:
            removed.append(line)
            continue
        if low.startswith('.include '):
            path = re.search(r'"([^"]+)"', line).group(1)
            if path == 'stimuli.inc':
                line = f'.include "{folder / "snap/stimuli.inc"}"'
            else:
                line = f'.include "{folder / includes[path]}"'
        if low.startswith('.options '):
            line = re.sub(r'\s+klu\b', '', line, flags=re.I)
            if solver == 'klu':
                line += ' klu'
        if low.startswith('.save '):
            continue
        lines.append(line)
    nodes = BASIC + [node for group in EXTRA[:layer+1] for node in group]
    vectors = {f'v{i}': f'v({node})' for i, node in enumerate(nodes)}
    vectors.update(CURRENTS)
    control = ['.control', 'set num_threads=1', 'set wr_vecnames', 'set wr_singlescale', 'op']
    control += [f'let {name}={expr}' for name, expr in vectors.items()]
    control += ['wrdata op.tsv ' + ' '.join(vectors), 'quit', '.endc', '.end']
    deck = '\n'.join(lines + control) + '\n'
    if re.search(r'^\s*\.ic\b|\buic\b', deck, re.I | re.M):
        raise ValueError('unexpected hard initial condition')
    return deck, removed, nodes


def prepare():
    original = ORIGINAL.read_text()
    ex = json.loads(EXECUTION.read_text())
    bc = boundary.get(BC)
    if ex['bc'] != BC or ex['deck_sha256'] != sha(ORIGINAL) or ex['inputs_sha256']['stimuli.inc'] != sha(STIMULUS):
        raise ValueError('source identity mismatch')
    if bc['load']['sha'] != '624029c653372f50':
        raise ValueError('recorded CTLE boundary load changed')
    if original.count('.nodeset ') != 1 or '.options reltol=1e-4 abstol=1p vntol=1u klu' not in original:
        raise ValueError('source OP setup changed')
    folder = OUT / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    includes = {}
    for path in re.findall(r'^\.include\s+"([^"]+)"', original, re.M | re.I):
        if path == 'stimuli.inc':
            continue
        src = Path(path)
        rel = src.relative_to(SOURCE / 'pdk_resistors')
        target = folder/'snap/cells'/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        if re.search(r'^\s*\.(include|lib)\b|\bfile\s*=', target.read_text(), re.I | re.M):
            raise ValueError(f'unhandled nested external dependency: {src}')
        includes[path] = str(target.relative_to(folder))
    (folder/'snap').mkdir(exist_ok=True)
    shutil.copyfile(STIMULUS, folder/'snap/stimuli.inc')
    if re.search(r'^\s*\.(include|lib)\b|\bfile\s*=', STIMULUS.read_text(), re.I | re.M):
        raise ValueError('unhandled stimulus dependency')
    cases = []
    for layer, label in enumerate(LAYERS):
        for solver in SOLVERS:
            deck, removed, nodes = make_deck(folder, original, layer, solver, includes)
            path = folder/'prepared'/f'{label}_{solver}.cir'
            path.parent.mkdir(exist_ok=True)
            path.write_text(deck)
            kept = instances(deck.split('.control')[0])
            load = {k: v for k, v in kept.items() if k.startswith(('x', 'c', 'i'))}
            cases.append(dict(name=f'{label}_{solver}', layer=label, solver=solver,
                              deck=str(path.relative_to(folder)), nodes=nodes, kept=kept,
                              removed=removed, load_signature=hashlib.sha256(json.dumps(load, sort_keys=True).encode()).hexdigest()))
    source_files = [ORIGINAL, STIMULUS, EXECUTION, Path(__file__).resolve(), ROOT/'config/pdk.toml', ROOT/'config/tools.toml'] + [Path(x) for x in includes]
    plan = dict(scope='FS 1.65 V -40 C hh; static OP only; observed/ungraded, not RX functionality',
                boundary_id=BC, boundary=bc, source_sha256={str(p): sha(p) for p in source_files},
                pdk_installation_id=project.pdk_installation_id(), pdk_sha256=pdk_manifest(),
                snapshots={str(p.relative_to(folder)): sha(p) for d in ('snap', 'prepared') for p in (folder/d).rglob('*') if p.is_file()},
                includes=includes, cases=cases, original_hint='unchanged six-node .nodeset; no .ic/uic',
                t0='original PWL replay and PI behavioral sources; Ikick=1 uA only at readout layer',
                method='All original controls and sources retained; omitted downstream instances and their explicit output capacitors; all original declared historical include files snapshotted.')
    (folder/'plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    return folder


def verify(folder):
    plan = json.loads((folder/'plan.json').read_text())
    if boundary.get(BC) != plan['boundary'] or project.pdk_installation_id() != plan['pdk_installation_id'] or pdk_manifest() != plan['pdk_sha256']:
        raise ValueError('boundary or PDK identity changed')
    for path, digest in plan['source_sha256'].items():
        if sha(path) != digest:
            raise ValueError(f'source changed: {path}')
    for path, digest in plan['snapshots'].items():
        if sha(folder/path) != digest:
            raise ValueError(f'snapshot changed: {path}')
    original = ORIGINAL.read_text()
    for c in plan['cases']:
        deck, removed, nodes = make_deck(folder, original, LAYERS.index(c['layer']), c['solver'], plan['includes'])
        if (folder/c['deck']).read_text() != deck or c['removed'] != removed or c['nodes'] != nodes:
            raise ValueError('deck or layer record changed')
    return plan


def read_op(path, nodes):
    lines = path.read_text().splitlines()
    if len(lines) != 2:
        raise ValueError('OP table missing or incomplete')
    names = lines[0].split()
    values = list(map(float, lines[1].split()))
    if len(names) != len(values) or not all(math.isfinite(x) for x in values):
        raise ValueError('invalid OP values')
    row = dict(zip(names, values))
    keys = [f'v{i}' for i in range(len(nodes))] + list(CURRENTS)
    if any(k not in row for k in keys):
        raise ValueError('missing OP vectors')
    return {'voltages': {n: row[f'v{i}'] for i, n in enumerate(nodes)}, 'currents': {k: row[k] for k in CURRENTS}}


def resume(folder, solver):
    with (folder/'.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = verify(folder)
        if any(p == folder or p.is_relative_to(folder) for p in watch.ngspice_cwds()):
            raise ValueError('campaign already active')
        rows = []
        for case in (c for c in plan['cases'] if solver == 'both' or c['solver'] == solver):
            name = case['name']
            candidates = [folder/name] + sorted(folder.glob(name+'.r*'))
            complete = None
            for run in reversed(candidates):
                try:
                    ex = json.loads((run/'execution.json').read_text())
                    if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures'] or sha(run/'tb.cir') != sha(folder/case['deck']):
                        continue
                    complete = (run, read_op(run/'op.tsv', case['nodes']))
                    break
                except (OSError, ValueError, KeyError):
                    continue
            if complete is None:
                if len(watch.ngspice_cwds()) >= 4:
                    raise RuntimeError('global ngspice quota')
                run = spice.next_run_dir(folder, name)
                ex = spice.run((folder/case['deck']).read_text(), run, timeout_s=120, meta={'layer': case['layer'], 'solver': case['solver'], 'bc': BC})
                try:
                    if ex.ok:
                        complete = (run, read_op(run/'op.tsv', case['nodes']))
                except (OSError, ValueError):
                    pass
            row = {'case': name, 'status': 'missing_or_numerical_failure', 'spec_status': 'ungraded'}
            if complete:
                run, values = complete
                row.update(status='observed', values=values, run=str(run.relative_to(ROOT)),
                           execution_sha256=sha(run/'execution.json'), op_sha256=sha(run/'op.tsv'))
            rows.append(row)
        archive = folder/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        archive.mkdir(parents=True, exist_ok=False)
        (archive/'summary.json').write_text(json.dumps({'scope': plan['scope'], 'rows': rows}, indent=2, allow_nan=False)+'\n')
        print(archive)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--check', type=Path)
    group.add_argument('--resume', type=Path)
    ap.add_argument('--solver', choices=('sparse', 'klu', 'both'), default='sparse')
    args = ap.parse_args()
    if args.prepare:
        print(prepare())
    elif args.check:
        verify(args.check.resolve())
        print('checkpoint valid; no ngspice')
    else:
        resume(args.resume.resolve(), args.solver)


if __name__ == '__main__':
    main()
