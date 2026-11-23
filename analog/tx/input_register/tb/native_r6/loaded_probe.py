"""Same-deck r6 PLL and current full TX: static loaded-clock interface probe.

Preparation is independent of the upstream result; execution requires the
explicit parent TT/ext native campaign to pass the engineering lock screen.
This short probe is not dynamic serialization or sustained loaded lock.
"""
import argparse
from datetime import datetime,timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tomllib

import numpy as np
from serdes_flow import boundary,clock,pll_lock,project,rcorner,spice,watch

ROOT=project.ROOT
SELF=Path(__file__).resolve()


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


native=load('tx_native_parent',ROOT/'analog/pll/top/tb/native_r6/campaign.py')
tx=load('tx_full_parent',ROOT/'analog/tx/input_register/tb/full_serializer/run.py')
OUT=ROOT/'results/analog/tx/native_r6_loaded'
PARAMS=dict(extra_2g=5,output_wt=16,output_r=240)
DRIVER='rpre=120 wtpre=60 wout=192'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def engineering(parent,exploratory=False):
    p=native.check(parent)
    e=next(e for e in p['entries'] if e['point']=='tt_v1800_t27:tt' and e['variant']=='ext')
    d=native.completed(parent,e)
    if d is None:raise ValueError('Parent TT native waveform is incomplete')
    w=spice.Waves(d/'loop.raw');cfg=tomllib.loads((ROOT/'verification/contracts/pll_lock_screen.toml').read_text())
    r=pll_lock.screen(clock.edges(w.t,w['v(ref)']-.9),clock.edges(w.t,w['v(fb0)']-.9),
        start=55e-9,stop=float(w.t[-1]),period=4e-9,window_cycles=cfg['reference_window_cycles'],
        stride_cycles=cfg['window_stride_cycles'],frequency_tolerance=cfg['maximum_relative_frequency_error'],
        phase_span=cfg['maximum_unwrapped_phase_span_s'],hold=cfg['required_hold_time_s'])
    last_window_ok=bool(r['windows'] and r['windows'][-1]['passed'])
    if not r['locked'] and not (exploratory and last_window_ok):
        raise ValueError('Parent TT native engineering lock not established: '+r['status'])
    return dict(raw=str((d/'loop.raw').relative_to(ROOT)),raw_sha256=sha(d/'loop.raw'),screen=r,
                contract_passed=r['locked'],last_window_passed=last_window_ok,
                execution_mode='exploratory_static_loading_only' if exploratory else 'parent_qualified_static_loading')


def renamed(text,names):
    pattern=r'\b(?:'+'|'.join(re.escape(n) for n in sorted(names,key=len,reverse=True))+r')\b'
    return re.sub(pattern,lambda m:m[0]+'_tx',text,flags=re.I) if names else text


def tx_cell(rel,text,names):
    result=renamed(text,names)
    # Match rcorner.to_pdk: channel/fixture models under verification/ retain
    # their ideal RLC elements; only analog DUT cells get PDK resistors.
    return rcorner._pdk_cell(result) if rel.startswith('analog/') else result


def fixture(text,includes,stop,private_names=()):
    """Append the existing TX and real port bridges; one shared BG and supply."""
    distribution=tx.distribution(**PARAMS)
    dist='\n'.join(l for l in distribution.splitlines() if not l.startswith('.include '))
    body=['* Current full TX on host rail; one extra real reference copy',*includes,dist,
        'XIref_tx vbias_tx vgi_bias vdd serdes_bias_pcopy n=85',
        'Xbias_tx vbias_tx 0 serdes_bias_cml']
    for port,source in [('250','d08'),('500','d04'),('1g','d02'),('2g','b0')]:
        # Match the previously verified native2G polarity. The other ports
        # terminate the preserved, unused input stages of the v3 distribution.
        p,n=(source+'n',source+'p') if port=='2g' else (source+'p',source+'n')
        body += [f'Vtap{port}p s{port}p {p} 0',f'Vtap{port}n s{port}n {n} 0']
    body += [tx.static_probe_sources(),
        'Xclocks s250p s250n s500p s500n s1gp s1gn s2gp s2gn c250p c250n c500p c500n c1gp c1gn c2gp c2gn vbias_tx vdd 0 serdes_cml_clock_distribution_tx_lowov',
        'Xtx '+' '.join('d'+str(i) for i in range(16))+' c250p c250n c500p c500n c1gp c1gn c2gp c2gn qp qn vbias_tx vdd 0 serdes_tx_capture_serializer16',
        'Cqp qp 0 2f','Cqn qn 0 2f','Vtxen tx_en 0 PWL(0 0 4n 0 4.1n 1.8)',
        tx.DRIVER_LINE.replace('vbias vdd','vbias_tx vdd')+' '+DRIVER,
        'Clpp lqp 0 200f','Clpn lqn 0 200f','Rlpp lqp llp .3','Rlpn lqn lln .3',
        'Llpp llp lap .5n','Llpn lln lan .5n','Clacp lap ltp 10n','Clacn lan ltn 10n',
        'Xchannel ltp ltn lxp lxn 0 serdes_diff_rlc16','Rlc0 lxp lrp .01','Rlc1 lxn lrn .01',
        'Clc0 lrp 0 100f','Clc1 lrn 0 100f','Vlcm lcm 0 .9','Rlterm0 lrp lcm 50','Rlterm1 lrn lcm 50']
    body += [f'Cq{k} xtx.q{k} 0 2f' for k in range(16)]
    body += [f'.nodeset v(xtx.q{k})=0 v(xtx.xcap.s{k})=0' for k in range(16)]
    vec=list(dict.fromkeys(native.base.PROBES.split()+tx.vectors(5)))
    text=re.sub(r'^\.save .*$', '.save '+' '.join(vec),text,flags=re.M)
    text=re.sub(r'^write loop\.raw .*$', 'write loop.raw '+' '.join(vec),text,flags=re.M)
    text=re.sub(r'^tran .*$',f'tran 4p {stop:.12g} 40n 4p',text,flags=re.M)
    return text.replace('.control\n',renamed('\n'.join(body),private_names)+'\n.control\n'),boundary.input_stage_signature(distribution,'serdes_cml_clock_distribution_tx_lowov',('s2gp','s2gn'))


def prepare(parent,stop):
    pp=native.check(parent)
    e=next(e for e in pp['entries'] if e['point']=='tt_v1800_t27:tt' and e['variant']=='ext')
    if stop<=80e-9:raise ValueError('Loaded probe requires >80ns endpoint')
    c=OUT/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');(c/'prepared').mkdir(parents=True)
    shutil.copytree(parent/'snap',c/'parent_snap')
    text=(parent/'prepared'/(e['name']+'.cir')).read_text().replace(str(parent/'snap'),str(c/'parent_snap'))
    # Preserve the already-verified TX's generic PDK resistor conversion.
    # A single fixed2p85 segment cannot represent its100/120/133ohm loads
    # (head resistance137.6ohm). Private TX subcircuit names let both cards
    # coexist while the PLL and shared BG retain the frozen M1 definitions.
    added=[p for p in tx.FILES if p not in tx.bias.BIAS_INC]
    content={p:(ROOT/p).read_text() for p in added}
    names={n for t in [*content.values(),tx.distribution(**PARAMS)] for n in re.findall(r'^\.subckt\s+(\S+)',t,re.M|re.I)}
    includes=[]
    for rel,body in content.items():
        dst=c/'tx_generic'/rel;dst.parent.mkdir(parents=True,exist_ok=True)
        dst.write_text(tx_cell(rel,body,names))
        includes.append(f'.include "{dst}"')
    text,load_signature=fixture(text,includes,stop,names)
    (c/'prepared/probe.cir').write_text(text)
    (c/'prepared/smoke.cir').write_text(re.sub(r'^tran .*$', 'tran 4p 1n 0 4p',text,flags=re.M))
    sources={SELF,tx.HERE/'run.py',tx.DIST,tx.HERE/'tb_full_ngspice.cir.in',
             *[ROOT/p for p in tx.FILES],ROOT/'src/serdes_flow/pll_lock.py',ROOT/'verification/contracts/pll_lock_screen.toml'}
    for src in sources:
        dst=c/'source'/src.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    plan=dict(parent=str(parent.relative_to(ROOT)),parent_plan_sha256=sha(parent/'plan.json'),
              t_end_s=stop,condition='tt_v1800_t27',passive='tt',supply_variant='ext',
              code=e['code'],parameters=PARAMS,driver=DRIVER,load_signature=load_signature,
              resistor_policy='PLL/sharedBG frozen fixed-width; private TX generic PDK exactly as full-TX bench conversion',
              snapshots={str(p.relative_to(c)):sha(p) for p in c.rglob('*') if p.is_file()},
              scope='Static same-deck r6 PLL+complete current TX; frozen fixed-width PLL/sharedBG plus private generic-PDK TX, shared real BG, independent host/quiet ideal rails, retained dummy input loads and counter.ic; short interface screen only, no dynamic/PEX/noise qualification')
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def check(c):
    p=json.loads((c/'plan.json').read_text());parent=ROOT/p['parent']
    if sha(parent/'plan.json')!=p['parent_plan_sha256']:raise ValueError('Parent changed')
    native.check(parent)
    for n,h in p['snapshots'].items():
        if sha(c/n)!=h:raise ValueError('Frozen input changed: '+n)
    return p


def complete(c,name,end):
    for d in reversed([c/name]+sorted(c.glob(name+'.r[0-9]*'))):
        try:
            ex=json.loads((d/'execution.json').read_text())
            if ex['exit_code'] or ex['timed_out'] or ex['log_failures']:continue
            if (d/'tb.cir').read_text()!=(c/'prepared'/(name+'.cir')).read_text():continue
            w=spice.Waves(d/'loop.raw')
            if w.t[-1]<end*(1-1e-9) or not np.all(np.isfinite(w.data)):continue
            return d
        except (OSError,ValueError,KeyError):pass
    return None


def analyse(c):
    p=check(c);d=complete(c,'probe',p['t_end_s'])
    result=dict(campaign=str(c.relative_to(ROOT)),scope=p['scope'],complete=d is not None)
    if (c/'parent_evidence.json').exists():result['parent_evidence']=json.loads((c/'parent_evidence.json').read_text())
    if d:
        w=spice.Waves(d/'loop.raw');start=p['t_end_s']-20e-9;end=p['t_end_s']-1e-9
        ck=w['v(xclocks.xcnt.ckp)']-w['v(xclocks.xcnt.ckn)']
        result.update(run=str(d.relative_to(ROOT)),
            counter=clock.binary_counter(w.t,[w[f'v(xclocks.q{k}p)']-w[f'v(xclocks.q{k}n)'] for k in range(3)],clock.edges(w.t,ck,-1),start,end),
            source=clock.period_stats(w.t,w['v(b0p)']-w['v(b0n)'],start,end),
            word=clock.period_stats(w.t,w['v(xtx.word_clk)']-.9,start,end))
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    (out/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps(result,indent=2),flush=True);print(out.relative_to(ROOT),flush=True)


def resume(c,timeout,exploratory=False):
    with (c/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=check(c)
        if exploratory and p['t_end_s']>120e-9*(1+1e-9):
            raise ValueError('Exploratory mode is bounded to the120ns static loading probe')
        accepted=engineering(ROOT/p['parent'],exploratory)
        stamp=c/'parent_evidence.json'
        if stamp.exists() and json.loads(stamp.read_text())!=accepted:
            raise ValueError('Accepted parent waveform/score changed; prepare a new probe')
        if not stamp.exists():stamp.write_text(json.dumps(accepted,indent=2)+'\n')
        if len(watch.ngspice_cwds())>=4:raise ValueError('Global ngspice slots occupied')
        for name,end in [('smoke',1e-9),('probe',p['t_end_s'])]:
            if complete(c,name,end):continue
            ex=spice.run((c/'prepared'/(name+'.cir')).read_text(),spice.next_run_dir(c,name),timeout_s=timeout)
            print(name,ex.ok,round(ex.elapsed_s,1),flush=True)
            if complete(c,name,end) is None:break
        analyse(c)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',type=Path);g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path)
    ap.add_argument('--stop',type=float,default=120e-9);ap.add_argument('--timeout',type=float,default=2400)
    ap.add_argument('--exploratory',action='store_true',help='bounded static load calibration; requires last32cycle window, never releases M2');a=ap.parse_args()
    if a.prepare:print(prepare(a.prepare.resolve(),a.stop))
    elif a.resume:resume(a.resume.resolve(),a.timeout,a.exploratory)
    else:analyse(a.analyse.resolve())
