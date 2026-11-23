"""Collect a fixed aperture campaign and redraw its deterministic hold map.

uv run python verification/plotting/tx_hold_aperture.py --collect CAMPAIGN
uv run python verification/plotting/tx_hold_aperture.py
The independent raw check covers the entire target selected-input window.
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import boundary, clock, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.timing import sampled_hold_boundary

DATA=ROOT/'docs/data/tx_launch_hold_aperture.json'
FIGURE=ROOT/'docs/figures/tx/ingress/tx_launch_hold_aperture.png'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_archive(camp,plan,entry):
    for rel,digest in plan['sources'].items():
        if sha(camp/'execution'/rel)!=digest:raise ValueError(f'archived input changed: {rel}')
    for rel,digest in entry['upstream']['physical_sources'].items():
        if plan['sources'].get(rel)!=digest:raise ValueError('physical recording/consumer dependency differs')
    if plan['sources'].get('analog/tx/input_register/spice/launch_hold_slice.spice')!=entry['consumer_sha256']:
        raise ValueError('consumer differs from registered cut')


def audit_row(row,c,entry,stop):
    item={k:row[k] for k in ('name','status','offset_ps')}
    if row['status']=='measured':
        path=ROOT/row['waveform'];w=spice.Waves(path)
        if w.t[-1]<stop*(1-1e-7):raise ValueError('truncated raw')
        event=entry['points'][c.tag]['events'][row['event']]
        selected_from=event['select_edge_s']-event['origin_s']
        closes=clock.edges(w.t,w['clk_b']-c.supply/2,-1,selected_from,stop)
        updates=clock.edges(w.t,w['data']-c.supply/2,event['polarity'],selected_from-.3e-9,stop)
        if len(closes)!=1 or len(updates)!=1:raise ValueError('ambiguous raw timing edges')
        delta=float((updates[0]-closes[0])*1e12)
        if abs(delta-row['metrics']['actual_separation_ps'])>.1:raise ValueError('reported/raw timing differs by >0.1ps')
        oldsign=-event['polarity']
        keep=(w.t>=selected_from-.1e-9)&(w.t<=stop)
        if not np.any(keep):raise ValueError('missing target selected window')
        qm=float(np.min((w['q'][keep]-c.supply/2)*oldsign))
        cm=float(np.min((w['cp'][keep]-w['cn'][keep])*oldsign))
        metrics=dict(row['metrics']);metrics['actual_separation_ps']=delta
        item.update(metrics=metrics,waveform=dict(path=row['waveform'],sha256=sha(path)),
                    selected_window_q_margin_v=qm,selected_window_cml_margin_v=cm,
                    q_margin_vdd=qm/c.supply,old_retained=qm>.3*c.supply and cm>0)
    elif 'error' in row:item['error']=row['error']
    return item


def collect(camp,refinements=()):
    plan_path,summary_path=camp/'plan.json',camp/'summary.json'
    plan=json.loads(plan_path.read_text());summary=json.loads(summary_path.read_text())
    entry=boundary.get(summary['boundary_id'])
    if hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()!=plan['boundary_sha256']:
        raise ValueError('boundary identity changed')
    verify_archive(camp,plan,entry)
    expected=[x['name'] for x in plan['cases']]
    names=[x['name'] for x in summary['rows']]
    if len(names)!=len(set(names)) or set(names)!=set(expected):raise ValueError('case identity mismatch')
    all_rows=list(summary['rows']);extra_baselines={};ref_sources=[]
    primary_keys={(x['condition'],x['event']) for x in plan['cases']}
    for directory in refinements:
        directory=directory.resolve();p2=directory/'plan.json';s2=directory/'summary.json'
        pp=json.loads(p2.read_text());ss=json.loads(s2.read_text())
        if pp['boundary_sha256']!=plan['boundary_sha256'] or pp['stop_s']!=plan['stop_s']:
            raise ValueError('refinement uses a different boundary/window')
        verify_archive(directory,pp,entry)
        n2=[r['name'] for r in ss['rows']]
        if len(n2)!=len(set(n2)) or set(n2)!={r['name'] for r in pp['cases']}:raise ValueError('refinement case identity differs')
        keys={(r['condition'],r['event']) for r in pp['cases']}
        if any(not any(r['condition']==c and r['event']==e and r['offset_ps'] is None for r in ss['rows']) for c,e in keys):
            raise ValueError('refinement requires its own baseline for each group')
        for row in ss['rows']:
            key=(row['condition'],row['event'])
            if key not in primary_keys:raise ValueError('refinement outside primary conditions/events')
            if row['offset_ps'] is None:extra_baselines.setdefault(key,[]).append(row)
            else:all_rows.append(row)
        ref_sources.append(dict(campaign=str(directory.relative_to(ROOT)),plan=dict(path=str(p2.relative_to(ROOT)),sha256=sha(p2)),summary=dict(path=str(s2.relative_to(ROOT)),sha256=sha(s2))))
    groups=[];disagreements=[]
    for cond in dict.fromkeys(x['condition'] for x in plan['cases']):
        c=Condition.parse(cond)
        for event in ('fall','rise'):
            rows=[x for x in all_rows if x['condition']==cond and x['event']==event]
            offsets=[r['offset_ps'] for r in rows]
            if len(offsets)!=len(set(offsets)):raise ValueError('overlapping refinement offsets; do not select latest')
            out=[]
            for row in rows:
                item=audit_row(row,c,entry,plan['stop_s'])
                if row['status']=='measured':
                    if item['old_retained']!=row['metrics']['old_retained']:disagreements.append(row['name'])
                out.append(item)
            baseline=next(x for x in out if x['offset_ps'] is None)
            scan=[x for x in out if x['offset_ps'] is not None]
            extra=[audit_row(r,c,entry,plan['stop_s']) for r in extra_baselines.get((cond,event),[])]
            calibration=all(b['status']=='measured' and b['metrics']['baseline_matches'] and b['old_retained'] for b in [baseline]+extra)
            complete=all(x['status']=='measured' for x in scan)
            frontier=sampled_hold_boundary([(x['metrics']['actual_separation_ps']*1e-12,x['old_retained']) for x in scan]) if calibration and complete else dict(status='incomplete_or_uncalibrated')
            if frontier['status']=='bracketed':
                frontier['baseline_distance_to_first_pass_ps']=baseline['metrics']['actual_separation_ps']-frontier['first_passed_s']*1e12
            groups.append(dict(condition=cond,event=event,calibrated=calibration,scan_complete=complete,
                               source_event=entry['points'][cond]['events'][event],frontier=frontier,rows=out,refinement_baselines=extra))
    result=dict(campaign=str(camp.relative_to(ROOT)),plan=dict(path=str(plan_path.relative_to(ROOT)),sha256=sha(plan_path)),
                summary=dict(path=str(summary_path.relative_to(ROOT)),sha256=sha(summary_path)),boundary_id=entry['id'],
                analysis_sources=[dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for p in
                    [Path(__file__).resolve(),ROOT/'src/serdes_flow/timing.py',ROOT/'src/serdes_flow/waves.py']],
                groups=groups,refinements=ref_sources,selected_window_disagreements=disagreements,
                scope='Two observed minimum-separation event shapes per stress condition. Fixed recorded clock/select/partner voltages and shifted data voltage; ideal source impedances. Not mismatch/noise, all patterns or 45PVT acceptance.')
    DATA.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    (ROOT/'results/catalog/tx_launch_hold_aperture.json').write_text(json.dumps(dict(data=str(DATA.relative_to(ROOT)),figure=str(FIGURE.relative_to(ROOT)),campaign=result['campaign'],refinements=[r['campaign'] for r in ref_sources],boundary_id=entry['id'],calibrated_groups=sum(x['calibrated'] for x in groups),complete_scans=sum(x['scan_complete'] for x in groups),baseline_cases=sum(1+len(g['refinement_baselines']) for g in groups),shifted_cases=sum(sum(r['offset_ps'] is not None for r in g['rows']) for g in groups)),indent=2)+'\n')
    return result


def plot(data):
    plt.rcParams.update({'font.family':'Noto Sans CJK JP','font.size':9,'axes.spines.top':False,'axes.spines.right':False})
    conditions=list(dict.fromkeys(g['condition'] for g in data['groups']))
    fig,axes=plt.subplots(2,3,figsize=(13,7),sharex=True,sharey=True)
    fig.subplots_adjust(left=.075,right=.98,bottom=.16,top=.89,wspace=.15,hspace=.3)
    all_x=[x['metrics']['actual_separation_ps'] for g in data['groups'] for x in g['rows'] if x['status']=='measured']
    for ax,cond in zip(axes.flat,conditions):
        c=Condition.parse(cond)
        ax.axhline(.3,color='#888',ls='--',lw=.8)
        for event,color in (('fall','#247f9d'),('rise','#bc703c')):
            g=next(x for x in data['groups'] if x['condition']==cond and x['event']==event)
            scan=[x for x in g['rows'] if x['offset_ps'] is not None and x['status']=='measured']
            scan.sort(key=lambda x:x['metrics']['actual_separation_ps'])
            ax.plot([x['metrics']['actual_separation_ps'] for x in scan],[x['q_margin_vdd'] for x in scan],'.-',color=color,label='数据下降' if event=='fall' else '数据上升')
            b=next(x for x in g['rows'] if x['offset_ps'] is None)
            if b['status']=='measured':ax.scatter(b['metrics']['actual_separation_ps'],b['q_margin_vdd'],marker='D',color=color,s=28,zorder=5)
            if g['frontier']['status']=='bracketed':ax.axvspan(g['frontier']['last_failed_s']*1e12,g['frontier']['first_passed_s']*1e12,color=color,alpha=.14)
        ax.set_title(f'{c.process.upper()} {c.supply:g}V / {c.temp}°C')
        ax.set_ylim(-.65,.65);ax.set_xlim(min(all_x)-10,max(all_x)+10);ax.grid(alpha=.15)
    axes[0,0].legend(fontsize=8,loc='lower right')
    fig.suptitle('B 锁存器关闭竞争：校准后的记录波形切片',fontsize=15,fontweight='bold',y=.97)
    fig.text(.5,.085,'数据中点交越 − clk_b 下降中点交越 / ps',ha='center')
    fig.text(.015,.52,'原数据的 CMOS 有符号最小裕量 / VDD',rotation=90,va='center')
    fig.text(.075,.025,'菱形：原始到达位置；色带：已测失败→保持的边界区间。判定还检查 CML 极性。电压回放，无失配/噪声，非45角签核。',fontsize=9)
    FIGURE.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(FIGURE,dpi=160);fig.savefig(FIGURE.with_suffix('.svg'));plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--collect',type=Path);p.add_argument('--refinement',type=Path,action='append',default=[]);a=p.parse_args()
    if a.refinement and not a.collect:p.error('--refinement requires --collect')
    data=collect(a.collect.resolve(),a.refinement) if a.collect else json.loads(DATA.read_text());plot(data)
    print(DATA.relative_to(ROOT),FIGURE.relative_to(ROOT))
