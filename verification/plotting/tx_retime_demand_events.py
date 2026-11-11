"""Recompute and plot FS extreme events without conflating reused data."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import spice
from serdes_flow.project import ROOT

ANALYSIS = ROOT / 'verification/analysis/tx_retime_demand_events.py'
DATA = ROOT / 'docs/data/tx_retime_demand_events.json'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    spec = importlib.util.spec_from_file_location('passive_events', ANALYSIS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.calculate()
    DATA.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    fs = next(c for c in result['cases'] if c['condition'] == 'fs_v1650_t85')
    camp = ROOT / fs['campaign']
    raw = spice.case_output(camp, 'run', 'waveforms.raw', 120e-9)
    if raw is None or sha(raw) != fs['hashes']['waveform_sha256']:
        raise ValueError('plotted waveform differs from verified analysis')
    w = spice.Waves(raw)
    events = [next(e for e in fs['events'] if e['output'] == 'serializer' and e['extreme'] == extreme)
              for extreme in ('earliest_edge', 'latest_edge')]
    fig, axes = plt.subplots(5, 2, figsize=(12, 9), sharex='col', layout='constrained')
    for col, event in enumerate(events):
        if event['status'] != 'observed':
            raise ValueError('event association is ungraded')
        close = event['close_s']
        mask = (w.t >= close - 250e-12) & (w.t <= close + 300e-12)
        prefix = 'xtx.xtree.xr4_0.'
        branch = event['branch'].lower()
        pairs = [(f'g3 {branch.upper()}', f'xtx.xtree.g3_{0 if branch == "a" else 1}p', f'xtx.xtree.g3_{0 if branch == "a" else 1}n'),
                 ('held', prefix + branch + 'hp', prefix + branch + 'hn'),
                 ('local clock', prefix + 's' + branch + 'p', prefix + 's' + branch + 'n'),
                 ('serializer', 'qp', 'qn'), ('pad', 'lqp', 'lqn')]
        for ax, (label, pos, neg) in zip(axes[:, col], pairs):
            ax.plot((w.t[mask] - close) * 1e12, (w[pos] - w[neg])[mask] * 1000, color='#247a8f')
            ax.axvline(0, color='#555', lw=.9)
            ax.axhline(0, color='#aaa', lw=.6)
            if event.get('g3_target_crossing_s') is not None:
                ax.axvline((event['g3_target_crossing_s'] - close) * 1e12, color='#c37836', ls='--', lw=.9)
            ax.set_ylabel(label + '\n(mV)', fontsize=8)
            ax.grid(alpha=.15)
        kind = 'new same-branch value' if event['new_branch_input'] else 'value reused from bit ' + str(event['bit'] - 2)
        axes[0, col].set_title(f'{event["extreme"]}: bit {event["bit"]}, branch {event["branch"]}\n{kind}', fontsize=10)
        axes[-1, col].set_xlabel('ps relative to actual local latch closing edge')
    fig.suptitle('FS extreme transitions: closing time and data history are separate observations', fontsize=13)
    fig.supxlabel('Gray: actual local close. Orange: unique new g3 target crossing, when present. Intervals are not measured setup/hold limits.', fontsize=9)
    figure = ROOT / 'docs/figures/tx/ingress/tx_retime_demand_events.png'
    fig.savefig(figure, dpi=170)
    plt.close(fig)
    archive = ROOT / 'results/analog/tx/retime_demand_events' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    archive.mkdir(parents=True, exist_ok=False)
    for p in (ANALYSIS, Path(__file__).resolve(), DATA):
        shutil.copyfile(p, archive / p.name)
    index = dict(data=str(DATA.relative_to(ROOT)), data_sha256=sha(DATA), figure=str(figure.relative_to(ROOT)),
                 figure_sha256=sha(figure), publisher_sha256=sha(Path(__file__).resolve()),
                 archive=str(archive.relative_to(ROOT)), scope=result['scope'],
                 sources=[{'campaign': c['campaign'], 'hashes': c['hashes']} for c in result['cases']])
    (ROOT / 'results/catalog/tx_retime_demand_events.json').write_text(json.dumps(index, indent=2) + '\n')
    print(json.dumps({'data': index['data'], 'figure': index['figure']}))


if __name__ == '__main__':
    main()
