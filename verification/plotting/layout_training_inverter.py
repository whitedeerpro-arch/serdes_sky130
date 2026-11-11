"""Publish the three verified DS-01 teaching cases and an annotated layout view."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from serdes_flow.project import ROOT


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def contact_counts(path):
    layer, counts = None, dict(ndiffc=0, pdiffc=0)
    for line in path.read_text().splitlines():
        if m := re.fullmatch(r'<< (\S+) >>', line):
            layer = m[1]
        elif line.startswith('rect ') and layer in counts:
            counts[layer] += 1
    return counts


def draw_layout(ax, path, title):
    text = path.read_text()
    if 'magscale 1 2' not in text or re.search(r'^use ', text, re.M):
        raise ValueError('renderer requires the calibrated flat teaching cell')
    # This fixed example was painted in micrometres; SKY130A stores 200
    # internal coordinates per micrometre here. Not a general .mag reader.
    colors = dict(nwell='#f2e3ac', pwell='#dce6f2', ndiff='#65a5d4', pdiff='#db9292',
                  poly='#d77b28', locali='#bdafd1', metal1='#536db4',
                  ndiffc='#272727', pdiffc='#272727', viali='#292929', polycont='#333333',
                  nsubdiff='#78ad80', psubdiff='#78ad80', nsubdiffcont='#222222', psubdiffcont='#222222')
    layer = None
    rects, labels = [], []
    for line in text.splitlines():
        if m := re.fullmatch(r'<< (\S+) >>', line):
            layer = m[1]
        elif m := re.fullmatch(r'rect (-?\d+) (-?\d+) (-?\d+) (-?\d+)', line):
            rects.append((layer, *[int(v) / 200 for v in m.groups()]))
        elif line.startswith('rlabel '):
            fields = line.split()
            labels.append((fields[-1], int(fields[2]) / 200, int(fields[3]) / 200))
    priority = {k: i for i, k in enumerate(colors)}
    for layer, x1, y1, x2, y2 in sorted(rects, key=lambda r: priority.get(r[0], -1)):
        if layer in colors:
            ax.add_patch(Rectangle((x1, y1), x2 - x1, y2 - y1,
                                   facecolor=colors[layer], edgecolor='none', alpha=.86))
    positions = dict(d=(7.6, 6.3), g=(7.6, 1.1), vdd=(7.6, 16.2), vss=(7.6, .2))
    for name, x, y in labels:
        if name in positions:
            ax.annotate(name.upper(), xy=(x, y), xytext=positions[name], fontsize=9,
                         ha='right', va='center', arrowprops=dict(arrowstyle='-', color='#333', lw=.8))
    ax.text(.7, 11.1, 'P', color='#753030', fontsize=12, weight='bold')
    ax.text(.7, 4.2, 'N', color='#245482', fontsize=12, weight='bold')
    ax.set(title=title, xlabel='µm', ylabel='µm', xlim=(.2, 8), ylim=(-.2, 17.3), aspect='equal')
    ax.grid(alpha=.12)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('workspace', type=Path)
    for label in ('baseline', 'student', 'fault'):
        p.add_argument('--' + label + '-summary', required=True, type=Path)
    a = p.parse_args()
    work = a.workspace.resolve()
    runner = ROOT / 'verification/layout_training/run.py'
    spec = importlib.util.spec_from_file_location('training_runner', runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = module.verify(work)
    rows = {}
    for label in ('baseline', 'student', 'fault'):
        source = getattr(a, label + '_summary').resolve()
        if source.parent.parent.parent != work:
            raise ValueError('summary belongs to another lesson')
        row = json.loads(source.read_text())
        expected = 'expected_open_detected' if label == 'fault' else 'layout_checks_pass'
        if row['status'] != expected or sha(source.parent / 'runner.py') != row['runner_sha256']:
            raise ValueError('incorrect case status or runner identity')
        for rel, digest in row['files_sha256'].items():
            if sha(work / rel) != digest:
                raise ValueError('case input/output changed: ' + rel)
        rows[label] = dict(summary=str(source.relative_to(ROOT)), summary_sha256=sha(source), result=row)
    layout = Path('analog/common/layout_practice')
    files = {view: work / view / layout / 'inv_std.mag' for view in ('baseline', 'student')}
    contacts = {view: contact_counts(path) for view, path in files.items()}
    if contacts != dict(baseline=dict(ndiffc=2, pdiffc=2), student=dict(ndiffc=18, pdiffc=38)):
        raise ValueError('actual contact cuts differ from the worked example')
    fig, axes = plt.subplots(1, 3, figsize=(12, 7.5), layout='constrained', gridspec_kw={'width_ratios': [1.3, 1, 1]})
    ax = axes[0]
    ax.axis('off')
    ax.set_title('Start from the electrical connections')
    ax.text(.02, .91, 'MOS     D   G   S    B     W/L (µm)\nPMOS    d   g   vdd  vdd   8/0.15\nNMOS    d   g   vss  vss   4/0.15',
            family='monospace', fontsize=9, transform=ax.transAxes, linespacing=1.8)
    ax.text(.02, .60, 'PMOS above NMOS\nOne shared vertical poly gate\nBoth drains join output D\nN-well tap → VDD\nSubstrate tap → VSS', fontsize=11, transform=ax.transAxes, linespacing=1.9)
    for y, color, label in [(.26, '#d77b28', 'Orange: poly / shared gate'), (.20, '#536db4', 'Blue: metal 1 / wiring'),
                             (.14, '#272727', 'Black: contact cuts'), (.08, '#f2e3ac', 'Pale yellow: N-well')]:
        ax.add_patch(Rectangle((.02, y), .04, .025, facecolor=color, transform=ax.transAxes))
        ax.text(.09, y + .004, label, fontsize=9, transform=ax.transAxes, va='bottom')
    draw_layout(axes[1], files['baseline'], 'Baseline: 1 contact per S/D')
    draw_layout(axes[2], files['student'], 'Worked example: N 9 / P 19 per S/D')
    fig.suptitle('DS-01: preserve the circuit while improving contact coverage', fontsize=14)
    fig.supxlabel('Both shown cells: full-rule DRC 0, LVS match with no property errors. Separate open-drain example: DRC 0 but LVS fails.\nTraining only: contact count is not current-capacity, timing, PVT or tapeout qualification.', fontsize=9)
    figure = ROOT / 'docs/figures/layout/deepseek_inverter_training.png'
    figure.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure, dpi=170)
    plt.close(fig)
    archive = ROOT / 'results/layout_training/publication' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    archive.mkdir(parents=True)
    shutil.copyfile(__file__, archive / 'publisher.py')
    result = dict(status='baseline_and_contact_example_DRC_LVS_pass; deliberate_open_detected; teaching_only',
                  workspace=str(work.relative_to(ROOT)), manifest_sha256=sha(work / 'manifest.json'),
                  manifest=manifest, cases=rows, publisher_sha256=sha(Path(__file__)),
                  publisher_snapshot=str((archive / 'publisher.py').relative_to(ROOT)),
                  measured_source_drain_contact_counts=contacts,
                  contact_plan=json.loads((work / 'student/contact_plan.json').read_text()))
    data = ROOT / 'docs/data/layout_training_ds01.json'
    data.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    index = dict(data=str(data.relative_to(ROOT)), data_sha256=sha(data), figure=str(figure.relative_to(ROOT)),
                 figure_sha256=sha(figure), workspace=result['workspace'], status=result['status'])
    (ROOT / 'results/catalog/layout_training_ds01.json').write_text(json.dumps(index, indent=2) + '\n')
    print(json.dumps(index, indent=2))


if __name__ == '__main__':
    main()
