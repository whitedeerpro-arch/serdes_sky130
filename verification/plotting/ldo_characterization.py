"""Publish verified LDO screening summaries and native plots, no simulation."""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import feedback, project, spice

ROOT=project.ROOT


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    data=json.loads(path.read_text())
    if data.get('missing'):raise ValueError(f'Incomplete campaign: {path}')
    camp=ROOT/data['campaign'];plan=json.loads((camp/'plan.json').read_text())
    if sha(camp/'plan.json')!=data['plan_sha256']:raise ValueError('Plan hash mismatch')
    for row in data['rows']:
        for name,h in row.get('evidence',{}).items():
            if sha(ROOT/row['run']/name)!=h:raise ValueError(f'Evidence changed: {name}')
        if 'raw' in row and sha(ROOT/row['raw'])!=row['raw_sha256']:raise ValueError('Mode waveform changed')
    return data,plan


def main(reg_path,dyn_path,stability_path,reference_path,switch_path,modes_path):
    r,rp=load(reg_path);d,dp=load(dyn_path)
    st,sp=load(stability_path);rf,rfp=load(reference_path);sw,swp=load(switch_path)
    modes=load(modes_path)[0] if modes_path else None
    if len(st['rows'])!=135 or any(len(x['crossings'])!=1 or x['crossings'][0]['direction']!='down' for x in st['rows']):raise ValueError('Unexpected dual-injection crossings')
    if sp['parent']!=r['campaign'] or dp['parent']!=r['campaign']:raise ValueError('Different parent circuit boundary')
    core_rel='analog/common/ldo/spice/ldo_hv18_core.spice'
    if rp['sources'][core_rel]!=rfp['sources'][core_rel] or rp['sources'][core_rel]!=sha(ROOT/core_rel):raise ValueError('Current and screened core differ')
    rows=r['rows'];dr=d['rows'];margins=[g['pm_deg'] for x in rows for g in x['return_ratio_crossings']]
    if len(rows)!=135 or any(len(x['return_ratio_crossings'])!=1 for x in rows):raise ValueError('Expected 135 unique DC/AC conditions and one downward crossing each')
    stats={key:dict(min=min(x[key] for x in rows),max=max(x[key] for x in rows)) for key in ('vout_v','psrr_20mhz_db','iq_ua')}
    stats['voltage_only_low_crossing_pm_deg']=dict(min=min(margins),max=max(margins))
    pm=[g['pm_deg'] for x in st['rows'] for g in x['crossings']];stats['middlebrook_pm_deg']=dict(min=min(pm),max=max(pm))
    data=dict(scope='HV18 r3 local screen with ideal passives; real-reference results use fixed host 1.8 V. No full LDO/PLL qualification',
              regulation_summary=str(reg_path.relative_to(ROOT)),regulation_summary_sha256=sha(reg_path),
              dynamic_summary=str(dyn_path.relative_to(ROOT)),dynamic_summary_sha256=sha(dyn_path),
              generator_sha256=sha(Path(__file__)),regulation_options=r['options'],statistics=stats,rows=rows,dynamic_rows=dr,
              supplementary={kind:dict(summary=str(path.relative_to(ROOT)),sha256=sha(path),data=source) for kind,path,source in [('stability',stability_path,st),('reference',reference_path,rf),('switch',switch_path,sw)]+([('modes',modes_path,modes)] if modes_path else [])},
              current_core_sha256=sha(ROOT/core_rel),
              excluded='Real reference and bias noise/MC; voltage trim; PDK passives and ll/hh; reverse isolation and bypass; UVLO/off sequencing; actual PLL load and phase noise.')
    (ROOT/'docs/data/ldo_characterization.json').write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    (ROOT/'results/catalog/ldo_characterization.json').write_text(json.dumps(dict(status='local_screen_only',revision='hv18_r3',data='docs/data/ldo_characterization.json',regulation_campaign=r['campaign'],dynamic_campaign=d['campaign'],reference_campaign=rf['campaign'],stability_campaign=st['campaign'],switch_campaign=sw['campaign'],modes_campaign=modes['campaign'] if modes else None,summary_sha256=sha(ROOT/'docs/data/ldo_characterization.json')),indent=2)+'\n')
    fig,axes=plt.subplots(3,2,figsize=(12,11),layout='constrained');ax,bx,cx,dx,ex,fx=axes.flat
    colors={'tt':'#176c8c','ss':'#7b5595','ff':'#d27732','sf':'#cf4951','fs':'#388c70'}
    curves=[]
    for row in rows:
        stem=f"v{round(row['vin_v']*1000)}_t{row['temp_c']}_i{row['load_ma']}"
        ac=np.loadtxt(ROOT/row['run']/(stem+'_supply.tsv'),skiprows=1);curves.append(-20*np.log10(np.hypot(ac[:,1],ac[:,2])))
        if (row['process'],row['vin_v'],row['temp_c'],row['load_ma'])==('tt',3.3,27,6):
            tt=curves[-1];loop=np.loadtxt(ROOT/row['run']/(stem+'_loop.tsv'),skiprows=1)
        bx.scatter(row['load_ma']+(row['vin_v']-3.3)*.35,(row['vout_v']-1.8)*1000,s=13,alpha=.55,color=colors[row['process']])
    hz=ac[:,0];curves=np.array(curves)
    ax.fill_between(hz,curves.min(axis=0),curves.max(axis=0),alpha=.2,color='#176c8c',label='135-condition range')
    ax.semilogx(hz,tt,color='#176c8c',label='TT / 3.3 V / 6 mA');ax.axvline(20e6,ls=':',color='#777');ax.axhline(34,ls='--',color='#a84c43',label='34 dB provisional target')
    ax.set(xlim=(1e3,1e9),ylim=(-5,110),xlabel='Frequency (Hz)',ylabel='PSRR (dB)',title='Input ripple to local output; ideal reference');ax.legend(fontsize=8)
    bx.set(xlabel='Load current (mA)',ylabel='Output error from 1.8 V (mV)',title='135 DC points; ideal 1.23 V reference',xticks=[2,6,10]);bx.axhline(0,ls=':',color='#777')
    for p,col in colors.items():bx.scatter([],[],s=20,color=col,label=p.upper())
    bx.legend(ncol=5,fontsize=8)
    for mode,col in [('step_100ua','#388c70'),('step_1ma','#176c8c'),('step','#d27732')]:
        row=next(x for x in dr if x['process']=='tt' and x['mode']==mode);w=spice.Waves(ROOT/row['run']/(mode+'.raw'));s=w.t<=400e-9
        cx.plot(w.t[s]*1e9,(w['out_v'][s]-row['baseline_v'])*1000,color=col,label={'step_100ua':'+0.1 mA','step_1ma':'+1 mA','step':'+4 mA stress'}[mode])
    cx.set(xlabel='Time (ns)',ylabel='Output excursion (mV)',title='TT load steps, 1 ns edges, 100 ns pulse');cx.legend(fontsize=8)
    for row in dr:
        if row['mode']=='startup':
            w=spice.Waves(ROOT/row['run']/'startup.raw');dx.plot(w.t*1e6,w['out_v'],label=row['name'].replace('_startup',''),color=colors[row['process']],alpha=.8)
        if row['mode']=='noise':
            w=spice.Waves(ROOT/row['run']/'noise.raw');ex.loglog(w.t,w['onoise_spectrum']*1e9,color=colors[row['process']],alpha=.8,label=f"{row['process'].upper()} {row['temp_c']} C")
    dx.set(xlabel='Time (us)',ylabel='Output (V)',title='HV ramp 20-120 ns; reference/bias ramp 150-250 ns');dx.axhline(1.8,color='#777',ls=':');dx.legend(fontsize=7)
    ex.set(xlabel='Frequency (Hz)',ylabel='Output noise (nV/sqrt(Hz))',title='Internal device + divider noise; reference/bias noiseless');ex.legend(fontsize=7,ncol=2)
    sx=next(x for x in st['rows'] if (x['process'],x['vin_v'],x['temp_c'],x['load_ma'])==('tt',3.3,27,6));stem='v3300_t27_i6'
    va=np.loadtxt(ROOT/sx['run']/(stem+'_voltage.tsv'),skiprows=1);ia=np.loadtxt(ROOT/sx['run']/(stem+'_current.tsv'),skiprows=1)
    tv=va[:,1]+1j*va[:,2];ti=ia[:,1]+1j*ia[:,2];gain=feedback.middlebrook(tv,ti);phase=np.unwrap(np.angle(gain))*180/np.pi
    fx.semilogx(va[:,0],20*np.log10(np.abs(gain)),color='#176c8c',label='Dual injection');fx.semilogx(va[:,0],20*np.log10(abs(tv)),color='#999',ls=':',label='Voltage only')
    fx.axhline(0,ls=':',color='#777');fy=fx.twinx();fy.semilogx(va[:,0],phase,color='#d27732',label='Phase')
    fx.set(xlim=(1e3,1e10),xlabel='Frequency (Hz)',ylabel='Return-ratio magnitude (dB)',title='TT dual injection; voltage-only HF artefact corrected');fy.set_ylabel('Phase (deg)');fx.legend(fontsize=8)
    for a in axes.flat:a.grid(alpha=.18)
    fig.suptitle('HV18 r3: separate cascode-gate filter, Chv 50 pF / Ccas 50 pF / Cout 100 pF',fontsize=13)
    fig.savefig(ROOT/'docs/figures/clocking/pll/core/ldo_characterization.png',dpi=160);plt.close(fig)
    if modes:
        fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
        for row in modes['rows']:
            mode=row['mode'];w=spice.Waves(ROOT/row['raw']);t=w.t*1e6;v=w['out_'+mode]
            axes[0,0].plot(t,v,label=mode);axes[0,1].plot(t,v,label=mode)
            axes[1,0].plot(t,v*1000,label=mode)
            if mode=='change':
                axes[1,1].plot(t,-w['ihv_'+mode]*1e3,label='HV input current');axes[1,1].plot(t,-w['iext_'+mode]*1e3,label='External input current')
        axes[0,0].set(title='TT: actual bandgap, HV enable after 20 us',xlabel='Time (us)',ylabel='Local output (V)')
        axes[0,1].set(title='Mode change under PLL reset',xlabel='Time (us)',ylabel='Local output (V)',xlim=(19.8,23))
        axes[1,0].set(title='Initial power-up feedthrough',xlabel='Time (us)',ylabel='Local output (mV)',xlim=(0,.5),ylim=(-25,75))
        axes[1,1].set(title='HV -> 500 ns gap -> external bypass',xlabel='Time (us)',ylabel='Supply current (mA)',xlim=(21.8,23))
        for a in axes.flat:a.grid(alpha=.2);a.legend(fontsize=8)
        fig.suptitle('Assembled HV18 r3 supply macro: TT functional pilot, 300-ohm load')
        fig.savefig(ROOT/'docs/figures/clocking/pll/core/ldo_modes.png',dpi=170);plt.close(fig)
    print(json.dumps(dict(statistics=stats,dynamic_cases=len(dr),reference_cases=len(rf['rows'])),indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('regulation_summary',type=Path);ap.add_argument('dynamic_summary',type=Path)
    ap.add_argument('--stability',type=Path,required=True);ap.add_argument('--reference',type=Path,required=True);ap.add_argument('--switch',type=Path,required=True);ap.add_argument('--modes',type=Path)
    a=ap.parse_args();main(a.regulation_summary.resolve(),a.dynamic_summary.resolve(),a.stability.resolve(),a.reference.resolve(),a.switch.resolve(),a.modes.resolve() if a.modes else None)
