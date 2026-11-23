"""Recompute and publish the isolated fixed-poly signed-cube verification."""
import argparse
import importlib.util
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import project,scalar_raw,spice

ROOT=project.ROOT
HERE=Path(__file__).resolve()


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


card=module('overlay_publish_card',ROOT/'analog/common/devices/tb/passive_card/fixed_load_overlay.py')
probe=module('overlay_publish_probe',ROOT/'analog/common/devices/tb/passive_card/linearization_probe.py')
base=card.base;sha=base.sha


def collect(summary,expression):
    camp=summary.parents[2];plan=card.check(camp);report=base.read(summary);toy=base.read(expression)
    if report['status']!='overlay_DC_AC_transient_verified_not_circuit_adopted':raise ValueError('overlay verification incomplete')
    if report['plan_sha256']!=sha(camp/'plan.json'):raise ValueError('plan changed')
    for rel,expected in {**report['evidence'],**toy['evidence']}.items():
        if sha(ROOT/rel)!=expected:raise ValueError('executed evidence changed')
    parts=base.read(camp/'networks.json')['parts']
    rows={(r['id'],r['corner'],r['temp_c'],r['drop_v']):r for r in report['rows']}
    expected={(p['id'],c,t,d) for p in parts for c in base.CORNERS for t in base.TEMPS for d in base.DROPS}
    if set(rows)!=expected or len(rows)!=len(report['rows']) or not all(r['numerical_agreement'] for r in report['rows']):
        raise ValueError('missing/duplicate/failing grid points')
    # Every accepted derivative and unchanged-DC/C comparison is checked again.
    for rc in base.CORNERS:
        outputs=[f't{t}_d{round(d*1000)}_{k}.raw' for t in base.TEMPS for d in base.DROPS for k in ('op','ac','low','high')]
        run=base.complete(camp,rc,(camp/'prepared'/f'{rc}.cir').read_text(),outputs)
        if run is None:raise ValueError('incomplete RC corner')
        for t in base.TEMPS:
            for d in base.DROPS:
                prefix=f't{t}_d{round(d*1000)}'
                op=scalar_raw.read(run/(prefix+'_op.raw'));ac=scalar_raw.read(run/(prefix+'_ac.raw'),frequency_hz=2e9)
                lo,hi=[scalar_raw.read(run/(prefix+'_'+s+'.raw')) for s in ('low','high')]
                for p in parts:
                    n=p['id'];r=rows[n,rc,t,d];fd=2*card.DELTA/(hi['fd_'+n]-lo['fd_'+n])
                    actual=(op['r_'+n],ac['c_'+n],ac['rd_'+n],fd)
                    saved=(r['resistance_ohm'],r['node_capacitance_f'],r['AC_resistance_ohm'],r['finite_difference_resistance_ohm'])
                    if actual!=saved:raise ValueError('raw scalar verification differs')
    toy_camp=expression.parent;toy_plan=base.read(toy_camp/'plan.json')
    if toy['plan_sha256']!=sha(toy_camp/'plan.json'):raise ValueError('expression plan changed')
    if toy_plan['expressions']!=probe.EXPRESSIONS:raise ValueError('expression definitions changed')
    for path,value in toy_plan['sources'].items():
        if sha(toy_camp/'execution'/path.lstrip('/'))!=value:raise ValueError('archived expression source changed')
    for r in toy['rows']:
        i=list(probe.CENTERS).index(r['center_v']);name=r['name']
        lo,hi=[spice.Waves(toy_camp/'run'/f'p{i}_{s}.raw') for s in ('low','high')]
        ac=scalar_raw.read(toy_camp/'run'/f'p{i}_ac.raw',frequency_hz=2e9)
        fd=float((hi['o_'+name][0]-lo['o_'+name][0])/(2*probe.DELTA))
        if fd!=r['DC_derivative'] or ac['g_'+name]!=r['AC_derivative']:raise ValueError('expression derivative differs')
    transient_run=spice.case_output(camp,'transient','transient.raw',3e-9)
    if transient_run is None:raise ValueError('incomplete overlaid transient')
    w=spice.Waves(transient_run)
    for row in report['transient']:
        if card.diag.admittance(w,row['id'])!=row['transient']:raise ValueError('transient fit differs')
    corners=[]
    for rc in base.CORNERS:
        group=[r for r in report['rows'] if r['corner']==rc]
        corners.append(dict(corner=rc,points=len(group),
                            original_max_AC_FD_relative=max(abs(r['original_AC_to_DC_differential_relative']) for r in group),
                            overlay_max_AC_FD_relative=max(abs(r['AC_to_DC_differential_relative']) for r in group),
                            max_DC_relative_change=max(abs(r['DC_relative_change']) for r in group),
                            max_C_relative_change=max(abs(r['C_relative_change']) for r in group)))
    manifest=base.read(camp/'models/overlay.json')
    return dict(status='numeric_overlay_verified; opt_in_only; no_production_DUT_adoption',
                campaign=str(camp.relative_to(ROOT)),summary=str(summary.relative_to(ROOT)),summary_sha256=sha(summary),
                expression_summary=str(expression.relative_to(ROOT)),expression_summary_sha256=sha(expression),
                plan_sha256=sha(camp/'plan.json'),overlay_manifest=str((camp/'models/overlay.json').relative_to(ROOT)),
                overlay_manifest_sha256=sha(camp/'models/overlay.json'),changed_models=manifest['changes'],
                library=manifest['library'],source_installation_id=manifest['source_installation_id'],
                total_passive_points=len(report['rows']),corners=corners,expression_rows=toy['rows'],
                TT_transient=report['transient'],numerical_gates=plan['numerical_gates'],
                source_sha256={str(p.relative_to(ROOT)):sha(p) for p in (HERE,card.HERE,probe.HERE,Path(card.pdk_overlays.__file__))},
                scope=report['scope'],ungraded=plan['ungraded'],
                root_cause='Under project ngspice47/HSA, pow(x,3) at negative x has correct signed DC values but the wrong-sign AC derivative. Explicit multiplication and **3 agree with finite differences and tiny transient in the minimal probe. Only contact cubes in fixed 1p41/2p85 cards are changed.')


def plot(data):
    fig,axes=plt.subplots(1,3,figsize=(14.6,4.9),layout='constrained')
    centers=[.25,1.2,1.8,2.2]
    def values(name,key):return [next(r[key] for r in data['expression_rows'] if r['name']==name and r['center_v']==c) for c in centers]
    axes[0].plot(centers,values('pow3','DC_derivative'),'o-',label='DC finite difference')
    axes[0].plot(centers,values('pow3','AC_derivative'),'x--',label='pow(u,3) AC',color='#b65042')
    axes[0].plot(centers,values('mul3','AC_derivative'),'+:',label='u*u*u AC',color='#24816a')
    axes[0].axhline(0,color='#aaa',lw=.7);axes[0].set(title='Minimal cubic expression',xlabel='Input DC voltage (V)',ylabel='Derivative with respect to input')
    axes[0].legend(fontsize=8)
    x=np.arange(len(data['corners']))
    old=[r['original_max_AC_FD_relative']*100 for r in data['corners']]
    new=[r['overlay_max_AC_FD_relative']*100 for r in data['corners']]
    axes[1].bar(x-.18,np.maximum(old,1e-10),width=.36,color='#b65042',label='Original model')
    axes[1].bar(x+.18,np.maximum(new,1e-10),width=.36,color='#24816a',label='Isolated overlay')
    axes[1].set_yscale('log');axes[1].set_xticks(x,[r['corner'] for r in data['corners']]);axes[1].set(title='Worst AC / DC-slope discrepancy',ylabel='Absolute relative difference (%)')
    axes[1].axhline(.1,color='#777',ls=':',label='0.1% numeric gate');axes[1].legend(fontsize=8)
    selected=['r50_n5','r50_n8','r120_n2','r120_n4','r400_n1']
    entries=[next(r for r in data['TT_transient'] if r['id']==n) for n in selected]
    rel=[100*(r['AC_resistance_ohm']/r['DC_differential_resistance_ohm']-1) for r in entries]
    tran=[100*(r['transient']['resistance_ohm']/r['DC_differential_resistance_ohm']-1) for r in entries]
    axes[2].plot(range(len(entries)),rel,'o-',label='Corrected AC / DC')
    axes[2].plot(range(len(entries)),tran,'x--',label='1mV transient / DC')
    axes[2].set_xticks(range(len(entries)),selected,rotation=30);axes[2].set(title='Independent TT 2GHz small-signal check',ylabel='Relative difference (%)')
    axes[2].ticklabel_format(axis='y',style='sci',scilimits=(0,0));axes[2].legend(fontsize=8)
    for ax in axes:ax.grid(alpha=.2,axis='y')
    fig.suptitle('Signed-cube model overlay: preserve DC and capacitance, repair the tested AC derivative',fontsize=13)
    dc=max(r['max_DC_relative_change'] for r in data['corners']);cap=max(r['max_C_relative_change'] for r in data['corners'])
    fig.supxlabel(f'1080 passive points + 10 TT sine fits. Max relative DC change {dc:.2g}, C change {cap:.2g}. Installed PDK and production DUT unchanged.',fontsize=9)
    return fig


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--summary',type=Path,required=True);p.add_argument('--expression',type=Path,required=True);a=p.parse_args()
    data=collect(a.summary.resolve(),a.expression.resolve());camp=ROOT/data['campaign']
    snapshot=camp/'publication_sources'/(sha(HERE)+'.py');snapshot.parent.mkdir(exist_ok=True)
    if not snapshot.exists():shutil.copyfile(HERE,snapshot)
    data['publisher_snapshot']=str(snapshot.relative_to(ROOT))
    output=ROOT/'docs/data/fixed_load_overlay.json';figure=ROOT/'docs/figures/common/fixed_load_overlay.png'
    plot(data).savefig(figure,dpi=170);plt.close('all');base.dump(output,data)
    base.dump(ROOT/'results/catalog/fixed_load_overlay.json',dict(data=str(output.relative_to(ROOT)),data_sha256=sha(output),
              figure=str(figure.relative_to(ROOT)),figure_sha256=sha(figure),summary=data['summary'],summary_sha256=data['summary_sha256'],scope=data['scope']))
    print(output)
    for row in data['corners']:print(row)


if __name__=='__main__':main()
