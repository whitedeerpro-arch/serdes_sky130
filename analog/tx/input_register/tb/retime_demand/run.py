"""Calibrated final-rank/driver demand card; prepare/check never simulate.

Replay the whole saved full-TX history and payload into the final rank plus
the current line driver and its direct load. Scan prescribed clock phase and
differential scale separately from transistor sizing. This omits upstream
source impedance/feedback and is not a new full-TX or startup qualification.
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
import uuid

import numpy as np

from serdes_flow import bias, boundary, clock, project, rcorner, serial, spice, watch, waves
from serdes_flow.corners import Condition

ROOT = project.ROOT
HERE = Path(__file__).resolve().parent
NATIVE = HERE.parent / 'final_retime/native_window.py'
SPEC = importlib.util.spec_from_file_location('frozen_retime_native', NATIVE)
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)
helper, collector = native.helper, native.collector
sha = helper.sha
PREFIX = .25e-9
POINTS = [dict(id=name, delay_ps=delay, differential_scale=scale) for name, delay, scale in (
    ('baseline', 0, 1.), ('early20', -20, 1.), ('late20', 20, 1.), ('late40', 40, 1.),
    ('scale090', 0, .9), ('scale110', 0, 1.1), ('late20_scale090', 20, .9), ('late20_scale110', 20, 1.1))]
REFS = {**helper.REFS, 'sap': 'xtx.xtree.xr4_0.sap', 'san': 'xtx.xtree.xr4_0.san',
        'sbp': 'xtx.xtree.xr4_0.sbp', 'sbn': 'xtx.xtree.xr4_0.sbn',
        'lqp': 'lqp', 'lqn': 'lqn'}
LOCAL = {**{n: n for n in ('qp', 'qn', 'lqp', 'lqn')},
         **{n: 'xslice.xfinal.' + n for n in ('ahp', 'ahn', 'bhp', 'bhn', 'sap', 'san', 'sbp', 'sbn')}}
VECTORS = ' '.join('v(' + n + ')' for n in [*helper.NODES, *LOCAL.values()])


def read(path):
    return json.loads(path.read_text())


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def pdk_manifest():
    root = project.model_library().parents[2]
    return {str(p): sha(p) for folder in ('libs.tech/ngspice', 'libs.ref/sky130_fd_pr/spice')
            for p in sorted((root / folder).rglob('*')) if p.is_file()}


def template():
    text = helper.TEMPLATE.read_text()
    old = 'serdes_tx_cml_line_driver_lowvt_enable wgatep=32'
    if text.count(old) != 1:
        raise ValueError('unexpected source driver template')
    text = text.replace(old, old + ' rpre=120 wout=192 wtpre=60')
    text, count = re.subn(r'(?m)^Vtxen .*$', 'Vtxen tx_en 0 PWL(0 0 .20n 0 .25n @SUPPLY@)', text)
    if count != 1:
        raise ValueError('enable template missing')
    return text


def source(camp):
    case = collector.collect(camp)
    if any(case[k] is not True for k in ('input_boundary_ok', 'halfword_hold_ok', 'behavioral_tags_align')) or not case['counter']['counting']:
        raise ValueError('source word interface failed')
    plan, summary = read(camp / 'plan.json'), read(camp / 'summary.json')
    if plan['driver_params'] != 'rpre=120 wout=192 wtpre=60':
        raise ValueError('requires the current pre120/WT60/out192 driver')
    if plan['pdk_installation_id'] != project.pdk_installation_id():
        raise ValueError('source PDK differs')
    cells = helper.validate_source_cell(camp, plan, snapshot_root='execution')
    for rel in helper.DEPENDENCIES:
        if sha(ROOT / rel) != plan['snapshot_files']['execution/' + rel]:
            raise ValueError(f'source physical dependency differs: {rel}')
    expected_load = helper.lines(template(), helper.LOAD_NAMES)
    if helper.lines((camp / 'execution/physical_tb.cir').read_text(), helper.LOAD_NAMES) != expected_load:
        raise ValueError('source direct driver/package/channel load differs')
    raw = ROOT / case['waveform']
    w = spice.Waves(raw)
    origin = float(w.t[0] - PREFIX)
    bits = [(row['word'] >> i) & 1 for row in summary['captures'] if row['payload_valid'] for i in range(16)]
    t = np.r_[0., w.t - origin]
    arrays = {'t': t}
    for name, node in {**helper.NODES, **{'ref_' + k: v for k, v in REFS.items()}}.items():
        arrays[name] = np.r_[w[node][0], w[node]]
    point = dict(condition=case['condition'], campaign=str(camp.relative_to(ROOT)), raw=case['waveform'],
                 raw_sha256=sha(raw), source_hashes=case['hashes'], source_cells=cells,
                 origin_s=origin, stop_s=float(t[-1]), sequence_start_s=case['sequence_start_s'] - origin,
                 payload_bits=plan['payload_bits'], bits=bits, clock_stage_profile=case['clock_stage_profile'],
                 source_metrics={label: summary['outputs'][label]['check'] for label in ('serializer', 'pad')})
    return point, arrays


def sources():
    return list(dict.fromkeys([Path(__file__).resolve(), NATIVE, native.HELPER, native.COLLECTOR,
                              helper.CELL, helper.TEMPLATE] + [ROOT / p for p in helper.DEPENDENCIES]
                             + [ROOT / 'src/serdes_flow' / (p + '.py') for p in
                                ('spice', 'clock', 'waves', 'serial', 'bias', 'rcorner', 'boundary', 'project', 'corners', 'watch', 'clock_profiles')]
                             + [ROOT / 'config/pdk.toml', ROOT / 'config/tools.toml']))


def prepare(campaigns):
    if len(campaigns) != len(set(campaigns)) or not campaigns:
        raise ValueError('distinct explicit source campaigns required')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:8]
    camp = ROOT / 'results/analog/tx/retime_demand' / stamp
    camp.mkdir(parents=True, exist_ok=False)
    points = {}
    for original in campaigns:
        point, arrays = source(original.resolve())
        tag = point['condition']
        if tag in points:
            raise ValueError('duplicate condition')
        points[tag] = point
        path = camp / 'inputs' / f'{tag}.npz'
        path.parent.mkdir(exist_ok=True)
        np.savez_compressed(path, **arrays)
        text = spice.render(template(), **spice.corner_values(Condition.parse(tag)), CASES='@CASES@', VECTORS=VECTORS)
        text = bias.section(rcorner.to_pdk(text, camp / 'snap' / tag), Condition.parse(tag).process, 'tt')
        base = camp / 'prepared' / f'{tag}.cir.in'
        base.parent.mkdir(exist_ok=True)
        base.write_text(text)
    entry = dict(id='tx_retime_demand_' + stamp.replace('.', '_'), kind='loaded_internal_port_voltage_replay',
                 description='Whole saved TX final-rank input history into the matching current driver and direct load.',
                 nodes=helper.NODES, load={'final_rank_cells': {str(p.relative_to(ROOT)): sha(p) for p in (helper.CELL, ROOT / 'analog/common/cml_mux/spice/cml_lowov_cells.spice')},
                                          'direct_downstream_lines': helper.lines(template(), helper.LOAD_NAMES)},
                 points=points, processing='Saved full history prefixed by 250ps with held first input values; driver enabled at 250ps from balanced DC idle. Phase shifts both c2g ports; amplitude scales differential voltage at unchanged common mode, also scaling differential slew.',
                 validation=dict(state='baseline_required', input_error_v=200e-6, waveform_error_v=.005, absolute_edge_error_s=2e-12),
                 valid_while=['same final cells and complete direct load', 'full-history baseline including pad must match before perturbations',
                              'ideal prescribed ports omit upstream impedance and feedback',
                              'training-only phase and fixed UI; no payload fitting',
                              'demand card is not a physical clock-sizing implementation or startup/PVT/noise qualification'])
    (camp / 'boundary_proposal.json').write_text(json.dumps(entry, indent=2) + '\n')
    identities = {}
    for path in sources():
        rel = str(path.relative_to(ROOT))
        identities[rel] = sha(path)
        dest = camp / 'execution' / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    plan = dict(boundary_sha256=canonical(entry), conditions=list(points), points=POINTS,
                sources=identities, pdk_manifest=pdk_manifest(), ngspice_sha256=sha(Path(project.ngspice())),
                snapshots={str(p.relative_to(camp)): sha(p) for folder in ('inputs', 'prepared', 'snap', 'execution')
                           for p in (camp / folder).rglob('*') if p.is_file()})
    (camp / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    check(camp)
    return camp


def check(camp, registered=False):
    plan, entry = read(camp / 'plan.json'), read(camp / 'boundary_proposal.json')
    if (canonical(entry) != plan['boundary_sha256'] or plan['points'] != POINTS
            or set(plan['conditions']) != set(entry['points'])):
        raise ValueError('boundary or point identity changed')
    if registered and boundary.get(entry['id']) != entry:
        raise ValueError('registered boundary differs')
    if pdk_manifest() != plan['pdk_manifest'] or sha(Path(project.ngspice())) != plan['ngspice_sha256']:
        raise ValueError('PDK or simulator changed')
    for rel, expected in plan['sources'].items():
        if sha(ROOT / rel) != expected or sha(camp / 'execution' / rel) != expected:
            raise ValueError(f'execution source changed: {rel}')
    for rel, expected in plan['snapshots'].items():
        if sha(camp / rel) != expected:
            raise ValueError(f'checkpoint changed: {rel}')
    for tag, pt in entry['points'].items():
        src = ROOT / pt['campaign']
        expected = pt['source_hashes']
        for path, key in ((src / 'plan.json', 'plan_sha256'), (src / 'summary.json', 'summary_sha256'),
                          (ROOT / pt['raw'], 'waveform_sha256')):
            if sha(path) != expected[key]:
                raise ValueError('full source changed')
        original = read(src / 'plan.json')
        for rel, expected_sha in original['snapshot_files'].items():
            if sha(src / rel) != expected_sha:
                raise ValueError('full source checkpoint changed')
        if tag != original['condition'] or helper.validate_source_cell(src, original, snapshot_root='execution') != pt['source_cells']:
            raise ValueError('full source condition/cells changed')
        helper.validate_execution(ROOT / pt['raw'])
    return plan, entry


def signals(data, point):
    result = {k: np.array(data[k]) for k in helper.NODES}
    cm = (result['sp'] + result['sn']) / 2
    half = (result['sp'] - result['sn']) / 2 * point['differential_scale']
    result['sp'], result['sn'] = cm + half, cm - half
    return result


def render(camp, tag, ids):
    if len(ids) != 1 or set(ids) - {p['id'] for p in POINTS}:
        raise ValueError('one declared experiment point per deck required')
    commands = []
    point_map = {p['id']: p for p in POINTS}
    with np.load(camp / 'inputs' / f'{tag}.npz') as data:
        for i, name in enumerate(ids):
            p = point_map[name]
            for n, y in signals(data, p).items():
                if i and n not in ('sp', 'sn'):
                    continue
                commands += native.commands(helper.SOURCE_MAP[n], data['t'], y, p['delay_ps'] * 1e-12 if n in ('sp', 'sn') else 0.)
            commands += [spice.skip_output_before(f'tran 1p {data["t"][-1]:.12e} 0 1p', '.1n'),
                         f'write {name}.raw {VECTORS}', 'destroy all']
    base = (camp / 'prepared' / f'{tag}.cir.in').read_text()
    if base.count('@CASES@') != 1:
        raise ValueError('prepared control block changed')
    return base.replace('@CASES@', '\n'.join(commands))


def completed(camp, tag, name, entry):
    deck = tag + '_' + name
    dirs = [d for d in camp.glob(deck + '.r*') if d.name.rsplit('.r', 1)[1].isdigit()] + [camp / deck]
    for run in sorted(dirs, key=lambda d: spice._rerun_index(d, deck), reverse=True):
        try:
            ex = read(run / 'execution.json')
            w = spice.Waves(run / (name + '.raw'))
        except (FileNotFoundError, ValueError):
            continue
        if w.t[-1] < entry['points'][tag]['stop_s'] * (1 - 1e-6):
            continue
        if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures']:
            continue
        if ex.get('condition') != tag or ex.get('point_ids') != [name] or ex.get('boundary_id') != entry['id']:
            raise ValueError('execution case identity differs')
        expected = hashlib.sha256(render(camp, tag, [name]).encode()).hexdigest()
        if expected != ex['deck_sha256'] or sha(run / 'tb.cir') != expected:
            raise ValueError('executed demand deck changed')
        return w.path
    return None


def measure(camp, tag, name, raw, entry):
    pt = entry['points'][tag]
    p = next(p for p in POINTS if p['id'] == name)
    helper.validate_execution(raw)
    w = spice.Waves(raw)
    seq = serial.Sequence(np.array(pt['bits'], dtype=int), pt['sequence_start_s'], 250e-12)
    outputs = {}
    with np.load(camp / 'inputs' / f'{tag}.npz') as data:
        inp = {n: float(np.max(abs(w[n] - np.interp(w.t - (p['delay_ps'] * 1e-12 if n in ('sp', 'sn') else 0.), data['t'], y))))
               for n, y in signals(data, p).items()}
        if max(inp.values()) > 200e-6:
            raise ValueError('replayed input voltage error')
        lo, hi = seq.start_s + 64 * seq.ui_s, seq.start_s + (64 + pt['payload_bits']) * seq.ui_s
        mask = (w.t >= lo) & (w.t <= hi)
        errors = {n: float(np.max(abs(w[node][mask] - np.interp(w.t[mask], data['t'], data['ref_' + n])))) for n, node in LOCAL.items()}
        for label, pos, neg in (('serializer', 'qp', 'qn'), ('pad', 'lqp', 'lqn')):
            m, d = serial.check(w.t, w[pos] - w[neg], seq, pt['payload_bits'])
            ref_m, ref_d = serial.check(data['t'], data['ref_' + pos] - data['ref_' + neg], seq, pt['payload_bits'])
            if not collector.equal(ref_m, pt['source_metrics'][label]):
                raise ValueError('replayed reference does not reproduce full metrics')
            actual = {b: (m['training_delay_ui'] + r) * seq.ui_s for b, r in zip(d['payload_transition_bits'], d['edge_residual_ui'])}
            ref = {b: (ref_m['training_delay_ui'] + r) * seq.ui_s for b, r in zip(ref_d['payload_transition_bits'], ref_d['edge_residual_ui'])}
            edge_error = max((abs(actual[b] - t) for b, t in ref.items()), default=0.) if actual.keys() == ref.keys() else None
            outputs[label] = dict(metrics=m, details=d, source_metrics=ref_m, meets_eye_gate=serial.meets_draft(m),
                                  baseline_absolute_edge_error_s=edge_error if name == 'baseline' else None)
    baseline_ok = bool(name == 'baseline' and max(errors.values()) <= .005
                       and all(o['baseline_absolute_edge_error_s'] is not None and o['baseline_absolute_edge_error_s'] <= 2e-12
                               and o['metrics']['functional'] == o['source_metrics']['functional'] for o in outputs.values()))
    return dict(input_max_error_v=inp, baseline_max_error_v=errors if name == 'baseline' else None,
                baseline_matches=baseline_ok if name == 'baseline' else None, outputs=outputs,
                actual_c2g_pp_v=float(np.ptp((w['sp'] - w['sn'])[mask])),
                c2g_common_mode_mean_v=waves.time_average(((w['sp'] + w['sn']) / 2)[mask], w.t[mask]),
                c2g_cycles=clock.cycle_amplitudes(w.t, w['sp'] - w['sn'], lo, hi),
                scope='whole saved waveform, prescribed voltage ports, matching final rank/driver/load, phase from training only')


def resume(camp, stage):
    with (camp / '.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan, entry = check(camp, registered=True)
        if any(p == camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()):
            raise RuntimeError('campaign has live ngspice')
        if stage == 'scan':
            for tag in plan['conditions']:
                raw = completed(camp, tag, 'baseline', entry)
                if raw is None or not measure(camp, tag, 'baseline', raw, entry)['baseline_matches']:
                    raise ValueError('unchanged full-history baseline missing or failed: ' + tag)
        ids = ['baseline'] if stage == 'baseline' else [p['id'] for p in POINTS if p['id'] != 'baseline']
        jobs = []
        for tag in plan['conditions']:
            for name in ids:
                if completed(camp, tag, name, entry) is None:
                    jobs.append((render(camp, tag, [name]), spice.next_run_dir(camp, tag + '_' + name),
                                 dict(timeout_s=480, meta=dict(condition=tag, point_ids=[name], boundary_id=entry['id']))))
        if jobs:
            if len(watch.ngspice_cwds()) + min(2, len(jobs)) > 4:
                raise RuntimeError('global simulation limit')
            first = jobs[0][2]['meta']
            smoke = spice.smoke_deck(render(camp, first['condition'], first['point_ids'][:1]))
            sr = spice.next_run_dir(camp, 'smoke')
            ex = spice.run(smoke, sr, timeout_s=180)
            if not ex.ok or spice.case_output(camp, sr.name, first['point_ids'][0] + '.raw', 1e-9) is None:
                raise RuntimeError('single-case smoke failed')
            if len(watch.ngspice_cwds()) + min(2, len(jobs)) > 4:
                raise RuntimeError('global simulation limit after smoke')
            executions = spice.run_many(jobs, workers=2, smoke=False)
            if any(not ex.ok for ex in executions):
                raise RuntimeError('incomplete demand deck; audit and resume missing points')
        archive = camp / 'analysis' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        archive.mkdir(parents=True, exist_ok=False)
        rows = []
        for tag in plan['conditions']:
            for p in POINTS:
                raw = completed(camp, tag, p['id'], entry)
                if raw is not None:
                    rows.append(dict(condition=tag, point=p, raw=str(raw.relative_to(ROOT)), raw_sha256=sha(raw),
                                     result=measure(camp, tag, p['id'], raw, entry)))
        summary = dict(scope='Calibrated prescribed-port demand card, not sized circuit or full-system qualification', stage=stage, rows=rows)
        (archive / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
        print(archive, flush=True)
        baselines = [r for r in rows if r['point']['id'] == 'baseline']
        if stage == 'baseline' and (len(baselines) != len(plan['conditions']) or any(not r['result']['baseline_matches'] for r in baselines)):
            raise RuntimeError('baseline failed; diagnostic summary preserved; demand scan is forbidden')
        return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare', action='store_true')
    g.add_argument('--check', type=Path)
    g.add_argument('--register', type=Path)
    g.add_argument('--resume', type=Path)
    p.add_argument('--source', action='append', type=Path, default=[])
    p.add_argument('--stage', choices=('baseline', 'scan'), default='baseline')
    a = p.parse_args()
    if a.prepare:
        print(prepare([s.resolve() for s in a.source]))
    elif a.register:
        _, entry = check(a.register.resolve())
        prior = boundary.registry().get(entry['id'])
        if prior is None:
            boundary.register(entry)
        elif prior != entry:
            raise ValueError('boundary ID already has a different identity')
        print(entry['id'])
    elif a.check:
        plan, _ = check(a.check.resolve())
        print(json.dumps({'conditions': plan['conditions'], 'points': plan['points']}, indent=2))
    else:
        result = resume(a.resume.resolve(), a.stage)
        for row in result['rows']:
            print(row['condition'], row['point']['id'], row['result']['baseline_matches'],
                  {label: (round(o['metrics']['minimum_signed_margin_v'] * 1000, 3), o['metrics']['transition_spread_ui'])
                   for label, o in row['result']['outputs'].items()}, flush=True)


if __name__ == '__main__':
    main()
