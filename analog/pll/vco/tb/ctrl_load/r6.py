"""r6 control admittance: declared ring/buffer proxy, real bias and slow tail RC."""
import argparse
from datetime import datetime,timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np
from serdes_flow import bias,clock,project,rcorner,spectral,spice,watch

ROOT=project.ROOT
SELF=Path(__file__).resolve()
OUT=ROOT/'results/analog/pll/vco/ctrl_load_r6'
INCLUDES=('analog/common/devices/spice/sky130_primitives.spice',
 'analog/common/devices/spice/sky130_pfet_lvt.spice',
 'analog/common/cml_buffer/spice/cml_delay_resistive.spice',
 'analog/common/cml_buffer/spice/cml_buffer.spice',
 'analog/pll/vco/spice/cap_bank_5b.spice','analog/pll/vco/spice/vco_delay_r6.spice',
 'analog/pll/vco/spice/vco_ring4_r6.spice','analog/ldo/spice/ldo_passives.spice',
 'analog/ldo/spice/pll_bias_filter_r4.spice')
PROBES='v(ctrl) v(ctrl_dc) i(vsin) v(v0p) v(v0n) v(vbias_q)'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def deck(c,e):
    voltage=e['vctrl_v'];fm=e['fm_hz'];amp=e['amp_v'];stop=e['t_end_s']
    lines=['r6 control admittance, independent ring and four30fF-loaded buffers',
           f'.lib "{project.model_library()}" tt']
    lines += [f'.include "{ROOT/p}"' for p in INCLUDES]
    lines += ['Vdd vdd 0 1.8','Vq vq 0 1.8','Iref vdd vbias .85m',
              'Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4',
              'Xtail vbias vbias_q 0 serdes_pll_bias_lowpass_slow_r4',
              f'Vctrl ctrl_dc 0 {voltage:.12g}',f'Vsin ctrl ctrl_dc SIN(0 {amp:.12g} {fm:.12g} 20n)']
    lines += [f'Vb{k} cfg{k} 0 {1.8*((e["code"]>>k)&1):.12g}' for k in range(5)]
    lines += ['Xvco v0p v0n v1p v1n v2p v2n v3p v3n ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vbias_q vq 0 pll_vco_ring4_r6']
    for k in range(4):
        lines += [f'Xbuf{k} v{k}p v{k}n b{k}p b{k}n vbias_q vq 0 serdes_cml_buffer',
                  f'Cb{k}p b{k}p 0 30f',f'Cb{k}n b{k}n 0 30f']
    lines += ['Ikick v0p v0n PWL(0 1u 20p 1u 21p 0)',
              '.temp 27','.options reltol=1e-4 abstol=1p vntol=1u',
              '.save '+PROBES,'.control','set num_threads=1','set filetype=binary',
              f'tran 2p {stop:.12g} 10n 2p','write ctrl.raw '+PROBES,'quit','.endc','.end','']
    return bias.section(rcorner.to_pdk_fixed(bias.real('\n'.join(lines)),c/'snap'),'tt','tt')


def prepare(map_path,frequencies=(50e6,),amplitudes=(0.,.005,.01),with_dc=True):
    if (not frequencies or not amplitudes or any(not np.isfinite(f) or f<=0 for f in frequencies)
            or any(not np.isfinite(a) or a<0 for a in amplitudes)):
        raise ValueError('Invalid tone frequencies/amplitudes')
    m=json.loads(map_path.read_text())['rows']['tt_v1800_t27:tt'];code=m['best'];voltage=m['v'][str(code)]
    c=OUT/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');(c/'prepared').mkdir(parents=True)
    entries=[]
    for fm in frequencies:
        for amp in amplitudes:
            e=dict(name=f'f{fm/1e6:g}_a{amp*1e3:g}',code=code,vctrl_v=voltage,fm_hz=fm,amp_v=amp,t_end_s=20e-9+3/fm)
            (c/'prepared'/(e['name']+'.cir')).write_text(deck(c,e));entries.append(e)
    for dv in (-.01,.01) if with_dc else ():
        e=dict(name='dc_'+('lo' if dv<0 else 'hi'),code=code,vctrl_v=voltage+dv,fm_hz=50e6,amp_v=0.,t_end_s=20e-9)
        (c/'prepared'/(e['name']+'.cir')).write_text(deck(c,e));entries.append(e)
    e=entries[0];smoke=re.sub(r'^tran .*$', 'tran 2p 1n 0 2p', (c/'prepared'/(e['name']+'.cir')).read_text(),flags=re.M)
    (c/'prepared/smoke.cir').write_text(smoke)
    sources={SELF,map_path,*[ROOT/p for p in (*INCLUDES,*bias.BIAS_INC)],
             *[ROOT/'src/serdes_flow'/(n+'.py') for n in ('bias','rcorner','clock','spectral','spice','project','waves','watch')]}
    for p in sources:
        dst=c/'source'/p.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dst)
    plan=dict(entries=entries,pdk_id=project.pdk_installation_id(),model_sha256=sha(project.model_library()),
              snapshots={str(p.relative_to(c)):sha(p) for p in c.rglob('*') if p.is_file()},
              scope='TT, map code/Vctrl, full PDK, r6 ring+4buffers each30fF, actual slow tail RC/real BG; not loaded frontend, closed-loop, PEX, full PVT or noise qualification')
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def check(c):
    p=json.loads((c/'plan.json').read_text())
    if p['pdk_id']!=project.pdk_installation_id() or p['model_sha256']!=sha(project.model_library()):raise ValueError('PDK changed')
    for n,h in p['snapshots'].items():
        if sha(c/n)!=h:raise ValueError('Frozen source changed: '+n)
    return p


def complete(c,name,end):
    for d in reversed([c/name]+sorted(c.glob(name+'.r[0-9]*'))):
        try:
            ex=json.loads((d/'execution.json').read_text())
            if ex['exit_code'] or ex['timed_out'] or ex['log_failures']:continue
            if (d/'tb.cir').read_text()!=(c/'prepared'/(name+'.cir')).read_text():continue
            w=spice.Waves(d/'ctrl.raw')
            if w.t[-1]<end*(1-1e-9) or not np.all(np.isfinite(w.data)) or any(v not in w for v in PROBES.split()):continue
            return d
        except (OSError,ValueError,KeyError):pass
    return None


def analyse(c):
    p=check(c);rows=[];missing=[]
    for e in p['entries']:
        d=complete(c,e['name'],e['t_end_s'])
        if d is None:missing.append(e['name']);continue
        w=spice.Waves(d/'ctrl.raw');fm=e['fm_hz'];end=e['t_end_s']
        start=20e-9+1/fm if e['amp_v'] or e['name'].startswith('f') else 12e-9
        z=spectral.tone(w.t,-w['i(vsin)'],fm,start,end)
        row=dict(e,run=str(d.relative_to(ROOT)),window_s=[start,end],
                 i_real_a=z['phasor'].real,i_imag_a=z['phasor'].imag,
                 frequency=clock.period_stats(w.t,w['v(v0p)']-w['v(v0n)'],start=start,stop=end))
        if e['amp_v']:
            v=spectral.tone(w.t,w['v(ctrl)']-w['v(ctrl_dc)'],fm,start,end)['phasor']
            y=z['phasor']/v
            row.update(y_real_s=y.real,y_imag_s=y.imag,c_f=y.imag/(2*np.pi*fm),v_amp_v=abs(v))
        rows.append(row)
    by={r['name']:r for r in rows}
    for r in rows:
        if r['amp_v']:
            baseline=by.get(f'f{r["fm_hz"]/1e6:g}_a0')
            if baseline:
                r['baseline_tone_to_signal']=float(np.hypot(baseline['i_real_a'],baseline['i_imag_a'])/np.hypot(r['i_real_a'],r['i_imag_a']))
    kv=(by['dc_hi']['frequency']['frequency_hz']-by['dc_lo']['frequency']['frequency_hz'])/.02 if {'dc_hi','dc_lo'}<=by.keys() else None
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    result=dict(campaign=str(c.relative_to(ROOT)),rows=rows,missing=missing,kvco_hz_v=kv,scope=p['scope'])
    (out/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps(result,indent=2),flush=True);print(out.relative_to(ROOT),flush=True)


def resume(c,timeout):
    with (c/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=check(c)
        if len(watch.ngspice_cwds())>=4:raise ValueError('Global ngspice slots occupied')
        for e in [dict(name='smoke',t_end_s=1e-9),*p['entries']]:
            if complete(c,e['name'],e['t_end_s']):continue
            name=e['name'];ex=spice.run((c/'prepared'/(name+'.cir')).read_text(),spice.next_run_dir(c,name),timeout_s=timeout)
            print(name,ex.ok,round(ex.elapsed_s,1),flush=True)
            if complete(c,name,e['t_end_s']) is None:break
        analyse(c)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',type=Path);g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path)
    ap.add_argument('--timeout',type=float,default=1800)
    ap.add_argument('--frequencies',type=float,nargs='+',default=[50e6])
    ap.add_argument('--amplitudes',type=float,nargs='+',default=[0.,.005,.01])
    ap.add_argument('--no-dc',action='store_true');a=ap.parse_args()
    if a.prepare:print(prepare(a.prepare.resolve(),a.frequencies,a.amplitudes,not a.no_dc))
    elif a.resume:resume(a.resume.resolve(),a.timeout)
    else:analyse(a.analyse.resolve())
