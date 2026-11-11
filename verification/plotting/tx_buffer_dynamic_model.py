"""Reproduce the offline differential model and publish held-out errors."""
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

from serdes_flow.project import ROOT

MODEL = ROOT / 'analog/tx/clock_distribution/theory/buffer_dynamic_model.py'
DATA = ROOT / 'docs/data/tx_buffer_dynamic_model.json'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    stored = json.loads(DATA.read_text())
    spec = importlib.util.spec_from_file_location('dynamic_model', MODEL)
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    calculated = json.loads(json.dumps(model.calculate(), allow_nan=False))
    if calculated != stored:
        raise ValueError('model/identities/refit do not reproduce the published result')
    archive = ROOT / 'results/analog/tx/buffer_dynamic_model' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    archive.mkdir(parents=True, exist_ok=False)
    for p in (MODEL, Path(__file__).resolve(), DATA):
        shutil.copyfile(p, archive / p.name)
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.6), layout='constrained')
    fields = (('amplitude_error_mv', 'Amplitude discrepancy (mV)'),
              ('crossing_error_ps_max_abs', 'Maximum crossing discrepancy (ps)'),
              ('slew_error_v_per_ns_max_abs', '10 ps aperture slew discrepancy (V/ns)'))
    labels = ['15 / 320', '15.6 / 300', '14 → 15.6', '14.4 → 15.6']
    cases = [('gain_search', 'tail15'), ('gain_search', 'tail15p6_r300'),
             ('taper', 'first14'), ('taper', 'first14p4')]
    summary = {}
    for tag, color, offset in [('tt_v1800_t27', '#286d9b', -.18), ('fs_v1650_t85', '#c36d37', .18)]:
        rows = [r for r in stored['results'][tag]['stage_errors'] if r['split'] == 'holdout']
        summary[tag] = {}
        for mode, marker, style, caption in [('one_step_measured_input', 'o', ':', 'one stage, measured input'),
                                            ('cascade_from_measured_iso_only', 'D', '-', 'four stages, iso input only')]:
            summary[tag][mode] = {}
            for ax, (field, ylabel) in zip(axes, fields):
                values = []
                for source, branch in cases:
                    errs = [r[mode][field] for r in rows if (r['source'], r['branch']) == (source, branch)]
                    if len(errs) != 4 or any(v is None for v in errs):
                        raise ValueError('incomplete held-out stage or missing crossing')
                    values.append(max(abs(v) for v in errs))
                summary[tag][mode][field] = max(values)
                ax.plot(np.arange(4) + offset, values, marker=marker, ls=style, color=color,
                        label=f'{tag.split("_")[0].upper()}: {caption}', ms=5)
                ax.set_ylabel(ylabel)
    for ax in axes:
        ax.set_xticks(range(4), labels, rotation=15, ha='right')
        ax.set_ylim(bottom=0)
        ax.grid(alpha=.2)
        ax.set_xlabel('Held-out tail width / nominal resistance')
    axes[0].legend(fontsize=7)
    fig.suptitle('Differential dynamic buffer model: measured holdout error', fontsize=13)
    fig.supxlabel('WN24 → WN24, e0–e3, TT / FS only. Heavy final load, Xout, common mode, other PVT and eye constraints remain unmodeled.', fontsize=9)
    figure = ROOT / 'docs/figures/tx/ingress/tx_buffer_dynamic_model.png'
    fig.savefig(figure, dpi=170)
    plt.close(fig)
    index = dict(data=str(DATA.relative_to(ROOT)), data_sha256=sha(DATA),
                 model=str(MODEL.relative_to(ROOT)), model_sha256=sha(MODEL),
                 publisher=str(Path(__file__).resolve().relative_to(ROOT)), publisher_sha256=sha(Path(__file__).resolve()),
                 archive=str(archive.relative_to(ROOT)), figure=str(figure.relative_to(ROOT)), figure_sha256=sha(figure),
                 scope=stored['scope'], status=stored['status'], holdout_maximum_errors=summary)
    (ROOT / 'results/catalog/tx_buffer_dynamic_model.json').write_text(json.dumps(index, indent=2, allow_nan=False) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
