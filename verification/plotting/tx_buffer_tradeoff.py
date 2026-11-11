"""Compare the explicit, independently published TT/FS extra-buffer experiments."""
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from serdes_flow.project import ROOT

SOURCES=('tx_buffer_cascade','tx_buffer_sizing','tx_buffer_gain_search','tx_buffer_taper')
CASES=[('baseline','tx_buffer_cascade','baseline'),('12.8 / 320','tx_buffer_cascade','extra5'),
       ('14 / 320','tx_buffer_sizing','tail14'),('14.4 / 320','tx_buffer_sizing','tail14p4'),
       ('15 / 320','tx_buffer_gain_search','tail15'),('15.6 / 300','tx_buffer_gain_search','tail15p6_r300'),
       ('14 → 15.6','tx_buffer_taper','first14'),('14.4 → 15.6','tx_buffer_taper','first14p4')]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def collect():
    sources={}; data={}
    for name in SOURCES:
        path=ROOT/'docs/data'/f'{name}.json';catalog=ROOT/'results/catalog'/f'{name}.json'
        index=json.loads(catalog.read_text());value=json.loads(path.read_text())
        if index['data_sha256']!=sha(path) or index['summary_sha256']!=value['summary_sha256']:
            raise ValueError(f'published data identity differs: {name}')
        if sha(ROOT/value['summary'])!=value['summary_sha256']:
            raise ValueError(f'summary changed: {name}')
        data[name]={r['condition']:r['result'] for r in value['results']}
        if set(data[name])!={'tt_v1800_t27','fs_v1650_t85'} or not all(r['baseline_matches'] for r in data[name].values()):
            raise ValueError('expected two calibrated local conditions')
        sources[name]={'data':str(path.relative_to(ROOT)),'sha256':sha(path),
                       'catalog_sha256':sha(catalog),'campaign':value['campaign']}
    # The experiment changes sizing, not the data or reference phase. Baseline
    # interpolation differences are much smaller than these comparison gates.
    for name in SOURCES[1:]:
        for tag in data[name]:
            ref=data[SOURCES[0]][tag]['branches'][0];actual=data[name][tag]['branches'][0]
            if (abs(ref['nodes']['c2g']['differential_pp_v']-actual['nodes']['c2g']['differential_pp_v'])>1e-6
                    or abs(ref['metrics']['transition_spread_ui']-actual['metrics']['transition_spread_ui'])>1e-5):
                raise ValueError('baseline changed between cards')
    rows=[]
    for label,name,branch in CASES:
        tt=next(b for b in data[name]['tt_v1800_t27']['branches'] if b['branch']==branch)
        fs=next(b for b in data[name]['fs_v1650_t85']['branches'] if b['branch']==branch)
        m=fs['metrics'];upper=max(tt['nodes'][f'e{i}']['differential_pp_v'] for i in range(5))
        rows.append(dict(label=label,source=name,branch=branch,tt_max_extra_pp_v=upper,
            fs_c2g_pp_v=fs['nodes']['c2g']['differential_pp_v'],fs_margin_v=m['minimum_signed_margin_v'],
            fs_spread_ui=m['transition_spread_ui'],functional=m['functional'],
            local_combined_observation=bool(m['functional'] and upper<=.4 and m['minimum_signed_margin_v']>=.075 and m['transition_spread_ui']<=.15)))
    return dict(scope='Two calibrated ideal-PWL loaded TT/FS cuts, eight-bit contract. TT amplitude of five extra stages and FS serial gates only; iso/I-17, full TX/PVT, noise and mismatch remain open.',
                generator_sha256=sha(Path(__file__)),sources=sources,rows=rows)


def main():
    result=collect();rows=result['rows']
    fig,axes=plt.subplots(1,2,figsize=(12,5.3),layout='constrained')
    for row in rows:
        good=row['local_combined_observation'];color='#207d63' if good else '#ba563d'
        marker='D' if '→' in row['label'] else 'o'
        axes[0].scatter(row['tt_max_extra_pp_v']*1e3,row['fs_spread_ui'],color=color,marker=marker,s=55,zorder=3)
        axes[1].scatter(row['fs_c2g_pp_v']*1e3,row['fs_margin_v']*1e3,color=color,marker=marker,s=55,zorder=3)
        # The two taper points nearly coincide; keep their shared region legible.
        if row['branch']=='first14':continue
        text='taper 14 / 14.4 → 15.6' if row['branch']=='first14p4' else row['label']
        offsets=[{'tail14p4':(-58,-14),'tail15p6_r300':(14,14),'first14p4':(14,-19)},
                 {'tail14':(-30,-14),'tail14p4':(-48,-20),'tail15p6_r300':(-74,8),'tail15':(12,-13)}]
        for index,(ax,xy) in enumerate([(axes[0],(row['tt_max_extra_pp_v']*1e3,row['fs_spread_ui'])),
                                        (axes[1],(row['fs_c2g_pp_v']*1e3,row['fs_margin_v']*1e3))]):
            offset=offsets[index].get(row['branch'],(5,7))
            ax.annotate(text,xy,xytext=offset,textcoords='offset points',fontsize=8,
                        arrowprops={'arrowstyle':'-','color':'#aaa','lw':.5} if offset!=(5,7) else None)
    axes[0].axvline(400,color='#666',ls='--');axes[0].axhline(.15,color='#666',ls='--')
    axes[0].fill_between([320,400],.095,.15,color='#207d63',alpha=.07)
    axes[0].set(xlabel='TT maximum extra-stage pp (mV)',ylabel='FS eight-bit transition spread (UI)',
                title='Amplitude and timing must overlap',xlim=(320,570),ylim=(.095,.225))
    axes[1].axhline(75,color='#666',ls='--');axes[1].axvline(200,color='#999',ls=':')
    axes[1].set(xlabel='FS loaded c2g pp (mV)',ylabel='FS minimum signed margin (mV)',
                title='More retained gain restores the loaded clock',xlim=(195,390),ylim=(60,113))
    for ax in axes:ax.grid(alpha=.2)
    fig.suptitle('TX extra-buffer sizing: uniform reduction versus graded tail widths',fontsize=13)
    fig.supxlabel('Local observations only. All points retain the over-amplitude iso stage; full-TX validation is separate.',fontsize=9)
    out=ROOT/'docs/data/tx_buffer_tradeoff.json';figure=ROOT/'docs/figures/tx/ingress/tx_buffer_tradeoff.png'
    fig.savefig(figure,dpi=170);plt.close(fig)
    out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    index=ROOT/'results/catalog/tx_buffer_tradeoff.json'
    index.write_text(json.dumps(dict(data=str(out.relative_to(ROOT)),data_sha256=sha(out),figure=str(figure.relative_to(ROOT)),
                                    figure_sha256=sha(figure),scope=result['scope'],sources=result['sources']),indent=2)+'\n')
    print(json.dumps(result['rows'],indent=2))


if __name__=='__main__':main()
