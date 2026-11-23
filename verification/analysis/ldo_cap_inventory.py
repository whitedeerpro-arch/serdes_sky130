"""Inventory selected current analog roots, counting instantiated caps once.

This deliberately does not sum all historical SPICE definitions or behavioural
simulation integrators into a chip-area number. Shared bias roots are separate.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from serdes_flow import netlist
from serdes_flow.project import ROOT


FILES = [ROOT/p for p in (
    'analog/bias/spice/bandgap.spice',
    'analog/bias/spice/bias_dist.spice',
    'analog/ldo/spice/ldo_passives.spice',
    'analog/ldo/spice/ldo_hv18_core_smallcap.spice',
    'analog/ldo/spice/pll_supply_hv18_smallcap.spice',
    'analog/ldo/spice/pll_bias_filter_r4.spice',
    'analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice',
    'analog/pll/loop_filter/spice/passive_rc_precharge.spice')]
ROOTS = [('serdes_pll_supply_hv18_smallcap', 'LDO70pF candidate, excludes shared BG and tail filter'),
         ('serdes_pll_bias_lowpass_slow_r4', 'one PLL tail filter, separate from LDO'),
         ('pll_loop_filter_k4', 'PLL loop integrator, not supply decoupling'),
         ('serdes_bias_ref', 'one shared reference, not counted per LDO'),
         ('serdes_bias_cml', 'one local CML diode, multiple modules may instantiate it')]


def inventory():
    # Resolve canonical primitive locations from the LDO's actual source list.
    import importlib.util
    sp=importlib.util.spec_from_file_location('ldo_inventory_parent',ROOT/'analog/ldo/tb/cap_sizing/run.py')
    caps=importlib.util.module_from_spec(sp);sp.loader.exec_module(caps)
    files=list(dict.fromkeys([*caps.r4.reg.BIAS,*[p for p in FILES if p.exists()]]))
    subs=netlist.parse(files)
    rows=[]
    for top,scope in ROOTS:
        devices,unknown=netlist.flatten(subs,top)
        groups=defaultdict(float)
        for d in devices:
            if d.kind=='C':value=d.value*1e12
            elif d.model=='sky130_fd_pr__cap_mim_m3_1':
                if abs(d.w-22.1965)>1e-6 or abs(d.l-22.1965)>1e-6:
                    raise ValueError('Uncalibrated MIM geometry: '+d.path)
                value=1.0  # nominal unit; exact PDK/extracted value is separate
            else:continue
            path=d.path.split('.')
            if path[0]=='xloop':path=path[1:]
            key='.'.join(path[:2]) if path[0] in ('xcore','xbg') else path[0]
            groups[key]+=value
        rows.append(dict(top=top,scope=scope,nominal_pf=sum(groups.values()),
                         branches=sorted([dict(instance=k,nominal_pf=v) for k,v in groups.items()],key=lambda r:-r['nominal_pf']),
                         unknown_subcircuits=sorted(unknown)))
    return dict(scope='Selected roots only; no chip total; nominal capacitors, excludes device/wire parasitics',
                sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},rows=rows)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();data=inventory();args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:json.dump(data,f,indent=2);f.write('\n')
    print(json.dumps(data['rows'],indent=2))
