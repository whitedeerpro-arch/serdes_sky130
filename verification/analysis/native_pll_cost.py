"""Offline prefix review of the two completed native PLL supply TT waveforms.

Run: uv run python verification/analysis/native_pll_cost.py
The derived raw files are crops of existing simulations, not new simulations.
"""
import hashlib
import importlib.util
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from serdes_flow import spice
from serdes_flow.project import ROOT

SOURCE = ROOT / 'results/analog/pll/top/native_k4_supply/20261110T133803Z'
NK = ROOT / 'analog/pll/top/tb/native_k4/run.py'
SUPPLY = ROOT / 'analog/pll/top/tb/native_k4_supply/run.py'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    nk, supply = module(NK, 'cost_native'), module(SUPPLY, 'cost_supply')
    dest = ROOT / 'results/analog/pll/top/native_cost_review' / time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    dest.mkdir(parents=True, exist_ok=False)
    out = {'kind': 'offline cropped analysis; not new simulation', 'source': str(SOURCE.relative_to(ROOT)),
           'analysis_sha256': {str(p.relative_to(ROOT)): sha(p) for p in (NK, SUPPLY, Path(__file__))},
           'scope': 'TT 1.8 V 27 C precharged, hv and ext only; not evidence for stress corners',
           'timing_note': 'Elapsed includes whole ngspice execution; logs show gmin stepping but contain no phase timing, so OP time cannot be apportioned.', 'cases': {}}
    for variant in ('hv', 'ext'):
        case = SOURCE / f'tt_v1800_t27_tt_{variant}' / 'run'
        ex = json.loads((case / 'execution.json').read_text())
        deck, raw, log = case / 'tb.cir', case / 'loop.raw', case / 'simulator.log'
        assert ex['point'] == 'tt_v1800_t27:tt' and ex['variant'] == variant
        assert ex['exit_code'] == 0 and not ex['timed_out'] and not ex['log_failures']
        assert sha(deck) == ex['deck_sha256']
        assert re.search(r'(?m)^tran 4p 1\.5000e-06 40n 4p$', deck.read_text())
        assert spice.case_output(case.parent, 'run', 'loop.raw', 1.5e-6) == raw
        w = spice.Waves(raw)
        assert len(w.t) > 370000 and w.t[-1] >= 1.5e-6 * (1 - 1e-6)
        logtext = log.read_text(errors='replace')
        assert 'gmin stepping' in logtext.lower()
        header = raw.read_bytes().split(b'Binary:\n', 1)[0]
        record = {'elapsed_s': ex['elapsed_s'], 'points': len(w.t), 'raw_t_start_s': float(w.t[0]),
                  'raw_t_end_s': float(w.t[-1]), 'tran_maxstep_s': 4e-12, 'tran_stop_s': 1.5e-6,
                  'sha256': {p.name: sha(p) for p in (deck, raw, log, case / 'execution.json')}, 'prefixes': {}}
        for ns in (600, 800, 1000, 1500):
            count = int(np.searchsorted(w.t, ns * 1e-9, side='right'))
            # Include the final sample at the requested stop if floating point rounding differs.
            if ns == 1500:
                count = len(w.t)
            path = dest / f'{variant}_{ns}ns.raw'
            h = re.sub(rb'No\. Points: \d+', f'No. Points: {count}'.encode(), header)
            with path.open('wb') as f:
                f.write(h + b'Binary:\n')
                f.write(np.asarray(w.data[:count], dtype='<f8').tobytes())
            result = dict(nk.analyse(path, SimpleNamespace()), **supply.rails(path))
            record['prefixes'][str(ns)] = {'end_s': float(w.t[count - 1]), 'points': count, 'raw_sha256': sha(path), **result}
        out['cases'][variant] = record
    text = json.dumps(out, indent=2, allow_nan=False) + '\n'
    (dest / 'review.json').write_text(text)
    (ROOT / 'docs/data/native_pll_cost.json').write_text(text)
    catalog = {'kind': out['kind'], 'source': out['source'], 'review': str(dest.relative_to(ROOT)),
               'data': 'docs/data/native_pll_cost.json', 'analysis_sha256': out['analysis_sha256'],
               'cases': {k: {'sha256': v['sha256']} for k, v in out['cases'].items()}}
    (ROOT / 'results/catalog/native_pll_cost.json').write_text(json.dumps(catalog, indent=2) + '\n')
    print(text)
    print(dest.relative_to(ROOT))


if __name__ == '__main__':
    main()
