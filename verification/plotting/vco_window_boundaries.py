"""Verify and publish H4 VCO window boundary evidence from an explicit summary.

No ngspice is run. The 95 historical brackets retain their source identity limits.
"""
import argparse
import importlib.util
import json
import math
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT/'analog/pll/vco/tb/tuning/window_boundary_anchor.py'
spec = importlib.util.spec_from_file_location('vco_boundary_anchor', RUNNER)
anchor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(anchor)
DATA = ROOT/'docs/data/vco_window_boundaries.json'
CATALOG = ROOT/'results/catalog/vco_window_boundaries.json'
FIG = ROOT/'docs/figures/clocking/vco/vco_h4_boundary_confirmation.png'
READONLY = ROOT/'verification/analysis/vco_boundary_readonly.py'


def verify(summary):
    summary = summary.resolve()
    camp = summary.parent.parent.parent
    spec = importlib.util.spec_from_file_location('vco_boundary_readonly',READONLY)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    guard = module.ReadOnlyVerification(camp,anchor)
    with guard:
        data = verified_measurements(summary,guard)
    data['historical_read_only_verification']={**guard.report,
        'verifier':str(READONLY.relative_to(ROOT)),'verifier_sha256':anchor.sha(READONLY),
        'policy':'only exact SPICE SHA pair; whole module AST equal outside run/log_failures; filesystem mutations and child processes forbidden during verification; original resume checks unchanged'}
    for source,label,expected in [(Path(__file__),'publisher',data['publisher_sha256']),
                                 (READONLY,'readonly',data['historical_read_only_verification']['verifier_sha256'])]:
        target=camp/'publication_sources'/f'{label}_{expected}.py'
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            with target.open('xb') as stream:stream.write(source.read_bytes())
        if anchor.sha(target)!=expected:raise ValueError('publication source snapshot changed')
        data[label+'_snapshot']=str(target.relative_to(ROOT))
    return data


def verified_measurements(summary,guard):
    camp = guard.camp
    plan, groups = guard.verify()
    measured = json.loads(summary.read_text())
    if measured['source_sha256'] != plan['source_sha256'] or measured['fill_sha256'] != plan['fill_sha256']:
        raise ValueError('summary source identity differs')
    if measured['already_complete'] != plan['already_complete'] or measured['no_single_point_candidate'] != plan['no_single_point_candidate']:
        raise ValueError('summary prior evidence differs')
    rows = measured['rows']; expected = plan['selected']
    if len(rows) != 40 or len(expected) != 40 or len(plan['already_complete']) != 95 or plan['no_single_point_candidate']:
        raise ValueError('unexpected campaign coverage')
    if len({r['condition'] for r in rows} | {r['condition'] for r in plan['already_complete']}) != 135:
        raise ValueError('conditions not unique or incomplete')
    paths = {name:anchor.checked(camp,name,items) for name,items in groups.items()}
    records = []
    for row, item in zip(rows,expected):
        if any(row.get(k) != v for k,v in item.items()): raise ValueError('selected item differs')
        if item['existing_boundary_frequency_hz'] is not None: raise ValueError('expected new measurement for every row')
        c,k,v = anchor.points([item])[0]
        path = paths[anchor.group_name(item)][anchor.wm.name(c,k,v)]
        if path is None or path.resolve() != (ROOT/row['run_waveform']).resolve(): raise ValueError('raw missing or summary path differs')
        run = path.parent
        execution = json.loads((run/'execution.json').read_text())
        deck = run/'tb.cir'
        if (execution.get('exit_code') != 0 or execution.get('timed_out') or execution.get('log_failures')
                or execution.get('deck_sha256') != anchor.sha(deck)
                or execution.get('pdk_installation_id') != plan['pdk_installation_id']):
            raise ValueError(f'unsuccessful execution: {run}')
        value = anchor.wm.measure(path)
        if value is None or not all(math.isfinite(x) for x in value): raise ValueError(f'invalid measurement: {path}')
        f,swing = value
        if not math.isclose(f,row['boundary_frequency_hz'],rel_tol=1e-12) or not math.isclose(swing,row['boundary_swing_v'],rel_tol=1e-12):
            raise ValueError(f'summary does not match waveform: {path}')
        signed = anchor.wm.TARGET-f if item['side']=='lo' else f-anchor.wm.TARGET
        paired = item['existing_frequency_hz'] >= anchor.wm.TARGET if item['side']=='lo' else item['existing_frequency_hz'] <= anchor.wm.TARGET
        if signed < 0 or not paired or row['status'] != 'evidenced_bracket': raise ValueError(f'no measured bracket: {path}')
        records.append({**item,'boundary_frequency_hz':f,'swing_v':swing,'signed_frequency_margin_hz':signed,
                        'raw_path':str(path.relative_to(ROOT)), 'raw_sha256':anchor.sha(path),
                        'deck_path':str(deck.relative_to(ROOT)), 'deck_sha256':anchor.sha(deck),
                        'execution_path':str((run/'execution.json').relative_to(ROOT)), 'execution_sha256':anchor.sha(run/'execution.json')})
    if Counter(r['side'] for r in records) != {'lo':31,'hi':9}: raise ValueError('side counts changed')
    return dict(scope='Historical r5 single-supply H4 ideal static nominal .90..VDD-.44 V, real bias, PDK R, 4 buffers and 30 fF per leg; not current separated host/quiet supply, actual thresholds, B2/CP/LF dynamic loading or MC/noise qualification; not adopted',
                prior_limit='95 prior measured same-code in-window brackets use source/fill identity and historical resume audit; historical PDK file and original source-summary hashes were not recorded',
                fixed_code_limit='40 added one-code boundary checks do not qualify previously predicted three-temperature common-code count',
                summary_path=str(summary.relative_to(ROOT)),summary_sha256=anchor.sha(summary),
                plan_path=str((camp/'plan.json').relative_to(ROOT)),plan_sha256=anchor.sha(camp/'plan.json'),
                source_path=plan['source_path'],source_sha256=plan['source_sha256'],fill_path=plan['fill_path'],fill_sha256=plan['fill_sha256'],
                pdk_installation_id=plan['pdk_installation_id'],runner_path=str(RUNNER.relative_to(ROOT)),runner_sha256=anchor.sha(RUNNER),
                publisher_path=str(Path(__file__).resolve().relative_to(ROOT)),publisher_sha256=anchor.sha(__file__),
                prior_conditions=plan['already_complete'],new_boundary_measurements=records,
                prior_count=95,new_count=40,low_count=31,high_count=9,
                min_frequency_margin=min(records,key=lambda x:x['signed_frequency_margin_hz']))


def publish(data):
    records=sorted(data['new_boundary_measurements'],key=lambda r:r['signed_frequency_margin_hz'])
    fig,ax=plt.subplots(figsize=(11.5,5.4),layout='constrained')
    for side,color,label in [('lo','#167d9a','Lower boundary (31)'),('hi','#d87839','Upper boundary (9)')]:
        xs=[i for i,r in enumerate(records) if r['side']==side]
        ax.scatter(xs,[records[i]['signed_frequency_margin_hz']/1e6 for i in xs],s=35,color=color,label=label,zorder=3)
    low=records[0]
    ax.annotate(f"Minimum {low['signed_frequency_margin_hz']/1e6:.2f} MHz\n{low['condition']}  K{low['code']}",
                xy=(0,low['signed_frequency_margin_hz']/1e6),xytext=(5,low['signed_frequency_margin_hz']/1e6+25),
                arrowprops={'arrowstyle':'->','color':'#555'},fontsize=9)
    ax.axhline(0,color='#555',linewidth=.8);ax.grid(axis='y',alpha=.25)
    ax.set(xlabel='New boundary checks, ordered by signed frequency margin',ylabel='Signed frequency margin to 2 GHz (MHz)',
           title='H4 static window evidence: 95 prior brackets + 40 new boundary checks')
    ax.legend(frameon=False);fig.savefig(FIG,dpi=180);plt.close(fig)
    DATA.parent.mkdir(parents=True,exist_ok=True);CATALOG.parent.mkdir(parents=True,exist_ok=True)
    DATA.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    catalog=dict(scope=data['scope'],data=str(DATA.relative_to(ROOT)),figure=str(FIG.relative_to(ROOT)),
                 data_sha256=anchor.sha(DATA),figure_sha256=anchor.sha(FIG),
                 summary=data['summary_path'],summary_sha256=data['summary_sha256'],plan=data['plan_path'],plan_sha256=data['plan_sha256'],
                 source_sha256=data['source_sha256'],fill_sha256=data['fill_sha256'],prior_count=95,new_count=40,
                 limitation=data['prior_limit'],publisher_snapshot=data['publisher_snapshot'],
                 readonly_snapshot=data['readonly_snapshot'],historical_read_only_verification=data['historical_read_only_verification'])
    CATALOG.write_text(json.dumps(catalog,indent=2)+'\n')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--summary',type=Path,required=True);a=ap.parse_args()
    data=verify(a.summary);publish(data)
    print(f"95 prior + 40 new, min {data['min_frequency_margin']['signed_frequency_margin_hz']/1e6:.6f} MHz; {DATA.relative_to(ROOT)}")


if __name__=='__main__':main()
