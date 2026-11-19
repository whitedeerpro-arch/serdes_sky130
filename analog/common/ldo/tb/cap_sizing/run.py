"""Resumable physical-MIM LDO capacitance screening. Original r4 stays intact.

Freeze exact per-candidate source files; one model section per deck. Screening
uses actual bandgap/copy, current load, physical R/MIM, dual loop injection.
No candidate is accepted on capacitance or AC performance alone.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import numpy as np
from serdes_flow import feedback, model_library, project, spice, watch
import re

ROOT = project.ROOT
SELF = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location('ldo_r4_cap_parent', SELF.parents[1]/'r4/run.py')
r4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r4)
OUT = ROOT/'results/analog/common/ldo/cap_sizing'

def variant(name, chv=50, ccas=50, cout=100, rhv=1000, rcas=10000, cc=2, single=False, cref=16, ref_series=1):
    return dict(name=name, chv_pf=chv, ccas_pf=ccas, cout_pf=cout,
                rhv_ohm=rhv, rcas_ohm=rcas, cc_pf=cc, single_pass=single,
                cref_pf=cref,ref_series=ref_series,total_pf=chv+ccas+cout+cc+cref)

VARIANTS = [variant('r4'), variant('gate8', ccas=8, rcas=62500),
            variant('both8', chv=8, ccas=8, rcas=62500),
            variant('s32', chv=8, ccas=8, cout=32, rcas=62500),
            variant('s16', chv=8, ccas=8, cout=16, rcas=62500),
            variant('s4', chv=8, ccas=8, cout=4, rcas=62500),
            variant('s0', chv=8, ccas=8, cout=0, rcas=62500),
            variant('hv4', chv=4, ccas=8, cout=16, rcas=62500),
            variant('hv16r2', chv=16, ccas=8, cout=16, rhv=2000, rcas=62500),
            variant('gate2', chv=8, ccas=2, cout=16, rcas=250000),
            variant('single', chv=8, ccas=0, cout=16, single=True)]

VARIANTS += [variant('hv16r3',chv=16,ccas=8,cout=4,rhv=3000,rcas=62500),
             variant('hv8r4',chv=8,ccas=16,cout=4,rhv=4000,rcas=31250),
             variant('b16r2',chv=16,ccas=16,cout=4,rhv=2000,rcas=31250),
             variant('b16r3',chv=16,ccas=16,cout=4,rhv=3000,rcas=31250),
             variant('b32',chv=32,ccas=16,cout=4,rcas=31250),
             variant('b32r2',chv=32,ccas=8,cout=4,rhv=2000,rcas=62500),
             variant('out4',chv=50,ccas=50,cout=4),
             variant('gate16',chv=50,ccas=16,cout=4,rcas=31250)]

VARIANTS += [variant('b32_h12',chv=32,ccas=16,cout=4,rhv=1200,rcas=31250),
             variant('b32_h15',chv=32,ccas=16,cout=4,rhv=1500,rcas=31250),
             variant('b32_h2',chv=32,ccas=16,cout=4,rhv=2000,rcas=31250)]

# Second pass: reference and cascode capacitors. Preserve the delivered70pF cell.
VARIANTS += [variant(name,chv=32,ccas=cas,cout=4,rhv=2000,rcas=500000/cas,
                     cref=ref,ref_series=nr) for name,cas,ref,nr in
             [('ref8',16,8,1),('ref4',16,4,1),('ref2',16,2,1),
              ('ref8_r2',16,8,2),('ref4_r2',16,4,2),
              ('cas8_only',8,16,1),('cas12_only',12,16,1),
              ('cas8_ref8',8,8,1),('cas12_ref8',12,8,1),
              ('cas12_ref4',12,4,1),('cas8_ref4',8,4,1)]]
VARIANTS += [dict(variant('stack_core70',chv=32,ccas=16,cout=4,rhv=2000,rcas=31250),mim2_core=True)]

# Planning gates: existing +/-2% output target and 34dB at20MHz. PM>=60deg
# is a local design guard, not a revised system specification.
GATES = dict(vout_min=1.764, vout_max=1.836, psrr_20mhz_db=34., pm_deg=60.)

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def cell_sources(v):
    cells = {p.name:p.read_text() for p in r4.CELLS}
    core = cells['ldo_hv18_core_r4.spice']
    changes = {'Xrhv vin va vss serdes_ldo_res r=1k':f'Xrhv vin va vss serdes_ldo_res r={v["rhv_ohm"]}',
               'Xrcas vin casg vss serdes_ldo_res r=10k':f'Xrcas vin casg vss serdes_ldo_res r={v["rcas_ohm"]}',
               'Xchv va vss serdes_ldo_mim50':f'Xchv va vss serdes_ldo_mim{v["chv_pf"]}',
               'Xccas casg vss serdes_ldo_mim50':f'Xccas casg vss serdes_ldo_mim{v["ccas_pf"]}',
               'Xccomp cz gate serdes_ldo_mim2':f'Xccomp cz gate serdes_ldo_mim{v["cc_pf"]}'}
    if v['name'] == 'r4':
        return cells
    for old,new in changes.items():
        if core.count(old)!=1: raise ValueError('Source anchor changed: '+old)
        core=core.replace(old,new)
    if v['single_pass']:
        core='\n'.join(s for s in core.splitlines() if not s.startswith(('Xcas ','Xrcas ','Xccas ')))+'\n'
        core=core.replace('Xpass mid gate out','Xpass vin gate out')
    cells['ldo_hv18_core_r4.spice']=core
    macro=cells['pll_supply_hv18_r4.spice']
    old='Xcout quiet vss serdes_ldo_mim100'
    if macro.count(old)!=1: raise ValueError('Output capacitor anchor changed')
    macro=macro.replace(old,f'Xcout quiet vss serdes_ldo_mim{v["cout_pf"]}' if v['cout_pf'] else '* Output MIM omitted in this explicit candidate')
    cref=v.get('cref_pf',16)
    if cref!=16:
        old='Xrefcap ref_local vss serdes_ldo_mim16'
        if macro.count(old)!=1:raise ValueError('Reference capacitor anchor changed')
        macro=macro.replace(old,f'Xrefcap ref_local vss serdes_ldo_mim{cref}')
    nr=v.get('ref_series',1)
    if nr not in (1,2,4):raise ValueError('Use1,2,4 explicit1Mohm physical strings')
    if nr!=1:
        old='Xrefres ref_start ref_local vss serdes_ldo_ref_res'
        if macro.count(old)!=1:raise ValueError('Reference resistor anchor changed')
        nodes=['ref_start',*[f'ref_series{k}' for k in range(1,nr)],'ref_local']
        macro=macro.replace(old,'\n'.join(f'Xrefres{k} {nodes[k]} {nodes[k+1]} vss serdes_ldo_ref_res' for k in range(nr)))
    cells['pll_supply_hv18_r4.spice']=macro
    for count in {v['chv_pf'],v['ccas_pf'],v['cout_pf'],v['cc_pf'],cref}-{0}:
        if f'.subckt serdes_ldo_mim{count} ' not in cells['ldo_passives.spice']:
            if not isinstance(count,int) or not 1<=count<64:raise ValueError('Unsupported physical MIM count')
            units=[2**k for k in range(6) if count&(2**k)]
            cells['ldo_passives.spice']+='\n'+f'.subckt serdes_ldo_mim{count} a b\n'+'\n'.join(f'X{k} a b serdes_ldo_mim{n}' for k,n in enumerate(units))+f'\n.ends serdes_ldo_mim{count}\n'
    if v.get('mim2_core'):
        for name,node,count in [('chv','va',v['chv_pf']),('ccas','casg',v['ccas_pf'])]:
            if count%2:raise ValueError('Two-level arrays require an even number of1pF units')
            old=f'X{name} {node} vss serdes_ldo_mim{count}'
            if cells['ldo_hv18_core_r4.spice'].count(old)!=1:raise ValueError('Stacked core anchor changed')
            cells['ldo_hv18_core_r4.spice']=cells['ldo_hv18_core_r4.spice'].replace(old,f'X{name} {node} vss serdes_ldo_stack{count}')
            cells['ldo_passives.spice']+='\n'+f'.subckt serdes_ldo_stack{count} a b\n'+'\n'.join(
                f'X{layer}_{k} {"a b" if layer==1 else "b a"} sky130_fd_pr__cap_mim_m3_{layer} w=22.1965 l=22.1965'
                for layer in (1,2) for k in range(count//2))+f'\n.ends serdes_ldo_stack{count}\n'
    if v.get('pex_file'):
        pex=Path(v['pex_file'])
        if sha(pex)!=v['pex_sha256']:raise ValueError('PEX source changed')
        cells['ldo_hv18_core_r4.spice']=pex.read_text()+"\n.subckt serdes_ldo_hv18_core_r4 vin out ref ibias fb off vss params: lp=0.9\nXpex vss out vin off ibias fb ref serdes_ldo_hv18_smallcap_pdk\n.ends serdes_ldo_hv18_core_r4\n"
    return cells

def pex_variant(v,path):
    text=path.read_text()
    if not re.search(r'^\.subckt serdes_ldo_hv18_smallcap_pdk vss out vin off ibias fb ref$',text,re.M):raise ValueError('Unexpected extracted core ports')
    lines=[x.split() for x in text.splitlines() if x.startswith('X')]
    nvt=[x for x in lines if len(x)>5 and x[5]=='sky130_fd_pr__nfet_05v0_nvt']
    pas=next(x for x in nvt if 'out' in (x[1],x[3]));cas=next(x for x in nvt if 'vin' in (x[1],x[3]))
    va=next(x[4] for x in lines if len(x)>5 and x[5]=='sky130_fd_pr__pfet_g5v0d10v5')
    mid=next(x for x in (pas[1],pas[3]) if x!='out')
    mapping={f'v(xdut.xcore.{name})':f'v(xdut.xcore.xpex.{node})' for name,node in [('gate',pas[2]),('casg',cas[2]),('va',va),('mid',mid)]}
    return dict(v,name=v['name']+'_pex',pex_file=str(path),pex_sha256=sha(path),probe_map=mapping)

def prepare(suite, names, reduced=False, pex_core=None):
    vs=[v for v in VARIANTS if v['name'] in names]
    if len(vs)!=len(set(names)):raise ValueError('Unknown/duplicate variant')
    if pex_core:
        if len(vs)!=1:raise ValueError('PEX core requires one variant')
        vs=[pex_variant(vs[0],pex_core.resolve())]
    # Include every primitive in the actual frozen candidates, including MIM2
    # and extracted cores. A baseline-only family list silently omits new types.
    required_primitives=sorted(set(re.findall(r'\bsky130_fd_pr__\w+',
        '\n'.join(text for v in vs for text in cell_sources(v).values()))))
    camp=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+suite)
    (camp/'prepared').mkdir(parents=True)
    for p in [SELF,*r4.RUNTIME,*r4.CELLS]:
        q=camp/'source'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
    cal=json.loads((ROOT/'docs/data/ldo_r4.json').read_text())
    cal_path=ROOT/cal['inputs']['calibration']['summary']
    calibration=json.loads(cal_path.read_text())['calibration_codes']
    entries=[]
    for v in vs:
        vp=camp/'variants'/v['name'];vp.mkdir(parents=True)
        for name,txt in cell_sources(v).items():(vp/name).write_text(txt)
        if suite=='worst':
            groups=[('fs','ll',[(3.,1.95,85,10)])]
        elif suite=='peripheral':
            groups=[('tt','tt',[(3.3,1.8,27,2),(3.3,1.8,27,10)]),
                    ('fs','ll',[(h,u,85,i) for h,u,i in [(3.,1.95,10),(3.6,1.95,2),(3.,1.65,10),(3.,1.95,2)]]),
                    ('ss','hh',[(3.,1.65,-40,i) for i in (2,10)]),
                    ('sf','hh',[(3.,1.65,85,i) for i in (2,10)])]
        elif suite=='screen':
            groups=[('tt','tt',[(3.3,1.8,27,2),(3.3,1.8,27,10)]),
                    ('fs','ll',[(3.,1.95,85,2),(3.6,1.95,85,2),(3.,1.65,85,10)])]
        elif suite=='stress':
            groups=[(mos,rc,[(h,u,t,i) for i in (2,10)]) for mos,rc,h,u,t in
                    [('tt','tt',3.3,1.8,27),('fs','ll',3.6,1.95,85),('ss','hh',3.,1.65,-40),
                     ('sf','hh',3.,1.65,85),('ff','ll',3.6,1.95,-40),('fs','hh',3.6,1.95,-40)]]
        else:
            groups=[(mos,rc,[(h,u,t,i) for h in (3.,3.6,3.3) for u in (1.65,1.95,1.8)
                             for t in (-40,85,27) for i in (2,10,6)]) for mos in ('fs','ss','sf','ff','tt') for rc in ('ll','hh','tt')]
        for mos,rc,points in groups:
            cases=[r4.case(trim=calibration[mos+':'+rc]['trim'],hv=h,host=u,temp=t,load=i,
                           ac=suite!='pvt' or (h in (3.,3.6) and u in (1.65,1.95) and t in (-40,85) and i in (2,10)) or (h,u,t,i)==(3.3,1.8,27,6)) for h,u,t,i in points]
            e=dict(name=f'{v["name"]}_{mos}_{rc}',variant=v['name'],mos=mos,rc=rc,section=r4.section(mos,rc),cases=cases,probe_map=v.get('probe_map',{}))
            deck=camp/'prepared'/(e['name']+'.cir')
            text=r4.deck(e)
            if reduced:
                lib=camp/'models'/e['section']
                if not lib.exists():
                    model_library.build(project.model_library(),e['section'],required_primitives,lib)
                text=text.replace(str(project.model_library()),str(lib/'sky130.lib.spice'))
            if v['single_pass']:
                text=text.replace('v(xdut.xcore.casg)','v(vin)').replace('v(xdut.xcore.mid)','v(vin)')
            for old,new in e['probe_map'].items():text=text.replace(old,new)
            deck.write_text(text)
            e.update(deck=str(deck.relative_to(camp)),deck_sha256=sha(deck));entries.append(e)
    smoke=dict(section='tt',cases=[r4.case(trim=42,ac=False)])
    smoke_text=r4.deck(smoke)
    if reduced:
        lib=camp/'models'/'tt'
        if not lib.exists():
            model_library.build(project.model_library(),'tt',required_primitives,lib)
        smoke_text=smoke_text.replace(str(project.model_library()),str(lib/'sky130.lib.spice'))
    (camp/'prepared/smoke.cir').write_text(smoke_text)
    p=dict(suite=suite,variants=vs,entries=entries,gates=GATES,calibration=str(cal_path.relative_to(ROOT)),calibration_sha256=sha(cal_path),
           pdk_sha256=r4.reg.pdk_identity(),sources={str(q.relative_to(camp)):sha(q) for folder in (('source','variants','prepared','models') if reduced else ('source','variants','prepared')) for q in (camp/folder).rglob('*') if q.is_file()},
           reduced_models=reduced,scope='Physical schematic R/MIM; real BG/copy; static current loads; no PEX, actual PLL startup/BER/noise qualification')
    (camp/'plan.json').write_text(json.dumps(p,indent=2)+'\n')
    return camp

def verify(camp):
    p=json.loads((camp/'plan.json').read_text())
    for rel,h in p['sources'].items():
        if sha(camp/rel)!=h:raise ValueError('Frozen input changed: '+rel)
    if r4.reg.pdk_identity()!=p['pdk_sha256']:raise ValueError('PDK changed')
    return p

def files_for(camp,v):
    return {p.name:p for p in (camp/'variants'/v).glob('*.spice')}

def completed(camp,e):
    for run in reversed([camp/e['name']]+sorted(camp.glob(e['name']+'.r[0-9]*'))):
        try:
            ex=json.loads((run/'execution.json').read_text())
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or sha(run/'tb.cir')!=e['deck_sha256']:continue
            if any(ex['inputs_sha256'].get(n)!=sha(p) or sha(run/n)!=sha(p) for n,p in files_for(camp,e['variant']).items()):continue
            for k,c in enumerate(e['cases']):
                w=spice.Waves(run/f'c{k:04d}_dc.raw')
                required=[e.get('probe_map',{}).get(key,key) for key in r4.DC_VECTORS if not (e['variant']=='single' and key in ('v(xdut.xcore.casg)','v(xdut.xcore.mid)'))]
                if len(w.t)!=2 or not np.allclose(w.t,[c['load_ma']*.001,(c['load_ma']+.001)*.001],rtol=0,atol=1e-12) or any(key not in w for key in required):raise ValueError('Incomplete DC')
                if c['ac']:
                    for kind in ('hv','host','voltage','current'):
                        a=np.loadtxt(run/f'c{k:04d}_{kind}.tsv',skiprows=1)
                        hi=kind in ('voltage','current');n=181 if hi else 147
                        if a.shape!=(n,3 if hi else 11) or not np.all(np.isfinite(a)) or not np.allclose(a[:,0],np.geomspace(10,1e10 if hi else 2e8,n),rtol=1e-6):raise ValueError('Incomplete AC')
            return run
        except (OSError,ValueError,KeyError):pass
    return None

def analyse(camp):
    p=verify(camp);rows=[];missing=[]
    for e in p['entries']:
        run=completed(camp,e)
        if run is None:missing.append(e['name']);continue
        for k,c in enumerate(e['cases']):
            stem=f'c{k:04d}';w=spice.Waves(run/(stem+'_dc.raw'))
            wv=lambda key:w[e.get('probe_map',{}).get(key,key)]
            row=dict(c,variant=e['variant'],mos=e['mos'],rc=e['rc'],vout_v=float(w['v(quiet)'][0]),ref_v=float(w['v(xdut.ref_local)'][0]),
                     gate_v=float(wv('v(xdut.xcore.gate)')[0]),va_v=float(wv('v(xdut.xcore.va)')[0]),
                     vin_excess_ua=float((-w['i(vdd)'][0]-c['load_ma']*.001)*1e6),run=str(run.relative_to(ROOT)),stem=stem)
            row['dc_pass']=p['gates']['vout_min']<=row['vout_v']<=p['gates']['vout_max']
            if c['ac']:
                hv=np.loadtxt(run/(stem+'_hv.tsv'),skiprows=1);host=np.loadtxt(run/(stem+'_host.tsv'),skiprows=1)
                a=np.loadtxt(run/(stem+'_voltage.tsv'),skiprows=1);b=np.loadtxt(run/(stem+'_current.tsv'),skiprows=1)
                gain=feedback.middlebrook(a[:,1]+1j*a[:,2],b[:,1]+1j*b[:,2]);cross=feedback.unity_crossings(a[:,0],gain)
                row.update(psrr20_db=float(-20*np.log10(r4.interp(hv,2e7))),host1_v_v=r4.interp(host,1e6),host20_v_v=r4.interp(host,2e7),crossings=cross)
                row['ac_pass']=len(cross)==1 and cross[0]['direction']=='down' and cross[0]['pm_deg']>=p['gates']['pm_deg'] and row['psrr20_db']>=p['gates']['psrr_20mhz_db']
            rows.append(row)
    summaries=[]
    for v in p['variants']:
        rr=[x for x in rows if x['variant']==v['name']];ac=[x for x in rr if x['ac']]
        summaries.append(dict(**v,complete=not any(x.startswith(v['name']+'_') for x in missing),dc_cases=len(rr),ac_cases=len(ac),
                              passed=bool(rr) and all(x['dc_pass'] and x.get('ac_pass',True) for x in rr) and not any(x.startswith(v['name']+'_') for x in missing),
                              vout_min=min((x['vout_v'] for x in rr),default=None),vout_max=max((x['vout_v'] for x in rr),default=None),
                              psrr20_min_db=min((x['psrr20_db'] for x in ac),default=None),pm_min_deg=min((z['pm_deg'] for x in ac for z in x['crossings']),default=None),
                              host1_max_v_v=max((x['host1_v_v'] for x in ac),default=None)))
    dest=camp/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');dest.mkdir(parents=True)
    result=dict(campaign=str(camp.relative_to(ROOT)),plan_sha256=sha(camp/'plan.json'),analyzer_sha256=sha(SELF),rows=rows,missing=missing,summary=summaries,gates=p['gates'],scope=p['scope'])
    (dest/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(summary=str((dest/'summary.json').relative_to(ROOT)),variants=summaries,missing=missing),indent=2),flush=True)
    return result

def resume(camp,workers):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=verify(camp)
        if len(watch.ngspice_cwds())+workers>4:raise ValueError('No global simulator slots')
        # Dedicated DC smoke per variant: no AC/transient is started on a new
        # DUT until its actual source set has completed this small card.
        def smoke(v):
            sr=camp/('smoke_'+v['name'])
            text=(camp/'prepared/smoke.cir').read_text()
            if v['single_pass']:
                text=text.replace('v(xdut.xcore.casg)','v(vin)').replace('v(xdut.xcore.mid)','v(vin)')
            for old,new in v.get('probe_map',{}).items():text=text.replace(old,new)
            done=False
            if (sr/'execution.json').exists():
                ex=json.loads((sr/'execution.json').read_text())
                done=ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and (sr/'c0000_dc.raw').exists()
            if not done:
                sr=spice.next_run_dir(camp,'smoke_'+v['name'])
                ex=spice.run(text,sr,files=files_for(camp,v['name']),timeout_s=180)
                if not ex.ok or not (sr/'c0000_dc.raw').exists():raise ValueError('DC smoke failed: '+v['name'])
        with ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(smoke,p['variants']))
        def one(e):
            if completed(camp,e):return
            if len(watch.ngspice_cwds())>=4:raise ValueError('Global slot occupied')
            dest=spice.next_run_dir(camp,e['name'])
            ex=spice.run((camp/e['deck']).read_text(),dest,files=files_for(camp,e['variant']),timeout_s=120+len(e['cases'])*15,
                         meta=dict(variant=e['variant'],suite=p['suite']))
            print(e['name'],round(ex.elapsed_s,2),'s',ex.ok,flush=True)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one,p['entries']))
        return analyse(camp)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',choices=('screen','stress','pvt','worst','peripheral'));g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path)
    ap.add_argument('--pex-core',type=Path,help='measured core capacitance-PEX, preserves frozen original schematic')
    ap.add_argument('--reduced',action='store_true',help='opt-in model-family reduction; compare baseline with full library before engineering use')
    ap.add_argument('--variants',nargs='+',default=[v['name'] for v in VARIANTS]);ap.add_argument('--workers',type=int,choices=(1,2),default=2)
    args=ap.parse_args()
    if args.prepare:print(prepare(args.prepare,args.variants,args.reduced,args.pex_core))
    elif args.resume:resume(args.resume.resolve(),args.workers)
    else:analyse(args.analyse.resolve())
