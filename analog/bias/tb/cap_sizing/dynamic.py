"""Bounded natural startup, in-range supply step and certified DC noise.

Startup ramps every externally imposed DC pin from zero; no nodeset/.ic/uic.
Noise uses pure DC sources and checks actual device OP immediately after each
spectrum, not after a new OP that could hide an incorrect noise bias.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import argparse
import fcntl
import importlib.util
import json
from pathlib import Path
import re
import shutil

import numpy as np
from serdes_flow import spice,watch

SELF=Path(__file__).resolve()
sp=importlib.util.spec_from_file_location('bg_cap_parent',SELF.with_name('run.py'))
base=importlib.util.module_from_spec(sp);sp.loader.exec_module(base)
ROOT=base.ROOT
IDS=[f'@m.xref.xbg.{n}.xmos.msky130_fd_pr__pfet_01v8_lvt[id]' for n in ('xm3','xmv')]
VGS='@m.xref.xbg.xmv.xmos.msky130_fd_pr__pfet_01v8_lvt[vgs]'
VECTORS=['v(vdd)','v(vbg)','v(vgi)','v(ci)','v(vr)','i(Vi0)','i(Vdd)']


def deck(e):
    text=base.body(e,base.project.model_library())
    vectors=VECTORS+(['v(vcml)','i(Vmcml)'] if e['load']=='dist' else ['i(Vload)'])
    if e['mode']=='startup':
        text=re.sub(r'^\.nodeset .*\n','',text,flags=re.M)
        after=e['supply_v']+e['step_v']
        text=re.sub(r'^Vdd .*$',f'Vdd vdd 0 pwl(0 0 1u {e["supply_v"]} 40u {e["supply_v"]} 40.00001u {after})',text,flags=re.M)
        for k in range(4):text=text.replace(f'Vi{k} i{k} 0 0.7',f'Bi{k} i{k} 0 V=0.7*min(time/1u,1)')
        # Keep the reference-current measurement as a0V source after a ramped
        # clamp; do not pre-power output PMOS junctions while Vdd=0.
        text=text.replace('Bi0 i0 0 V=0.7*min(time/1u,1)','Bclamp0 clamp0 0 V=0.7*min(time/1u,1)\nVi0 i0 clamp0 0')
        text=text.replace('Vload load 0 0.9','Bload load clamp_load V=0.9*min(time/1u,1)\nVload clamp_load 0 0')
        text=text.replace('Vtop top 0 1.0','Btop top 0 V=min(time/1u,1)')
        ctl=['set num_threads=1','set filetype=binary','save '+' '.join(vectors),'tran 10n 60u 0 20n','write wave.raw '+' '.join(vectors)]
    else:
        ctl=['set num_threads=1','set filetype=binary','set numdgt=15','optran 1 1 1 20n 120u 0','op',
             'write op.raw '+' '.join(vectors+IDS+[VGS]),'destroy all']
        for node in ['vbg','vgi']+(['vcml'] if e['load']=='dist' else []):
            ctl += [f'noise v({node}) Vdd dec 40 1k 200meg','setplot noise1',f'write {node}_noise.raw frequency onoise_spectrum',
                    'print '+' '.join(IDS+[VGS]),'destroy all']
    return text+'\n.control\n'+'\n'.join(ctl+['quit','.endc','.end',''])


def prepare(parent,names):
    pp=base.verify(parent);variants=[v for v in pp['variants'] if v['name'] in names]
    if len(variants)!=len(set(names)):raise ValueError('Unknown candidate')
    c=base.OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_dynamic');(c/'prepared').mkdir(parents=True)
    shutil.copytree(parent/'variants',c/'variants');shutil.copytree(parent/'source',c/'source');shutil.copyfile(SELF,c/'source/dynamic.py')
    entries=[]
    for v in variants:
        for old in pp['entries']:
            if old['variant']!=v['name'] or old['section'] not in ('tt','ss_hh','ff_ll'):continue
            for mode in ('startup','noise'):
                e=dict(old,mode=mode,name=old['name']+'_'+mode,step_v=-.05 if old['supply_v']>1.9 else .05)
                if mode=='startup':e['t_end_s']=60e-6
                path=c/'prepared'/(e['name']+'.cir');path.write_text(deck(e));e['deck']=str(path.relative_to(c));entries.append(e)
    p=dict(variants=variants,entries=entries,parent=str(parent.relative_to(ROOT)),parent_plan_sha256=base.sha(parent/'plan.json'),
           pdk_id=pp['pdk_id'],model_library_sha256=pp['model_library_sha256'],
           sha256={str(p.relative_to(c)):base.sha(p) for p in c.rglob('*') if p.is_file()},
           scope='Two declared loads; zero-to-nominal1us ramp, supply step at40us staying1.65..1.95V,60us endpoint; separate pure-DC noise1k..199.5MHz; no full-system/MC/PEX qualification')
    (c/'plan.json').write_text(json.dumps(p,indent=2)+'\n');return c


def completed(c,e):
    for d in reversed([c/e['name']]+sorted(c.glob(e['name']+'.r[0-9]*'))):
        try:
            ex=json.loads((d/'execution.json').read_text())
            if ex['exit_code'] or ex['timed_out'] or ex['log_failures'] or (d/'tb.cir').read_text()!=(c/e['deck']).read_text():continue
            if e['mode']=='startup':
                w=spice.Waves(d/'wave.raw')
                if w.t[0]!=0 or w.t[-1]<e['t_end_s']*(1-1e-9) or any(v not in w for v in VECTORS):raise ValueError('Truncated startup')
            else:
                op=spice.Waves(d/'op.raw');nodes=['vbg','vgi']+(['vcml'] if e['load']=='dist' else [])
                for n in nodes:
                    w=spice.Waves(d/f'{n}_noise.raw')
                    if len(w.t)!=213 or not np.allclose(w.t,1e3*10**(np.arange(213)/40),rtol=1e-9):raise ValueError('Incomplete noise')
                log=(d/'simulator.log').read_text()
                for key in IDS+[VGS]:
                    vals=[float(x) for x in re.findall(re.escape(key)+r'\s*=\s*([-+0-9.eE]+)',log,re.I)]
                    if len(vals)!=len(nodes) or not np.allclose(vals,float(op[key][0]),rtol=1e-3,atol=1e-9):raise ValueError('Noise bias changed: '+key)
            return d
        except (OSError,ValueError,KeyError):pass
    return None


def analyse(c):
    p=base.verify(c);rows=[];missing=[];parent=ROOT/p['parent'];pp=base.verify(parent)
    for e in p['entries']:
        d=completed(c,e)
        if d is None:missing.append(e['name']);continue
        row=dict(e,run=str(d.relative_to(ROOT)))
        if e['mode']=='noise':
            row['noise_uv']={}
            for n in ['vbg','vgi']+(['vcml'] if e['load']=='dist' else []):
                w=spice.Waves(d/f'{n}_noise.raw');row['noise_uv'][n]=float(np.sqrt(np.trapezoid(w['onoise_spectrum']**2,w.t))*1e6)
            row['bias_verified']=True
        else:
            source=next(x for x in pp['entries'] if x['name']==e['name'].removesuffix('_startup'))
            reference=base.completed(parent,source)
            if reference is None:raise ValueError('Reference DC card incomplete')
            op=spice.Waves(reference/'op.raw');w=spice.Waves(d/'wave.raw');pre=(w.t>38e-6)&(w.t<40e-6);post=w.t>=40.1e-6;last=w.t>=58e-6
            v=float(np.mean(w['v(vbg)'][pre]));i=float(np.mean(w['i(vi0)'][pre]))
            row.update(vbg_v=v,iref_ua=i*1e6,reach_op=bool(abs(v-op['v(vbg)'][0])<.002 and abs(i/op['i(vi0)'][0]-1)<.01),
                       startup_vbg_error_mv=float((v-op['v(vbg)'][0])*1e3),
                       supply_step_peak_mv=float(np.max(np.abs(w['v(vbg)'][w.t>=40e-6]-v))*1e3),
                       last_vbg_pp_mv=float(np.ptp(w['v(vbg)'][last])*1e3))
        rows.append(row)
    target=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');target.mkdir(parents=True)
    out=dict(campaign=str(c.relative_to(ROOT)),rows=rows,missing=missing,scope=p['scope'])
    (target/'summary.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n');print(json.dumps(dict(summary=str((target/'summary.json').relative_to(ROOT)),rows=rows,missing=missing),indent=2),flush=True)


def resume(c,workers):
    with (c/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=base.verify(c)
        if len(watch.ngspice_cwds())+workers>4:raise ValueError('Global slots occupied')
        def one(e):
            if completed(c,e):return
            files={q.name:q for q in (c/'variants'/e['variant']).glob('*.spice')}
            ex=spice.run((c/e['deck']).read_text(),spice.next_run_dir(c,e['name']),files=files,timeout_s=300)
            print(e['name'],round(ex.elapsed_s,1),ex.ok,flush=True)
        with ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(one,p['entries']))
        analyse(c)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',type=Path);g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path)
    ap.add_argument('--variants',nargs='+',default=['phys6_rp','cc4_r30p']);ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare:print(prepare(a.prepare.resolve(),a.variants))
    elif a.resume:resume(a.resume.resolve(),a.workers)
    else:analyse(a.analyse.resolve())
