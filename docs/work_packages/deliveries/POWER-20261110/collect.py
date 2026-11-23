"""Collect existing supply-waveform evidence without running a simulator."""
import hashlib
import json
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
CATALOG = Path('results/catalog/tx_full_pvt45.json')
RX_RAW = Path('results/analog/rx/sampler/cold_readout_full_transient_dc/20261109T134623.873301Z_0c20ee1d/transient_full/wave.raw')
OLD_RX_SUMMARY = Path('results/analog/rx/sampler/readout_deser/20261103T124408Z_ac_trim32/summary.json')
OLD_RX_DECK = OLD_RX_SUMMARY.parent / 'tt_v1800_t27/tb.cir'
OUTPUT = Path('docs/work_packages/deliveries/POWER-20261110/evidence.json')
EXTRA = [
    CATALOG,
    Path('docs/data/rx_cold_readout.json'),
    Path('results/analog/pll/top/native_k4/20261108T200611Z/tt_v1800_t27_tt/run/tb.cir'),
    Path('results/analog/pll/top/native_k4/20261108T200611Z/tt_v1800_t27_tt/run/loop.raw'),
    Path('analog/pll/top/spice/clock_frontend_r5.spice'),
    Path('analog/pll/top/spice/pll_core_r5k4.spice'),
]


def sha(path):
    h = hashlib.sha256()
    with (ROOT / path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def raw(path, required):
    path = ROOT / path
    with path.open('rb') as f:
        lines = []
        while True:
            line = f.readline()
            if not line:
                raise ValueError(f'{path}: EOF before binary data')
            lines.append(line)
            if line.strip() == b'Binary:':
                break
        offset = f.tell()
    header = b''.join(lines).decode('ascii')
    n = int(re.search(r'No. Variables: (\d+)', header)[1])
    points = int(re.search(r'No. Points: (\d+)', header)[1])
    names = re.findall(r'^\s*\d+\s+(\S+)\s+\S+', header, re.M)
    if len(names) != n or points < 2 or names[0] != 'time':
        raise ValueError(f'{path}: invalid vector table or point count')
    if path.stat().st_size != offset + points * n * 8:
        raise ValueError(f'{path}: binary size does not match header')
    if not set(required).issubset(names):
        raise ValueError(f'{path}: missing vectors {set(required) - set(names)}')
    values = np.memmap(path, dtype='<f8', mode='r', offset=offset, shape=(points, n))
    time = values[:, 0]
    if not np.all(np.isfinite(time)) or not np.all(np.diff(time) > 0):
        raise ValueError(f'{path}: nonfinite or nonincreasing time')
    for name in required:
        if not np.all(np.isfinite(values[:, names.index(name)])):
            raise ValueError(f'{path}: nonfinite {name}')
    return values, names


def mean_over_window(time, values, start, end):
    selected = (time >= start) & (time <= end)
    x, y = time[selected], values[selected]
    if x.size < 2:
        raise ValueError('integration window contains fewer than two points')
    integrate = getattr(np, 'trapezoid', None) or np.trapz
    return float(integrate(y, x) / (x[-1] - x[0])), [float(x[0] * 1e9), float(x[-1] * 1e9)]


def main():
    catalog = json.loads((ROOT / CATALOG).read_text())
    rows = {}
    for name, case in catalog['conditions'].items():
        base = Path(case['run'])
        path, deck = base / 'run/waveforms.raw', base / 'run/tb.cir'
        a, names = raw(path, ['v(vdd)', 'i(vdd)'])
        time, voltage, current = a[:, 0], a[:, names.index('v(vdd)')], a[:, names.index('i(vdd)')]
        power, window = mean_over_window(time, -voltage * current, 24e-9, 100e-9)
        amps, _ = mean_over_window(time, -current, 24e-9, 100e-9)
        rows[name] = {'mean_power_mw': power * 1e3, 'mean_current_ma': amps * 1e3,
                      'actual_window_ns': window, 'raw': str(path), 'raw_sha256': sha(path),
                      'deck': str(deck), 'deck_sha256': sha(deck)}
    a, names = raw(RX_RAW, ['power'])
    power, window = mean_over_window(a[:, 0], a[:, names.index('power')], 24e-9, 44e-9)
    deck = RX_RAW.parent / 'tb.cir'
    rx = {'condition': 'fs_v1650_t-40 hh', 'window_ns': window,
          'mean_power_mw_time_weighted': power * 1e3, 'raw': str(RX_RAW), 'raw_sha256': sha(RX_RAW),
          'deck': str(deck), 'deck_sha256': sha(deck)}
    old = json.loads((ROOT / OLD_RX_SUMMARY).read_text())
    old_rx = {'summary': str(OLD_RX_SUMMARY), 'sha256': sha(OLD_RX_SUMMARY),
              'tt_deck': str(OLD_RX_DECK), 'tt_deck_sha256': sha(OLD_RX_DECK),
              'power_mw_by_condition': {x['condition']: x['power_mw'] for x in old['rows']},
              'method': 'source summary sample arithmetic mean, 8-44.75 ns; ideal 0.85mA separate Vref excluded; legacy result, not current real bias PDK-R full 45'}
    out = {'method': 'Time-weighted trapezoidal mean -V(vdd)*I(Vdd), raw transient. Excludes power from other ideal sources. TX 24-100 ns; RX 24-44 ns.',
           'tx': rows, 'rx': rx, 'other_sha256': {str(p): sha(p) for p in EXTRA}, 'rx_historical_45': old_rx}
    (ROOT / OUTPUT).write_text(json.dumps(out, indent=2) + '\n')
    print('tx', len(rows), min((v['mean_power_mw'], k) for k, v in rows.items()),
          max((v['mean_power_mw'], k) for k, v in rows.items()),
          'tt', rows['tt_v1800_t27']['mean_power_mw'], 'rx', rx['mean_power_mw_time_weighted'])


if __name__ == '__main__':
    main()
