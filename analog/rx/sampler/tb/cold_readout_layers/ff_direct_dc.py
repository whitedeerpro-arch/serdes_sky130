"""FF W40 independent direct-Newton DC from the same-DUT ordinary OP candidate.

Prepare/check are read-only with respect to existing results; resume is a
single-worker 600 s SPARSE OP attempt. An OPtran candidate is not a DC root.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

import numpy as np
from serdes_flow import boundary, project, spice, watch

ROOT=project.ROOT
SELF=Path(__file__).resolve()
PARENT=ROOT/'results/analog/rx/sampler/cold_readout_ff_current/20261110T125113.199628Z_8f15432e'
UPSTREAM=PARENT/'ff_op'
OUT=ROOT/'results/analog/rx/sampler/cold_readout_ff_direct_dc'
BC='rx_ff_w40_optran_newton_seed_v1'
REPLAY='rx_c2_far_nominal@ctle_rc'
NODE_RE=re.compile(r'^[a-z0-9_.:#]+$')
RUNTIME=[SELF,Path(spice.__file__).resolve(),Path(project.__file__).resolve(),Path(watch.__file__).resolve(),Path(boundary.__file__).resolve(),ROOT/'config/pdk.toml',ROOT/'config/tools.toml']


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def entries(path):
    names,data=spice.read_raw(path)
    if data.shape!=(1,len(names)) or not np.isfinite(data).all():raise ValueError('candidate OP raw incomplete/nonfinite')
    result=[];seen=set()
    for i,name in enumerate(names):
        if not(name.startswith('v(') and name.endswith(')')):continue
        node=name[2:-1]
        if not NODE_RE.fullmatch(node) or node in seen:raise ValueError(f'invalid node: {node}')
        seen.add(node);result.append({'node':node,'value':float(data[0,i])})
    if not {'bias_vbg','vgi_bias','vbias','vctle','xro.ckq','xro.xwc.j0'}<=seen:raise ValueError('required nodes missing')
    return result


def check_candidate(raw,deck,execution,log,parent_deck):
    ex=json.loads(execution.read_text());text=log.read_text(errors='replace')
    if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=sha(deck) or sha(deck)!=sha(parent_deck):raise ValueError('candidate execution/deck mismatch')
    if ex['bc']!=REPLAY or not all(x in text for x in ('STAGE_BEFORE_OP','STAGE_OP_RETURNED','STAGE_RAW_WRITTEN')):raise ValueError('candidate boundary/stage missing')
    return entries(raw)


def make_deck(c,nodes):
    parent=(c/'upstream/tb.cir').read_text()
    body=parent.split('.control',1)[0]
    old=str(PARENT/'snap')+'/';new=str(c/'snap')+'/'
    if old not in body:raise ValueError('upstream snapshot paths missing')
    body=body.replace(old,new)
    lines=body.splitlines(); oldsets=[x for x in lines if x.lower().startswith('.nodeset ')]
    if len(oldsets)!=1:raise ValueError('expected six-node upstream hint')
    lines=[x for x in lines if not x.lower().startswith(('.nodeset ','.save '))]
    lines+=['* all same-FF OP voltages are soft hints; not a DC residual proof']+[f'.nodeset v({x["node"]})={x["value"]:.17g}' for x in nodes]
    text='\n'.join(lines)+'''\n.save all
.control
set num_threads=1
set filetype=binary
echo STAGE_DIRECT_NEWTON_ONLY
optran 1 0 0 0 0 0
echo STAGE_BEFORE_OP
op
echo STAGE_OP_RETURNED
write op.raw all
echo STAGE_RAW_WRITTEN
quit
.endc
.end
'''
    if re.search(r'^\s*\.ic\b|\buic\b',text,re.I|re.M):raise ValueError('hard initial condition')
    return text


def proposal(c,nodes):
    return {'id':BC,'kind':'numerical_initial_guess','description':'All finite voltage nodes from same-FF W40 ordinary-OP OPtran candidate, soft guesses for independent Newton; not a DC root or physical startup.',
            'upstream':{'module':'RX sampler/readout','run':str(UPSTREAM.relative_to(ROOT)),
                        'raw_sha256':sha(c/'upstream/op.raw'),'deck_sha256':sha(c/'upstream/tb.cir'),
                        'execution_sha256':sha(c/'upstream/execution.json'),'source_plan_sha256':sha(c/'upstream/parent_plan.json')},
            'nodes':{'file':str((c/'seed_nodes.json').relative_to(ROOT)),'sha256':sha(c/'seed_nodes.json'),'format':'JSON list of node/value; voltage nodes only'},
            'load':None,'points':{'ff_v1950_t-40':{'condition':'FF_hh 1.95 V -40 C full W40 PI20 trim32 rb2k real bias','replay_boundary':REPLAY}},
            'processing':'all finite same-DUT OP voltages as soft .nodeset; replace original six guesses; no .ic/uic',
            'validation':{'state':'ungraded','limitation':'OPtran candidate can be transient state; independent Newton required; no physical startup proof'},
            'valid_while':['same full FF circuit, replay, PDK, load, t=0 and numerical node list']}


def prepare():
    p=json.loads((PARENT/'plan.json').read_text())
    for path,h in p['source_sha256'].items():
        if sha(path)!=h:raise ValueError(f'parent source changed: {path}')
    for path,h in p['pdk_sha256'].items():
        if sha(path)!=h:raise ValueError(f'parent PDK changed: {path}')
    for path,h in p['snapshots'].items():
        if sha(PARENT/path)!=h:raise ValueError(f'parent snapshot changed: {path}')
    if sha(PARENT/'boundary_proposal.json')!=p['proposal_sha256']:raise ValueError('parent proposal changed')
    nodes=check_candidate(UPSTREAM/'op.raw',UPSTREAM/'tb.cir',UPSTREAM/'execution.json',UPSTREAM/'simulator.log',PARENT/'prepared/ff_op.cir')
    replay=boundary.get(REPLAY)
    signature=boundary.input_stage_signature((PARENT/'snap/cells/analog/rx/ctle/spice/rx_ctle_rc.spice').read_text(),'serdes_rx_ctle_rc',('inp','inn'))
    boundary.check_load(REPLAY,signature)
    c=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);c.mkdir(parents=True,exist_ok=False)
    shutil.copytree(PARENT/'snap',c/'snap')
    (c/'source').mkdir();(c/'upstream').mkdir();(c/'prepared').mkdir()
    for path,h in p['source_sha256'].items():
        src=Path(path);rel=src.relative_to(ROOT);dst=c/'source'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
        if sha(dst)!=h:raise ValueError(f'source copy mismatch: {src}')
    for src in RUNTIME:
        dst=c/'source'/src.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists() and sha(dst)!=sha(src):raise ValueError(f'parent and current runtime differ: {src}')
        if not dst.exists():shutil.copyfile(src,dst)
    for name in ('op.raw','tb.cir','execution.json','simulator.log'):shutil.copyfile(UPSTREAM/name,c/'upstream'/name)
    shutil.copyfile(PARENT/'plan.json',c/'upstream/parent_plan.json')
    shutil.copyfile(PARENT/'boundary_proposal.json',c/'upstream/parent_boundary_proposal.json')
    (c/'seed_nodes.json').write_text(json.dumps(nodes,indent=1,allow_nan=False)+'\n')
    (c/'prepared/ff_direct_dc.cir').write_text(make_deck(c,nodes))
    (c/'seed_boundary_proposal.json').write_text(json.dumps(proposal(c,nodes),indent=2)+'\n')
    copies={str(x.relative_to(c)):sha(x) for d in ('snap','source','upstream','prepared') for x in (c/d).rglob('*') if x.is_file()}
    plan={'source_copies':copies,'parent_sources':p['source_sha256'],'pdk_sha256':p['pdk_sha256'],
          'runtime':{str(x.relative_to(ROOT)):sha(x) for x in RUNTIME},'seed_sha256':sha(c/'seed_nodes.json'),
          'proposal_sha256':sha(c/'seed_boundary_proposal.json'),'node_count':len(nodes),
          'replay_entry':replay,'replay_load_signature':signature,'seed_bc':BC,'scope':'FF W40 independent Newton attempt; not startup qualification'}
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def verify(c,registered=False):
    p=json.loads((c/'plan.json').read_text())
    for path,h in p['source_copies'].items():
        if sha(c/path)!=h:raise ValueError(f'frozen source changed: {path}')
    for path,h in p['parent_sources'].items():
        if sha(c/'source'/Path(path).relative_to(ROOT))!=h:raise ValueError(f'parent frozen source mismatch: {path}')
    for path,h in p['runtime'].items():
        if sha(ROOT/path)!=h:raise ValueError(f'runtime changed: {path}')
    for path,h in p['pdk_sha256'].items():
        if sha(path)!=h:raise ValueError(f'PDK changed: {path}')
    if boundary.get(REPLAY)!=p['replay_entry']:raise ValueError('replay entry changed')
    boundary.check_load(REPLAY,p['replay_load_signature'])
    n=entries(c/'upstream/op.raw')
    if sha(c/'seed_nodes.json')!=p['seed_sha256'] or json.loads((c/'seed_nodes.json').read_text())!=n or len(n)!=p['node_count']:raise ValueError('seed changed')
    b=json.loads((c/'seed_boundary_proposal.json').read_text())
    if sha(c/'seed_boundary_proposal.json')!=p['proposal_sha256'] or b!=proposal(c,n):raise ValueError('proposal changed')
    if (c/'prepared/ff_direct_dc.cir').read_text()!=make_deck(c,n):raise ValueError('deck changed')
    if registered and boundary.get(BC)!=b:raise ValueError('seed BC not registered or changed')
    return p,n


def assess(c,run,nodes):
    ex=json.loads((run/'execution.json').read_text());log=(run/'simulator.log').read_text(errors='replace');deck=c/'prepared/ff_direct_dc.cir'
    if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=sha(deck) or sha(run/'tb.cir')!=sha(deck):raise ValueError('execution mismatch')
    if ex['bc']!=BC or ex['replay_bc']!=REPLAY or ex['ngspice']!=project.ngspice() or ex['pdk_installation_id']!=project.pdk_installation_id():raise ValueError('tool/boundary mismatch')
    if not all(x in log for x in ('STAGE_DIRECT_NEWTON_ONLY','Optran is deselected','STAGE_OP_RETURNED','STAGE_RAW_WRITTEN')):raise ValueError('Newton markers missing')
    if re.search(r'Starting (?:dynamic gmin|true gmin|source stepping)|Transient op started',log,re.I):raise ValueError('solver fallback')
    new=entries(run/'op.raw');values={x['node']:x['value'] for x in new};old={x['node']:x['value'] for x in nodes}
    if not set(old)<=set(values):raise ValueError('result node set incomplete')
    diffs={key:values[key]-value for key,value in old.items()};worst=max(diffs,key=lambda x:abs(diffs[x]))
    return {'status':'observed','spec_status':'ungraded','scope':'direct Newton without fallback; not physical startup',
            'nodes':len(new),'max_abs_delta_v':abs(diffs[worst]),'max_delta_node':worst,
            'bias':{k:{'candidate_v':old[k],'newton_v':values[k],'delta_v':diffs[k]} for k in ('bias_vbg','vgi_bias','vbias','vctle')},
            'raw_sha256':sha(run/'op.raw'),'execution_sha256':sha(run/'execution.json'),'log_sha256':sha(run/'simulator.log'),'run':str(run.relative_to(ROOT))}


def resume(c):
    with (c/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p,n=verify(c,registered=True)
        for r in reversed([c/'ff_direct_dc']+sorted(c.glob('ff_direct_dc.r[0-9]*'))):
            try:print(json.dumps(assess(c,r,n),indent=2));return
            except (OSError,ValueError,KeyError,IndexError):pass
        active=watch.ngspice_cwds()
        if len(active)>=4 or any(x.is_relative_to(c) for x in active):raise ValueError('ngspice quota or active campaign')
        r=spice.next_run_dir(c,'ff_direct_dc')
        execution=spice.run((c/'prepared/ff_direct_dc.cir').read_text(),r,timeout_s=600,meta={'bc':BC,'replay_bc':REPLAY,'scope':p['scope']})
        try:result=assess(c,r,n)
        except (OSError,ValueError,KeyError,IndexError) as exc:
            result=dict(status='incomplete_or_numerical_failure',spec_status='ungraded',reason=str(exc),
                        timed_out=execution.timed_out,run=str(r.relative_to(ROOT)),execution_sha256=sha(r/'execution.json'))
        out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
        (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(out.relative_to(ROOT))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--check',type=Path);g.add_argument('--resume',type=Path);a=ap.parse_args()
    if a.prepare:
        c=prepare();p,n=verify(c);print(json.dumps({'campaign':str(c.relative_to(ROOT)),'nodes':len(n),'proposal':str((c/'seed_boundary_proposal.json').relative_to(ROOT)),'registered':False},indent=2))
    elif a.check:
        p,n=verify(a.check.resolve());print(json.dumps({'nodes':len(n),'status':'verified; no simulation'},indent=2))
    else:resume(a.resume.resolve())
