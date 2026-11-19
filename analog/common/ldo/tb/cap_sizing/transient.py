"""Bounded startup/load-step/noise comparison of frozen LDO cap candidates.

No waveform is accepted without its transient endpoint; noise recomputes bias
and must reproduce both pass currents and output voltage. All sources are DC
in noise mode. Dynamic load steps are declared stress inputs, not measured PLL.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import fcntl
import importlib.util
import json
from pathlib import Path
import re
import shutil
import numpy as np
from serdes_flow import project,spice,watch

SELF=Path(__file__).resolve();ROOT=project.ROOT
s=importlib.util.spec_from_file_location('ldo_caps',SELF.with_name('run.py'));caps=importlib.util.module_from_spec(s);s.loader.exec_module(caps)
IDS=['@m.xdut.xcore.'+x+'.msky130_fd_pr__nfet_05v0_nvt[id]' for x in ('xpass','xcas')]
VBS='@m.xdut.xcore.xpass.msky130_fd_pr__nfet_05v0_nvt[vbs]'
VECTORS=('v(quiet)','v(xdut.ref_local)','v(bg)','v(xdut.xcore.gate)','v(xdut.xcore.casg)','i(vdd)','i(vhost)')
PROFILES=[('tt','tt',3.3,1.8,27),('fs','ll',3.,1.95,85),('ss','hh',3.,1.65,-40),('ff','ll',3.6,1.95,-40)]

def deck(e):
    body=caps.r4.body(caps.r4.section(e['mos'],e['rc'])).replace('.save all','')
    body=re.sub(r'^Vdd .*$',f'Vdd vin 0 {e["hv_v"]} ac 0',body,flags=re.M)
    body=re.sub(r'^Vhost .*$',f'Vhost host 0 {e["host_v"]} ac 0',body,flags=re.M)
    body=re.sub(r'^Venable .*$',f'Venable enable 0 {e["host_v"]}',body,flags=re.M)
    for k in range(6):body=re.sub(rf'^Vb{k} .*$',f'Vb{k} b{k} 0 {e["host_v"] if (e["trim"]>>k)&1 else 0}',body,flags=re.M)
    body=re.sub(r'^Iload .*$',f'Iload quiet 0 {e["load_ma"]}m',body,flags=re.M)
    mode=e['mode'];end=e.get('t_end_s')
    if mode=='startup':
        body=re.sub(r'^Vdd .*$',f'Vdd vin 0 pwl(0 0 20n 0 120n {e["hv_v"]})',body,flags=re.M)
        body=re.sub(r'^Vhost .*$',f'Vhost host 0 pwl(0 0 20n 0 120n {e["host_v"]})',body,flags=re.M)
        body=re.sub(r'^Venable .*$',f'Venable enable 0 pwl(0 0 250n 0 255n {e["host_v"]})',body,flags=re.M)
        for k in range(6):body=re.sub(rf'^Vb{k} .*$',f'Ebit{k} b{k} 0 host 0 {int(bool((e["trim"]>>k)&1))}',body,flags=re.M)
        body=re.sub(r'^Iload .*$',f'Rload quiet 0 {1800/e["load_ma"]}',body,flags=re.M)
    elif mode=='step':
        # 6mA base: +0.1mA/-0.1mA, +1mA/-1mA and +4mA/-4mA,
        # all1ns transitions, with200ns recovery per level.
        body+='Istep quiet 0 pwl(0 0 0.5u 0 0.501u 100u 0.7u 100u 0.701u 0 0.9u 0 0.901u -100u 1.1u -100u 1.101u 0 1.3u 0 1.301u 1m 1.5u 1m 1.501u 0 1.7u 0 1.701u -1m 1.9u -1m 1.901u 0 2.1u 0 2.101u 4m 2.3u 4m 2.301u 0 2.5u 0 2.501u -4m 2.7u -4m 2.701u 0)\n'
    lines=[body,f'.temp {e["temp_c"]}','.control','set num_threads=1','set filetype=binary','optran 1 1 1 100n 300u 0']
    if mode=='noise':
        lines+=['op','write op.raw '+' '.join(VECTORS+tuple(IDS)),'destroy all','noise v(quiet) Vdd dec 40 1k 200meg','setplot noise1','write noise.raw frequency onoise_spectrum','print '+' '.join(IDS+[VBS]),'destroy all']
    else:
        lines+=['save '+' '.join(VECTORS),f'tran {"20n" if mode=="startup" else "0.2n"} {end:g} 0 {"20n" if mode=="startup" else "1n"}', 'write wave.raw '+' '.join(VECTORS),'destroy all']
    return '\n'.join(lines+['quit','.endc','.end',''])

def prepare(parent,names,modes,pilot,profiles=None):
    pp=caps.verify(parent);cal=json.loads((ROOT/pp['calibration']).read_text())['calibration_codes']
    vs=[v for v in pp['variants'] if v['name'] in names]
    if len(vs)!=len(set(names)):raise ValueError('Unknown variant')
    c=caps.OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_dynamic');(c/'prepared').mkdir(parents=True)
    shutil.copytree(parent/'variants',c/'variants');shutil.copytree(parent/'source',c/'source')
    shutil.copyfile(SELF,c/'source/transient.py');entries=[]
    for v in vs:
        selected=PROFILES[:1] if pilot else [x for x in PROFILES if profiles is None or x[0] in profiles]
        for mos,rc,h,u,t in selected:
            for mode in modes:
                for load in ((2,10) if mode in ('noise','startup') else (6,)):
                    e=dict(name=f'{v["name"]}_{mos}_{rc}_{mode}_{load}',variant=v['name'],mode=mode,mos=mos,rc=rc,hv_v=h,host_v=u,temp_c=t,load_ma=load,trim=cal[mos+':'+rc]['trim'])
                    if mode!='noise':e['t_end_s']=180e-6 if mode=='startup' else 3e-6
                    path=c/'prepared'/(e['name']+'.cir');path.write_text(deck(e));e.update(deck=str(path.relative_to(c)),deck_sha256=caps.sha(path));entries.append(e)
    p=dict(entries=entries,variants=vs,parent=str(parent.relative_to(ROOT)),parent_plan_sha256=caps.sha(parent/'plan.json'),pdk_sha256=pp['pdk_sha256'],
           sources={str(q.relative_to(c)):caps.sha(q) for folder in ('source','variants','prepared') for q in (c/folder).rglob('*') if q.is_file()},
           scope='Local real BG/copy; startup resistive loads; declared 0.1/1/4mA 1ns load steps; noise1k..199.5MHz; no actual PLL/MC/PEX qualification')
    (c/'plan.json').write_text(json.dumps(p,indent=2)+'\n');return c

def completed(c,e):
    for r in reversed([c/e['name']]+sorted(c.glob(e['name']+'.r[0-9]*'))):
        try:
            ex=json.loads((r/'execution.json').read_text())
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or caps.sha(r/'tb.cir')!=e['deck_sha256']:continue
            if any(ex['inputs_sha256'].get(n)!=caps.sha(p) or caps.sha(r/n)!=caps.sha(p) for n,p in caps.files_for(c,e['variant']).items()):continue
            if e['mode']=='noise':
                w=spice.Waves(r/'noise.raw');op=spice.Waves(r/'op.raw')
                if len(w.t)!=213 or not np.allclose(w.t,1e3*10**(np.arange(213)/40),rtol=1e-9):raise ValueError('Truncated noise')
                log=(r/'simulator.log').read_text()
                for key in IDS:
                    vals=[float(x) for x in re.findall(re.escape(key)+r'\s*=\s*([-+0-9.eE]+)',log,re.I)]
                    if len(vals)!=1 or not np.isclose(vals[0],float(op[key][0]),rtol=1e-3):raise ValueError('Noise bias current changed')
                vals=[float(x) for x in re.findall(re.escape(VBS)+r'\s*=\s*([-+0-9.eE]+)',log,re.I)]
                if len(vals)!=1 or not np.isclose(-vals[0],op['v(quiet)'][0],atol=1e-3):raise ValueError('Noise bias voltage changed')
            else:
                w=spice.Waves(r/'wave.raw')
                if w.t[0]!=0 or w.t[-1]<e['t_end_s']*(1-1e-9) or any(x not in w for x in VECTORS):raise ValueError('Truncated transient')
            return r
        except (OSError,ValueError,KeyError):pass
    return None

def analyse(c):
    p=caps.verify(c);rows=[];missing=[]
    for e in p['entries']:
        r=completed(c,e)
        if r is None:missing.append(e['name']);continue
        x={k:v for k,v in e.items() if k not in ('deck','deck_sha256')};x['run']=str(r.relative_to(ROOT))
        if e['mode']=='noise':
            w=spice.Waves(r/'noise.raw');op=spice.Waves(r/'op.raw')
            x.update(noise_uv=float(np.sqrt(np.trapezoid(w['onoise_spectrum']**2,w.t))*1e6),vout_v=float(op['v(quiet)'][0]),bias_verified=True)
        else:
            w=spice.Waves(r/'wave.raw');v=w['v(quiet)'];last=w.t>=w.t[-1]*.95
            x.update(v_min=float(v.min()),v_max=float(v.max()),v_final=float(np.mean(v[last])),last_pp_mv=float(np.ptp(v[last])*1000))
            if e['mode']=='startup':
                final=float(np.mean(v[last]));outside=np.flatnonzero(np.abs(v-final)>.01)
                x['settle_10mv_us']=float(w.t[min(outside[-1]+1,len(w.t)-1)]*1e6) if len(outside) else 0.
            else:
                base=float(np.mean(v[w.t<.49e-6]));x['baseline_v']=base
                x['steps']=[dict(delta_ma=d,droop_mv=float((base-v[(w.t>=a)&(w.t<b)].min())*1e3),overshoot_mv=float((v[(w.t>=a)&(w.t<b)].max()-base)*1e3)) for d,a,b in [(0.1,.5e-6,.9e-6),(1,1.3e-6,1.7e-6),(4,2.1e-6,2.5e-6)]]
        rows.append(x)
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    (out/'summary.json').write_text(json.dumps(dict(campaign=str(c.relative_to(ROOT)),plan_sha256=caps.sha(c/'plan.json'),rows=rows,missing=missing,scope=p['scope']),indent=2)+'\n')
    print(json.dumps(dict(summary=str((out/'summary.json').relative_to(ROOT)),rows=rows,missing=missing),indent=2),flush=True)

def resume(c,workers):
    with (c/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=caps.verify(c)
        if len(watch.ngspice_cwds())+workers>4:raise ValueError('No global slots')
        def one(e):
            if completed(c,e):return
            if len(watch.ngspice_cwds())>=4:raise ValueError('Global quota changed')
            ex=spice.run((c/e['deck']).read_text(),spice.next_run_dir(c,e['name']),files=caps.files_for(c,e['variant']),timeout_s=600,meta=dict(mode=e['mode'],variant=e['variant']))
            print(e['name'],round(ex.elapsed_s,1),'s',ex.ok,flush=True)
        with ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(one,p['entries']))
        analyse(c)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',type=Path);g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path)
    ap.add_argument('--profiles',nargs='+',choices=('tt','fs','ss','ff'))
    ap.add_argument('--variants',nargs='+',required=False,default=['r4','s16']);ap.add_argument('--modes',nargs='+',choices=('startup','step','noise'),default=['startup','step','noise']);ap.add_argument('--pilot',action='store_true');ap.add_argument('--workers',type=int,choices=(1,2),default=2)
    a=ap.parse_args()
    if a.prepare:print(prepare(a.prepare.resolve(),a.variants,a.modes,a.pilot,a.profiles))
    elif a.resume:resume(a.resume.resolve(),a.workers)
    else:analyse(a.analyse.resolve())
