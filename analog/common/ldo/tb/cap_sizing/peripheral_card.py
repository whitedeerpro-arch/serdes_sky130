"""Compare physical1Mohm/16pF filters, with declared1/5pF gate surrogates.

Full PDK, pure DC source, AC and resistor noise. This is a passive interface
card, not an oscillator/PLL jitter or startup qualification.
"""
from datetime import datetime,timezone
import argparse
import json
from pathlib import Path
import shutil

import numpy as np
from serdes_flow import project,spice,watch

ROOT=project.ROOT
OLD=ROOT/'results/layout/ldo_pdk/20261114_r4_full_suite/serdes_pll_bias_lowpass_slow_r4_pdk/serdes_pll_bias_lowpass_slow_r4_pdk_pex.spice'
NEW=ROOT/'results/layout/ldo_stacked/20261114_filter16_v2/serdes_pll_bias_lowpass_slow_r4_pdk/serdes_pll_bias_lowpass_stacked_pdk_pex.spice'


def prepare():
    camp=ROOT/'results/analog/common/ldo/stacked_peripheral'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    source=camp/'source';source.mkdir(parents=True)
    shutil.copyfile(OLD,source/'old.spice');shutil.copyfile(NEW,source/'new.spice');shutil.copyfile(__file__,source/'runner.py')
    entries=[]
    for section,temp in [('tt',27),('fs_ll',85),('ss_hh',-40)]:
        body=['* physical peripheral filter comparison',f'.lib "{project.model_library()}" {section}',
              '.include "old.spice"','.include "new.spice"','Vs input 0 1.2 ac 1',
              'Xold input old 0 serdes_pll_bias_lowpass_slow_r4_pdk',
              'Xnew input new 0 serdes_pll_bias_lowpass_stacked_pdk',
              'Cgo old 0 1p','Cgn new 0 1p',f'.temp {temp}',
              '.options reltol=1e-6 abstol=1p vntol=1u','.control','set num_threads=1',
              'set filetype=binary','set wr_singlescale','set wr_vecnames','op',
              'write op.raw v(input) v(old) v(new)','destroy all']
        for load in (1,5):
            body += [f'alter Cgo {load}p',f'alter Cgn {load}p','ac dec 40 100 100meg',
                     'let ro=real(v(old))','let io=imag(v(old))','let rn=real(v(new))','let inn=imag(v(new))',
                     f'wrdata ac_{load}.tsv ro io rn inn','destroy all']
        body += ['alter Cgo 1p','alter Cgn 1p']
        for i,node in enumerate(('old','new'),1):
            body += [f'noise v({node}) Vs dec 40 100 100meg','setplot noise1',
                     f'write {node}_noise.raw frequency onoise_spectrum','destroy all','op',
                     f'write {node}_post.raw v(old) v(new)','destroy all']
        text='\n'.join(body+['quit','.endc','.end',''])
        path=camp/(section+'.cir');path.write_text(text);entries.append(dict(section=section,temp_c=temp,deck=path.name))
    import hashlib
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    (camp/'plan.json').write_text(json.dumps(dict(entries=entries,sha256={str(p.relative_to(camp)):sha(p) for p in camp.rglob('*') if p.is_file()},pdk=project.pdk_installation_id()),indent=2)+'\n')
    return camp


def run(camp,workers):
    import hashlib
    p=json.loads((camp/'plan.json').read_text())
    if p['pdk']!=project.pdk_installation_id():raise ValueError('PDK changed')
    for rel,h in p['sha256'].items():
        if hashlib.sha256((camp/rel).read_bytes()).hexdigest()!=h:raise ValueError('Input changed')
    if len(watch.ngspice_cwds())+workers>4:raise ValueError('Global ngspice slots occupied')
    files={k:camp/'source'/k for k in ('old.spice','new.spice')}
    jobs=[((camp/e['deck']).read_text(),spice.next_run_dir(camp,e['section']),dict(files=files,timeout_s=180)) for e in p['entries']]
    ex=spice.run_many(jobs,workers=workers,smoke=False)
    if any(not r.ok for r in ex):raise ValueError('Peripheral card execution failed')
    return analyse(camp,[r.run_dir for r in ex])


def analyse(camp,folders=None):
    import hashlib
    p=json.loads((camp/'plan.json').read_text());rows=[]
    if p['pdk']!=project.pdk_installation_id():raise ValueError('PDK changed')
    for rel,h in p['sha256'].items():
        if hashlib.sha256((camp/rel).read_bytes()).hexdigest()!=h:raise ValueError('Frozen input changed')
    if folders is None:
        folders=[]
        for e in p['entries']:
            candidates=[camp/e['section']]+sorted(camp.glob(e['section']+'.r[0-9]*'))
            valid=[]
            for folder in candidates:
                if not (folder/'execution.json').exists():continue
                ex=json.loads((folder/'execution.json').read_text())
                if ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and (folder/'tb.cir').read_text()==(camp/e['deck']).read_text():valid.append(folder)
            if not valid:raise ValueError('No complete matching card execution')
            folders.append(valid[-1])
    for e,folder in zip(p['entries'],folders):
        op=spice.Waves(folder/'op.raw')
        # Multiple internal passive nodes accumulate a few1uV Newton residuals.
        # Certify against10uV, rather than asking the output to beat vntol.
        if any(abs(op[f'v({n})'][0]-1.2)>1e-5 for n in ('old','new')):raise ValueError('Wrong DC bias')
        rr=[]
        for load in (1,5):
            a=np.loadtxt(folder/f'ac_{load}.tsv',skiprows=1)
            if a.shape!=(241,5) or not np.allclose(a[:,0],np.geomspace(100,1e8,241),rtol=1e-6):raise ValueError('Incomplete AC')
            gains=[np.hypot(a[:,j],a[:,j+1]) for j in (1,3)]
            fc=[float(np.exp(np.interp(1/np.sqrt(2),g[::-1],np.log(a[::-1,0])))) for g in gains]
            rr.append(dict(load_pf=load,old_fc_hz=fc[0],new_fc_hz=fc[1],relative_fc=fc[1]/fc[0]))
        noise={}
        for node in ('old','new'):
            w=spice.Waves(folder/f'{node}_noise.raw');post=spice.Waves(folder/f'{node}_post.raw')
            if len(w.t)!=241 or not np.allclose(w.t,np.geomspace(100,1e8,241),rtol=1e-6):raise ValueError('Incomplete noise')
            if any(abs(post[f'v({n})'][0]-op[f'v({n})'][0])>1e-5 for n in ('old','new')):raise ValueError('Noise OP changed')
            noise[node]=float(np.sqrt(np.trapezoid(w['onoise_spectrum']**2,w.t))*1e6)
        rows.append(dict(e,run=str(folder.relative_to(ROOT)),ac=rr,noise_uv=noise))
    dest=camp/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');dest.mkdir(parents=True)
    summary=dict(campaign=str(camp.relative_to(ROOT)),rows=rows,scope=__doc__,dc_numeric_tolerance_v=1e-5,
                 analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),grade='ungraded passive comparison, no system jitter allocation')
    (dest/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(dict(summary=str((dest/'summary.json').relative_to(ROOT)),rows=rows),indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--run',type=Path);g.add_argument('--analyse',type=Path)
    ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare:print(prepare())
    elif a.run:run(a.run.resolve(),a.workers)
    else:analyse(a.analyse.resolve())
