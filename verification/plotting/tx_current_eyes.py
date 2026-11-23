"""Render current full-TX TT/FS eyes from explicit, validated MOS45 records."""
import hashlib
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import project, spice

ROOT = project.ROOT
SELF = Path(__file__).resolve()
COLLECTOR = SELF.with_name('tx_parallel_serializer.py')
INDEX = ROOT / 'docs/data/tx_full_pvt45.json'
FIGURE = ROOT / 'docs/figures/tx/ingress/tx_current_eyes.png'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    spec = importlib.util.spec_from_file_location('current_eye_collector', COLLECTOR)
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    index = json.loads(INDEX.read_text())
    if index['clock'] != [5, 16, 240] or index['driver_params'] != 'rpre=120 wout=192 wtpre=60':
        raise ValueError('Current TX configuration changed; review plotting inputs')
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.5), sharex=True, sharey=True, layout='constrained')
    cases = []
    x = np.linspace(-.5, 1.5, 321)
    nodes = [('serializer', 'qp', 'qn'), ('pad', 'lqp', 'lqn'), ('remote', 'lrp', 'lrn')]
    for rownum, (tag, title) in enumerate([
        ('tt_v1800_t27', 'TT / 1.80 V / 27 C'), ('fs_v1650_t85', 'FS / 1.65 V / 85 C')
    ]):
        row = next(r for r in index['rows'] if r['condition'] == tag)
        camp = ROOT / row['run']
        if sha(camp / 'summary.json') != row['summary_sha256']:
            raise ValueError('Indexed summary changed')
        case = collector.collect(camp)
        wave = spice.Waves(ROOT / case['waveform'])
        for col, (label, p, n) in enumerate(nodes):
            ax = axes[rownum, col]
            metrics = case['outputs'][label]['check']
            traces = []
            for bit in range(64, 64 + metrics['payload_bits']):
                times = case['sequence_start_s'] + (bit + metrics['training_delay_ui'] + x) * 250e-12
                if times[0] < wave.t[0] or times[-1] > wave.t[-1]:
                    raise ValueError('Eye trace outside recorded waveform')
                traces.append(np.interp(times, wave.t, wave[p] - wave[n]) * 1000)
            ax.plot(x, np.asarray(traces).T, color='#096eae', alpha=.10, lw=.65)
            ax.axvline(.5, color='#555555', lw=.7, ls=':')
            for level in (-75, 75):
                ax.axhline(level, color='#b76438', lw=.65, ls='--', alpha=.7)
            ax.grid(alpha=.15)
            scope = 'comparison' if label == 'remote' else 'gate'
            ax.set_title(f'{title}\n{label.capitalize()} ({scope})', fontsize=10)
            ax.text(.03, .97, f"Margin {metrics['minimum_signed_margin_v'] * 1000:.1f} mV\nSpread {metrics['transition_spread_ui']:.3f} UI",
                    transform=ax.transAxes, va='top', fontsize=9,
                    bbox=dict(facecolor='white', edgecolor='none', alpha=.85))
            ax.set(xlim=(-.5, 1.5), ylim=(-300, 300), xticks=[-.5, 0, .5, 1, 1.5])
            if rownum == 1:
                ax.set_xlabel('Time (UI); 1 UI = 250 ps')
            if col == 0:
                ax.set_ylabel('Differential voltage (mV)')
        cases.append(case)
    fig.suptitle('Current full TX: 4 Gb/s payload eyes\nIdeal 2 GHz source; 256 bits; PDK R tt; noiseless transient; training-only alignment', fontsize=12)
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE, dpi=180)
    plt.close(fig)
    result = dict(scope='Existing current complete TX extra5/WT16/R240, driver120/60/192; ideal2GHz, PDK Rtt,256bits,noiseless; not r6 native-PLL-driven dynamic qualification',
                  input_index=dict(path=str(INDEX.relative_to(ROOT)), sha256=sha(INDEX)),
                  sources={str(p.relative_to(ROOT)): sha(p) for p in (SELF, COLLECTOR)},
                  figure=str(FIGURE.relative_to(ROOT)), cases=cases)
    (ROOT / 'docs/data/tx_current_eyes.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(FIGURE)


if __name__ == '__main__':
    main()
