"""Full RX transient from same-DUT direct-Newton DC soft hints.

No hard initial conditions; solver fallback disabled. Pilot is a prerequisite
for full analysis, not a functional pass. --resume requires registered seed BC.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import sys
import uuid

import numpy as np
import run as base
import full_short as short
import full_sparse_op as full
import full_dc_newton as dc
from serdes_flow import boundary, eye, spice, watch
from serdes_flow.corners import Condition

SOURCE=dc.OUT/'20261109T134022.118325Z_0e2ea2f8'
RUN=SOURCE/'full_dc_newton'
OUT=base.ROOT/'results/analog/rx/sampler/cold_readout_full_transient_dc'
BC='rx_fs_w40_full_direct_newton_dc_seed_v1'
ANALYSIS=base.ROOT/'analog/rx/sampler/tb/readout_deser/run.py'
CASES={'pilot':(1e-9,600),'full':(44.75e-9,1500)}
LANES=('a0','b0','ae1','be1','a1','b1','ae0','be0')
NODES=[f'{lane}_{i}' for lane in LANES for i in range(4)]+['w','vdd','xro.ckq','xro.ckqb','xro.ckm','xro.ckmb','xro.st_q','xro.st_qb','xro.st_m','xro.st_mb','xro.xwc.j0','xro.xwc.j1']+[f'xro.r{lane}' for lane in LANES]+['bias_vbg','vgi_bias','vbias','vctle','rxp','rxn','op','on','dp','dn','ep','en','d0p','d0n','d1p','d1n','rkp','rkn']
VECTORS=[f'v({n})' for n in NODES]+['i(vdd)','power']


def load_analysis():
    spec=importlib.util.spec_from_file_location('rx_readout_deser_analysis',ANALYSIS); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def deck_for(folder,oldplan,nodes,case):
    deck=dc.make_deck(folder,oldplan,nodes)
    body=deck.split('.control\n',1)[0]
    body='\n'.join(x for x in body.splitlines() if not x.startswith('.save '))+'\n'
    save='.save '+' '.join(f'v({n})' for n in NODES)+' i(vdd)'
    stop='1n' if case=='pilot' else '44.75n'
    control=[save,'.control','set num_threads=1','set filetype=binary','echo STAGE_DIRECT_NEWTON_ONLY',
             'optran 1 0 0 0 0 0','echo STAGE_BEFORE_TRAN','rusage',f'tran 2p {stop} 0 4p',
             'echo STAGE_TRAN_RETURNED','rusage','let power=-v(vdd)*i(vdd)',
             'write wave.raw '+' '.join(VECTORS),'echo STAGE_RAW_WRITTEN','quit','.endc','.end']
    return body+'\n'.join(control)+'\n'


def proposal(folder,nodesfile):
    return dict(id=BC,kind='numerical_initial_guess',description='Same full FS W40 direct-Newton DC solution used as soft transient operating-point guesses; not a physical startup condition.',
       upstream=dict(module='RX sampler/readout',run=str(RUN.relative_to(base.ROOT)),raw_sha256=base.sha(RUN/'op.raw'),deck_sha256=base.sha(RUN/'tb.cir'),execution_sha256=base.sha(RUN/'execution.json'),source_plan_sha256=base.sha(SOURCE/'plan.json')),
       nodes=dict(file=str(nodesfile.relative_to(base.ROOT)),sha256=base.sha(nodesfile),format='JSON list of node/value; voltage nodes only'),load=None,
       points={'fs_v1650_t-40':dict(condition='FS_hh 1.65 V -40 C full W40 PI20 trim32 rb2k real bias',replay_boundary=base.BC)},
       processing='all finite same-DUT DC v(...) vectors as soft nodeset; overlaps replace original six hints; no .ic/uic or clamps',
       validation=dict(state='ungraded',limitation='DC converged direct Newton, not physical startup or RX functional proof'),
       valid_while=['same full circuit, historical snapshot/PDK and t=0 sources','same node list and recorded source identity'])


def analysis_hashes():
    mod=load_analysis(); boundary.check_load(base.BC,mod.sp.replay.signature())
    paths={ANALYSIS}
    for m in list(sys.modules.values()):
        f=getattr(m,'__file__',None)
        if f:
            p=Path(f).resolve()
            if p.is_relative_to(base.ROOT) and p.suffix=='.py': paths.add(p)
    for obj in (mod.rd,mod.sp,mod.sp.link,mod.sp.replay):
        p=Path(obj.__file__).resolve(); paths.add(p)
    return {str(p):base.sha(p) for p in sorted(paths)}


def prepare():
    dc.verify(SOURCE,registered=True); oldplan=base.verify(short.OLD)
    ex=json.loads((RUN/'execution.json').read_text()); nodes=dc.entries(RUN/'op.raw'); details=dc.assess(RUN,json.loads((SOURCE/'seed_nodes.json').read_text()))
    if not(ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and ex['deck_sha256']==base.sha(RUN/'tb.cir')==base.sha(SOURCE/'prepared/full_dc_newton.cir') and details['raw_complete'] and details['optran_deselected'] and not details['any_fallback']): raise ValueError('source DC incomplete')
    hashes=analysis_hashes()
    folder=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]); folder.mkdir(parents=True,exist_ok=False)
    shutil.copytree(SOURCE/'snap',folder/'snap'); (folder/'prepared').mkdir(); nf=folder/'seed_nodes.json'; nf.write_text(json.dumps(nodes,indent=1,allow_nan=False)+'\n')
    for case in CASES: (folder/'prepared'/f'{case}.cir').write_text(deck_for(folder,oldplan,nodes,case))
    (folder/'seed_boundary_proposal.json').write_text(json.dumps(proposal(folder,nf),indent=2)+'\n')
    snapshots={str(p.relative_to(folder)):base.sha(p) for d in ('snap','prepared') for p in (folder/d).rglob('*') if p.is_file()}
    sources={str(p):base.sha(p) for p in (Path(__file__).resolve(),Path(base.__file__).resolve(),Path(short.__file__).resolve(),Path(full.__file__).resolve(),Path(dc.__file__).resolve(),SOURCE/'plan.json',RUN/'execution.json',RUN/'tb.cir',RUN/'op.raw')}
    plan=dict(scope='same full FS W40 RX; direct Newton DC hints; 1 ns pilot then 44.75 ns PRBS; no physical startup qualification',
      seed_bc=BC,seed_nodes_sha256=base.sha(nf),proposal_sha256=base.sha(folder/'seed_boundary_proposal.json'),node_count=len(nodes),
      cases={'pilot':{'t_end_s':1e-9,'timeout_s':600},'full':{'t_end_s':44.75e-9,'timeout_s':1500}},sources=sources,analysis_sources=hashes,snapshots=snapshots,
      replay_bc=base.BC,analysis='readout_deser.analyse with original eye.prbs7(link.NBITS), code20; fixed t_from = T0+(WARM+6)*UI = 12.5 ns through 44.75 ns; mapping, timing, clock and power; no changed stimulus',
      pilot_health='complete 0..1 ns, no solver fallback, vbg/vgi/vbias/vctle initial and final within 5% of direct-DC values and positive supplied power; numerical prerequisite only')
    (folder/'plan.json').write_text(json.dumps(plan,indent=2)+'\n'); return folder


def verify(folder,registered=False):
    plan=json.loads((folder/'plan.json').read_text()); dc.verify(SOURCE,registered=True); oldplan=base.verify(short.OLD)
    for path,h in {**plan['sources'],**plan['analysis_sources']}.items():
        if base.sha(path)!=h: raise ValueError(f'source changed: {path}')
    for path,h in plan['snapshots'].items():
        if base.sha(folder/path)!=h: raise ValueError(f'snapshot changed: {path}')
    nf=folder/'seed_nodes.json'; nodes=dc.entries(RUN/'op.raw'); bc=json.loads((folder/'seed_boundary_proposal.json').read_text())
    if base.sha(nf)!=plan['seed_nodes_sha256'] or json.loads(nf.read_text())!=nodes or len(nodes)!=plan['node_count'] or base.sha(folder/'seed_boundary_proposal.json')!=plan['proposal_sha256'] or bc!=proposal(folder,nf): raise ValueError('seed identity changed')
    for case in CASES:
        deck=deck_for(folder,oldplan,nodes,case)
        if deck!=(folder/'prepared'/f'{case}.cir').read_text() or re.search(r'^\s*\.ic\b|\buic\b',deck,re.I|re.M): raise ValueError('deck changed')
    if registered and boundary.get(BC)!=bc: raise ValueError('registered BC differs')
    return plan,nodes


def inspect(run,case,nodes):
    log=(run/'simulator.log').read_text(errors='replace') if (run/'simulator.log').exists() else ''
    info=dict(initial_solution='Initial Transient Solution' in log,tran_returned='STAGE_TRAN_RETURNED' in log,raw_written='STAGE_RAW_WRITTEN' in log,
              optran_deselected='Optran is deselected' in log,any_fallback=bool(re.search(r'Starting (?:dynamic gmin|true gmin|source stepping)|Transient op started',log,re.I)),
              raw_exists=(run/'wave.raw').exists(),start_s=None,endpoint_s=None,raw_complete=False,health=None)
    try:
        waves=spice.Waves(run/'wave.raw'); info['start_s']=float(waves.t[0]); info['endpoint_s']=float(waves.t[-1])
        info['raw_complete']=bool(abs(info['start_s'])<=1e-18 and abs(info['endpoint_s']-CASES[case][0])<=1e-15 and all(x in waves for x in VECTORS))
        if info['raw_complete']:
            seed={x['node']:x['value'] for x in nodes}; vals={}
            for node in ('bias_vbg','vgi_bias','vbias','vctle'):
                a=waves[f'v({node})']; vals[node]=dict(start=float(a[0]),end=float(a[-1]),reference=seed[node])
            power=waves['power']; healthy=all(abs(vals[n][k]-seed[n])<=0.05*abs(seed[n]) for n in vals for k in ('start','end')) and float(power[0])>0 and float(power[-1])>0
            info['health']=dict(numerical_bias_health=healthy,bias=vals,power_start_w=float(power[0]),power_end_w=float(power[-1]))
    except (OSError,ValueError,IndexError,KeyError): pass
    return info


def completed(folder,case,nodes):
    name='transient_'+case
    for run in reversed([folder/name]+sorted(folder.glob(name+'.r*'))):
        try:
            ex=json.loads((run/'execution.json').read_text()); info=inspect(run,case,nodes)
            if ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and base.sha(run/'tb.cir')==base.sha(folder/'prepared'/f'{case}.cir') and info['tran_returned'] and info['raw_written'] and info['raw_complete'] and info['optran_deselected'] and not info['any_fallback']: return run,info
        except (OSError,ValueError,KeyError): pass
    return None


def resume(folder,case):
    with (folder/f'.{case}.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); plan,nodes=verify(folder,registered=True)
        if case=='full':
            pilot=completed(folder,'pilot',nodes)
            if pilot is None or not pilot[1]['health']['numerical_bias_health']: raise ValueError('full requires complete healthy pilot')
        done=completed(folder,case,nodes)
        if done is None:
            if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice quota')
            run=spice.next_run_dir(folder,'transient_'+case); ex=spice.run((folder/'prepared'/f'{case}.cir').read_text(),run,timeout_s=CASES[case][1],meta=dict(case=case,bc=base.BC,seed_bc=BC,scope=plan['scope']))
            info=inspect(run,case,nodes); done=completed(folder,case,nodes)
        else: run,info=done
        row=dict(case=case,status='observed' if done else 'incomplete_or_numerical_failure',spec_status='ungraded',run=str(run.relative_to(base.ROOT)),stages=info,execution_sha256=base.sha(run/'execution.json'))
        if (run/'wave.raw').exists(): row['raw_sha256']=base.sha(run/'wave.raw')
        if case=='full' and done:
            try:
                mod=load_analysis(); boundary.check_load(base.BC,mod.sp.replay.signature()); c=Condition('fs',1.65,-40)
                row['readout_analysis']=mod.analyse(run/'wave.raw',c,20,eye.prbs7(mod.sp.link.NBITS))
                row['analysis_window_s']=[mod.sp.link.T0+(mod.sp.link.WARM+6)*mod.sp.link.UI,CASES['full'][0]]
            except (ValueError,IndexError,KeyError) as exc: row['analysis_error']=str(exc)
        dest=folder/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'); dest.mkdir(parents=True,exist_ok=False)
        (dest/'summary.json').write_text(json.dumps(dict(scope=plan['scope'],result=row),indent=2,allow_nan=False)+'\n'); print(dest)


def main():
    ap=argparse.ArgumentParser(description=__doc__); g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true'); g.add_argument('--check',type=Path); g.add_argument('--resume',type=Path); ap.add_argument('--case',choices=tuple(CASES),default='pilot'); a=ap.parse_args()
    if a.prepare: print(prepare())
    elif a.check: verify(a.check.resolve()); print('checkpoint valid; BC proposal not registered; no ngspice')
    else: resume(a.resume.resolve(),a.case)


if __name__=='__main__': main()
