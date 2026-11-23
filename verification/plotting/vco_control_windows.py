"""Publish an explicit bracketed VCO analysis; never start simulation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm

from serdes_flow.project import ROOT

ANALYSER = ROOT / 'verification/analysis/vco_control_windows.py'
spec = importlib.util.spec_from_file_location('control_window_analysis', ANALYSER)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bracket_containment(result):
    """Separate interpolated positions from whole measured brackets in the window."""
    out = {}
    for upper in model.DROPS:
        rows = {}
        for condition, row in result['conditions'].items():
            w = row['windows'][upper]
            codes = [k for k in w['candidates'] if any(
                x['kvco_hz_per_v'] > 0 and min(x['bracket_v']) >= w['vlo'] and max(x['bracket_v']) <= w['vhi']
                for x in row['curves'][str(k)]['crossings'])]
            rows[condition] = dict(whole_bracket_codes=codes, needs_boundary_confirmation=not bool(codes))
        out[upper] = dict(conditions_with_whole_bracket=sum(bool(r['whole_bracket_codes']) for r in rows.values()),
                          needs_boundary_confirmation=sum(r['needs_boundary_confirmation'] for r in rows.values()), conditions=rows)
    return out


def collect(path):
    result = json.loads(path.read_text())
    source, fill = ((ROOT / result[k]).resolve() for k in ('source_path', 'fill_path'))
    expected = model.analyse(json.loads(source.read_text()), json.loads(fill.read_text()),
                             sha(source), sha(fill), result['source_path'], result['fill_path'])
    if expected != result:
        raise ValueError('analysis differs from source/fill or current analyser; recompute to a new path')
    return dict(spec_status='ungraded', analysis=result, bracket_containment=bracket_containment(result),
                warning='Candidate positions use linear interpolation. A bracket crossing a window boundary needs an actual boundary-frequency check; 38 C calibration found a 22 mV position difference for one code.',
                inputs_sha256={str(p.relative_to(ROOT)): sha(p) for p in (path, source, fill, ANALYSER, Path(__file__).resolve())})


def plot(data, dest):
    result = data['analysis']
    processes, supplies, resistors, temps = ('tt', 'ss', 'ff', 'sf', 'fs'), (1650, 1800, 1950), ('tt', 'hh', 'll'), (-40, 27, 85)
    rows = [(p, v) for p in processes for v in supplies]
    labels = [f'{p.upper()}  {v/1000:.2f} V' for p, v in rows]
    top, bottom = [], []
    for code in model.DROPS:
        top.append(np.array([[len(result['conditions'][f'{p}_v{v}_t{t}:{r}']['windows'][code]['candidates'])
                              for r in resistors for t in temps] for p, v in rows]))
        bottom.append(np.array([[len(result['fixed_three_temperature'][f'{p}_v{v}:{r}'][code]['codes'])
                                 for r in resistors] for p, v in rows]))
    vmax = max(int(x.max()) for x in top + bottom)
    cmap = plt.get_cmap('YlGnBu', vmax + 1)
    norm = BoundaryNorm(np.arange(-.5, vmax + 1.5), cmap.N)
    fig, axes = plt.subplots(2, 3, figsize=(14.5, 10), layout='constrained')
    for j, code in enumerate(model.DROPS):
        for i, matrix in enumerate((top[j], bottom[j])):
            ax = axes[i, j]
            im = ax.imshow(matrix, cmap=cmap, norm=norm, aspect='auto')
            ax.set_yticks(range(len(rows)), labels, fontsize=8)
            ax.set_xticks(range(matrix.shape[1]), [f'{r}\n{t}' for r in resistors for t in temps] if i == 0 else list(resistors), fontsize=8)
            for y in range(matrix.shape[0]):
                for x in range(matrix.shape[1]):
                    ax.text(x, y, str(matrix[y, x]), ha='center', va='center', fontsize=8,
                            color='white' if matrix[y, x] > vmax * .55 else 'black')
            for y in (2.5, 5.5, 8.5, 11.5):
                ax.axhline(y, color='white', linewidth=1.5)
            if i == 0:
                for x in (2.5, 5.5): ax.axvline(x, color='white', linewidth=1.5)
            counts = result['counts'][code]
            total = counts['conditions_with_code'] if i == 0 else counts['fixed_chips_with_common_code']
            title = (f'Upper threshold H={code}: VDD - {model.DROPS[code]:.2f} V\n'
                     f'{total}/135 interpolated choices; '
                     f'{data["bracket_containment"][code]["conditions_with_whole_bracket"]} whole brackets in window') if i == 0 else (
                         'Same VCO code K at all three temperatures\n' + f'{total}/45 interpolated common codes')
            ax.set_title(title, fontsize=9)
            ax.set_xlabel('RC section / temperature (C)' if i == 0 else 'RC section', fontsize=9)
    fig.colorbar(im, ax=axes, ticks=range(vmax + 1), shrink=.8, label='Number of measured, bracketed 2 GHz code choices')
    fig.suptitle('VCO choices within ideal windows: lower threshold 0.90 V\n'
                 '30 fF per leg; positive Kvco; static evidence only, no startup or recoding qualification', fontsize=13)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for ext in ('png', 'svg'): fig.savefig(dest.with_suffix('.' + ext), dpi=180)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--analysis', type=Path, required=True)
    a = ap.parse_args()
    data = collect(a.analysis.resolve())
    text = json.dumps(data, indent=2, allow_nan=False) + '\n'
    for p in (ROOT / 'docs/data/vco_control_windows.json', ROOT / 'results/catalog/vco_control_windows.json'):
        p.write_text(text)
    plot(data, ROOT / 'docs/figures/clocking/vco/vco_coarse_control_windows')
    print(json.dumps(data['analysis']['counts']))


if __name__ == '__main__': main()
