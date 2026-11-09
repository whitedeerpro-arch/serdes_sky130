"""Collect two completed joint CP/ladder mismatch pilots, without simulation."""
import argparse
import importlib.util
import json
import math
import re
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from serdes_flow import mc, project

ROOT = project.ROOT
RUNNER = ROOT / 'analog/pll/coarse/tb/cp_handoff_mc/run.py'
spec = importlib.util.spec_from_file_location('cp_handoff_runner', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def collect(camp, check_only=False):
    camp = camp.resolve()
    plan = runner.verify(camp)
    if (plan['samples'], plan['chunk'], plan['seed'], plan['code_hi']) not in ((32, 4, 1, 3), (32, 4, 1, 4)):
        raise ValueError(f'{camp}: expected 32 samples, chunk 4, seed 1, code 3 or 4')
    if not any(runner.smoke_valid(p, camp / 'prepared/smoke.cir') for p in [camp / 'smoke', *camp.glob('smoke.r[0-9]*')]):
        raise ValueError(f'{camp}: no valid deterministic smoke')
    selected, missing = [], []
    for c in plan['chunks']:
        deck = (camp / c['deck']).read_text()
        manifest = json.loads((camp / (c['name'] + '.inputs.json')).read_text())
        excluded = manifest.pop('unverified_attempts', [])
        if manifest != mc._signature(deck, {}):
            raise ValueError(f'{camp}: {c["name"]} input identity mismatch')
        attempts = [camp / c['name']] + sorted((p for p in camp.glob(c['name'] + '.r*')
            if p.is_dir() and p.name.rsplit('.r', 1)[-1].isdigit()), key=lambda p: int(p.name.rsplit('.r', 1)[-1]))
        valid = []
        for p in attempts:
            if p.name in excluded or not mc.complete(p, deck):
                continue
            ex = json.loads((p / 'execution.json').read_text())
            if ((p / 'tb.cir').read_text() == deck and ex.get('deck_sha256') == runner.sha(p / 'tb.cir')
                    and ex.get('seed') == c['seed'] and ex.get('samples') == c['samples']
                    and ex.get('pdk_installation_id') == plan['pdk_installation_id'] and not ex.get('log_failures')):
                valid.append(p)
        if not valid:
            missing.append(c['name'])
        else:
            selected.append((c, valid[-1], deck))
    if missing:
        raise ValueError(f'{camp}: incomplete or unverified chunks {missing}; no collection')
    if check_only:
        return {'campaign': str(camp.relative_to(ROOT)), 'code_hi': plan['code_hi'], 'chunks': len(selected), 'samples': 32}
    rows = []
    inputs = {str((camp / 'plan.json').relative_to(ROOT)): runner.sha(camp / 'plan.json')}
    for c, path, _ in selected:
        for file in (path / 'mc.tsv', path / 'execution.json', path / 'tb.cir', camp / (c['name'] + '.inputs.json')):
            inputs[str(file.relative_to(ROOT))] = runner.sha(file)
        for index, row in enumerate(mc.read(path)):
            ok = runner.validate(row)
            droop = {}
            for side, mid, hi, plus in [('up', 'midup', 'hiup', 'plusup'), ('dn', 'middn', 'hidn', 'plusdn')]:
                for label, key in [('hi', hi), ('plus20mv', plus)]:
                    a, b = row.get(mid), row.get(key)
                    droop[f'{side}_{label}'] = 1 - b / a if a is not None and b is not None and math.isfinite(a) and math.isfinite(b) and a != 0 else None
            rows.append(dict(chunk=c['name'], chunk_seed=c['seed'], sample=index, valid=ok,
                             values={k: v if math.isfinite(v) else None for k, v in row.items()}, droop=droop))
    return {'campaign': str(camp.relative_to(ROOT)), 'code_hi': plan['code_hi'],
            'runs': [str(p.relative_to(ROOT)) for _, p, _ in selected], 'inputs_sha256': inputs, 'rows': rows}


def normalized_decks(camp):
    plan = json.loads((camp / 'plan.json').read_text())
    return [re.sub(r'code_hi=[34]\b', 'code_hi=CODE', (camp / c['deck']).read_text().replace(str(camp), 'CAMPAIGN')) for c in plan['chunks']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', action='append', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if len(args.campaign) != 2:
        parser.error('provide --campaign twice')
    camps = [p.resolve() for p in args.campaign]
    try:
        data = sorted([collect(p, args.check) for p in camps], key=lambda x: x['code_hi'])
        if [x['code_hi'] for x in data] != [3, 4]:
            raise ValueError('one campaign each for code 3 and code 4 required')
        if normalized_decks(camps[0]) != normalized_decks(camps[1]):
            raise ValueError('prepared decks differ beyond campaign path and code_hi')
        if args.check:
            print(json.dumps(data, indent=2)); return
        paired = []
        for a, b in zip(data[0]['rows'], data[1]['rows']):
            if (a['chunk'], a['chunk_seed'], a['sample']) != (b['chunk'], b['chunk_seed'], b['sample']):
                raise ValueError('sample identities differ')
            fields = {}
            differences = {}
            for key in ('vbg', 'vgi', 'midup', 'middn'):
                x, y = a['values'].get(key), b['values'].get(key)
                fields[key] = x is not None and y is not None and math.isclose(x, y, rel_tol=1e-4, abs_tol=1e-7 if key in ('vbg', 'vgi') else 1e-12)
                differences[key] = y - x if x is not None and y is not None else None
            paired.append(dict(chunk=a['chunk'], sample=a['sample'], matches=fields, code4_minus_code3=differences))
        paired_ok = all(all(p['matches'].values()) for p in paired)
        result = dict(scope='ungraded pilot; SF/ll, 1.65 V, 85 C; ladder included; comparator offset and actual PLL excluded; static vhi + 20 mV is an experiment, not an approved dynamic budget; 32 samples do not establish yield', paired=paired_ok, pairing_checks=paired, campaigns=data,
                      collector_sha256=runner.sha(Path(__file__)), runner_sha256=runner.sha(RUNNER))
        payload = json.dumps(result, indent=2, allow_nan=False) + '\n'
        for path in (ROOT / 'docs/data/pll_cp_handoff_mc.json', ROOT / 'results/catalog/pll_cp_handoff_mc.json'):
            path.write_text(payload)
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
        for ax, side in zip(axes, ('up', 'dn')):
            for j, campaign in enumerate(data):
                for offset, point, marker in [(-.13, 'hi', 'o'), (.13, 'plus20mv', 'x')]:
                    vals = [(i + 1 + offset, row['droop'][f'{side}_{point}'] * 100) for i, row in enumerate(campaign['rows']) if row['droop'][f'{side}_{point}'] is not None]
                    if vals:
                        ax.scatter(*zip(*vals), s=20, marker=marker, color=f'C{j}', label=f'code {campaign["code_hi"]}, ' + ('vhi' if point == 'hi' else 'vhi + 20 mV'))
            ax.axhline(5, color='black', linestyle='--', linewidth=1, label='5% reference')
            ax.set(title=side.upper(), xlabel='Sample index (seed 1; chunks of 4)', ylabel='Current droop relative to mid (%)')
            ax.grid(alpha=.2)
        axes[1].legend(fontsize=7)
        fig.suptitle('CP static handoff pilot: ladder vhi and vhi + 20 mV' + ('' if paired_ok else ' (pairing mismatch)'))
        fig.tight_layout()
        figure = ROOT / 'docs/figures/clocking/pll/charge_pump/cp_handoff_threshold_mc'
        figure.parent.mkdir(parents=True, exist_ok=True)
        for ext in ('png', 'svg'):
            fig.savefig(figure.with_suffix('.' + ext), dpi=180)
        plt.close(fig)
        print(json.dumps({'paired': paired_ok, 'invalid_samples': [sum(not r['valid'] for r in c['rows']) for c in data]}))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
