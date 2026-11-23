"""Publish fixed LDO capacitor-area evidence and a standalone comparison plot.

Only data/figures/catalogs are generated. The design report is hand maintained.
No latest-run lookup and no transfer of first-layer qualification to MIM2.
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow.project import ROOT


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--manifest',type=Path,required=True)
    a=ap.parse_args();manifest=json.loads(a.manifest.read_text())
    paths={k:ROOT/v for k,v in manifest.items()};d={k:json.loads(p.read_text()) for k,p in paths.items()}
    for key in ('screen','noise','noise_rc','pex16','pex12','pex8','pexstack','stack_pvt','stack_dynamic'):
        if d[key].get('missing'):raise ValueError('Incomplete evidence: '+key)
    if d['stack_pvt']['summary'][0]['dc_cases']!=1215 or d['stack_pvt']['summary'][0]['ac_cases']!=255:
        raise ValueError('Incomplete stacked PVT coverage')
    if len(d['stack_dynamic']['rows'])!=15:raise ValueError('Incomplete stacked dynamic set')
    if any(not x['bias_verified'] for x in d['stack_dynamic']['rows'] if x['mode']=='noise'):
        raise ValueError('Unverified noise operating point')
    if any(x['samples']!=8 or not x['seed_replay_pass'] for x in d['stack_mc']['groups'].values()):
        raise ValueError('Incomplete/replay-failed stacked MC pilot')
    # Full-PDK and reduced decks have identical coordinates and four complete
    # AC spectra per case. Compare tables, not just rounded headline metrics.
    full=paths['full_screen'].parents[2];reduced=paths['reduced_screen'].parents[2]
    plan=json.loads((full/'plan.json').read_text());count=0;max_delta=0.
    for e in plan['entries']:
        for f in (full/e['name']).glob('*.tsv'):
            x=np.loadtxt(f,skiprows=1);y=np.loadtxt(reduced/e['name']/f.name,skiprows=1)
            np.testing.assert_allclose(x,y,rtol=1e-12,atol=1e-15)
            max_delta=max(max_delta,float(np.max(np.abs(x-y))));count+=1
    if count!=40:raise ValueError('Missing full/reduced comparison tables')
    order=[('8pF','core8','pex8'),('12pF','core12','pex12'),('16pF','core16','pex16'),('16pF stacked','corestack','pexstack')]
    trials=[dict(label=label,area_um2=d[area]['area_um2'],psrr20_db=d[pex]['summary'][0]['psrr20_min_db'],
                 pm_deg=d[pex]['summary'][0]['pm_min_deg'],point_pass=d[pex]['summary'][0]['passed']) for label,area,pex in order]
    noise=[x for x in d['noise']['rows'] if x['load_ma']==2]
    result=dict(report='docs/design/ldo_cap_area.md',scope='local cap-area iteration; core-only PEX; global r4/PLL adoption unchanged',
                inputs={k:dict(path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for k,p in paths.items()},
                inventory=d['inventory']['rows'],screen=d['screen']['summary'],noise_screen=d['noise']['rows'],
                rc_noise_screen=d['noise_rc']['rows'],physical_trials=trials,
                area_reduction_vs_compact70=1-d['corestack']['area_um2']/d['core16']['area_um2'],
                full_reduced_comparison=dict(tables=count,max_abs_delta=max_delta),
                stacked_pvt=d['stack_pvt']['summary'],stacked_dynamic=d['stack_dynamic']['rows'],
                stacked_mc=d['stack_mc']['groups'],stacked_pex_screen=d['stack_pex_screen']['summary'],
                peripheral_layout=d['filter16'],peripheral_card=d['filter_card'])
    dest=ROOT/'docs/data/ldo_cap_area.json';dest.write_text(json.dumps(result,indent=2)+'\n')
    catalog=dict(report=result['report'],data=str(dest.relative_to(ROOT)),inputs=result['inputs'],scope=result['scope'])
    (ROOT/'results/catalog/ldo_cap_area.json').write_text(json.dumps(catalog,indent=2)+'\n')
    fig,axs=plt.subplots(1,3,figsize=(13,4.1),layout='constrained')
    labels=[x['label'] for x in trials];colors=['#c75a5a','#daa64d','#6d8baa','#4b9d81']
    for ax,field,title in zip(axs[:2],('area_um2','psrr20_db'),('Core area (1,000 um²)','PEX PSRR at 20MHz (dB)')):
        values=[x[field]/(1000 if field=='area_um2' else 1) for x in trials]
        bars=ax.bar(labels,values,color=colors);ax.bar_label(bars,fmt='%.2f',padding=3,fontsize=8)
        ax.set_title(title);ax.tick_params(axis='x',rotation=25,labelsize=8);ax.set_ylim(0,max(values)*1.17)
    axs[1].axhline(34,color='black',ls='--',lw=1,label='34dB gate');axs[1].legend(fontsize=8)
    values=[x['noise_uv'] for x in noise]
    bars=axs[2].bar(['16pF','8pF','4pF','2pF'],values,color=['#6d8baa','#d5ac55','#ca825b','#c75a5a'])
    axs[2].bar_label(bars,fmt='%.1f',padding=3,fontsize=8);axs[2].set_ylim(0,max(values)*1.17)
    axs[2].set_title('Reference cap: TT noise (uVrms)');axs[2].set_xlabel('1Mohm unchanged; 1kHz-199.5MHz')
    fig.suptitle('LDO capacitor-area study | left/middle: same worst FS/ll point | right: TT/2mA',fontsize=11)
    folder=ROOT/'docs/figures/layout/ldo/cap_area';folder.mkdir(parents=True,exist_ok=True)
    fig.savefig(folder/'comparison.png',dpi=170);plt.close(fig)
    print(json.dumps(dict(data=str(dest.relative_to(ROOT)),area_reduction=result['area_reduction_vs_compact70'],tables=count),indent=2))


if __name__=='__main__':main()
