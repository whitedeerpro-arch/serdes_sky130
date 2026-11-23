"""Compare 2p85/5p73 load networks and a controlled code-15 Rref surrogate.

Calibrate each width separately. Only the explicit existing signed-cube overlay
is used; native 5p73 is unchanged. Its cubic base is nonnegative. LF AC is
checked against DC finite differences; RF admittance is recorded separately.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import uuid

import numpy as np

from serdes_flow import poly_geometry as geometry, project, scalar_raw, spice, watch

ROOT = project.ROOT
HERE = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location('wide_card_parent', HERE.with_name('fixed_load_card.py'))
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
read, dump = base.read, base.dump
def sha(path): return base.sha(Path(path))
LENGTHS = dict(short=(.5, .75, 1., 1.5, 2., 3., 4., 6., 8., 12., 16., 24., 32.),
               reference=(.5, 1., 2., 4., 8., 16., 32., 64., 128., 256., 512.))
TARGETS = (50, 120, 240, 300, 400, 600)
COUNTS = {50: {'2p85': (5, 8, 17, 24, 32), '5p73': (2, 4, 8, 12, 16)},
          120: {'2p85': (2, 4, 6), '5p73': (1, 2, 3)},
          **{r: {'2p85': (1, 2, 4), '5p73': (1, 2)} for r in (240, 300, 400, 600)}}
TEMPS = (-40, 27, 85)
DROPS = (.01, .1, .25, .5)
CORNERS = ('tt', 'll', 'hh', 'hl', 'lh')
DELTA = 1e-4


def overlay():
    data = read(ROOT / 'docs/data/fixed_load_overlay.json'); manifest = ROOT / data['overlay_manifest']
    if sha(manifest) != data['overlay_manifest_sha256']: raise ValueError('validated overlay identity changed')
    result = read(manifest); changes = {c['path']: c['overlay_sha256'] for c in result['changes']}
    for path, expected in result['source_files'].items():
        if sha(manifest.parent / path) != changes.get(path, expected) or sha(Path(result['source_pdk']) / path) != expected:
            raise ValueError('source or overlay model changed')
    native = 'libs.ref/sky130_fd_pr/spice/sky130_fd_pr__res_high_po_5p73.model.spice'
    if native in changes: raise ValueError('5p73 must remain the unmodified source model')
    return dict(manifest=str(manifest.relative_to(ROOT)), manifest_sha256=sha(manifest),
                library=result['library'], native_5p73_sha256=result['source_files'][native], id=result['id'])


def calibration_parts():
    parts = []
    for card in ('1p41', '2p85', '5p73'):
        lengths = LENGTHS['reference' if card == '1p41' else 'short']
        for i, length in enumerate(lengths):
            name = f'cal_{card}_{i}'
            parts.append(dict(id=name, kind='calibration', card=card, length_um=length,
                instance=f'X{name} rail out_{name} 0 sky130_fd_pr__res_high_po_{card} l={length}'))
    parts += [base.legacy(f'generic{r}', r) for r in TARGETS]
    parts += [base.legacy('ref112', 112000), base.legacy('ref16', 16 * 780)]
    return parts


def drop_for(part, drop): return 1.23 if part['kind'] == 'reference_string_surrogate' else drop


def deck(parts, corner, library, calibration=False):
    lines = ['wide fixed-poly load comparison', f'.lib "{library}" {corner}', 'Vrail rail 0 1.8']
    for p in parts: lines += [f'Vport_{p["id"]} out_{p["id"]} 0 DC 1.55 AC 1', p['instance']]
    lines += ['.options reltol=1e-6 abstol=1p vntol=1n', '.control', 'set num_threads=1', 'set filetype=binary']
    for temp in ((27,) if calibration else TEMPS):
        for drop in ((.25,) if calibration else DROPS):
            prefix = f't{temp}_d{round(drop * 1000)}'
            lines += [f'option temp={temp}']
            lines += [f'alter Vport_{p["id"]} dc={1.8-drop_for(p,drop):.15g}' for p in parts] + ['op']
            lines += [f'let r_{p["id"]}={drop_for(p,drop):.15g}/i(vport_{p["id"]})' for p in parts]
            lines += [f'write {prefix}_op.raw ' + ' '.join('r_' + p['id'] for p in parts)]
            if not calibration:
                for label, offset in (('lo', -DELTA), ('hi', DELTA)):
                    lines += [f'alter Vport_{p["id"]} dc={1.8-drop_for(p,drop)-offset:.15g}' for p in parts] + ['op']
                    lines += [f'let i_{p["id"]}=i(vport_{p["id"]})' for p in parts]
                    lines += [f'write {prefix}_{label}.raw ' + ' '.join('i_' + p['id'] for p in parts)]
                lines += [f'alter Vport_{p["id"]} dc={1.8-drop_for(p,drop):.15g}' for p in parts] + ['op']
                for label, freq in (('lf', 1.), ('rf', 2e9)):
                    lines += [f'ac lin 1 {freq:.12g} {freq:.12g}']
                    for p in parts:
                        name = p['id']; lines += [f'let rd_{name}=-1/real(i(vport_{name}))',
                                                  f'let c_{name}=-imag(i(vport_{name}))/(2*pi*{freq:.12g})']
                    lines += [f'write {prefix}_{label}.raw ' + ' '.join(v + p['id'] for p in parts for v in ('rd_', 'c_'))]
            lines += ['destroy all']
    return '\n'.join(lines + ['quit', '.endc', '.end', ''])


def prepare():
    models = overlay(); camp = ROOT / 'results/analog/common/devices/wide_load_card' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:8])
    camp.mkdir(parents=True, exist_ok=False); (camp / 'prepared').mkdir()
    text = base.MAGIC.read_text(); minimums = {}
    for card in ('1p41', '2p85', '5p73'):
        defaults = text.split(f'proc sky130::sky130_fd_pr__res_high_po_{card}_defaults {{}} {{')[1].split('\n}')[0]
        if 'lmin 0.50' not in defaults: raise ValueError('recheck fixed-poly generator length constraint')
        minimums[card] = .5
    parts = calibration_parts(); (camp / 'prepared/calibration.cir').write_text(deck(parts, 'tt', models['library'], True))
    current_data = ROOT / 'docs/data/tx_coupling_state.json'; measured = read(current_data)
    peak = max(b['measured_peak_abs_a'] for r in measured['paired_rows'] for m in r['full_record_current'] for b in m['branches'])
    paths = list(dict.fromkeys(base.RUNTIME + [HERE, Path(geometry.__file__), current_data]))
    for source in paths:
        dest = camp / 'execution' / str(source).lstrip('/'); dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, dest)
    dump(camp / 'plan.json', dict(overlay=models, calibration_parts=parts, lengths_um=LENGTHS, minimum_lengths_um=minimums,
        sources={str(p): sha(p) for p in paths}, python=sys.version, numpy=np.__version__,
        calibration_deck_sha256=sha(camp / 'prepared/calibration.cir'),
        current_boundary=dict(peak_a=peak, source=str(current_data.relative_to(ROOT)), source_sha256=sha(current_data),
                              scope='Two clean-input states; not the full-PVT fixed-network current bound.'),
        corners=list(CORNERS), temperatures=list(TEMPS), voltage_drops=list(DROPS), LF_hz=1., RF_hz=2e9, DC_half_step_v=DELTA,
        model_check_relative_gate=1e-3,
        reference_scope='Controlled 1.23V across only the code15 112k+16*780 resistor string; ideal bypass of other trim segments. No switch MOS, Vbg loop, current mirrors or actual swing qualification.',
        geometry_scope='Calibrated signed A+B*L+C/L on the measured increasing branch, 0.01um grid; body-only film area excludes contacts/guards/routes.',
        ungraded=['actual bandgap/trim-switch/current-loop tracking', 'full circuit source/load/coupling state', 'other MOS corners/noise/mismatch', 'network layout/EM/self-heating', 'new implementation adoption']))
    return camp


def check(camp):
    p = read(camp / 'plan.json')
    if p['overlay'] != overlay() or (p['python'], p['numpy']) != (sys.version, np.__version__): raise ValueError('model/runtime identity changed')
    for path, expected in p['sources'].items():
        if sha(path) != expected or sha(camp / 'execution' / path.lstrip('/')) != expected: raise ValueError('source changed: ' + path)
    if sha(camp / 'prepared/calibration.cir') != p['calibration_deck_sha256']: raise ValueError('calibration deck changed')
    return p


def output_names(calibration=False):
    return [f't{t}_d{round(d * 1000)}_{k}.raw' for t in ((27,) if calibration else TEMPS)
            for d in ((.25,) if calibration else DROPS) for k in (('op',) if calibration else ('op', 'lo', 'hi', 'lf', 'rf'))]


def complete(camp, name, text, outputs):
    runs = [camp / name] + [p for p in camp.glob(name + '.r*') if p.name.rsplit('.r', 1)[1].isdigit()]
    expected = hashlib.sha256(text.encode()).hexdigest()
    for run in sorted(runs, key=lambda p: spice._rerun_index(p, name), reverse=True):
        try:
            ex = read(run / 'execution.json')
            if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures']: continue
            if ex['deck_sha256'] != expected or sha(run / 'tb.cir') != expected: raise ValueError('executed deck changed')
            for output in outputs:
                scalar_raw.read(run / output, frequency_hz=1. if output.endswith('_lf.raw') else 2e9 if output.endswith('_rf.raw') else None)
            return run
        except FileNotFoundError: pass
    return None


def run_case(camp, label, text, calibration=False):
    outputs = output_names(calibration); run = complete(camp, label, text, outputs)
    if run is None:
        if len(watch.ngspice_cwds()) >= 4: raise RuntimeError('global ngspice limit')
        ex = spice.run(text, spice.next_run_dir(camp, label), timeout_s=240,
                       meta=dict(case=label, overlay_manifest_sha256=read(camp / 'plan.json')['overlay']['manifest_sha256']))
        if not ex.ok: raise RuntimeError('passive case failed: ' + str(ex.run_dir))
        run = complete(camp, label, text, outputs)
        if run is None: raise RuntimeError('passive output missing')
    return run


def make_networks(plan, raw):
    values = scalar_raw.read(raw / 't27_d250_op.raw'); curves = {}; parts = []; choices = []
    for card in ('1p41', '2p85', '5p73'):
        lengths = LENGTHS['reference' if card == '1p41' else 'short']
        curves[card] = geometry.calibrate(lengths, [values[f'r_cal_{card}_{i}'] for i in range(len(lengths))])
        if curves[card]['max_error_ohm'] > 1e-3: raise ValueError('calibrated length curve inaccurate')
    for target in TARGETS:
        parts.append(base.legacy(f'generic{target}', target))
        for card, counts in COUNTS[target].items():
            for count in counts:
                proposed = geometry.parallel(values[f'r_generic{target}'], count, curves[card], minimum_length=plan['minimum_lengths_um'][card])
                name = f'r{target}_{card}_n{count}'; choices.append(dict(id=name, geometry=proposed))
                if proposed is None: continue
                parts.append(dict(id=name, kind='fixed_load', nominal_ohm=target, card=card, **proposed,
                    poly_body_area_um2=count * geometry.WIDTHS[card] * proposed['length_um'],
                    hypothetical_peak_uA_per_um=plan['current_boundary']['peak_a'] * 1e6 / (count * geometry.WIDTHS[card]) if target == 50 else None,
                    instance=geometry.instances(name, 'rail', 'out_' + name, '0', proposed, card)))
    g112, g16 = base.legacy('g112', 112000), base.legacy('g16', 16 * 780)
    generic = g112['instance'].replace('out_g112', 'gref_mid') + '\n' + g16['instance'].replace(' rail ', ' gref_mid ').replace('out_g16', 'out_reference_generic')
    parts.append(dict(id='reference_generic', kind='reference_string_surrogate', instance=generic))
    for sections in (1, 8):
        name = f'reference_fixed_s{sections}'; lines = []; elements = []
        targets = [values['r_ref112'] / sections] * sections + [values['r_ref16']]
        nodes = ['rail'] + [f'{name}_{i}' for i in range(sections)] + ['out_' + name]
        for i, (target, pos, neg) in enumerate(zip(targets, nodes[:-1], nodes[1:])):
            g = geometry.parallel(target, 1, curves['1p41'], minimum_length=plan['minimum_lengths_um']['1p41'])
            if g is None: raise ValueError('reference string outside calibration')
            elements.append(g); lines.append(geometry.instances(name + '_' + str(i), pos, neg, '0', g, '1p41'))
        parts.append(dict(id=name, kind='reference_string_surrogate', card='1p41', elements=elements, instance='\n'.join(lines)))
    return dict(curves=curves, parts=parts, choices=choices)


def measure(camp, model, runs):
    rows = []; evidence = {}
    for rc, run in runs.items():
        outputs = output_names(); evidence.update({str(p.relative_to(ROOT)): sha(p) for p in
            [run / n for n in outputs] + [run / n for n in ('tb.cir', 'execution.json', 'simulator.log')]})
        for temp in TEMPS:
            for drop in DROPS:
                prefix = f't{temp}_d{round(drop * 1000)}'
                op, lo, hi = [scalar_raw.read(run / f'{prefix}_{kind}.raw') for kind in ('op', 'lo', 'hi')]
                lf = scalar_raw.read(run / f'{prefix}_lf.raw', frequency_hz=1.)
                rf = scalar_raw.read(run / f'{prefix}_rf.raw', frequency_hz=2e9)
                for p in model['parts']:
                    name = p['id']; fd = 2 * DELTA / (hi['i_' + name] - lo['i_' + name])
                    rows.append(dict(id=name, corner=rc, temp_c=temp, drop_v=drop_for(p, drop), load_drop_grid_v=drop,
                        resistance_ohm=op['r_' + name], FD_resistance_ohm=fd,
                        LF_incremental_resistance_ohm=lf['rd_' + name], RF_real_admittance_inverse_ohm=rf['rd_' + name],
                        RF_effective_node_capacitance_f=rf['c_' + name], LF_AC_vs_FD_relative_error=abs(lf['rd_' + name] / fd - 1)))
    return rows, evidence


def resume(camp):
    with (camp / '.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); plan = check(camp)
        if any(p.is_relative_to(camp) for p in watch.ngspice_cwds()): raise RuntimeError('campaign active')
        dest = spice.next_run_dir(camp / 'analysis', 'measurement'); dest.mkdir(parents=True)
        result = dict(status='failed', plan_sha256=sha(camp / 'plan.json'), rows=[])
        try:
            cal = run_case(camp, 'calibration', (camp / 'prepared/calibration.cir').read_text(), True)
            model = make_networks(plan, cal); network = camp / 'networks.json'
            if network.exists() and read(network) != model: raise ValueError('planned geometry changed')
            if not network.exists(): dump(network, model)
            runs = {}
            for rc in CORNERS:
                text = deck(model['parts'], rc, plan['overlay']['library']); prepared = camp / 'prepared' / (rc + '.cir')
                if prepared.exists() and prepared.read_text() != text: raise ValueError('prepared deck changed')
                if not prepared.exists(): prepared.write_text(text)
                runs[rc] = run_case(camp, rc, text)
            rows, evidence = measure(camp, model, runs)
            result.update(rows=rows, evidence=evidence, networks_sha256=sha(network),
                calibration_evidence={str(p.relative_to(ROOT)): sha(p) for p in (cal / 'tb.cir', cal / 'execution.json', cal / 'simulator.log', cal / 't27_d250_op.raw')})
            result['max_LF_AC_vs_FD_relative_error'] = max(r['LF_AC_vs_FD_relative_error'] for r in rows)
            if result['max_LF_AC_vs_FD_relative_error'] > plan['model_check_relative_gate']:
                raise ValueError('LF AC derivative disagrees with DC finite differences')
            result['status'] = 'wide_networks_measured_not_actual_bias_or_circuit_qualified'
        except Exception as exc:
            result['error'] = f'{type(exc).__name__}: {exc}'; raise
        finally: dump(dest / 'summary.json', result)
    return dest / 'summary.json'


def main():
    p = argparse.ArgumentParser(description=__doc__); g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare', action='store_true'); g.add_argument('--resume', type=Path); a = p.parse_args()
    print(prepare() if a.prepare else resume(a.resume.resolve()))


if __name__ == '__main__': main()
