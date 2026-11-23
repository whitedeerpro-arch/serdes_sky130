"""Append-only H4 boundary evidence: prepare/check/resume, no extrapolation.

One measured boundary point per previously unproven condition, paired with a
same-code measured in-window endpoint. Prediction ranks candidates, not acceptance.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from serdes_flow import project, spice, watch
from serdes_flow.corners import Condition
ROOT=project.ROOT
SELF=Path(__file__).resolve(); HERE=SELF.parent
spec=importlib.util.spec_from_file_location('boundary_workmap',HERE/'workmap.py');wm=importlib.util.module_from_spec(spec);spec.loader.exec_module(wm)
spec=importlib.util.spec_from_file_location('boundary_windows',ROOT/'verification/analysis/vco_control_windows.py');windows=importlib.util.module_from_spec(spec);spec.loader.exec_module(windows)
SOURCE=ROOT/'results/analog/pll/vco/workmap/20261106T035710Z/summary.json'
FILL=ROOT/'results/analog/pll/vco/workmap_fill/20261109T044852Z/analysis/20261109T092349.030536Z_0bac2b46/summary.json'
OUT=ROOT/'results/analog/pll/vco/window_boundary_anchor'
SOURCES=(SELF,HERE/'workmap.py',wm.TEMPLATE,ROOT/'verification/analysis/vco_control_windows.py',
         ROOT/'src/serdes_flow/spice.py',ROOT/'src/serdes_flow/bias.py',ROOT/'src/serdes_flow/rcorner.py',
         ROOT/'src/serdes_flow/project.py',ROOT/'src/serdes_flow/corners.py',ROOT/'src/serdes_flow/waves.py',
         ROOT/'config/pdk.toml',ROOT/'config/tools.toml')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def pdk_manifest():
    root=project.model_library().parents[2]
    files=sorted(p for d in (root/'libs.tech/ngspice',root/'libs.ref/sky130_fd_pr/spice') for p in d.rglob('*') if p.is_file())
    if not files:raise ValueError('missing PDK')
    return {str(p):sha(p) for p in files}


def make_plan():
    src=json.loads(SOURCE.read_text());fill=json.loads(FILL.read_text())
    static=windows.analyse(src,fill,sha(SOURCE),sha(FILL),SOURCE,FILL)
    original,extra=windows.unpack(src,True),windows.unpack(fill,False)
    curves={**original,**extra};selected=[];complete=[];no_single=[]
    for condition,row in static['conditions'].items():
        tag,rc=condition.split(':');c=Condition.parse(tag);lo=.90;hi=round(c.supply-.44,8);options=[];good=[]
        for code,entry in row['curves'].items():
            curve=curves[(condition,int(code))]
            for cross in entry['crossings']:
                a,b=cross['bracket_v'];fa,fb=cross['bracket_hz']
                if fa>=fb:continue
                if lo<=a and b<=hi:
                    good.append(int(code));continue
                if a<lo<=b<=hi: side,edge,inside,inside_f='lo',lo,b,fb
                elif lo<=a<=hi<b:side,edge,inside,inside_f='hi',hi,a,fa
                else:continue
                match=[i for i,x in enumerate(curve['vs']) if abs(x-edge)<1e-9]
                options.append(dict(condition=condition,code=int(code),side=side,boundary_v=edge,
                                    existing_v=inside,existing_frequency_hz=inside_f,origin=entry['origin'],
                                    predicted_crossing_v=cross['v'], predicted_room_v=min(cross['v']-lo,hi-cross['v']),
                                    existing_boundary_frequency_hz=curve['f'][match[0]] if match else None))
        if good:complete.append(dict(condition=condition,codes=sorted(set(good))));continue
        if not options:no_single.append(condition);continue
        # Reuse an already measured boundary first; otherwise choose largest predicted window room.
        selected.append(max(options,key=lambda x:(x['existing_boundary_frequency_hz'] is not None,x['predicted_room_v'],-x['code'])))
    return dict(already_complete=complete,selected=selected,no_single_point_candidate=no_single,
                scope='H4 ideal static .90..VDD-.44 V; 30 fF per leg; positive measured bracket slopes; selection prediction ungraded')


def group_name(item):
    tag,rc=item['condition'].split(':');c=Condition.parse(tag)
    return f'{c.process}_{rc}'


def points(items):
    return [(Condition.parse(x['condition'].split(':')[0]),x['code'],x['boundary_v']) for x in items]


def prepare():
    design=make_plan();camp=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);camp.mkdir(parents=True,exist_ok=False)
    for p in SOURCES:
        dest=camp/'sources'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    for label,p in (('source_summary.json',SOURCE),('fill_summary.json',FILL)):(camp/'sources'/label).write_bytes(p.read_bytes())
    groups=defaultdict(list)
    for item in design['selected']:
        if item['existing_boundary_frequency_hz'] is None:groups[group_name(item)].append(item)
    (camp/'prepared').mkdir()
    entries=[]
    for name,items in sorted(groups.items()):
        proc,rc=name.split('_');path=camp/'prepared'/f'{name}.cir';path.write_text(wm.deck(proc,rc,points(items),camp/'snap'/name,4))
        entries.append(dict(name=name,conditions=[x['condition'] for x in items],deck=str(path.relative_to(camp))))
    first=entries[0];item=groups[first['name']][0];proc,rc=first['name'].split('_')
    smoke=wm.deck(proc,rc,points([item]),camp/'snap'/first['name'],4)
    short=smoke.replace(f'tran 2p {wm.STOP:.4e} {wm.START:.4e}','tran 2p 1e-9 0')
    if short==smoke:raise ValueError('smoke replacement failed')
    (camp/'prepared/smoke.cir').write_text(short)
    files=sorted(p for sub in ('sources','snap','prepared') for p in (camp/sub).rglob('*') if p.is_file())
    plan=dict(**design,groups=entries,smoke_condition=item['condition'],smoke_name=wm.name(*points([item])[0]),
              source_path=str(SOURCE.relative_to(ROOT)),source_sha256=sha(SOURCE),fill_path=str(FILL.relative_to(ROOT)),fill_sha256=sha(FILL),
              source_files={str(p.relative_to(ROOT)):sha(p) for p in SOURCES},bank=4,
              pdk_installation_id=project.pdk_installation_id(),pdk_sha256=pdk_manifest(),
              snapshots={str(p.relative_to(camp)):sha(p) for p in files})
    (camp/'plan.json').write_text(json.dumps(plan,indent=2,allow_nan=False)+'\n');return camp


def verify(camp):
    plan=json.loads((camp/'plan.json').read_text())
    if plan['pdk_installation_id']!=project.pdk_installation_id() or plan['pdk_sha256']!=pdk_manifest():raise ValueError('PDK changed')
    if sha(SOURCE)!=plan['source_sha256'] or sha(FILL)!=plan['fill_sha256']:raise ValueError('input summary changed')
    for rel,h in plan['source_files'].items():
        if sha(ROOT/rel)!=h:raise ValueError(f'source changed {rel}')
    for rel,h in plan['snapshots'].items():
        if sha(camp/rel)!=h:raise ValueError(f'snapshot changed {rel}')
    actual=make_plan()
    for key in ('already_complete','selected','no_single_point_candidate','scope'):
        if plan[key]!=actual[key]:raise ValueError(f'plan identity changed {key}')
    groups=defaultdict(list)
    for item in plan['selected']:
        if item['existing_boundary_frequency_hz'] is None:groups[group_name(item)].append(item)
    if {g['name'] for g in plan['groups']}!=set(groups):raise ValueError('group identity changed')
    for g in plan['groups']:
        proc,rc=g['name'].split('_');items=groups[g['name']]
        if g['conditions']!=[x['condition'] for x in items] or (camp/g['deck']).read_text()!=wm.deck(proc,rc,points(items),camp/'snap'/g['name'],4):raise ValueError('prepared deck changed')
    return plan,groups


def checked(camp,name,items):
    proc,rc=name.split('_');allowed={wm.name(c,k,v):(c,k,v) for c,k,v in points(items)}
    for run in [camp/name]+list(camp.glob(name+'.r[0-9]*')):
        if not run.exists():continue
        text=(run/'tb.cir').read_text();names=re.findall(r'^write (\S+)',text,re.M)
        if not names or len(names)!=len(set(names)) or any(n not in allowed for n in names):raise ValueError(f'untrusted deck {run}')
        if text!=wm.deck(proc,rc,[allowed[n] for n in names],camp/'snap'/name,4):raise ValueError(f'changed deck {run}')
        e=run/'execution.json'
        if e.exists() and json.loads(e.read_text()).get('deck_sha256')!=sha(run/'tb.cir'):raise ValueError(f'deck hash mismatch {run}')
    return {n:spice.case_output(camp,name,n,wm.STOP) for n in allowed}


def smoke_valid(run,deck,name):
    try:
        ex=json.loads((run/'execution.json').read_text());w=spice.Waves(run/name)
        return (ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and ex['deck_sha256']==sha(deck)
                and sha(run/'tb.cir')==sha(deck) and w.t[-1]>=1e-9*(1-1e-6) and 'v(v0p)' in w and 'v(v0n)' in w)
    except (OSError,ValueError,KeyError,IndexError):return False


def collect(camp,plan,groups):
    cache={name:checked(camp,name,items) for name,items in groups.items()};rows=[]
    for item in plan['selected']:
        c,k,v=points([item])[0];existing=item['existing_boundary_frequency_hz'];p=None
        if existing is None:p=cache[group_name(item)][wm.name(c,k,v)]
        try:m=wm.measure(p) if p else None
        except (OSError,ValueError,KeyError,IndexError):m=None
        f=existing if existing is not None else (float(m[0]) if m is not None and math.isfinite(m[0]) else None)
        observed=None if f is None else (f<=wm.TARGET if item['side']=='lo' else f>=wm.TARGET)
        # Also validate the in-window measured endpoint has the opposite sign.
        paired=item['existing_frequency_hz']>=wm.TARGET if item['side']=='lo' else item['existing_frequency_hz']<=wm.TARGET
        status='unknown_missing_or_invalid_measurement' if observed is None else ('evidenced_bracket' if observed and paired else 'tested_boundary_did_not_bracket')
        rows.append(dict(**item,boundary_frequency_hz=f,boundary_swing_v=float(m[1]) if m else None,
                         run_waveform=str(p.relative_to(ROOT)) if p else None,status=status))
    folder=camp/'analysis'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);folder.mkdir(parents=True)
    (folder/'summary.json').write_text(json.dumps(dict(scope=plan['scope'],spec_status='ungraded',rows=rows,
        no_single_point_candidate=plan['no_single_point_candidate'],already_complete=plan['already_complete'],source_sha256=plan['source_sha256'],fill_sha256=plan['fill_sha256']),indent=2,allow_nan=False)+'\n')
    print(folder/'summary.json');return rows


def resume(camp,workers):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);plan,groups=verify(camp);active=watch.ngspice_cwds()
        if len(active)+workers>4 or any(p==camp or p.is_relative_to(camp) for p in active):raise RuntimeError('global quota or campaign active')
        smoke=camp/'prepared/smoke.cir'
        if not any(smoke_valid(p,smoke,plan['smoke_name']) for p in [camp/'smoke']+list(camp.glob('smoke.r[0-9]*'))):
            run=spice.next_run_dir(camp,'smoke');spice.run(smoke.read_text(),run,timeout_s=120,meta={'phase':'1ns_smoke_ungraded'})
            if not smoke_valid(run,smoke,plan['smoke_name']):raise RuntimeError(f'smoke failed {run}')
        jobs=[]
        for name,items in sorted(groups.items()):
            have=checked(camp,name,items);todo=[p for p in points(items) if have[wm.name(*p)] is None]
            if todo:
                proc,rc=name.split('_');jobs.append((wm.deck(proc,rc,todo,camp/'snap'/name,4),spice.next_run_dir(camp,name),dict(timeout_s=600+60*len(todo),meta={'points':len(todo),'bank':4})))
        for ex in spice.run_many(jobs,workers=workers,smoke=False):
            if not ex.ok:print(f'deck failed {ex.run_dir}',flush=True)
        rows=collect(camp,plan,groups)
        if any(r['status']=='unknown_missing_or_invalid_measurement' for r in rows):raise RuntimeError('incomplete/invalid observations; inspect and resume')


def main():
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--check',type=Path);g.add_argument('--resume',type=Path)
    ap.add_argument('--workers',type=int,default=2);a=ap.parse_args()
    if not 1<=a.workers<=2:ap.error('workers must be 1 or 2')
    if a.prepare:print(prepare())
    elif a.check:
        plan,groups=verify(a.check.resolve());print(f'checkpoint valid; {len(plan["already_complete"])} already evidenced, {len(plan["selected"])} selected, {sum(map(len,groups.values()))} new points in {len(groups)} decks; no ngspice')
    else:resume(a.resume.resolve(),a.workers)


if __name__=='__main__':main()
