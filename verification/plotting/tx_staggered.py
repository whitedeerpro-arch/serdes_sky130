"""Collect existing staggered-ingress results and draw an offline timing card.

uv run python verification/plotting/tx_staggered.py --collect CAMPAIGN [--collect CAMPAIGN]
uv run python verification/plotting/tx_staggered.py
No simulations are run and campaign files are never modified.
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import loading, spice
from serdes_flow.project import ROOT
from serdes_flow.corners import Condition

DATA = ROOT / 'docs/data/tx_staggered_ingress.json'
FIGURE = ROOT / 'docs/figures/tx/ingress/tx_staggered_hold_timing.png'
CATALOG = ROOT / 'results/catalog/tx_staggered_ingress.json'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def ref(path):
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def snapshot(w, mode, metrics):
    # Word 0 -> 1: lane 8 changes while B is selected.
    edge = metrics['words'][0]['lanes'][8]['selected_from_s']
    start, end = edge - .6e-9, edge + 3e-9
    keep = (w.t >= start) & (w.t <= end)
    t = w.t[keep]
    if len(t) < 2 or t[0] > start + .01e-9 or t[-1] < end - .01e-9:
        raise ValueError('TT waveform does not cover the plotting interval')
    # Uniform interpolation preserves transitions at 2 ps resolution in small JSON.
    sample = np.linspace(t[0], t[-1], int(np.ceil((t[-1]-t[0])/2e-12))+1)
    vdd = w['vdd'][keep]
    if 'sp' in w and 'sn' in w:
        select = (w['sp'] - w['sn'])[keep]
        origin = 'saved sp-sn'
    elif mode == 'ideal':
        # Legacy deck: Bsp=vdd-.35+.2*ck_u, Bsn=vdd-.15-.2*ck_u,
        # Bclock=vdd*ck_u. This is reconstructed, not a saved vector.
        select = -.2 + .4 * w['clk'][keep] / vdd
        origin = 'reconstructed from legacy ideal deck and saved clk/vdd'
    else:
        raise ValueError('receiver waveform lacks sp/sn')
    signals = {'select_v': select, 'clk_v': w['clk'][keep],
               'clk_b_v': w['xcap.clk_b'][keep], 'h8_v': w['xcap.h8'][keep],
               'q8_v': w['q8'][keep], 'lane8_cml_v': (w['c8p'] - w['c8n'])[keep]}
    return dict(condition='tt_v1800_t27', clock_mode=mode, select_origin=origin,
                time_ns=(sample * 1e9).round(6).tolist(),
                **{k: np.interp(sample, t, v).round(7).tolist() for k, v in signals.items()})


def collect(campaigns):
    sources, candidates = [], []
    for camp in campaigns:
        camp = camp.resolve()
        plan_path, summary_path = camp / 'plan.json', camp / 'summary.json'
        plan = json.loads(plan_path.read_text())
        summary = json.loads(summary_path.read_text())
        mode = plan.get('clock_mode', 'ideal')
        summary_mode = summary.get('clock_mode', 'ideal')
        if mode != summary_mode:
            raise ValueError(f'{camp}: plan/summary clock mode mismatch')
        planned = plan['conditions']
        reported = [row['condition'] for row in summary['rows']]
        if (len(planned) != len(set(planned)) or len(reported) != len(set(reported))
                or len(planned) != len(reported) or set(planned) != set(reported)):
            raise ValueError(f'{camp}: plan/summary conditions differ or contain duplicates')
        stop = float(plan['stop_s'])
        if not np.isfinite(stop) or stop < 36e-9 * (1 - 1e-9):
            raise ValueError(f'{camp}: invalid transient stop')
        rows = []
        for row in summary['rows']:
            item = {'condition': row['condition'], 'status': row['status']}
            if row['status'] == 'measured':
                path = ROOT / row['waveform']
                w = spice.Waves(path)  # validates finite values and strictly increasing time
                if len(w.t) == 0 or w.t[-1] < stop * (1 - 1e-6):
                    raise ValueError(f'{path}: incomplete transient')
                item.update(waveform={'path': ref(path), 'sha256': sha(path)}, metrics=row['metrics'])
                if mode == 'receiver':
                    warmup = float(plan.get('warmup_s', 0))
                    vdd = float(np.mean(w['vdd']))
                    port = loading.rising_edge_load(w.t, w['clk'], w['i(vclock_sense)'],
                                                    0, vdd, warmup+4e-9, warmup+35e-9)
                    if len(port) != 8:
                        raise ValueError('need eight clock port observations')
                    item['clock_port'] = dict(status='ungraded', measurements=port,
                                             definition='signed input charge/VDD within midpoint +/-400ps; not extracted capacitance')
                if row['condition'] == 'tt_v1800_t27':
                    candidates.append(snapshot(w, mode, row['metrics']))
            elif row['status'] == 'analysis_error':
                if 'error' in row:
                    item['error'] = row['error']
                condition = Condition.parse(row['condition'])
                path = spice.case_output(camp, condition.process, row['condition'] + '.raw', stop)
                if path is not None:
                    w = spice.Waves(path)
                    item['waveform'] = {'path': ref(path), 'sha256': sha(path),
                                        'end_s': float(w.t[-1])}
            elif 'error' in row:
                item['error'] = row['error']
            rows.append(item)
        sources.append({'campaign': ref(camp), 'clock_mode': mode, 'scope': summary['scope'],
                        'plan': {'path': ref(plan_path), 'sha256': sha(plan_path)},
                        'summary': {'path': ref(summary_path), 'sha256': sha(summary_path)},
                        'planned_conditions': plan['conditions'], 'rows': rows})
    if not candidates:
        raise ValueError('no complete measured TT waveform available for timing plot')
    timing = next((x for x in candidates if x['clock_mode'] == 'receiver'), candidates[0])
    analysis = [Path(__file__).resolve()] + [ROOT/'src/serdes_flow'/x for x in ('loading.py', 'clock.py', 'waves.py', 'spice.py')]
    data = {'analysis_sources': [{'path': ref(p), 'sha256': sha(p)} for p in analysis],
            'scope': 'Six stress conditions per campaign; local first mux only; not 45-PVT qualification. Crossing separation is not aperture margin.',
            'campaigns': sources, 'timing': timing}
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps({'data': ref(DATA), 'figure': ref(FIGURE),
                                   'campaigns': [s['campaign'] for s in sources],
                                   'measured_rows': [sum(r['status'] == 'measured' for r in s['rows']) for s in sources]},
                                  indent=2, allow_nan=False) + '\n')
    return data


def plot(data):
    plt.rcParams.update({'font.family': 'Noto Sans CJK JP', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    d = data['timing']
    t = np.asarray(d['time_ns'])
    sel = np.asarray(d['select_v'])
    fig, axes = plt.subplots(4, 1, figsize=(11, 8), sharex=True)
    fig.subplots_adjust(left=.08, right=.98, bottom=.11, top=.92, hspace=.16)
    series = [(('select_v', 'sp − sn', '#7354a5'),),
              (('clk_v', 'clk', '#3075a0'), ('clk_b_v', 'clk_b', '#e09534')),
              (('h8_v', 'h8：新数据', '#d45c43'), ('q8_v', 'q8：保持旧字', '#28876b')),
              (('lane8_cml_v', 'lane 8：c8p − c8n', '#7354a5'),)]
    for ax, group in zip(axes, series):
        ax.fill_between(t, 0, 1, where=sel > 0, transform=ax.get_xaxis_transform(),
                        color='#dcefe5', alpha=.8, step='mid', label='B 选中')
        for key, label, color in group:
            ax.plot(t, d[key], color=color, lw=1.8, label=label)
        ax.axhline(0, color='black', lw=.5, alpha=.4)
        ax.set_ylabel('电压 / V')
        ax.grid(alpha=.18)
        ax.legend(loc='upper right', ncol=3, fontsize=9)
    axes[-1].set_xlabel('时间 / ns')
    mode = '实际接收器' if d['clock_mode'] == 'receiver' else '理想匹配时钟'
    origin = '实存 sp − sn' if d['select_origin'] == 'saved sp-sn' else 'sp − sn 按理想源定义及实存 clk 重建'
    fig.suptitle(f'TX 分组保持：跨字时 B 组维持旧数据（TT，{mode}）', fontsize=14, fontweight='bold')
    fig.text(.08, .018, f'{origin}；绿色区为 B 选中。局部首级 MUX 测试，非完整串化或 45 PVT 签核。', fontsize=9)
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE, dpi=160)
    fig.savefig(FIGURE.with_suffix('.svg'))
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect', type=Path, action='append', metavar='CAMPAIGN')
    args = parser.parse_args()
    result = collect(args.collect) if args.collect else json.loads(DATA.read_text())
    plot(result)
    print(ref(DATA), ref(FIGURE))
