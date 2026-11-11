"""Xe4 WN24/32/40 local sensitivity, with its actual frozen WN32 output load.

Prepare/check launch no simulator. Register the reviewed boundary separately;
resume runs one worker, a 1 ns smoke, then each missing complete 6.5 ns case.
This is a legacy generic-resistor/driver fixture, not current full-TX approval.
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

import numpy as np

from serdes_flow import boundary, clock, project, spice, stage_metrics, watch

ROOT = project.ROOT
PARENT = ROOT / 'results/analog/tx/buffer_matrix_card/20261110T172325Z_dda392af'
DATA = ROOT / 'docs/data/tx_buffer_taper.json'
HELPER = Path(__file__).with_name('buffer_matrix_card.py')
spec = importlib.util.spec_from_file_location('heavy_parent', HELPER)
matrix = importlib.util.module_from_spec(spec); spec.loader.exec_module(matrix)
old = matrix.old
WIDTHS = (24, 32, 40)
START, END = 4e-9, 6.4e-9
SCOPE = ('TT and FS low-voltage hot; recorded ideal PWL; frozen generic high_po R tt; '
         'legacy pre150/out256 driver; eight-bit local contract, not current full TX')
UNGRADED = ['fixed-width physical resistors and their corners', 'upstream source impedance',
            'new real-bias response', 'remaining PVT', 'noise and mismatch',
            'full-payload current full TX and pad', 'I-17 closure']


def parent_identity():
    matrix.check(PARENT, registered=True)
    data = json.loads(DATA.read_text())
    if data['campaign'] != str(PARENT.relative_to(ROOT)):
        raise ValueError('wrong parent publication')
    for key, path in (('plan_sha256', PARENT/'plan.json'),
                      ('sizing_plan_sha256', PARENT/'matrix_plan.json'),
                      ('runner_sha256', HELPER), ('summary_sha256', ROOT/data['summary'])):
        if old.digest(path) != data[key]: raise ValueError(f'parent {key} changed')
    for tag in old.TAGS:
        raw = old.completed(PARENT, tag)
        if raw is None: raise ValueError('incomplete parent')
        for name, expected in data['evidence'][tag].items():
            path = raw if name == tag+'.raw' else raw.parent/name
            if old.digest(path) != expected: raise ValueError(f'parent evidence changed: {path}')
        row = next(r for r in data['results'] if r['condition'] == tag)
        if not row['result']['baseline_matches']: raise ValueError('uncalibrated parent')
    return dict(data_sha256=old.digest(DATA), evidence=data['evidence'],
                plan_sha256=data['plan_sha256'], matrix_sha256=data['sizing_plan_sha256'])


def device_probes():
    probes = []
    for i in (1, 2, 3):
        for cell in ('xe4', 'xout'):
            prefix = f'm.xclock{i}.{cell}.xgain'
            for name, attribute in (('xtail', 'id'), ('xtail', 'vdsat'),
                                    ('xmp', 'gm'), ('xmn', 'gm')):
                model = 'nfet_01v8' if name == 'xtail' else 'nfet_01v8_lvt'
                probes.append((f'{cell}_{name}_{attribute}_{i}',
                               f'@{prefix}.{name}.msky130_fd_pr__{model}[{attribute}]'))
    return probes


def render(text, camp, tag):
    """The only electrical changes: Xe4 WN; ideal rail current-sense sources."""
    text = text.replace(str(PARENT/'snap'/tag), str(camp/'snap'/tag))
    def alter(match):
        i = int(match.group(1)); block = match.group()
        for n in range(5):
            wn = WIDTHS[i-1] if n == 4 else 24
            block, count = re.subn(rf'(?m)^(Xe{n} .*?) wn=\S+ wt=\S+ rload=\S+$',
                                  lambda m: f'{m[1]} wn={wn} wt=16 rload=400', block)
            if count != 1: raise ValueError('missing/duplicate extra stage')
        boundary.check_load(json.loads((PARENT/'boundary_proposal.json').read_text())['id'],
                            boundary.input_stage_signature(block, f'local_chain_{i}', ['rp','rn']))
        return block
    text, count = re.subn(r'(?ms)^\.subckt local_chain_([123]) .*?^\.ends local_chain_\1$', alter, text)
    if count != 3: raise ValueError('missing chain')
    for i in (1, 2, 3):
        original = f'Xclock{i} rp rn sp{i} sn{i} vbias vdd 0 local_chain_{i}'
        replacement = f'Vsense{i} vdd vd{i} 0\nXclock{i} rp rn sp{i} sn{i} vbias vd{i} 0 local_chain_{i}'
        if text.count(original) != 1: raise ValueError('missing chain supply')
        text = text.replace(original, replacement)
    voltages = [f'v(xclock{i}.{cell}.xgain.tail)' for i in (1,2,3) for cell in ('xe4','xout')]
    currents = [f'i(vsense{i})' for i in (1,2,3)]
    props = device_probes()
    saves = ' '.join(voltages + currents + [p for _,p in props])
    writes = ' '.join(voltages + currents + [n for n,_ in props])
    text, ns = re.subn(r'(?m)^(\.save .+)$', lambda m: m[1]+' '+saves, text)
    lets = '\n'.join(f'let {name} = {prop}' for name,prop in props)
    text, nw = re.subn(r'(?m)^(write '+tag+r'\.raw .+)$', lambda m: lets+'\n'+m[1]+' '+writes, text)
    if ns != 1 or nw != 1 or 'set filetype=binary' not in text:
        raise ValueError('binary/probe insertion failed')
    return text


def prepare():
    identity = parent_identity()
    camp = ROOT/'results/analog/tx/buffer_heavy_card'/(time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+uuid.uuid4().hex[:8])
    camp.mkdir(parents=True, exist_ok=False)
    for name in ('inputs', 'snap'): shutil.copytree(PARENT/name, camp/name)
    (camp/'prepared').mkdir(); (camp/'runtime').mkdir()
    for tag in old.TAGS:
        (camp/'prepared'/f'{tag}.cir').write_text(render((PARENT/'prepared'/f'{tag}.cir').read_text(), camp, tag))
    bc = json.loads((PARENT/'boundary_proposal.json').read_text())
    proposal = dict(bc, id='tx_extra5_heavy_wn24_32_40_v1', parent_id=bc['id'],
                    parent_sha256=old.canonical(bc), scope=SCOPE,
                    independent_mathematical_branches=[f'xe4_wn{w}' for w in WIDTHS])
    (camp/'boundary_proposal.json').write_text(json.dumps(proposal,indent=2)+'\n')
    runtime = {str(p):old.digest(p) for p in old.RUNTIME + [Path(__file__).resolve(), Path(stage_metrics.__file__)]}
    for path in runtime:
        destination = camp/'runtime'/path.lstrip('/'); destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,destination)
    shutil.copyfile(DATA,camp/'parent_data.json')
    (camp/'hypothesis.json').write_text(json.dumps(dict(
        varied='Xe4 input pair total WN only; NF4, WT16 and R400 fixed; Xout WN32/WT16/R240 fixed',
        reason='Calibrate final extra stage driving WN32 and include increased load on Xe3.',
        pre_run_expectation='At fixed current, long-channel gm scales roughly sqrt(W); input gate area roughly W. '
                            'Larger W may improve current steering and tail compliance but loads Xe3 and increases Xe4 drain C. '
                            'No numerical eye/delay or process-corner prediction is claimed.',
        relative_width=[w/24 for w in WIDTHS], rough_relative_gm=[float(np.sqrt(w/24)) for w in WIDTHS],
        measured=['stage amplitude/common mode', 'causal delay/slew', 'tail Id/VDS-VDSAT', 'clock-chain rail power', 'local eight-bit contract'],
        baseline_gates='same-time single-ended <=5mV; c2g same absolute edge <=2ps; original source baseline gate also retained',
        adoption='none; current full TX/load and physical resistor mapping need separate confirmation',
        scope=SCOPE, ungraded=UNGRADED),indent=2)+'\n')
    plan = dict(scope=SCOPE, parent=str(PARENT.relative_to(ROOT)), parent_identity=identity,
                script_sha256=old.digest(Path(__file__)), runtime=runtime,
                stop_s=old.STOP, widths=list(WIDTHS), measurement_window_s=[START,END],
                snapshots={str(p.relative_to(camp)):old.digest(p) for p in camp.rglob('*') if p.is_file()},
                status='prepared_not_simulated', ungraded=UNGRADED)
    (camp/'heavy_plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    check(camp); return camp


def check(camp, registered=False):
    plan = json.loads((camp/'heavy_plan.json').read_text())
    if plan['script_sha256'] != old.digest(Path(__file__)) or plan['parent_identity'] != parent_identity():
        raise ValueError('runner/parent changed')
    for path, expected in plan['runtime'].items():
        if old.digest(Path(path)) != expected: raise ValueError(f'runtime changed: {path}')
    for rel, expected in plan['snapshots'].items():
        if old.digest(camp/rel) != expected: raise ValueError(f'snapshot changed: {rel}')
    proposal = json.loads((camp/'boundary_proposal.json').read_text())
    if old.canonical(boundary.get(proposal['parent_id'])) != proposal['parent_sha256']:
        raise ValueError('parent boundary changed')
    if registered and boundary.get(proposal['id']) != proposal: raise ValueError('child boundary not registered')
    for tag in old.TAGS:
        expected = render((PARENT/'prepared'/f'{tag}.cir').read_text(),camp,tag)
        if (camp/'prepared'/f'{tag}.cir').read_text() != expected: raise ValueError('undeclared deck change')
    return plan


def probe_check(raw):
    w = spice.Waves(raw)
    for i in (1,2,3):
        if f'i(vsense{i})' not in w: raise ValueError('missing rail current vector')
    for name, _ in device_probes():
        if name not in w or not np.all(np.isfinite(w[name])):
            raise ValueError(f'missing/non-finite device telemetry: {name}')
    return w


def measure(camp, tag, raw):
    w = probe_check(raw); parent_raw = old.completed(PARENT,tag); parent = spice.Waves(parent_raw)
    names = ['sp1','sn1','qp1','qn1']+[f'xclock1.e{k}{pn}' for k in (3,4) for pn in ('p','n')]
    mask = (w.t>=START)&(w.t<=END)
    errors = {n:float(np.max(np.abs(w[n][mask]-np.interp(w.t[mask],parent.t,parent[n])))) for n in names}
    edge_errors = []
    for polarity in (-1,1):
        a = clock.edges(w.t,w['sp1']-w['sn1'],polarity,START,END)
        b = clock.edges(parent.t,parent['sp1']-parent['sn1'],polarity,START,END)
        edge_errors.extend(matrix.cascade.offsets(a,b))
    calibrated = max(errors.values())<=.005 and max(abs(x) for x in edge_errors)<=2e-12
    points = json.loads((camp/'boundary_proposal.json').read_text())['points']
    result = matrix.cascade.measure(camp,tag,raw,points[tag])
    result['parent_baseline'] = dict(matches=bool(calibrated),maximum_voltage_error_v=max(errors.values()),
                                     voltage_errors_v=errors,maximum_absolute_edge_error_s=max(abs(x) for x in edge_errors))
    result['ungraded'] = UNGRADED
    if not calibrated or not result['baseline_matches']:
        result['status']='ungraded_baseline_failed'; return result
    for i, (row, wn) in enumerate(zip(result['branches'],WIDTHS),1):
        row['branch']=f'xe4_wn{wn}'; row['wn_um']=wn
        row['clock_chain_power_w']=stage_metrics.telemetry(w.t,w['vdd']*w[f'i(vsense{i})'],START,END)
        row['power_scope']='Xiso + Xe0..Xe4 + Xout rail only; excludes input/bias sources and all other TX blocks'
        row['propagation']={}
        for before, after in (('e2','e3'),('e3','e4')):
            yin=w[f'xclock{i}.{before}p']-w[f'xclock{i}.{before}n']
            yout=w[f'xclock{i}.{after}p']-w[f'xclock{i}.{after}n']
            row['propagation'][f'{before}_to_{after}']=stage_metrics.propagation(w.t,yin,yout,START,END,200e-12)
        row['devices']={}
        for cell in ('xe4','xout'):
            tail=w[f'xclock{i}.{cell}.xgain.tail']; sat=w[f'{cell}_xtail_vdsat_{i}']
            row['devices'][cell]=dict(
                tail_current_a=stage_metrics.telemetry(w.t,w[f'{cell}_xtail_id_{i}'],START,END),
                tail_headroom_v=stage_metrics.headroom(w.t,tail,np.zeros_like(tail),sat,START,END),
                pair_gm_sum_s=stage_metrics.telemetry(w.t,w[f'{cell}_xmp_gm_{i}']+w[f'{cell}_xmn_gm_{i}'],START,END))
        metrics=row['metrics']
        row['local_eye_screen']=bool(metrics['functional'] and metrics['minimum_signed_margin_v']>=.075 and metrics['transition_spread_ui']<=.15)
    return result


def register(camp):
    check(camp)
    proposal=json.loads((camp/'boundary_proposal.json').read_text())
    before=json.loads(boundary.REGISTRY.read_text())
    boundary.register(proposal)
    # Keep existing order/format: registration must not reorder unrelated entries.
    after=json.loads(boundary.REGISTRY.read_text())
    if {e['id']:e for e in after} != {e['id']:e for e in before+[proposal]}:
        raise RuntimeError('unexpected registry change')
    boundary.REGISTRY.write_text(json.dumps(before+[proposal],indent=1,ensure_ascii=False)+'\n')
    check(camp,registered=True)


def resume(camp):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        check(camp,registered=True)
        if any(p==camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()): raise RuntimeError('campaign active')
        archive=spice.next_run_dir(camp/'analysis','measurement')
        archive.mkdir(parents=True,exist_ok=False)
        report=dict(status='failed',scope=SCOPE,plan_sha256=old.digest(camp/'heavy_plan.json'),rows=[],ungraded=UNGRADED)
        try:
            for tag in old.TAGS:
                raw=old.completed(camp,tag)
                if raw is None:
                    if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice limit')
                    deck=(camp/'prepared'/f'{tag}.cir').read_text()
                    smoke=deck.replace('tran .5p 6.500000000000e-09 .1n .5p','tran .5p 1.001n 0 .5p')
                    if smoke==deck: raise ValueError('smoke tran missing')
                    sd=spice.next_run_dir(camp,'smoke_'+tag)
                    ex=spice.run(smoke,sd,timeout_s=240,meta={'condition':tag,'kind':'smoke'})
                    smoke_raw=spice.case_output(camp,sd.name,tag+'.raw',1.001e-9)
                    if not ex.ok or smoke_raw is None: raise RuntimeError(f'smoke failed: {sd}')
                    probe_check(smoke_raw)
                    if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice limit')
                    run=spice.next_run_dir(camp,tag)
                    ex=spice.run(deck,run,timeout_s=480,meta={'condition':tag,'kind':'full'})
                    if not ex.ok: raise RuntimeError(f'full failed: {run}')
                    raw=old.completed(camp,tag)
                    if raw is None: raise RuntimeError(f'incomplete output: {tag}')
                row=dict(condition=tag,raw=str(raw.relative_to(ROOT)),
                         evidence={p.name:old.digest(p) for p in (raw,raw.parent/'execution.json',raw.parent/'tb.cir',raw.parent/'simulator.log')})
                report['rows'].append(row); row['result']=measure(camp,tag,raw)
                if not row['result']['baseline_matches'] or row['result']['status']=='ungraded_baseline_failed':
                    raise RuntimeError(f'baseline calibration failed: {tag}')
            report['status']='measurement_complete'
        except Exception as exc:
            report['error']=f'{type(exc).__name__}: {exc}'; raise
        finally:
            (archive/'summary.json').write_text(json.dumps(report,indent=2,default=old.json_default,allow_nan=False)+'\n')
    return archive/'summary.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true'); group.add_argument('--check',type=Path)
    group.add_argument('--register',type=Path); group.add_argument('--resume',type=Path)
    args=parser.parse_args()
    if args.prepare: print(prepare())
    elif args.check: print(json.dumps(check(args.check.resolve()),indent=2))
    elif args.register: register(args.register.resolve()); print('registered')
    else: print(resume(args.resume.resolve()))


if __name__=='__main__': main()
