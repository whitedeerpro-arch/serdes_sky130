"""Frozen r6 native-loop prepare, smoke, resume and analysis entry point."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
from types import SimpleNamespace

import numpy as np
from serdes_flow import project, spice, watch
from serdes_flow.corners import Condition

ROOT = project.ROOT
SELF = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location('native_r6_base', SELF.with_name('run.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(map_path, points, variants, stop, pre_offset=.04):
    if not np.isfinite(stop) or stop <= 55e-9 or not np.isfinite(pre_offset):
        raise ValueError('Stop must extend beyond reset release and pre-offset must be finite')
    if set(variants) - {'ext', 'hv'}:
        raise ValueError('Unknown supply variant')
    c = base.RESULTS / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    (c / 'prepared').mkdir(parents=True, exist_ok=False)
    table = json.loads(map_path.read_text())['rows']
    trims = json.loads(base.LDO_DATA.read_text())['calibration_codes']
    args = SimpleNamespace(stop=stop, pre_offset=pre_offset, vin=3.3)
    entries = []
    for point in points:
        cond, rc = point.split(':')
        condition = Condition.parse(cond)
        for variant in variants:
            key, code, voltage = base.entry(table, point, variant, 0)
            trim = trims[f'{condition.process}:{rc}']['trim']
            name = base.case_dir(Path('.'), point, variant).name
            text = base.deck(condition, rc, code, voltage, variant, trim, args, c / 'snap')
            path = c / 'prepared' / (name + '.cir')
            path.write_text(text)
            # Explicit 1 ns smoke: output retention begins at zero for this
            # separate deck, rather than silently simulating to saved-start+1ns.
            smoke = re.sub(r'^tran .*$', 'tran 4p 1n 0 4p', text, flags=re.M)
            if smoke == text:
                raise ValueError('Transient anchor changed')
            (c / 'prepared' / (name + '_smoke.cir')).write_text(smoke)
            entries.append(dict(name=name, point=point, variant=variant, code=code,
                                vctrl_model_v=voltage, vco_entry=key, trim=trim, t_end_s=stop))
    sources = {SELF, SELF.with_name('run.py'), map_path, base.LDO_DATA,
               ROOT / 'analog/pll/top/tb/native_k4/run.py',
               *[ROOT / p for p in base.INCLUDES],
               *[ROOT / p for p in base.bias.BIAS_INC],
               *[ROOT / 'src/serdes_flow' / (n + '.py') for n in
                 ('spice', 'clock', 'waves', 'bias', 'rcorner', 'project', 'corners', 'watch')]}
    for src in sorted(sources):
        dst = c / 'source' / src.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    plan = dict(entries=entries, pre_offset_v=pre_offset, vin_v=3.3,
                pdk_id=project.pdk_installation_id(),
                external_sha256={str(p): sha(p) for p in (project.model_library(), Path(base.SC_LIB))},
                source_sha256={str(p.relative_to(ROOT)): sha(p) for p in sources},
                snapshots={str(p.relative_to(c)): sha(p) for p in c.rglob('*') if p.is_file()},
                scope='r6 schematic, fixed-width PDK resistors, real shared bias; ideal external reference/rail for ext; precharge and explicit divider kicks; not power-up, PEX, TX or stochastic-noise qualification')
    (c / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    return c


def check(c):
    plan = json.loads((c / 'plan.json').read_text())
    if plan['pdk_id'] != project.pdk_installation_id():
        raise ValueError('PDK installation changed')
    for name, digest in plan['external_sha256'].items():
        if sha(name) != digest:
            raise ValueError('External library changed: ' + name)
    for name, digest in plan['snapshots'].items():
        if sha(c / name) != digest:
            raise ValueError('Frozen input changed: ' + name)
    # Execution and analysis code must retain the prepared identity. Circuit
    # inputs are the frozen copies used by the decks, not current workspace DUTs.
    for name, digest in plan['source_sha256'].items():
        if name.startswith('src/') or name.startswith('analog/pll/top/tb/'):
            if sha(ROOT / name) != digest:
                raise ValueError('Runner/analysis changed; prepare a new campaign: ' + name)
    return plan


def completed(c, entry, smoke=False):
    name = entry['name'] + ('_smoke' if smoke else '')
    deck = (c / 'prepared' / (name + '.cir')).read_text()
    for d in reversed([c / name] + sorted(c.glob(name + '.r[0-9]*'))):
        try:
            ex = json.loads((d / 'execution.json').read_text())
            if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures']:
                continue
            if (d / 'tb.cir').read_text() != deck:
                continue
            w = spice.Waves(d / 'loop.raw')
            end = 1e-9 if smoke else entry['t_end_s']
            if w.t[-1] < end * (1 - 1e-9) or not np.all(np.isfinite(w.data)):
                continue
            if any(v not in w for v in base.PROBES.split()):
                continue
            return d
        except (OSError, ValueError, KeyError):
            pass
    return None


def analyse(c):
    p = check(c)
    rows = []
    for e in p['entries']:
        d = completed(c, e)
        row = dict(e, state='missing', smoke_complete=completed(c, e, True) is not None)
        if d:
            try:
                metrics = base.analyse(d / 'loop.raw', None)
                row.update(state='measured', run=str(d.relative_to(ROOT)), metrics=metrics)
            except (ValueError, IndexError, KeyError) as err:
                row.update(state='analysis_error', error=str(err))
        rows.append(row)
    out = c / 'analysis' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out.mkdir(parents=True, exist_ok=False)
    result = dict(campaign=str(c.relative_to(ROOT)), plan_sha256=sha(c / 'plan.json'),
                  rows=rows, scope=p['scope'])
    (out / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    print(out.relative_to(ROOT), flush=True)
    return result


def resume(c, workers, smoke_only, timeout):
    with (c / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        p = check(c)
        if len(watch.ngspice_cwds()) + workers > 4:
            raise ValueError('Global ngspice slots occupied')
        def one(e):
            for smoke in (True,) if smoke_only else (True, False):
                if completed(c, e, smoke):
                    continue
                name = e['name'] + ('_smoke' if smoke else '')
                deck = (c / 'prepared' / (name + '.cir')).read_text()
                d = spice.next_run_dir(c, name)
                ex = spice.run(deck, d, timeout_s=timeout,
                               meta=dict(point=e['point'], smoke=smoke, plan_sha256=sha(c / 'plan.json')))
                print(name, 'elapsed', round(ex.elapsed_s, 2), 'execution_ok', ex.ok, flush=True)
                if not completed(c, e, smoke):
                    break
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, p['entries']))
        return analyse(c)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--check', type=Path)
    group.add_argument('--resume', type=Path)
    group.add_argument('--analyse', type=Path)
    ap.add_argument('--map', type=Path)
    ap.add_argument('--points', default='tt_v1800_t27:tt')
    ap.add_argument('--variants', default='ext')
    ap.add_argument('--stop', type=float, default=1.2e-6)
    ap.add_argument('--pre-offset', type=float, default=.04)
    ap.add_argument('--workers', type=int, choices=(1, 2), default=1)
    ap.add_argument('--smoke-only', action='store_true')
    ap.add_argument('--timeout', type=float, default=1200)
    a = ap.parse_args()
    if a.prepare:
        if not a.map:
            ap.error('--prepare requires --map pointing at table.json')
        print(prepare(a.map.resolve(), a.points.split(','), a.variants.split(','), a.stop, a.pre_offset))
    elif a.check:
        print('validated', len(check(a.check.resolve())['entries']), 'frozen cases')
    elif a.analyse:
        analyse(a.analyse.resolve())
    else:
        resume(a.resume.resolve(), a.workers, a.smoke_only, a.timeout)
