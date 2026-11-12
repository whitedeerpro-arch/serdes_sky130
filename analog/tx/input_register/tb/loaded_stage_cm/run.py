"""Direct Xe4/Xout common-mode perturbations with the preceding load retained.

Equal ideal series DC sources shift both input legs. They preserve electrical
loading and the driven differential voltage, but are an experiment, not an
implementable level shifter. External tapes and loads inherit an explicit BC.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import uuid

import numpy as np

from serdes_flow import boundary, clock, clock_transfer, project, spice, stage_metrics, watch

ROOT = project.ROOT
HERE = Path(__file__).resolve()
PARENT = ROOT / 'results/analog/tx/loaded_clock_card/20261111T171205.027336Z_8881ed25'
PARENT_CODE = ROOT / 'analog/tx/input_register/tb/loaded_clock_card/run.py'
spec = importlib.util.spec_from_file_location('stage_cm_parent', PARENT_CODE)
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
sha, read, dump = parent.sha, parent.read, parent.dump
POINTS = [dict(id=n, e4_cm_v=e, out_cm_v=o) for n, e, o in
          (('baseline', 0., 0.), ('e4_m25', -.025, 0.), ('out_m25', 0., -.025))]


def inject_chain(text, point):
    """Use equal voltage shifts, without removing upstream gate loading."""
    for label, source, target, value in (('e4', 'e3', 'e4i', point['e4_cm_v']),
                                         ('out', 'e4', 'outi', point['out_cm_v'])):
        old = f'X{label} {source}p {source}n '
        sources = '\n'.join(f'Vcm_{label}{leg} {target}{leg} {source}{leg} {value:.17g}' for leg in ('p', 'n'))
        new = sources + f'\nX{label} {target}p {target}n '
        if text.count(old) != 3:
            raise ValueError('expected one injection in each of the three branches')
        text = text.replace(old, new)
    return text


def prepare():
    pp, bc = parent.check(PARENT, registered=True)
    camp = ROOT / 'results/analog/tx/loaded_stage_cm' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:8])
    camp.mkdir(parents=True, exist_ok=False)
    refs = {}
    for tag in pp['conditions']:
        raw = parent.completed(PARENT, tag, 'baseline', pp)
        if raw is None or not parent.measure(PARENT, tag, 'baseline', raw, pp)['baseline_fidelity']['passed']:
            raise ValueError('parent baseline incomplete or invalid')
        refs[tag] = dict(raw=str(raw.relative_to(ROOT)), raw_sha256=sha(raw),
                         evidence={str(p.relative_to(ROOT)): sha(p) for p in
                                   (raw.parent / n for n in ('tb.cir', 'execution.json', 'simulator.log'))})
        for point in POINTS:
            dest = camp / 'variants' / tag / (point['id'] + '.spice')
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(inject_chain((PARENT / 'snap' / tag / 'clock_variants.spice').read_text(), point))
    entry = dict(id='tx_direct_stage_cm_' + camp.name.replace('.', '_'),
                 kind='inherited_external_voltage_replay_with_internal_series_CM_experiment',
                 parent_boundary_id=bc['id'], parent_boundary_sha256=parent.boundary_hash(bc),
                 nodes=bc['nodes'], points=bc['points'], load=bc['load'],
                 variant_input_signatures=bc['variant_input_signatures'],
                 interventions=POINTS,
                 processing='External waveforms exactly inherit the registered parent baseline; equal DC series sources at Xe4 or Xout gates. Prior cells remain connected through sources.',
                 valid_while='Only the explicit source/load snapshots and independent fixed bias; no physical level-shifter, source adoption or full-TX qualification.',
                 validation=dict(baseline_waveform_error_v=.005, baseline_absolute_clock_edge_error_s=2e-12,
                                 series_voltage_error_v=1e-9),
                 scope='FS hot and SS cold, RC tt; generic/short/long clock loads, current driver downstream. Training/diagnosis only; no independent new model holdout.')
    dump(camp / 'boundary_proposal.json', entry)
    sources = {str(p): sha(p) for p in (HERE, Path(clock_transfer.__file__))}
    for path in sources:
        dest = camp / 'execution' / path.lstrip('/')
        dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, dest)
    plan = dict(parent=str(PARENT.relative_to(ROOT)), parent_plan_sha256=sha(PARENT / 'plan.json'),
                boundary_sha256=parent.boundary_hash(entry), conditions=pp['conditions'], points=POINTS,
                stop_s=pp['stop_s'], evaluation_window_s=pp['evaluation_window_s'], parent_baselines=refs,
                sources=sources, python=sys.version, numpy=np.__version__,
                snapshots={str(p.relative_to(camp)): sha(p) for p in camp.rglob('*') if p.is_file()},
                hypothesis='The previous entry-only CM perturbation is attenuated before Xe4/Xout. Direct internal perturbations supply identifiable CM variation while retaining bidirectional gate loading.',
                model_policy='These new points are development/training data. Freeze a new model before generating any fresh model holdout; do not relabel old development points as independent validation.',
                ungraded=['complete TX payload/eye/pad', 'remaining PVT and passive corners', 'physical shifter', 'bias feedback', 'noise/mismatch/PEX', 'size adoption'])
    dump(camp / 'plan.json', plan)
    check(camp, registered=False)
    return camp


def check(camp, registered=True):
    parent.check(PARENT, registered=True)
    p = read(camp / 'plan.json'); bc = read(camp / 'boundary_proposal.json')
    if (p['parent'] != str(PARENT.relative_to(ROOT)) or p['parent_plan_sha256'] != sha(PARENT / 'plan.json')
            or p['points'] != POINTS or p['boundary_sha256'] != parent.boundary_hash(bc)
            or (p['python'], p['numpy']) != (sys.version, np.__version__)):
        raise ValueError('parent, plan, boundary or runtime changed')
    for path, expected in p['sources'].items():
        if sha(Path(path)) != expected or sha(camp / 'execution' / path.lstrip('/')) != expected:
            raise ValueError('source changed: ' + path)
    for path, expected in p['snapshots'].items():
        if sha(camp / path) != expected: raise ValueError('snapshot changed: ' + path)
    for ref in p['parent_baselines'].values():
        if sha(ROOT / ref['raw']) != ref['raw_sha256']: raise ValueError('parent raw changed')
        for path, expected in ref['evidence'].items():
            if sha(ROOT / path) != expected: raise ValueError('parent execution changed')
    if registered and boundary.get(bc['id']) != bc: raise ValueError('boundary registration differs')
    return p


def register(camp):
    check(camp, registered=False)
    before = read(boundary.REGISTRY); entry = read(camp / 'boundary_proposal.json')
    boundary.register(entry)
    if {b['id']: b for b in read(boundary.REGISTRY)} != {b['id']: b for b in before + [entry]}:
        raise ValueError('concurrent registry change')
    boundary.REGISTRY.write_text(json.dumps(before + [entry], indent=1, ensure_ascii=False) + '\n')
    check(camp)


def render(camp, tag, name):
    text = parent.render(PARENT, tag, 'baseline')
    old = PARENT / 'snap' / tag / 'clock_variants.spice'
    new = camp / 'variants' / tag / (name + '.spice')
    if text.count(str(old)) != 1: raise ValueError('unexpected parent variant include')
    text = text.replace(str(old), str(new))
    added = [f'xclock{i}.{node}' for i in (1, 2, 3) for node in ('e4ip', 'e4in', 'outip', 'outin')]
    for keyword in ('.save ', 'write baseline.raw '):
        text, count = re.subn(r'(?m)^' + re.escape(keyword), keyword + ' '.join('v(' + n + ')' for n in added) + ' ', text)
        if count != 1: raise ValueError('missing parent save/write command')
    return text.replace('write baseline.raw ', 'write ' + name + '.raw ')


def completed(camp, tag, name, plan):
    raw = spice.case_output(camp, tag + '_' + name, name + '.raw', plan['stop_s'])
    if raw is None: return None
    ex = read(raw.parent / 'execution.json')
    if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures']: return None
    digest = hashlib.sha256(render(camp, tag, name).encode()).hexdigest()
    if ex['deck_sha256'] != digest or sha(raw.parent / 'tb.cir') != digest:
        raise ValueError('executed deck identity differs')
    if ex['condition'] != tag or ex['point'] != name: raise ValueError('executed case identity differs')
    return raw


def measure(camp, tag, name, raw, plan):
    w = spice.Waves(raw); start, stop = plan['evaluation_window_s']
    point = next(p for p in POINTS if p['id'] == name)
    result = dict(branches=[], baseline_fidelity=None)
    if name == 'baseline':
        base = spice.Waves(ROOT / plan['parent_baselines'][tag]['raw'])
        voltages, _ = parent.probe_spec()
        tw, _ = stage_metrics.window(w.t, w['ip'], start, stop)
        errors = {n: float(np.max(abs(np.interp(tw, w.t, w[n]) - np.interp(tw, base.t, base[n])))) for n in voltages}
        edges = {}
        for i in (1, 2, 3):
            for label, pos, neg in (('e3', 'e3p', 'e3n'), ('e4', 'e4p', 'e4n'), ('c2g', 'sp', 'sn')):
                differences = []
                for polarity in (1, -1):
                    a = clock.edges(base.t, base[pos + str(i)] - base[neg + str(i)], polarity, start, stop)
                    b = clock.edges(w.t, w[pos + str(i)] - w[neg + str(i)], polarity, start, stop)
                    if len(a) != len(b) or not len(a) or np.any(abs(a - b) >= 125e-12):
                        raise ValueError('baseline absolute event identity changed')
                    differences.extend(b - a)
                edges[label + str(i)] = float(max(abs(np.asarray(differences))))
        result['baseline_fidelity'] = dict(voltage_errors_v=errors, edge_errors_s=edges,
            max_voltage_error_v=max(errors.values()), max_edge_error_s=max(edges.values()),
            passed=bool(max(errors.values()) <= .005 and max(edges.values()) <= 2e-12))
    for i, mode in enumerate(parent.MODES, 1):
        b = dict(mode=mode, stages=[], clock_rail_power_w=stage_metrics.telemetry(w.t, w['vdd'] * w[f'i(vsense{i})'], start, stop))
        result['branches'].append(b)
        series_error = 0.
        for label, source, target, value in (('e4', 'e3', 'e4i', point['e4_cm_v']), ('out', 'e4', 'outi', point['out_cm_v'])):
            for leg in ('p', 'n'):
                series_error = max(series_error, float(np.max(abs(w[f'xclock{i}.{target}{leg}'] - w[f'{source}{leg}{i}'] - value))))
        if series_error > 1e-9: raise ValueError('unequal or incorrect series common-mode shift')
        b['max_series_voltage_error_v'] = series_error
        for stage, ap, an, bp, bn in (('e3', 'ip', 'inn', f'e3p{i}', f'e3n{i}'),
                                      ('e4', f'xclock{i}.e4ip', f'xclock{i}.e4in', f'e4p{i}', f'e4n{i}'),
                                      ('out', f'xclock{i}.outip', f'xclock{i}.outin', f'sp{i}', f'sn{i}')):
            d, y = w[ap] - w[an], w[bp] - w[bn]
            s = dict(stage=stage, input_differential_v=stage_metrics.telemetry(w.t, d, start, stop),
                     input_common_mode_v=stage_metrics.telemetry(w.t, (w[ap] + w[an]) / 2, start, stop),
                     output_differential_v=stage_metrics.telemetry(w.t, y, start, stop),
                     output_common_mode_v=stage_metrics.telemetry(w.t, (w[bp] + w[bn]) / 2, start, stop))
            tail = w[f'xclock{i}.x{stage}.xgain.tail']
            s['tail_headroom_v'] = stage_metrics.headroom(w.t, tail, tail * 0, w[f'{stage}_xtail_vdsat_{i}'], start, stop)
            s['tail_current_a'] = stage_metrics.telemetry(w.t, w[f'{stage}_xtail_id_{i}'], start, stop)
            for device, drain in (('xmp', bn), ('xmn', bp)):
                s[device + '_headroom_v'] = stage_metrics.headroom(w.t, w[drain], tail, w[f'{stage}_{device}_vdsat_{i}'], start, stop)
            try:
                s['clock_check'] = clock_transfer.analyze(w.t, d, y, start, stop - 200e-12, 200e-12, minimum_pp_v=.15)
            except ValueError as exc:
                s['clock_check'] = dict(edges_complete=False, clock_qualified=False, error=str(exc))
            b['stages'].append(s)
        try:
            b['input_to_c2g'] = clock_transfer.analyze(w.t, w['ip'] - w['inn'], w[f'sp{i}'] - w[f'sn{i}'], start, stop - 200e-12, 200e-12, minimum_pp_v=.15)
        except ValueError as exc:
            b['input_to_c2g'] = dict(edges_complete=False, clock_qualified=False, error=str(exc))
        b['clock_floor_and_events_pass'] = all(s['clock_check']['clock_qualified'] for s in b['stages']) and b['input_to_c2g']['clock_qualified']
    return result


def resume(camp, baseline_only):
    with (camp / '.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = check(camp)
        if any(p.is_relative_to(camp) for p in watch.ngspice_cwds()): raise RuntimeError('campaign already active')
        archive = spice.next_run_dir(camp / 'analysis', 'measurement'); archive.mkdir(parents=True, exist_ok=False)
        report = dict(status='failed', plan_sha256=sha(camp / 'plan.json'), rows=[])
        try:
            for point in POINTS[:1] if baseline_only else POINTS:
                for tag in plan['conditions']:
                    name = point['id']; raw = completed(camp, tag, name, plan)
                    if raw is None:
                        if len(watch.ngspice_cwds()) >= 4: raise RuntimeError('global ngspice limit')
                        text = render(camp, tag, name)
                        sd = spice.next_run_dir(camp, 'smoke_' + tag + '_' + name)
                        smoke = re.sub(r'(?m)^tran .+$', 'tran .5p 1.001n 0 .5p', text)
                        ex = spice.run(smoke, sd, timeout_s=180, meta=dict(condition=tag, point=name, kind='smoke'))
                        if not ex.ok or spice.case_output(camp, sd.name, name + '.raw', 1.001e-9) is None:
                            raise RuntimeError('smoke failed: ' + str(sd))
                        if len(watch.ngspice_cwds()) >= 4: raise RuntimeError('global ngspice limit')
                        ex = spice.run(text, spice.next_run_dir(camp, tag + '_' + name), timeout_s=480,
                                       meta=dict(condition=tag, point=name, boundary_id=read(camp / 'boundary_proposal.json')['id']))
                        if not ex.ok: raise RuntimeError('full execution failed: ' + str(ex.run_dir))
                        raw = completed(camp, tag, name, plan)
                        if raw is None: raise RuntimeError('truncated full case')
                    result = measure(camp, tag, name, raw, plan)
                    report['rows'].append(dict(condition=tag, point=name, raw=str(raw.relative_to(ROOT)),
                        evidence={str(p.relative_to(ROOT)): sha(p) for p in (raw, raw.parent / 'tb.cir', raw.parent / 'execution.json', raw.parent / 'simulator.log')}, result=result))
                    if name == 'baseline' and not result['baseline_fidelity']['passed']:
                        raise RuntimeError('zero-shift baseline failed calibration')
            report['status'] = 'direct_CM_baselines_validated_DOE_pending' if baseline_only else 'direct_CM_measured_no_adoption'
        except Exception as exc:
            report['error'] = f'{type(exc).__name__}: {exc}'; raise
        finally:
            dump(archive / 'summary.json', report)
    return archive / 'summary.json'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare', action='store_true'); g.add_argument('--register', type=Path)
    g.add_argument('--check', type=Path); g.add_argument('--resume', type=Path)
    p.add_argument('--baseline-only', action='store_true'); args = p.parse_args()
    if args.prepare: print(prepare())
    elif args.register: register(args.register.resolve()); print('registered')
    elif args.check: check(args.check.resolve()); print('identity verified')
    else: print(resume(args.resume.resolve(), args.baseline_only))


if __name__ == '__main__': main()
