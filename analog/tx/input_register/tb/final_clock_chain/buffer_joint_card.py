"""Joint Xe2 card from the completed single-axis card; prepare/check do not simulate.

--resume requires a reviewed, registered boundary proposal. One worker, separate
smoke per condition, append-only runs and analysis. Scope is ideal replay only.
"""
import argparse
import fcntl
import importlib.util
import json
import re
import shutil
import time
import uuid
from pathlib import Path

from serdes_flow import boundary, spice, watch

ROOT = Path(__file__).resolve().parents[5]
HELPER = Path(__file__).with_name('buffer_local_card.py')
PARENT = ROOT / 'results/analog/tx/buffer_local_card/20261110T162412Z_17c84a60'
CAL = ROOT / 'docs/data/tx_buffer_local.json'
SPEC = importlib.util.spec_from_file_location('buffer_local_frozen_helper', HELPER)
old = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(old)
PARAMS = [('baseline', '16', '400'), ('joint_a', '12.8', '320'), ('joint_b', '12', '320')]
PREDICTION = {'joint_a': {'tt_v1800_t27': {'xe2_pp_v': .33783, 'c2g_increment_s': -.52e-12},
                          'fs_v1650_t85': {'xe2_pp_v': .31603, 'c2g_increment_s': -.42e-12}},
              'method': 'single-axis local model; prediction, not measured'}


def parent_check():
    old.check(PARENT, registered=True)
    data = json.loads(CAL.read_text())
    if data['campaign'] != str(PARENT.relative_to(ROOT)) or data['plan_sha256'] != old.digest(PARENT / 'plan.json'):
        raise ValueError('calibration parent plan mismatch')
    if data['runner_sha256'] != old.digest(HELPER): raise ValueError('parent helper changed')
    summary = ROOT / data['summary']
    if old.digest(summary) != data['summary_sha256']: raise ValueError('calibration summary changed')
    parsed = json.loads(summary.read_text())
    if parsed['status'] != 'measured' or any(not r['result']['baseline_matches'] for r in parsed['rows']):
        raise ValueError('parent baseline not calibrated')
    evidence = {}
    for tag in old.TAGS:
        raw = old.completed(PARENT, tag)
        if raw is None: raise ValueError(f'parent raw missing or incomplete: {tag}')
        for name, expected in data['evidence'][tag].items():
            p = raw if name == tag + '.raw' else raw.parent / name
            if old.digest(p) != expected: raise ValueError(f'parent evidence changed: {p}')
        evidence[tag] = data['evidence'][tag]
    return {'plan_sha256': old.digest(PARENT / 'plan.json'), 'cal_sha256': old.digest(CAL),
            'summary_sha256': old.digest(summary), 'evidence': evidence}


def check_decks(camp):
    for tag in old.TAGS:
        text = (camp / 'prepared' / f'{tag}.cir').read_text()
        for i, (_, wt, r) in enumerate(PARAMS, 1):
            sub = re.search(rf'(?ms)^\.subckt local_chain_{i} .*?^\.ends local_chain_{i}$', text)
            if not sub: raise ValueError('missing branch')
            lines = re.findall(r'(?m)^Xe2 .*$', sub.group())
            want = f'Xe2 e1p e1n e2p e2n vbias vdd vss serdes_cml_buffer wn=24 wt={wt} rload={r}'
            if lines != [want]: raise ValueError(f'wrong Xe2 branch {i}')
        # Branches must otherwise be byte-for-byte identical.
        chains = [re.search(rf'(?ms)^\.subckt local_chain_{i} .*?^\.ends local_chain_{i}$', text).group()
                  for i in (1, 2, 3)]
        normalized = [re.sub(r'(?m)^Xe2 .*$', 'Xe2 PARAMETERIZED', re.sub(r'local_chain_[123]', 'local_chain', c)) for c in chains]
        if len(set(normalized)) != 1: raise ValueError('non-Xe2 branch difference')


def prepare():
    parent = parent_check()
    camp = ROOT / 'results/analog/tx/buffer_joint_card' / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '_' + uuid.uuid4().hex[:8])
    camp.mkdir(parents=True, exist_ok=False)
    for dirname in ('inputs', 'snap', 'prepared', 'runtime'):
        shutil.copytree(PARENT / dirname, camp / dirname)
    for tag in old.TAGS:
        path = camp / 'prepared' / f'{tag}.cir'
        text = path.read_text().replace(str(PARENT / 'snap' / tag), str(camp / 'snap' / tag))
        def rewrite(m):
            i = int(m.group(1)); wt, r = PARAMS[i-1][1:]
            block = m.group(0)
            block, count = re.subn(r'(?m)^(Xe2 .*? wn=24 wt=)\S+( rload=)\S+$', rf'\g<1>{wt}\g<2>{r}', block)
            if count != 1: raise ValueError('expected one Xe2')
            return block
        text, n = re.subn(r'(?ms)^\.subckt local_chain_([123]) .*?^\.ends local_chain_\1$', rewrite, text)
        if n != 3: raise ValueError('missing chains')
        path.write_text(text)
    parent_bc = json.loads((PARENT / 'boundary_proposal.json').read_text())
    proposal = dict(parent_bc, id='tx_i17_extra5_xe2_joint_proposal', parent_id=parent_bc['id'],
                    parent_sha256=old.canonical(parent_bc), independent_mathematical_branches=[p[0] for p in PARAMS],
                    scope='ideal recorded PWL bias and supplies; no upstream impedance or new real-bias validation')
    (camp / 'boundary_proposal.json').write_text(json.dumps(proposal, indent=2) + '\n')
    shutil.copyfile(HELPER, camp / 'helper.py')
    shutil.copyfile(Path(__file__), camp / 'wrapper.py')
    shutil.copyfile(CAL, camp / 'calibration.json')
    plan = json.loads((PARENT / 'plan.json').read_text())
    plan['snapshots'] = {str(p.relative_to(camp)): old.digest(p) for p in camp.rglob('*') if p.is_file()}
    plan['status'] = 'prepared_not_simulated'
    (camp / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    joint = {'parent': str(PARENT.relative_to(ROOT)), 'parent_identity': parent,
             'wrapper_sha256': old.digest(Path(__file__)), 'helper_sha256': old.digest(HELPER),
             'plan_sha256': old.digest(camp / 'plan.json'), 'parameters': PARAMS, 'predictions': PREDICTION,
             'ungraded': ['physical resistance', 'tail Vdsat and Id', 'branch current and power', 'noise', 'upstream impedance', 'new real bias']}
    (camp / 'joint_plan.json').write_text(json.dumps(joint, indent=2) + '\n')
    check(camp)
    return camp


def check(camp, registered=False):
    joint = json.loads((camp / 'joint_plan.json').read_text())
    if joint['wrapper_sha256'] != old.digest(Path(__file__)) or joint['helper_sha256'] != old.digest(HELPER):
        raise ValueError('wrapper/helper changed')
    if joint['plan_sha256'] != old.digest(camp / 'plan.json') or joint['parent_identity'] != parent_check():
        raise ValueError('plan or parent evidence changed')
    if joint['parameters'] != [list(p) for p in PARAMS] or joint['predictions'] != PREDICTION:
        raise ValueError('joint identity changed')
    old.check(camp, registered=registered)
    proposal = json.loads((camp / 'boundary_proposal.json').read_text())
    if old.canonical(boundary.get(proposal['parent_id'])) != proposal['parent_sha256']:
        raise ValueError('parent boundary changed')
    check_decks(camp)
    return joint


def resume(camp):
    with (camp / '.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        archive = camp / 'analysis' / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '_' + uuid.uuid4().hex[:8])
        archive.mkdir(parents=True, exist_ok=False)
        result = {'status': 'failed', 'scope': 'ideal PWL replay; local cut only', 'rows': [], 'predictions': PREDICTION}
        try:
            check(camp, registered=True)
            if any(p == camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()): raise RuntimeError('campaign active')
            entry = json.loads((PARENT / 'boundary_proposal.json').read_text())
            for tag in old.TAGS:
                raw = old.completed(camp, tag)
                if raw is None:
                    if len(watch.ngspice_cwds()) >= 4: raise RuntimeError('global ngspice limit before smoke')
                    deck = (camp / 'prepared' / f'{tag}.cir').read_text()
                    smoke = deck.replace('tran .5p 6.500000000000e-09 .1n .5p', 'tran .5p 1.001n 0 .5p')
                    if smoke == deck: raise ValueError('smoke tran missing')
                    sd = spice.next_run_dir(camp, 'smoke_' + tag)
                    ex = spice.run(smoke, sd, timeout_s=180, meta={'condition': tag, 'kind': 'smoke'})
                    if not ex.ok or spice.case_output(camp, sd.name, tag + '.raw', 1.001e-9) is None:
                        raise RuntimeError(f'smoke failed: {sd}')
                    if len(watch.ngspice_cwds()) >= 4: raise RuntimeError('global ngspice limit before full run')
                    run = spice.next_run_dir(camp, tag)
                    ex = spice.run(deck, run, timeout_s=360, meta={'condition': tag, 'kind': 'full'})
                    if not ex.ok: raise RuntimeError(f'full run failed: {run}')
                    raw = old.completed(camp, tag)
                    if raw is None: raise RuntimeError(f'incomplete output: {tag}')
                row = {'condition': tag, 'raw': str(raw.relative_to(ROOT)), 'raw_sha256': old.digest(raw)}
                result['rows'].append(row)
                measurement = old.measure(camp, tag, raw, entry['points'][tag])
                for branch, (label, wt, r) in zip(measurement.get('branches', []), PARAMS):
                    branch.update(branch=label, wn_um=24, wt_um=float(wt), r_nominal_ohm=int(r))
                row['result'] = measurement
            result['status'] = 'measured' if all(r['result']['baseline_matches'] for r in result['rows']) else 'baseline_failed'
        except Exception as exc:
            result['error'] = f'{type(exc).__name__}: {exc}'
            raise
        finally:
            (archive / 'summary.json').write_text(json.dumps(result, indent=2, default=old.json_default, allow_nan=False) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--check', type=Path)
    group.add_argument('--resume', type=Path)
    args = parser.parse_args()
    if args.prepare: print(prepare())
    elif args.check: print(json.dumps(check(args.check.resolve()), indent=2))
    else: print(json.dumps(resume(args.resume.resolve()), indent=2, default=old.json_default, allow_nan=False))


if __name__ == '__main__': main()
