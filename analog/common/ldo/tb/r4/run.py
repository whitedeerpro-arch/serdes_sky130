"""HV18 r4 static-pin supply: physical passives, voltage trim and reference RC.

Calibrate at 27 C / HV3.3 / host1.8 / 6mA once PER MOS/RC model, then retain
that code across the independent HV, host, temperature and load grid. Offset
stress is an imposed input error, never a statistical mismatch qualification.
"""
import argparse
import fcntl
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from serdes_flow import feedback, project, spice, watch

ROOT=project.ROOT;SELF=Path(__file__).resolve();REG=ROOT/'analog/common/ldo/tb/regulation/run.py'
spec=importlib.util.spec_from_file_location('ldo_regulation',REG);reg=importlib.util.module_from_spec(spec);spec.loader.exec_module(reg)
sha=reg.sha
CELLS=reg.BIAS+[ROOT/('analog/common/ldo/spice/'+name) for name in ('ldo_passives.spice','ldo_hv18_core_r4.spice','pll_supply_hv18_r4.spice')]
RUNTIME=[SELF,REG,*[ROOT/('src/serdes_flow/'+name+'.py') for name in ('project','spice','watch','feedback')],ROOT/'config/pdk.toml',ROOT/'config/tools.toml']
OUT=ROOT/'results/analog/common/ldo/r4'
DC_VECTORS=('v(quiet)','v(bg)','v(rawref)','v(xdut.ref_local)','v(xdut.ibias)','v(xdut.xcore.gate)','v(xdut.xcore.casg)','v(xdut.xcore.va)','v(xdut.xcore.mid)','i(vdd)','i(vhost)')
AC_NODES=('quiet','xdut.ref_local','bg','xdut.ibias','xdut.xcore.gate')


def section(mos,rc):
    return mos if rc=='tt' else (rc if mos=='tt' else mos+'_'+rc)


def case(trim=43,hv=3.3,host=1.8,temp=27,load=6,offset=0,ac=False):
    return dict(trim=trim,hv_v=hv,host_v=host,temp_c=temp,load_ma=load,offset_v=offset,ac=ac)


def body(lib):
    lines=['* HV18 r4 static configuration: actual reference and physical passives',f'.lib "{project.model_library()}" {lib}']
    lines += [f'.include "{p.name}"' for p in CELLS]
    lines += ['Vdd vin 0 3.3 ac 0','Vhost host 0 1.8 ac 0','Venable enable 0 1.8','Voffset bg rawref 0 ac 0',
              'Xbg rawref host host host host vgi host 0 serdes_bias_ref trim=15',
              *[f'Vb{k} b{k} 0 {1.8 if (43>>k)&1 else 0}' for k in range(6)],
              'Xdut vin host quiet bg vgi enable b0 b1 b2 b3 b4 b5 fbret fbin 0 serdes_pll_supply_hv18_r4_probe',
              'Vtest fbin fbret 0 ac 0','Itest 0 fbin 0 ac 0','Iload quiet 0 6m',
              '.options reltol=1e-5 abstol=1p vntol=1u','.save all']
    return '\n'.join(lines)+'\n'


def ac_write(stem,kind):
    lines=[];names=[]
    for n,node in enumerate(AC_NODES):
        lines += [f'let r{n}=real(v({node}))',f'let q{n}=imag(v({node}))'];names += [f'r{n}',f'q{n}']
    return lines+[f'wrdata {stem}_{kind}.tsv '+ ' '.join(names),'destroy all']


def deck(entry):
    lines=[body(entry['section']),'.control','set num_threads=1','set filetype=binary','set wr_singlescale','set wr_vecnames']
    for n,c in enumerate(entry['cases']):
        stem=f'c{n:04d}'
        lines += [f"option temp={c['temp_c']}",f"alter Vdd dc={c['hv_v']}",f"alter Vhost dc={c['host_v']}",
                  f"alter Venable dc={c['host_v']}",f"alter Voffset dc={c['offset_v']}",
                  *[f"alter Vb{k} dc={c['host_v'] if (c['trim']>>k)&1 else 0}" for k in range(6)],
                  f"dc Iload {c['load_ma']}m {c['load_ma']+.001}m 1u",f'write {stem}_dc.raw '+' '.join(DC_VECTORS),'destroy all']
        if not c['ac']:continue
        lines += [f"alter Iload dc={c['load_ma']}m",'alter Vdd acmag=1','alter Vhost acmag=0','alter Vtest acmag=0','alter Itest acmag=0','ac dec 20 10 200meg']+ac_write(stem,'hv')
        lines += ['alter Vdd acmag=0','alter Vhost acmag=1','ac dec 20 10 200meg']+ac_write(stem,'host')
        lines += ['alter Vhost acmag=0','alter Vtest acmag=1','ac dec 20 10 10g','let tv=-v(fbret)/v(fbin)','let vr=real(tv)','let vi=imag(tv)',f'wrdata {stem}_voltage.tsv vr vi','destroy all',
                  'alter Vtest acmag=0','alter Itest acmag=1','ac dec 20 10 10g','let ti=i(Vtest)/(1-i(Vtest))','let ir=real(ti)','let ii=imag(ti)',f'wrdata {stem}_current.tsv ir ii','destroy all','alter Itest acmag=0']
    return '\n'.join(lines+['quit','.endc','.end',''])


def prepare(suite,calibration=None):
    c=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);(c/'source').mkdir(parents=True);(c/'prepared').mkdir()
    for path in [*CELLS,*RUNTIME]:
        target=c/'source'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    smoke=dict(name='smoke',mos='tt',rc='tt',section='tt',cases=[case()],smoke=True)
    entries=[smoke]
    libs=[('tt','tt')] if suite=='pilot' else [(m,r) for r in ('ll','hh','tt') for m in ('fs','ss','sf','ff','tt')]
    if suite=='grid':
        if calibration is None:raise ValueError('--calibration required')
        source=json.loads(calibration.read_text())
        if source['missing'] or source['suite']!='calibration':raise ValueError('Calibration incomplete/wrong suite')
        cp=verify(ROOT/source['campaign'])
        for path in CELLS:
            rel=str(path.relative_to(ROOT))
            if sha(path)!=cp['cell_sha256'][rel]:raise ValueError('DUT changed after calibration')
        codes=source['calibration_codes']
    for mos,rc in libs:
        if suite=='pilot':
            cases=[case(ac=True),case(trim=0),case(trim=63)]
        elif suite=='calibration':
            offsets=(-.09,0,.09) if (mos,rc)==('tt','tt') else (0,)
            cases=[case(trim=k,offset=offset) for offset in offsets for k in range(64)]
        else:
            code=codes[mos+':'+rc]['trim']
            cases=[case(trim=code,hv=h,host=u,temp=t,load=i,
                        ac=(h in (3.,3.6) and u in (1.65,1.95) and t in (-40,85) and i in (2,10)) or (h,u,t,i)==(3.3,1.8,27,6))
                   for h in (3.,3.6,3.3) for u in (1.65,1.95,1.8) for t in (85,-40,27) for i in (10,2,6)]
        entries.append(dict(name=mos+'_'+rc,mos=mos,rc=rc,section=section(mos,rc),cases=cases,smoke=False))
    for e in entries:
        p=c/'prepared'/(e['name']+'.cir');p.write_text(deck(e));e.update(deck=str(p.relative_to(c)),deck_sha256=sha(p))
    plan=dict(suite=suite,entries=entries,pdk_sha256=reg.pdk_identity(),cell_sha256={str(p.relative_to(ROOT)):sha(p) for p in CELLS},
              runtime={str(p.relative_to(ROOT)):sha(p) for p in RUNTIME},sources={str(p.relative_to(c)):sha(p) for p in (c/'source').rglob('*') if p.is_file()},
              calibration_summary=str(calibration.relative_to(ROOT)) if calibration else None,calibration_sha256=sha(calibration) if calibration else None,
              scope='Physical R/MIM, real BG, independent host/HV; no PEX, complete mismatch/noise or whole-PLL qualification')
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def verify(c):
    p=json.loads((c/'plan.json').read_text())
    if reg.pdk_identity()!=p['pdk_sha256']:raise ValueError('PDK changed')
    for rel,h in p['sources'].items():
        if sha(c/rel)!=h:raise ValueError('Source changed')
    for e in p['entries']:
        if sha(c/e['deck'])!=e['deck_sha256']:raise ValueError('Deck changed')
    return p


def completed(c,e):
    for r in reversed([c/e['name']]+sorted(c.glob(e['name']+'.r[0-9]*'))):
        try:
            ex=json.loads((r/'execution.json').read_text())
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=e['deck_sha256'] or sha(r/'tb.cir')!=e['deck_sha256']:continue
            if any(sha(r/path.name)!=sha(c/'source'/path.relative_to(ROOT)) or ex['inputs_sha256'][path.name]!=sha(c/'source'/path.relative_to(ROOT)) for path in CELLS):continue
            for n,x in enumerate(e['cases']):
                stem=f'c{n:04d}';w=spice.Waves(r/(stem+'_dc.raw'))
                if len(w.t)!=2 or not np.allclose(w.t,[x['load_ma']*.001,(x['load_ma']+.001)*.001],atol=1e-12,rtol=0) or any(key not in w for key in DC_VECTORS):raise ValueError('DC incomplete')
                if x['ac']:
                    for kind in ('hv','host','voltage','current'):
                        a=np.loadtxt(r/(stem+'_'+kind+'.tsv'),skiprows=1);hi=kind in ('voltage','current');count=181 if hi else 147;cols=3 if hi else 11
                        expected=np.geomspace(10,1e10 if hi else 2e8,count)
                        if a.shape!=(count,cols) or not np.all(np.isfinite(a)) or not np.allclose(a[:,0],expected,rtol=1e-6):raise ValueError('AC incomplete')
            return r
        except (OSError,ValueError,KeyError):pass
    return None


def interp(a,hz,col=0):
    v=a[:,1+col*2]+1j*a[:,2+col*2]
    return float(np.exp(np.interp(np.log(hz),np.log(a[:,0]),np.log(np.abs(v)))))


def analyse(c,p):
    rows=[];missing=[]
    for e in p['entries'][1:]:
        r=completed(c,e)
        if r is None:missing.append(e['name']);continue
        for n,x in enumerate(e['cases']):
            stem=f'c{n:04d}';dc=r/(stem+'_dc.raw');w=spice.Waves(dc)
            row=dict(x,mos=e['mos'],rc=e['rc'],vout_v=float(w['v(quiet)'][0]),vbg_v=float(w['v(bg)'][0]),ref_local_v=float(w['v(xdut.ref_local)'][0]),
                     vin_excess_ua=float((-w['i(vdd)'][0]-x['load_ma']*.001)*1e6),host_power_mw=float(-w['i(vhost)'][0]*x['host_v']*1000),
                     gate_v=float(w['v(xdut.xcore.gate)'][0]),casg_v=float(w['v(xdut.xcore.casg)'][0]),mid_v=float(w['v(xdut.xcore.mid)'][0]),
                     run=str(r.relative_to(ROOT)),stem=stem)
            files=[dc,r/'execution.json']
            if x['ac']:
                hv=np.loadtxt(r/(stem+'_hv.tsv'),skiprows=1);host=np.loadtxt(r/(stem+'_host.tsv'),skiprows=1)
                v=np.loadtxt(r/(stem+'_voltage.tsv'),skiprows=1);i=np.loadtxt(r/(stem+'_current.tsv'),skiprows=1)
                gain=feedback.middlebrook(v[:,1]+1j*v[:,2],i[:,1]+1j*i[:,2])
                row.update(psrr_20mhz_db=float(-20*np.log10(interp(hv,20e6))),host_300khz_v_v=interp(host,300e3),host_20mhz_v_v=interp(host,20e6),
                           host_1mhz_v_v=interp(host,1e6),crossings=feedback.unity_crossings(v[:,0],gain),gain_10ghz=float(abs(gain[-1])))
                files += [r/(stem+'_'+kind+'.tsv') for kind in ('hv','host','voltage','current')]
            row['evidence']={path.name:sha(path) for path in files};rows.append(row)
    codes={}
    if p['suite']=='calibration':
        for key in sorted({(r['mos'],r['rc']) for r in rows}):
            choices=[r for r in rows if (r['mos'],r['rc'])==key and r['offset_v']==0]
            best=min(choices,key=lambda r:abs(r['vout_v']-1.8));codes[':'.join(key)]=dict(trim=best['trim'],vout_v=best['vout_v'],source_stem=best['stem'],source_run=best['run'])
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    data=dict(campaign=str(c.relative_to(ROOT)),plan_sha256=sha(c/'plan.json'),suite=p['suite'],rows=rows,missing=missing,calibration_codes=codes,analyzer_sha256=sha(SELF),scope=p['scope'])
    (out/'summary.json').write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(analysis=str(out.relative_to(ROOT)),cases=len(rows),ac_cases=sum(x['ac'] for x in rows),missing=missing,
                         rows=rows if len(rows)<=3 else None,calibration_codes=codes),indent=2),flush=True)


def resume(c,workers):
    with (c/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=verify(c)
        for rel,h in p['runtime'].items():
            if sha(ROOT/rel)!=h:raise ValueError(f'Runtime changed: {rel}')
        active=watch.ngspice_cwds()
        if any(x.is_relative_to(c) for x in active) or len(active)+workers>4:raise ValueError('No slots/already active')
        files={path.name:c/'source'/path.relative_to(ROOT) for path in CELLS};e=p['entries'][0]
        if completed(c,e) is None:spice.run((c/e['deck']).read_text(),spice.next_run_dir(c,e['name']),files=files,timeout_s=240)
        if completed(c,e) is None:raise ValueError('DC smoke failed')
        jobs=[((c/e['deck']).read_text(),spice.next_run_dir(c,e['name']),dict(files=files,timeout_s=60+len(e['cases'])*15)) for e in p['entries'][1:] if completed(c,e) is None]
        spice.run_many(jobs,workers=workers,smoke=False);analyse(c,p)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',choices=('pilot','calibration','grid'));g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path)
    ap.add_argument('--calibration',type=Path);ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare:print(prepare(a.prepare,a.calibration.resolve() if a.calibration else None).relative_to(ROOT))
    elif a.resume:resume(a.resume.resolve(),a.workers)
    else:analyse(a.analyse.resolve(),verify(a.analyse.resolve()))
