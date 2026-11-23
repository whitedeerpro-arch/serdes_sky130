"""Paired clean-input output stages: delayed enable vs enabled DC operating point.

The copies share prescribed clean inputs and one real bias reference. This
isolates a load-state boundary; it does not replay or qualify the full TX.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import uuid

import numpy as np

from serdes_flow import bias, project, serial, spice, stage_metrics, watch
from serdes_flow.corners import Condition

ROOT = project.ROOT
HERE = Path(__file__).resolve()
DDJ = ROOT / 'analog/tx/output_driver/tb/ddj/run.py'
spec = importlib.util.spec_from_file_location('coupling_ddj_helper', DDJ)
ddj = importlib.util.module_from_spec(spec); spec.loader.exec_module(ddj)
# Reuse the existing exact training/payload generator at a declared new origin.
ddj.T0 = 8e-9
TAGS = ('fs_v1650_t85', 'ff_v1950_t-40')
PARAMS = dict(rpre='120', wout='192', wtpre='60')
sha = ddj.sha
read = lambda p: json.loads(p.read_text())
def dump(p, d): p.write_text(json.dumps(d, indent=2, allow_nan=False) + '\n')


def probes():
    nodes = ['vdd', 'vbias', 'bias_vbg', 'qp', 'qn']
    props = []
    for i in (1, 2):
        nodes += [n + str(i) for n in ('lqp', 'lqn', 'lrp', 'lrn')]
        nodes += [f'xdriver{i}.' + n for n in ('tail', 'vbtail')]
        props += [(f'irp{i}', f'@r.xdriver{i}.xrp.rbody[i]'), (f'irn{i}', f'@r.xdriver{i}.xrn.rbody[i]'),
                  (f'itail{i}', f'@m.xdriver{i}.xt.xmos.msky130_fd_pr__nfet_01v8[id]'),
                  (f'vdsat{i}', f'@m.xdriver{i}.xt.xmos.msky130_fd_pr__nfet_01v8[vdsat]')]
    return nodes, props


def build(camp, tag, stop):
    text = ddj.deck(Condition.parse(tag), 'tt', PARAMS, '200f', '.5n', stop, camp / 'snap' / tag)
    match = re.search(r'(?ms)^Cqp .*?^Rlterm1 [^\n]*$', text)
    if not match: raise ValueError('output fixture block changed')
    block = match.group()
    # Preserve the input capacitance once; the source is ideal and its loading
    # does not constitute an upstream serializer impedance measurement.
    input_caps = '\n'.join(l for l in block.splitlines() if l.startswith(('Cqp ', 'Cqn ')))
    block = '\n'.join(l for l in block.splitlines() if not l.startswith(('Cqp ', 'Cqn ')))
    renames = set('lqp lqn llp lln lap lan ltp ltn lxp lxn lrp lrn lcm'.split())
    copies = [input_caps]
    for i in (1, 2):
        copies.append(f'Vsense{i} vdd vd{i} 0')
        for line in block.splitlines():
            fields = line.split()
            if not fields: continue
            fields = [fields[0] + str(i)] + [x + str(i) if x in renames else x for x in fields[1:]]
            if fields[0] == f'Xdriver{i}':
                if fields[:10] != [f'Xdriver{i}', 'qp', 'qn', 'tx_en', f'lqp{i}', f'lqn{i}', 'vbias', 'vdd', 'vdd', '0']:
                    raise ValueError('driver pins changed')
                fields[3] = 'tx_en' + str(i); fields[7] = fields[8] = 'vd' + str(i)
            copies.append(' '.join(fields))
    text = text.replace(match.group(), '\n'.join(copies))
    supply = Condition.parse(tag).supply
    text, count = re.subn(r'(?m)^Ven .+$',
        f'Ven1 tx_en1 0 PWL(0 0 4n 0 4.1n {supply:g})\nVen2 tx_en2 0 {supply:g}', text)
    if count != 1: raise ValueError('enable source changed')
    nodes, props = probes()
    save = ' '.join(['v(' + n + ')' for n in nodes] + [f'i(vsense{i})' for i in (1, 2)] + [p for _, p in props])
    text, count = re.subn(r'(?m)^\.save .+$', '.save ' + save, text)
    if count != 1: raise ValueError('save block changed')
    control = ['.control', 'set num_threads=1', 'set filetype=binary', f'tran 2p {stop:.15e} 0 2p']
    control += [f'let {n}={p}' for n, p in props]
    control += ['write waveforms.raw ' + ' '.join(['v(' + n + ')' for n in nodes] + [f'i(vsense{i})' for i in (1, 2)] + [n for n, _ in props]), 'quit', '.endc']
    text, count = re.subn(r'(?ms)^\.control\n.*?^\.endc$', '\n'.join(control), text)
    if count != 1: raise ValueError('control block changed')
    return text


def prepare():
    camp = ROOT / 'results/analog/tx/output_driver/coupling_state' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:8])
    camp.mkdir(parents=True, exist_ok=False)
    bits = ddj.clean_bits(); stop = ddj.T0 + len(bits) * ddj.UI
    for tag in TAGS:
        dest = camp / 'prepared' / tag; dest.mkdir(parents=True, exist_ok=False)
        (dest / 'stimuli.inc').write_text(ddj.clean_stimuli(bits, Condition.parse(tag).supply, .4, 20e-12, .12))
        (dest / 'tb.cir').write_text(build(camp, tag, stop))
    sources = {str(p): sha(p) for p in (HERE, DDJ, ddj.TEMPLATE, ddj.DRIVER, ddj.BUFFER,
        ddj.EXPECTED, Path(spice.__file__), Path(bias.__file__), ROOT / 'src/serdes_flow/rcorner.py',
        Path(serial.__file__), Path(stage_metrics.__file__), Path(project.ngspice()))}
    for source in sources:
        dest = camp / 'execution' / source.lstrip('/'); dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, dest)
    dump(camp / 'plan.json', dict(conditions=list(TAGS), stop_s=stop, bits=bits, sequence_start_s=ddj.T0, ui_s=ddj.UI,
        input=dict(differential_pp_v=.4, edge_0to100_s=20e-12, cm_below_v=.12, balanced_until_s=7e-9),
        driver_params=PARAMS, python=sys.version, numpy=np.__version__, sources=sources,
        snapshots={str(p.relative_to(camp)): sha(p) for p in camp.rglob('*') if p.is_file()},
        experiment='Same clean training/payload and one real reference. Branch 1 off until 4ns; branch 2 enabled during the balanced DC operating point. Each has its own identical pad/package/10nF/RLC16/50ohm-to-0.9V load.',
        scope='Local output-state comparison only; no full serializer source impedance, noise/mismatch/PEX, power-up proof or fixed-resistor adoption.',
        op_policy='Balanced input at DC. Always-enabled branch starts from simulator DC solution, not a physically verified startup. Real bias nodeset as in existing ddj fixture.'))
    return camp


def check(camp):
    p = read(camp / 'plan.json')
    if p['conditions'] != list(TAGS) or (p['python'], p['numpy']) != (sys.version, np.__version__): raise ValueError('plan/runtime changed')
    for path, expected in p['sources'].items():
        if sha(path) != expected or sha(camp / 'execution' / path.lstrip('/')) != expected: raise ValueError('source changed: ' + path)
    for path, expected in p['snapshots'].items():
        if sha(camp / path) != expected: raise ValueError('snapshot changed: ' + path)
    return p


def completed(camp, tag, plan):
    raw = spice.case_output(camp, tag, 'waveforms.raw', plan['stop_s'])
    if raw is None: return None
    ex = read(raw.parent / 'execution.json')
    if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures']: return None
    if ex['deck_sha256'] != sha(camp / 'prepared' / tag / 'tb.cir') or sha(raw.parent / 'tb.cir') != ex['deck_sha256']:
        raise ValueError('executed deck differs')
    if sha(raw.parent / 'stimuli.inc') != sha(camp / 'prepared' / tag / 'stimuli.inc'): raise ValueError('executed stimulus differs')
    return raw


def measure(raw, plan):
    w = spice.Waves(raw); seq = serial.Sequence(np.asarray(plan['bits']), plan['sequence_start_s'], plan['ui_s'])
    out = dict(branches=[], bias_v=stage_metrics.telemetry(w.t, w['vbias'], 10e-9, 90e-9), vbg_v=stage_metrics.telemetry(w.t, w['bias_vbg'], 10e-9, 90e-9))
    for i, mode in ((1, 'enable_4ns'), (2, 'enabled_DC')):
        b = dict(mode=mode, windows=[], outputs={})
        for name, a, z in (('dc_solution', 0., .05e-9), ('early', 10e-9, 20e-9), ('late', 80e-9, 90e-9)):
            r = dict(name=name, start_s=a, stop_s=z)
            signals = dict(local_CM=(w[f'lqp{i}'] + w[f'lqn{i}']) / 2,
                remote_CM=(w[f'lrp{i}'] + w[f'lrn{i}']) / 2,
                remote_VCM_current=(w[f'lrp{i}'] + w[f'lrn{i}'] - 1.8) / 50,
                local_Rp_conduction=w[f'irp{i}'], local_Rn_conduction=w[f'irn{i}'], measured_tail_current=w[f'itail{i}'],
                tail_headroom=w[f'xdriver{i}.tail'] - w[f'vdsat{i}'], rail_power=w['vdd'] * w[f'i(vsense{i})'])
            for key, y in signals.items(): r[key] = stage_metrics.telemetry(w.t, y, a, z)
            b['windows'].append(r)
        for label, pos, neg in (('pad', f'lqp{i}', f'lqn{i}'), ('remote', f'lrp{i}', f'lrn{i}')):
            y = w[pos] - w[neg]; chk, _ = serial.check(w.t, y, seq, ddj.PAYLOAD)
            mapping = serial.bit_mapping(w.t, y, seq)
            b['outputs'][label] = dict(check=chk, mapping=mapping, local_draft_meets=bool(serial.meets_draft(chk)))
        out['branches'].append(b)
    return out


def resume(camp):
    with (camp / '.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); plan = check(camp)
        if any(p.is_relative_to(camp) for p in watch.ngspice_cwds()): raise RuntimeError('campaign active')
        dest = spice.next_run_dir(camp / 'analysis', 'measurement'); dest.mkdir(parents=True)
        result = dict(status='failed', plan_sha256=sha(camp / 'plan.json'), rows=[])
        try:
            for tag in TAGS:
                raw = completed(camp, tag, plan)
                if raw is None:
                    text = (camp / 'prepared' / tag / 'tb.cir').read_text(); stim = camp / 'prepared' / tag / 'stimuli.inc'
                    if len(watch.ngspice_cwds()) >= 4: raise RuntimeError('global ngspice limit')
                    sd = spice.next_run_dir(camp, 'smoke_' + tag)
                    ex = spice.run(re.sub(r'(?m)^tran .+$', 'tran 2p 1.001n 0 2p', text), sd, files={'stimuli.inc': stim}, timeout_s=180)
                    if not ex.ok or spice.case_output(camp, sd.name, 'waveforms.raw', 1.001e-9) is None: raise RuntimeError('smoke failed: ' + str(sd))
                    if len(watch.ngspice_cwds()) >= 4: raise RuntimeError('global ngspice limit')
                    ex = spice.run(text, spice.next_run_dir(camp, tag), files={'stimuli.inc': stim}, timeout_s=480, meta=dict(condition=tag))
                    if not ex.ok: raise RuntimeError('full case failed: ' + str(ex.run_dir))
                    raw = completed(camp, tag, plan)
                    if raw is None: raise RuntimeError('truncated output')
                result['rows'].append(dict(condition=tag, raw=str(raw.relative_to(ROOT)),
                    evidence={str(p.relative_to(ROOT)): sha(p) for p in (raw, raw.parent / 'tb.cir', raw.parent / 'execution.json', raw.parent / 'stimuli.inc', raw.parent / 'simulator.log')}, result=measure(raw, plan)))
            result['status'] = 'paired_local_state_measured_no_full_TX_qualification'
        except Exception as exc:
            result['error'] = f'{type(exc).__name__}: {exc}'; raise
        finally: dump(dest / 'summary.json', result)
    return dest / 'summary.json'


def main():
    p = argparse.ArgumentParser(description=__doc__); g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare', action='store_true'); g.add_argument('--resume', type=Path); a = p.parse_args()
    print(prepare() if a.prepare else resume(a.resume.resolve()))


if __name__ == '__main__': main()
