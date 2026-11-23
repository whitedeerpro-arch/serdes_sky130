"""Independent direct-Newton DC attempt seeded by same-DUT OPtran raw voltages.

Soft numerical hints are not clamps. Disable gmin/source/OPtran; a converged
nearby root is independent evidence, not a residual evaluation of the input.
--resume requires exact numerical-initial-guess BC registration beforehand.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import math
from pathlib import Path
import re
import shutil
import uuid

import numpy as np
import run as base
import full_short as short
import full_sparse_op as full
from serdes_flow import boundary, spice, watch

SOURCE=full.OUT/'20261109T133404.020641Z_42c4ada0'
RUN=SOURCE/'full_sparse_op'
OUT=base.ROOT/'results/analog/rx/sampler/cold_readout_full_dc_newton'
BC='rx_fs_w40_full_optran_raw_newton_seed_v1'
NODES=re.compile(r'^[a-z0-9_.:#]+$')


def entries(raw):
    names,data=spice.read_raw(raw)
    if data.shape!=(1,len(names)) or not np.isfinite(data).all(): raise ValueError('invalid source raw')
    out=[]; seen=set()
    for i,name in enumerate(names):
        if not (name.startswith('v(') and name.endswith(')')): continue
        node=name[2:-1]
        if not NODES.fullmatch(node) or node in seen: raise ValueError(f'unsupported/duplicate node {node}')
        seen.add(node); out.append(dict(node=node,value=float(data[0,i])))
    if not {'bias_vbg','vgi_bias','xbias_ref.xbg.s','xbias_ref.vg','xbias_ref.xbg.ta','xbias_ref.xbg.tb'} <= seen: raise ValueError('original hint nodes absent')
    return out


def make_deck(folder,oldplan,nodes):
    deck=full.deck_for(folder,oldplan)
    body,ctrl=deck.split('.control\n',1)
    lines=body.splitlines(); old=[x for x in lines if x.lower().startswith('.nodeset ')]
    if len(old)!=1: raise ValueError('original hint mismatch')
    lines=[x for x in lines if not x.lower().startswith('.nodeset ')]
    lines+=['* nodeset soft guesses from same-DUT recorded OPtran raw']+[f'.nodeset v({x["node"]})={x["value"]:.17g}' for x in nodes]
    ctrl=ctrl.replace('echo STAGE_BEFORE_OP\n','echo STAGE_DIRECT_NEWTON_ONLY\noptran 1 0 0 0 0 0\necho STAGE_BEFORE_OP\n',1)
    return '\n'.join(lines)+'\n.control\n'+ctrl


def bc_proposal(folder,nodesfile):
    ex=json.loads((RUN/'execution.json').read_text())
    return dict(id=BC,kind='numerical_initial_guess',description='Soft guesses from same full FS W40 circuit OPtran raw; direct Newton comparison only; not a DC or functional qualification.',
      upstream=dict(module='RX sampler/readout',run=str(RUN.relative_to(base.ROOT)),raw_sha256=base.sha(RUN/'op.raw'),deck_sha256=base.sha(RUN/'tb.cir'),execution_sha256=base.sha(RUN/'execution.json'),
                    execution_deck_sha256=ex['deck_sha256'],source_plan_sha256=base.sha(SOURCE/'plan.json')),
      nodes=dict(file=str(nodesfile.relative_to(base.ROOT)),sha256=base.sha(nodesfile),format='JSON list of node/value; voltage nodes only'),
      load=None,points={'fs_v1650_t-40':dict(condition='FS_hh 1.65 V -40 C full W40 PI20 trim32 rb2k real bias',replay_boundary=base.BC)},
      processing='all finite v(...) vectors copied as soft .nodeset; original six overlapping hints replaced, never .ic/uic or clamped',
      validation=dict(state='ungraded',limitation='source is an internal OPtran endpoint, not an established DC solution; candidate and converged root comparison does not directly evaluate original residual'),
      valid_while=['same full deck, stimulus, historical cell/PDK identities and numerical node list','same t=0 and load'])


def prepare():
    sourceplan=full.verify(SOURCE); oldplan=base.verify(short.OLD)
    ex=json.loads((RUN/'execution.json').read_text()); stats=full.assess(RUN)
    if not(ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and ex['deck_sha256']==base.sha(RUN/'tb.cir')==base.sha(SOURCE/'prepared/full_sparse_op.cir') and stats['raw_complete'] and stats['optran_finished']): raise ValueError('source full candidate incomplete')
    nodes=entries(RUN/'op.raw')
    folder=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]); folder.mkdir(parents=True,exist_ok=False)
    shutil.copytree(SOURCE/'snap',folder/'snap'); (folder/'prepared').mkdir()
    nodesfile=folder/'seed_nodes.json'; nodesfile.write_text(json.dumps(nodes,indent=1,allow_nan=False)+'\n')
    (folder/'prepared/full_dc_newton.cir').write_text(make_deck(folder,oldplan,nodes))
    bc=bc_proposal(folder,nodesfile); (folder/'seed_boundary_proposal.json').write_text(json.dumps(bc,indent=2)+'\n')
    snapshots={str(p.relative_to(folder)):base.sha(p) for d in ('snap','prepared') for p in (folder/d).rglob('*') if p.is_file()}
    plan=dict(scope='same full physical RX direct Newton DC attempt from soft OPtran hints; observed/ungraded; nearby DC root is not original residual',
              bc=BC,node_count=len(nodes),seed_nodes_sha256=base.sha(nodesfile),proposal_sha256=base.sha(folder/'seed_boundary_proposal.json'),
              source_plan_sha256=base.sha(SOURCE/'plan.json'),source_raw_sha256=base.sha(RUN/'op.raw'),
              source_runner_sha256=base.sha(full.__file__),base_runner_sha256=base.sha(base.__file__),this_runner_sha256=base.sha(__file__),
              analysis='SPARSE op; optran 1 0 0 0 0 0: initial Newton enabled, gmin/source/OPtran disabled; 240 s',
              snapshots=snapshots)
    (folder/'plan.json').write_text(json.dumps(plan,indent=2)+'\n'); return folder


def verify(folder,registered=False):
    plan=json.loads((folder/'plan.json').read_text()); full.verify(SOURCE); oldplan=base.verify(short.OLD)
    if base.sha(SOURCE/'plan.json')!=plan['source_plan_sha256'] or base.sha(RUN/'op.raw')!=plan['source_raw_sha256'] or base.sha(full.__file__)!=plan['source_runner_sha256'] or base.sha(base.__file__)!=plan['base_runner_sha256'] or base.sha(__file__)!=plan['this_runner_sha256']: raise ValueError('source identity changed')
    for path,digest in plan['snapshots'].items():
        if base.sha(folder/path)!=digest: raise ValueError(f'snapshot changed: {path}')
    nodes=entries(RUN/'op.raw'); file=folder/'seed_nodes.json'; bc=json.loads((folder/'seed_boundary_proposal.json').read_text())
    if base.sha(file)!=plan['seed_nodes_sha256'] or json.loads(file.read_text())!=nodes or len(nodes)!=plan['node_count'] or base.sha(folder/'seed_boundary_proposal.json')!=plan['proposal_sha256'] or bc!=bc_proposal(folder,file): raise ValueError('BC or seed changed')
    deck=make_deck(folder,oldplan,nodes)
    if deck!=(folder/'prepared/full_dc_newton.cir').read_text() or re.search(r'^\s*\.ic\b|\buic\b',deck,re.I|re.M): raise ValueError('deck changed')
    if registered and boundary.get(BC)!=bc: raise ValueError('registered BC differs')
    return plan


def assess(run,nodes):
    info=full.assess(run); log=(run/'simulator.log').read_text(errors='replace') if (run/'simulator.log').exists() else ''
    info.update(direct_configured='STAGE_DIRECT_NEWTON_ONLY' in log,optran_deselected='Optran is deselected' in log,any_fallback=bool(re.search(r'Starting (?:dynamic gmin|true gmin|source stepping)|Transient op started',log,re.I)),comparison=None)
    if info['raw_complete']:
        names,data=spice.read_raw(run/'op.raw'); values={n[2:-1]:float(data[0,i]) for i,n in enumerate(names) if n.startswith('v(') and n.endswith(')')}
        if not all(x['node'] in values and math.isfinite(values[x['node']]) for x in nodes): raise ValueError('missing result node')
        diffs={x['node']:values[x['node']]-x['value'] for x in nodes}; worst=max(diffs,key=lambda n:abs(diffs[n]))
        info['comparison']=dict(max_abs_v=abs(diffs[worst]),max_node=worst,bias_delta_v={k:diffs[k] for k in ('bias_vbg','vgi_bias','vbias','vctle')})
    return info


def resume(folder):
    with (folder/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); plan=verify(folder,registered=True); nodes=json.loads((folder/'seed_nodes.json').read_text()); name='full_dc_newton'; complete=None
        for run in reversed([folder/name]+sorted(folder.glob(name+'.r*'))):
            try:
                ex=json.loads((run/'execution.json').read_text()); details=assess(run,nodes)
                if ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and base.sha(run/'tb.cir')==base.sha(folder/'prepared/full_dc_newton.cir') and details['op_returned'] and details['raw_written'] and details['raw_complete'] and details['optran_deselected'] and not details['any_fallback']:
                    complete=(run,details); break
            except (OSError,ValueError,KeyError): pass
        if complete is None:
            if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice quota')
            run=spice.next_run_dir(folder,name); ex=spice.run((folder/'prepared/full_dc_newton.cir').read_text(),run,timeout_s=240,meta=dict(bc=base.BC,seed_bc=BC,scope=plan['scope']))
            details=assess(run,nodes)
            if ex.ok and details['op_returned'] and details['raw_written'] and details['raw_complete'] and details['optran_deselected'] and not details['any_fallback']: complete=(run,details)
        row=dict(status='observed_direct_newton' if complete else 'incomplete_or_numerical_failure',spec_status='ungraded',run=str(run.relative_to(base.ROOT)),stages=details,execution_sha256=base.sha(run/'execution.json'))
        if (run/'op.raw').exists(): row['raw_sha256']=base.sha(run/'op.raw')
        dest=folder/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'); dest.mkdir(parents=True,exist_ok=False)
        (dest/'summary.json').write_text(json.dumps(dict(scope=plan['scope'],result=row),indent=2,allow_nan=False)+'\n'); print(dest)


def main():
    ap=argparse.ArgumentParser(description=__doc__); g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true'); g.add_argument('--check',type=Path); g.add_argument('--resume',type=Path); a=ap.parse_args()
    if a.prepare: print(prepare())
    elif a.check: verify(a.check.resolve()); print('checkpoint valid; BC proposal not registered; no ngspice')
    else: resume(a.resume.resolve())


if __name__=='__main__': main()
