"""Frozen, resumable LDO DC/AC screening, ideal reference/current/load boundary.

The feedback injection retains the DC operating point. -V(div)/V(fb) is a
voltage return-ratio estimate at the high-impedance amplifier input; full
transient checks are required before interpreting stability as qualified.
"""
import argparse
import fcntl
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from serdes_flow import project, spice, watch

ROOT = project.ROOT
SELF = Path(__file__).resolve()
CORE = ROOT / "analog/common/ldo/spice/ldo_hv18_core_r4.spice"
BIAS = [ROOT/('analog/common/'+p) for p in ('devices/spice/sky130_primitives.spice','devices/spice/sky130_pfet_lvt.spice','devices/spice/cmos_logic.spice','bias/spice/bandgap.spice','bias/spice/bias_dist.spice')]
SOURCES = [SELF, CORE, *BIAS, ROOT/"src/serdes_flow/spice.py", ROOT/"src/serdes_flow/project.py", ROOT/"src/serdes_flow/watch.py", ROOT/"config/pdk.toml", ROOT/"config/tools.toml"]
OUT = ROOT/"results/analog/common/ldo/regulation"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pdk_identity():
    root = project.model_library().parents[2]
    return {str(p): sha(p) for folder in ("libs.tech/ngspice", "libs.ref/sky130_fd_pr/spice")
            for p in sorted((root/folder).rglob("*")) if p.is_file()}


def prefix(v, t, ma):
    return f"v{round(v*1000)}_t{t}_i{ma}"


def deck(process, cases, opts, smoke=False):
    text = ["* HV18 regulator screening: see plan for reference and current boundary", f'.lib "{project.model_library()}" {process}',
            '.include "core.spice"', "Vdd vin 0 3.3 ac 0", f"Vhost host 0 {opts.get('host_v',1.8)} ac 0", "Vref ref 0 1.23 ac 0",
            "Iref host ibias 10u", "Voff off 0 0", "Iload out 0 6m", "Rbleed out 0 100k",
            "Rtop out div 38k", "Rbottom div 0 82k", "Vtest fb div 0 ac 0", f"Cout out 0 {opts['cout_pf']}p",
            f"Xreg vin out ref ibias fb off 0 serdes_ldo_hv18_core lp={opts['lp_um']} cc={opts['cc_pf']}p rz={opts['rz_ohm']} rhv={opts['rhv_ohm']} chv={opts['chv_pf']}p",
            ".options reltol=1e-5 abstol=1p vntol=1u", ".save all", ".control", "set num_threads=1", "set filetype=binary",
            "set wr_singlescale", "set wr_vecnames"]
    if opts.get('real_bias'):
        text.remove('Iref host ibias 10u')
        text[text.index('Vref ref 0 1.23 ac 0')]='Vref ref bg 0 ac 0'
        extra=[f'.include "{path}"' for path in opts['bias_includes']]
        extra+=['Xbg bg host host host host vgi host 0 serdes_bias_ref trim=15','Xcopy ibias vgi host serdes_bias_pcopy n=4']
        text[3:3]=extra
    for v,t,ma in cases:
        name = prefix(v,t,ma)
        text += [f"option temp={t}", f"alter Vdd dc={v}", f"alter Iload dc={ma}m",
                 f"dc Iload {ma}m {ma+.001}m 1u", f"write {name}_dc.raw v(out) v(ref) v(host) v(xreg.gate) v(xreg.x) v(xreg.tail) v(ibias) v(xreg.bp) i(Vdd) i(Vhost)", "destroy all"]
        if smoke:
            continue
        text += ["alter Vtest acmag=1", "alter Vdd acmag=0", "ac dec 50 10 1g",
                 "let loop=-v(div)/v(fb)", "let lr=real(loop)", "let li=imag(loop)", f"wrdata {name}_loop.tsv lr li", "destroy all",
                 "alter Vtest acmag=0", "alter Vdd acmag=1", "ac dec 50 10 1g",
                 "let hr=real(v(out))", "let hi=imag(v(out))", f"wrdata {name}_supply.tsv hr hi",
                 "let gr=real(v(xreg.gate))", "let gi=imag(v(xreg.gate))", "let ar=real(v(xreg.va))", "let ai=imag(v(xreg.va))",
                 f"wrdata {name}_nodes.tsv gr gi ar ai", "destroy all"]
        if opts.get('real_bias'):
            text += ['alter Vdd acmag=0','alter Vhost acmag=1','ac dec 50 10 1g','let hr=real(v(out))','let hi=imag(v(out))',f'wrdata {name}_host.tsv hr hi','destroy all','alter Vhost acmag=0']
    return "\n".join(text+["quit", ".endc", ".end", ""])


def prepare(opts):
    camp = OUT/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")+"_"+uuid4().hex[:8])
    (camp/"prepared").mkdir(parents=True)
    for path in SOURCES:
        target=camp/"source"/path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path,target)
    if opts.get('real_bias'):
        opts['bias_includes']=[str(camp/'source'/path.relative_to(ROOT)) for path in BIAS]
    allcases=[(v,t,i) for v in (3.0,3.3,3.6) for t in (-40,27,85) for i in (2,6,10)]
    entries=[dict(name="smoke",process="tt",cases=[(3.3,27,6)],smoke=True)]
    entries += ([dict(name="tt",process="tt",cases=[(3.3,27,6)],smoke=False)] if opts['pilot'] else
                [dict(name=p,process=p,cases=allcases,smoke=False) for p in ("ss","sf","fs","ff","tt")])
    for e in entries:
        path=camp/"prepared"/(e['name']+".cir")
        path.write_text(deck(e['process'],e['cases'],opts,e['smoke']))
        e.update(deck=str(path.relative_to(camp)),deck_sha256=sha(path),real_bias=bool(opts.get('real_bias')))
    plan=dict(options=opts,entries=entries,pdk_sha256=pdk_identity(), sources={str(p.relative_to(ROOT)):sha(p) for p in SOURCES},
              scope="Real host bandgap/current copy if real_bias option, otherwise ideal 1.23V/10uA; feedback/filter passives/load ideal. No MC, isolation or actual PLL qualification")
    (camp/"plan.json").write_text(json.dumps(plan,indent=2)+"\n")
    return camp


def verify(camp):
    plan=json.loads((camp/"plan.json").read_text())
    if pdk_identity()!=plan['pdk_sha256']:
        raise ValueError("PDK changed")
    for rel,h in plan['sources'].items():
        if sha(camp/"source"/rel)!=h:
            raise ValueError("Frozen source changed")
    for e in plan['entries']:
        if sha(camp/e['deck'])!=e['deck_sha256']:
            raise ValueError("Prepared deck changed")
    return plan


def completed(camp,e):
    for run in reversed([camp/e['name']]+sorted(camp.glob(e['name']+'.r[0-9]*'))):
        try:
            ex=json.loads((run/"execution.json").read_text())
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=e['deck_sha256'] or sha(run/"tb.cir")!=e['deck_sha256']:
                continue
            if ex['inputs_sha256']['core.spice']!=sha(camp/"source"/CORE.relative_to(ROOT)):
                continue
            for v,t,i in e['cases']:
                name=prefix(v,t,i)
                w=spice.Waves(run/(name+"_dc.raw"))
                if len(w.t)!=2 or not np.allclose(w.t, [i*.001,(i+.001)*.001],atol=1e-12,rtol=0):
                    raise ValueError("Incomplete DC grid")
                if not e['smoke']:
                    for kind in (('loop','supply','host') if e.get('real_bias') else ('loop','supply')):
                        a=np.loadtxt(run/(name+'_'+kind+'.tsv'),skiprows=1)
                        if a.shape!=(401,3) or not np.all(np.isfinite(a)) or not np.allclose(a[:,0],np.logspace(1,9,401),rtol=1e-6):
                            raise ValueError("Incomplete AC grid")
            return run
        except (OSError,ValueError,KeyError):
            pass
    return None


def analyse(camp,plan):
    rows=[]; missing=[]
    for e in plan['entries']:
        if e['smoke']: continue
        run=completed(camp,e)
        if run is None:
            missing.append(e['name']);continue
        for v,t,i in e['cases']:
            name=prefix(v,t,i); w=spice.Waves(run/(name+'_dc.raw'))
            l=np.loadtxt(run/(name+'_loop.tsv'),skiprows=1); s=np.loadtxt(run/(name+'_supply.tsv'),skiprows=1)
            gain=l[:,1]+1j*l[:,2]; mag=np.abs(gain); phase=np.unwrap(np.angle(gain))*180/np.pi
            cross=np.flatnonzero((mag[:-1]>=1)&(mag[1:]<1))
            margins=[]
            for n in cross:
                a=np.log(mag[n])/(np.log(mag[n])-np.log(mag[n+1]))
                margins.append(dict(hz=float(np.exp(np.log(l[n,0])*(1-a)+np.log(l[n+1,0])*a)),pm_deg=float(180+phase[n]*(1-a)+phase[n+1]*a)))
            h20=float(np.exp(np.interp(np.log(20e6),np.log(s[:,0]),np.log(np.hypot(s[:,1],s[:,2])))))
            rows.append(dict(process=e['process'],vin_v=v,temp_c=t,load_ma=i,vout_v=float(w['v(out)'][0]),gate_v=float(w['v(xreg.gate)'][0]),
                             iq_ua=float((-w['i(vdd)'][0]-i*.001-w['v(out)'][0]/1e5)*1e6),
                             supply_20mhz_v_v=h20,psrr_20mhz_db=float(-20*np.log10(h20)),return_ratio_crossings=margins,
                             run=str(run.relative_to(ROOT)),evidence={p.name:sha(p) for p in [run/(name+'_dc.raw'),run/(name+'_loop.tsv'),run/(name+'_supply.tsv'),run/'execution.json']}))
            if e.get('real_bias'):
                h=np.loadtxt(run/(name+'_host.tsv'),skiprows=1);gain=float(np.exp(np.interp(np.log(20e6),np.log(h[:,0]),np.log(np.hypot(h[:,1],h[:,2])))))
                rows[-1].update(vref_v=float(w['v(ref)'][0]),host_v=float(w['v(host)'][0]),host_reference_supply_mw=float(-w['v(host)'][0]*w['i(vhost)'][0]*1000),host_coupling_20mhz_v_v=gain)
                rows[-1]['evidence'][name+'_host.tsv']=sha(run/(name+'_host.tsv'))
    out=camp/"analysis"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ");out.mkdir(parents=True)
    data=dict(campaign=str(camp.relative_to(ROOT)),plan_sha256=sha(camp/'plan.json'),analyzer_sha256=sha(SELF),wave_reader_sha256=sha(ROOT/'src/serdes_flow/spice.py'),options=plan['options'],rows=rows,missing=missing,spec_status="ungraded screening")
    (out/'summary.json').write_text(json.dumps(data,indent=2,allow_nan=False)+"\n")
    print(json.dumps(dict(analysis=str(out.relative_to(ROOT)),missing=missing,rows=rows if len(rows)<4 else len(rows)),indent=2),flush=True)


def resume(camp,workers):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan=verify(camp);active=watch.ngspice_cwds()
        for rel,h in plan['sources'].items():
            if rel.startswith('analog/common/ldo/spice/'):
                continue  # DUT is copied exclusively from the verified snapshot.
            if sha(ROOT/rel)!=h:
                raise ValueError(f'Runtime changed: {rel}; use its recorded revision or create a new campaign')
        if any(p.is_relative_to(camp) for p in active) or len(active)+workers>4:
            raise ValueError("Active campaign or no simulation slots")
        core=camp/'source'/CORE.relative_to(ROOT)
        e=plan['entries'][0]
        if completed(camp,e) is None:
            spice.run((camp/e['deck']).read_text(),spice.next_run_dir(camp,e['name']),files={'core.spice':core},timeout_s=240)
        if completed(camp,e) is None:
            raise ValueError("DC smoke failed")
        jobs=[((camp/e['deck']).read_text(),spice.next_run_dir(camp,e['name']),dict(files={'core.spice':core},timeout_s=600)) for e in plan['entries'][1:] if completed(camp,e) is None]
        spice.run_many(jobs,workers=workers,smoke=False)
        analyse(camp,plan)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path)
    ap.add_argument('--pilot',action='store_true');ap.add_argument('--lp-um',type=float,choices=(.9,2,4),default=.9)
    ap.add_argument('--cc-pf',type=float,default=2);ap.add_argument('--cout-pf',type=float,default=100);ap.add_argument('--rz-ohm',type=float,default=2000)
    ap.add_argument('--rhv-ohm',type=float,default=.001);ap.add_argument('--chv-pf',type=float,default=.001)
    ap.add_argument('--real-bias',action='store_true');ap.add_argument('--host-v',type=float,default=1.8)
    ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare:
        print(prepare(dict(pilot=a.pilot,lp_um=a.lp_um,cc_pf=a.cc_pf,cout_pf=a.cout_pf,rz_ohm=a.rz_ohm,rhv_ohm=a.rhv_ohm,chv_pf=a.chv_pf,real_bias=a.real_bias,host_v=a.host_v)).relative_to(ROOT))
    elif a.resume: resume(a.resume.resolve(),a.workers)
    else: analyse(a.analyse.resolve(),verify(a.analyse.resolve()))
