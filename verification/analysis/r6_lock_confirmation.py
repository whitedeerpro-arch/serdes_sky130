"""Score an explicit completed r6 native waveform against the project contract."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import tomllib

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import clock,feedback,pll_lock,pnoise,project,spice,waves

ROOT=project.ROOT


def identity(p):
    p=Path(p)
    return dict(path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest())


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--native-summary',type=Path,required=True)
    ap.add_argument('--admittance-summary',type=Path,nargs='+',default=[])
    ap.add_argument('--interface-summary',type=Path)
    ap.add_argument('--varactor-noise-summary',type=Path)
    ap.add_argument('--varactor-noise-corrected-summary',type=Path)
    ap.add_argument('--varactor-equivalence-summary',type=Path)
    ap.add_argument('--mismatch-summary',type=Path)
    ap.add_argument('--prefix-native-summary',type=Path);a=ap.parse_args()
    src=a.native_summary.resolve();summary=json.loads(src.read_text());c=ROOT/summary['campaign']
    contract=ROOT/'verification/contracts/pll_lock_screen.toml';cfg=tomllib.loads(contract.read_text())
    plan=json.loads((c/'plan.json').read_text())
    if hashlib.sha256((c/'plan.json').read_bytes()).hexdigest()!=summary['plan_sha256']:raise ValueError('Native plan changed')
    inputs=[identity(src),identity(c/'plan.json'),identity(contract),identity(Path(__file__).resolve()),
            identity(ROOT/'src/serdes_flow/pll_lock.py'),identity(ROOT/'src/serdes_flow/clock.py')]
    inputs.extend(identity(ROOT/'src/serdes_flow'/(n+'.py')) for n in ('feedback','pnoise','waves'))
    rows=[]
    folder=ROOT/'docs/figures/clocking/pll/core';folder.mkdir(parents=True,exist_ok=True)
    for row in summary['rows']:
        if row['state']!='measured':continue
        d=ROOT/row['run'];ex=json.loads((d/'execution.json').read_text());raw=d/'loop.raw'
        if ex['exit_code'] or ex['timed_out'] or ex['log_failures']:raise ValueError('Execution failed')
        entry=next(e for e in plan['entries'] if e['name']==row['name'])
        if (d/'tb.cir').read_bytes()!=(c/'prepared'/(entry['name']+'.cir')).read_bytes():raise ValueError('Deck changed')
        inputs.extend(identity(p) for p in (raw,d/'tb.cir',d/'execution.json'))
        w=spice.Waves(raw)
        if w.t[-1]<entry['t_end_s']*(1-1e-9) or not np.all(np.isfinite(w.data)):raise ValueError('Incomplete waveform')
        refs=clock.edges(w.t,w['v(ref)']-w['v(ref)'].max()/2)
        fb=clock.edges(w.t,w['v(fb0)']-w['v(fb0)'].max()/2)
        eng=pll_lock.screen(refs,fb,start=55e-9,stop=float(w.t[-1]),period=4e-9,
            window_cycles=cfg['reference_window_cycles'],stride_cycles=cfg['window_stride_cycles'],
            frequency_tolerance=cfg['maximum_relative_frequency_error'],phase_span=cfg['maximum_unwrapped_phase_span_s'],hold=cfg['required_hold_time_s'])
        start=float(w.t[-1]-200e-9);end=float(w.t[-1]);sel=w.t>=start
        stats=clock.period_stats(w.t,w['v(b0p)']-w['v(b0n)'],start,end)
        b0edges=clock.edges(w.t,w['v(b0p)']-w['v(b0n)'],start=start,stop=end)
        tie=b0edges-b0edges[0]-np.arange(len(b0edges))/2e9 if len(b0edges)>1 else np.array([])
        periods8=8*((len(b0edges)-1)//8)
        aligned=dict(periods=periods8,frequency_hz=float(periods8/(b0edges[periods8]-b0edges[0]))) if periods8 else None
        tail20=end-20e-9
        pulses={key:len(clock.edges(w.t,w['v('+key+')']-.9,start=tail20,stop=end)) for key in ('ref','up','dn')}
        widths={}
        for key in ('up','dn'):
            rise=clock.edges(w.t,w['v('+key+')']-.9,start=tail20,stop=end)
            fall=clock.edges(w.t,w['v('+key+')']-.9,-1,start=tail20,stop=end)
            values=[float(fall[i]-t) for t in rise if (i:=int(np.searchsorted(fall,t)))<len(fall)]
            widths[key]=dict(complete_pulses=len(values),mean_s=float(np.mean(values)) if values else None,
                             minimum_s=min(values) if values else None,maximum_s=max(values) if values else None)
        result=dict(point=row['point'],variant=row['variant'],code=row['code'],
                    run=row['run'],actual_start_s=float(w.t[0]),actual_end_s=end,elapsed_s=ex['elapsed_s'],
                    engineering_lock=eng,last200ns_output=stats,last20ns_rising_pulses=pulses,
                    last20ns_logic_pulse_widths=widths,
                    last200ns_complete_div8_groups=aligned,
                    fixed_2ghz_tie_pp_last200_s=float(np.ptp(tie)) if len(tie) else None,
                    tie_scope='Fixed nominal2GHz rising-edge grid, DC phase removed; includes deterministic modulation/drift; noiseless transient, not random jitter',
                    last200ns_ctrl_mean_v=waves.time_average(w['v(ctrl)'][sel],w.t[sel]),last200ns_ctrl_pp_v=float(np.ptp(w['v(ctrl)'][sel])),
                    scope='Precharged, noiseless native r6/ext; ideal PFD reference and rails, explicit kicks; no power-up, TX eye, PEX or stochastic-jitter qualification')
        rows.append(result)
        fig,axs=plt.subplots(3,1,figsize=(8,7),layout='constrained')
        axs[0].plot(w.t*1e9,w['v(ctrl)'],lw=.8,label='Vctrl');axs[0].plot(w.t*1e9,w['v(z)'],lw=.8,label='LF integrator')
        if eng['hold_start_s'] is not None:
            axs[0].axvspan(eng['hold_start_s']*1e9,eng['windows'][-1]['end_s']*1e9,color='#65a68a',alpha=.15,label='passing hold')
        axs[0].set(xlabel='Time (ns)',ylabel='Voltage (V)');axs[0].legend(fontsize=8)
        edges=clock.edges(w.t,w['v(b0p)']-w['v(b0n)'],start=start,stop=end)
        axs[1].plot((edges[8:]+edges[:-8])*.5e9,(8/(edges[8:]-edges[:-8])/2e9-1)*1e6,lw=.8)
        axs[1].set(xlabel='Time (ns)',ylabel='8-cycle mean error (ppm)',title='Noiseless output: final200ns; not random jitter')
        windows=eng['windows']
        axs[2].plot([r['end_s']*1e9 for r in windows],[r['phase_span_s']*1e12 for r in windows],marker='.',lw=.8)
        axs[2].axhline(20,color='grey',ls='--',lw=.8)
        axs[2].set(xlabel='32-cycle window end (ns)',ylabel='Unwrapped phase span (ps)')
        for ax in axs:ax.grid(alpha=.2)
        fig.suptitle(f"r6 {row['point']} {row['variant']}; engineering screen: {eng['status']}")
        fig.savefig(folder/(row['name']+'_lock_confirmation.png'),dpi=160);plt.close(fig)
    prefix=[]
    if a.prefix_native_summary:
        p=a.prefix_native_summary.resolve();old=json.loads(p.read_text());inputs.append(identity(p))
        oc=ROOT/old['campaign'];oi=identity(oc/'plan.json');inputs.append(oi)
        if oi['sha256']!=old['plan_sha256']:raise ValueError('Prefix plan changed')
        for row in old['rows']:
            if row['state']!='measured':continue
            new=next((r for r in rows if (r['point'],r['variant'],r['code'])==(row['point'],row['variant'],row['code'])),None)
            if new is None:continue
            d=ROOT/row['run'];inputs.extend(identity(d/n) for n in ('loop.raw','tb.cir','execution.json'))
            wa=spice.Waves(d/'loop.raw');wb=spice.Waves(ROOT/new['run']/'loop.raw')
            start=max(wa.t[0],wb.t[0]);end=min(wa.t[-1],wb.t[-1])-10e-9
            sel=(wa.t>=start)&(wa.t<=end)
            errors={n:float(np.max(np.abs(wa[n][sel]-np.interp(wa.t[sel],wb.t,wb[n]))))
                    for n in ('v(ctrl)','v(z)','v(b0p)','v(b0n)','v(fb0)','v(up)','v(dn)')}
            prefix.append(dict(point=row['point'],variant=row['variant'],old_run=row['run'],new_run=new['run'],
                               start_s=float(start),end_s=float(end),max_abs_voltage_errors_v=errors))
        if not prefix:raise ValueError('No matching prefix record')
    admittance=[]
    for item in a.admittance_summary:
        p=item.resolve();r=json.loads(p.read_text());inputs.append(identity(p))
        if r['missing']:raise ValueError('Incomplete admittance input')
        acamp=ROOT/r['campaign'];aplan=json.loads((acamp/'plan.json').read_text());inputs.append(identity(acamp/'plan.json'))
        for rel,digest in aplan['snapshots'].items():
            if hashlib.sha256((acamp/rel).read_bytes()).hexdigest()!=digest:raise ValueError('Admittance input changed')
        for item in r['rows']:
            inputs.extend(identity(ROOT/item['run']/n) for n in ('ctrl.raw','tb.cir','execution.json'))
        admittance.append(r)
    admittance_quality={}
    responses=[r for a in admittance for r in a['rows'] if r['amp_v']]
    fifty=[r for r in responses if r['fm_hz']==50e6]
    if len(fifty)>1:
        caps=[r['c_f'] for r in fifty]
        admittance_quality['cap_amplitude_relative_span_50mhz']=(max(caps)-min(caps))/np.mean(caps)
    if responses:
        admittance_quality['maximum_background_to_signal']=max(r['baseline_tone_to_signal'] for r in responses)
    baselines=[r for a in admittance for r in a['rows'] if r['name'].startswith('f') and r['amp_v']==0]
    if len(baselines)==2:
        wa,wb=[spice.Waves(ROOT/r['run']/'ctrl.raw') for r in baselines]
        use=wa.t<min(wa.t[-1],wb.t[-1])-5e-9
        admittance_quality['matched_dc_prefix_max_abs']={n:float(np.max(np.abs(wa[n][use]-np.interp(wa.t[use],wb.t,wb[n])))) for n in ('v(v0p)','v(v0n)','v(ctrl)','i(vsin)')}
    local_model=None
    if admittance:
        tones=[r for a in admittance for r in a['rows'] if r['amp_v']]
        low=min(r['fm_hz'] for r in tones)
        cap=float(np.mean([r['c_f'] for r in tones if r['fm_hz']==low]))
        kv=next((a['kvco_hz_v'] for a in admittance if a['kvco_hz_v'] is not None),None)
        if kv is not None:
            lp=pnoise.Loop(icp=200e-6,rz=4130,ci=18e-12,cf=cap,kvco=kv,n=8,delay=2e-9)
            f=np.geomspace(1e4,1e9,5001)
            local_model=dict(cf_f=cap,kvco_hz_v=kv,cf_measure_hz=low,crossings=feedback.unity_crossings(f,lp.open_loop(f)),
                scope='Local ring/buffer proxy C and Kvco; nominal CP/LF and assumed2ns delay; excludes control conductance, frontend/CP/LF PVT, nonlinear and noise effects; not stability qualification')
    interface=None
    if a.interface_summary:
        p=a.interface_summary.resolve();inputs.append(identity(p));interface=json.loads(p.read_text())
        ic=ROOT/interface['campaign'];inputs.extend(identity(ic/n) for n in ('plan.json','parent_evidence.json'))
        inputs.extend(identity(ROOT/interface['run']/n) for n in ('tb.cir','execution.json','loop.raw'))
        iw=spice.Waves(ROOT/interface['run']/'loop.raw')
        interface['loaded_engineering_lock']=pll_lock.screen(
            clock.edges(iw.t,iw['v(ref)']-.9),clock.edges(iw.t,iw['v(fb0)']-.9),
            start=55e-9,stop=float(iw.t[-1]),period=4e-9,
            window_cycles=cfg['reference_window_cycles'],stride_cycles=cfg['window_stride_cycles'],
            frequency_tolerance=cfg['maximum_relative_frequency_error'],
            phase_span=cfg['maximum_unwrapped_phase_span_s'],hold=cfg['required_hold_time_s'])
    varactor_noise=None
    if a.varactor_noise_summary:
        p=a.varactor_noise_summary.resolve();inputs.append(identity(p));varactor_noise=json.loads(p.read_text())
        vc=ROOT/varactor_noise['campaign'];inputs.extend(identity(vc/'run'/n) for n in ('tb.cir','execution.json','admittance.tsv','var_noise.raw','ref_noise.raw','op.raw'))
    corrected=None;equivalence=None;mismatch=None
    if a.varactor_noise_corrected_summary:
        p=a.varactor_noise_corrected_summary.resolve();inputs.append(identity(p));corrected=json.loads(p.read_text())
        vc=ROOT/corrected['campaign'];inputs.extend(identity(vc/'run'/n) for n in ('tb.cir','execution.json','admittance.tsv','var_noise.raw','ref_noise.raw','op.raw'))
        overlay=Path(corrected['noise_overlay']['generated'])
        if identity(overlay)['sha256']!=corrected['noise_overlay']['generated_sha256']:raise ValueError('Noise overlay changed')
        inputs.append(identity(overlay))
        if varactor_noise:
            orig=np.loadtxt(ROOT/varactor_noise['campaign']/'run/admittance.tsv',skiprows=1)
            fixed=np.loadtxt(vc/'run/admittance.tsv',skiprows=1)
            corrected['original_to_corrected_ac_max_abs']=float(np.max(np.abs(orig-fixed)))
    if a.varactor_equivalence_summary:
        p=a.varactor_equivalence_summary.resolve();inputs.append(identity(p));equivalence=json.loads(p.read_text())
        ec=ROOT/equivalence['campaign'];inputs.extend(identity(ec/'run'/n) for n in ('tb.cir','execution.json','ctrl.raw'))
        inputs.extend(identity(ec/n) for n in ('input.json','models/varactor_noisy.spice'))
        if not equivalence['passed']:raise ValueError('Noise overlay changed noiseless transient')
    if a.mismatch_summary:
        p=a.mismatch_summary.resolve();inputs.append(identity(p));mismatch=json.loads(p.read_text())
        mi=identity(ROOT/mismatch['campaign']/'plan.json')
        if mi['sha256']!=mismatch['plan_sha256']:raise ValueError('Mismatch plan changed')
        inputs.append(mi)
        mp=json.loads((ROOT/mi['path']).read_text());parent=ROOT/mp['parent']
        if identity(parent/'plan.json')['sha256']!=mp['parent_plan_sha256']:raise ValueError('Mismatch parent changed')
        baseline=parent/'f50_a0/ctrl.raw';inputs.append(identity(baseline));w=spice.Waves(baseline)
        edges=clock.edges(w.t,w['v(v0p)']-w['v(v0n)'],start=14e-9,stop=24e-9)
        if len(edges)<12:raise ValueError('Insufficient nominal reference edges')
        reference=10/(edges[11]-edges[1]);nominal=mismatch['other']['nominal'][0]['freq']
        mismatch['nominal_crosscheck']=dict(reference_frequency_hz=float(reference),
            relative_error=float(nominal/reference-1),scope='Same second-to-twelfth rising edge after14ns; nominal TT MC control versus frozen CG baseline')
        if abs(nominal/reference-1)>1e-5:raise ValueError('Mismatch nominal DUT changed')
        mismatch['grade']='ungraded_frequency_scatter_pilot'
        for item in mismatch['inputs']:
            if identity(ROOT/item['path'])['sha256']!=item['sha256']:raise ValueError('Mismatch input changed')
            inputs.append(item)
    out=ROOT/'results/analog/pll/top/lock_confirmation'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    sources=[Path(__file__).resolve(),contract,*[ROOT/'src/serdes_flow'/(n+'.py') for n in ('pll_lock','clock','feedback','pnoise','waves')]]
    archived=[]
    for p in sources:
        dest=out/'source'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
        archived.append(identity(dest))
    result=dict(report='docs/design/r6_lock_confirmation.md',inputs=inputs,rows=rows,admittance=admittance,
                local_nominal_model=local_model,loaded_interface=interface)
    result['analysis_source_archive']=archived
    result['common_prefix_comparison']=prefix
    result['varactor_noise_audit']=varactor_noise
    result['varactor_noise_corrected']=corrected
    result['varactor_noiseless_equivalence']=equivalence
    result['local_mismatch_pilot']=mismatch
    result['admittance_quality']=admittance_quality
    text=json.dumps(result,indent=2,allow_nan=False)+'\n';(out/'summary.json').write_text(text)
    (ROOT/'docs/data/r6_lock_confirmation.json').write_text(text)
    (ROOT/'results/catalog/r6_lock_confirmation.json').write_text(json.dumps(dict(report=result['report'],data='docs/data/r6_lock_confirmation.json',analysis=str((out/'summary.json').relative_to(ROOT)),inputs=inputs),indent=2)+'\n')
    print(json.dumps(dict(analysis=str(out.relative_to(ROOT)),rows=[{k:v for k,v in r.items() if k!='engineering_lock'}|dict(engineering={k:v for k,v in r['engineering_lock'].items() if k!='windows'}) for r in rows]),indent=2))


if __name__=='__main__':main()
