"""r4 cold start/re-initialization and static bypass, actual BG and PDK passives.

Three independent benches per model parse: 2mA-equivalent resistor load,
10mA-equivalent load, and bypass with Vin/quiet strapped to one supply.
Extra12pF on vgi and1pF tail-gate load are explicit surrogates, not a full PLL.
This runner publishes transient results only. Use dc_noise.py for noise;
every noise analysis must certify its own recomputed operating point.
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
from serdes_flow import project, spice, watch

ROOT=project.ROOT;SELF=Path(__file__).resolve();RUN=SELF.with_name('run.py')
spec=importlib.util.spec_from_file_location('r4',RUN);r4=importlib.util.module_from_spec(spec);spec.loader.exec_module(r4)
sha=r4.sha;OUT=ROOT/'results/analog/common/ldo/r4_startup'
BIAS_CELL=ROOT/'analog/common/ldo/spice/pll_bias_filter_r4.spice'
CELLS=[*r4.CELLS,BIAS_CELL]
RUNTIME=[SELF,*r4.RUNTIME]
PROFILES=[('tt','tt',3.3,1.8,27,1.8),('fs','ll',3.,1.65,85,1.65),('ss','hh',3.,1.65,-40,1.8),
          ('sf','hh',3.,1.65,85,1.95),('ff','ll',3.6,1.95,-40,1.95),('fs','hh',3.6,1.95,-40,1.65)]
VECTORS=('out_v','ref_v','raw_v','bias_v','gate_v','casg_v','tail_v','hv_i','host_i')


def deck(e,smoke=False):
    lines=['* HV18 r4 cold startup and fixed bypass; no supply-mode hot switching',f'.lib "{project.model_library()}" {r4.section(e["mos"],e["rc"])}']
    lines += [f'.include "{p.name}"' for p in CELLS]
    lines += [f'.temp {e["temp_c"]}','.options reltol=1e-4 abstol=1p vntol=1u']
    for mode in ('hv2','hv10','bypass'):
        local=r4.body('tt');local=local[local.index('Vdd vin'):local.index('.options')]
        body=[]
        for line in local.splitlines():
            if line.startswith('Vdd '):line=f"Vdd vin 0 pwl(0 0 20n 0 120n {e['bypass_v'] if mode=='bypass' else e['hv_v']}) ac 0"
            elif line.startswith('Vhost '):line=f"Vhost host 0 pwl(0 0 20n 0 120n {e['host_v']}) ac 0"
            elif line.startswith('Venable '):
                line='Venable enable 0 0' if mode=='bypass' else f"Venable enable 0 pwl(0 0 250n 0 255n {e['host_v']} 180u {e['host_v']} 180.005u 0 200u 0 200.005u {e['host_v']})"
            elif line.startswith('Vb'):
                bit=int(line[2]);line=f'Ebit{bit} b{bit} 0 host 0 {int(bool((e["trim"]>>bit)&1))}'
            elif line.startswith('Iload '):line=f'Rload quiet 0 {180 if mode=="hv10" else (900 if mode=="hv2" else 300)}'
            body.append(line)
        # Explicit CML copy plus remaining distribution capacitance. Gate-load
        # 1pF is a conservative surrogate; AC study uses actual VCO/buffer gates.
        body += ['Xcmlcopy bias_original vgi host serdes_bias_pcopy n=85','Xcmldiode bias_original 0 serdes_bias_cml',
                 'Xtailfilter bias_original tail_filtered 0 serdes_pll_bias_lowpass_slow_r4','Ctailgates tail_filtered 0 1p','Cdistribution vgi host 12p']
        if mode=='bypass':body.append('Vstrap vin quiet 0')
        lines += [f'.subckt bench_{mode} gnd',*body,f'.ends bench_{mode}',f'X{mode} 0 bench_{mode}']
    saves=[]
    for mode in ('hv2','hv10','bypass'):
        saves += [f'v(x{mode}.{node})' for node in ('quiet','xdut.ref_local','rawref','xdut.ibias','xdut.xcore.gate','xdut.xcore.casg','tail_filtered')]
        saves += [f'i(v.x{mode}.{source})' for source in ('vdd','vhost')]
    lines += ['.control','set num_threads=1','set filetype=binary','save '+' '.join(saves),f'tran 2n {"1n" if smoke else "360u"} 0 10n']
    for mode in ('hv2','hv10','bypass'):
        for alias,node in [('out_v','quiet'),('ref_v','xdut.ref_local'),('raw_v','rawref'),('bias_v','xdut.ibias'),('gate_v','xdut.xcore.gate'),('casg_v','xdut.xcore.casg'),('tail_v','tail_filtered')]:
            lines.append(f'let {alias}=v(x{mode}.{node})')
        lines += [f'let hv_i=i(v.x{mode}.vdd)',f'let host_i=i(v.x{mode}.vhost)',f'write {mode}.raw '+' '.join(VECTORS)]
    lines.append('destroy all')
    return '\n'.join(lines+['quit','.endc','.end',''])


def prepare(calibration):
    d=json.loads(calibration.read_text());p=r4.verify(ROOT/d['campaign'])
    if d['missing'] or d['suite']!='calibration':raise ValueError('Need complete calibration')
    for path in r4.CELLS:
        if sha(path)!=p['cell_sha256'][str(path.relative_to(ROOT))]:raise ValueError('Cell changed')
    c=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);(c/'source').mkdir(parents=True);(c/'prepared').mkdir()
    for path in [*CELLS,*RUNTIME]:
        q=c/'source'/path.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,q)
    entries=[]
    for n,(mos,rc,hv,host,temp,bypass) in enumerate(PROFILES):
        e=dict(name=f'{mos}_{rc}_h{round(hv*1000)}_u{round(host*1000)}_t{temp}',mos=mos,rc=rc,hv_v=hv,host_v=host,temp_c=temp,bypass_v=bypass,
               trim=d['calibration_codes'][mos+':'+rc]['trim'])
        path=c/'prepared'/(e['name']+'.cir');path.write_text(deck(e));e.update(deck=str(path.relative_to(c)),deck_sha256=sha(path));entries.append(e)
    (c/'prepared/smoke.cir').write_text(deck(entries[0],True))
    plan=dict(entries=entries,t_end_s=360e-6,pdk_sha256=p['pdk_sha256'],runtime={str(x.relative_to(ROOT)):sha(x) for x in RUNTIME},
              sources={str(x.relative_to(c)):sha(x) for x in (c/'source').rglob('*') if x.is_file()},smoke_sha256=sha(c/'prepared/smoke.cir'),
              calibration_summary=str(calibration.relative_to(ROOT)),calibration_sha256=sha(calibration),vgi_extra_pf=12,cml_copy_fingers=85,tail_gate_surrogate_pf=1,tail_filter_ohm=1000000)
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def completed(c,e):
    for r in reversed([c/e['name']]+sorted(c.glob(e['name']+'.r[0-9]*'))):
        try:
            ex=json.loads((r/'execution.json').read_text())
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=e['deck_sha256'] or sha(r/'tb.cir')!=e['deck_sha256']:continue
            if any(sha(r/x.name)!=sha(c/'source'/x.relative_to(ROOT)) or ex['inputs_sha256'][x.name]!=sha(c/'source'/x.relative_to(ROOT)) for x in CELLS):continue
            for mode in ('hv2','hv10','bypass'):
                w=spice.Waves(r/(mode+'.raw'))
                if w.t[0]!=0 or w.t[-1]<360e-6*(1-1e-9) or any(key not in w for key in VECTORS):raise ValueError('Truncated transient')
            return r
        except (OSError,ValueError,KeyError):pass
    return None


def analyse(c,p):
    rows=[];missing=[]
    for e in p['entries']:
        r=completed(c,e)
        if r is None:missing.append(e['name']);continue
        for mode in ('hv2','hv10','bypass'):
            w=spice.Waves(r/(mode+'.raw'));v=w['out_v'];off=(w.t>=185e-6)&(w.t<=195e-6);final=w.t>=350e-6;first=(w.t<180e-6)
            row=dict(name=e['name'],mode=mode,mos=e['mos'],rc=e['rc'],hv_v=e['hv_v'],host_v=e['host_v'],temp_c=e['temp_c'],trim=e['trim'],
                     min_v=float(v.min()),peak_v=float(v.max()),first_peak_v=float(v[first].max()),first_final_v=float(np.mean(v[(w.t>170e-6)&(w.t<179e-6)])),
                     final_v=float(np.mean(v[final])),final_pp_mv=float(np.ptp(v[final])*1000),off_floor_v=float(np.mean(v[off])),
                     off_hv_current_ma=float(-np.mean(w['hv_i'][off])*1000),off_host_current_ma=float(-np.mean(w['host_i'][off])*1000),
                     ref_off_v=float(np.mean(w['ref_v'][off])),tail_at_150us_v=float(np.interp(150e-6,w.t,w['tail_v'])),tail_final_v=float(np.mean(w['tail_v'][final])),run=str(r.relative_to(ROOT)),raw=str((r/(mode+'.raw')).relative_to(ROOT)))
            files=[r/(mode+'.raw'),r/'execution.json']
            row['evidence']={path.name:sha(path) for path in files};rows.append(row)
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    (out/'summary.json').write_text(json.dumps(dict(campaign=str(c.relative_to(ROOT)),plan_sha256=sha(c/'plan.json'),analyzer_sha256=sha(SELF),rows=rows,missing=missing,
                                                  scope='Transient only: six physical-passive pressure profiles, actual BG/CML copy and explicit12pF extra vgi/1pF gate surrogates; noise requires separate post-noise bias certification; no complete system/MC qualification'),indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(analysis=str(out.relative_to(ROOT)),rows=len(rows),missing=missing),indent=2))


def resume(c,workers):
    with (c/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=json.loads((c/'plan.json').read_text())
        if r4.reg.pdk_identity()!=p['pdk_sha256']:raise ValueError('PDK changed')
        for rel,h in p['sources'].items():
            if sha(c/rel)!=h:raise ValueError('Snapshot changed')
        for rel,h in p['runtime'].items():
            if sha(ROOT/rel)!=h:raise ValueError('Runtime changed')
        for e in p['entries']:
            if sha(c/e['deck'])!=e['deck_sha256']:raise ValueError('Deck changed')
        active=watch.ngspice_cwds()
        if any(x.is_relative_to(c) for x in active) or len(active)+workers>4:raise ValueError('No slots/already running')
        files={path.name:c/'source'/path.relative_to(ROOT) for path in CELLS}
        ex=spice.run((c/'prepared/smoke.cir').read_text(),spice.next_run_dir(c,'smoke'),files=files,timeout_s=240)
        if not ex.ok:raise ValueError('Smoke failed')
        jobs=[((c/e['deck']).read_text(),spice.next_run_dir(c,e['name']),dict(files=files,timeout_s=1200)) for e in p['entries'] if completed(c,e) is None]
        spice.run_many(jobs,workers=workers,smoke=False);analyse(c,p)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True);g.add_argument('--prepare',type=Path);g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path);ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare:print(prepare(a.prepare.resolve()).relative_to(ROOT))
    elif a.resume:resume(a.resume.resolve(),a.workers)
    else:analyse(a.analyse.resolve(),json.loads((a.analyse/'plan.json').read_text()))
