"""Prepare/check an I-17 Xe2 local card from the archived extra5 replay.

Prepare/check launch no simulation. The proposed boundary is not registered.
Execution is explicit via --resume and requires independent baseline calibration.
"""
import argparse
import fcntl
import hashlib
import json
import re
import shutil
import sys
import time
import uuid

import numpy as np
from pathlib import Path

from serdes_flow import boundary, clock, project, serial, spice, watch, waves

ROOT = project.ROOT
SOURCE = ROOT / 'results/analog/tx/native_reduced_clock/20261107T164517.822006Z_16514531'
STOP = 6.5e-9
TAGS = ('tt_v1800_t27', 'fs_v1650_t85')
BC = 'tx_reduced_final_word18_clock_stages_v1'
RUNTIME = [Path(__file__).resolve()] + [ROOT / 'src/serdes_flow' / (x + '.py') for x in ('spice', 'project', 'boundary', 'clock', 'serial', 'waves', 'watch', 'mc', 'corners')] + [ROOT / 'config/tools.toml', ROOT / 'config/pdk.toml', Path(project.ngspice())]


def pdk_identity():
    root = project.model_library().parents[2]
    return {str(p): digest(p) for directory in ('libs.tech/ngspice', 'libs.ref/sky130_fd_pr/spice')
            for p in sorted((root / directory).rglob('*')) if p.is_file()}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def source_check():
    plan = json.loads((SOURCE / 'plan.json').read_text())
    entry = json.loads((SOURCE / 'boundary.json').read_text())
    if entry != boundary.get(BC) or canonical(entry) != plan['boundary_sha256']:
        raise ValueError('archived boundary identity differs from registry/plan')
    if canonical(boundary.get(entry['parent_id'])) != entry['parent_sha256']:
        raise ValueError('parent boundary changed')
    if plan['conditions'] != list(TAGS) or plan['counts'] != [3, 4, 5] or plan['stop_s'] != STOP:
        raise ValueError('unexpected archived plan')
    for rel, expected in plan['snapshots'].items():
        if digest(SOURCE / rel) != expected:
            raise ValueError(f'archived snapshot changed: {rel}')
    for rel, expected in plan['sources'].items():
        p = SOURCE / 'execution' / rel
        if not p.is_file() or digest(p) != expected:
            raise ValueError(f'archived execution source mismatch: {rel}')
    if digest(project.model_library()) != plan['pdk_library_sha256']:
        raise ValueError('PDK model library changed')
    raw_hashes = {}
    for tag in TAGS:
        run = SOURCE / tag
        ex = json.loads((run / 'execution.json').read_text())
        prepared = SOURCE / 'prepared' / f'{tag}.cir'
        if (ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures'] or
                ex.get('condition') != tag or ex['deck_sha256'] != digest(prepared) or
                digest(run / 'tb.cir') != digest(prepared)):
            raise ValueError(f'bad execution/deck identity: {tag}')
        raw = spice.case_output(SOURCE, tag, f'{tag}.raw', STOP)
        if raw is None:
            raise ValueError(f'missing or truncated waveform: {tag}')
        w = spice.Waves(raw)
        for name in ('sp3', 'sn3', 'qp3', 'qn3', 'xslice3.xfinal.ahp',
                     'xslice3.xfinal.ahn', 'xslice3.xfinal.bhp', 'xslice3.xfinal.bhn'):
            if name not in w:
                raise ValueError(f'missing {name} in {tag}')
        raw_hashes[tag] = {'raw': digest(raw), 'execution': digest(run / 'execution.json'),
                           'deck': digest(prepared), 't_end_s': float(w.t[-1])}
    return plan, entry, raw_hashes


def prepare():
    plan, entry, raw_hashes = source_check()
    camp = ROOT / 'results/analog/tx/buffer_local_card' / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '_' + uuid.uuid4().hex[:8])
    camp.mkdir(parents=True, exist_ok=False)
    (camp / 'inputs').mkdir(); (camp / 'prepared').mkdir(); (camp / 'snap').mkdir()
    for tag in TAGS:
        shutil.copyfile(SOURCE / 'inputs' / f'{tag}.npz', camp / 'inputs' / f'{tag}.npz')
        text = (SOURCE / 'prepared' / f'{tag}.cir').read_text()
        # Copy every frozen include; channel was captured under execution, not snap.
        def copy_include(match):
            original = Path(match.group(1))
            if original.is_relative_to(SOURCE / 'snap' / tag):
                rel = original.relative_to(SOURCE / 'snap' / tag)
                src = original
            elif original == ROOT / 'verification/models/channel/diff_rlc16.spice':
                rel = Path('channel/diff_rlc16.spice')
                src = SOURCE / 'execution/verification/models/channel/diff_rlc16.spice'
            else:
                raise ValueError(f'unexpected include: {original}')
            dest = camp / 'snap' / tag / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            return f'.include "{dest}"'
        text = re.sub(r'^\.include "([^"]+)"', copy_include, text, flags=re.M)
        match = re.search(r'(?ms)^\.subckt native_chain_5 .*?^\.ends native_chain_5\n', text)
        if not match:
            raise ValueError('missing frozen extra5 chain')
        base = match.group()
        needle = 'Xe2 e1p e1n e2p e2n vbias vdd vss serdes_cml_buffer wn=24 wt=16 rload=400'
        if base.count(needle) != 1:
            raise ValueError('unexpected Xe2')
        chains = []
        for index, (wt, r) in enumerate(((16, 400), (12.8, 400), (16, 320)), 1):
            chain = base.replace('native_chain_5', f'local_chain_{index}').replace(needle, needle.replace('wt=16 rload=400', f'wt={wt} rload={r}'))
            chains.append(chain)
        text = re.sub(r'(?ms)^\.subckt native_chain_[345] .*?^\.ends native_chain_[345]\n', '', text)
        text = text.replace('.include "', ''.join(chains) + '.include "', 1)
        for i, n in enumerate((3, 4, 5), 1):
            old = f'Xclock{i} rp rn sp{i} sn{i} vbias vdd 0 native_chain_{n}'
            new = f'Xclock{i} rp rn sp{i} sn{i} vbias vdd 0 local_chain_{i}'
            if text.count(old) != 1: raise ValueError('branch identity mismatch')
            text = text.replace(old, new)
        probes = ' '.join(f'v(xclock{i}.{node})' for i in (1, 2, 3)
                          for node in ('e1p', 'e1n', 'e2p', 'e2n', 'e3p', 'e3n', 'xe2.xgain.tail'))
        text, nsave = re.subn(r'(?m)^(\.save .+)$', lambda m: m.group(1) + ' ' + probes, text)
        text, nwrite = re.subn(r'(?m)^(write ' + tag + r'\.raw .+)$', lambda m: m.group(1) + ' ' + probes, text)
        if nsave != 1 or nwrite != 1: raise ValueError('probe insertion failed')
        (camp / 'prepared' / f'{tag}.cir').write_text(text)
    proposal = dict(id='tx_i17_extra5_xe2_local_proposal', kind=entry['kind'], parent_id=BC,
                    parent_sha256=canonical(entry), points=entry['points'], nodes=entry['nodes'],
                    load=entry['load'], output_load=entry['output_load'],
                    independent_mathematical_branches=['baseline', 'tail_only', 'R_only'],
                    scope='ideal recorded PWL bias and supplies; no upstream impedance or new real-bias validation')
    (camp / 'boundary_proposal.json').write_text(json.dumps(proposal, indent=2) + '\n')
    runtime = {}
    for path in RUNTIME:
        key = str(path)
        runtime[key] = digest(path)
        destination = camp / 'runtime' / key.lstrip('/')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    snapshots = {str(p.relative_to(camp)): digest(p) for p in camp.rglob('*') if p.is_file()}
    result = {'source': str(SOURCE.relative_to(ROOT)), 'source_plan_sha256': digest(SOURCE / 'plan.json'),
              'source_boundary_sha256': digest(SOURCE / 'boundary.json'), 'source_raw': raw_hashes,
              'pdk_library_sha256': plan['pdk_library_sha256'], 'script_sha256': digest(Path(__file__)),
              'pdk_identity': pdk_identity(),
              'snapshots': snapshots, 'runtime': runtime, 'python_version': sys.version, 'numpy_version': np.__version__, 'stop_s': STOP,
              'status': 'prepared_not_simulated',
              'ungraded': ['physical resistance', 'tail Vdsat and Id', 'branch current and power', 'upstream impedance', 'new real bias'],
              'pending': ['baseline versus old extra5 branch3', 'boundary registration after review']}
    (camp / 'plan.json').write_text(json.dumps(result, indent=2) + '\n')
    return camp


def check(camp, registered=False):
    _, _, raw_hashes = source_check()
    plan = json.loads((camp / 'plan.json').read_text())
    if raw_hashes != plan['source_raw']:
        raise ValueError('source waveform/execution identity changed')
    if digest(Path(__file__)) != plan['script_sha256']:
        raise ValueError('preparation script changed')
    if digest(SOURCE / 'plan.json') != plan['source_plan_sha256']:
        raise ValueError('source plan changed')
    for rel, expected in plan['snapshots'].items():
        if digest(camp / rel) != expected: raise ValueError(f'local snapshot changed: {rel}')
    if plan['python_version'] != sys.version or plan['numpy_version'] != np.__version__:
        raise ValueError('Python/NumPy runtime changed')
    for path, expected in plan['runtime'].items():
        if digest(Path(path)) != expected: raise ValueError(f'runtime changed: {path}')
    if pdk_identity() != plan['pdk_identity']:
        raise ValueError('PDK model closure changed')
    if registered:
        proposal = json.loads((camp / 'boundary_proposal.json').read_text())
        if boundary.get(proposal['id']) != proposal:
            raise ValueError('local boundary not registered or changed')
    for tag in TAGS:
        text = (camp / 'prepared' / f'{tag}.cir').read_text()
        for p in re.findall(r'^\.include "([^"]+)"', text, re.M):
            if not Path(p).is_relative_to(camp / 'snap' / tag):
                raise ValueError('mutable include')
    return plan


def completed(camp, tag):
    raw = spice.case_output(camp, tag, tag + '.raw', STOP)
    if raw is None:
        return None
    ex_path = raw.parent / 'execution.json'
    if not ex_path.is_file(): return None
    ex = json.loads(ex_path.read_text())
    expected = digest(camp / 'prepared' / f'{tag}.cir')
    if ex.get('exit_code') != 0 or ex.get('timed_out') or ex.get('log_failures'):
        return None
    if ex.get('condition') != tag or ex.get('deck_sha256') != expected or digest(raw.parent / 'tb.cir') != expected:
        raise ValueError('completed deck identity mismatch')
    if ex.get('ngspice') != project.ngspice() or ex.get('pdk_installation_id') != project.pdk_installation_id():
        raise ValueError('completed runtime identity mismatch')
    return raw


def measure(camp, tag, raw, point):
    w = spice.Waves(raw)
    old = spice.Waves(SOURCE / tag / (tag + '.raw'))
    with np.load(camp / 'inputs' / f'{tag}.npz') as inputs:
        input_errors = {k: float(np.max(np.abs(w[k] - np.interp(w.t, inputs['t'], inputs[k]))))
                        for k in ('ap', 'an', 'bp', 'bn', 'vbias', 'vbias_logic', 'vdd', 'rp', 'rn')}
        source_fall = clock.edges(inputs['t'], inputs['ref_sp'] - inputs['ref_sn'], -1, 4e-9, STOP - .1e-9)
    mask = (w.t >= 3.5e-9) & (w.t <= 6.45e-9)
    pairs = [(n + '1', n + '3') for n in ('sp', 'sn', 'qp', 'qn')]
    pairs += [(f'xslice1.xfinal.{n}', f'xslice3.xfinal.{n}') for n in ('ahp', 'ahn', 'bhp', 'bhn', 'sap', 'san')]
    errors = {a: float(np.max(np.abs(w[a][mask] - np.interp(w.t[mask], old.t, old[b])))) for a, b in pairs}
    matched = max(input_errors.values()) <= 200e-6 and max(errors.values()) <= .005
    result = {'input_max_error_v': input_errors, 'baseline_max_error_v': errors,
              'baseline_matches': bool(matched), 'branch_status': 'ungraded_baseline_failed' if not matched else 'measured',
              'ungraded': ['physical resistance', 'tail Vdsat and Id', 'branch current and power']}
    if not matched: return result
    seq = serial.Sequence(np.asarray(point['bits'], dtype=int), point['sequence_start_s'] - point['origin_s'], 250e-12)
    ref_fall = clock.edges(old.t, old['sp3'] - old['sn3'], -1, 4e-9, STOP - .1e-9)
    # The recorded training phase belongs to the original extra3 source.
    # Old branch3 is extra5, so retain its already accumulated clock delay.
    def offsets(target, reference):
        shifts = []
        for edge in reference:
            hits = target[np.abs(target - edge) < 125e-12]
            if len(hits) != 1: raise ValueError('ambiguous clock edge association')
            shifts.append(float(hits[0] - edge))
        if not shifts or len(shifts) != len(target): raise ValueError('missing clock edges')
        return shifts
    previous_shift = float(np.median(offsets(ref_fall, source_fall)))
    old_metrics, old_details = serial.fixed_phase_window(old.t, old['qp3'] - old['qn3'], seq,
        delay_ui=point['training_delay_ui'] + previous_shift / seq.ui_s, first_bit=296, end_bit=304)
    result['source_to_old_extra5_clock_shift_s'] = previous_shift
    result['old_extra5_metrics'] = old_metrics
    rows = []
    for i, label in enumerate(('baseline', 'tail_only', 'R_only'), 1):
        fall = clock.edges(w.t, w[f'sp{i}'] - w[f'sn{i}'], -1, 4e-9, STOP - .1e-9)
        shifts = offsets(fall, ref_fall)
        delta = float(np.median(shifts))
        total_shift = float(np.median(offsets(fall, source_fall)))
        metrics, details = serial.fixed_phase_window(w.t, w[f'qp{i}'] - w[f'qn{i}'], seq,
            delay_ui=point['training_delay_ui'] + total_shift / seq.ui_s, first_bit=296, end_bit=304)
        if i == 1:
            a = dict(zip(old_details['payload_transition_bits'], old_details['edge_residual_ui']))
            b = dict(zip(details['payload_transition_bits'], details['edge_residual_ui']))
            error = max((abs((b[k] - v) * seq.ui_s + delta) for k, v in a.items()), default=None) if a.keys() == b.keys() else None
            result['baseline_serial_edge_error_s'] = error
            if error is None or error > 2e-12 or metrics['bit_errors'] != old_metrics['bit_errors']:
                result.update(baseline_matches=False, branch_status='ungraded_baseline_failed')
                return result
        wm = (w.t >= 4e-9) & (w.t <= STOP - .1e-9)
        signals = {}
        for name, pos, neg in (('xe2_input', 'e1p', 'e1n'), ('xe2_output', 'e2p', 'e2n'), ('xe3_output', 'e3p', 'e3n')):
            p, n = w[f'xclock{i}.{pos}'], w[f'xclock{i}.{neg}']
            diff, cm = p - n, (p + n) / 2
            signals[name] = {'differential_pp_v': float(np.ptp(diff[wm])),
                             'cycles': clock.cycle_amplitudes(w.t, diff, 4e-9, STOP - .1e-9),
                             'common_mode_mean_v': float(waves.time_average(cm[wm], w.t[wm]))}
        for polarity in (-1, 1):
            a = clock.edges(w.t, w[f'xclock{i}.e1p'] - w[f'xclock{i}.e1n'], polarity, 4e-9, STOP - .1e-9)
            a = a[a <= STOP - .1e-9 - 250e-12]
            b = clock.edges(w.t, w[f'xclock{i}.e2p'] - w[f'xclock{i}.e2n'], polarity, 4e-9, STOP - .1e-9)
            delays = []
            for edge in a:
                hits = b[(b >= edge) & (b < edge + 250e-12)]
                if len(hits) != 1: raise ValueError('ambiguous Xe2 edge association')
                delays.append(float(hits[0] - edge))
            if not delays: raise ValueError('missing Xe2 edges')
            signals['xe2_output'][f'delay_{polarity}_s'] = delays
        cp, cn = w[f'sp{i}'], w[f'sn{i}']
        signals['c2g'] = {'differential_pp_v': float(np.ptp((cp-cn)[wm])),
                          'cycles': clock.cycle_amplitudes(w.t, cp-cn, 4e-9, STOP-.1e-9),
                          'common_mode_mean_v': float(waves.time_average(((cp+cn)/2)[wm], w.t[wm]))}
        rows.append({'branch': label, 'clock_fall_shift_s': delta, 'clock_shift_min_s': min(shifts),
                     'clock_total_shift_from_source_s': total_shift,
                     'clock_shift_max_s': max(shifts), 'metrics': metrics, 'details': details, 'nodes': signals,
                     'xe2_tail_mean_v': float(waves.time_average(w[f'xclock{i}.xe2.xgain.tail'][wm], w.t[wm]))})
    result['branches'] = rows
    return result


def json_default(obj):
    if isinstance(obj, np.generic): return obj.item()
    if isinstance(obj, np.ndarray): return obj.tolist()
    raise TypeError(type(obj).__name__)


def resume(camp):
    with (camp / '.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '_' + uuid.uuid4().hex[:8]
        archive = camp / 'analysis' / stamp
        archive.mkdir(parents=True, exist_ok=False)
        report = {'status': 'failed', 'scope': 'ideal replay; single worker; no upstream impedance or new real-bias validation', 'rows': []}
        try:
            check(camp, registered=True)
            if any(p == camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()): raise RuntimeError('campaign already active')
            entry = json.loads((SOURCE / 'boundary.json').read_text())
            for tag in TAGS:
                raw = completed(camp, tag)
                if raw is None:
                    if len(watch.ngspice_cwds()) >= 4: raise RuntimeError('global ngspice limit before smoke')
                    deck = (camp / 'prepared' / f'{tag}.cir').read_text()
                    smoke = deck.replace('tran .5p 6.500000000000e-09 .1n .5p', 'tran .5p 1.001n 0 .5p')
                    if smoke == deck: raise ValueError('smoke tran not found')
                    sd = spice.next_run_dir(camp, 'smoke_' + tag)
                    ex = spice.run(smoke, sd, timeout_s=180, meta={'condition': tag, 'kind': 'smoke'})
                    if not ex.ok or spice.case_output(camp, sd.name, tag + '.raw', 1.001e-9) is None:
                        raise RuntimeError(f'smoke failed: {sd}')
                    if len(watch.ngspice_cwds()) >= 4: raise RuntimeError('global ngspice limit before full run')
                    run = spice.next_run_dir(camp, tag)
                    ex = spice.run(deck, run, timeout_s=360, meta={'condition': tag, 'kind': 'full'})
                    if not ex.ok: raise RuntimeError(f'full run failed: {run}')
                    raw = completed(camp, tag)
                    if raw is None: raise RuntimeError(f'missing or truncated output: {tag}')
                row = {'condition': tag, 'raw': str(raw.relative_to(ROOT)), 'raw_sha256': digest(raw)}
                report['rows'].append(row)
                row['result'] = measure(camp, tag, raw, entry['points'][tag])
            report['status'] = 'measured' if all(r['result']['baseline_matches'] for r in report['rows']) else 'baseline_failed'
        except Exception as exc:
            report['error'] = f'{type(exc).__name__}: {exc}'
            raise
        finally:
            (archive / 'summary.json').write_text(json.dumps(report, indent=2, default=json_default, allow_nan=False) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--check', type=Path)
    group.add_argument('--resume', type=Path)
    args = parser.parse_args()
    if args.prepare:
        camp = prepare(); check(camp); print(camp)
    elif args.check:
        print(json.dumps(check(args.check.resolve()), indent=2))
    else:
        print(json.dumps(resume(args.resume.resolve()), indent=2, default=json_default, allow_nan=False))


if __name__ == '__main__':
    main()
