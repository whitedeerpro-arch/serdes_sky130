"""r4 noise with ONLY DC sources; recheck pass currents after every analysis.

Noise recomputes its own bias even after a valid .op. The default10us transient
OP fallback is shorter than the16us reference RC, including with pure DC
sources. Allow300us for fallback and compare both pass currents after every
spectrum. This check does not individually certify all reference/tail nodes.
"""
import argparse
import importlib.util
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from serdes_flow import project, spice, watch

ROOT=project.ROOT;SELF=Path(__file__).resolve();START=SELF.with_name('startup.py')
spec=importlib.util.spec_from_file_location('r4startup',START);st=importlib.util.module_from_spec(spec);spec.loader.exec_module(st)
sha=st.sha;OUT=ROOT/'results/analog/ldo/r4_dc_noise'
IDS={mode:f'@m.x{mode}.xdut.xcore.xpass.msky130_fd_pr__nfet_05v0_nvt[id]' for mode in ('hv2','hv10')}


def prepare(startup_campaign,pilot):
    pp=json.loads((startup_campaign/'plan.json').read_text());c=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);(c/'source').mkdir(parents=True);(c/'prepared').mkdir()
    for path in [SELF,START,*st.r4.RUNTIME,*st.CELLS]:
        q=c/'source'/path.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,q)
    entries=[]
    for old in pp['entries'][:1] if pilot else pp['entries']:
        e=dict(old);lines=[];mode=None
        for line in st.deck(e).split('.control')[0].splitlines():
            if line.startswith('.subckt bench_'):mode=line.split()[1].removeprefix('bench_')
            if line.startswith('Vdd '):line=f'Vdd vin 0 {e["bypass_v"] if mode=="bypass" else e["hv_v"]} ac 1'
            elif line.startswith('Vhost '):line=f'Vhost host 0 {e["host_v"]} ac 0'
            elif line.startswith('Venable '):line=f'Venable enable 0 {0 if mode=="bypass" else e["host_v"]}'
            lines.append(line)
        # Nodeset is a Newton starting guess, never a forced .ic. Every noise
        # bias is checked afterwards. The default10us optran is shorter than
        # the16us reference RC, so any fallback must be allowed to settle.
        for mode in ('hv2','hv10','bypass'):
            nodes={'rawref':1.23,'vgi':e['host_v']-.8,'xbg.xbg.s':1.23,'xbg.vg':.9,'xbg.xbg.ta':.95,'xbg.xbg.tb':.95,
                   'xdut.ref_local':0 if mode=='bypass' else 1.23,'quiet':e['bypass_v'] if mode=='bypass' else 1.8,
                   'xdut.xcore.gate':0 if mode=='bypass' else 2.4,'xdut.ibias':0 if mode=='bypass' else .9}
            lines.append('.nodeset '+' '.join(f'v(x{mode}.{key})={value}' for key,value in nodes.items()))
        lines += ['.control','set num_threads=1','set filetype=binary','optran 1 1 1 100n 300u 0','op','write op.raw v(xhv2.quiet) v(xhv10.quiet) '+ ' '.join(IDS.values()),'destroy all']
        for key,node,src in [('hv2','xhv2.quiet','v.xhv2.vdd'),('hv10','xhv10.quiet','v.xhv10.vdd'),('tail','xhv2.tail_filtered','v.xhv2.vhost')]:
            lines += [f'noise v({node}) {src} dec 40 1k 200meg','setplot noise1',f'write {key}_noise.raw frequency onoise_spectrum','print '+' '.join(IDS.values()),'destroy all']
        lines += ['quit','.endc','.end',''];path=c/'prepared'/(e['name']+'.cir');path.write_text('\n'.join(lines))
        if 'pwl(' in path.read_text().lower():raise ValueError('Transient source remains in noise view')
        e.update(deck=str(path.relative_to(c)),deck_sha256=sha(path));entries.append(e)
    plan=dict(entries=entries,pdk_sha256=pp['pdk_sha256'],startup_parent=str(startup_campaign.relative_to(ROOT)),startup_plan_sha256=sha(startup_campaign/'plan.json'),
              sources={str(p.relative_to(c)):sha(p) for p in (c/'source').rglob('*') if p.is_file()},runtime={str(p.relative_to(ROOT)):sha(p) for p in [SELF,START,*st.r4.RUNTIME]})
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def completed(c,e):
    for r in reversed([c/e['name']]+sorted(c.glob(e['name']+'.r[0-9]*'))):
        try:
            ex=json.loads((r/'execution.json').read_text());op=spice.Waves(r/'op.raw')
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=e['deck_sha256'] or sha(r/'tb.cir')!=e['deck_sha256']:continue
            if any(not 1.764<=float(op[f'v(x{mode}.quiet)'][0])<=1.836 for mode in ('hv2','hv10')):raise ValueError('OP outside local voltage target')
            if any(sha(r/path.name)!=sha(c/'source'/path.relative_to(ROOT)) or ex['inputs_sha256'][path.name]!=sha(c/'source'/path.relative_to(ROOT)) for path in st.CELLS):continue
            log=(r/'simulator.log').read_text()
            for mode,vector in IDS.items():
                current=float(op[vector][0]);values=[float(x) for x in re.findall(re.escape(vector)+r'\s*=\s*([-+0-9.eE]+)',log,re.I)]
                if len(values)!=3 or current<(.001 if mode=='hv2' else .007) or not np.allclose(values,current,rtol=1e-3):raise ValueError('Post-noise operating point mismatch')
            for key in ('hv2','hv10','tail'):
                w=spice.Waves(r/(key+'_noise.raw'));expected=1e3*10**(np.arange(213)/40)
                if len(w.t)!=213 or not np.allclose(w.t,expected,rtol=1e-9) or 'onoise_spectrum' not in w:raise ValueError('Incomplete noise')
            return r
        except (OSError,KeyError,ValueError):pass
    return None


def analyse(c,p):
    rows=[];missing=[]
    for e in p['entries']:
        r=completed(c,e)
        if r is None:missing.append(e['name']);continue
        op=spice.Waves(r/'op.raw')
        for mode in ('hv2','hv10','tail'):
            w=spice.Waves(r/(mode+'_noise.raw'))
            rows.append(dict(name=e['name'],mode=mode,mos=e['mos'],rc=e['rc'],temp_c=e['temp_c'],hv_v=e['hv_v'],host_v=e['host_v'],
                             rms_uv=float(np.sqrt(np.trapezoid(w['onoise_spectrum']**2,w.t))*1e6),dc_quiet_2ma_v=float(op['v(xhv2.quiet)'][0]),
                             dc_quiet_10ma_v=float(op['v(xhv10.quiet)'][0]),post_noise_pass_current_verified=True,run=str(r.relative_to(ROOT)),
                             evidence={x.name:sha(x) for x in [r/(mode+'_noise.raw'),r/'op.raw',r/'execution.json',r/'simulator.log']}))
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    (out/'summary.json').write_text(json.dumps(dict(campaign=str(c.relative_to(ROOT)),plan_sha256=sha(c/'plan.json'),analyzer_sha256=sha(SELF),rows=rows,missing=missing,
                                                  scope='Pure DC 1kHz..199.5MHz, actual BG/CML copy, physical passives, post-noise pass currents rechecked; not all slow-node bias/measurement-silicon PSD/whole-PLL jitter qualification'),indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(analysis=str(out.relative_to(ROOT)),rows=rows,missing=missing),indent=2))


def resume(c,workers):
    p=json.loads((c/'plan.json').read_text())
    if st.r4.reg.pdk_identity()!=p['pdk_sha256']:raise ValueError('PDK changed')
    for rel,h in p['sources'].items():
        if sha(c/rel)!=h:raise ValueError('Snapshot changed')
    for rel,h in p['runtime'].items():
        if sha(ROOT/rel)!=h:raise ValueError('Runtime changed')
    active=watch.ngspice_cwds()
    if any(x.is_relative_to(c) for x in active) or len(active)+workers>4:raise ValueError('No slots/already active')
    files={path.name:c/'source'/path.relative_to(ROOT) for path in st.CELLS}
    jobs=[((c/e['deck']).read_text(),spice.next_run_dir(c,e['name']),dict(files=files,timeout_s=300)) for e in p['entries'] if completed(c,e) is None]
    spice.run_many(jobs,workers=workers,smoke=False);analyse(c,p)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True);g.add_argument('--prepare',type=Path);g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path);ap.add_argument('--pilot',action='store_true');ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare:print(prepare(a.prepare.resolve(),a.pilot).relative_to(ROOT))
    elif a.resume:resume(a.resume.resolve(),a.workers)
    else:analyse(a.analyse.resolve(),json.loads((a.analyse/'plan.json').read_text()))
