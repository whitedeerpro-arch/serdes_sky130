"""Compare ideal static VCO control windows using only bracketed measured curves.

This does not qualify PLL startup, noise, or dynamic re-coding. Fill curves are
used whole when complete; source curves are never merged or averaged with them.
"""
import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

from serdes_flow.corners import Condition, grid45

TARGET = 2e9
VLO = .90
DROPS = {'3': .41, '4': .44, '5': .47}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def curve(vs, f, swing, label):
    if not isinstance(vs, list) or not isinstance(f, list) or not isinstance(swing, list):
        raise ValueError(f'{label}: vs/f/swing must be lists')
    if len(vs) < 2 or len(vs) != len(f) or len(vs) != len(swing):
        raise ValueError(f'{label}: incomplete curve')
    if any(not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) for a in (vs, f, swing) for x in a):
        raise ValueError(f'{label}: nonfinite or nonnumeric curve')
    if any(b <= a for a, b in zip(vs, vs[1:])):
        raise ValueError(f'{label}: voltage grid must increase')
    return {'vs': vs, 'f': f, 'swing': swing}


def unpack(data, source):
    result = {}
    for condition, row in data['rows'].items():
        tag, rc = condition.split(':')
        Condition.parse(tag)
        if rc not in ('tt', 'hh', 'll'): raise ValueError(f'invalid resistor corner {rc}')
        vs = data['vs'] if source else row['vs']
        if set(row['f']) != set(row['swing']): raise ValueError(f'{condition}: code keys differ')
        for code, f in row['f'].items():
            if not code.isdigit() or not 0 <= int(code) <= 15: raise ValueError(f'{condition}: invalid code {code}')
            result[(condition, int(code))] = curve(vs, f, row['swing'][code], f'{condition} code {code}')
    return result


def crossings(c):
    """Return every 2 GHz crossing on a measured adjacent interval, with segment Kvco."""
    out = []
    for i in range(len(c['vs']) - 1):
        v0, v1 = c['vs'][i:i+2]
        f0, f1 = c['f'][i:i+2]
        if f0 == f1 or not min(f0, f1) <= TARGET <= max(f0, f1): continue
        v = v0 + (TARGET - f0) * (v1 - v0) / (f1 - f0)
        if out and abs(out[-1]['v'] - v) < 1e-12: continue
        out.append(dict(v=v, kvco_hz_per_v=(f1-f0)/(v1-v0), bracket_v=[v0, v1], bracket_hz=[f0, f1]))
    return out


def analyse(source, fill, source_hash, fill_hash, source_path, fill_path):
    if fill.get('source_summary_sha256') != source_hash:
        raise ValueError('fill source summary hash does not match supplied source')
    original, extra = unpack(source, True), unpack(fill, False)
    partial = fill.get('partial_rows')
    if not isinstance(partial, list): raise ValueError('fill partial_rows missing')
    duplicates = []
    for key in sorted(original.keys() & extra.keys()):
        a, b = original[key], extra[key]
        for i, v in enumerate(a['vs']):
            for j, w in enumerate(b['vs']):
                if abs(v-w) < 1e-9:
                    duplicates.append(dict(condition=key[0], code=key[1], voltage=v, source_hz=a['f'][i],
                                           fill_hz=b['f'][j], fill_minus_source_hz=b['f'][j]-a['f'][i]))
    combined = {**original, **extra}
    valid_conditions = {f'{c.tag}:{rc}' for c in grid45() for rc in ('tt', 'hh', 'll')}
    if any(k[0] not in valid_conditions for k in combined): raise ValueError('curve outside 135-condition grid')
    conditions = {}
    for c in grid45():
        for rc in ('tt', 'hh', 'll'):
            name = f'{c.tag}:{rc}'
            curves = {}
            for (tag, code), data in combined.items():
                if tag != name: continue
                curves[str(code)] = dict(origin='fill' if (tag, code) in extra else 'source', crossings=crossings(data))
            windows = {}
            for code, drop in DROPS.items():
                high = c.supply - drop
                candidates = sorted(int(k) for k, row in curves.items() if any(
                    VLO <= x['v'] <= high and x['kvco_hz_per_v'] > 0 for x in row['crossings']))
                endpoint = curves.get('15', {}).get('crossings', [])
                windows[code] = dict(vlo=VLO, vhi=high, candidates=candidates,
                                     status='evidenced_code' if candidates else 'no_evidenced_code',
                                     code15_crossing_below_vlo=[x for x in endpoint if x['v'] < VLO])
            conditions[name] = dict(curves=curves, windows=windows)
    chips = defaultdict(dict)
    for condition, record in conditions.items():
        tag, rc = condition.split(':'); c = Condition.parse(tag)
        key = f'{c.process}_v{round(c.supply*1000)}:{rc}'
        chips[key][c.temp] = record
    fixed = {}
    for key, per_temp in chips.items():
        if set(per_temp) != {-40, 27, 85}: raise ValueError(f'{key}: missing temperature')
        fixed[key] = {}
        for code in DROPS:
            common = set.intersection(*(set(per_temp[t]['windows'][code]['candidates']) for t in (-40, 27, 85)))
            fixed[key][code] = dict(codes=sorted(common), status='evidenced_common_code' if common else 'no_evidenced_code')
    counts = {code: dict(conditions_with_code=sum(bool(v['windows'][code]['candidates']) for v in conditions.values()),
                         fixed_chips_with_common_code=sum(bool(v[code]['codes']) for v in fixed.values()),
                         code15_below_vlo_conditions=sum(bool(v['windows'][code]['code15_crossing_below_vlo']) for v in conditions.values()))
              for code in DROPS}
    return dict(scope='static ideal thresholds separated by 30 mV; measured 30 fF per-leg proxy; positive Kvco candidates only; no startup/noise or dynamic recoding qualification; actual comparator thresholds, mismatch and dynamic headroom excluded',
                interpolation='2 GHz bracket of adjacent measured points only; Kvco is segment secant',
                source_path=str(source_path), source_sha256=source_hash, fill_path=str(fill_path), fill_sha256=fill_hash,
                fill_partial=bool(partial), partial_rows=partial, duplicate_observations=duplicates,
                curve_counts={'source': len(original), 'fill': len(extra), 'selected': len(combined)},
                counts=counts, conditions=conditions, fixed_three_temperature=fixed)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--fill', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    result = analyse(json.loads(a.source.read_text()), json.loads(a.fill.read_text()), sha(a.source), sha(a.fill), a.source, a.fill)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open('x') as f: json.dump(result, f, indent=2, allow_nan=False); f.write('\n')
    print(f'{a.out}: {len(result["conditions"])} conditions, {len(result["fixed_three_temperature"])} chips; partial={result["fill_partial"]}')


if __name__ == '__main__': main()
