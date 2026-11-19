"""Publish bandgap capacitor review from an explicit immutable evidence list."""
import argparse
import hashlib
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow.project import ROOT


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--manifest',required=True);a=ap.parse_args()
    manifest=json.loads((ROOT/a.manifest).read_text());paths={k:ROOT/v for k,v in manifest.items()}
    d={k:json.loads(p.read_text()) for k,p in paths.items()}
    for key in ('pilot','full_pilot','screen','physical_rz','dynamic'):
        if d[key]['missing']:raise ValueError('Incomplete evidence: '+key)
    if len(d['screen']['rows'])!=100 or len(d['physical_rz']['rows'])!=20 or len(d['dynamic']['rows'])!=24:
        raise ValueError('Unexpected campaign coverage')
    startup=[r for r in d['dynamic']['rows'] if r['mode']=='startup'];noise=[r for r in d['dynamic']['rows'] if r['mode']=='noise']
    if len(startup)!=12 or len(noise)!=12 or not all(r['bias_verified'] for r in noise):raise ValueError('Incomplete startup/noise')
    tables=0;delta=0.;full=paths['full_pilot'].parents[2];reduced=paths['pilot'].parents[2]
    for load in ('light','dist'):
        for f in (full/('phys6_tt_'+load)).glob('*.tsv'):
            x=np.loadtxt(f,skiprows=1);y=np.loadtxt(reduced/('phys6_tt_'+load)/f.name,skiprows=1)
            np.testing.assert_allclose(x,y,rtol=1e-12,atol=1e-15);tables+=1;delta=max(delta,float(np.max(np.abs(x-y))))
    if tables!=10:raise ValueError('Missing full/reduced comparison')
    metrics=[]
    for group in ('screen','physical_rz'):
        for v in d[group]['summary']:
            rows=[r for r in d[group]['rows'] if r['variant']==v['name']]
            vi={load:min(c['pm_deg'] for r in rows if r['load']==load for c in r['loops']['vi']['crossings']) for load in ('light','dist')}
            metrics.append(dict(v,vi_min_by_load=vi,group=group))
    result=dict(report='docs/design/bias_cap_review.md',
        inputs={k:dict(path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for k,p in paths.items()},
        scope='Local shared-reference cap review;60deg planning guard, not a retroactive functional gate; no new adoption/full PVT/MC/PEX qualification',
        metrics=metrics,startup=startup,noise=noise,rz_card=d['rz_card'],
        layout_snapshot=[dict(cell=r['cell'],area_um2=r['area_um2']) for r in d['layout_snapshot']],
        full_reduced=dict(tables=tables,max_abs_delta=delta))
    (ROOT/'docs/data/bias_cap_review.json').write_text(json.dumps(result,indent=2)+'\n')
    (ROOT/'results/catalog/bias_cap_review.json').write_text(json.dumps(dict(report=result['report'],data='docs/data/bias_cap_review.json',inputs=result['inputs'],scope=result['scope']),indent=2)+'\n')
    fig,axs=plt.subplots(1,3,figsize=(13,4),layout='constrained')
    pick=['phys6','cc4','cc3','cc2','cc4_r30'];ms={r['name']:r for r in metrics}
    vals=[ms[n]['core_min_pm'] for n in pick]
    bars=axs[0].bar(['6p/20k','4p/20k','3p/20k','2p/20k','4p/30k'],vals,color=['#6d8baa','#daa64d','#ca825b','#c75a5a','#4b9d81'])
    axs[0].bar_label(bars,fmt='%.1f',padding=3,fontsize=8);axs[0].axhline(60,c='black',ls='--',lw=1)
    axs[0].set_title('Core loop: minimum PM (deg)');axs[0].set_ylim(0,100);axs[0].tick_params(axis='x',rotation=25,labelsize=8)
    pick=['phys6','gi1','gi0'];x=np.arange(3);width=.35
    for offset,load,color in [(-width/2,'light','#daa64d'),(width/2,'dist','#6d8baa')]:
        vals=[ms[n]['vi_min_by_load'][load] for n in pick]
        bars=axs[1].bar(x+offset,vals,width,label=load,color=color);axs[1].bar_label(bars,fmt='%.1f',padding=3,fontsize=8)
    axs[1].set_xticks(x,['2pF','1pF','0pF']);axs[1].set_ylim(0,80);axs[1].set_title('V-to-I: minimum PM vs added Cgi');axs[1].legend(fontsize=8)
    variants=['phys6_rp','cc4_r30p'];labels=['6p/20k physical','4p/30k physical']
    nv=[next(r['noise_uv']['vbg'] for r in noise if r['variant']==v and r['section']=='tt' and r['load']=='dist') for v in variants]
    bars=axs[2].bar(labels,nv,color=['#6d8baa','#4b9d81']);axs[2].bar_label(bars,fmt='%.1f',padding=3,fontsize=8)
    axs[2].set_ylim(0,max(nv)*1.2);axs[2].set_title('TT/dist Vbg noise (uVrms)');axs[2].set_xlabel('1kHz-199.5MHz; Rz has4 real segments')
    folder=ROOT/'docs/figures/common/bias_cap_review';folder.mkdir(parents=True,exist_ok=True)
    fig.savefig(folder/'comparison.png',dpi=160);plt.close(fig)
    print(json.dumps(dict(tables=tables,max_delta=delta,startup_reach=sum(r['reach_op'] for r in startup),startup_count=len(startup),noise_spectra=sum(len(r['noise_uv']) for r in noise)),indent=2))


if __name__=='__main__':main()
