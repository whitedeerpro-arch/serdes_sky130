"""Publish measured-anchor adjacent-code landing evidence, without simulation."""
import argparse
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from serdes_flow.project import ROOT

ANALYSER = ROOT / 'verification/analysis/vco_recode_evidence.py'
spec = importlib.util.spec_from_file_location('recode_evidence', ANALYSER)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)
sha = model.windows.sha


def collect(path):
    report = json.loads(path.read_text())
    source, fill = ((ROOT / report[k]).resolve() for k in ('source_path', 'fill_path'))
    static = model.windows.analyse(json.loads(source.read_text()), json.loads(fill.read_text()),
                                   sha(source), sha(fill), report['source_path'], report['fill_path'])
    if report != model.analyse(static, report['margin_v']):
        raise ValueError('report differs from current input and model; recompute to a new path')
    events = {}
    for upper in model.windows.DROPS:
        events[upper] = [dict(chip=chip, old_code=s['code'], temperature_interval=s['temperature'], **e)
                         for chip, rows in report['chips'].items() for s in rows[upper]['segments']
                         for e in s.get('crossings', [])]
    return dict(spec_status='ungraded', scope=report['scope'], model=report['model'],
                warning='Only 172 of 1440 code/temperature segments have measured crossings at both temperature anchors. Minima cover observed model events only; no global or dynamic guarantee.',
                margin_assumption_v=report['margin_v'], boundary_summary=report['boundary_summary'], events=events,
                inputs_sha256={str(p.relative_to(ROOT)): sha(p) for p in (path, source, fill, ANALYSER, Path(model.windows.__file__), Path(__file__).resolve())})


def plot(data):
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6), sharex=True, sharey=True, layout='constrained')
    for ax, (code, events) in zip(axes, data['events'].items()):
        for edge, marker in (('upper', 'o'), ('lower', '^')):
            rows = [e for e in events if e['edge'] == edge and 'opposite_edge_room_v' in e]
            ax.scatter([e['temperature'] for e in rows], [e['opposite_edge_room_v'] * 1e3 for e in rows],
                       marker=marker, s=25, label='K - 1 at upper edge' if edge == 'upper' else 'K + 1 at lower edge')
        summary = data['boundary_summary'][code]
        minimum = summary['minimum_opposite_room_event']
        ax.axhline(data['margin_assumption_v'] * 1e3, color='black', linestyle='--', linewidth=1, label='20 mV static assumption')
        ax.set_title(f'Upper threshold H={code}\n{summary["landing_evidenced"]}/{summary["events"]} landings evidenced; min {minimum["opposite_edge_room_v"]*1e3:.1f} mV', fontsize=10)
        ax.set(xlabel='Boundary crossing temperature (C)', xticks=[-40, 0, 27, 50, 85], ylim=(0, None))
        ax.grid(alpha=.2)
    axes[0].set_ylabel('Distance after switching to the opposite threshold (mV)')
    axes[1].legend(fontsize=7, loc='upper left')
    fig.suptitle('4-bit VCO hysteresis: adjacent-code landing under a piecewise-linear temperature model\n'
                 'Ideal thresholds; measured anchors in 172/1440 code-temperature segments; dynamic and mismatch budgets excluded', fontsize=11)
    dest = ROOT / 'docs/figures/clocking/vco/vco_hysteresis_landing'
    for ext in ('png', 'svg'): fig.savefig(dest.with_suffix('.' + ext), dpi=180)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--report', type=Path, required=True)
    a = ap.parse_args()
    data = collect(a.report.resolve())
    text = json.dumps(data, indent=2, allow_nan=False) + '\n'
    for dest in (ROOT / 'docs/data/vco_hysteresis.json', ROOT / 'results/catalog/vco_hysteresis.json'):
        dest.write_text(text)
    plot(data)
    print(json.dumps(data['boundary_summary']))


if __name__ == '__main__': main()
