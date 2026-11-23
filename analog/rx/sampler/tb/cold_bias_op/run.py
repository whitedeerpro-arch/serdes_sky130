"""Cold RX bias-only OP preparation; never claims complete RX equivalence.

--prepare snapshots fixed FS W40 cells and records the seed BC proposal; --check
is read-only; --register explicitly registers that proposal before --resume.
Only --resume runs ngspice. No .ic/uic; four independent cases, one worker.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import uuid

from serdes_flow import boundary, project, spice, watch

ROOT=project.ROOT
SOURCE=ROOT/'results/analog/rx/sampler/readout_deser/20261105T195801Z_ac_trim32_realbias_rhh'
SOURCE_DECK=SOURCE/'fs_v1650_t-40/tb.cir'
DIST=ROOT/'results/analog/bias/dist_pvt/20261103T212249Z'
OUT=ROOT/'results/analog/rx/sampler/cold_bias_op'
BC='rx_cold_bias_dist_seed_v1'
CELLS=('analog/common/devices/spice/sky130_primitives.spice',
       'analog/common/devices/spice/sky130_pfet_lvt.spice',
       'analog/bias/spice/bandgap.spice', 'analog/bias/spice/bias_dist.spice')
CASES={'fs_v1650_t-40':('fs_hh',1.65),'ff_v1950_t-40':('ff_hh',1.95)}
NODES=('bias_vbg','vgi_bias','vbias','vctle')
VECTORS=('vbg','vgi','vcml','vctle','iref','icml','ictle')


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest()


def seed_boundary():
    source=json.loads((DIST/'summary.json').read_text())
    points={}
    for tag,(section,supply) in CASES.items():
        proc=tag.split('_')[0]
        rows=[r for r in source if r['process']==proc and r['rcorner']=='hh' and r['supply']==supply and r['temp']==-40]
        if len(rows)!=1:raise ValueError('missing or duplicate seed row')
        row=rows[0]
        seed=dict(zip(NODES,(row['vbg'],row['vgi'],row['v_cml'],row['v_ctle'])))
        if not all(math.isfinite(x) for x in seed.values()):raise ValueError('nonfinite seed')
        tsv=DIST/section/f'{section}_v{round(supply*1000)}_t-40.tsv'
        lines=tsv.read_text().splitlines()
        if len(lines)!=2:raise ValueError('seed TSV incomplete')
        data=dict(zip(lines[0].split(),map(float,lines[1].split())))
        for key,value in [('vbg',row['vbg']),('vgi',row['vgi']),('v_cml',row['v_cml']),('v_ctle',row['v_ctle'])]:
            if data[key]!=value:raise ValueError('TSV differs from summary')
        points[tag]=dict(seed_v=seed,source_tsv=str(tsv.relative_to(ROOT)),source_tsv_sha256=sha(tsv),
                         source_deck_sha256=sha(DIST/section/'tb.cir'),source_execution_sha256=sha(DIST/section/'execution.json'))
    return dict(id=BC,kind='numerical_nodeset_initial_guess',description='dist_pvt DC voltages as soft guesses only; not RX equivalent or accepted operating point',
        upstream=dict(module='bias',summary=str((DIST/'summary.json').relative_to(ROOT)),summary_sha256=sha(DIST/'summary.json'),
                      limitation='historic dist deck used mutable includes without archived cell snapshot'),
        nodes=list(NODES),points=points,load=None,processing='four top-level .nodeset guesses; never .ic/uic or forced voltage',
        validation=dict(state='ungraded',reason='source load differs; solve and check actual bias-only and later RX loading'),
        valid_while=['source hashes and condition tags unchanged','seed is solver aid only'])


def pdk_manifest():
    root=project.model_library().parents[2]
    directories=[root/'libs.tech/ngspice',root/'libs.ref/sky130_fd_pr/spice']
    files=sorted(p for d in directories for p in d.rglob('*') if p.is_file())
    if not files:raise ValueError('PDK model tree missing')
    return {str(p):sha(p) for p in files}


def deck(camp,tag,seeded,bc):
    section,supply=CASES[tag]
    snap=camp/'snap'
    inc='\n'.join(f'.include "{snap/rel}"' for rel in CELLS)
    # Keep original default OP hints except top-level vbg/vgi, which are replaced
    # by the measured seed only in the seeded case. No hard initial conditions.
    top=bc['points'][tag]['seed_v'] if seeded else {'bias_vbg':1.23,'vgi_bias':0.9}
    hints=' '.join(f'v({k})={v:.12g}' for k,v in top.items())
    hints+=' v(xbias_ref.xbg.s)=1.23 v(xbias_ref.vg)=0.9 v(xbias_ref.xbg.ta)=0.95 v(xbias_ref.xbg.tb)=0.95'
    return f'''RX bias-only OP; independent from full RX load
.lib "{project.model_library()}" {section}
{inc}
Vdd vdd 0 {supply}
Vref vref 0 {supply}
Xbias_ref bias_vbg bias_i0 bias_i1 bias_i2 bias_i3 vgi_bias vdd 0 serdes_bias_ref trim=15
Vbias_i0 bias_i0 0 0.7
Vbias_i1 bias_i1 0 0.7
Vbias_i2 bias_i2 0 0.7
Vbias_i3 bias_i3 0 0.7
XIref vbias vgi_bias vdd serdes_bias_pcopy n=85
Xref vbias 0 serdes_bias_cml
XIctle vctle vgi_bias vdd serdes_bias_pcopy n=20
Xcbias vctle vctle 0 0 serdes_nfet_lvt w=8 l=.5 nf=4
.nodeset {hints}
.temp -40
.options reltol=1e-4 abstol=1p vntol=1u klu
.control
set num_threads=1
set wr_vecnames
set wr_singlescale
op
let vbg=v(bias_vbg)
let vgi=v(vgi_bias)
let vcml=v(vbias)
let vctle=v(vctle)
let iref=i(Vbias_i0)
let icml=@m.xref.xd.xmos.msky130_fd_pr__nfet_01v8[id]
let ictle=@m.xcbias.xmos.msky130_fd_pr__nfet_01v8_lvt[id]
wrdata op.tsv {' '.join(VECTORS)}
quit
.endc
.end
'''


def prepare():
    bc=seed_boundary()
    original=SOURCE_DECK.read_text()
    for exact in ('Xbias_ref bias_vbg bias_i0 bias_i1 bias_i2 bias_i3 vgi_bias vdd 0 serdes_bias_ref trim=15',
                  'XIref vbias vgi_bias vdd serdes_bias_pcopy n=85','Xref vbias 0 serdes_bias_cml',
                  'XIctle vctle vgi_bias vdd serdes_bias_pcopy n=20','Xcbias vctle vctle 0 0 serdes_nfet_lvt w=8 l=.5 nf=4'):
        if exact not in original:raise ValueError(f'FS reference differs: {exact}')
    folder=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    for rel in CELLS:
        src=SOURCE/'pdk_resistors'/rel;dst=folder/'snap'/rel
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
        # Snapshot cells have no nested includes; PDK library is tracked below.
        if re.search(r'^\s*\.(include|lib)\b',dst.read_text(),re.I|re.M):raise ValueError(f'nested include requires closure: {rel}')
    (folder/'seed_boundary.json').write_text(json.dumps(bc,indent=2)+'\n')
    cases=[]
    for tag in CASES:
        for mode in ('original','seeded'):
            name=tag+'_'+mode
            p=folder/'prepared'/f'{name}.cir';p.parent.mkdir(exist_ok=True)
            text=deck(folder,tag,mode=='seeded',bc)
            if re.search(r'^\s*\.ic\b|\buic\b',text,re.I|re.M):raise ValueError('hard initial condition forbidden')
            p.write_text(text);cases.append(dict(name=name,condition=tag,mode=mode,deck=str(p.relative_to(folder))))
    source_files=[SOURCE_DECK,Path(__file__).resolve(),ROOT/'config/pdk.toml',ROOT/'config/tools.toml']+[SOURCE/'pdk_resistors'/x for x in CELLS]
    snapshots={str(p.relative_to(folder)):sha(p) for d in ('snap','prepared') for p in (folder/d).rglob('*') if p.is_file()}
    plan=dict(scope='bias-only OP; Xeq/Xpi/Xdut/Xro and kick absent; RX loading not represented',
              source_sha256={str(p.relative_to(ROOT)):sha(p) for p in source_files},
              pdk_installation_id=project.pdk_installation_id(),pdk_sha256=pdk_manifest(),
              seed_bc=BC,seed_boundary_sha256=digest(bc),snapshots=snapshots,cases=cases,
              removed=['Xeq','Xpi','Xdut','Xro','Ikick','PI/data/trim stimulus and RX load'],
              kept=['Xbias_ref trim15','four 0.7 V sinks','XIref n85','Xref CML diode/decoupling','XIctle n20','Xcbias','Vdd/Vref'],
              original_source_deck=str(SOURCE_DECK.relative_to(ROOT)),ff_scope='new FF condition from same FS W40 cell snapshot; no historical FF W40 deck claimed')
    (folder/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    return folder


def verify(folder,registered=False):
    plan=json.loads((folder/'plan.json').read_text());bc=json.loads((folder/'seed_boundary.json').read_text())
    if digest(bc)!=plan['seed_boundary_sha256'] or bc!=seed_boundary():raise ValueError('seed identity changed')
    if registered and boundary.get(BC)!=bc:raise ValueError('seed BC not registered or differs')
    if project.pdk_installation_id()!=plan['pdk_installation_id'] or pdk_manifest()!=plan['pdk_sha256']:raise ValueError('PDK identity changed')
    for path,h in plan['source_sha256'].items():
        if sha(ROOT/path)!=h:raise ValueError(f'source changed: {path}')
    for path,h in plan['snapshots'].items():
        if sha(folder/path)!=h:raise ValueError(f'checkpoint changed: {path}')
    for c in plan['cases']:
        if (folder/c['deck']).read_text()!=deck(folder,c['condition'],c['mode']=='seeded',bc):raise ValueError('deck differs from snapshot')
    return plan,bc


def read_op(path):
    lines=path.read_text().splitlines()
    if len(lines)!=2:raise ValueError('missing or incomplete OP table')
    cols=lines[0].split();vals=list(map(float,lines[1].split()))
    if len(cols)!=len(vals) or not all(math.isfinite(v) for v in vals):raise ValueError('invalid OP table')
    values=dict(zip(cols,vals))
    if any(k not in values for k in VECTORS):raise ValueError('missing OP vector')
    return values


def resume(folder,timeout):
    with (folder/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan,_=verify(folder,registered=True)
        if any(p==folder or p.is_relative_to(folder) for p in watch.ngspice_cwds()):raise ValueError('campaign active')
        results=[]
        for case in plan['cases']:
            name=case['name']; candidates=[folder/name]+[p for p in folder.glob(name+'.r*') if p.name.rsplit('.r',1)[-1].isdigit()]
            complete=None
            for run in reversed(candidates):
                try:
                    ex=json.loads((run/'execution.json').read_text())
                    if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or sha(run/'tb.cir')!=sha(folder/case['deck']):continue
                    v=read_op(run/'op.tsv');complete=(run,v);break
                except (OSError,ValueError,KeyError):continue
            if complete is None:
                if len(watch.ngspice_cwds())>=4:raise RuntimeError('global ngspice quota')
                run=spice.next_run_dir(folder,name)
                ex=spice.run((folder/case['deck']).read_text(),run,timeout_s=timeout,meta=case)
                try:
                    if ex.ok:complete=(run,read_op(run/'op.tsv'))
                except (OSError,ValueError):pass
            row={**case,'status':'missing_or_numerical_failure','spec_status':'ungraded'}
            if complete:
                run,v=complete; supply=CASES[case['condition']][1]
                # Basic physical consistency detects dead roots; not a signoff or acceptance threshold.
                sanity=(0<v['vbg']<supply and 0<v['vgi']<supply and 0<v['vcml']<supply and 0<v['vctle']<supply
                        and v['iref']>0 and v['icml']>0 and v['ictle']>0)
                row.update(status='observed' if sanity else 'invalid_or_zero_current_root',values=v,physical_sanity=sanity,
                           run=str(run.relative_to(ROOT)),execution_sha256=sha(run/'execution.json'),deck_sha256=sha(run/'tb.cir'),op_sha256=sha(run/'op.tsv'))
            results.append(row)
        archive=folder/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');archive.mkdir(parents=True,exist_ok=False)
        (archive/'summary.json').write_text(json.dumps(dict(scope=plan['scope'],seed_boundary_sha256=plan['seed_boundary_sha256'],rows=results),indent=2,allow_nan=False)+'\n')
        print(archive)


def main():
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--check',type=Path);g.add_argument('--register',type=Path);g.add_argument('--resume',type=Path)
    ap.add_argument('--timeout',type=float,default=120)
    a=ap.parse_args()
    if a.prepare:print(prepare())
    elif a.check:verify(a.check.resolve());print('checkpoint and seed proposal valid; no ngspice')
    elif a.register:
        _,bc=verify(a.register.resolve());old=boundary.registry().get(BC)
        if old is None:boundary.register(bc)
        elif old!=bc:raise ValueError('registered seed BC differs')
        print(BC)
    else:
        if not math.isfinite(a.timeout) or not 1<=a.timeout<=180:ap.error('timeout must be 1..180 s')
        resume(a.resume.resolve(),a.timeout)


if __name__=='__main__':main()
