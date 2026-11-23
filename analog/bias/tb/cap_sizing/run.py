"""Frozen two-loop bandgap capacitor study with explicit light/dist boundaries.

Original sources stay unchanged. Test-only wrappers expose both loop breaks;
all injection sources, supplies and loads belong to the bench. Physical-cap
variants use explicit1pF SKY130 MIM units, including resistor/capacitor corners.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np
from serdes_flow import feedback,model_library,project,spice,watch

ROOT=project.ROOT;SELF=Path(__file__).resolve()
SOURCES=[ROOT/p for p in ('analog/common/devices/spice/sky130_primitives.spice',
    'analog/common/devices/spice/sky130_pfet_lvt.spice','analog/bias/spice/bandgap.spice',
    'analog/bias/spice/bias_dist.spice')]
OUT=ROOT/'results/analog/bias/cap_sizing'
VARIANTS=[dict(name=name,cc_pf=cc,cb_pf=cb,cg_pf=cg,physical=physical,total_pf=cc+cb+cg)
          for name,cc,cb,cg,physical in [('legacy',6,5,2,False),('phys6',6,5,2,True),
          ('cc4',4,5,2,True),('cc3',3,5,2,True),('cc2',2,5,2,True),
          ('bg3',6,3,2,True),('gi1',6,5,1,True),('gi0',6,5,0,True),('cc4_gi1',4,5,1,True)]]
VARIANTS += [dict(name='cc4_r30',cc_pf=4,cb_pf=5,cg_pf=2,physical=True,total_pf=11,rz_ohm=30000),
             dict(name='cc3_r40',cc_pf=3,cb_pf=5,cg_pf=2,physical=True,total_pf=10,rz_ohm=40000)]
VARIANTS += [dict(name='phys6_rp',cc_pf=6,cb_pf=5,cg_pf=2,physical=True,total_pf=13,rz_ohm=20000,physical_rz=True),
             dict(name='cc4_r30p',cc_pf=4,cb_pf=5,cg_pf=2,physical=True,total_pf=11,rz_ohm=30000,physical_rz=True)]
PROFILES=[('tt',1.8,27),('ss_hh',1.65,-40),('ff_ll',1.95,85),('fs_ll',1.95,-40),('sf_hh',1.65,85)]


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def change_subckt(text,name,edit):
    pattern=rf'(?ims)^\.subckt {name}\b.*?^\.ends {name}\b[^\n]*'
    matches=list(re.finditer(pattern,text))
    if len(matches)!=1:raise ValueError('Subcircuit changed: '+name)
    m=matches[0];return text[:m.start()]+edit(m[0])+text[m.end():]


def cell_sources(v,probe=True):
    cells={p.name:p.read_text() for p in SOURCES}
    bg=cells['bandgap.spice'];dist=cells['bias_dist.spice']
    for old,new in [('cc=6p',f'cc={v["cc_pf"]}p')]:
        if bg.count(old)!=1:raise ValueError('Miller parameter anchor changed')
        bg=bg.replace(old,new)
    if v.get('rz_ohm',20000)!=20000:
        if bg.count('rz=20k')!=1:raise ValueError('Compensation resistor anchor changed')
        bg=bg.replace('rz=20k',f'rz={v["rz_ohm"]}')
    dist=dist.replace('cvgi=2p cvbg=5p',f'cvgi={v["cg_pf"]}p cvbg={v["cb_pf"]}p')
    if v['physical']:
        for old,new in [('Cc cz out {cc}',f'Xcc cz out bg_mim{v["cc_pf"]}'),
                        ('Cvgi vgi vdd {cvgi}',f'Xcvgi vgi vdd bg_mim{v["cg_pf"]}' if v['cg_pf'] else '* Explicit no-added-Cvgi candidate')]:
            if bg.count(old)!=1:raise ValueError('Bandgap capacitor anchor changed')
            bg=bg.replace(old,new)
        if dist.count('Cvbg vbg vss {cvbg}')!=1:raise ValueError('Vbg capacitor anchor changed')
        dist=dist.replace('Cvbg vbg vss {cvbg}',f'Xcvbg vbg vss bg_mim{v["cb_pf"]}')
        cells['bg_capacitors.spice']='\n'.join(f'.subckt bg_mim{n} a b\n'+'\n'.join(
            f'X{k} a b sky130_fd_pr__cap_mim_m3_1 w=22.1965 l=22.1965' for k in range(n))+f'\n.ends bg_mim{n}'
            for n in sorted({v['cc_pf'],v['cb_pf'],v['cg_pf']}-{0}))+'\n'
    if v.get('physical_rz'):
        if bg.count('Rz o1 cz {rz}')!=1:raise ValueError('Physical compensation resistor anchor changed')
        nodes=['o1','rz1','rz2','rz3','cz']
        bg=bg.replace('Rz o1 cz {rz}','\n'.join(f'Xrz{k} {nodes[k]} {nodes[k+1]} vss bg_rz_piece' for k in range(4)))
        length=(v.get('rz_ohm',20000)/4-378)/317
        cells['bg_capacitors.spice']+=f'\n.subckt bg_rz_piece a b sub\nXr a b sub sky130_fd_pr__res_high_po w=1 l={length:.12g}\n.ends bg_rz_piece\n'
    if probe:
        def edit_bg(s):
            # Break the common PMOS gate line after the core amplifier. A
            # one-input cut leaves the other differential feedback branch
            # closed and is not the total BG return ratio.
            head,rest=s.split('\n',1)
            head=head.replace(' vg vgi vdd vss',' core_return vgi vdd vss core_input vi_return vi_input')
            rest=re.sub(r'\bvg\b','core_input',rest);rest=re.sub(r'\bs\b','vi_return',rest)
            s=head+'\n'+rest
            for old,new in [('Xamp tb ta core_input nb','Xamp tb ta core_return nb'),
                            ('Xamp2 vi_return vbg','Xamp2 vi_input vbg')]:
                if s.count(old)!=1:raise ValueError('Bandgap probe anchor changed: '+old)
                s=s.replace(old,new)
            return s.replace('serdes_bandgap','serdes_bandgap_probe')
        bg=change_subckt(bg,'serdes_bandgap',edit_bg)
        def edit_ref(s):
            old='vgi vdd vss params:'
            if s.count(old)!=1:raise ValueError('Reference probe ports changed')
            s=s.replace(old,'vgi vdd vss core_return core_input vi_return vi_input params:')
            s=s.replace('vg vgi vdd vss serdes_bandgap ','core_return vgi vdd vss core_input vi_return vi_input serdes_bandgap_probe ')
            return s.replace('serdes_bias_ref','serdes_bias_ref_probe')
        dist=change_subckt(dist,'serdes_bias_ref',edit_ref)
    cells['bandgap.spice']=bg;cells['bias_dist.spice']=dist;return cells


def body(e,lib):
    lines=['* Independent bandgap capacitor/loop card',f'.lib "{lib}" {e["section"]}']
    lines += [f'.include "{name}"' for name in e['files']]
    lines += [f'Vdd vdd 0 {e["supply_v"]} ac 0',
        'Xref vbg i0 i1 i2 i3 vgi vdd 0 cr ci vr vi serdes_bias_ref_probe',
        *[f'Vi{k} i{k} 0 0.7' for k in range(4)],
        'Vcore ci cr 0 ac 0','Icore 0 ci 0 ac 0','Vvi vi vr 0 ac 0','Ivi 0 vi 0 ac 0']
    if e['load']=='light':lines += ['Xcopy load vgi vdd serdes_bias_pcopy n=4','Vload load 0 0.9']
    else:lines += ['Xccml ocml vgi vdd serdes_bias_pcopy n=85','Xcctle octle vgi vdd serdes_bias_pcopy n=20',
        'Xccp ocp vgi vdd serdes_bias_pcopy n=20','Vmcml ocml vcml 0','Xdcml vcml 0 serdes_bias_cml',
        'Vmctle octle vctle 0','Xdctle vctle 0 serdes_bias_ctle','Vmcp ocp vbn 0','Xdcp vbn vbp vdd 0 serdes_bias_cp',
        'Vtop top 0 1.0','Xrl top dr 0 sky130_fd_pr__res_high_po w=3 l=3.54','Xtail dr vcml 0 0 serdes_nfet w=20 l=.5 nf=4']
    return '\n'.join(lines+[f'.temp {e["temp_c"]}',
        '.nodeset v(vbg)=1.23 v(vr)=1.23 v(cr)=.9 v(ci)=.9 v(xref.xbg.ta)=.95 v(xref.xbg.tb)=.95 v(vgi)=.9',
        '.options reltol=1e-5 abstol=1p vntol=1u'])+'\n'


def deck(e,lib):
    lines=[body(e,lib),'.control','set num_threads=1','set filetype=binary','set wr_singlescale','set wr_vecnames',
        'op','write op.raw v(vbg) v(vgi) v(vr) v(cr) i(Vi0) i(Vdd)','destroy all']
    if e.get('smoke'):return '\n'.join(lines+['quit','.endc','.end',''])
    for name,ret,inp in [('core','cr','ci'),('vi','vr','vi')]:
        vs='V'+name;isrc='I'+name
        lines += [f'alter {vs} acmag=1','ac dec 25 10 1g',f'let tv=-v({ret})/v({inp})',
                  'let r=real(tv)','let q=imag(tv)',f'wrdata {name}_v.tsv r q','destroy all',f'alter {vs} acmag=0',
                  f'alter {isrc} acmag=1','ac dec 25 10 1g',f'let ti=i({vs})/(1-i({vs}))',
                  'let r=real(ti)','let q=imag(ti)',f'wrdata {name}_i.tsv r q','destroy all',f'alter {isrc} acmag=0']
    lines += ['alter Vdd acmag=1','ac dec 25 10 100meg']
    nodes=['vbg','vgi']+(['vcml','vbn','vbp'] if e['load']=='dist' else ['load'])
    for k,node in enumerate(nodes):lines += [f'let r{k}=real(v({node}))',f'let q{k}=imag(v({node}))']
    lines += ['wrdata supply.tsv '+' '.join(f'r{k} q{k}' for k in range(len(nodes))),'destroy all','quit','.endc','.end','']
    return '\n'.join(lines)


def prepare(names,pilot,reduced):
    vs=[v for v in VARIANTS if v['name'] in names]
    if len(vs)!=len(set(names)):raise ValueError('Unknown candidate')
    c=OUT/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');(c/'prepared').mkdir(parents=True)
    for p in [SELF,*SOURCES,*[ROOT/f'src/serdes_flow/{n}.py' for n in ('spice','feedback','model_library','project')]]:
        q=c/'source'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
    primitives=sorted(set(re.findall(r'\bsky130_fd_pr__\w+','\n'.join(t for v in vs for t in cell_sources(v).values()))))
    entries=[]
    for v in vs:
        folder=c/'variants'/v['name'];folder.mkdir(parents=True)
        for name,text in cell_sources(v).items():(folder/name).write_text(text)
        profiles=PROFILES[:1] if pilot else PROFILES
        for section,supply,temp in profiles:
            lib=project.model_library()
            if reduced:
                dest=c/'models'/section
                if not dest.exists():model_library.build(lib,section,primitives,dest)
                lib=dest/'sky130.lib.spice'
            for load in ('light','dist'):
                e=dict(name=f'{v["name"]}_{section}_{load}',variant=v['name'],section=section,supply_v=supply,temp_c=temp,load=load,files=list(cell_sources(v)))
                p=c/'prepared'/(e['name']+'.cir');p.write_text(deck(e,lib));e['deck']=str(p.relative_to(c));entries.append(e)
    plan=dict(variants=vs,entries=entries,pdk_id=project.pdk_installation_id(),model_library_sha256=sha(project.model_library()),
        reduced=reduced,pilot=pilot,scope='Two coupled BG loops with explicit external dual injection; light n4 clamp versus CML85/CTLE20/CP20 distribution; no system qualification',
        sha256={str(p.relative_to(c)):sha(p) for p in c.rglob('*') if p.is_file()})
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def verify(c):
    p=json.loads((c/'plan.json').read_text())
    if p['pdk_id']!=project.pdk_installation_id() or p['model_library_sha256']!=sha(project.model_library()):raise ValueError('PDK changed')
    for rel,h in p['sha256'].items():
        if sha(c/rel)!=h:raise ValueError('Frozen input changed: '+rel)
    return p


def completed(c,e):
    for d in reversed([c/e['name']]+sorted(c.glob(e['name']+'.r[0-9]*'))):
        try:
            ex=json.loads((d/'execution.json').read_text())
            if ex['exit_code'] or ex['timed_out'] or ex['log_failures'] or (d/'tb.cir').read_text()!=(c/e['deck']).read_text():continue
            for f in ('core_v','core_i','vi_v','vi_i','supply'):
                a=np.loadtxt(d/(f+'.tsv'),skiprows=1)
                n=176 if f=='supply' else 201
                if a.shape!=(n,(11 if e['load']=='dist' else 7) if f=='supply' else 3) or not np.all(np.isfinite(a)) or not np.allclose(a[:,0],np.geomspace(10,1e8 if f=='supply' else 1e9,n),rtol=1e-6):raise ValueError('Incomplete spectrum')
            w=spice.Waves(d/'op.raw')
            if len(w.t)!=1:raise ValueError('Incomplete OP')
            return d
        except (OSError,ValueError,KeyError):pass
    return None


def analyse(c):
    p=verify(c);rows=[];missing=[]
    for e in p['entries']:
        d=completed(c,e)
        if d is None:missing.append(e['name']);continue
        w=spice.Waves(d/'op.raw');row=dict(e,run=str(d.relative_to(ROOT)),vbg_v=float(w['v(vbg)'][0]),iref_ua=float(w['i(vi0)'][0]*1e6),power_uw=float(-w['i(vdd)'][0]*e['supply_v']*1e6),loops={})
        for port in ('core','vi'):
            a=np.loadtxt(d/(port+'_v.tsv'),skiprows=1);b=np.loadtxt(d/(port+'_i.tsv'),skiprows=1)
            gain=feedback.middlebrook(a[:,1]+1j*a[:,2],b[:,1]+1j*b[:,2]);cross=feedback.unity_crossings(a[:,0],gain)
            row['loops'][port]=dict(crossings=cross,pm60=len(cross)==1 and cross[0]['direction']=='down' and cross[0]['pm_deg']>=60)
        a=np.loadtxt(d/'supply.tsv',skiprows=1)
        row['vbg_host_v_v']={str(f):float(np.interp(np.log(f),np.log(a[:,0]),np.hypot(a[:,1],a[:,2]))) for f in (1e3,1e5,1e6,2e7)}
        rows.append(row)
    summary=[]
    for v in p['variants']:
        rs=[r for r in rows if r['variant']==v['name']]
        summary.append(dict(v,cases=len(rs),stable60=bool(rs) and all(r['loops'][x]['pm60'] for r in rs for x in ('core','vi')),
            core_min_pm=min((k['pm_deg'] for r in rs for k in r['loops']['core']['crossings']),default=None),
            vi_min_pm=min((k['pm_deg'] for r in rs for k in r['loops']['vi']['crossings']),default=None)))
    target=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');target.mkdir(parents=True)
    out=dict(campaign=str(c.relative_to(ROOT)),rows=rows,missing=missing,summary=summary,scope=p['scope'])
    (target/'summary.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n');print(json.dumps(dict(summary=str((target/'summary.json').relative_to(ROOT)),variants=summary,missing=missing),indent=2),flush=True)
    return out


def resume(c,workers):
    with (c/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=verify(c)
        if len(watch.ngspice_cwds())+workers>4:raise ValueError('Global slots occupied')
        def one(e):
            if completed(c,e):return
            dest=spice.next_run_dir(c,e['name']);files={q.name:q for q in (c/'variants'/e['variant']).glob('*.spice')}
            ex=spice.run((c/e['deck']).read_text(),dest,files=files,timeout_s=180)
            print(e['name'],round(ex.elapsed_s,1),ex.ok,flush=True)
        with ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(one,p['entries']))
        return analyse(c)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path)
    ap.add_argument('--variants',nargs='+',default=['legacy','phys6','cc4','cc3','bg3','gi1']);ap.add_argument('--pilot',action='store_true')
    ap.add_argument('--reduced',action='store_true');ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare:print(prepare(a.variants,a.pilot,a.reduced))
    elif a.resume:resume(a.resume.resolve(),a.workers)
    else:analyse(a.analyse.resolve())
