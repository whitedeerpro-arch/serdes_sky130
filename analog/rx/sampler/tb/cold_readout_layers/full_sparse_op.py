"""Full historical FS W40 readout, ordinary SPARSE OP with all-node binary raw.

Only --resume runs ngspice; 600 s, one worker. OPtran fallback may return a
transient state rather than a DC root: record the solver path, never grade pass.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re
import shutil
import uuid
import numpy as np

import run as base
import full_short as short
from serdes_flow import spice, watch

OUT=base.ROOT/'results/analog/rx/sampler/cold_readout_full_sparse_op'
DEVICE_CURRENTS=['@m.xref.xd.xmos.msky130_fd_pr__nfet_01v8[id]', '@m.xcbias.xmos.msky130_fd_pr__nfet_01v8_lvt[id]']
REQUIRED=['v(bias_vbg)','v(vgi_bias)','v(vbias)','v(vctle)','v(xro.ckq)','v(xro.xwc.j0)','i(vdd)']


def deck_for(folder,oldplan):
    includes={src:str(Path('snap/cells')/Path(src).relative_to(base.SOURCE/'pdk_resistors')) for src in oldplan['includes']}
    deck,removed,_=base.make_deck(folder,base.ORIGINAL.read_text(),3,'sparse',includes)
    if removed: raise ValueError('full circuit changed')
    body=deck.split('.control',1)[0]
    control=['.save all '+' '.join(DEVICE_CURRENTS),'.control','set num_threads=1','set filetype=binary',
             'echo STAGE_BEFORE_OP','rusage','op','echo STAGE_OP_RETURNED','rusage',
             'write op.raw all','echo STAGE_RAW_WRITTEN','quit','.endc','.end']
    return body+'\n'.join(control)+'\n'


def prepare():
    oldplan=base.verify(short.OLD)
    folder=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]); folder.mkdir(parents=True,exist_ok=False)
    shutil.copytree(short.OLD/'snap',folder/'snap'); (folder/'prepared').mkdir()
    (folder/'prepared/full_sparse_op.cir').write_text(deck_for(folder,oldplan))
    snapshots={str(p.relative_to(folder)):base.sha(p) for d in ('snap','prepared') for p in (folder/d).rglob('*') if p.is_file()}
    prior=short.OLD/'readout_sparse'
    plan=dict(scope='FS_hh 1.65 V -40 C full readout W40; ordinary SPARSE OP; 600 seconds; observed/ungraded',
              warning='If solver uses OPtran fallback the returned vector may be a pseudo-transient state; independently verify DC residual and stability before calling it a DC solution.',
              physical='same historical full circuit, real bias, PI20 trim32 rb2k, original six nodeset hints, original t0 sources/kick; no .ic/uic',
              boundary=base.BC,source_hashes={str(p):base.sha(p) for p in (Path(__file__).resolve(),Path(base.__file__).resolve(),Path(short.__file__).resolve(),short.OLD/'plan.json')},
              original_120s=dict(execution_sha256=base.sha(prior/'execution.json'),log_sha256=base.sha(prior/'simulator.log'),run=str(prior)),
              output='binary op.raw with save all and explicit CML/CTLE diode currents, simulator log and execution',snapshots=snapshots)
    (folder/'plan.json').write_text(json.dumps(plan,indent=2)+'\n'); return folder


def verify(folder):
    plan=json.loads((folder/'plan.json').read_text()); oldplan=base.verify(short.OLD)
    for path,digest in plan['source_hashes'].items():
        if base.sha(path)!=digest: raise ValueError(f'source changed: {path}')
    for path,digest in plan['snapshots'].items():
        if base.sha(folder/path)!=digest: raise ValueError(f'snapshot changed: {path}')
    prior=short.OLD/'readout_sparse'
    if base.sha(prior/'execution.json')!=plan['original_120s']['execution_sha256'] or base.sha(prior/'simulator.log')!=plan['original_120s']['log_sha256']: raise ValueError('prior reference changed')
    deck=deck_for(folder,oldplan)
    if deck!=(folder/'prepared/full_sparse_op.cir').read_text() or deck.count('.nodeset ')!=1 or re.search(r'^\s*\.ic\b|\buic\b',deck,re.I|re.M): raise ValueError('deck changed or unexpected initial condition')
    return plan


def assess(run):
    log=(run/'simulator.log').read_text(errors='replace') if (run/'simulator.log').exists() else ''
    info=dict(before_op='STAGE_BEFORE_OP' in log,op_returned='STAGE_OP_RETURNED' in log,raw_written='STAGE_RAW_WRITTEN' in log,
              optran_started='Transient op started' in log,optran_finished='Transient op finished successfully' in log,
              raw_exists=(run/'op.raw').exists(),raw_complete=False,vector_count=None,point_count=None,values={})
    try:
        names,data=spice.read_raw(run/'op.raw'); lower=[x.lower() for x in names]
        info.update(vector_count=len(names),point_count=len(data))
        required=all(x in lower for x in REQUIRED) and all(f'i({x.lower()})' in lower for x in DEVICE_CURRENTS)
        info['raw_complete']=bool(required and len(data)==1 and np.all(np.isfinite(data)))
        if info['raw_complete']:
            info['values']={n:float(data[0,lower.index(n.lower())]) for n in REQUIRED}
            info['values'].update({n:float(data[0,lower.index(f'i({n.lower()})')]) for n in DEVICE_CURRENTS})
    except (OSError,ValueError,IndexError,KeyError): pass
    return info


def resume(folder):
    with (folder/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); plan=verify(folder); name='full_sparse_op'; complete=None
        for run in reversed([folder/name]+sorted(folder.glob(name+'.r*'))):
            try:
                ex=json.loads((run/'execution.json').read_text()); details=assess(run)
                if ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and base.sha(run/'tb.cir')==base.sha(folder/'prepared/full_sparse_op.cir') and details['op_returned'] and details['raw_written'] and details['raw_complete']:
                    complete=(run,details); break
            except (OSError,ValueError,KeyError): pass
        if complete is None:
            if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice quota')
            run=spice.next_run_dir(folder,name); ex=spice.run((folder/'prepared/full_sparse_op.cir').read_text(),run,timeout_s=600,meta=dict(bc=base.BC,solver='sparse',scope=plan['scope']))
            details=assess(run)
            if ex.ok and details['op_returned'] and details['raw_written'] and details['raw_complete']: complete=(run,details)
        row=dict(status='observed' if complete else 'incomplete_or_numerical_failure',spec_status='ungraded',run=str(run.relative_to(base.ROOT)),stages=details,execution_sha256=base.sha(run/'execution.json'))
        if (run/'op.raw').exists(): row['raw_sha256']=base.sha(run/'op.raw')
        dest=folder/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'); dest.mkdir(parents=True,exist_ok=False)
        (dest/'summary.json').write_text(json.dumps(dict(scope=plan['scope'],warning=plan['warning'],result=row),indent=2,allow_nan=False)+'\n'); print(dest)


def main():
    ap=argparse.ArgumentParser(description=__doc__); g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true'); g.add_argument('--check',type=Path); g.add_argument('--resume',type=Path); a=ap.parse_args()
    if a.prepare: print(prepare())
    elif a.check: verify(a.check.resolve()); print('checkpoint valid; no ngspice')
    else: resume(a.resume.resolve())


if __name__=='__main__': main()
