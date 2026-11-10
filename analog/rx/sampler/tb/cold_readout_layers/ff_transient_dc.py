"""FF W40 C2 replay, pilot then full transient from independently verified FF DC.

Prepare/check never run ngspice. Resume requires registered FF DC seed BC;
no physical startup or native PLL qualification is implied.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
from uuid import uuid4

import numpy as np
from serdes_flow import boundary, eye, project, spice, watch
from serdes_flow.corners import Condition

ROOT=project.ROOT
SELF=Path(__file__).resolve()
HERE=SELF.parent
DC_RUNNER=HERE/'ff_direct_dc.py'
FS_RUNNER=HERE/'full_transient_dc.py'
PARENT=ROOT/'results/analog/rx/sampler/cold_readout_ff_direct_dc/20261110T130130.446962Z_0943ba28'
OUT=ROOT/'results/analog/rx/sampler/cold_readout_ff_transient_dc'
BC='rx_ff_w40_direct_newton_dc_seed_v1'
REPLAY='rx_c2_far_nominal@ctle_rc'
CASES={'pilot':(1e-9,600),'full':(44.75e-9,1500)}


def load(path,name):
    sys.path.insert(0,str(HERE))
    try:
        spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
    finally:sys.path.pop(0)


dc=load(DC_RUNNER,'ff_direct_dc_transient')
fs=load(FS_RUNNER,'fs_transient_measurement')
sha=dc.sha


def source_hashes():
    paths={SELF,DC_RUNNER,FS_RUNNER,Path(dc.spice.__file__).resolve(),Path(project.__file__).resolve(),Path(watch.__file__).resolve(),Path(boundary.__file__).resolve(),ROOT/'config/pdk.toml',ROOT/'config/tools.toml'}
    paths.update(Path(p) for p in fs.analysis_hashes())
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}


def deck_for(c,nodes,case):
    text=(c/'parent/prepared/ff_direct_dc.cir').read_text().split('.control',1)[0]
    text=text.replace(str(PARENT/'snap')+'/',str(c/'snap')+'/')
    if str(PARENT/'snap') in text or str(c/'snap') not in text:raise ValueError('snapshot rewrite failed')
    text='\n'.join(x for x in text.splitlines() if not x.lower().startswith(('.nodeset ','.save ')))+'\n'
    text+='* same-FF independent-Newton voltages, soft guesses only\n'
    text+='\n'.join(f'.nodeset v({x["node"]})={x["value"]:.17g}' for x in nodes)+'\n'
    text+='.save '+' '.join(f'v({n})' for n in fs.NODES)+' i(vdd)\n'
    stop='1n' if case=='pilot' else '44.75n'
    text+=''' .control
set num_threads=1
set filetype=binary
echo STAGE_DIRECT_NEWTON_ONLY
optran 1 0 0 0 0 0
echo STAGE_BEFORE_TRAN
'''.lstrip()+f'tran 2p {stop} 0 4p\n'+'''echo STAGE_TRAN_RETURNED
let power=-v(vdd)*i(vdd)
write wave.raw '''+' '.join(fs.VECTORS)+'''\necho STAGE_RAW_WRITTEN
quit
.endc
.end
'''
    if re.search(r'^\s*\.ic\b|\buic\b',text,re.I|re.M):raise ValueError('unexpected hard initial condition')
    return text


def proposal(c):
    upstream=c/'parent/ff_direct_dc'
    return {'id':BC,'kind':'numerical_initial_guess','description':'All finite voltage nodes from same-FF W40 direct Newton solution; soft transient guesses, not physical startup.',
            'upstream':{'module':'RX sampler/readout','run':str((PARENT/'ff_direct_dc').relative_to(ROOT)),
                        'raw_sha256':sha(upstream/'op.raw'),'deck_sha256':sha(upstream/'tb.cir'),
                        'execution_sha256':sha(upstream/'execution.json'),'source_plan_sha256':sha(c/'parent/plan.json')},
            'nodes':{'file':str((c/'seed_nodes.json').relative_to(ROOT)),'sha256':sha(c/'seed_nodes.json'),'format':'JSON list of node/value; voltage nodes only'},
            'load':None,'points':{'ff_v1950_t-40':{'condition':'FF_hh 1.95 V -40 C full W40 PI20 trim32 rb2k real bias','replay_boundary':REPLAY}},
            'processing':'all finite same-DUT independent Newton voltages as soft .nodeset; no .ic/uic',
            'validation':{'state':'ungraded','limitation':'converged DC is not physical startup or functional readout proof'},
            'valid_while':['same full FF circuit, nominal C2 replay, PDK, load and t=0 sources']}


def prepare():
    pp,oldnodes=dc.verify(PARENT,registered=True)
    r=PARENT/'ff_direct_dc'
    if not (r/'execution.json').is_file():raise ValueError('fixed FF direct-Newton result not complete: execution.json missing')
    evidence=dc.assess(PARENT,r,oldnodes)
    nodes=dc.entries(r/'op.raw')
    bc_entry=boundary.get(dc.BC);replay=boundary.get(REPLAY)
    sig=boundary.input_stage_signature((PARENT/'snap/cells/analog/rx/ctle/spice/rx_ctle_rc.spice').read_text(),'serdes_rx_ctle_rc',('inp','inn'));boundary.check_load(REPLAY,sig)
    hashes=source_hashes()
    c=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);c.mkdir(parents=True,exist_ok=False)
    shutil.copytree(PARENT/'snap',c/'snap')
    (c/'parent').mkdir();shutil.copytree(PARENT/'source',c/'parent/source');shutil.copytree(PARENT/'upstream',c/'parent/upstream');shutil.copytree(PARENT/'prepared',c/'parent/prepared');shutil.copytree(r,c/'parent/ff_direct_dc')
    for name in ('plan.json','seed_nodes.json','seed_boundary_proposal.json'):shutil.copyfile(PARENT/name,c/'parent'/name)
    (c/'source').mkdir()
    for rel,h in hashes.items():
        target=c/'source'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,target)
        if sha(target)!=h:raise ValueError(f'runtime source copy mismatch {rel}')
    (c/'seed_nodes.json').write_text(json.dumps(nodes,indent=1,allow_nan=False)+'\n')
    (c/'prepared').mkdir()
    for case in CASES:(c/'prepared'/f'{case}.cir').write_text(deck_for(c,nodes,case))
    (c/'seed_boundary_proposal.json').write_text(json.dumps(proposal(c),indent=2)+'\n')
    snapshots={str(x.relative_to(c)):sha(x) for d in ('snap','parent','source','prepared') for x in (c/d).rglob('*') if x.is_file()}
    plan={'scope':'FF 1.95 V -40 C hh W40, real bias and nominal C2 replay, ideal PI anchors; no physical startup or native PLL',
          'source_hashes':hashes,'snapshots':snapshots,'pdk_sha256':pp['pdk_sha256'],'parent_dc_evidence':evidence,
          'parent_seed_entry':bc_entry,'replay_entry':replay,'replay_signature':sig,'seed_bc':BC,
          'seed_sha256':sha(c/'seed_nodes.json'),'proposal_sha256':sha(c/'seed_boundary_proposal.json'),'node_count':len(nodes),'cases':CASES}
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def verify(c,registered=False):
    p=json.loads((c/'plan.json').read_text())
    for rel,h in p['snapshots'].items():
        if sha(c/rel)!=h:raise ValueError(f'snapshot changed: {rel}')
    for rel,h in p['source_hashes'].items():
        if sha(ROOT/rel)!=h or sha(c/'source'/rel)!=h:raise ValueError(f'runtime changed: {rel}')
    for path,h in p['pdk_sha256'].items():
        if sha(path)!=h:raise ValueError(f'PDK changed: {path}')
    if boundary.get(REPLAY)!=p['replay_entry'] or boundary.get(dc.BC)!=p['parent_seed_entry']:raise ValueError('upstream BC changed')
    boundary.check_load(REPLAY,p['replay_signature'])
    nodes=dc.entries(c/'parent/ff_direct_dc/op.raw')
    if sha(c/'seed_nodes.json')!=p['seed_sha256'] or json.loads((c/'seed_nodes.json').read_text())!=nodes or len(nodes)!=p['node_count']:raise ValueError('seed changed')
    b=json.loads((c/'seed_boundary_proposal.json').read_text())
    if sha(c/'seed_boundary_proposal.json')!=p['proposal_sha256'] or b!=proposal(c):raise ValueError('proposal changed')
    for case in CASES:
        if (c/'prepared'/f'{case}.cir').read_text()!=deck_for(c,nodes,case):raise ValueError('deck changed')
    if registered and boundary.get(BC)!=b:raise ValueError('new BC not registered or changed')
    return p,nodes


def assess(c,run,case,nodes):
    ex=json.loads((run/'execution.json').read_text());deck=c/'prepared'/f'{case}.cir'
    if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=sha(deck) or sha(run/'tb.cir')!=sha(deck):raise ValueError('execution/deck mismatch')
    if ex['bc']!=REPLAY or ex['seed_bc']!=BC or ex['case']!=case or ex['ngspice']!=project.ngspice() or ex['pdk_installation_id']!=project.pdk_installation_id():raise ValueError('execution identity mismatch')
    info=fs.inspect(run,case,nodes)
    if not info['tran_returned'] or not info['raw_written'] or not info['raw_complete'] or not info['optran_deselected'] or info['any_fallback']:raise ValueError('truncated or fallback transient')
    wave=spice.Waves(run/'wave.raw')
    if not all(x in wave and np.isfinite(wave[x]).all() for x in fs.VECTORS):raise ValueError('missing/nonfinite vectors')
    if case=='pilot' and not info['health']['numerical_bias_health']:raise ValueError('pilot bias or power unhealthy')
    return info


def completed(c,case,nodes):
    for r in reversed([c/('transient_'+case)]+sorted(c.glob('transient_'+case+'.r[0-9]*'))):
        try:return r,assess(c,r,case,nodes)
        except (OSError,ValueError,KeyError,IndexError):pass
    return None


def resume(c,case):
    with (c/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p,nodes=verify(c,registered=True)
        if case=='full' and completed(c,'pilot',nodes) is None:raise ValueError('healthy complete pilot required')
        done=completed(c,case,nodes)
        if done:r,info=done;error=None
        else:
            active=watch.ngspice_cwds()
            if len(active)>=4 or any(x.is_relative_to(c) for x in active):raise ValueError('quota exceeded or campaign active')
            r=spice.next_run_dir(c,'transient_'+case);spice.run((c/'prepared'/f'{case}.cir').read_text(),r,timeout_s=CASES[case][1],meta={'case':case,'bc':REPLAY,'seed_bc':BC,'scope':p['scope']})
            try:info=assess(c,r,case,nodes);error=None
            except (OSError,ValueError,KeyError,IndexError) as exc:info=None;error=str(exc)
        row={'case':case,'status':'observed' if error is None else 'incomplete_or_numerical_failure','spec_status':'ungraded','run':str(r.relative_to(ROOT)),
             'stages':info,'error':error,'execution_sha256':sha(r/'execution.json')}
        if (r/'wave.raw').exists():row['raw_sha256']=sha(r/'wave.raw')
        if case=='full' and error is None:
            try:
                mod=fs.load_analysis();boundary.check_load(REPLAY,mod.sp.replay.signature())
                row['readout_analysis']=mod.analyse(r/'wave.raw',Condition('ff',1.95,-40),20,eye.prbs7(mod.sp.link.NBITS))
                row['analysis_window_s']=[mod.sp.link.T0+(mod.sp.link.WARM+6)*mod.sp.link.UI,CASES['full'][0]]
            except (ValueError,IndexError,KeyError) as exc:row['analysis_error']=str(exc)
        out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
        (out/'summary.json').write_text(json.dumps({'scope':p['scope'],'result':row},indent=2,allow_nan=False)+'\n');print(out.relative_to(ROOT))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--check',type=Path);g.add_argument('--resume',type=Path)
    ap.add_argument('--case',choices=tuple(CASES),default='pilot');a=ap.parse_args()
    if a.prepare:
        c=prepare();p,n=verify(c);print(json.dumps({'campaign':str(c.relative_to(ROOT)),'nodes':len(n),'proposal':str((c/'seed_boundary_proposal.json').relative_to(ROOT)),'registered':False},indent=2))
    elif a.check:
        p,n=verify(a.check.resolve());print(json.dumps({'nodes':len(n),'status':'verified; no simulation'},indent=2))
    else:resume(a.resume.resolve(),a.case)
