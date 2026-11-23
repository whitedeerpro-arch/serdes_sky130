"""Prepare, check and resume k4 steering-CP DC windows; no transient smoke.

One deck per MOS/resistor corner combines nine voltage/temperature conditions.
The single-condition DC smoke is a prerequisite for the grouped campaign.
"""
import argparse
import fcntl
import hashlib
import json
import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from serdes_flow import bias, project, spice, watch
from serdes_flow.corners import grid45

ROOT = project.ROOT
HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / 'tb_cp_steer_dc_ngspice.cir.in'
RESULTS = ROOT / 'results/analog/pll/cp/window_steer'
CP_PARAMS = 'wn=20 wp=80 wsn=8 wsp=16 up_wn=2 up_wp=8 dn_wn=4 dn_wp=8 pnf=16 nnf=4 ntail=2 cdum=0.3p'
DROPS = (0.36, 0.39, 0.41, 0.44)
INCLUDES = ('analog/common/devices/spice/sky130_primitives.spice',
            'analog/common/devices/spice/sky130_pfet_lvt.spice',
            'analog/common/devices/spice/cmos_logic.spice',
            'analog/bias/spice/bandgap.spice',
            'analog/bias/spice/bias_dist.spice',
            'analog/pll/cp/spice/charge_pump.spice',
            'analog/pll/cp/spice/charge_pump_steer.spice')
SOURCES = (str(Path(__file__).resolve().relative_to(ROOT)), str(TEMPLATE.relative_to(ROOT)),
           'src/serdes_flow/bias.py', 'src/serdes_flow/spice.py', 'src/serdes_flow/corners.py',
           'src/serdes_flow/project.py', 'config/pdk.toml', 'config/tools.toml') + INCLUDES


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def pdk_manifest():
    root = project.model_library().parents[2]
    files = sorted(p for d in (root / 'libs.tech/ngspice', root / 'libs.ref/sky130_fd_pr/spice')
                   for p in d.rglob('*') if p.is_file())
    if not files:
        raise ValueError('PDK model tree missing')
    return {str(p): sha(p) for p in files}


def deck(camp, process, rc, conds):
    text = spice.render(camp / 'snap' / TEMPLATE.relative_to(ROOT), **spice.corner_values(conds[0]),
                        CP_PARAMS=CP_PARAMS, IBIAS='* ibias: after bias.real')
    text = bias.section(bias.real(text), process, rc)
    text = text.replace('* ibias: after bias.real',
                        'XIbu ibu vgi_bias vdd serdes_bias_pcopy n=4\nXIbd ibd vgi_bias vdd serdes_bias_pcopy n=4')
    for rel in INCLUDES:
        text = text.replace(str(ROOT / rel), str(camp / 'snap' / rel))
    lines = ['.control', 'set num_threads=1', 'set filetype=binary']
    for c in conds:
        lines += [f'option temp={c.temp}', f'alter Vdd dc={c.supply}', f'alter Vbias dc={c.supply}',
                  f'dc Vout 0.1 {c.supply - 0.05:.3f} 0.01', f'write {c.tag}.raw i(Eu) i(Ed)', 'destroy all']
    return text[:text.rindex('.end')] + '\n'.join(lines + ['quit', '.endc', '.end', ''])


def prepare(passive, droop):
    camp = RESULTS / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid4().hex[:8])
    camp.mkdir(parents=True, exist_ok=False)
    for rel in SOURCES:
        target = camp / 'snap' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    for rel in INCLUDES:
        if re.search(r'^\s*\.(include|lib)\b', (camp / 'snap' / rel).read_text(), re.I | re.M):
            raise ValueError(f'nested include requires snapshot closure: {rel}')
    groups = {}
    for rc in passive:
        for c in grid45():
            groups.setdefault((c.process, rc), []).append(c)
    cases = []
    for (proc, rc), conds in groups.items():
        name = f'{proc}_{rc}'
        path = camp / 'prepared' / f'{name}.cir'
        path.parent.mkdir(exist_ok=True)
        path.write_text(deck(camp, proc, rc, conds))
        cases.append(dict(name=name, process=proc, passive=rc, tags=[c.tag for c in conds], deck=str(path.relative_to(camp))))
    smoke = next(c for c in grid45() if c.process == 'tt' and c.supply == 1.8 and c.temp == 27)
    path = camp / 'prepared' / 'smoke.cir'
    path.write_text(deck(camp, 'tt', 'tt', [smoke]))
    paths = sorted(p for d in ('snap', 'prepared') for p in (camp / d).rglob('*') if p.is_file())
    plan = dict(scope='DC diagnostic; real bias, k4 CP; PDK MOS and resistor corners; no noise or mismatch MC',
                cp_params=CP_PARAMS, droop=droop, passive=passive, cases=cases, smoke_tag=smoke.tag,
                pdk_installation_id=project.pdk_installation_id(), pdk_sha256=pdk_manifest(),
                snapshots={str(p.relative_to(camp)): sha(p) for p in paths})
    (camp / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    return camp


def verify(camp):
    plan = json.loads((camp / 'plan.json').read_text())
    if plan['cp_params'] != CP_PARAMS or project.pdk_installation_id() != plan['pdk_installation_id'] or pdk_manifest() != plan['pdk_sha256']:
        raise ValueError('CP parameters or PDK identity changed')
    for rel, digest in plan['snapshots'].items():
        if sha(camp / rel) != digest:
            raise ValueError(f'checkpoint changed: {rel}')
    # Current runner and shared generation/measurement helpers must match the saved version.
    for rel in SOURCES:
        if sha(ROOT / rel) != sha(camp / 'snap' / rel):
            raise ValueError(f'source changed: {rel}')
    conditions = {c.tag: c for c in grid45()}
    for case in plan['cases']:
        if (camp / case['deck']).read_text() != deck(camp, case['process'], case['passive'], [conditions[t] for t in case['tags']]):
            raise ValueError('prepared deck changed')
    smoke = conditions[plan['smoke_tag']]
    if (camp / 'prepared/smoke.cir').read_text() != deck(camp, 'tt', 'tt', [smoke]):
        raise ValueError('smoke deck changed')
    return plan


def measure(path, supply, threshold):
    w = spice.Waves(path)
    v = w.t
    up, dn = np.abs(w['i(eu)']), np.abs(w['i(ed)'])
    expected = np.arange(round((supply - .05 - .1) / .01) + 1) * .01 + .1
    if len(v) != len(expected) or not np.allclose(v, expected, rtol=0, atol=1e-7):
        raise ValueError(f'incomplete or invalid DC sweep: {path}')
    mid = int(np.argmin(np.abs(v - supply / 2)))
    if up[mid] <= 1e-12 or dn[mid] <= 1e-12:
        raise ValueError(f'zero mid current: {path}')
    ok = (np.abs(up / up[mid] - 1) <= threshold) & (np.abs(dn / dn[mid] - 1) <= threshold)
    lo = hi = mid
    while lo > 0 and ok[lo - 1]: lo -= 1
    while hi + 1 < len(v) and ok[hi + 1]: hi += 1
    return dict(lo=float(v[lo]), hi=float(v[hi]), up=float(up[mid]), dn=float(dn[mid]),
                mismatch=float(abs(up[mid] - dn[mid]) / ((up[mid] + dn[mid]) / 2)),
                droop_at={f'{d:.2f}': {'up': float(1 - np.interp(supply-d, v, up)/up[mid]),
                                          'dn': float(1 - np.interp(supply-d, v, dn)/dn[mid])} for d in DROPS})


def valid_run(run, deck_path, conds, threshold):
    try:
        ex = json.loads((run / 'execution.json').read_text())
        digest = sha(deck_path)
        if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256'] != digest or sha(run / 'tb.cir') != digest:
            return None
        return {c.tag: measure(run / f'{c.tag}.raw', c.supply, threshold) for c in conds}
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def completed(camp, name, path, conds, threshold):
    runs = [camp / name] + sorted(camp.glob(name + '.r[0-9]*'))
    for run in reversed(runs):
        result = valid_run(run, path, conds, threshold)
        if result is not None:
            return run, result
    return None


def resume(camp, workers, timeout):
    with (camp / '.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = verify(camp)
        active = watch.ngspice_cwds()
        if any(p == camp or p.is_relative_to(camp) for p in active):
            raise RuntimeError('campaign already has an active ngspice process')
        if len(active) + workers > 4:
            raise RuntimeError('requested workers exceed global four-ngspice quota')
        conditions = {c.tag: c for c in grid45()}
        smoke_path = camp / 'prepared/smoke.cir'
        smoke_conds = [conditions[plan['smoke_tag']]]
        if not completed(camp, 'smoke', smoke_path, smoke_conds, plan['droop']):
            run = spice.next_run_dir(camp, 'smoke')
            spice.run(smoke_path.read_text(), run, timeout_s=timeout, meta={'kind': 'single_condition_dc_smoke'})
            if valid_run(run, smoke_path, smoke_conds, plan['droop']) is None:
                raise RuntimeError(f'DC smoke failed: {run}; grouped campaign not started')
        jobs = []
        for case in plan['cases']:
            path = camp / case['deck']
            conds = [conditions[t] for t in case['tags']]
            if not completed(camp, case['name'], path, conds, plan['droop']):
                jobs.append((path.read_text(), spice.next_run_dir(camp, case['name']),
                             dict(timeout_s=timeout, meta={'process': case['process'], 'passive': case['passive']})))
        # The standard smoke helper requires transient analysis; the DC smoke above is explicit.
        for ex in spice.run_many(jobs, workers=workers, smoke=False):
            if not ex.ok: print(f'failed: {ex.run_dir}: {ex.log_failures[:2]}', flush=True)
        analyse(camp, plan)


def analyse(camp, plan):
    conditions = {c.tag: c for c in grid45()}
    rows, failures = {}, []
    for case in plan['cases']:
        conds = [conditions[t] for t in case['tags']]
        found = completed(camp, case['name'], camp / case['deck'], conds, plan['droop'])
        if found is None:
            failures.append(case['name'])
            continue
        run, data = found
        for c in conds:
            rows[f'{c.tag}:{case["passive"]}'] = dict(supply=c.supply, run=str(run.relative_to(ROOT)), **data[c.tag])
    summary = dict(scope=plan['scope'], spec_status='ungraded', droop=plan['droop'], cp_params=CP_PARAMS,
                   expected_conditions=sum(len(c['tags']) for c in plan['cases']), completed_conditions=len(rows),
                   incomplete_groups=failures, rows=rows)
    out = camp / 'analysis' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
    print(f'{len(rows)}/{summary["expected_conditions"]} conditions; incomplete groups: {failures}; {out}')
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--check', type=Path)
    mode.add_argument('--resume', type=Path)
    mode.add_argument('--analyse', type=Path)
    ap.add_argument('--passive', default='tt,hh,ll')
    ap.add_argument('--droop', type=float, default=.05)
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--timeout', type=float, default=1800)
    a = ap.parse_args()
    passive = a.passive.split(',')
    if not passive or len(set(passive)) != len(passive) or any(x not in ('tt', 'hh', 'll') for x in passive): ap.error('invalid passive corners')
    if not math.isfinite(a.droop) or not 0 < a.droop < 1: ap.error('droop must be between 0 and 1')
    if not 1 <= a.workers <= 4: ap.error('workers must be 1 to 4')
    if not math.isfinite(a.timeout) or a.timeout <= 0: ap.error('timeout must be positive')
    if a.prepare: print(prepare(passive, a.droop))
    elif a.check: verify(a.check.resolve()); print('checkpoint valid; no ngspice')
    elif a.resume: resume(a.resume.resolve(), a.workers, a.timeout)
    else:
        camp = a.analyse.resolve()
        analyse(camp, verify(camp))


if __name__ == '__main__': main()
