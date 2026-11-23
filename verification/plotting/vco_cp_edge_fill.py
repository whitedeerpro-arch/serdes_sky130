"""Collect a completed CP-edge fill and render fixed-code VCO curves; no ngspice."""
import argparse
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT, pdk_installation_id

TUNING=ROOT/'analog/pll/vco/tb/tuning'
sys.path.insert(0,str(TUNING))
import workmap

OLD=ROOT/'results/analog/pll/vco/workmap/20261106T035710Z'
CP=ROOT/'results/analog/pll/cp/window/20261106T021356Z/summary.json'
DATA=ROOT/'docs/data/vco_cp_edge_fill.json'
CATALOG=ROOT/'results/catalog/vco_cp_edge_fill.json'
FIG=ROOT/'docs/figures/clocking/vco/vco_fixed_code_temperature'
GROUPS=(('ff','tt',7),('ff','ll',12),('fs','ll',7))
TARGET=2e9


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def physical_identity(deck):
    """Compare real loads/cells while ignoring swept DC defaults and temperature."""
    prefix=Path(deck).read_text().split('.control',1)[0]
    included={}
    def replace(match):
        path=Path(match.group(1));digest=sha(path)
        included[str(path)]=digest
        return '.include sha256:'+digest
    prefix=re.sub(r'^\.include\s+"([^"]+)"',replace,prefix,flags=re.M|re.I)
    prefix=re.sub(r'^(Vdd|Vref)\s+.*$',r'\1 SWEPT',prefix,flags=re.M)
    prefix=re.sub(r'^\.temp\s+.*$','.temp SWEPT',prefix,flags=re.M)
    return dict(core_sha256=hashlib.sha256(prefix.encode()).hexdigest(),include_sha256=included)


def verify_controls(raw, condition, code, voltage):
    text=Path(raw).parent.joinpath('tb.cir').read_text()
    stem=Path(raw).name.removesuffix('.gz')
    blocks=[b for b in text.split('destroy all') if re.search(r'^write\s+'+re.escape(stem)+r'\s',b,re.M)]
    if len(blocks)!=1:raise ValueError('case write missing/non-unique in executed deck')
    block=blocks[0]
    expected={'Vdd':condition.supply,'Vref':condition.supply,'Vctrl':voltage,
              **{f'Vb{k}':condition.supply if (code>>k)&1 else 0 for k in range(4)}}
    for node,value in expected.items():
        values=re.findall(r'^alter\s+'+node+r'\s+dc=([^\s]+)',block,re.M|re.I)
        if len(values)!=1 or not np.isclose(float(values[0]),value,rtol=0,atol=1e-12):
            raise ValueError(f'case control mismatch: {node}, {raw}')
    temps=re.findall(r'^option temp=([^\s]+)',block,re.M)
    if len(temps)!=1 or float(temps[0])!=condition.temp:raise ValueError('temperature control mismatch')


def verify_raw(path, stop=24e-9):
    path=Path(path);w=spice.Waves(path)
    if not len(w.t) or w.t[-1]<stop*(1-1e-6) or w.t[0]>19e-9+2e-12*(1+1e-6):
        raise ValueError(f'truncated or missing measurement window: {path}')
    ex_path=path.parent/'execution.json';deck=path.parent/'tb.cir';ex=json.loads(ex_path.read_text())
    if ex['exit_code']!=0 or ex.get('timed_out') or sha(deck)!=ex['deck_sha256']:
        raise ValueError(f'execution or deck identity failure: {path}')
    value=workmap.measure(path)
    if value is None or not all(math.isfinite(float(x)) for x in value) or value[0]<=0:
        raise ValueError(f'unmeasurable waveform: {path}')
    return dict(frequency_hz=float(value[0]),swing_vpp=float(value[1]),raw=str(path.relative_to(ROOT)),raw_sha256=sha(path),
                execution_sha256=sha(ex_path),deck_sha256=sha(deck),t_start_s=float(w.t[0]),t_end_s=float(w.t[-1]),
                group_log_failures=ex.get('log_failures',[]))


def brackets(points,cp_hi):
    found=[]
    for a,b in zip(points,points[1:]):
        if a['status']!='measured' or b['status']!='measured':continue
        fa,fb=a['frequency_hz'],b['frequency_hz']
        if min(fa,fb)<=TARGET<=max(fa,fb):
            if fa==fb:
                if fa==TARGET: found.append(dict(vctrl_v=None,cp_headroom_v=None,reason='flat interval at target'))
                continue
            v=a['vctrl_v']+(TARGET-fa)*(b['vctrl_v']-a['vctrl_v'])/(fb-fa)
            found.append(dict(vctrl_v=v,cp_headroom_v=cp_hi-v,between_v=[a['vctrl_v'],b['vctrl_v']]))
    return found


def collect(camp,report_path=None):
    camp=camp.resolve();reports=sorted(camp.glob('report_*.json'))
    if report_path is None:
        if not reports:raise ValueError('campaign has no report; no output written')
        report_path=reports[-1]
    report_path=report_path.resolve()
    if report_path.parent!=camp or not report_path.name.startswith('report_'):raise ValueError('report must belong to campaign')
    report=json.loads(report_path.read_text());manifest=json.loads((camp/'manifest.json').read_text())
    if manifest['pdk_installation_id']!=pdk_installation_id():raise ValueError('PDK identity changed')
    if manifest['stop_s']!=24e-9:raise ValueError('unexpected transient stop')
    for path,digest in manifest['input_sha256'].items():
        if sha(path)!=digest:raise ValueError(f'input changed: {path}')
    for rel,digest in manifest['archived_source_sha256'].items():
        if sha(camp/rel)!=digest:raise ValueError(f'archive changed: {rel}')
    for info in manifest['prepared_decks'].values():
        if sha(camp/info['path'])!=info['sha256']:raise ValueError('prepared deck changed')
    for path,digest in report['analysis_source_sha256'].items():
        if sha(path)!=digest:raise ValueError(f'report analysis source changed: {path}')
    expected={f'{p}_{rc}' for p,rc,_ in GROUPS}
    if set(manifest['cases'])!=expected or set(report['rows'])!=expected:raise ValueError('unexpected group set')
    hot={}
    for group,cases in manifest['cases'].items():
        reported=report['rows'][group]
        if not reported['complete'] or len(reported['samples'])!=len(cases):raise ValueError(f'incomplete report: {group}')
        samples=[]
        for case,row in zip(cases,reported['samples']):
            if any(row[k]!=case[k] for k in ('condition','passive','code','vctrl_v','raw')):
                raise ValueError('report case identity mismatch')
            raw=spice.case_output(camp,group,case['raw'],manifest['stop_s'])
            if raw is None or str(raw)!=row['raw_path'] or sha(raw)!=row['raw_sha256']:
                raise ValueError(f'raw missing or changed: {case}')
            verify_controls(raw,Condition.parse(case['condition']),case['code'],case['vctrl_v'])
            value=verify_raw(raw)
            if value['execution_sha256']!=row['execution_sha256'] or value['deck_sha256']!=row['deck_sha256']:
                raise ValueError('reported execution/deck hash mismatch')
            if value['group_log_failures']:
                raise ValueError(f'new campaign group contains solver/log failures: {raw.parent}')
            if row['measurement_error'] or row['frequency_hz'] is None or not np.isclose(value['frequency_hz'],row['frequency_hz'],rtol=1e-12,atol=1e-3) or not np.isclose(value['swing_vpp'],row['swing_vpp'],rtol=1e-12,atol=1e-12):
                raise ValueError('report measurement differs from independent workmap measurement')
            samples.append(dict(vctrl_v=case['vctrl_v'],status='measured',**value))
        hot[group]=sorted(samples,key=lambda x:x['vctrl_v'])
    cp=json.loads(CP.read_text())['rows'];oldsummary=json.loads((OLD/'summary.json').read_text())
    output=[]
    for process,rc,code in GROUPS:
        group=f'{process}_{rc}';series=[]
        reference_core=physical_identity(camp/manifest['prepared_decks'][group]['path'])
        old_cores={}
        for temp in (-40,27,85):
            cond=Condition.parse(f'{process}_v1950_t{temp}');hi=float(cp[f'{cond.tag}:{rc}']['hi'])
            if temp==85:
                points=hot[group]
                if any(c['condition']!=cond.tag or c['passive']!=rc or c['code']!=code for c in manifest['cases'][group]):
                    raise ValueError('hot condition or code mismatch')
            else:
                points=[]
                for v in (0.85,1.1,1.35,1.5):
                    raw=spice.case_output(OLD,group,workmap.name(cond,code,v),24e-9)
                    if raw is None:points.append(dict(vctrl_v=v,status='missing'));continue
                    verify_controls(raw,cond,code,v)
                    core=physical_identity(raw.parent/'tb.cir')
                    if core['core_sha256']!=reference_core['core_sha256']:raise ValueError(f'old/new physical boundary mismatch: {raw}')
                    old_cores[str((raw.parent/'tb.cir').relative_to(ROOT))]=core
                    measured=verify_raw(raw)
                    if v in oldsummary['vs']:
                        source_row=oldsummary['rows'][f'{cond.tag}:{rc}']; values=source_row['f'].get(str(code))
                        if values is not None and not np.isclose(measured['frequency_hz'],values[oldsummary['vs'].index(v)],rtol=1e-9,atol=1e-3):
                            raise ValueError(f'old summary disagrees with raw: {raw}')
                    points.append(dict(vctrl_v=v,status='measured',**measured))
            series.append(dict(temp_c=temp,condition=cond.tag,cp_hi_v=hi,points=points,brackets=brackets(points,hi)))
        output.append(dict(process=process,passive=rc,supply_v=1.95,code=code,series=series,physical_identity=reference_core,old_physical_identities=old_cores))
    return dict(campaign=str(camp.relative_to(ROOT)),manifest_sha256=sha(camp/'manifest.json'),report=str(report_path.relative_to(ROOT)),
        report_sha256=sha(report_path),old_workmap_summary_sha256=sha(OLD/'summary.json'),cp_summary_sha256=sha(CP),
        collector_sha256=sha(Path(__file__)),scope='Fixed code, 1.95 V, measured static VCO frequencies and CP upper edges; not startup, lock or full PVT.',
        method='2 GHz crossing only between adjacent measured Vctrl points; missing points are retained and no extrapolation is used. Old per-deck log failures are reported with each affected point.',groups=output)


def draw(data):
    fig,axes=plt.subplots(1,3,figsize=(14,4.6),layout='constrained',sharey=True)
    colors={-40:'#3176a8',27:'#25936c',85:'#bf5035'}
    for ax,group in zip(axes,data['groups']):
        for s in group['series']:
            pts=s['points'];color=colors[s['temp_c']]
            # Missing measurements break the curve; never connect through them.
            y=[p['frequency_hz']/1e9 if p['status']=='measured' else np.nan for p in pts]
            ax.plot([p['vctrl_v'] for p in pts],y,'o-',color=color,label=f"{s['temp_c']} °C")
            ax.axvline(s['cp_hi_v'],color=color,ls=':',lw=1)
            for b in s['brackets']:
                if b['vctrl_v'] is not None:ax.plot(b['vctrl_v'],2,'x',color=color,ms=8)
        ax.axhline(2,color='black',lw=.9,ls='--');ax.grid(alpha=.2)
        ax.set_title(f"{group['process'].upper()} / {group['passive'].upper()} / code {group['code']}")
        ax.set_xlabel('Vctrl (V)')
    axes[0].set_ylabel('Frequency (GHz)');axes[0].legend(title='Temperature',fontsize=8)
    fig.suptitle('Fixed-code VCO measurements: dotted lines are measured CP upper edges',fontsize=11)
    FIG.parent.mkdir(parents=True,exist_ok=True)
    for ext in ('png','svg'):fig.savefig(FIG.with_suffix('.'+ext),dpi=160)
    plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--campaign',type=Path,required=True);p.add_argument('--report',type=Path);a=p.parse_args()
    result=collect(a.campaign,a.report)
    DATA.parent.mkdir(parents=True,exist_ok=True);DATA.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    draw(result);CATALOG.parent.mkdir(parents=True,exist_ok=True)
    CATALOG.write_text(json.dumps(dict(campaign=result['campaign'],report=result['report'],data=str(DATA.relative_to(ROOT)),data_sha256=sha(DATA),
        figures=[str(FIG.relative_to(ROOT))+'.'+x for x in ('png','svg')],scope=result['scope']),indent=2)+'\n')
    print(DATA)


if __name__=='__main__':main()
