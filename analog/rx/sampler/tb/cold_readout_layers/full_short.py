"""Fixed historical FS W40 full RX: one 1 ns transient, no functional grading.

--prepare and --check never invoke ngspice; --resume is single-worker KLU.
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
from serdes_flow import spice, watch

OLD = base.OUT/'20261109T083205.422134Z_5cb6b16b'
OUT = base.ROOT/'results/analog/rx/sampler/cold_readout_full_short'
NODES = ['bias_vbg','vgi_bias','vbias','vctle','vdd','rxp','rxn','op','on',
         'dp','dn','ep','en','d0p','d0n','d1p','d1n','rkp','rkn',
         'xro.ckq','xro.ckqb','xro.ckm','xro.ckmb','xro.xwc.j0','xro.xwc.j1',
         'w','a0_0','a0_1','a0_2','a0_3']
VECTORS = [f'v({n})' for n in NODES]+['i(vdd)']


def deck_for(folder, oldplan):
    includes = {src:str(Path('snap/cells')/Path(src).relative_to(base.SOURCE/'pdk_resistors')) for src in oldplan['includes']}
    deck,removed,_ = base.make_deck(folder,base.ORIGINAL.read_text(),3,'klu',includes)
    if removed: raise ValueError('full physical circuit lost instances')
    body = deck.split('.control',1)[0]
    control = ['.save '+' '.join(VECTORS),'.control','set num_threads=1','set filetype=binary',
               'echo STAGE_BEFORE_TRAN','rusage','tran 2p 1n 0 4p',
               'echo STAGE_TRAN_RETURNED','rusage','write short.raw '+' '.join(VECTORS),
               'echo STAGE_RAW_WRITTEN','quit','.endc','.end']
    return body+'\n'.join(control)+'\n'


def prepare():
    oldplan = base.verify(OLD)
    archive = OLD/'execution/run.py'
    if base.sha(archive) != oldplan['source_sha256'][str(Path(base.__file__).resolve())]: raise ValueError('original runner archive mismatch')
    folder = OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    shutil.copytree(OLD/'snap',folder/'snap')
    deck = deck_for(folder,oldplan)
    (folder/'prepared').mkdir(); (folder/'prepared/full_short.cir').write_text(deck)
    snapshots = {str(p.relative_to(folder)):base.sha(p) for d in ('snap','prepared') for p in (folder/d).rglob('*') if p.is_file()}
    plan = dict(scope='full physical RX FS 1.65 V -40 C hh; 1 ns transient completion only, observed/ungraded; no eye, mapping or startup qualification',
                source_campaign=str(OLD),source_plan_sha256=base.sha(OLD/'plan.json'),
                source_runner_archive_sha256=base.sha(archive),this_runner_sha256=base.sha(__file__),
                boundary_id=base.BC,condition='FS_hh 1.65 V -40 C; PI20 trim32 rb2k W40; real bias',
                hints='original six-node nodeset only; no added nodeset, .ic or uic',
                stimulus='original replay and PI at t=0, original 1 uA readout Ikick',
                analysis='tran 2p 1n 0 4p; KLU; 600 s timeout; single worker',
                saved_vectors=VECTORS, snapshots=snapshots,
                original_log='results/analog/rx/sampler/readout_deser/20261105T195801Z_ac_trim32_realbias_rhh/fs_v1650_t-40/simulator.log:1804-1814: KLU; dynamic/true gmin and source stepping failed, transient op finished successfully, initial solution printed; no completed transient raw')
    (folder/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    return folder


def verify(folder):
    plan=json.loads((folder/'plan.json').read_text()); oldplan=base.verify(OLD)
    if base.sha(OLD/'plan.json')!=plan['source_plan_sha256'] or base.sha(OLD/'execution/run.py')!=plan['source_runner_archive_sha256'] or base.sha(__file__)!=plan['this_runner_sha256']: raise ValueError('source identity changed')
    for path,digest in plan['snapshots'].items():
        if base.sha(folder/path)!=digest: raise ValueError(f'snapshot changed: {path}')
    deck=deck_for(folder,oldplan)
    if deck!=(folder/'prepared/full_short.cir').read_text(): raise ValueError('deck changed')
    if deck.count('.nodeset ')!=1 or re.search(r'^\s*\.ic\b|\buic\b',deck,re.I|re.M): raise ValueError('unexpected initial condition')
    return plan


def assess(run):
    log=(run/'simulator.log').read_text(errors='replace') if (run/'simulator.log').exists() else ''
    info=dict(before_tran='STAGE_BEFORE_TRAN' in log,initial_solution='Initial Transient Solution' in log,
              transient_op_success='Transient op finished successfully' in log,
              tran_returned='STAGE_TRAN_RETURNED' in log,raw_written='STAGE_RAW_WRITTEN' in log,
              raw_exists=(run/'short.raw').exists(),endpoint_s=None,start_s=None,raw_complete=False)
    try:
        waves=spice.Waves(run/'short.raw')
        info.update(start_s=float(waves.t[0]),endpoint_s=float(waves.t[-1]))
        info['raw_complete']=(abs(info['start_s'])<=1e-18 and abs(info['endpoint_s']-1e-9)<=1e-15 and all(v in waves for v in VECTORS))
    except (OSError,ValueError,IndexError,KeyError): pass
    return info


def resume(folder):
    with (folder/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); plan=verify(folder)
        if any(p==folder or p.is_relative_to(folder) for p in watch.ngspice_cwds()): raise ValueError('campaign active')
        complete=None
        for run in reversed([folder/'full_short']+sorted(folder.glob('full_short.r*'))):
            try:
                ex=json.loads((run/'execution.json').read_text()); details=assess(run)
                if ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and base.sha(run/'tb.cir')==base.sha(folder/'prepared/full_short.cir') and details['tran_returned'] and details['raw_written'] and details['raw_complete']:
                    complete=(run,details); break
            except (OSError,ValueError,KeyError): pass
        if complete is None:
            if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice quota')
            run=spice.next_run_dir(folder,'full_short')
            ex=spice.run((folder/'prepared/full_short.cir').read_text(),run,timeout_s=600,meta={'bc':base.BC,'solver':'klu','scope':plan['scope']})
            details=assess(run)
            if ex.ok and details['tran_returned'] and details['raw_written'] and details['raw_complete']: complete=(run,details)
        row=dict(status='observed' if complete else 'incomplete_or_numerical_failure',spec_status='ungraded',
                 run=str(run.relative_to(base.ROOT)),stages=details,execution_sha256=base.sha(run/'execution.json'))
        if (run/'short.raw').exists(): row['raw_sha256']=base.sha(run/'short.raw')
        dest=folder/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'); dest.mkdir(parents=True,exist_ok=False)
        (dest/'summary.json').write_text(json.dumps(dict(scope=plan['scope'],result=row),indent=2,allow_nan=False)+'\n'); print(dest)


def main():
    ap=argparse.ArgumentParser(description=__doc__); g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true'); g.add_argument('--check',type=Path); g.add_argument('--resume',type=Path)
    a=ap.parse_args()
    if a.prepare: print(prepare())
    elif a.check: verify(a.check.resolve()); print('checkpoint valid; no ngspice')
    else: resume(a.resume.resolve())


if __name__=='__main__': main()
