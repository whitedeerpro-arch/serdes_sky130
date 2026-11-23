"""Readout lane loading diagnostic; partial circuits are not full-RX equivalents.

No ideal bias, hard initial conditions or changed t=0 stimuli. --prepare and
--check never invoke ngspice. --resume uses SPARSE, 240 s per case, one worker.
The partial OP result does not establish full-RX or functional pass.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid

import run as base
import full_short as short
from serdes_flow import spice, watch

OUT=base.ROOT/'results/analog/rx/sampler/cold_readout_lane_op'
CELL='analog/rx/sampler/spice/rx_readout_deser16.spice'
LANES={'xla0':'a0','xlae1':'ae1','xlb0':'b0','xlbe1':'be1','xla1':'a1','xlae0':'ae0','xlb1':'b1','xlbe0':'be0'}
CASES={'one':{'xla0'},'four':{'xla0','xlb0','xla1','xlb1'}}


def variant(text,keep):
    blocks=[]
    for line in text.splitlines():
        if line.lstrip().startswith('+'):
            if not blocks: raise ValueError('orphan continuation')
            blocks[-1].append(line)
        else: blocks.append([line])
    inside=False; output=[]; removed=[]; present=set()
    for block in blocks:
        line=block[0].strip(); name=line.split()[0].lower() if line else ''
        if line.lower().startswith('.subckt serdes_rx_readout_deser16 '): inside=True
        if inside and name in LANES:
            present.add(name)
            if name not in keep: removed.append('\n'.join(block)); continue
        output.extend(block)
        if inside and line.lower()=='.ends serdes_rx_readout_deser16': inside=False
    if present!=set(LANES): raise ValueError('lane instance mismatch')
    for name in ('xf','xwc'):
        original=[b for b in blocks if b[0].strip().lower().startswith(name+' ')]
        if len(original)!=1 or '\n'.join(original[0]) not in '\n'.join(output): raise ValueError(f'{name} changed')
    return '\n'.join(output)+'\n',removed


def make_deck(folder,oldplan,case):
    includes={src:str(Path('snap/cells')/Path(src).relative_to(base.SOURCE/'pdk_resistors')) for src in oldplan['includes']}
    cell=next(src for src in includes if src.endswith('/'+CELL)); includes[cell]=f'variants/{case}.spice'
    deck,removed,_=base.make_deck(folder,base.ORIGINAL.read_text(),3,'sparse',includes)
    if removed: raise ValueError('top-level instances changed')
    deck=deck.split('.control',1)[0]
    kept_outputs={LANES[x] for x in CASES[case]}; lines=[]; caps=[]
    for line in deck.splitlines():
        name=line.split()[0].lower() if line.split() else ''
        match=re.fullmatch(r'c(a0|b0|ae1|be1|a1|b1|ae0|be0)_[0-3]',name)
        if match and match.group(1) not in kept_outputs: caps.append(line)
        else: lines.append(line)
    if len(caps)!=4*(8-len(kept_outputs)): raise ValueError('output cap mismatch')
    nodes=['bias_vbg','vgi_bias','vbias','vctle','rkp','rkn','xro.ckq','xro.ckqb','xro.xwc.j0','xro.xwc.j1','w']
    vectors={f'v{i}':f'v({node})' for i,node in enumerate(nodes)}
    vectors.update(base.CURRENTS)
    ctrl=['.control','set num_threads=1','set wr_vecnames','set wr_singlescale','op']
    ctrl += [f'let {name}={expr}' for name,expr in vectors.items()]
    ctrl += ['wrdata op.tsv '+' '.join(vectors),'quit','.endc','.end']
    return '\n'.join(lines+ctrl)+'\n',caps


def prepare():
    oldplan=base.verify(short.OLD)
    folder=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]); folder.mkdir(parents=True,exist_ok=False)
    shutil.copytree(short.OLD/'snap',folder/'snap'); (folder/'variants').mkdir(); (folder/'prepared').mkdir()
    original=(folder/'snap/cells'/CELL).read_text(); cases=[]
    for case,keep in CASES.items():
        cell,removed=variant(original,keep); (folder/'variants'/f'{case}.spice').write_text(cell)
        deck,caps=make_deck(folder,oldplan,case); (folder/'prepared'/f'{case}.cir').write_text(deck)
        cases.append(dict(name=case,kept_lanes=sorted(keep),removed_lanes=removed,removed_caps=caps,load_sha256=hashlib.sha256((cell+deck).encode()).hexdigest()))
    snapshots={str(p.relative_to(folder)):base.sha(p) for d in ('snap','variants','prepared') for p in (folder/d).rglob('*') if p.is_file()}
    refs=['results/analog/rx/sampler/cold_readout_parts/20261109T084345.824625Z_321a922a/front_wordclk/execution.json',
          'results/analog/rx/sampler/cold_readout_layers/20261109T083205.422134Z_5cb6b16b/readout_sparse/execution.json']
    plan=dict(scope='FS full upstream with 1 or 4 physical CMOS lanes; SPARSE ordinary OP; partial loads not full circuit; observed/ungraded',
              warning='Partial circuit changes OP root; OP numerical convergence does not establish full-RX, startup or functional pass.',
              comparison='Compare zero lanes and eight lanes with existing ordinary SPARSE OP; previous eight-lane 120s timeout is incomplete, not failure.',
              boundary=base.BC,physical='real bias and FS_hh historical snapshot, PI20 trim32 rb2k W40, original six nodesets and original t0 stimuli/kick; no .ic/uic',
              source_hashes={str(p):base.sha(p) for p in (Path(__file__).resolve(),Path(base.__file__).resolve(),Path(short.__file__).resolve(),short.OLD/'plan.json')},
              reference_execution_hashes={p:base.sha(base.ROOT/p) for p in refs},snapshots=snapshots,cases=cases)
    (folder/'plan.json').write_text(json.dumps(plan,indent=2)+'\n'); return folder


def verify(folder):
    plan=json.loads((folder/'plan.json').read_text()); oldplan=base.verify(short.OLD)
    for path,digest in plan['source_hashes'].items():
        if base.sha(path)!=digest: raise ValueError(f'source changed: {path}')
    for path,digest in plan['reference_execution_hashes'].items():
        if base.sha(base.ROOT/path)!=digest: raise ValueError('reference changed')
    for path,digest in plan['snapshots'].items():
        if base.sha(folder/path)!=digest: raise ValueError(f'snapshot changed: {path}')
    for c in plan['cases']:
        cell,removed=variant((folder/'snap/cells'/CELL).read_text(),CASES[c['name']]); deck,caps=make_deck(folder,oldplan,c['name'])
        if cell!=(folder/'variants'/f'{c["name"]}.spice').read_text() or deck!=(folder/'prepared'/f'{c["name"]}.cir').read_text() or removed!=c['removed_lanes'] or caps!=c['removed_caps'] or deck.count('.nodeset ')!=1 or re.search(r'^\s*\.ic\b|\buic\b',deck,re.I|re.M): raise ValueError('case changed')
    return plan


def resume(folder,selected):
    plan=verify(folder)
    for case in ([selected] if selected else CASES):
        with (folder/f'.{case}.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); name='lane_'+case; complete=None
            for run in reversed([folder/name]+sorted(folder.glob(name+'.r*'))):
                try:
                    ex=json.loads((run/'execution.json').read_text()); details=base.read_op(run/'op.tsv',['bias_vbg','vgi_bias','vbias','vctle','rkp','rkn','xro.ckq','xro.ckqb','xro.xwc.j0','xro.xwc.j1','w'])
                    if ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and base.sha(run/'tb.cir')==base.sha(folder/'prepared'/f'{case}.cir'):
                        complete=(run,details); break
                except (OSError,ValueError,KeyError): pass
            if complete is None:
                if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice quota')
                run=spice.next_run_dir(folder,name); ex=spice.run((folder/'prepared'/f'{case}.cir').read_text(),run,timeout_s=240,meta=dict(case=case,bc=base.BC,scope=plan['scope']))
                details=None
                try:
                    if ex.ok: details=base.read_op(run/'op.tsv',['bias_vbg','vgi_bias','vbias','vctle','rkp','rkn','xro.ckq','xro.ckqb','xro.xwc.j0','xro.xwc.j1','w'])
                except (OSError,ValueError): pass
                if ex.ok and details is not None: complete=(run,details)
            row=dict(case=case,status='observed' if complete else 'incomplete_or_numerical_failure',spec_status='ungraded',run=str(run.relative_to(base.ROOT)),stages=details,execution_sha256=base.sha(run/'execution.json'))
            if (run/'op.tsv').exists(): row['op_sha256']=base.sha(run/'op.tsv')
            dest=folder/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'); dest.mkdir(parents=True,exist_ok=False)
            (dest/'summary.json').write_text(json.dumps(dict(scope=plan['scope'],warning=plan['warning'],result=row),indent=2,allow_nan=False)+'\n'); print(dest)


def main():
    ap=argparse.ArgumentParser(description=__doc__); g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true'); g.add_argument('--check',type=Path); g.add_argument('--resume',type=Path); ap.add_argument('--case',choices=tuple(CASES))
    a=ap.parse_args()
    if a.prepare: print(prepare())
    elif a.check: verify(a.check.resolve()); print('checkpoint valid; no ngspice')
    else: resume(a.resume.resolve(),a.case)


if __name__=='__main__': main()
