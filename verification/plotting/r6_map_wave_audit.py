"""Publish a frozen in-flight r6 waveform audit, without updating its model."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from serdes_flow import project, spice

ROOT = project.ROOT
HERE = Path(__file__).resolve()
AUDITOR = ROOT / 'verification/analysis/r6_map_wave_audit.py'


def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p, d): p.write_text(json.dumps(d, indent=2, allow_nan=False) + '\n')


def collect(summary):
    result = read(summary); inventory = summary.parent / 'inventory.json'
    if result['status'] != 'partial_campaign_read_only_audit' or sha(inventory) != result['inventory_sha256']:
        raise ValueError('audit/inventory identity mismatch')
    if sha(summary.parent / 'pdk_manifest.json') != result['pdk_manifest_sha256']:
        raise ValueError('audit model manifest changed')
    for name, info in result['source_hashes'].items():
        frozen = summary.parent / 'execution' / Path(name).name
        if sha(frozen) != info['sha256']: raise ValueError('frozen audit source changed')
    snapshot = summary.parent / 'execution' / AUDITOR.name
    spec = importlib.util.spec_from_file_location('r6_audit_frozen_metrics', snapshot)
    auditor = importlib.util.module_from_spec(spec); spec.loader.exec_module(auditor)
    for name in ('src/serdes_flow/spice.py', 'src/serdes_flow/clock.py', 'src/serdes_flow/waves.py'):
        if sha(ROOT / name) != result['source_hashes'][name]['sha256']:
            raise ValueError('measurement runtime changed: ' + name)
    for row in result['rows']:
        if 'raw' not in row: continue
        raw = ROOT / row['raw']
        if sha(raw) != row['raw_sha256']: raise ValueError('captured raw changed: ' + str(raw))
        waves = spice.Waves(raw)
        if waves.t[-1] < 14e-9 * (1 - 1e-6): raise ValueError('truncated captured record')
        metrics = auditor.metrics(waves.t, waves['v(v0p)'] - waves['v(v0n)'])
        if any(row[k] != v for k, v in metrics.items()): raise ValueError('audit metrics do not reproduce')
        if sha(raw) != row['raw_sha256']: raise ValueError('raw changed while rereading')
    counts = Counter(r['status'] for r in result['rows'])
    if any(counts[k] != v for k, v in result['counts'].items()) or len(result['rows']) != 1620:
        raise ValueError('audit counts differ')
    skipped = [r for r in result['rows'] if r['status'] == '4_or_5_edges_reader_skips']
    measured = [r for r in result['rows'] if r.get('frequency_hz') is not None]
    screened = [r for r in result['rows'] if r.get('qualified_window')]
    return dict(status='frozen_partial_r6_measurement_audit_not_qualification',
        summary=str(summary.relative_to(ROOT)), summary_sha256=sha(summary), campaign=result['campaign'],
        inventory=str(inventory.relative_to(ROOT)), inventory_sha256=sha(inventory),
        counts=result['counts'], expected_points=1620, captured_complete_waveforms=sum('raw' in r for r in result['rows']),
        completed_waveforms_without_deck_execution_at_capture=sum('raw' in r and r.get('execution') is None for r in result['rows']),
        skipped_conditions=len({(r['condition'], r['rc']) for r in skipped}),
        skipped_frequency_range_hz=[min(r['frequency_hz'] for r in skipped), max(r['frequency_hz'] for r in skipped)] if skipped else None,
        skipped_codes=sorted({r['code'] for r in skipped}),
        skipped_by_rc=dict(Counter(r['rc'] for r in skipped)),
        max_screened_abs_drift=max(abs(r['drift_fraction']) for r in screened) if screened else None,
        examples=sorted(skipped, key=lambda r: r['frequency_hz'])[:8],
        per_rc={rc:dict(Counter(r['status'] for r in result['rows'] if r['rc']==rc)) for rc in ('tt','hh','ll')},
        scope=result['scope'], sources={str(HERE.relative_to(ROOT)):sha(HERE)})


def plot(data, rows):
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8), layout='constrained')
    positions = range(3); bottom = [0] * 3
    for status, label, color in (
        ('settled', 'Last-5ns drift screened', '#238b72'),
        ('4_or_5_edges_reader_skips', 'Complete, only 4/5 rising edges', '#d68d35'),
        ('unsettled_reader_returns_number', 'Drift exceeds reader threshold', '#bf5547'),
        ('insufficient_edges', 'Fewer than 4 edges', '#9a758c'),
        ('unavailable_or_writing', 'Unavailable / writing', '#b1bcc5'),
        ('missing', 'Not captured', '#dce1e6')):
        values = [data['per_rc'][rc].get(status,0) for rc in ('tt','hh','ll')]
        if not sum(values):continue
        axes[0].bar(positions, values, bottom=bottom, color=color, label=label)
        bottom = [a+b for a,b in zip(bottom,values)]
    axes[0].set(xticks=list(positions), xticklabels=['RC tt','RC hh','RC ll'], ylabel='Points at the frozen snapshot')
    axes[0].legend(fontsize=8, loc='upper left')
    for rc, color in (('tt','#4b79b7'),('hh','#b46a2d'),('ll','#238b72')):
        selected=[r for r in rows if r.get('frequency_hz') is not None and r['rc']==rc]
        axes[1].scatter([r['frequency_hz']/1e9 for r in selected],[r['rising_edges'] for r in selected],s=8,alpha=.35,color=color,label=rc)
    axes[1].axhline(5.5,ls='--',lw=.8,color='#555555')
    axes[1].set(xlabel='Frequency from the complete tail record (GHz)',ylabel='Rising edges in the last 5ns')
    axes[1].legend(title='RC',fontsize=8);axes[1].grid(alpha=.2)
    fig.suptitle('Frozen r6 map audit: observation window limits versus absent data')
    fig.supxlabel('Snapshot coverage only; complete waveforms from running decks are included separately. Low-cycle frequencies are descriptive, not newly accepted steady-state points.',fontsize=8)
    return fig


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--summary',required=True,type=Path);a=p.parse_args()
    summary=a.summary.resolve();data=collect(summary)
    snap=summary.parent/'publication_sources'/sha(HERE);snap.mkdir(parents=True,exist_ok=True)
    if not (snap/HERE.name).exists():shutil.copyfile(HERE,snap/HERE.name)
    figure=ROOT/'docs/figures/clocking/vco/r6_map_wave_audit.png'
    fig=plot(data,read(summary)['rows']);fig.savefig(figure,dpi=170,bbox_inches='tight',pad_inches=.15);plt.close(fig)
    data['figures']={str(figure.relative_to(ROOT)):sha(figure)}
    output=ROOT/'docs/data/r6_map_wave_audit.json';dump(output,data)
    dump(ROOT/'results/catalog/r6_map_wave_audit.json',dict(data=str(output.relative_to(ROOT)),data_sha256=sha(output),
        summary=data['summary'],summary_sha256=data['summary_sha256'],figures=data['figures'],status=data['status']))
    print(output)


if __name__=='__main__':main()
