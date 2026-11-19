"""Current r6 loop sensitivity and evidence inventory; no noise qualification."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tomllib

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import clock, feedback, pll_lock, pnoise, project, spice

ROOT = project.ROOT


def identity(path):
    p = ROOT / path
    return dict(path=path, sha256=hashlib.sha256(p.read_bytes()).hexdigest())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--map', required=True, help='Explicit r6 table.json')
    ap.add_argument('--native-summary', required=True, help='Explicit new native-loop analysis/summary.json')
    a = ap.parse_args()
    paths = [a.map, a.native_summary,
        'analog/pll/top/spice/pll_core_r6k4q.spice',
        'analog/pll/top/spice/clock_frontend_r6q.spice',
        'analog/pll/vco/spice/vco_ring4_r6.spice',
        'analog/pll/vco/spice/vco_delay_r6.spice',
        'analog/pll/vco/spice/cap_bank_5b.spice',
        'analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice',
        'analog/pll/top/tb/native_r6/run.py',
        'analog/pll/top/tb/native_r6/campaign.py',
        'analog/tx/serializer/tb/clock_replay/variants/dist_v3.py',
        'analog/tx/serializer/tb/native_clock/r5_v3.py',
        'analog/tx/input_register/tb/full_serializer/run.py',
        'analog/tx/input_register/tb/full_serializer/tb_full_ngspice.cir.in',
        'verification/digital/tx_ingress_stimulus.py',
        'docs/data/tx_full_pvt45.json',
        'analog/pll/vco/tb/phase_noise/corner.py',
        'analog/pll/vco/tb/phase_noise/isf_4b_pilot.py',
        'analog/pll/vco/tb/mc/run.py',
        'docs/data/vco_isf_4b.json', 'docs/data/native_pll_cost.json',
        'src/serdes_flow/pnoise.py', 'src/serdes_flow/feedback.py',
        'src/serdes_flow/clock.py', 'src/serdes_flow/pll_lock.py',
        'verification/contracts/pll_lock_screen.toml', 'verification/analysis/r6_mainline_review.py']
    rows = json.loads((ROOT / a.map).read_text())['rows']
    native = json.loads((ROOT / a.native_summary).read_text())
    if len(rows) != 135 or not all(0 <= r['best'] <= 31 for r in rows.values()):
        raise ValueError('Expected current 135-condition five-bit map')
    contract=tomllib.loads((ROOT/'verification/contracts/pll_lock_screen.toml').read_text())
    engineering={}
    observations={}
    for r in native['rows']:
        if r['state']!='measured':
            continue
        raw=ROOT/r['run']/'loop.raw';w=spice.Waves(raw)
        refs=clock.edges(w.t,w['v(ref)']-w['v(ref)'].max()/2)
        fb=clock.edges(w.t,w['v(fb0)']-w['v(fb0)'].max()/2)
        engineering[r['point']+':'+r['variant']]=dict(
            raw=identity(str(raw.relative_to(ROOT))),
            result=pll_lock.screen(refs,fb,start=55e-9,stop=float(w.t[-1]),period=4e-9,
                window_cycles=contract['reference_window_cycles'],stride_cycles=contract['window_stride_cycles'],
                frequency_tolerance=contract['maximum_relative_frequency_error'],
                phase_span=contract['maximum_unwrapped_phase_span_s'],hold=contract['required_hold_time_s']))
        mask=w.t>=w.t[-1]-20e-9
        observations[r['point']+':'+r['variant']]=dict(
            actual_start_s=float(w.t[0]),actual_end_s=float(w.t[-1]),
            last20ns_b0=clock.period_stats(w.t,w['v(b0p)']-w['v(b0n)'],start=float(w.t[-1]-20e-9),stop=float(w.t[-1])),
            last20ns_ctrl_min_v=float(w['v(ctrl)'][mask].min()),
            last20ns_ctrl_max_v=float(w['v(ctrl)'][mask].max()),
            last20ns_ctrl_mean_v=float(w['v(ctrl)'][mask].mean()),
            elapsed_s=json.loads((raw.parent/'execution.json').read_text())['elapsed_s'])
        fig,axs=plt.subplots(2,1,figsize=(8,5),sharex=True,layout='constrained')
        axs[0].plot(w.t*1e9,w['v(ctrl)'],label='Vctrl',lw=1)
        axs[0].plot(w.t*1e9,w['v(z)'],label='LF integrator',lw=1)
        axs[0].axhline(r['vctrl_model_v'],color='grey',ls='--',lw=.8,label='map estimate')
        axs[0].set_ylabel('Voltage (V)');axs[0].legend(fontsize=8)
        er=clock.edges(w.t,w['v(b0p)']-w['v(b0n)'])
        axs[1].plot((er[8:]+er[:-8])*.5e9,8/(er[8:]-er[:-8])/1e9,lw=1)
        axs[1].axhline(2,color='grey',ls='--',lw=.8)
        axs[1].set(xlabel='Time (ns)',ylabel='b0 frequency (GHz)',title='8-cycle mean; noiseless short pilot')
        for ax in axs:
            ax.axvline(50,color='#aaa',lw=.8);ax.axvline(52,color='#aaa',ls=':',lw=.8);ax.grid(alpha=.2)
        fig.suptitle('r6 TT, code9, external quiet rail; insufficient lock-hold record')
        folder=ROOT/'docs/figures/clocking/pll/core';folder.mkdir(parents=True,exist_ok=True)
        fig.savefig(folder/f'r6_native_{r["name"]}_pilot.png',dpi=160);plt.close(fig)
    old_check={}
    old=json.loads((ROOT/'docs/data/native_pll_cost.json').read_text())
    for variant in ('ext','hv'):
        path=spice.case_output(ROOT/old['source']/f'tt_v1800_t27_tt_{variant}','run','loop.raw',1.5e-6)
        if path is None:raise ValueError('Missing explicit historical cross-check')
        w=spice.Waves(path)
        ref=clock.edges(w.t,w['v(ref)']-w['v(ref)'].max()/2)
        fb=clock.edges(w.t,w['v(fb0)']-w['v(fb0)'].max()/2)
        check=pll_lock.screen(ref,fb,start=55e-9,stop=float(w.t[-1]),period=4e-9)
        old_check[variant]=dict(raw=identity(str(path.relative_to(ROOT))),result=check,
            scope='offline measurement cross-check of historical r5 TT only; not new r6 qualification')
    f = np.geomspace(1e4, 1e9, 5001)
    sensitivity = []
    for delay in (1e-9, 2e-9, 3e-9):
        for cf in (.2e-12, .5e-12, .7e-12, 1e-12):
            points = []
            for name, r in rows.items():
                lp = pnoise.Loop(icp=200e-6, rz=4130, ci=18e-12, cf=cf,
                                 kvco=r['kvco'], n=8, delay=delay)
                crossings = feedback.unity_crossings(f, lp.open_loop(f))
                if len(crossings) != 1 or crossings[0]['direction'] != 'down':
                    raise ValueError('Unexpected loop crossing: ' + name)
                x = crossings[0]
                points.append(dict(point=name, code=r['best'], kvco_hz_v=r['kvco'],
                                   pm_deg=x['pm_deg'], ugb_hz=x['hz']))
            sensitivity.append(dict(cf_f=cf, delay_s=delay,
                worst_pm=min(points, key=lambda p:p['pm_deg']),
                pm_max_deg=max(p['pm_deg'] for p in points),
                ugb_max_hz=max(p['ugb_hz'] for p in points)))
    points = ('tt_v1800_t27:tt', 'fs_v1650_t85:hh', 'ss_v1650_t-40:hh', 'sf_v1650_t-40:ll')
    result = dict(report='docs/design/r6_mainline_review.md', inputs=[identity(p) for p in paths],
        scope='M1 short native pilot; M2/M4 source inventory; nominal-R/C/I sensitivity using135 best-code Kvco values. Not full PVT, TX eye, measured control admittance, noise or MC qualification.',
        map_conditions=len(rows), kvco_min_hz_v=min(r['kvco'] for r in rows.values()),
        kvco_max_hz_v=max(r['kvco'] for r in rows.values()),
        planned_points={p:rows[p] for p in points}, native=native, engineering_lock=engineering,
        short_observations=observations,historical_measurement_crosscheck=old_check,
        model_assumptions=dict(icp_a=200e-6, rz_ohm=4130, ci_f=18e-12, n=8,
            cf='hypothetical control shunt, not current r6 measurement',
            delay='hypothetical effective delay, not measured sampling/transport delay',
            pvt='only best-code Kvco varies; CP/LF PVT, usable-code variation, nonlinearities and noise excluded'),
        sensitivity=sensitivity)
    out = ROOT / 'results/analog/pll/top/mainline_review' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out.mkdir(parents=True, exist_ok=False)
    (out/'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    (ROOT/'docs/data/r6_mainline_review.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    fig, ax = plt.subplots(figsize=(7,4), layout='constrained')
    for delay in (1e-9,2e-9,3e-9):
        rs = [r for r in sensitivity if r['delay_s']==delay]
        ax.plot([r['cf_f']*1e12 for r in rs], [r['worst_pm']['pm_deg'] for r in rs], marker='o',label=f'delay {delay*1e9:g} ns')
    ax.set(xlabel='Assumed control shunt capacitance (pF)', ylabel='Minimum PM (deg)',
           title='r6 best-code Kvco envelope; nominal CP and LF only')
    ax.legend(); ax.grid(alpha=.2)
    folder=ROOT/'docs/figures/clocking/pll/core';folder.mkdir(parents=True,exist_ok=True)
    fig.savefig(folder/'r6_loop_sensitivity.png',dpi=160);plt.close(fig)
    (ROOT/'results/catalog/r6_mainline_review.json').write_text(json.dumps(dict(
        report=result['report'], data='docs/data/r6_mainline_review.json',
        analysis=str((out/'summary.json').relative_to(ROOT)), inputs=result['inputs'], scope=result['scope']),indent=2)+'\n')
    print(json.dumps(dict(analysis=str(out.relative_to(ROOT)), map_conditions=len(rows),
                         sensitivity=sensitivity, native=native['rows']),indent=2))


if __name__=='__main__':
    main()
