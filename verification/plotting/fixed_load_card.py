"""Recompute scalar raw evidence and publish fixed-width resistor tradeoffs."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import project,scalar_raw,spice

ROOT=project.ROOT
RUNNER=ROOT/'analog/common/devices/tb/passive_card/fixed_load_card.py'
spec=importlib.util.spec_from_file_location('fixed_card_publish',RUNNER)
card=importlib.util.module_from_spec(spec);spec.loader.exec_module(card)
DIAG=RUNNER.with_name('fixed_load_ac_check.py')
spec=importlib.util.spec_from_file_location('fixed_card_diag',DIAG)
diag=importlib.util.module_from_spec(spec);spec.loader.exec_module(diag)
sha=card.sha


def collect(summary,diagnostic):
    camp=summary.parents[2];card.check(camp)
    report=card.read(summary);audit=card.read(diagnostic)
    if report['status']!='passive_measurements_complete_not_circuit_qualified':raise ValueError('passive scan incomplete')
    if report['plan_sha256']!=sha(camp/'plan.json') or report['networks_sha256']!=sha(camp/'networks.json'):raise ValueError('plan/networks changed')
    for rel,expected in {**report['evidence'],**audit['evidence']}.items():
        if sha(ROOT/rel)!=expected:raise ValueError('raw/deck/log evidence changed: '+rel)
    model=report['model']
    expected_keys={(p['id'],rc,t,d) for p in model['parts'] for rc in card.CORNERS for t in card.TEMPS for d in card.DROPS}
    rows={(r['id'],r['corner'],r['temp_c'],r['drop_v']):r for r in report['rows']}
    if len(rows)!=len(report['rows']) or set(rows)!=expected_keys:raise ValueError('missing/duplicate passive points')
    # Re-evaluate every scalar in all 90 DC/AC outputs rather than trust JSON.
    for rc in card.CORNERS:
        text=card.deck(model['parts'],rc)
        outputs=[f't{t}_d{round(d*1000)}_{k}.raw' for t in card.TEMPS for d in card.DROPS for k in ('op','ac')]
        run=card.complete(camp,rc,text,outputs)
        if run is None:raise ValueError('incomplete passive execution')
        for t in card.TEMPS:
            for d in card.DROPS:
                prefix=f't{t}_d{round(d*1000)}'
                op=scalar_raw.read(run/(prefix+'_op.raw'));ac=scalar_raw.read(run/(prefix+'_ac.raw'),frequency_hz=2e9)
                for p in model['parts']:
                    n=p['id'];r=rows[n,rc,t,d]
                    for field,value in [('resistance_ohm',op['r_'+n]),('incremental_resistance_ohm',ac['rd_'+n]),('node_capacitance_f',ac['c_'+n])]:
                        if value!=r[field]:raise ValueError('scalar recomputation differs')
    # Independently recover the completed transient/DC cross-check.
    dc=diagnostic.parents[2];plan=card.read(dc/'plan.json');run=dc/'run'
    if audit['plan_sha256']!=sha(dc/'plan.json') or plan['networks_sha256']!=report['networks_sha256']:raise ValueError('diagnostic source differs')
    if spice.case_output(dc,'run','transient.raw',3e-9) is None:raise ValueError('truncated transient cross-check')
    low,high=spice.Waves(run/'low.raw'),spice.Waves(run/'high.raw');w=spice.Waves(run/'transient.raw')
    checked=[]
    for r in audit['rows']:
        n=r['id'];current=f'i(vport_{n})';rd=-.002/(high[current][0]-low[current][0])
        tr=diag.admittance(w,n)
        if not np.isclose(rd,r['DC_differential_resistance_ohm'],rtol=1e-12):raise ValueError('DC cross-check differs')
        if tr!=r['transient']:raise ValueError('transient cross-check differs')
        checked.append(r)
    compact=[]
    for p in model['parts']:
        if p['kind']=='reference_tracking':continue
        n=p['id'];nom=rows[n,'tt',27,.25];R0=nom['resistance_ohm']
        values=[r['resistance_ohm']/R0 for key,r in rows.items() if key[0]==n]
        ratios=[]
        ref0=rows['reference','tt',27,.25]['resistance_ohm']
        for rc in card.CORNERS:
            for t in card.TEMPS:
                ratio=(rows[n,rc,t,.25]['resistance_ohm']/rows['reference',rc,t,.25]['resistance_ohm'])/(R0/ref0)
                ratios.append(dict(corner=rc,temp_c=t,normalized_ratio=ratio))
        compact.append(dict(id=n,kind=p['kind'],nominal_ohm=p['nominal_ohm'],
                            parallel_count=p.get('parallel_count'),length_um=p['length_um'],
                            TT27C_250mV_resistance_ohm=R0,TT27C_250mV_node_capacitance_f=nom['node_capacitance_f'],
                            resistance_relative_range_all_45=[min(values),max(values)],
                            reference_ratio_range_15=[min(x['normalized_ratio'] for x in ratios),max(x['normalized_ratio'] for x in ratios)],
                            reference_ratios=ratios,
                            TT27C_voltage_curve=[dict(drop_v=d,resistance_ohm=rows[n,'tt',27,d]['resistance_ohm']) for d in card.DROPS]))
    return dict(status='passive_and_TT_transient_verified; fixed_card_AC_resistance_not_validated',adopted=False,
                campaign=str(camp.relative_to(ROOT)),summary=str(summary.relative_to(ROOT)),summary_sha256=sha(summary),
                diagnostic=str(diagnostic.relative_to(ROOT)),diagnostic_sha256=sha(diagnostic),
                plan_sha256=sha(camp/'plan.json'),networks_sha256=sha(camp/'networks.json'),
                runner_sha256=sha(RUNNER),publisher_sha256=sha(Path(__file__)),
                calibrated_length_formula='R=A+B*L+C/L; TT27C,250mV; longer monotonic root, L>=0.5um, 0.01um grid',
                coefficients_ohm=model['coefficients_ohm'],fit_max_error_ohm=model['fit_max_error_ohm'],
                illegal_choices=[r for r in model['choices'] if r['status']!='planned'],parts=compact,AC_cross_check=checked,
                scope='Five RC corners x three temperatures x three voltage drops; 24 passive networks; no MOS PVT or full circuit qualification.',
                reference_proxy='1p41 L42.36 at 250mV, normalized at TT27C. This is a geometric tracking proxy, not the actual 112k+trim reference, Vbg or bias-loop response.',
                AC_policy='Retain AC results as measurements; do not use fixed-card AC real part for physical impedance selection. TT DC slope and 1mV/2GHz transient agree; cause of AC discrepancy remains unresolved.',
                capacitance_scope='One load-end admittance to AC-ground rail/body at 2GHz, PDK intrinsic parasitics only; no layout routing or MOS capacitance.',
                ungraded=card.read(camp/'plan.json')['ungraded'])


def plot(data):
    fig,axes=plt.subplots(2,3,figsize=(13.2,7.8),layout='constrained')
    for row,target in enumerate((50,120)):
        parts=[p for p in data['parts'] if p['nominal_ohm']==target]
        labels=['generic' if p['kind']=='legacy_generic' else f'{p["parallel_count"]} x {p["length_um"]:.2f}um' for p in parts]
        for p,label in zip(parts,labels):
            axes[row,0].plot([r['drop_v'] for r in p['TT27C_voltage_curve']],
                             [r['resistance_ohm'] for r in p['TT27C_voltage_curve']],'-o',label=label)
        caps=[p['TT27C_250mV_node_capacitance_f']*1e15 for p in parts]
        axes[row,1].bar(labels,caps,color=['#73808c']+['#447e9b']*(len(parts)-1))
        for i,v in enumerate(caps):axes[row,1].text(i,v+.08,f'{v:.2f}',ha='center',fontsize=8)
        for i,p in enumerate(parts):
            lo,hi=np.array(p['reference_ratio_range_15'])*100-100
            axes[row,2].plot([i,i],[lo,hi],color='#447e9b',lw=3)
            axes[row,2].scatter([i,i],[lo,hi],color='#447e9b',s=25)
        axes[row,2].set_xticks(range(len(parts)),labels);axes[row,2].axhline(0,color='#888',lw=.7)
        axes[row,0].set(title=f'{target} ohm nominal: TT DC voltage dependence',xlabel='Voltage drop (V)',ylabel='DC resistance (ohm)')
        axes[row,0].legend(fontsize=8)
        axes[row,1].set(title='Load-end intrinsic capacitance',ylabel='Capacitance at 2GHz (fF)')
        axes[row,2].set(title='Ratio to long fixed reference: 15 RC/T points',ylabel='Normalized ratio change (%)')
        for ax in axes[row]:ax.grid(alpha=.2,axis='y')
        for ax in axes[row,1:]:ax.tick_params(axis='x',rotation=15)
    fig.suptitle('Fixed-width parallel resistor planning: legal geometry is only the first constraint',fontsize=13)
    fig.supxlabel('Match legacy TT27C/250mV R first. Reference-ratio proxy only; fixed-card AC real part excluded; no dimensions adopted.',fontsize=9)
    return fig


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--summary',type=Path,required=True);p.add_argument('--diagnostic',type=Path,required=True);a=p.parse_args()
    data=collect(a.summary.resolve(),a.diagnostic.resolve());camp=ROOT/data['campaign']
    snapshot=camp/'publication_sources'/(sha(Path(__file__))+'.py');snapshot.parent.mkdir(exist_ok=True)
    if not snapshot.exists():shutil.copyfile(Path(__file__),snapshot)
    data['publisher_snapshot']=str(snapshot.relative_to(ROOT))
    output=ROOT/'docs/data/fixed_load_card.json';figure=ROOT/'docs/figures/common/fixed_load_card.png';figure.parent.mkdir(parents=True,exist_ok=True)
    plot(data).savefig(figure,dpi=170);plt.close('all');card.dump(output,data)
    card.dump(ROOT/'results/catalog/fixed_load_card.json',dict(data=str(output.relative_to(ROOT)),data_sha256=sha(output),
                figure=str(figure.relative_to(ROOT)),figure_sha256=sha(figure),summary=data['summary'],summary_sha256=data['summary_sha256'],
                diagnostic=data['diagnostic'],diagnostic_sha256=data['diagnostic_sha256'],scope=data['scope']))
    print(output);print(figure)


if __name__=='__main__':main()
