"""Read-only remeasurement and publication of the historical four-bit VCO ISF pilot."""
import argparse
import importlib.util
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import project

ROOT=project.ROOT
RUNNER=ROOT/'analog/pll/vco/tb/phase_noise/isf_4b_pilot.py'
GUARD=ROOT/'verification/analysis/vco_boundary_readonly.py'
FROZEN_SPICE=ROOT/'results/analog/pll/vco/window_boundary_anchor/20261109T135254.636837Z_803e72d4/sources/src/serdes_flow/spice.py'


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path); obj=importlib.util.module_from_spec(spec); spec.loader.exec_module(obj); return obj


def same(a,b):
    if isinstance(a,dict): return isinstance(b,dict) and a.keys()==b.keys() and all(same(a[k],b[k]) for k in a)
    if isinstance(a,list): return isinstance(b,list) and len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
    if isinstance(a,(float,int)) and not isinstance(a,bool): return isinstance(b,(float,int)) and not isinstance(b,bool) and math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-18)
    return a==b


def verify(camp,summary):
    pilot=load('historical_isf_pilot',RUNNER); guardmod=load('vco_readonly',GUARD)
    with guardmod.ReadOnlyVerification(camp,pilot) as guard:
        if summary.parent.parent.parent!=camp: raise ValueError('summary from another campaign')
        plan=json.loads((camp/'plan.json').read_text()); output=json.loads(summary.read_text())
        if plan['pdk_installation_id']!=pilot.project.pdk_installation_id() or plan['pdk_sha256']!=pilot.pdk_manifest(): raise ValueError('PDK changed')
        spice_path=ROOT/'src/serdes_flow/spice.py'
        if plan['sources'].get(str(spice_path))!=guardmod.OLD or pilot.sha(FROZEN_SPICE)!=guardmod.OLD or pilot.sha(spice_path)!=guardmod.CURRENT: raise ValueError('unrecognized spice migration')
        if guardmod._module_nodes(FROZEN_SPICE)!=guardmod._module_nodes(spice_path): raise ValueError('SPICE module AST differs beyond run/log_failures')
        for name,expected in plan['sources'].items():
            if Path(name)!=spice_path and pilot.sha(name)!=expected: raise ValueError(f'source changed {name}')
        for name,expected in plan['snapshots'].items():
            if pilot.sha(camp/name)!=expected: raise ValueError(f'snapshot changed {name}')
        for smoke in (False,True):
            deck,_=pilot.make_deck(camp,smoke)
            if deck!=(camp/'prepared'/('smoke.cir' if smoke else 'frequency.cir')).read_text(): raise ValueError('prepared deck mismatch')
        base=(camp/'prepared/frequency.cir').read_text()
        smoke=pilot.completed(camp,'smoke_rp',(camp/'prepared/smoke.cir').read_text(),'smoke.raw',1e-9,['v(v0p)','v(v0n)','v(xvco.x0.tail)'])
        if not smoke: raise ValueError('incomplete smoke')
        siteplan=(ROOT/output['site_plan']).resolve()
        if not siteplan.is_relative_to(camp/'site_plans') or pilot.sha(siteplan/'summary.json')!=output['site_plan_sha256']: raise ValueError('site plan changed')
        siteinfo=json.loads((siteplan/'summary.json').read_text()); cal=(ROOT/siteinfo['calibration']).resolve()
        if not cal.is_relative_to(camp/'calibration') or pilot.sha(cal/'summary.json')!=siteinfo['calibration_sha256']: raise ValueError('calibration changed')
        calibration=json.loads((cal/'summary.json').read_text())
        if calibration['status']!='measured' or len(calibration['points'])!=1: raise ValueError('unexpected calibration')
        item=calibration['points'][0]; voltage=item['vctrl_v']; deck=pilot.voltage_deck(base,voltage)
        name=f'freq_{round(voltage*1e9):010d}'
        freq=pilot.completed(camp,name,deck,'frequency.raw',24e-9,['v(v0p)','v(v0n)'])
        if not freq or str(freq[0].relative_to(ROOT))!=item['run'] or pilot.sha(freq[0]/'frequency.raw')!=item['raw_sha256'] or pilot.sha(freq[0]/'execution.json')!=item['execution_sha256']: raise ValueError('frequency evidence mismatch')
        f=pilot.frequency(freq[1]); period=1/f
        if not same(f,item['frequency_hz']) or not same(f,calibration['frequency_hz']) or not same(period,calibration['period_s']) or not same(f,siteinfo['frequency_hz']) or not same(period,siteinfo['period_s']) or abs(f/pilot.TARGET-1)>.01: raise ValueError('frequency mismatch')
        if output['status']!='complete' or output['spec_status']!='ungraded' or set(output['sites'])!=set(pilot.SITES): raise ValueError('ISF summary incomplete')
        evidence={}
        for site in pilot.SITES:
            deck,centres,stop=pilot.site_deck(base,site,voltage,period); entry=siteinfo['sites'][site]
            if pilot.sha(siteplan/f'{site}.cir')!=entry['deck_sha256'] or deck!=(siteplan/f'{site}.cir').read_text() or not same(stop,entry['t_end_s']) or not same(centres.tolist(),entry['centres_s']): raise ValueError('site deck/phase plan differs')
            done=pilot.completed(camp,site,deck,site+'.raw',stop,['v(v0p)','v(v0n)','v(xvco.x0.tail)',*pilot.PROBES[site]])
            row=output['sites'][site]
            if not done: raise ValueError(f'incomplete site {site}')
            run,w=done
            if str(run.relative_to(ROOT))!=row['run'] or pilot.sha(run/(site+'.raw'))!=row['raw_sha256'] or pilot.sha(run/'execution.json')!=row['execution_sha256']: raise ValueError('site evidence mismatch')
            imp=pilot.pnoise.impulse_response(w.t,w['v(v0p)']-w['v(v0n)'],centres,.5e-15)
            gap=pilot.phase_gap(imp.x); good=len(imp.x)==32 and gap is not None and gap<=.08 and np.all(np.isfinite(imp.h))
            calculated={'period_s':imp.period,'phase':[float(x) if np.isfinite(x) else None for x in imp.x],
                        'response':[float(x) if np.isfinite(x) else None for x in imp.h],'gap':gap,
                        'status':'observed' if good else 'incomplete','h_rms':float(np.sqrt(pilot.pnoise.white_coefficient(imp))) if good else None,
                        'h_mean':float(pilot.pnoise.slow_coefficient(imp)) if good else None,'actual_t_end_s':float(w.t[-1])}
            if any(not same(row[k],v) for k,v in calculated.items()) or row['spec_status']!='ungraded': raise ValueError(f'site result differs {site}')
            evidence[site]={'deck_sha256':pilot.sha(run/'tb.cir'),'raw_sha256':row['raw_sha256'],'execution_sha256':row['execution_sha256'],'t_end_s':float(w.t[-1])}
        guard.report['ast_verified']=True
        verified={'scope':'Historical TT 1.8 V single-rail r5 four-bit VCO, K6, Vctrl 1.195 V, four buffers and 30 fF per node; rp/mp/mt 32-phase ISF pilot. Not current quiet domain or a complete noise budget.',
            'campaign':str(camp.relative_to(ROOT)),'summary':str(summary.relative_to(ROOT)),'summary_sha256':pilot.sha(summary),
            'plan_sha256':pilot.sha(camp/'plan.json'),'site_plan_sha256':pilot.sha(siteplan/'summary.json'),
            'calibration_sha256':pilot.sha(cal/'summary.json'),'frequency_hz':f,'vctrl_v':voltage,'evidence':evidence,
            'sites':output['sites'],'runner_sha256':pilot.sha(RUNNER),'guard_sha256':pilot.sha(GUARD),
            'publisher_sha256':pilot.sha(Path(__file__)),'publisher_source':Path(__file__).read_text()}
    verified['readonly_migration']=guard.report
    return verified


def main(camp,summary,check_only):
    data=verify(camp,summary)
    if check_only:
        print(json.dumps({'verified':True,'frequency_hz':data['frequency_hz'],'migration':data['readonly_migration']},indent=2));return
    fig,ax=plt.subplots(figsize=(9,4.8),layout='constrained')
    for site,row in data['sites'].items(): ax.plot(row['phase'],row['response'],'o-',markersize=3,label=site)
    ax.set(xlabel='Oscillation phase (cycles)',ylabel='Phase impulse response (rad/C)',title='Historical 4-bit VCO ISF pilot · TT · single rail');ax.grid(alpha=.2);ax.legend()
    figure=ROOT/'docs/figures/clocking/vco/vco_isf_4b_pilot.png';fig.savefig(figure,dpi=160);plt.close(fig)
    output=ROOT/'docs/data/vco_isf_4b.json';output.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    digest=load('isf_digest',RUNNER).sha
    catalog={'scope':data['scope'],'data':str(output.relative_to(ROOT)),'data_sha256':digest(output),
             'figure':str(figure.relative_to(ROOT)),'figure_sha256':digest(figure),'campaign':data['campaign'],
             'summary':data['summary'],'summary_sha256':data['summary_sha256'],'evidence':data['evidence']}
    (ROOT/'results/catalog/vco_isf_4b.json').write_text(json.dumps(catalog,indent=2)+'\n')
    print('verified and published',output)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--campaign',type=Path,required=True);p.add_argument('--summary',type=Path,required=True);p.add_argument('--check-only',action='store_true');a=p.parse_args();main(a.campaign.resolve(),a.summary.resolve(),a.check_only)
