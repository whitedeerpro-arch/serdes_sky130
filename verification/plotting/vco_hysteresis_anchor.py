"""Publish the explicit 38 C static calibration, preserving its measured boundaries."""
import argparse
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from serdes_flow.project import ROOT

RUNNER = ROOT / 'analog/pll/vco/tb/tuning/hysteresis_anchor.py'
spec = importlib.util.spec_from_file_location('vco_anchor_runner', RUNNER)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def collect(summary):
    camp = summary.parents[2]
    plan = r.verify(camp)
    data = json.loads(summary.read_text())
    paths = r.checked_cases(camp)
    inputs = {str(p.relative_to(ROOT)): r.sha(p) for p in (summary, camp / 'plan.json', RUNNER, Path(__file__).resolve())}
    for row in data['points']:
        path = ROOT / row['path']
        c = r.C
        if path != paths[r.wm.name(c, row['code'], row['vctrl'])]:
            raise ValueError('selected raw differs from the campaign')
        measured = r.wm.measure(path)
        if measured != (row['frequency_hz'], row['swing_v']):
            raise ValueError('frequency/swing differs from raw')
        ex_path = path.parent / 'execution.json'
        ex = json.loads(ex_path.read_text())
        if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256'] != r.sha(path.parent / 'tb.cir'):
            raise ValueError('calibration run did not complete cleanly')
        for p in (path, ex_path, path.parent / 'tb.cir'):
            inputs[str(p.relative_to(ROOT))] = r.sha(p)
    for code in ('0', '1'):
        if r.crossing([x for x in data['points'] if str(x['code']) == code]) != data['crossings'][code]:
            raise ValueError('crossing differs from measured points')
    if plan['model_sha256'] != data['model_report_sha256']:
        raise ValueError('model identity differs')
    if data['h4_code1_opposite_room_v'] != 1.21 - data['crossings']['1']['vctrl']:
        raise ValueError('distance differs from measured crossing')
    return dict(spec_status='ungraded', calibration=data, inputs_sha256=inputs,
                warning='38 C is a calibration point, not an observed switching temperature. Errors include coarse voltage-grid and temperature interpolation. Independent static codes do not demonstrate dynamic switching.')


def plot(data):
    x = data['calibration']
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.5), layout='constrained')
    for ax, code in zip(axes, ('0', '1')):
        rows = [v for v in x['points'] if str(v['code']) == code]
        ax.plot([v['vctrl'] for v in rows], [v['frequency_hz'] / 1e9 for v in rows], 'o-', label='Measured points / straight segments')
        ax.axhline(2, color='black', linestyle=':', linewidth=1)
        ax.axvline(x['model_at_38_vctrl'][code], color='C1', linestyle='--', label='Old interpolated lock voltage')
        ax.scatter([x['crossings'][code]['vctrl']], [2], marker='x', s=65, color='C2', label='Measured-bracket crossing')
        ax.set(title=f'VCO code K={code}: error {x["measured_minus_model_vctrl"][code]*1e3:+.2f} mV',
               xlabel='Vctrl (V)', ylabel='Frequency (GHz)')
        ax.grid(alpha=.2)
    axes[0].axvline(.90, color='gray', linestyle=':', linewidth=1)
    axes[1].axvline(1.21, color='gray', linestyle=':', linewidth=1)
    axes[1].annotate('', xy=(1.21, 2), xytext=(x['crossings']['1']['vctrl'], 2), arrowprops=dict(arrowstyle='<->', color='C3'))
    axes[1].text(1.16, 2.008, '105.28 mV to H=4', ha='center', color='C3', fontsize=8)
    axes[0].legend(fontsize=7, loc='upper left')
    fig.suptitle('4-bit VCO static calibration: FS / 1.65 V / hh / 38 C\nReal bias; 30 fF per leg; independent fixed codes, no dynamic switching', fontsize=11)
    dest = ROOT / 'docs/figures/clocking/vco/vco_hysteresis_static_anchor'
    for ext in ('png', 'svg'): fig.savefig(dest.with_suffix('.' + ext), dpi=180)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--summary', type=Path, required=True)
    a = ap.parse_args()
    data = collect(a.summary.resolve())
    text = json.dumps(data, indent=2, allow_nan=False) + '\n'
    for path in (ROOT / 'docs/data/vco_hysteresis_anchor.json', ROOT / 'results/catalog/vco_hysteresis_anchor.json'):
        path.write_text(text)
    plot(data)
    print(data['calibration']['measured_minus_model_vctrl'])


if __name__ == '__main__': main()
