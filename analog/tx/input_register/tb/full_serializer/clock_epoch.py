"""Short, archived startup comparisons for a rejected producer-clock boundary.

Only metadata voltage sources and explicitly declared counter initial states
change. This does not implement a reset or certify power-up behavior.
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
from serdes_flow import clock, project, spice, watch
from serdes_flow.corners import Condition

ROOT = project.ROOT
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('full_tx_epoch_parent', HERE / 'run.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
STOP = 18e-9
OUT = ROOT / 'results/analog/tx/clock_epoch'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def source(camp, mode):
    camp = camp.resolve()
    plan = json.loads((camp / 'plan.json').read_text())
    if plan['mode'] != mode:
        raise ValueError('source mode mismatch')
    for rel, digest in plan['snapshot_files'].items():
        if sha(camp / rel) != digest:
            raise ValueError(f'source snapshot changed: {rel}')
    raw = spice.case_output(camp, 'run', 'waveforms.raw', plan['stop_s'])
    if raw is None:
        raise ValueError('source transient incomplete')
    ex = json.loads((raw.parent / 'execution.json').read_text())
    if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures']:
        raise ValueError('source execution failed')
    text = (raw.parent / 'tb.cir').read_text()
    if sha(raw.parent / 'tb.cir') != ex['deck_sha256'] or ex['deck_sha256'] != plan['deck_sha256']:
        raise ValueError('source executed deck changed')
    parent.check_runtime_includes(text, camp, plan)
    return plan, raw, text


def render(text, masters=False, metadata=False):
    prefix, control = text.split('.control', 1)
    if masters:
        if len(re.findall(r'^\.ic ', prefix, re.M)) != 1:
            raise ValueError('unexpected source initial-condition statements')
        state = ' '.join(f'v(xclocks.xcnt.m{i}p)=1.3 v(xclocks.xcnt.m{i}n)=1.6' for i in range(3))
        prefix = re.sub(r'^(\.ic .*)$', lambda m: m[1] + ' ' + state, prefix, flags=re.M)
    if metadata:
        if 'Vguard_' in prefix:
            raise ValueError('probe already contains metadata sources')
        extra = '\n'.join(f'Vguard_{n} guard_{n} 0 0' for n in ('a', 'b', 'ready', 'valid'))
        prefix, count = re.subn(r'^(Vd15 .*)$', lambda m: m[1] + '\n' + extra, prefix, flags=re.M)
        if count != 1:
            raise ValueError('cannot locate last probe data source')
    control, count = re.subn(r'^tran .*$','tran 2p 18n 0 2p',control,flags=re.M)
    if count != 1:
        raise ValueError('expected one transient')
    return prefix + '.control' + control


def circuit_key(text):
    return parent.fixture_signature(re.sub(r'^\.ic .*$', '', text, flags=re.M))


def prepare(probe, dynamic):
    pp, pr, pt = source(probe, 'probe')
    dp, dr, dt = source(dynamic, 'run')
    if pp['condition'] != dp['condition'] or circuit_key(pt) != circuit_key(dt):
        raise ValueError('source physical fixtures differ')
    camp = OUT / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    camp.mkdir(parents=True, exist_ok=False)
    variants = {'dynamic_repeat': render(dt), 'probe_metadata': render(pt, metadata=True),
                'probe_masters': render(pt, masters=True), 'dynamic_masters': render(dt, masters=True)}
    decks = {}
    for name, text in variants.items():
        if circuit_key(text) != circuit_key(pt):
            raise ValueError('diagnostic changed physical circuit')
        path = camp / 'prepared' / (name + '.cir')
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
        decks[name] = str(path.relative_to(camp))
    # Referenced original snapshots are immutable inputs, with every byte bound.
    bound = {}
    for original, plan in ((probe.resolve(), pp), (dynamic.resolve(), dp)):
        for rel in plan['snapshot_files']:
            path = original / rel
            bound[str(path)] = sha(path)
        for filename in ('plan.json', 'run/execution.json', 'run/tb.cir'):
            path = original / filename
            bound[str(path)] = sha(path)
    for raw in (pr, dr):
        bound[str(raw.resolve())] = sha(raw)
    bound[str(project.model_library())] = sha(project.model_library())
    files = [Path(__file__).resolve(), HERE/'run.py', HERE/'trace.py'] + [ROOT/'src/serdes_flow'/n for n in
             ('clock.py', 'spice.py', 'waves.py', 'watch.py', 'project.py', 'corners.py')]
    for f in files:
        dest = camp/'execution'/f.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, dest)
        bound[str(f)] = sha(f)
    plan = dict(condition=pp['condition'], stop_s=STOP, decks=decks,
                inputs_sha256=bound, snapshot_sha256={str(p.relative_to(camp)):sha(p)
                for folder in ('prepared','execution') for p in (camp/folder).rglob('*') if p.is_file()},
                pdk_installation_id=project.pdk_installation_id(),
                source_probe=str(probe.resolve()), source_dynamic=str(dynamic.resolve()),
                scope='Working-state initialization diagnosis; no reset, startup, eye or design qualification.')
    (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    return camp


def analyse(camp, plan):
    c = Condition.parse(plan['condition'])
    rows = []
    for name in plan['decks']:
        raw = spice.case_output(camp,name,'waveforms.raw',STOP)
        if raw is None:
            rows.append(dict(case=name,status='missing'))
            continue
        origin=Path(plan['source_dynamic'] if name.startswith('dynamic') else plan['source_probe'])
        parent.check_runtime_includes((raw.parent/'tb.cir').read_text(),origin,json.loads((origin/'plan.json').read_text()))
        ex = json.loads((raw.parent/'execution.json').read_text())
        if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures'] or sha(raw.parent/'tb.cir') != ex['deck_sha256'] or sha(camp/plan['decks'][name])!=ex['deck_sha256']:
            rows.append(dict(case=name,status='execution_failed'))
            continue
        w = spice.Waves(raw)
        rises = clock.edges(w.t,w['xtx.word_clk']-c.supply/2,1,8e-9,17.9e-9)
        e = clock.edges(w.t,w['xclocks.xcnt.ckp']-w['xclocks.xcnt.ckn'],-1)
        counter = clock.binary_counter(w.t,[w[f'xclocks.q{i}p']-w[f'xclocks.q{i}n'] for i in range(3)],e,8e-9,17.9e-9)
        rows.append(dict(case=name,status='measured',word_rises_s=rises.tolist(),counter=counter,
                         raw=str(raw),raw_sha256=sha(raw),deck_sha256=ex['deck_sha256'],execution_sha256=sha(raw.parent/'execution.json')))
    measured = {r['case']:r for r in rows if r['status']=='measured'}
    comparisons = {}
    for a,b in (('dynamic_repeat','probe_metadata'),('probe_masters','dynamic_masters')):
        if a not in measured or b not in measured:
            continue
        aa=np.asarray(measured[a]['word_rises_s']);bb=np.asarray(measured[b]['word_rises_s'])
        distances=[float(np.min(abs(bb-x))) for x in aa] if len(bb) else []
        comparisons[a+'__'+b]=dict(max_nearest_rise_difference_s=max(distances) if distances else None,
                                   both_counting=measured[a]['counter']['counting'] and measured[b]['counter']['counting'])
    calibration=None
    if 'dynamic_repeat' in measured:
        old=spice.Waves(Path(plan['source_dynamic'])/'run/waveforms.raw')
        new=spice.Waves(measured['dynamic_repeat']['raw'])
        keep=(new.t>=8e-9)&(new.t<=17e-9)
        nodes=['xtx.word_clk','c250p','c250n','c2gp','c2gn']+[f'xclocks.q{i}{s}' for i in range(3) for s in ('p','n')]
        errors={n:float(np.max(abs(new[n][keep]-np.interp(new.t[keep],old.t,old[n])))) for n in nodes}
        calibration=dict(max_voltage_error_v=errors,passed=max(errors.values())<=.005)
    result=dict(scope=plan['scope'],rows=rows,comparisons=comparisons,dynamic_repeat_calibration=calibration,analysis_source_sha256=sha(Path(__file__)))
    dest=camp/'analysis';dest.mkdir(exist_ok=True)
    (dest/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    (camp/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(comparisons,indent=2))


def resume(camp):
    camp=camp.resolve();plan=json.loads((camp/'plan.json').read_text())
    if any(p.is_relative_to(camp) for p in watch.ngspice_cwds()):
        raise RuntimeError('campaign has live ngspice')
    if project.pdk_installation_id()!=plan['pdk_installation_id']:
        raise ValueError('PDK changed')
    for path,digest in plan['inputs_sha256'].items():
        if sha(path)!=digest:raise ValueError(f'input changed: {path}')
    for path,digest in plan['snapshot_sha256'].items():
        if sha(camp/path)!=digest:raise ValueError(f'snapshot changed: {path}')
    jobs=[((camp/rel).read_text(),spice.next_run_dir(camp,name),dict(timeout_s=420))
          for name,rel in plan['decks'].items() if spice.case_output(camp,name,'waveforms.raw',STOP) is None]
    if jobs:
        spice.run_many(jobs,workers=2)
    analyse(camp,plan)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--probe',type=Path);p.add_argument('--dynamic',type=Path);p.add_argument('--resume',type=Path)
    a=p.parse_args()
    if a.resume:
        resume(a.resume)
    else:
        if not a.probe or not a.dynamic:p.error('--probe and --dynamic required')
        print(prepare(a.probe,a.dynamic))


if __name__=='__main__':main()
