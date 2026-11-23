"""Same full FS W40 RX: KLU 1 ns transient with bounded internal OPtran.

--prepare/--check do not simulate. Per-case --resume uses one worker and 600 s.
A short internal OPtran success is not a DC steady-state or functional pass;
compare bias, supply and clocks at start/end, then test longer dynamics.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re
import shutil
import uuid

import run as base
import full_short as short
from serdes_flow import spice, watch

OUT=base.ROOT/'results/analog/rx/sampler/cold_readout_full_optran'
CASES={'100ns':'100n','1us':'1u'}
MANUAL=Path('/home/host/.local/share/simple_serdes_build/ngspice47/ngspice-47/README.optran')
SOURCE=Path('/home/host/.local/share/simple_serdes_build/ngspice47/ngspice-47/src/spicelib/analysis/optran.c')
REPORT=base.ROOT/'docs/work_packages/deliveries/rx-optran-diagnostic.md'


def deck_for(folder,oldplan,case):
    deck=short.deck_for(folder,oldplan)
    marker='echo STAGE_BEFORE_TRAN\n'
    if deck.count(marker)!=1: raise ValueError('stage marker mismatch')
    return deck.replace(marker,f'echo STAGE_CONFIGURE_OPTRAN\noptran 1 1 1 1n {CASES[case]} 0\n'+marker,1)


def prepare():
    oldplan=base.verify(short.OLD)
    manual=MANUAL.read_text(); source=SOURCE.read_text()
    if 'optran 0 0 0 50u 10m 0' not in manual or 'opstepsize\n    opfinaltime\n    opramptime' not in source: raise ValueError('local OPtran documentation changed')
    folder=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]); folder.mkdir(parents=True,exist_ok=False)
    shutil.copytree(short.OLD/'snap',folder/'snap')
    (folder/'prepared').mkdir()
    for case in CASES: (folder/'prepared'/f'{case}.cir').write_text(deck_for(folder,oldplan,case))
    snapshots={str(p.relative_to(folder)):base.sha(p) for d in ('snap','prepared') for p in (folder/d).rglob('*') if p.is_file()}
    sources={str(p):base.sha(p) for p in (Path(__file__).resolve(),Path(base.__file__).resolve(),Path(short.__file__).resolve(),MANUAL,SOURCE,REPORT,short.OLD/'plan.json')}
    plan=dict(scope='full physical FS W40 RX; internal OPtran numerical comparison; real 1 ns transient only; observed/ungraded',
              warning='OPtran reaching its internal endpoint does not establish DC steady state, startup or functional pass. Compare bias/supply/clock start and end, then longer dynamics.',
              cases=CASES,command='optran 1 1 1 1n <tstop> 0: initial iteration, gmin, source stepping, internal step, internal stop, ramp',
              comparison='Both cases use 1 ns internal maximum step; internal endpoint 100 ns versus 1 us. Default unseeded 10 us used 100 ns step and is not a one-variable comparison.',
              physical='exact historical full deck, real bias, FS_hh 1.65 V -40 C PI20 trim32 rb2k W40; original six nodeset hints and t=0 Ikick; no 695-hint BC, no .ic/uic',
              bc=base.BC,tran='tran 2p 1n 0 4p; KLU; binary raw; 600 s/case',sources=sources,snapshots=snapshots)
    (folder/'plan.json').write_text(json.dumps(plan,indent=2)+'\n'); return folder


def verify(folder):
    plan=json.loads((folder/'plan.json').read_text()); oldplan=base.verify(short.OLD)
    for path,digest in plan['sources'].items():
        if base.sha(path)!=digest: raise ValueError(f'source changed: {path}')
    for path,digest in plan['snapshots'].items():
        if base.sha(folder/path)!=digest: raise ValueError(f'snapshot changed: {path}')
    for case in CASES:
        deck=deck_for(folder,oldplan,case)
        if deck!=(folder/'prepared'/f'{case}.cir').read_text() or deck.count('.nodeset ')!=1 or re.search(r'^\s*\.ic\b|\buic\b',deck,re.I|re.M): raise ValueError('deck or initial conditions changed')
    a=deck_for(folder,oldplan,'100ns').replace('optran 1 1 1 1n 100n 0','optran 1 1 1 1n STOP 0')
    b=deck_for(folder,oldplan,'1us').replace('optran 1 1 1 1n 1u 0','optran 1 1 1 1n STOP 0')
    if a!=b: raise ValueError('case differences exceed OPtran stop')
    return plan


def assess(run):
    info=short.assess(run)
    info['endpoints']={}
    if info['raw_complete']:
        waves=spice.Waves(run/'short.raw')
        for vector in short.VECTORS:
            data=waves[vector]
            info['endpoints'][vector]={'start':float(data[0]),'end':float(data[-1])}
    return info


def resume_case(folder,case,plan):
    with (folder/f'.{case}.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        name='optran_'+case; complete=None
        if any(p.parent == folder and (p.name == name or p.name.startswith(name + '.r'))
               for p in watch.ngspice_cwds()):
            raise RuntimeError('case already has an active ngspice process')
        for run in reversed([folder/name]+sorted(folder.glob(name+'.r*'))):
            try:
                ex=json.loads((run/'execution.json').read_text()); details=assess(run)
                if ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and base.sha(run/'tb.cir')==base.sha(folder/'prepared'/f'{case}.cir') and details['tran_returned'] and details['raw_written'] and details['raw_complete']:
                    complete=(run,details); break
            except (OSError,ValueError,KeyError): pass
        if complete is None:
            if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice quota')
            run=spice.next_run_dir(folder,name)
            ex=spice.run((folder/'prepared'/f'{case}.cir').read_text(),run,timeout_s=600,meta={'case':case,'bc':base.BC,'solver':'klu','scope':plan['scope']})
            details=assess(run)
            if ex.ok and details['tran_returned'] and details['raw_written'] and details['raw_complete']: complete=(run,details)
        row=dict(case=case,status='observed' if complete else 'incomplete_or_numerical_failure',spec_status='ungraded',run=str(run.relative_to(base.ROOT)),stages=details,execution_sha256=base.sha(run/'execution.json'))
        if (run/'short.raw').exists(): row['raw_sha256']=base.sha(run/'short.raw')
        dest=folder/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'); dest.mkdir(parents=True,exist_ok=False)
        (dest/'summary.json').write_text(json.dumps(dict(scope=plan['scope'],warning=plan['warning'],result=row),indent=2,allow_nan=False)+'\n'); print(dest)


def main():
    ap=argparse.ArgumentParser(description=__doc__); g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true'); g.add_argument('--check',type=Path); g.add_argument('--resume',type=Path)
    ap.add_argument('--case',choices=tuple(CASES))
    a=ap.parse_args()
    if a.prepare: print(prepare())
    elif a.check: verify(a.check.resolve()); print('checkpoint valid; no ngspice')
    else:
        folder=a.resume.resolve(); plan=verify(folder)
        for case in ([a.case] if a.case else CASES): resume_case(folder,case,plan)


if __name__=='__main__': main()
