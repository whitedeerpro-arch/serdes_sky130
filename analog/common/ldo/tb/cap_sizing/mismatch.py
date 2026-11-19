"""Local mismatch pilot for the frozen 70pF LDO; full PDK, real BG/R/MIM.

Each sample sweeps all 64 trim codes at 27C/HV3.3/host1.8/6mA, then holds
the nearest code at its profile's supply/temperature and 2/6/10mA loads.
Dual injection and HV PSRR are measured at 10mA. No resampling within a chip.
This is conditional local mismatch, not global statistical process/yield signoff.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil

import numpy as np
from serdes_flow import feedback, mc, project, spice, stats, watch

SELF = Path(__file__).resolve()
ROOT = project.ROOT
spec = importlib.util.spec_from_file_location('ldo_cap_mc_parent', SELF.with_name('run.py'))
caps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(caps)
OUT = ROOT/'results/analog/common/ldo/smallcap_mismatch'
PROFILES = {'tt': dict(section='tt', hv=3.3, host=1.8, temp=27, fixed=42),
            'fs': dict(section='fs_ll', hv=3., host=1.95, temp=85, fixed=41)}
SCALARS = ['fixed_v', 'best_code', 'cal_v', 'code0_v', 'code63_v', 'min_step_v',
           'out2_v', 'out6_v', 'out10_v', 'bg_v', 'va_v', 'gate_v']


def bits(code, host):
    lines = []
    for k in range(6):
        lines += [f'let bitval = ({host})*(floor(({code})/{2**k})-2*floor(({code})/{2**(k+1)}))',
                  f'alter Vb{k} dc=$&bitval']
    return lines


def deck(profile, samples, seed, mismatch=True):
    p = PROFILES[profile]
    netlist = caps.r4.body(p['section'] + ('_mm' if mismatch else ''))
    # Scalars live in const because each OP/AC plot is destroyed immediately.
    lines = ['option temp=27', 'alter Vdd dc=3.3', 'alter Vhost dc=1.8',
             'alter Venable dc=1.8', 'alter Iload dc=6m',
             'alter Vdd acmag=0', 'alter Vhost acmag=0',
             'alter Vtest acmag=0', 'alter Itest acmag=0',
             'let calv=unitvec(64)', 'let code=0', 'dowhile code < 64']
    lines += bits('code', '1.8')
    lines += ['op', 'let const.calv[const.code]=v(quiet)', 'destroy all',
              'setplot const', 'let code=code+1', 'end',
              'let best_code=0', 'let best_err=abs(calv[0]-1.8)',
              'let min_step_v=1', 'let code=1', 'dowhile code < 64',
              'let err=abs(calv[code]-1.8)', 'if err < best_err',
              'let best_code=code', 'let best_err=err', 'end',
              'let step=calv[code]-calv[code-1]', 'if step < min_step_v',
              'let min_step_v=step', 'end', 'let code=code+1', 'end',
              f'let fixed_v=calv[{p["fixed"]}]', 'let cal_v=calv[best_code]',
              'let code0_v=calv[0]', 'let code63_v=calv[63]',
              f'option temp={p["temp"]}', f'alter Vdd dc={p["hv"]}',
              f'alter Vhost dc={p["host"]}', f'alter Venable dc={p["host"]}']
    lines += bits('best_code', str(p['host']))
    for load in (2, 6, 10):
        lines += [f'alter Iload dc={load}m', 'op',
                  f'let const.out{load}_v=v(quiet)']
        if load == 10:
            lines += ['let const.bg_v=v(bg)', 'let const.va_v=v(xdut.xcore.va)',
                      'let const.gate_v=v(xdut.xcore.gate)']
        lines += ['destroy all', 'setplot const']
    lines += ['alter Vdd acmag=1', 'ac dec 20 10 200meg',
              'let hr=real(v(quiet))', 'let hi=imag(v(quiet))',
              'wrdata hv.tsv hr hi', 'destroy all', 'setplot const',
              'alter Vdd acmag=0', 'alter Vtest acmag=1',
              'ac dec 20 10 10g', 'let tv=-v(fbret)/v(fbin)',
              'let vr=real(tv)', 'let vi=imag(tv)',
              'wrdata voltage.tsv vr vi', 'destroy all', 'setplot const',
              'alter Vtest acmag=0', 'alter Itest acmag=1',
              'ac dec 20 10 10g', 'let ti=i(Vtest)/(1-i(Vtest))',
              'let ir=real(ti)', 'let ii=imag(ti)',
              'wrdata current.tsv ir ii', 'destroy all', 'setplot const',
              'alter Itest acmag=0', 'op']
    return mc.deck(netlist, samples, seed=seed, analysis='\n'.join(lines),
                   lets={k:'const.'+k for k in SCALARS}, setup='set numdgt=15', profile=True)


def prepare(samples, chunk, seed, profiles):
    camp = OUT/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    (camp/'cells').mkdir(parents=True)
    v = next(v for v in caps.VARIANTS if v['name']=='b32_h2')
    for name, data in caps.cell_sources(v).items():
        (camp/'cells'/name).write_text(data)
    for src in [SELF, SELF.with_name('run.py'), caps.r4.SELF,
                ROOT/'src/serdes_flow/mc.py', ROOT/'src/serdes_flow/spice.py',
                ROOT/'src/serdes_flow/feedback.py']:
        dst=camp/'source'/src.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src,dst)
    entries=[]
    (camp/'prepared').mkdir()
    for profile in profiles:
        for kind in ('nominal', 'repro', 'mc'):
            chunks = ([(0, seed, 1)] if kind=='nominal' else
                      [(0,seed*1000,1)] if kind=='repro' else mc.chunks(samples,seed,per=chunk))
            for k, s, n in chunks:
                name=f'{profile}_{kind}_{k:03d}'
                path=camp/'prepared'/(name+'.cir')
                path.write_text(deck(profile,n,s,kind!='nominal'))
                entries.append(dict(name=name,profile=profile,kind=kind,seed=s,samples=n,
                                    deck=str(path.relative_to(camp))))
    plan=dict(samples=samples,chunk=chunk,seed=seed,profiles=profiles,entries=entries,
              variant=v,pdk=caps.r4.reg.pdk_identity(),
              sha256={str(p.relative_to(camp)):caps.sha(p) for p in camp.rglob('*') if p.is_file()},
              gates=caps.GATES,
              scope='schematic conditional local mismatch; factory nearest-code selection; 10mA AC only; no PNP mismatch, global statistical process, startup, full PEX or PLL')
    (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    return camp


def jobs(camp):
    p=json.loads((camp/'plan.json').read_text())
    for rel,h in p['sha256'].items():
        if caps.sha(camp/rel)!=h:raise ValueError('Frozen input changed: '+rel)
    if p['pdk']!=caps.r4.reg.pdk_identity():raise ValueError('PDK changed')
    files={s.name:s for s in (camp/'cells').glob('*.spice')}
    return p, [((camp/e['deck']).read_text(), camp/e['name'],
                dict(files=files,timeout_s=180+e['samples']*90)) for e in p['entries']]


def spectra(path,n,length,high):
    lines=[s for s in path.read_text().splitlines() if s.strip() and s.split()[0]!='frequency']
    a=np.array([[float(x) for x in s.split()] for s in lines])
    if a.shape!=(n*length,3) or not np.all(np.isfinite(a)):
        raise ValueError('Incomplete AC: '+str(path))
    a=a.reshape(n,length,3)
    if not np.allclose(a[:,:,0],np.geomspace(10,high,length),rtol=1e-6):
        raise ValueError('Invalid frequency axis: '+str(path))
    return a


def analyse(camp):
    p,js=jobs(camp)
    resolved=mc.completed(js)
    if any(r is None for r in resolved):raise ValueError('Incomplete MC chunks')
    rows=[]
    for e,r in zip(p['entries'],resolved):
        ss=mc.read(r)
        hv=spectra(r/'hv.tsv',len(ss),147,2e8)
        av=spectra(r/'voltage.tsv',len(ss),181,1e10)
        ai=spectra(r/'current.tsv',len(ss),181,1e10)
        for i,s in enumerate(ss):
            if not all(np.isfinite(s[k]) for k in SCALARS):raise ValueError('Missing scalar')
            h=hv[i];v=av[i];a=ai[i]
            cross=feedback.unity_crossings(v[:,0],feedback.middlebrook(v[:,1]+1j*v[:,2],a[:,1]+1j*a[:,2]))
            psrr=float(-20*np.interp(np.log(2e7),np.log(h[:,0]),np.log10(np.hypot(h[:,1],h[:,2]))))
            dc=all(caps.GATES['vout_min']<=s[f'out{x}_v']<=caps.GATES['vout_max'] for x in (2,6,10))
            stable=len(cross)==1 and cross[0]['direction']=='down' and cross[0]['pm_deg']>=60
            rows.append(dict(s,profile=e['profile'],kind=e['kind'],chunk_seed=e['seed'],sample=i,
                             run=str(r.relative_to(ROOT)),psrr20_db=psrr,crossings=cross,
                             dc_pass=dc,ac_pass=stable and psrr>=34,
                             trim_pass=s['min_step_v']>0 and s['code0_v']<=1.8<=s['code63_v']))
    groups={}
    for profile in p['profiles']:
        rs=[r for r in rows if r['profile']==profile and r['kind']=='mc']
        if len(rs)!=p['samples']:raise ValueError('Wrong total count')
        replay=next(r for r in rows if r['profile']==profile and r['kind']=='repro')
        np.testing.assert_allclose([replay[k] for k in SCALARS],
                                   [rs[0][k] for k in SCALARS],rtol=1e-11,atol=1e-13)
        for filename,length,high in [('hv.tsv',147,2e8),('voltage.tsv',181,1e10),('current.tsv',181,1e10)]:
            a=spectra(ROOT/replay['run']/filename,1,length,high)[0]
            b=spectra(ROOT/rs[0]['run']/filename,min(p['chunk'],p['samples']),length,high)[0]
            np.testing.assert_allclose(a,b,rtol=1e-11,atol=1e-13)
        if len(rs)>1 and np.std([r['fixed_v'] for r in rs])<1e-12:
            raise ValueError('No observable mismatch variation')
        passed=sum(r['dc_pass'] and r['ac_pass'] and r['trim_pass'] for r in rs)
        fields={k:stats.summary([r[k] for r in rs]) if len(rs)>1 else dict(value=rs[0][k])
                for k in ['fixed_v','cal_v','best_code','out2_v','out6_v','out10_v','psrr20_db']}
        fields['pm_deg']=stats.summary([r['crossings'][0]['pm_deg'] for r in rs]) if len(rs)>1 and all(len(r['crossings'])==1 for r in rs) else None
        groups[profile]=dict(samples=len(rs),passed=passed,yield95=stats.yield_ci(passed,len(rs)),
                             seed_replay_pass=True,metrics=fields)
    dest=camp/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    dest.mkdir(parents=True)
    out=dict(campaign=str(camp.relative_to(ROOT)),scope=p['scope'],groups=groups,rows=rows)
    (dest/'summary.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(summary=str((dest/'summary.json').relative_to(ROOT)),groups=groups),indent=2),flush=True)
    return dest/'summary.json'


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path)
    ap.add_argument('--samples',type=int,default=32);ap.add_argument('--chunk',type=int,default=4)
    ap.add_argument('--seed',type=int,default=70);ap.add_argument('--profiles',nargs='+',choices=PROFILES,default=list(PROFILES))
    ap.add_argument('--workers',type=int,choices=(1,2),default=2)
    args=ap.parse_args()
    if args.prepare:print(prepare(args.samples,args.chunk,args.seed,args.profiles))
    elif args.resume:
        camp=args.resume.resolve();p,js=jobs(camp)
        if len(watch.ngspice_cwds())+args.workers>4:raise ValueError('Insufficient global slots')
        mc.run_many(js,workers=args.workers);analyse(camp)
    else:analyse(args.analyse.resolve())
