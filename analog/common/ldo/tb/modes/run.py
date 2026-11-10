"""TT functional pilot of assembled supply macro, actual bandgap startup.

HV, bypass with absent HV, both off, and reset-required mode change share one
model load. This is not a brownout/one-hot-controller or PVT qualification.
"""
import argparse
import hashlib
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from serdes_flow import project, spice, watch

ROOT=project.ROOT;SELF=Path(__file__).resolve();REG=ROOT/'analog/common/ldo/tb/regulation/run.py'
spec=importlib.util.spec_from_file_location('ldo_regulation',REG);reg=importlib.util.module_from_spec(spec);spec.loader.exec_module(reg)
sha=reg.sha
FILES=[*reg.BIAS,*[ROOT/('analog/common/ldo/spice/'+x) for x in ('ldo_hv18_core.spice','ldo_power_switch.spice','pll_supply_hv18.spice')]]
OUT=ROOT/'results/analog/common/ldo/modes'


def deck(smoke=False):
    lines=['* HV18 r3 TT functional mode pilot',f'.lib "{project.model_library()}" tt']
    lines += [f'.include "{p.name}"' for p in FILES]
    lines += ['.temp 27','.options reltol=1e-4 abstol=1p vntol=1u']
    for mode in ('hv','bypass','off','change'):
        vhv='0' if mode=='bypass' else 'pwl(0 0 20n 0 120n 3.3)'
        hvsel={'hv':'pwl(0 0 20u 0 20.005u 1.8)','bypass':'0','off':'0','change':'pwl(0 0 20u 0 20.005u 1.8 22u 1.8 22.005u 0)'}[mode]
        extsel={'hv':'0','bypass':'pwl(0 0 220n 0 225n 1.8)','off':'0','change':'pwl(0 0 22.5u 0 22.505u 1.8)'}[mode]
        lines += [f'.subckt bench_{mode} gnd',f'Vdd vin 0 {vhv}','Vhost host 0 pwl(0 0 20n 0 120n 1.8)',
                  'Vext ext 0 pwl(0 0 20n 0 120n 1.8)',f'Vhsel hs 0 {hvsel}',f'Vesel es 0 {extsel}',
                  'Xbg ref host host host host vgi host 0 serdes_bias_ref trim=15',
                  'Xdut vin host ext out ref vgi hs es 0 serdes_pll_supply_hv18','Rload out 0 300',f'.ends bench_{mode}',f'X{mode} 0 bench_{mode}']
    lines += ['.control','set num_threads=1','set filetype=binary',f'tran 1n {"1n" if smoke else "25u"} 0 2n']
    for mode in ('hv','bypass','off','change'):
        lines += [f'let out_{mode}=v(x{mode}.out)',f'let reg_{mode}=v(x{mode}.xdut.reg)',f'let ref_{mode}=v(x{mode}.ref)',f'let vin_{mode}=v(x{mode}.vin)',
                  f'let ihv_{mode}=i(v.x{mode}.vdd)',f'let iext_{mode}=i(v.x{mode}.vext)',f'write {mode}.raw out_{mode} reg_{mode} ref_{mode} vin_{mode} ihv_{mode} iext_{mode}']
    return '\n'.join(lines+['quit','.endc','.end',''])


def prepare():
    c=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);(c/'source').mkdir(parents=True);(c/'prepared').mkdir()
    for p in [*FILES,SELF,REG,ROOT/'src/serdes_flow/spice.py',ROOT/'src/serdes_flow/project.py']:
        name='modes_runner.py' if p==SELF else ('regulation_runner.py' if p==REG else p.name)
        shutil.copyfile(p,c/'source'/name)
    for mode in ('smoke','run'):(c/'prepared'/(mode+'.cir')).write_text(deck(mode=='smoke'))
    plan=dict(pdk_sha256=reg.pdk_identity(),sources={p.name:sha(p) for p in (c/'source').iterdir()},decks={p.name:sha(p) for p in (c/'prepared').iterdir()},
              model_files={p.name:str(p.relative_to(ROOT)) for p in FILES},runtime={str(p.relative_to(ROOT)):sha(p) for p in [SELF,REG,ROOT/'src/serdes_flow/spice.py',ROOT/'src/serdes_flow/project.py']},t_end_s=25e-6)
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def analyse(c):
    p=json.loads((c/'plan.json').read_text());rows=[]
    r=c/'run';ex=json.loads((r/'execution.json').read_text())
    if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=p['decks']['run.cir'] or sha(r/'tb.cir')!=ex['deck_sha256']:raise ValueError('Execution failed')
    for name in p['model_files']:
        if sha(r/name)!=p['sources'][name] or ex['inputs_sha256'][name]!=p['sources'][name]:raise ValueError('Include changed')
    for mode in ('hv','bypass','off','change'):
        w=spice.Waves(r/(mode+'.raw'))
        if w.t[0]!=0 or w.t[-1]<25e-6*(1-1e-9):raise ValueError('Truncated output')
        v=w['out_'+mode];s=w.t>24e-6
        rows.append(dict(mode=mode,min_v=float(v.min()),max_v=float(v.max()),final_v=float(v[-1]),final_pp_mv=float(np.ptp(v[s])*1000),
                         supply_current_a=float(np.mean(w['ihv_'+mode][s])),external_current_a=float(np.mean(w['iext_'+mode][s])),
                         raw=str((r/(mode+'.raw')).relative_to(ROOT)),raw_sha256=sha(r/(mode+'.raw'))))
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    data=dict(campaign=str(c.relative_to(ROOT)),plan_sha256=sha(c/'plan.json'),execution_sha256=sha(r/'execution.json'),rows=rows,scope='TT real-bandgap functional modes only; no UVLO or controller qualification')
    (out/'summary.json').write_text(json.dumps(data,indent=2,allow_nan=False)+'\n');print(json.dumps(dict(analysis=str(out.relative_to(ROOT)),**data),indent=2))


def run(c):
    p=json.loads((c/'plan.json').read_text())
    if reg.pdk_identity()!=p['pdk_sha256']:raise ValueError('PDK changed')
    for rel,h in p['runtime'].items():
        if sha(ROOT/rel)!=h:raise ValueError('Runtime changed')
    for name,h in p['sources'].items():
        if sha(c/'source'/name)!=h:raise ValueError('Snapshot changed')
    for name,h in p['decks'].items():
        if sha(c/'prepared'/name)!=h:raise ValueError('Deck changed')
    if len(watch.ngspice_cwds())>=4:raise ValueError('No simulation slot')
    files={name:c/'source'/name for name in p['model_files']}
    ex=spice.run((c/'prepared/smoke.cir').read_text(),c/'smoke',files=files,timeout_s=240)
    if not ex.ok:raise ValueError('Smoke failed')
    ex=spice.run((c/'prepared/run.cir').read_text(),c/'run',files=files,timeout_s=600)
    if not ex.ok:raise ValueError('Run failed')
    analyse(c)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--run',type=Path);g.add_argument('--analyse',type=Path);a=ap.parse_args()
    if a.prepare:print(prepare().relative_to(ROOT))
    elif a.run:run(a.run.resolve())
    else:analyse(a.analyse.resolve())
