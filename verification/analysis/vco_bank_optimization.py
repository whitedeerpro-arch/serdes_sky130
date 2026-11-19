"""Enumerate a finite measured-leaf catalog; no interpolation or new SPICE.

Pareto results apply only to the ideal-interconnect AC proxy and old-r6 code
envelopes. Retention cuts and loss budgets are study parameters, not specs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import project
from serdes_flow.robust_sizing import pareto_mask, power_widths

ROOT = project.ROOT
SOURCE = ROOT/'results/analog/pll/vco/switch_allocation/20261114T175639.407250Z/analysis/20261114T175835.510673Z/summary.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evaluate(combo, source, meta, code_map):
    counts = np.array([1, 2, 2, 2, 2])
    states = np.array([[(code>>b)&1 for b in range(5)] for code in range(32)])
    width = float(sum(meta[n]['density_um']*(1<<b) for b,n in enumerate(combo)))
    coff, loss, loss_all, con, step = 0., 0., 0., float('inf'), float('inf')
    active_limit, cases = None, []
    for row in source['rows']:
        label, process, rc, vdd, temp = row['condition']
        key = f'{process}_v{round(vdd*1000)}_t{temp}:{rc}'
        codes = code_map[key]['codes']
        for fi in range(2):
            values = row['values']
            off = np.array([[values[f'off_{fi}'][n][k] for k in ('cap_ff','conductance_s')]
                            for n in combo])*counts[:,None]
            on = np.array([[values[f'on_{fi}'][n][k] for k in ('cap_ff','conductance_s')]
                           for n in combo])*counts[:,None]
            bank = off.sum(0)+states@(on-off)
            ref = row['profiles']['reference'][fi]
            step = min(step, float(np.diff(bank[:,0]).min()/ref['min_step_ff']))
            if fi != 1:
                continue
            coff_ratio = float(bank[0,0]/ref['coff_ff'])
            con_ratio = float(bank[-1,0]/ref['con_ff'])
            peak_code = int(max(codes, key=lambda code:bank[code,1]))
            loss_ratio = float(bank[peak_code,1]/max(ref['codes'][code]['conductance_s'] for code in codes))
            all_ratio = float(max(bank[:,1])/ref['max_conductance_s'])
            if loss_ratio > loss:
                loss, active_limit = loss_ratio, dict(condition=label, old_feasible_codes=codes, peak_code=peak_code)
            coff, con, loss_all = max(coff,coff_ratio), min(con,con_ratio), max(loss_all,all_ratio)
            cases.append(dict(condition=label, old_feasible_codes=codes, peak_code=peak_code,
                              coff_ff=float(bank[0,0]), peak_g_us=float(bank[peak_code,1]*1e6),
                              coff_ratio=coff_ratio, con_retention=con_ratio, loss_ratio=loss_ratio,
                              min_step_ff=float(np.diff(bank[:,0]).min())))
    widths = [meta[n]['density_um']*(1<<b) for b,n in enumerate(combo)]
    alpha = float(np.polyfit(np.log([1,2,4,8,16]), np.log(widths), 1)[0])
    return dict(leaves=list(combo), width_um=width, bit_width_um=widths,
                density_um=[meta[n]['density_um'] for n in combo], fitted_alpha=alpha,
                coff_ratio=coff, loss_ratio=loss, all_codes_loss_ratio=loss_all,
                con_retention=con, min_step_ratio=step, loss_limit=active_limit, cases=cases)


def eligible(row, con_floor, step_floor):
    return row['min_step_ratio']>0 and row['con_retention']>=con_floor-1e-9 and row['min_step_ratio']>=step_floor-1e-9


def frontier(rows):
    mask = pareto_mask([[r['coff_ratio'], r['loss_ratio']] for r in rows])
    return sorted([r for r,keep in zip(rows,mask) if keep], key=lambda r:r['coff_ratio'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    args = parser.parse_args()
    src = args.source.resolve()
    source = json.loads(src.read_text())
    campaign = ROOT/source['campaign']
    plan_path = campaign/'plan.json'
    if sha(plan_path) != source['plan_sha256']:
        raise ValueError('Plan changed')
    plan = json.loads(plan_path.read_text())
    if (plan['pdk_id'] != project.pdk_installation_id() or
        plan['model_sha256'] != sha(project.model_library())):
        raise ValueError('Installed model audit differs from frozen input identity')
    for name,digest in plan['inputs'].items():
        if sha(campaign/name) != digest:
            raise ValueError('Input changed: '+name)
    code_map = json.loads((campaign/'source/table.json').read_text())['rows']
    meta = {leaf['name']:leaf for leaf in plan['leaves']}
    choices = [[leaf['name'] for leaf in plan['leaves'] if leaf['units']==n] for n in (1,1,2,4,8)]
    rows = []
    for combo in itertools.product(*choices):
        width = sum(meta[n]['density_um']*(1<<b) for b,n in enumerate(combo))
        if width <= 46.5+1e-9:
            rows.append(evaluate(combo, source, meta, code_map))
    named = {name:next(r for r in rows if r['leaves']==[m['leaf'] for m in profile['members']])
             for name,profile in source['profiles'].items()}
    slices = []
    for con_floor,step_floor in itertools.product((0., .95, .98, .99), (0., .5, 1.)):
        accepted = [r for r in rows if eligible(r,con_floor,step_floor)]
        front = frontier(accepted)
        selected = {}
        for epsilon in (1., 1.1, 1.25, 1.5, 1.75, 2.):
            candidates = [r for r in front if r['loss_ratio']<=epsilon+1e-9]
            if candidates:
                selected[str(epsilon)] = min(candidates,key=lambda r:(r['coff_ratio'],r['loss_ratio'],r['width_um']))
        slices.append(dict(con_floor=con_floor, step_floor=step_floor,
                           count=len(accepted), frontier=front, epsilon_selected=selected))
    default = next(s for s in slices if s['con_floor']==.98 and s['step_floor']==1.)
    candidate = default['epsilon_selected']['1.5']
    compact = lambda r:{k:v for k,v in r.items() if k!='cases'}
    data = dict(scope=__doc__, scope_exclusions=['No global/local probability model or MC yield',
        'No updated calibration or temperature-held code policy', 'No full routed bank/ring/noise qualification'],
        count=len(rows), monotonic_count=sum(r['min_step_ratio']>0 for r in rows),
        study_parameters=dict(max_total_width_um=46.5, default_con_floor=.98,
                              default_step_floor=1., example_loss_budget=1.5,
                              official_specs=False),
        named={name:compact(r) for name,r in named.items()},
        slices=[dict(s, frontier=[compact(r) for r in s['frontier']],
                     epsilon_selected={name:compact(r) for name,r in s['epsilon_selected'].items()}) for s in slices],
        example_candidate=candidate,
        parameterization=dict(total_width_um=31.5, alpha=1., bit_floors_um=[1.5,0,0,0,0],
                              bit_width_um=power_widths(31.5,floors_um=[1.5,0,0,0,0]).tolist()),
        inputs_sha256={str(src.relative_to(ROOT)):sha(src),
                       str(plan_path.relative_to(ROOT)):sha(plan_path)})
    dest = ROOT/'results/analog/pll/vco/bank_optimization'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    dest.mkdir(parents=True)
    for path in [Path(__file__), ROOT/'src/serdes_flow/robust_sizing.py']:
        shutil.copyfile(path,dest/path.name)
        data['inputs_sha256'][str((dest/path.name).relative_to(ROOT))] = sha(dest/path.name)
    pdk = project.model_library().parent
    model_inputs = [project.model_library(), pdk/'r+c/res_high__cap_high.spice',
                    pdk/'r+c/res_low__cap_low.spice', pdk/'corners/ss/nonfet.spice',
                    pdk.parents[1]/'libs.ref/sky130_fd_pr/spice/sky130_fd_pr__nfet_01v8__mismatch.corner.spice',
                    pdk.parents[1]/'libs.ref/sky130_fd_pr/spice/sky130_fd_pr__cap_mim_m3_1.model.spice']
    for path in model_inputs:
        shutil.copyfile(path,dest/path.name)
        data['inputs_sha256'][str((dest/path.name).relative_to(ROOT))] = sha(dest/path.name)
    (dest/'all_candidates.json').write_text(json.dumps(rows,indent=2,allow_nan=False)+'\n')
    data['all_candidates']=str((dest/'all_candidates.json').relative_to(ROOT))
    data['inputs_sha256'][data['all_candidates']]=sha(dest/'all_candidates.json')
    fig,axes = plt.subplots(1,2,figsize=(11.4,4.5))
    axes[0].scatter([r['coff_ratio'] for r in rows], [r['loss_ratio'] for r in rows],
                    s=9,alpha=.22,color='0.6',label='Measured-leaf combinations')
    front = default['frontier']
    axes[0].plot([r['coff_ratio'] for r in front],[r['loss_ratio'] for r in front],
                 '.-',color='#146fa1',label='Pareto: Con >=98%, step >= reference')
    for name,label,color in [('reference','Original W46.5','#4a4a4a'),
                             ('proportional','Proportional W31','#d97c12'),
                             ('small_first','Small-first W31','#b83b50')]:
        r=named[name]
        axes[0].scatter(r['coff_ratio'],r['loss_ratio'],s=45,color=color)
        offset = {'reference':(-6,10),'proportional':(5,-16),'small_first':(5,8)}[name]
        axes[0].annotate(label,(r['coff_ratio'],r['loss_ratio']),xytext=offset,
                         ha='right' if name=='reference' else 'left',textcoords='offset points',fontsize=8)
    axes[0].scatter(candidate['coff_ratio'],candidate['loss_ratio'],s=80,marker='*',color='#238650',label='Study candidate W31.5')
    axes[0].set(xlabel='Worst normalized Coff (lower is better)',
                ylabel='Worst normalized peak G\n(old feasible-code envelope)',
                title='Seven local corners; ideal-interconnect AC proxy')
    axes[0].grid(alpha=.2)
    axes[0].legend(fontsize=7,loc='upper right')
    x=np.arange(5)
    axes[1].bar(x-.2,named['reference']['bit_width_um'],.4,label='Original W46.5')
    axes[1].bar(x+.2,candidate['bit_width_um'],.4,label='Study candidate W31.5')
    axes[1].set(xticks=x,xticklabels=[f'b{i}' for i in x],ylabel='Total switch width per bit (um)',
                title='alpha = 1 with a 1.5 um floor on b0')
    axes[1].legend(fontsize=8)
    axes[1].grid(axis='y',alpha=.2)
    for ax in axes:
        ax.title.set_fontsize(11)
    fig.tight_layout(pad=1.3,w_pad=2)
    figure = ROOT/'docs/figures/layout/vco_bank_optimization.png'
    fig.savefig(figure,dpi=160,bbox_inches='tight')
    plt.close(fig)
    shutil.copyfile(figure,dest/'pareto.png')
    data['inputs_sha256'][str((dest/'pareto.png').relative_to(ROOT))] = sha(dest/'pareto.png')
    data['figure']=str(figure.relative_to(ROOT))
    data_path = ROOT/'docs/data/vco_bank_optimization.json'
    data_path.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    shutil.copyfile(data_path,dest/'summary.json')
    catalog = dict(summary=str((dest/'summary.json').relative_to(ROOT)), summary_sha256=sha(dest/'summary.json'),
                   data=str(data_path.relative_to(ROOT)), data_sha256=sha(data_path),
                   figure=str(figure.relative_to(ROOT)), figure_sha256=sha(figure), scope=__doc__)
    (ROOT/'results/catalog/vco_bank_optimization.json').write_text(json.dumps(catalog,indent=2)+'\n')
    print(dest/'summary.json')
    print(json.dumps(dict(candidates=len(rows),default_slice=default['count'],
                         pareto_count=len(front),candidate=compact(candidate)),indent=2))


if __name__=='__main__':
    main()
