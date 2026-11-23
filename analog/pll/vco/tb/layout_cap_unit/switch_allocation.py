"""Physical SVT leaves and an ideal-interconnect proxy for bank width allocation.

The proxy retains nine rectangles but omits inter-block routing/coupling and
uses independent bottom plates for the two b1 halves. It is not a routed bank.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

import numpy as np
from serdes_flow import bias, project, spice, watch

ROOT = project.ROOT
sys.path.insert(0, str(ROOT / 'analog/pll/vco/layout'))
from build_fused_cap_bank import group

PLAN = ROOT / 'analog/pll/vco/layout/plan/cap_bank_plan.json'
MAP = ROOT / 'results/analog/pll/vco/r6/map_20261112T062237Z/table.json'
PROFILES = dict(reference=[1.5]*5, proportional=[1.]*5,
                small_first=[2.2, 2., 1.2, 1., .75],
                large_first=[1., 1., 1., .6, 1.2])
CONDITIONS = [('tt', 'tt', 'tt', 1.8, 27),
              ('fs_hot_hh', 'fs', 'hh', 1.65, 85),
              ('ss_hot_hh', 'ss', 'hh', 1.65, 85),
              ('ss_cold_hh', 'ss', 'hh', 1.65, -40),
              ('ss_hot_ll', 'ss', 'll', 1.65, 85),
              ('sf_cold_ll', 'sf', 'll', 1.65, -40),
              ('ff_cold_ll', 'ff', 'll', 1.95, -40)]
FREQS = (20e6, 2e9)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')


def deck(c, condition, leaves):
    label, process, rc, vdd, temp = condition
    out = ['Physical leaves for switch allocation',
           f'.lib "{project.model_library()}" tt', f'.temp {temp}', 'Ven en 0 0']
    for i, leaf in enumerate(leaves):
        name = leaf['name']
        out += [f'.include "{c}/inputs/{name}.spice"',
                f'Vp{i} q{i} 0 dc 1.5 ac 1', f'X{i} q{i} en 0 {name}']
    out += ['.control', 'set num_threads=1', 'set wr_singlescale',
            'set wr_vecnames', 'set numdgt=12']
    for state, voltage in [('off', 0), ('on', vdd)]:
        out += [f'alter Ven dc={voltage}']
        for fi, f in enumerate(FREQS):
            out += [f'ac lin 1 {f} {f}']
            for i in range(len(leaves)):
                out += [f'let c{i}=-imag(i(vp{i}))/(2*pi*frequency)',
                        f'let g{i}=-real(i(vp{i}))']
            out += [f'wrdata {state}_{fi}.tsv ' + ' '.join(
                f'c{i} g{i}' for i in range(len(leaves))), 'destroy all']
    return bias.section('\n'.join(out + ['quit', '.endc', '.end', '']), process, rc)


def prepare():
    c = ROOT / 'results/analog/pll/vco/switch_allocation' / stamp()
    c.mkdir(parents=True)
    for name in ('inputs', 'prepared', 'source'):
        (c/name).mkdir()
    blocks = json.loads(PLAN.read_text())['blocks']
    leaves, profiles = [], {}
    for profile, densities in PROFILES.items():
        members = []
        for bit, density in enumerate(densities):
            block = blocks[f'b{bit}']
            n = block['units_eq']//block['count']
            name = f'n{n}_u{round(density*100):03d}'
            if not any(v['name'] == name for v in leaves):
                nf, fw = (n, density) if density <= 1 and n > 1 else (2*n, density/2)
                work = c/name
                work.mkdir()
                top, _, _ = group(work, n, block['w_um'], block['l_um'],
                                  switch_fingers=nf, finger_w=fw, body_wire_um=.28,
                                  solid_ground_return=True)
                net = (work/(top+'_cap.spice')).read_text()
                plate = re.search(r'^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1\b', net, re.M)[1]
                devices = re.findall(r'^X\S+ (\S+) en (\S+) vss sky130_fd_pr__nfet_01v8 .* w=([\d.]+) l=0.15$', net, re.M)
                if len(devices) != nf or any(abs(float(w)-fw)>1e-9 or {a,b}!={plate,'vss'} for a,b,w in devices):
                    raise ValueError('Wrong physical switch fingers/connectivity')
                net = net.replace(top, name)
                net = re.sub(r'^\.ends.*$', f'Rdc {plate} vss 125g\n.ends', net, flags=re.M)
                (c/'inputs'/(name+'.spice')).write_text(net)
                leaves.append(dict(name=name, units=n, density_um=density,
                                   fingers=nf, finger_width_um=fw,
                                   rectangle_um=[block['w_um'], block['l_um']]))
            members.append(dict(leaf=name, count=block['count'], bit=bit))
        profiles[profile] = dict(density_um=densities, members=members,
                                 total_width_um=sum((1<<b)*u for b,u in enumerate(densities)))
    for e in CONDITIONS:
        (c/'prepared'/(e[0]+'.cir')).write_text(deck(c, e, leaves))
    prefix = deck(c, CONDITIONS[0], leaves).split('.control')[0]
    smoke = prefix+'\n.save v(q0)\n.control\nset num_threads=1\ntran 2p 1n 0 2p\nwrdata smoke.tsv v(q0)\nquit\n.endc\n.end\n'
    (c/'prepared/smoke.cir').write_text(spice.binary_output(spice.skip_output_before(smoke, '0.2n')))
    for p in [Path(__file__).resolve(), ROOT/'analog/pll/vco/layout/build_fused_cap_bank.py',
              ROOT/'verification/layout/geometry.py', ROOT/'verification/layout/flat_cap_export.py', PLAN, MAP]:
        shutil.copyfile(p, c/'source'/p.name)
    plan = dict(conditions=CONDITIONS, frequencies_hz=FREQS, leaves=leaves,
                profiles=profiles, pdk_id=project.pdk_installation_id(),
                model_sha256=sha(project.model_library()),
                scope=__doc__, inputs={str(p.relative_to(c)):sha(p) for p in c.rglob('*') if p.is_file()})
    (c/'plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    print(c, flush=True)


def read(c, name, p):
    for d in reversed([c/name] + sorted(c.glob(name+'.r[0-9]*'))):
        try:
            ex = json.loads((d/'execution.json').read_text())
            if ex['exit_code'] or ex['timed_out'] or ex['log_failures']:
                continue
            if (d/'tb.cir').read_bytes() != (c/'prepared'/(name+'.cir')).read_bytes():
                continue
            values = {}
            for state in ('off', 'on'):
                for fi, f in enumerate(p['frequencies_hz']):
                    x = np.atleast_2d(np.loadtxt(d/f'{state}_{fi}.tsv', skiprows=1))
                    if x.shape != (1, 1+3*len(p['leaves'])) or not np.isfinite(x).all() or abs(x[0,0]/f-1)>1e-9:
                        raise ValueError('Incomplete AC output')
                    if not np.allclose(x[0,2::3], 0, rtol=0, atol=1e-25):
                        raise ValueError('Unexpected imaginary capacitance metric')
                    values[f'{state}_{fi}'] = {leaf['name']:dict(cap_ff=float(x[0,1+3*i])*1e15,
                        conductance_s=float(x[0,3+3*i])) for i,leaf in enumerate(p['leaves'])}
            return dict(run=str(d.relative_to(ROOT)), elapsed_s=ex['elapsed_s'], values=values)
        except (OSError, ValueError, KeyError):
            continue
    return None


def bank(values, members, code, fi):
    cap, conductance = 0., 0.
    for member in members:
        state = 'on' if code & (1<<member['bit']) else 'off'
        v = values[f'{state}_{fi}'][member['leaf']]
        cap += member['count']*v['cap_ff']
        conductance += member['count']*v['conductance_s']
    return dict(code=code, cap_ff=cap, conductance_s=conductance)


def resume(c):
    p = json.loads((c/'plan.json').read_text())
    if p['pdk_id'] != project.pdk_installation_id() or p['model_sha256'] != sha(project.model_library()):
        raise ValueError('PDK changed')
    for name, digest in p['inputs'].items():
        if sha(c/name) != digest:
            raise ValueError('Frozen input changed: '+name)
    if len(watch.ngspice_cwds())+2 > 4:
        raise ValueError('Global NG quota occupied')
    if spice.case_output(c, 'smoke', 'smoke.raw', t_end=1e-9) is None:
        d = spice.next_run_dir(c, 'smoke')
        ex = spice.run((c/'prepared/smoke.cir').read_text(), d, timeout_s=180)
        if not ex.ok or spice.Waves(d/'smoke.raw').t[-1] < 1e-9*(1-1e-9):
            raise ValueError('Smoke failed')
    jobs = [((c/'prepared'/(e[0]+'.cir')).read_text(), spice.next_run_dir(c,e[0]),dict(timeout_s=300))
            for e in p['conditions'] if read(c,e[0],p) is None]
    if jobs:
        spice.run_many(jobs, workers=2, smoke=False)
    code_map = json.loads((c/'source/table.json').read_text())['rows']
    rows = []
    for e in p['conditions']:
        r = read(c,e[0],p)
        if r is None:
            raise ValueError('Incomplete condition '+e[0])
        _, process, rc, vdd, temp = e
        key = f'{process}_v{round(vdd*1000)}_t{temp}:{rc}'
        old_code = code_map[key]['best']
        profiles = {}
        for name, profile in p['profiles'].items():
            freqs = []
            for fi, f in enumerate(p['frequencies_hz']):
                codes = [bank(r['values'],profile['members'],code,fi) for code in range(32)]
                caps = np.array([v['cap_ff'] for v in codes])
                g = np.array([v['conductance_s'] for v in codes])
                steps = np.diff(caps)
                freqs.append(dict(hz=f, codes=codes, coff_ff=float(caps[0]), con_ff=float(caps[-1]),
                    span_ff=float(caps[-1]-caps[0]), min_step_ff=float(min(steps)),
                    step_7_8_ff=float(steps[7]), step_15_16_ff=float(steps[15]),
                    monotonic=bool(np.all(steps>0)), max_conductance_s=float(max(g)),
                    old_code=old_code, at_old_code=codes[old_code],
                    q_code31=float(2*np.pi*f*caps[-1]*1e-15/g[-1])))
            profiles[name] = freqs
        rows.append(dict(condition=e, **r, profiles=profiles))
    grouped = {process:dict(best_codes=sorted({v['best'] for k,v in code_map.items() if k.startswith(process+'_')}),
                           msb_on_count=sum(bool(v['best']&16) for k,v in code_map.items() if k.startswith(process+'_')),
                           count=sum(k.startswith(process+'_') for k in code_map))
               for process in ('tt','ss','ff','fs','sf')}
    dest = c/'analysis'/stamp()
    dest.mkdir(parents=True)
    shutil.copyfile(Path(__file__), dest/'analysis.py')
    summary = dict(campaign=str(c.relative_to(ROOT)), plan_sha256=sha(c/'plan.json'),
                   profiles=p['profiles'], scope=p['scope'], code_map_by_process=grouped, rows=rows)
    (dest/'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
    print(dest/'summary.json', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare', action='store_true')
    g.add_argument('--resume', type=Path)
    args = parser.parse_args()
    if args.prepare:
        prepare()
    else:
        resume(args.resume.resolve())
