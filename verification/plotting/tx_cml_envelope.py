"""Observe full-TX CML envelopes, only from verified completed campaigns.

--campaign is explicit and repeatable. --check reads metadata, never raw waves.
--self-test checks synthetic metrics; neither option writes outputs or runs ngspice.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np

from serdes_flow import clock, spice, watch, waves
from serdes_flow.project import ROOT

COLLECTOR = ROOT / 'verification/plotting/tx_parallel_serializer.py'
spec = importlib.util.spec_from_file_location('tx_parallel_collector', COLLECTOR)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
START, STOP = 40e-9, 100e-9
DATA = ROOT / 'docs/data/tx_cml_envelope.json'
CATALOG = ROOT / 'results/catalog/tx_cml_envelope.json'
FIGURE = ROOT / 'docs/figures/tx/ingress/tx_cml_amplitude_map'

CLOCKS = {**{f'q{i}': (f'xclocks.q{i}p', f'xclocks.q{i}n') for i in range(3)},
          **{x: (f'xclocks.xcnt.{x}p', f'xclocks.xcnt.{x}n') for x in ('ck',)},
          **{x: (f'xclocks.{stem}p', f'xclocks.{stem}n') for x, stem in [('kc','kc'), ('kr','kr'), ('r2g','r2g')]},
          **{x: (x+'p', x+'n') for x in ('c250', 'c500', 'c1g', 'c2g')},
          'boundary_s2g': ('s2gp', 's2gn'),
          **{x: (f'xtx.xtree.xr4_0.{x}p', f'xtx.xtree.xr4_0.{x}n') for x in ('sa', 'sb')}}
DATA_GROUPS = {
    'counter_data': {x: (f'xclocks.xcnt.{x}p', f'xclocks.xcnt.{x}n') for x in ('d1', 'd2', 'm1', 'm2')},
    'converters': {f'p{i}': (f'xtx.p{i}', f'xtx.n{i}') for i in range(16)},
    **{f'g{stage}': {f'g{stage}_{i}': (f'xtx.xtree.g{stage}_{i}p', f'xtx.xtree.g{stage}_{i}n') for i in range(n)} for stage,n in ((1,8),(2,4),(3,2))},
    'held': {x: (f'xtx.xtree.xr4_0.{x}p', f'xtx.xtree.xr4_0.{x}n') for x in ('ah','bh')},
    'output': {'serializer': ('qp','qn'), 'pad': ('lqp','lqn'), 'remote': ('lrp','lrn')},
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def preflight(paths):
    camps = [p.resolve() for p in paths]
    if not camps or len(set(camps)) != len(camps):
        raise ValueError('provide distinct explicit campaigns')
    alive = watch.ngspice_cwds()
    out = []
    for camp in camps:
        if not camp.is_relative_to(ROOT):
            raise ValueError('campaign must be within repository')
        if any(p == camp or p.is_relative_to(camp) for p in alive):
            raise ValueError(f'active ngspice: {camp}')
        plan = json.loads((camp/'plan.json').read_text())
        if plan.get('mode') != 'run' or not math.isclose(plan.get('stop_s', 0), 120e-9, abs_tol=1e-15, rel_tol=0):
            raise ValueError(f'expected full 120 ns run: {camp}')
        if not (camp/'summary.json').is_file() or (camp/'analysis_error.json').exists():
            raise ValueError(f'missing or rejected collector summary: {camp}')
        for rel, expected in plan['snapshot_files'].items():
            if sha(camp/rel) != expected:
                raise ValueError(f'checkpoint mismatch: {camp/rel}')
        if sha(camp/'execution/physical_tb.cir') != plan['deck_sha256']:
            raise ValueError('physical checkpoint deck mismatch')
        attempts = [camp/'run'] + [p for p in camp.glob('run.r*') if p.name[5:].isdigit()]
        okay = []
        for run in attempts:
            if not (run/'execution.json').is_file() or not (run/'tb.cir').is_file():
                continue
            ex = json.loads((run/'execution.json').read_text())
            if (ex.get('exit_code') == 0 and not ex.get('timed_out') and not ex.get('log_failures')
                and ex.get('deck_sha256') == plan['deck_sha256'] == sha(run/'tb.cir')
                and ((run/'waveforms.raw').is_file() or (run/'waveforms.raw.gz').is_file())):
                okay.append(run)
        if not okay:
            raise ValueError(f'no completed execution with matching deck and raw: {camp}')
        out.append(camp)
    return out


def envelope(t, p, n, is_clock):
    t, p, n = (np.asarray(x, dtype=float) for x in (t,p,n))
    if (len(t)<2 or p.shape != t.shape or n.shape != t.shape or not np.all(np.isfinite(t))
        or not np.all(np.isfinite(p)) or not np.all(np.isfinite(n)) or np.any(np.diff(t)<=0)
        or t[0]>START or t[-1]<STOP):
        raise ValueError('invalid or uncovered waveform')
    inside = (t > START) & (t < STOP)
    ti = np.r_[START, t[inside], STOP]
    pi = np.r_[np.interp(START,t,p), p[inside], np.interp(STOP,t,p)]
    ni = np.r_[np.interp(START,t,n), n[inside], np.interp(STOP,t,n)]
    diff, cm = pi-ni, (pi+ni)/2
    low, high = float(np.min(diff)), float(np.max(diff))
    cycles = clock.cycle_amplitudes(ti,diff,START,STOP) if is_clock else None
    minimum = cycles['min_pp_v'] if cycles is not None else None
    return {'diff_pp_v': high-low, 'diff_min_v': low, 'diff_max_v': high,
            'common_mode_min_v': float(np.min(cm)), 'common_mode_max_v': float(np.max(cm)),
            'common_mode_time_mean_v': waves.time_average(cm,ti),
            'observed_both_polarities': bool(low<0 and high>0),
            'observed_400mv_upper_screen': bool(high-low<=0.4),
            'cycle_amplitudes': cycles,
            'observed_min_cycle_150mv_screen': minimum >= 0.15 if minimum is not None else None,
            'observed_min_cycle_200mv_target': minimum >= 0.2 if minimum is not None else None,
            'lower_bound_status': 'clock_cycle_screen' if is_clock and minimum is not None else 'ungraded'}


def analyze(camp):
    if any(p == camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()):
        raise ValueError(f'active ngspice: {camp}')
    # Never use rejected analyses: this verifies summary, actual execution, all
    # boundary/producer/schedule identities, raw completeness and interface metrics.
    case = collector.collect(camp)
    required = ('input_boundary_ok', 'halfword_hold_ok', 'behavioral_tags_align')
    if any(case.get(k) is not True for k in required) or case.get('counter', {}).get('counting') is not True:
        raise ValueError(f'interface or counter verification failed: {camp}')
    counter = case['counter']
    compact = {key: case[key] for key in ('campaign','condition','clock_extra_2g','clock_output_wt',
               'clock_output_r','numerical_source_graph_sha256','waveform','hashes','accepted_words',
               'actual_capture_edges','sequence_start_s',*required)}
    compact['counter'] = {key: counter[key] for key in ('counting','samples','invalid_steps') if key in counter}
    ser = case['outputs']['serializer']
    compact['serializer'] = {'check': ser['check'], 'meets_spec': ser['meets_spec'],
                             'mapping': ser['mapping'],
                             'status': 'pass' if ser['meets_spec'] else 'fail'}
    wave = ROOT/case['waveform']
    w = spice.Waves(wave)
    if w.t[0] > START or w.t[-1] < 120e-9*(1-1e-6):
        raise ValueError('waveform lacks observation window or full 120 ns')
    def group(pairs, clocks=False):
        return {name: {'positive_node':p,'negative_node':n, **envelope(w.t,w[p],w[n],clocks)} for name,(p,n) in pairs.items()}
    clocks = group(CLOCKS, True)
    clocks['boundary_s2g']['role'] = 'prescribed_source_boundary_not_dut'
    clocks['boundary_s2g']['observed_400mv_upper_screen'] = None
    clocks['boundary_s2g']['observed_min_cycle_150mv_screen'] = None
    clocks['boundary_s2g']['observed_min_cycle_200mv_target'] = None
    clocks['boundary_s2g']['lower_bound_status'] = 'ungraded_boundary'
    data = {name: group(pairs) for name,pairs in DATA_GROUPS.items()}
    return {'source': compact, 'raw_sha256': sha(wave), 'execution_sha256': sha(wave.parent/'execution.json'),
            'deck_sha256': sha(wave.parent/'tb.cir'), 'plan_sha256': sha(camp/'plan.json'),
            'summary_sha256': sha(camp/'summary.json'), 'clocks': clocks, 'data_groups': data}


def plot(rows):
    groups = list(DATA_GROUPS)
    clks = list(CLOCKS)
    a = np.array([[r['clocks'][x]['diff_pp_v']*1e3 for x in clks] for r in rows])
    b = np.array([[max(item['diff_pp_v'] for item in r['data_groups'][g].values())*1e3 for g in groups] for r in rows])
    labels = [collector.case_label(r['source']) for r in rows]
    fig,axes = plt.subplots(2,1,figsize=(17,max(6,2+len(rows))),layout='constrained')
    cmap = ListedColormap(['#e9f4e7','#b4dcad','#f4da87','#aa272b'])
    norm = BoundaryNorm([0,200,300,400,1e9],cmap.N,clip=True)
    for ax,arr,names,title in [(axes[0],a,clks,'Named clocks: observed differential peak-to-peak'),(axes[1],b,groups,'Data groups: maximum observed node peak-to-peak')]:
        im = ax.imshow(arr,aspect='auto',norm=norm,cmap=cmap)
        ax.set_xticks(range(len(names)), names, rotation=45, ha='right')
        ax.set_yticks(range(len(labels)),labels,fontsize=8)
        ax.set_title(title+' (mV)')
        for i in range(len(rows)):
            for j in range(len(names)):
                ax.text(j,i,f'{arr[i,j]:.0f}',ha='center',va='center',fontsize=7,
                        color='white' if arr[i,j]>=400 else 'black',fontweight='bold' if arr[i,j]>=400 else 'normal')
    cbar = fig.colorbar(im,ax=axes,ticks=[100,250,350,500000200],label='mVpp; red ≥400 (exact 400 allowed)')
    cbar.ax.set_yticklabels(['<200','200–300','300–400','≥400'])
    fig.suptitle('40–100 ns observed CML envelopes; upper-bound screen only, not I-17 closure')
    FIGURE.parent.mkdir(parents=True,exist_ok=True)
    for ext in ('png','svg'):
        fig.savefig(FIGURE.with_suffix('.'+ext),dpi=180)
    plt.close(fig)


def self_test():
    t=np.linspace(0,120e-9,24001)
    y=.2*np.sin(2*np.pi*2e9*t)
    m=envelope(t,1+y/2,1-y/2,True)
    assert abs(m['diff_pp_v']-.4)<1e-6 and m['observed_both_polarities'] and m['cycle_amplitudes']['complete_cycles']>1
    m=envelope(t,np.ones_like(t)*1.1,np.ones_like(t),False)
    assert not m['observed_both_polarities'] and m['cycle_amplitudes'] is None
    assert envelope(t,np.ones_like(t),np.ones_like(t),True)['cycle_amplitudes'] is None
    print('synthetic metrics passed')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--campaign',action='append',type=Path)
    p.add_argument('--check',action='store_true')
    p.add_argument('--self-test',action='store_true')
    a=p.parse_args()
    if a.self_test:
        if a.campaign or a.check: p.error('--self-test must be used alone')
        self_test(); return
    if not a.campaign: p.error('at least one --campaign required')
    camps=preflight(a.campaign)
    if a.check:
        print(f'{len(camps)} campaigns passed metadata preflight; no raw read or output written'); return
    # Verify all campaigns before writing any result.
    rows=[analyze(camp) for camp in camps]
    sources=[Path(__file__).resolve(),COLLECTOR]+[ROOT/'src/serdes_flow'/x for x in ('clock.py','spice.py','waves.py','watch.py','serial.py','corners.py','project.py')]
    result={'scope':'verified source/interface; observed window upper screen only; no full PVT, noise or I-17 closure',
            'window_s':[START,STOP], 'analysis_source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sources},'cases':rows}
    text=json.dumps(result,indent=2,allow_nan=False)+'\n'
    DATA.parent.mkdir(parents=True,exist_ok=True)
    DATA.write_text(text)
    CATALOG.write_text(text)
    plot(rows)
    print('wrote',DATA,CATALOG,FIGURE.with_suffix('.png'),FIGURE.with_suffix('.svg'))


if __name__=='__main__': main()
