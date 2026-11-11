"""Supplementary pin/geometry audit for flat, four-terminal teaching inverters.

Deliberately narrow: it does not replace LVS or handle arbitrary SPICE aliases,
hierarchy or device types. Detects an unused exported D pin even if a netlist
matcher removes it and reports an otherwise matching internal topology.
"""
import argparse
import json
from pathlib import Path


def audit(path, cell):
    logical = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('*'):
            continue
        if line.startswith('+'):
            logical[-1] += ' ' + line[1:]
        else:
            logical.append(line)
    active, ports, devices, unknown = False, None, [], []
    kinds = {'sky130_fd_pr__nfet_01v8': 'n', 'sky130_fd_pr__pfet_01v8': 'p'}
    for line in logical:
        tokens = line.split()
        if tokens[0].lower() == '.subckt':
            active = tokens[1] == cell
            if active:
                ports = tokens[2:]
        elif tokens[0].lower() == '.ends':
            active = False
        elif active:
            if tokens[0][0].upper() != 'X' or len(tokens) < 6 or tokens[5] not in kinds:
                unknown.append(line)
                continue
            params = dict(t.split('=', 1) for t in tokens[6:] if '=' in t)
            try:
                values = {k: float(v) for k, v in params.items()}
                width, length = values['w'], values['l']
            except (ValueError, KeyError):
                unknown.append(line)
                continue
            devices.append(dict(instance=tokens[0], kind=kinds[tokens[5]], model=tokens[5],
                                terminals=dict(zip(('D', 'G', 'S', 'B'), tokens[1:5])),
                                w_um=width, l_um=length, params=values))
    if ports is None or unknown:
        return dict(status='ungraded', reason='missing top or unsupported non-flat/aliased view', unknown=unknown)
    errors = []
    if ports != ['d', 'g', 'vdd', 'vss']:
        errors.append('external port order differs from d g vdd vss')
    usage = {p: [f'{x["instance"]}.{terminal}' for x in devices for terminal, net in x['terminals'].items() if net == p]
             for p in ports}
    errors += ['unused exported port: ' + p for p, uses in usage.items() if not uses]
    for x in devices:
        t = x['terminals']
        rail = 'vss' if x['kind'] == 'n' else 'vdd'
        if t['G'] != 'g' or t['B'] != rail or {t['D'], t['S']} != {'d', rail}:
            errors.append(x['instance'] + ': does not connect the exported inverter nets')
        if abs(x['l_um'] - .15) > 1e-9:
            errors.append(x['instance'] + ': channel length changed')
    widths = {k: sum(x['w_um'] * x['params'].get('m', 1) for x in devices if x['kind'] == k) for k in ('n', 'p')}
    if abs(widths['n'] - 4) > 1e-9 or abs(widths['p'] - 8) > 1e-9:
        errors.append('total MOS widths differ from N4/P8 µm')
    junction = {}
    for kind in ('n', 'p'):
        if not usage.get('d'):
            junction[kind] = dict(output_diffusion_area_um2=None, output_diffusion_perimeter_um=None,
                                  reason='exported D has no device connection')
            continue
        area, perimeter, missing_geometry = 0., 0., False
        for x in devices:
            if x['kind'] != kind:
                continue
            t, params = x['terminals'], x['params']
            for terminal, akey, pkey in [('D', 'ad', 'pd'), ('S', 'as', 'ps')]:
                if t[terminal] == 'd':
                    if akey not in params or pkey not in params:
                        missing_geometry = True
                        continue
                    area += params[akey]
                    perimeter += params[pkey]
        junction[kind] = dict(output_diffusion_area_um2=None if missing_geometry else area,
                             output_diffusion_perimeter_um=None if missing_geometry else perimeter)
    return dict(status='fail' if errors else 'pass', errors=errors, ports=ports, port_usage=usage,
                devices=devices, total_w_um=widths, output_junction=junction,
                scope='Flat inverter D/G/S/B and N4/P8/L0.15 only; AD/AS are µm² and PD/PS µm in this Magic view; no arbitrary hierarchy or electrical signoff.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('netlist', type=Path)
    p.add_argument('--cell', required=True)
    a = p.parse_args()
    result = audit(a.netlist, a.cell)
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(0 if result['status'] == 'pass' else 1)
