"""Publish a reproduced WP-TX-CM-001 diagnostic and its waveform examples."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import project

ROOT = project.ROOT
HERE = Path(__file__).resolve()
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def read(path): return json.loads(path.read_text())
def dump(path, data): path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def collect(delivery, reproduced):
    original, reviewed = read(delivery), read(reproduced)
    if original != reviewed:
        raise ValueError('independent rerun did not reproduce the delivery')
    if original['status'] != 'offline_diagnostic_no_adoption': raise ValueError('diagnostic incomplete')
    for path, expected in original['input_sha256'].items():
        if sha(ROOT / path) != expected: raise ValueError('diagnostic input changed: ' + path)
    expected = {(c, m, p, s) for c in ('fs_v1650_t85', 'ss_v1650_t-40')
                for m in ('generic', 'fixed_short', 'fixed_long')
                for p in ('cm_m25', 'weak080_cm_m25') for s in ('e3', 'e4', 'c2g')}
    rows = original['paired_cm']
    if {(r['condition'], r['mode'], r['point'], r['stage']) for r in rows} != expected or len(rows) != 36:
        raise ValueError('paired diagnostic coverage differs')
    if len(original['inputs']) != 72 or len(original['predictions']) != 72:
        raise ValueError('diagnostic input/prediction coverage differs')
    held = []
    for r in original['predictions']:
        if r['point'] != 'weak080_cm_m25': continue
        entry = {k: r[k] for k in ('condition', 'mode', 'stage')}
        entry['methods'] = {}
        for method, record in r['methods'].items():
            entry['methods'][method] = dict(signed_edges=record['signed_edges'],
                maxima={k: record['metrics'][k] for k in ('differential_max_error_mv', 'common_mode_max_error_mv', 'crossing_error_max_abs_ps')},
                clock_qualified=record['metrics']['complete_causal_clock_check']['clock_qualified'])
        held.append(entry)
    return dict(status='reproduced_offline_CM_diagnostic_no_adoption',
                delivery=str(delivery.relative_to(ROOT)), delivery_sha256=sha(delivery),
                reproduced=str(reproduced.relative_to(ROOT)), reproduced_sha256=sha(reproduced),
                input_sha256=original['input_sha256'], inputs=original['inputs'], paired_cm=rows,
                heldout_errors=held, failures=original['failures'], window_s=original['window_s'],
                scope=original['scope'], interpretation=original['interpretation'],
                publisher_sha256=sha(HERE))


def plot(data):
    fig, axes = plt.subplots(2, 2, figsize=(11, 6.5), layout='constrained')
    for row, condition in enumerate(('fs_v1650_t85', 'ss_v1650_t-40')):
        for mode, color in zip(('generic', 'fixed_short', 'fixed_long'), ('#657788', '#c27236', '#20877b')):
            for point, marker, style in (('cm_m25', 'o', '-'), ('weak080_cm_m25', 'D', ':')):
                values = [next(r for r in data['paired_cm'] if
                    (r['condition'], r['mode'], r['point'], r['stage']) == (condition, mode, point, stage))
                          for stage in ('e4', 'c2g')]
                for ax, field in zip(axes[row], ('mean', 'max')):
                    y = [r['cm_delta_v']['mean'] * 1e3 if field == 'mean' else r['cm_max_abs_delta_v'] * 1e3 for r in values]
                    ax.plot(range(2), y, marker=marker, ls=style, color=color, ms=5, label=mode + ': ' + point)
        axes[row, 0].axhline(0, color='#555', lw=.6)
        axes[row, 0].set_ylabel(condition + '\nMean input CM change (mV)')
        axes[row, 1].set_ylabel('Maximum absolute input CM change (mV)')
        for ax in axes[row]:
            ax.set_xticks(range(2), ('Xe4 input', 'Xout input'))
            ax.grid(alpha=.2)
    axes[0, 0].legend(fontsize=6.5)
    fig.suptitle('An entry CM shift of -25 mV does not independently excite later stages')
    fig.supxlabel('Paired cm-only minus original, and weak+CM minus weak. Same absolute time; ideal recorded sources, actual downstream loading.', fontsize=9)
    return fig


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--delivery', type=Path, required=True); p.add_argument('--reproduced', type=Path, required=True)
    a = p.parse_args(); delivery, reproduced = a.delivery.resolve(), a.reproduced.resolve()
    data = collect(delivery, reproduced)
    dest = reproduced.parent / 'publication_sources' / sha(HERE); dest.mkdir(parents=True, exist_ok=True)
    if not (dest / HERE.name).exists(): shutil.copyfile(HERE, dest / HERE.name)
    output = ROOT / 'docs/data/tx_loaded_cm.json'
    figure = ROOT / 'docs/figures/tx/ingress/tx_loaded_cm_excitation.png'
    plot(data).savefig(figure, dpi=170, bbox_inches='tight', pad_inches=.15); plt.close('all')
    figures = [figure]
    for tag, name in (('fs_v1650_t85', 'tx_loaded_cm_fs_waveforms'), ('ss_v1650_t-40', 'tx_loaded_cm_ss_waveforms')):
        source = reproduced.parent / (tag + '.png'); counterpart = delivery.parent / source.name
        if sha(source) != sha(counterpart): raise ValueError('reproduced waveform figure differs')
        target = figure.with_name(name + '.png'); shutil.copyfile(source, target); figures.append(target)
    data['figures'] = {str(p.relative_to(ROOT)): sha(p) for p in figures}
    dump(output, data)
    dump(ROOT / 'results/catalog/tx_loaded_cm.json',
         dict(data=str(output.relative_to(ROOT)), data_sha256=sha(output), figures=data['figures'],
              delivery=data['delivery'], delivery_sha256=data['delivery_sha256'],
              reproduced=data['reproduced'], reproduced_sha256=data['reproduced_sha256'],
              failures=len(data['failures']), scope=data['scope']))
    print(output)


if __name__ == '__main__': main()
