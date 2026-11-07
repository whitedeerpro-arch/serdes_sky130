"""Append internal observations to an archived circuit, without changing stimuli.

--source selects an explicit completed dynamic campaign; --resume uses its own
immutable rendered checkpoint. The shorter run is a diagnostic, not another
256-bit qualification. Common saved voltages must reproduce within 5 mV.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil

import numpy as np

from serdes_flow import project, spice, watch

ROOT = project.ROOT
HERE = Path(__file__).resolve().parent
COLLECTOR = ROOT / 'verification/plotting/tx_parallel_serializer.py'
LOADED_SOURCE = Path(__file__).read_bytes()
LOADED_SHA256 = hashlib.sha256(LOADED_SOURCE).hexdigest()


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def circuit_signature(text):
    """Keep actual input sources, loads and initial conditions in the identity."""
    lines = [line.strip() for line in text.split('.control', 1)[0].splitlines()
             if not line.strip().lower().startswith(('.save ', '.include '))]
    return hashlib.sha256('\n'.join(lines).encode()).hexdigest()


def internal_vectors():
    out = ['v(vbias)', 'v(vgi_bias)', 'v(xtx.xtree.vbias_logic)']
    out += [f'v(xtx.{leg}{i})' for i in range(16) for leg in ('p', 'n')]
    out += [f'v(xtx.xtree.g{rank}_{i}{leg})'
            for rank, count in ((1, 8), (2, 4), (3, 2)) for i in range(count) for leg in ('p', 'n')]
    out += [f'v(xtx.xtree.xr{rank}_{i}.{node})'
            for rank, count in ((1, 8), (2, 4), (3, 2)) for i in range(count)
            for node in ('slp', 'sln', 'ta', 'tb', 'tail')]
    out += [f'v(xtx.xtree.xr4_0.{node})' for node in ('ahp', 'ahn', 'bhp', 'bhn', 'sap', 'san', 'sbp', 'sbn')]
    return out


def instrument(text, stop_s=60e-9, save_start_s=30e-9):
    match = re.search(r'^\.save (.+)$', text, re.M)
    if match is None:
        raise ValueError('source requires one explicit save list')
    vectors = list(dict.fromkeys(match[1].split() + internal_vectors()))
    out, count = re.subn(r'^\.save .+$', '.save ' + ' '.join(vectors), text, flags=re.M)
    if count != 1:
        raise ValueError('requires exactly one save list')
    control = '\n'.join(['.control', 'set num_threads=1', 'set filetype=binary',
                         f'tran 2p {stop_s:.12e} {save_start_s:.12e} 2p',
                         'write waveforms.raw ' + ' '.join(vectors), 'quit', '.endc', '.end', ''])
    return out.split('.control', 1)[0] + control


def prepare(source):
    spec = importlib.util.spec_from_file_location('trace_source_audit', COLLECTOR)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    validated = audit.collect(source)
    original_plan = json.loads((source / 'plan.json').read_text())
    original_deck = (source / 'execution/physical_tb.cir').read_text()
    camp = ROOT / 'results/analog/tx/parallel_trace' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    camp.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source / 'snap', camp / 'snap')
    shutil.copytree(source / 'execution', camp / 'execution/source_snapshot')
    # All project includes, including the channel outside analog/, point to
    # this diagnostic's snapshots. No mutable source enters a resumed run.
    def relocate(match):
        path = Path(match[1]).resolve()
        if path.is_relative_to(source):
            target = camp / path.relative_to(source)
        elif path.is_relative_to(ROOT):
            target = camp / 'execution/source_snapshot' / path.relative_to(ROOT)
        else:
            raise ValueError(f'unarchived project include: {path}')
        if not target.is_file() or sha(target) != sha(path):
            raise ValueError(f'include relocation mismatch: {path}')
        return f'.include "{target}"'
    relocated = re.sub(r'^\.include\s+"([^"]+)"', relocate, original_deck, flags=re.M | re.I)
    physical = instrument(relocated)
    smoke = instrument(relocated, 1.001e-9, 0.)
    if circuit_signature(physical) != circuit_signature(original_deck):
        raise ValueError('instrumentation changed physical circuit or data')
    (camp / 'execution/physical_tb.cir').write_text(physical)
    (camp / 'execution/smoke_tb.cir').write_text(smoke)
    sources = [Path(__file__).resolve(), COLLECTOR]
    sources += [ROOT / 'src/serdes_flow' / name for name in ('project.py', 'spice.py', 'waves.py', 'watch.py')]
    for path in sources:
        target = camp / 'execution/analysis_sources' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path == Path(__file__).resolve():
            target.write_bytes(LOADED_SOURCE)
        else:
            shutil.copyfile(path, target)
    files = [p for folder in ('execution', 'snap') for p in (camp / folder).rglob('*') if p.is_file()]
    plan = dict(mode='internal_trace', source_campaign=str(source.relative_to(ROOT)),
                source_waveform=validated['waveform'], source_waveform_sha256=validated['hashes']['waveform_sha256'],
                source_plan_sha256=sha(source / 'plan.json'), source_summary_sha256=sha(source / 'summary.json'),
                condition=original_plan['condition'], stop_s=60e-9, save_start_s=30e-9,
                circuit_sha256=circuit_signature(physical), pdk_installation_id=project.pdk_installation_id(),
                model_library_sha256=sha(project.model_library()), calibration_window_s=[32e-9, 58e-9], calibration_gate_v=.005,
                snapshot_files={str(p.relative_to(camp)): sha(p) for p in files},
                scope='Same archived native TX circuit and prescribed inputs, extra saved nodes and shorter stop only. Not 256-bit/PVT/noise/startup qualification.')
    (camp / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    return camp, plan


def execute(camp, plan):
    for rel, digest in plan['snapshot_files'].items():
        if sha(camp / rel) != digest:
            raise ValueError(f'checkpoint changed: {rel}')
    if project.pdk_installation_id() != plan['pdk_installation_id'] or sha(project.model_library()) != plan['model_library_sha256']:
        raise ValueError('PDK changed')
    source = ROOT / plan['source_campaign']
    if sha(source / 'summary.json') != plan['source_summary_sha256'] or sha(source / 'plan.json') != plan['source_plan_sha256']:
        raise ValueError('source metadata changed')
    if sha(ROOT / plan['source_waveform']) != plan['source_waveform_sha256']:
        raise ValueError('source waveform changed')
    print(camp, flush=True)
    raw = spice.case_output(camp, 'run', 'waveforms.raw', plan['stop_s'])
    if raw is None:
        if any(path.is_relative_to(camp) for path in watch.ngspice_cwds()):
            raise RuntimeError('campaign still has a live ngspice; observe it instead of restarting')
        for name in ('physical_tb.cir', 'smoke_tb.cir'):
            text = (camp / 'execution' / name).read_text()
            for include in re.findall(r'^\.include\s+"([^"]+)"', text, re.M | re.I):
                path = Path(include)
                if not path.is_relative_to(camp) or str(path.relative_to(camp)) not in plan['snapshot_files']:
                    raise ValueError('runtime include is not in checkpoint')
        smoke = spice.run((camp / 'execution/smoke_tb.cir').read_text(), spice.next_run_dir(camp, 'smoke'), timeout_s=180)
        if not smoke.ok or spice.case_output(camp, 'smoke', 'waveforms.raw', 1e-9) is None:
            raise RuntimeError(f'internal-node smoke failed: {smoke.run_dir}')
        ex = spice.run((camp / 'execution/physical_tb.cir').read_text(), spice.next_run_dir(camp, 'run'),
                       timeout_s=1200, meta=dict(source_campaign=plan['source_campaign'], scope=plan['scope']))
        raw = spice.case_output(camp, 'run', 'waveforms.raw', plan['stop_s'])
        if not ex.ok or raw is None:
            raise RuntimeError(f'incomplete internal trace: {ex.run_dir}')
    execution=json.loads((raw.parent/'execution.json').read_text())
    if (execution['exit_code'] != 0 or execution['timed_out'] or execution['log_failures']
            or sha(raw.parent/'tb.cir') != execution['deck_sha256']
            or execution['deck_sha256'] != sha(camp/'execution/physical_tb.cir')):
        raise ValueError('trace execution or rendered deck failed identity checks')
    actual, original = spice.Waves(raw), spice.Waves(ROOT / plan['source_waveform'])
    start, end = plan['calibration_window_s']
    keep = (actual.t >= start) & (actual.t <= end)
    if not np.any(keep) or actual.t[0] > start or actual.t[-1] < end:
        raise ValueError('calibration window missing')
    errors, currents = {}, {}
    for name in original.names[1:]:
        delta = float(np.max(np.abs(actual[name][keep] - np.interp(actual.t[keep], original.t, original[name]))))
        (currents if name.lower().startswith('i(') else errors)[name] = delta
    calibration = dict(passed=max(errors.values()) <= plan['calibration_gate_v'], gate_v=plan['calibration_gate_v'],
                       window_s=[start, end], max_voltage_error_v=max(errors.values()), voltage_errors=errors,
                       current_errors_a=currents, current_status='ungraded')
    result = dict(condition=plan['condition'], waveform=str(raw.relative_to(ROOT)), waveform_sha256=sha(raw),analysis_source_sha256=LOADED_SHA256,
                  calibration=calibration, scope=plan['scope'], source_campaign=plan['source_campaign'])
    analysis = camp / 'analysis'
    analysis.mkdir(exist_ok=True)
    analysis_source=analysis/('trace_'+LOADED_SHA256+'.py')
    if not analysis_source.exists():
        with analysis_source.open('xb') as stream:
            stream.write(LOADED_SOURCE)
    elif sha(analysis_source) != LOADED_SHA256:
        raise ValueError('archived analyzer changed')
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + LOADED_SHA256[:10] + '.json'
    with (analysis / name).open('x') as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write('\n')
    (camp / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print('calibration', calibration['passed'], 'max_voltage_error_v', calibration['max_voltage_error_v'], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--resume', type=Path)
    args = parser.parse_args()
    if bool(args.source) == bool(args.resume):
        parser.error('select exactly one of --source or --resume')
    if args.source:
        camp, plan = prepare(args.source.resolve())
    else:
        camp = args.resume.resolve()
        plan = json.loads((camp / 'plan.json').read_text())
    execute(camp, plan)


if __name__ == '__main__':
    main()
