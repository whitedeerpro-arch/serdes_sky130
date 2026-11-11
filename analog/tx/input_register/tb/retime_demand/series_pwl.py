"""Independent series-PWL renderer for the calibrated retime demand card.

The original card remains untouched. A new campaign binds this file and its
renderer manifest; this adapter refuses to operate on old card campaigns.
"""
import importlib.util
import json
import re
from pathlib import Path

import numpy as np
from serdes_flow import spice, waves

HERE = Path(__file__).resolve()
RUNNER = HERE.with_name('run.py')
spec = importlib.util.spec_from_file_location('retime_series_base', RUNNER)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

COUNTS = {**{n: 16 for n in ('ap','an','bp','bn','sp','sn')},
          'vbias':4, 'vbias_logic':4, 'vdd':1}
VERSION = 'series_pwl_exact_v1'
BASE_TEMPLATE, BASE_SOURCES, BASE_CHECK, BASE_PREPARE = base.template, base.sources, base.check, base.prepare
PREPARING = False


def source_name(node, i):
    original = base.helper.SOURCE_MAP[node]
    return original if i == 0 else f'{original}_s{i:02d}'


def series_template():
    text = BASE_TEMPLATE()
    for node, count in COUNTS.items():
        original = base.helper.SOURCE_MAP[node]
        matches = re.findall(rf'(?mi)^{re.escape(original)}\s+(\S+)\s+(\S+)\s+PWL\([^\n]*\)\s*$', text)
        if len(matches) != 1:
            raise ValueError(f'original voltage source missing or ambiguous: {original}')
        positive, negative = matches[0]
        if negative != '0':
            raise ValueError('series renderer expects grounded voltage sources')
        lines = []
        for i in range(count):
            left = positive if i == 0 else f'series_{node}_{i}'
            right = negative if i == count-1 else f'series_{node}_{i+1}'
            lines.append(f'{source_name(node,i)} {left} {right} PWL(0 0 6n 0)')
        text, replaced = re.subn(rf'(?mi)^{re.escape(original)}\s+\S+\s+\S+\s+PWL\([^\n]*\)\s*$',
                                 '\n'.join(lines), text)
        if replaced != 1:
            raise ValueError('source replacement failed')
    return text


def series_parts(t, y, count):
    """Split an already compressed PWL into exact additive plateau functions."""
    t, y = np.asarray(t, dtype=float), np.asarray(y, dtype=float)
    if t.ndim != 1 or t.shape != y.shape or len(t) < 2 or t[0] != 0 or np.any(np.diff(t) <= 0) or count < 1:
        raise ValueError('invalid compressed PWL')
    actual = min(count, len(t)-1)
    bounds = np.linspace(0, len(t)-1, actual+1, dtype=int)
    result = []
    for j, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        tt = t[a:b+1].copy()
        yy = y[a:b+1].copy() if j == 0 else y[a:b+1] - y[a]
        if a:
            tt = np.r_[0.,tt]
            yy = np.r_[0.,yy]
        # Default PWL endpoint holding supplies the plateau. Keeping the
        # global stop time here would force finished segments to scan their
        # whole table instead of taking VSRCload's time > end_time shortcut.
        result.append((tt,yy))
    result.extend([(np.array([0.,t[-1]]),np.array([0.,0.])) for _ in range(count-actual)])
    # All segment breakpoints are global vertices; linearity guarantees the
    # error bound on every interval when the union of those vertices agrees.
    reconstruction = sum((np.interp(t, a, b) for a,b in result), np.zeros_like(y))
    error = float(np.max(np.abs(reconstruction-y)))
    if error > 1e-12:
        raise ValueError(f'series decomposition error {error:g} V')
    return result, error


def alter(source, t, y):
    vals = np.column_stack((t,y)).ravel()
    fmt = lambda x: f'{x:.17e}'
    out = [f'alter {source} dc={fmt(y[0])}']
    if len(vals) <= 360:
        return out + ['alter @'+source+'[pwl] = [ '+' '.join(map(fmt,vals))+' ]']
    return out + [f'let replay_pwl=vector({len(vals)})'] + [f'let replay_pwl[{i}]={fmt(v)}' for i,v in enumerate(vals)] + [
        'alter @'+source+'[pwl] = replay_pwl', 'unlet replay_pwl']


def render(camp, tag, ids):
    if len(ids) != 1 or ids[0] not in {p['id'] for p in base.POINTS}:
        raise ValueError('one declared experiment point per deck required')
    point = next(p for p in base.POINTS if p['id'] == ids[0])
    commands = []
    with np.load(camp/'inputs'/f'{tag}.npz') as data:
        for node, y in base.signals(data, point).items():
            offset = point['delay_ps']*1e-12 if node in ('sp','sn') else 0.
            ts, ys = waves.shift_pwl(data['t'], y, offset, tolerance_v=1e-5, time_quantum_s=1e-16)
            parts, _ = series_parts(ts,ys,COUNTS[node])
            for i,(t,v) in enumerate(parts):
                commands += alter(source_name(node,i),t,v)
        commands += [spice.skip_output_before(f'tran 1p {data["t"][-1]:.12e} 0 1p','.1n'),
                     f'write {ids[0]}.raw {base.VECTORS}', 'destroy all']
    template = (camp/'prepared'/f'{tag}.cir.in').read_text()
    if template.count('@CASES@') != 1:
        raise ValueError('prepared control block changed')
    return template.replace('@CASES@','\n'.join(commands))


def manifest():
    return {'renderer':VERSION, 'renderer_source_sha256':base.sha(HERE), 'segments':COUNTS,
            'extra_source_count':sum(COUNTS.values())-len(COUNTS),
            'compression_tolerance_v':1e-5, 'time_quantum_s':1e-16,
            'reconstruction_error_limit_v':1e-12,
            'scope':'Exact additive decomposition after original global shift_pwl; no circuit or acceptance change.'}


def check(camp, registered=False):
    plan, entry = BASE_CHECK(camp,registered=registered)
    path = camp/'renderer.json'
    if PREPARING and not path.exists():
        return plan,entry
    if not path.is_file() or json.loads(path.read_text()) != manifest():
        raise ValueError('series renderer manifest missing or changed')
    if plan['snapshots'].get('renderer.json') != base.sha(path):
        raise ValueError('series renderer manifest not bound to plan')
    if plan['sources'].get(str(HERE.relative_to(base.ROOT))) != base.sha(HERE):
        raise ValueError('series renderer source not bound to plan')
    return plan,entry


def prepare(campaigns):
    global PREPARING
    PREPARING = True
    try:
        camp = BASE_PREPARE(campaigns)
    finally:
        PREPARING = False
    path = camp/'renderer.json'
    path.write_text(json.dumps(manifest(),indent=2)+'\n')
    plan_path = camp/'plan.json'
    plan = json.loads(plan_path.read_text())
    plan['snapshots']['renderer.json'] = base.sha(path)
    plan_path.write_text(json.dumps(plan,indent=2)+'\n')
    check(camp)
    print(f'{VERSION}: {manifest()["extra_source_count"]} extra series voltage sources',flush=True)
    return camp


def install():
    base.template = series_template
    base.sources = lambda: list(dict.fromkeys(BASE_SOURCES()+[HERE]))
    base.render = render
    base.check = check
    base.prepare = prepare


install()
ROOT, POINTS = base.ROOT, base.POINTS
completed, measure = base.completed, base.measure


if __name__ == '__main__':
    print(f'renderer={VERSION}; extra_sources={manifest()["extra_source_count"]}',flush=True)
    base.main()
