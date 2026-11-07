#!/usr/bin/env python3
"""Render archived guard timing; --collect independently parses fixed STA logs."""
import argparse
import hashlib
import json
from pathlib import Path
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow.project import ROOT

CAMP = ROOT / 'results/digital/tx/ingress_timing/20261107T052347Z'
DATA = ROOT / 'docs/data/tx_ingress_timing.json'
CAT = ROOT / 'results/catalog/tx_ingress_timing_plot.json'
FIG = ROOT / 'docs/figures/tx/ingress/tx_ingress_timing_feasibility'
CORNERS = ['tt_025C_1v80', 'ss_n40C_1v60', 'ss_100C_1v60', 'ff_n40C_1v95']
LABELS = ['TT\n25°C 1.80 V', 'SS\n−40°C 1.60 V', 'SS\n100°C 1.60 V', 'FF\n−40°C 1.95 V']
MAPPINGS = ['baseline', 'strength2', 'strength4', 'outputbuf']


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def paths(section):
    rows = []
    for part in re.split(r'(?=^Startpoint: )', section, flags=re.M):
        start = re.search(r'^Startpoint:\s+(\S+)', part, re.M)
        end = re.search(r'^Endpoint:\s+(\S+)', part, re.M)
        slack = re.search(r'^\s*([-+]?\d+\.\d+)\s+slack \((?:MET|VIOLATED)\)', part, re.M)
        if start and end and slack:
            rows.append(dict(startpoint=start.group(1), endpoint=end.group(1), slack_ns=float(slack.group(1))))
    if not rows:
        raise ValueError('no complete timing paths in section')
    return min(rows, key=lambda x: x['slack_ns'])


def collect():
    summary_path = CAMP / 'summary.json'
    summary = json.loads(summary_path.read_text())
    if summary['status'] != 'complete_ungraded':
        raise ValueError('campaign is not complete_ungraded')
    cases = []
    for corner in CORNERS:
        for mapping in MAPPINGS:
            selected = [x for x in summary['cases'] if x['corner'] == corner and x['mapping'] == mapping and x['load_ff'] == 10]
            if len(selected) != 1:
                raise ValueError(f'expected one case for {corner} {mapping}')
            case = selected[0]
            expected_name = f'{mapping}_{corner}_10ff.log'
            if case['report'] != expected_name:
                raise ValueError(f'unexpected report {case["report"]}')
            report = CAMP / expected_name
            text = report.read_text()
            setup = text.split('--- SETUP PATHS ---', 1)[1].split('--- HOLD PATHS ---', 1)[0]
            hold = text.split('--- HOLD PATHS ---', 1)[1].split('--- UNCONSTRAINED ---', 1)[0]
            parsed = {'setup': paths(setup), 'hold': paths(hold)}
            for kind in ('setup', 'hold'):
                if parsed[kind] != case[kind + '_worst']:
                    raise ValueError(f'{expected_name}: {kind} disagrees with summary')
            warning = [line.strip() for line in text.splitlines() if 'default_operating_condition' in line]
            cases.append(dict(corner=corner, mapping=mapping, load_ff=10, **parsed,
                              report=str(report.relative_to(ROOT)), report_sha256=sha(report),
                              default_operating_condition_warnings=warning))
    data = dict(campaign=str(CAMP.relative_to(ROOT)), summary_sha256=sha(summary_path),
                analysis_source=dict(path=str(Path(__file__).resolve().relative_to(ROOT)),sha256=sha(Path(__file__))),
                scope='Exploratory and ungraded; 4 ns clock, provisional external setup 0.5 ns and tag 1.3 ns budgets; 10 fF per output. SS 1.60 V libraries do not represent 1.65 V specification; four libraries do not cover 45 PVT.',
                warnings='OpenSTA reports default_operating_condition not found; interpretation remains unresolved. Max capacitance rule checking is unknown. No extracted analog interface, parasitics, CDC, blanking, reset recovery/removal, or signoff.', cases=cases)
    DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    CAT.write_text(json.dumps(dict(campaign=data['campaign'], summary_sha256=data['summary_sha256'], reports=[dict(path=x['report'], sha256=x['report_sha256']) for x in cases], scope=data['scope'], warnings=data['warnings']), indent=2, ensure_ascii=False) + '\n')
    return data


def plot(data):
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    x = np.arange(len(CORNERS)); width = .19
    colors = ['#356b8c', '#46a18d', '#cb9344', '#9c6ba3']
    for ax, kind in zip(axes, ('setup', 'hold')):
        for j, mapping in enumerate(MAPPINGS):
            values = [next(c[kind]['slack_ns'] for c in data['cases'] if c['corner'] == corner and c['mapping'] == mapping) for corner in CORNERS]
            bars = ax.bar(x + (j - 1.5)*width, values, width, label=mapping, color=colors[j])
            ax.bar_label(bars, labels=[f'{v:+.3f}' for v in values], padding=3, fontsize=7, rotation=90)
        ax.axhline(0, color='#bd3333', lw=1.3)
        ax.set_ylabel('Minimum slack (ns)')
        ax.set_title(f'{kind.capitalize()} paths', loc='left', fontweight='bold')
        ax.grid(axis='y', alpha=.2); ax.set_axisbelow(True)
        ax.margins(y=.3)
    axes[0].legend(ncol=4, loc='upper center', fontsize=9)
    axes[1].set_xticks(x, LABELS)
    fig.suptitle('TX ingress guard mapping: 10 fF timing feasibility', fontsize=15)
    fig.subplots_adjust(left=.08, right=.98, top=.91, bottom=.18, hspace=.18)
    fig.text(.5, .025, 'Ungraded · 4 ns clock · provisional 0.5 ns external setup / 1.3 ns tag budgets\nDefault operating condition warning unresolved; max-capacitance check unknown · four libraries, not 45 PVT', ha='center', fontsize=8)
    FIG.parent.mkdir(parents=True, exist_ok=True)
    for ext in ('png', 'svg'):
        fig.savefig(FIG.with_suffix('.' + ext), dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect', action='store_true', help='refresh data from fixed campaign reports')
    args = parser.parse_args()
    data = collect() if args.collect else json.loads(DATA.read_text())
    plot(data)
    print(f'Plotted {len(data["cases"])} cases')


if __name__ == '__main__': main()
