"""FS/1.65 V/hh 38 C static four-bit VCO hysteresis anchor; not dynamic switching.

Prepare/check are simulator-free. Resume first performs an independent 1 ns smoke,
then resumes only missing 24 ns cases, and writes an ungraded analysis record.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from serdes_flow import project, spice, watch
from serdes_flow.corners import Condition

ROOT = project.ROOT
SELF = Path(__file__).resolve()
HERE = SELF.parent
spec = importlib.util.spec_from_file_location('hysteresis_anchor_workmap', HERE / 'workmap.py')
wm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wm)
OUT = ROOT / 'results/analog/pll/vco/hysteresis_anchor'
MODEL = ROOT / 'results/analog/pll/vco/workmap_fill/20261109T044852Z/analysis/recode_evidence_20261109T1000_review2.json'
SOURCES = (SELF, HERE/'workmap.py', wm.TEMPLATE, ROOT/'src/serdes_flow/spice.py',
           ROOT/'src/serdes_flow/bias.py', ROOT/'src/serdes_flow/rcorner.py',
           ROOT/'src/serdes_flow/project.py', ROOT/'src/serdes_flow/corners.py',
           ROOT/'src/serdes_flow/waves.py', ROOT/'config/pdk.toml', ROOT/'config/tools.toml')
C = Condition('fs', 1.65, 38)
POINTS = [(C, k, v) for k, vs in ((0, (.85, .90, .95)), (1, (1.05, 1.10, 1.15))) for v in vs]
NAME = 'fs_hh_v1650'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''): h.update(b)
    return h.hexdigest()


def pdk_manifest():
    root = project.model_library().parents[2]
    files = sorted(p for d in (root/'libs.tech/ngspice', root/'libs.ref/sky130_fd_pr/spice')
                   for p in d.rglob('*') if p.is_file())
    if not files: raise ValueError('PDK files absent')
    return {str(p):sha(p) for p in files}


def prepare():
    camp = OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8])
    camp.mkdir(parents=True, exist_ok=False)
    for src in SOURCES:
        dest=camp/'sources'/src.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
    (camp/'sources/model_report.json').write_bytes(MODEL.read_bytes())
    (camp/'prepared').mkdir()
    full=wm.deck('fs','hh',POINTS,camp/'snap',4)
    one=wm.deck('fs','hh',POINTS[:1],camp/'snap',4)
    smoke=one.replace(f'tran 2p {wm.STOP:.4e} {wm.START:.4e}', 'tran 2p 1e-9 0')
    if smoke == one: raise ValueError('smoke transient substitution failed')
    (camp/'prepared/full.cir').write_text(full)
    (camp/'prepared/smoke.cir').write_text(smoke)
    files=[p for sub in ('sources','snap','prepared') for p in (camp/sub).rglob('*') if p.is_file()]
    plan=dict(scope='static calibration only; nonstandard 38 C; real bias PDK R four buffers 30 fF/leg; no switching or startup qualification',
              points=[dict(condition=C.tag,code=k,vctrl=v) for _,k,v in POINTS],bank=4,
              source_files={str(p.relative_to(ROOT)):sha(p) for p in SOURCES},model_path=str(MODEL.relative_to(ROOT)),model_sha256=sha(MODEL),
              pdk_installation_id=project.pdk_installation_id(),pdk_sha256=pdk_manifest(),
              snapshots={str(p.relative_to(camp)):sha(p) for p in files})
    (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    return camp


def verify(camp):
    plan=json.loads((camp/'plan.json').read_text())
    if plan['bank'] != 4 or plan['points'] != [dict(condition=C.tag,code=k,vctrl=v) for _,k,v in POINTS]: raise ValueError('geometry changed')
    if plan['pdk_installation_id'] != project.pdk_installation_id() or plan['pdk_sha256'] != pdk_manifest(): raise ValueError('PDK identity changed')
    if sha(MODEL) != plan['model_sha256']: raise ValueError('model report changed')
    for rel,h in plan['source_files'].items():
        if sha(ROOT/rel)!=h: raise ValueError(f'source changed: {rel}')
    for rel,h in plan['snapshots'].items():
        if sha(camp/rel)!=h: raise ValueError(f'snapshot changed: {rel}')
    return plan


def checked_cases(camp):
    # case_output intentionally also accepts interrupted decks, but only after proving
    # their recorded deck corresponds exactly to a subset of this campaign's geometry.
    allowed={wm.name(c,k,v):(c,k,v) for c,k,v in POINTS}
    for run in [camp/NAME]+sorted(camp.glob(NAME+'.r[0-9]*')):
        if not run.exists(): continue
        text=(run/'tb.cir').read_text()
        names=re.findall(r'^write (\S+)',text,re.M)
        if not names or len(set(names))!=len(names) or any(n not in allowed for n in names): raise ValueError(f'untrusted run: {run}')
        expected=wm.deck('fs','hh',[allowed[n] for n in names],camp/'snap',4)
        if text!=expected: raise ValueError(f'deck identity differs: {run}')
        ex=run/'execution.json'
        if ex.exists() and json.loads(ex.read_text()).get('deck_sha256') != sha(run/'tb.cir'): raise ValueError(f'execution deck hash differs: {run}')
    return {wm.name(c,k,v):spice.case_output(camp,NAME,wm.name(c,k,v),wm.STOP) for c,k,v in POINTS}


def smoke_valid(run, deck):
    try:
        ex=json.loads((run/'execution.json').read_text())
        p=run/wm.name(*POINTS[0]); w=spice.Waves(p)
        return (ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and ex['deck_sha256']==sha(deck)
                and sha(run/'tb.cir')==sha(deck) and w.t[-1]>=1e-9*(1-1e-6)
                and 'v(v0p)' in w and 'v(v0n)' in w)
    except (OSError,ValueError,KeyError,IndexError): return False


def crossing(rows):
    if any(not math.isfinite(r['frequency_hz']) for r in rows):return None
    for a,b in zip(rows,rows[1:]):
        f0,f1=a['frequency_hz'],b['frequency_hz']
        if f0 != f1 and min(f0,f1)<=wm.TARGET<=max(f0,f1):
            return dict(vctrl=a['vctrl']+(wm.TARGET-f0)*(b['vctrl']-a['vctrl'])/(f1-f0),
                        kvco_hz_per_v=(f1-f0)/(b['vctrl']-a['vctrl']),bracket_v=[a['vctrl'],b['vctrl']])
    return None


def collect(camp,plan,paths):
    rows=[]
    for c,k,v in POINTS:
        p=paths[wm.name(c,k,v)];m=wm.measure(p) if p else None
        rows.append(dict(code=k,vctrl=v,path=str(p.relative_to(ROOT)) if p else None,
                         frequency_hz=float(m[0]) if m else None,swing_v=float(m[1]) if m else None))
    xs={str(k):crossing([r for r in rows if r['code']==k]) if all(r['frequency_hz'] is not None for r in rows if r['code']==k) else None for k in (0,1)}
    report=json.loads((camp/'sources/model_report.json').read_text())
    rec=report['chips']['fs_v1650:hh']['4']
    predicted={}
    for k in (0,1):
        item=next(s for s in rec['segments'] if s['code']==k and s['temperature']==[27,85])
        v0,v1=item['vctrl_endpoints'];predicted[str(k)]=v0+(v1-v0)*(38-27)/(85-27)
    room=None if xs['1'] is None else 1.21-xs['1']['vctrl']
    data=dict(scope=plan['scope'],spec_status='ungraded',points=rows,crossings=xs,
              model_at_38_vctrl=predicted,model_event_at_38_37=report['boundary_summary']['4']['minimum_opposite_room_event'],
              measured_minus_model_vctrl={str(k):None if xs[str(k)] is None else xs[str(k)]['vctrl']-predicted[str(k)] for k in (0,1)},
              h4_window_v=[.90,1.21],h4_code1_opposite_room_v=room,
              h4_room_minus_model_at_38_v=None if room is None else room-(1.21-predicted['1']),
              model_report_sha256=plan['model_sha256'])
    folder=camp/'analysis'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);folder.mkdir(parents=True)
    (folder/'summary.json').write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    print(folder/'summary.json')


def resume(camp):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan=verify(camp); active=watch.ngspice_cwds()
        if len(active)>=4 or any(p==camp or p.is_relative_to(camp) for p in active): raise RuntimeError('ngspice quota or campaign active')
        deck=camp/'prepared/smoke.cir'
        if not any(smoke_valid(p,deck) for p in [camp/'smoke']+list(camp.glob('smoke.r[0-9]*'))):
            run=spice.next_run_dir(camp,'smoke');spice.run(deck.read_text(),run,timeout_s=120,meta={'phase':'1ns_smoke_not_qualification'})
            if not smoke_valid(run,deck): raise RuntimeError(f'smoke failed: {run}')
        paths=checked_cases(camp)
        missing=[(c,k,v) for c,k,v in POINTS if paths[wm.name(c,k,v)] is None]
        if missing:
            text=wm.deck('fs','hh',missing,camp/'snap',4);run=spice.next_run_dir(camp,NAME)
            ex=spice.run(text,run,timeout_s=600,meta={'points':len(missing),'bank':4,'condition':C.tag,'passive':'hh'})
            if not ex.ok: print(f'deck failed or interrupted: {run}')
        paths=checked_cases(camp)
        collect(camp,plan,paths)
        if any(p is None for p in paths.values()): raise RuntimeError('incomplete cases; resume to fill')


def main():
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--check',type=Path);g.add_argument('--resume',type=Path)
    a=ap.parse_args()
    if a.prepare:print(prepare())
    elif a.check:verify(a.check.resolve());print('checkpoint valid; no ngspice')
    else:resume(a.resume.resolve())


if __name__=='__main__':main()
