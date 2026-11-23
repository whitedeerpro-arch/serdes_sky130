"""Calibrate the actual r4 passive views, including hierarchy count and ESR."""
import argparse
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
sha=r4.sha;CELL=ROOT/'analog/ldo/spice/ldo_passives.spice'
OUT=ROOT/'results/analog/ldo/r4_passive_card'
RES=(1000,2000,10000,38000,62000,82000,100000,1000000);CAP=(1,2,16,50,100)


def name(t,v):return f't{t}_b{round(v*1000)}'


def deck(lib):
    lines=['* Actual HV18 r4 resistor and MIM views',f'.lib "{project.model_library()}" {lib}', '.include "passives.spice"','Vbias bias 0 1.23']
    for n,value in enumerate(RES):
        lines += [f'Vu{n} r{n} bias .01',f'Xr{n} r{n} bias 0 '+('serdes_ldo_ref_res' if value==1000000 else f'serdes_ldo_res r={value}')]
    for value in CAP:lines += [f'Vc{value} c{value} 0 dc 1.8 ac 1',f'Xc{value} c{value} 0 serdes_ldo_mim{value}']
    lines += ['.options reltol=1e-6 abstol=1f vntol=1n','.save all','.control','set num_threads=1','set filetype=binary','set wr_singlescale','set wr_vecnames']
    for temp in (-40,27,85):
        for bias in (0,1.23,3.3):
            stem=name(temp,bias);lines += [f'option temp={temp}',f'dc Vbias {bias} {bias+.000001} .000001',f'write {stem}_dc.raw '+ ' '.join(f'i(Vu{n})' for n in range(len(RES))),'destroy all',f'alter Vbias dc={bias}','ac dec 1 1k 1meg']
            for value in CAP:lines += [f'let r{value}=real(i(Vc{value}))',f'let q{value}=imag(i(Vc{value}))']
            lines += [f'wrdata {stem}_ac.tsv '+' '.join(f'r{value} q{value}' for value in CAP),'destroy all']
    return '\n'.join(lines+['quit','.endc','.end',''])


def prepare():
    c=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);(c/'source').mkdir(parents=True);(c/'prepared').mkdir()
    paths=[SELF,RUN,r4.REG,CELL,ROOT/'src/serdes_flow/spice.py',ROOT/'src/serdes_flow/project.py',ROOT/'config/pdk.toml',ROOT/'config/tools.toml']
    for p in paths:
        q=c/'source'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
    for lib in ('tt','ll','hh'):(c/'prepared'/(lib+'.cir')).write_text(deck(lib))
    p=dict(pdk_sha256=r4.reg.pdk_identity(),runtime={str(p.relative_to(ROOT)):sha(p) for p in paths if p!=CELL},sources={str(p.relative_to(c)):sha(p) for p in (c/'source').rglob('*') if p.is_file()},decks={p.stem:sha(p) for p in (c/'prepared').iterdir()})
    (c/'plan.json').write_text(json.dumps(p,indent=2)+'\n');return c


def completed(c,lib,p):
    for r in reversed([c/lib]+sorted(c.glob(lib+'.r[0-9]*'))):
        try:
            ex=json.loads((r/'execution.json').read_text())
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or sha(r/'tb.cir')!=p['decks'][lib] or ex['deck_sha256']!=p['decks'][lib] or sha(r/'passives.spice')!=sha(c/'source'/CELL.relative_to(ROOT)):continue
            for t in (-40,27,85):
                for b in (0,1.23,3.3):
                    stem=name(t,b);w=spice.Waves(r/(stem+'_dc.raw'));a=np.loadtxt(r/(stem+'_ac.tsv'),skiprows=1)
                    if len(w.t)!=2 or not np.allclose(w.t,[b,b+.000001],atol=1e-12,rtol=0) or a.shape!=(4,11) or not np.all(np.isfinite(a)) or not np.allclose(a[:,0],[1e3,1e4,1e5,1e6]):raise ValueError('Incomplete card grid')
            return r
        except (OSError,KeyError,ValueError):pass
    return None


def analyse(c,p):
    rows=[];missing=[]
    for lib in p['decks']:
        r=completed(c,lib,p)
        if r is None:missing.append(lib);continue
        for temp in (-40,27,85):
            for bias in (0,1.23,3.3):
                stem=name(temp,bias);w=spice.Waves(r/(stem+'_dc.raw'));a=np.loadtxt(r/(stem+'_ac.tsv'),skiprows=1)
                rows.append(dict(rc=lib,temp_c=temp,commonmode_v=bias,resistance_ohm={str(value):float(-.01/w[f'i(vu{n})'][0]) for n,value in enumerate(RES)},
                                 capacitance_pf={str(value):float(-1/(2*np.pi*1e6*((-1/complex(a[-1,1+2*n],a[-1,2+2*n])).imag))*1e12) for n,value in enumerate(CAP)},
                                 series_resistance_ohm={str(value):float((-1/complex(a[-1,1+2*n],a[-1,2+2*n])).real) for n,value in enumerate(CAP)},
                                 run=str(r.relative_to(ROOT)),evidence={path.name:sha(path) for path in [r/(stem+'_dc.raw'),r/(stem+'_ac.tsv'),r/'execution.json']}))
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    (out/'summary.json').write_text(json.dumps(dict(campaign=str(c.relative_to(ROOT)),plan_sha256=sha(c/'plan.json'),rows=rows,missing=missing),indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(analysis=str(out.relative_to(ROOT)),conditions=len(rows),missing=missing)))


def execute(c,workers):
    p=json.loads((c/'plan.json').read_text())
    if r4.reg.pdk_identity()!=p['pdk_sha256']:raise ValueError('PDK changed')
    for rel,h in p['sources'].items():
        if sha(c/rel)!=h:raise ValueError('Source changed')
    for rel,h in p['runtime'].items():
        if sha(ROOT/rel)!=h:raise ValueError('Runtime changed')
    active=watch.ngspice_cwds()
    if any(x.is_relative_to(c) for x in active) or len(active)+workers>4:raise ValueError('No slots/already running')
    jobs=[((c/'prepared'/(lib+'.cir')).read_text(),spice.next_run_dir(c,lib),dict(files={'passives.spice':c/'source'/CELL.relative_to(ROOT)},timeout_s=240)) for lib in p['decks'] if completed(c,lib,p) is None]
    spice.run_many(jobs,workers=workers,smoke=False);analyse(c,p)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True);g.add_argument('--prepare',action='store_true');g.add_argument('--resume',type=Path);ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare:print(prepare().relative_to(ROOT))
    else:execute(a.resume.resolve(),a.workers)
