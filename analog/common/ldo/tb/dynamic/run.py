"""Local transient/noise checks of a frozen, completed LDO DC/AC campaign.

Ideal reference, bias current and loads. A resistor load is used for startup
so an ideal current sink cannot force a negative unpowered output. No .ic/uic.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from serdes_flow import project, spice, watch

ROOT=project.ROOT
SELF=Path(__file__).resolve()
REG=ROOT/'analog/common/ldo/tb/regulation/run.py'
RUNTIME=[SELF,REG,ROOT/'src/serdes_flow/spice.py',ROOT/'src/serdes_flow/project.py',ROOT/'src/serdes_flow/watch.py',ROOT/'config/pdk.toml',ROOT/'config/tools.toml']
spec=importlib.util.spec_from_file_location('ldo_regulation',REG)
reg=importlib.util.module_from_spec(spec);spec.loader.exec_module(reg)
sha=reg.sha
OUT=ROOT/'results/analog/common/ldo/dynamic'


def deck(parent, process, vin, temp, mode, core):
    opts=parent['options']
    text=reg.deck(process,[(vin,temp,6)],opts,True).split('.control')[0]
    text=text.replace('.include "core.spice"',f'.include "{core}"')
    text=text.replace('.save all','.save v(out) v(vin) v(xreg.gate) v(xreg.va) v(xreg.mid) i(Vdd) i(Vhost)')
    text+=f'\n.temp {temp}\n.control\nset num_threads=1\nset filetype=binary\n'
    text=text.replace('Vdd vin 0 3.3 ac 0',f'Vdd vin 0 {vin} ac 0')
    if mode=='noise':
        text='\n'.join(line for line in text.splitlines() if not line.startswith('.save'))+'\n'
        return text+'noise v(out) Vref dec 40 1k 200meg\nsetplot noise1\nwrite noise.raw frequency onoise_spectrum\nsetplot noise2\nprint onoise_total\nquit\n.endc\n.end\n'
    if mode.startswith('step'):
        top=dict(step=10,step_1ma=7,step_100ua=6.1)[mode]
        text=text.replace('Iload out 0 6m',f'Iload out 0 pulse(6m {top}m 100n 1n 1n 100n 300n)')
        stop,start,dt=400e-9,20e-9,100e-12
    elif mode=='ripple':
        text=text.replace(f'Vdd vin 0 {vin} ac 0',f'Vdd vin 0 dc {vin} sin({vin} 0.05 20meg) ac 0')
        stop,start,dt=1200e-9,700e-9,100e-12
    elif mode=='startup':
        text=text.replace(f'Vdd vin 0 {vin} ac 0',f'Vdd vin 0 pwl(0 0 20n 0 120n {vin}) ac 0')
        text=text.replace('Vref ref 0 1.23 ac 0','Vref ref 0 pwl(0 0 150n 0 250n 1.23) ac 0')
        text=text.replace('Iref host ibias 10u','Iref host ibias pwl(0 0 150n 0 250n 10u)')
        text=text.replace('Iload out 0 6m','Rload out 0 300')
        stop,start,dt=2000e-9,0,200e-12
    else: raise ValueError(mode)
    text+=f'tran {dt:g} {stop:g} 0 {dt:g}\nwrite wave.raw v(out) v(vin) v(xreg.gate) v(xreg.va) v(xreg.mid) i(Vdd) i(Vhost)\nquit\n.endc\n.end\n'
    return spice.skip_output_before(text,start)


def prepare(parent_path,pilot):
    parent_path=parent_path.resolve();p=reg.verify(parent_path)
    if p['options'].get('real_bias'):raise ValueError('Real-reference power-up needs a separate host sequence bench')
    if any(reg.completed(parent_path,e) is None for e in p['entries']):
        raise ValueError('Parent DC/AC campaign incomplete')
    core=parent_path/'source/analog/common/ldo/spice/ldo_hv18_core.spice'
    if 'Xcas ' not in core.read_text():
        raise ValueError('This bench expects the cascoded core')
    camp=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);(camp/'prepared').mkdir(parents=True)
    (camp/'source').mkdir();shutil.copyfile(SELF,camp/'source/run.py');shutil.copyfile(REG,camp/'source/regulation.py');shutil.copyfile(core,camp/'source/core.spice')
    runtime={str(path.relative_to(ROOT)):sha(path) for path in RUNTIME}
    for path in RUNTIME:
        target=camp/'source/runtime'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    cases=[('tt',3.3,27)] if pilot else [('tt',3.3,27),('ss',3.,-40),('ss',3.,85),('sf',3.,-40),('fs',3.,85),('ff',3.6,-40)]
    entries=[]
    modes=('step','step_1ma','step_100ua','ripple','startup')
    for process,vin,temp in cases:
        group=f'{process}_v{round(vin*1000)}_t{temp}'
        # Five independent local benches share one model parse and transient.
        # Their only shared node is ideal ground; every source remains local.
        lines=['* HV18 independent local dynamic benches, one PDK parse per condition',
               f'.lib "{project.model_library()}" {process}', '.include "core.spice"',f'.temp {temp}',
               '.options reltol=1e-5 abstol=1p vntol=1u']
        for mode in modes:
            local=deck(p,process,vin,temp,mode,'core.spice').split('.control')[0]
            circuit=local[local.index('Vdd vin'):]
            circuit='\n'.join(line for line in circuit.splitlines() if not line.startswith('.'))
            lines += [f'.subckt bench_{mode} gnd',circuit,f'.ends bench_{mode}',f'X{mode} 0 bench_{mode}']
        lines += ['.control','set num_threads=1','set filetype=binary','tran 0.1n 2u 0 0.1n']
        for mode in modes:
            for alias,node in zip(('out_v','vin_v','gate_v','va_v','mid_v'),('out','vin','xreg.gate','xreg.va','xreg.mid')):
                lines.append(f'let {alias}=v(x{mode}.{node})')
            for source in ('vdd','vhost'):
                lines.append(f'let {source}_i=i(v.x{mode}.{source})')
            lines.append(f'write {mode}.raw out_v vin_v gate_v va_v mid_v vdd_i vhost_i')
        lines += ['destroy all','noise v(xstep.out) v.xstep.vref dec 40 1k 200meg','setplot noise1',
                  'write noise.raw frequency onoise_spectrum','setplot noise2','print onoise_total','quit','.endc','.end','']
        path=camp/'prepared'/(group+'.cir');path.write_text('\n'.join(lines))
        for mode in (*modes,'noise'):
            entries.append(dict(name=group+'_'+mode,run_name=group,filename=mode+'.raw',process=process,vin_v=vin,temp_c=temp,mode=mode,
                                deck=str(path.relative_to(camp)),deck_sha256=sha(path),t_end_s=None if mode=='noise' else 2e-6))
    plan=dict(parent=str(parent_path.relative_to(ROOT)),parent_plan_sha256=sha(parent_path/'plan.json'),pdk_sha256=p['pdk_sha256'],
              sources={str(path.relative_to(camp)):sha(path) for path in (camp/'source').rglob('*') if path.is_file()},runtime=runtime,entries=entries,scope='local ideal-boundary dynamic/noise screen, no host reference noise, isolation or PLL qualification')
    (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return camp


def verify(camp):
    p=json.loads((camp/'plan.json').read_text())
    if reg.pdk_identity()!=p['pdk_sha256']:raise ValueError('PDK changed')
    for path,h in p['sources'].items():
        if sha(camp/path)!=h:raise ValueError('Source changed')
    for e in p['entries']:
        if sha(camp/e['deck'])!=e['deck_sha256']:raise ValueError('Deck changed')
    return p


def completed(camp,e):
    name=e.get('run_name',e['name'])
    for run in reversed([camp/name]+sorted(camp.glob(name+'.r[0-9]*'))):
        try:
            ex=json.loads((run/'execution.json').read_text())
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=e['deck_sha256'] or sha(run/'tb.cir')!=e['deck_sha256'] or ex['inputs_sha256']['core.spice']!=sha(camp/'source/core.spice'):continue
            w=spice.Waves(run/e.get('filename','noise.raw' if e['mode']=='noise' else 'wave.raw'))
            if e['mode']=='noise':
                expected=1e3*10**(np.arange(213)/40)
                if len(w.t)!=213 or not np.allclose(w.t,expected,rtol=1e-9) or 'onoise_spectrum' not in w:raise ValueError('Noise sweep incomplete')
            elif w.t[-1]<e['t_end_s']*(1-1e-9) or len(w.t)<10:raise ValueError('Truncated transient')
            elif any(key not in w for key in ({'out_v','vin_v','gate_v','va_v','mid_v','vdd_i','vhost_i'} if 'run_name' in e else {'v(out)','v(vin)'})):
                raise ValueError('Missing transient vectors')
            elif w.t[0]> (0 if 'run_name' in e or e['mode']=='startup' else (700e-9 if e['mode']=='ripple' else 20e-9))+1e-12:
                raise ValueError('Missing beginning of intended window')
            return run,w
        except (OSError,ValueError,KeyError):pass
    return None


def analyse(camp,p):
    rows=[];missing=[]
    for e in p['entries']:
        got=completed(camp,e)
        if got is None:missing.append(e['name']);continue
        run,w=got;row={k:e[k] for k in ('name','process','vin_v','temp_c','mode')};row.update(run=str(run.relative_to(ROOT)))
        if e['mode']=='noise':
            row.update(internal_noise_rms_uv=float(np.sqrt(np.trapezoid(w['onoise_spectrum']**2,w.t))*1e6),f_start_hz=float(w.t[0]),f_stop_hz=float(w.t[-1]))
        else:
            # Each independent bench is solved to 2 us; analyse its intended window.
            window=(w.t<=400e-9) if e['mode'].startswith('step') else ((w.t>=w.t[-1]-500e-9) if e['mode']=='ripple' else np.ones(len(w.t),dtype=bool))
            time=w.t[window];v=w['out_v' if 'run_name' in e else 'v(out)'][window]
            row.update(window_s=[float(time[0]),float(time[-1])],min_v=float(v.min()),max_v=float(v.max()),final_v=float(v[-1]),last_window_pp_mv=float(np.ptp(v[time>=time[-1]-50e-9])*1000))
            if e['mode']=='ripple':
                # Fit a DC term, linear drift and 20 MHz quadratures; retain raw pp too.
                matrix=np.column_stack([np.ones(len(time)),(time-time.mean())/1e-9,np.sin(2*np.pi*20e6*time),np.cos(2*np.pi*20e6*time)])
                coef=np.linalg.lstsq(matrix,v,rcond=None)[0];amp=float(np.hypot(coef[2],coef[3]));row.update(tone_mvpp=2000*amp,psrr_db=float(20*np.log10(.05/amp)))
            if e['mode'].startswith('step'):
                base=float(np.mean(v[time<95e-9]));row.update(baseline_v=base,droop_mv=float((base-v.min())*1000),overshoot_mv=float((v.max()-base)*1000))
        files=[run/'execution.json',run/e.get('filename','noise.raw' if e['mode']=='noise' else 'wave.raw')];row['evidence']={path.name:sha(path) for path in files};rows.append(row)
    out=camp/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    (out/'summary.json').write_text(json.dumps(dict(campaign=str(camp.relative_to(ROOT)),plan_sha256=sha(camp/'plan.json'),analyzer_sha256=sha(SELF),wave_reader_sha256=sha(ROOT/'src/serdes_flow/spice.py'),rows=rows,missing=missing,spec_status='ungraded diagnostic'),indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(analysis=str(out.relative_to(ROOT)),rows=rows,missing=missing),indent=2),flush=True)


def resume(camp,workers):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=verify(camp);active=watch.ngspice_cwds()
        if 'runtime' not in p:raise ValueError('Legacy runner has no runtime lock; create a new campaign')
        for rel,h in p['runtime'].items():
            if sha(ROOT/rel)!=h:raise ValueError(f'Runtime changed: {rel}; create a new campaign')
        if any(x.is_relative_to(camp) for x in active) or len(active)+workers>4:raise ValueError('No slots or campaign already active')
        trans=[e for e in p['entries'] if e['mode']!='noise' and completed(camp,e) is None]
        if trans:
            e=trans[0];sdir=spice.next_run_dir(camp,'smoke');sd=spice.smoke_deck((camp/e['deck']).read_text());ex=spice.run(sd,sdir,files={'core.spice':camp/'source/core.spice'},timeout_s=240)
            if not ex.ok:raise ValueError(f'Transient smoke failed: {ex.log_failures[:3]}')
            w=spice.Waves(sdir/e.get('filename','wave.raw'))
            if not ex.ok or w.t[-1]<spice.spice_number(sd.split('tran ')[1].split()[1])*(1-1e-9):raise ValueError('Transient smoke failed')
        pending={e.get('run_name',e['name']):e for e in p['entries'] if completed(camp,e) is None}
        jobs=[((camp/e['deck']).read_text(),spice.next_run_dir(camp,name),dict(files={'core.spice':camp/'source/core.spice'},timeout_s=300)) for name,e in pending.items()]
        spice.run_many(jobs,workers=workers,smoke=False);analyse(camp,p)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare-from',type=Path);g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path)
    ap.add_argument('--pilot',action='store_true');ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare_from:print(prepare(a.prepare_from,a.pilot).relative_to(ROOT))
    elif a.resume:resume(a.resume.resolve(),a.workers)
    else:analyse(a.analyse.resolve(),verify(a.analyse.resolve()))
