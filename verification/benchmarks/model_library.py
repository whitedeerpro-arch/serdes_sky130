"""Measure reduced-library cost and electrical equivalence on a small CML card.

Cost baseline: 2 ns / 2 ps, three MOS/RC corners, scalar OP and 20 MHz AC.
This short card deliberately separates library/setup overhead from long-circuit
solver cost; it does not select a minimum production VCO observation window.
One worker, explicit opt-in models, original PDK untouched. No MC qualification.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
import uuid

import numpy as np

from serdes_flow import clock, model_library, project, scalar_raw, spice, watch

ROOT = project.ROOT
HERE = Path(__file__).resolve()
DEVICES = ['sky130_fd_pr__' + x for x in ('nfet_01v8', 'pfet_01v8', 'nfet_01v8_lvt', 'res_high_po_2p85')]
CASES = [('tt', 1.8, 27), ('ss_hh', 1.65, -40), ('ff_ll', 1.95, 85)]
NODES = ['op', 'on', 'tail', 'dp', 'dn', 'i(vdd)']


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p, d): p.write_text(json.dumps(d, indent=2, allow_nan=False) + '\n')


def deck(library, section, vdd, temp, stop=2e-9):
    signals = ' '.join(n if n.startswith('i(') else 'v(' + n + ')' for n in NODES)
    return f'''Library reduction nominal comparison
.lib "{library}" {section}
.temp {temp}
Vdd vdd 0 {vdd}
Vip ip 0 DC {vdd-.3} AC .5 PULSE({vdd-.4} {vdd-.2} .25n 20p 20p .23n .5n)
Vin inn 0 DC {vdd-.3} AC .5 180 PULSE({vdd-.2} {vdd-.4} .25n 20p 20p .23n .5n)
Vbias bias 0 .85
Xnp op ip tail 0 sky130_fd_pr__nfet_01v8_lvt w=12 l=.15
Xnn on inn tail 0 sky130_fd_pr__nfet_01v8_lvt w=12 l=.15
Xt tail bias 0 0 sky130_fd_pr__nfet_01v8 w=4 l=.5
Xrp vdd op 0 sky130_fd_pr__res_high_po_2p85 l=4.77
Xrn vdd on 0 sky130_fd_pr__res_high_po_2p85 l=4.77
Cop op 0 30f
Con on 0 30f
Ipp dp 0 20u
Xpp dp dp vdd vdd sky130_fd_pr__pfet_01v8 w=5 l=1
Inn vdd dn 20u
Xnref dn dn 0 0 sky130_fd_pr__nfet_01v8 w=5 l=1
.save {signals}
.control
set num_threads=1
set filetype=binary
echo SETUP_RESOURCE_USAGE
rusage
op
write dc.raw {signals}
ac lin 1 20meg 20meg
let out_re=real(v(op)-v(on))
let out_im=imag(v(op)-v(on))
write ac.raw out_re out_im
tran 2p {stop:.15e} 0 2p
write transient.raw {signals}
echo FINAL_RESOURCE_USAGE
rusage
quit
.endc
.end
'''


def compare(full, reduced):
    dc = []
    a, b = spice.Waves(full/'dc.raw'), spice.Waves(reduced/'dc.raw')
    for n in NODES:
        error = float(np.max(abs(a[n]-b[n])))
        limit = 1e-11 if n.startswith('i(') else 1e-8
        dc.append(dict(node=n, max_abs_error=error, limit=limit, passed=error<=limit))
    a, b = scalar_raw.read(full/'ac.raw', frequency_hz=20e6), scalar_raw.read(reduced/'ac.raw', frequency_hz=20e6)
    ac = {n: dict(error=abs(a[n]-b[n]), passed=bool(np.isclose(a[n], b[n], rtol=1e-8, atol=1e-10))) for n in ('out_re','out_im')}
    a, b = spice.Waves(full/'transient.raw'), spice.Waves(reduced/'transient.raw')
    if min(a.t[-1],b.t[-1])<2e-9*(1-1e-6): raise ValueError('truncated comparison')
    tran = []
    for n in NODES:
        error = float(np.max(abs(a[n]-np.interp(a.t,b.t,b[n]))))
        limit = 1e-10 if n.startswith('i(') else 1e-7
        tran.append(dict(node=n, max_abs_error=error, limit=limit, passed=error<=limit))
    return dict(dc=dc, ac=ac, transient=tran,
                passed=all(x['passed'] for x in dc+tran) and all(x['passed'] for x in ac.values()))


def vco_card():
    """Use one recorded r6 map circuit, with one explicit nominal operating point."""
    origin=ROOT/'results/analog/pll/vco/r6/map_20261112T062237Z/tt_tt/tb.cir'
    body=origin.read_text().split('.control')[0]
    inputs=[origin]+[Path(x) for x in re.findall(r'(?im)^\.include "([^"]+)"',body)]
    texts=[body]
    for p in inputs[1:]:
        text=p.read_text()
        if re.search(r'(?im)^\s*\.inc(?:lude)?\s',text):raise ValueError('nested VCO source needs explicit freezing')
        texts.append(text)
    devices=set()
    for text in texts:
        for line in text.splitlines():
            if re.match(r'(?i)^\s*[xmdqrc]\w',line):
                devices.update(re.findall(r'(?i)\bsky130_fd_pr__\w+',line))
    entry=json.loads((origin.parents[1]/'table.json').read_text())['rows']['tt_v1800_t27:tt']
    code=entry['best'];voltage=round(entry['v'][str(code)],3)
    def render(lib,stop=14e-9):
        text,n=re.subn(r'(?im)^\.lib "[^"]+" tt$',lambda _:f'.lib "{lib}" tt',body)
        if n!=1:raise ValueError('nominal VCO model section mismatch')
        commands=['.control','set num_threads=1','set filetype=binary','rusage','option temp=27',
                  'alter Vdd dc=1.8','alter Vref dc=1.8',f'alter Vctrl dc={voltage}']
        commands += [f'alter Vb{k} dc={1.8 if code&(1<<k) else 0}' for k in range(5)]
        commands += [f'tran 4p {stop:.15e} {8e-9 if stop>8e-9 else 0:.15e}',
                     'write transient.raw v(v0p) v(v0n)','rusage','quit','.endc','.end']
        return text+'\n'+'\n'.join(commands)+'\n'
    return render,sorted(devices),dict(code=code,vctrl=voltage,supply=1.8,temp=27,
                                      sources={str(p.relative_to(ROOT)):sha(p) for p in inputs})


def compare_vco(full,reduced):
    a,b=spice.Waves(full/'transient.raw'),spice.Waves(reduced/'transient.raw')
    if min(a.t[-1],b.t[-1])<14e-9*(1-1e-6):raise ValueError('truncated VCO comparison')
    errors={n:float(np.max(abs(a[n]-np.interp(a.t,b.t,b[n])))) for n in ('v0p','v0n')}
    frequencies=[]
    for w in (a,b):
        e=clock.edges(w.t,w['v0p']-w['v0n'],1,start=9e-9)
        if len(e)<6:raise ValueError('insufficient VCO measurement cycles')
        frequencies.append(float((len(e)-1)/(e[-1]-e[0])))
    relative=abs(frequencies[1]/frequencies[0]-1)
    return dict(frequency_hz=frequencies,relative_frequency_error=relative,
                max_abs_node_error_v=errors,limits=dict(node_v=1e-6,relative_frequency=1e-7),
                passed=max(errors.values())<=1e-6 and relative<=1e-7)


def main():
    camp = ROOT/'results/verification/model_library'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    camp.mkdir(parents=True)
    source = camp/'execution'; source.mkdir()
    for p in (HERE,Path(model_library.__file__),Path(spice.__file__),Path(scalar_raw.__file__)):
        target=source/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(p,target)
    report = dict(status='running',scope='nominal OP/20MHz AC/2ns transient, four primitive families; warm-cache short-card cost, not full SerDes or MC',
                  devices=DEVICES, sources={str(p.relative_to(ROOT)):sha(p) for p in (HERE,Path(model_library.__file__),Path(spice.__file__),Path(scalar_raw.__file__))},
                  ngspice_sha256=sha(project.ngspice()),pdk=project.pdk_installation_id(),cases=[])
    try:
        for index,(section,vdd,temp) in enumerate(CASES):
            started=time.monotonic()
            reduced=model_library.build(project.model_library(),section,DEVICES,camp/section/'models')
            row=dict(section=section,vdd=vdd,temp=temp,build_s=time.monotonic()-started,runs={})
            report['cases'].append(row)
            # Alternate order so one variant is not systematically second.
            modes=('full','reduced') if index%2==0 else ('reduced','full')
            for mode in modes:
                lib=project.model_library() if mode=='full' else reduced
                if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice limit')
                if index==0:
                    smoke=spice.run(deck(lib,section,vdd,temp,1.001e-9),camp/section/('smoke_'+mode),timeout_s=90)
                    if not smoke.ok or spice.case_output(camp/section,'smoke_'+mode,'transient.raw',1.001e-9) is None:
                        raise RuntimeError('smoke failed: '+mode)
                if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice limit')
                run=camp/section/mode
                result=spice.run(deck(lib,section,vdd,temp),run,timeout_s=90)
                row['runs'][mode]=dict(elapsed_s=result.elapsed_s,ok=result.ok,run=str(run.relative_to(ROOT)))
                if not result.ok:raise RuntimeError('comparison run failed: '+str(run))
            row['comparison']=compare(camp/section/'full',camp/section/'reduced')
            if not row['comparison']['passed']:raise ValueError('electrical equivalence gate failed')
            row['short_card_speed_ratio']=row['runs']['full']['elapsed_s']/row['runs']['reduced']['elapsed_s']
        render,devices,identity=vco_card()
        reduced=model_library.build(project.model_library(),'tt',devices,camp/'r6_tt'/'models')
        vco=dict(identity=identity,devices=devices,runs={});report['vco']=vco
        for mode,lib in (('full',project.model_library()),('reduced',reduced)):
            if len(watch.ngspice_cwds())>=4:raise RuntimeError('global ngspice limit')
            smoke=spice.run(render(lib,1.001e-9),camp/'r6_tt'/('smoke_'+mode),timeout_s=90)
            if not smoke.ok or spice.case_output(camp/'r6_tt','smoke_'+mode,'transient.raw',1.001e-9) is None:
                raise RuntimeError('VCO smoke failed: '+mode)
            if len(watch.ngspice_cwds())>=4:raise RuntimeError('global ngspice limit')
            result=spice.run(render(lib),camp/'r6_tt'/mode,timeout_s=180)
            vco['runs'][mode]=dict(elapsed_s=result.elapsed_s,ok=result.ok)
            if not result.ok:raise RuntimeError('VCO comparison failed: '+mode)
        vco['comparison']=compare_vco(camp/'r6_tt'/'full',camp/'r6_tt'/'reduced')
        if not vco['comparison']['passed']:raise ValueError('VCO equivalence gate failed')
        vco['speed_ratio']=vco['runs']['full']['elapsed_s']/vco['runs']['reduced']['elapsed_s']
        for p,h in identity['sources'].items():
            if sha(ROOT/p)!=h:raise ValueError('VCO circuit changed')
        if any(sha(ROOT/p)!=h for p,h in report['sources'].items()):raise ValueError('benchmark source changed')
        report['status']='three_corner_short_card_and_one_r6_VCO_equivalent_no_production_adoption'
    except Exception as exc:
        report['error']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        report['evidence']={str(p.relative_to(camp)):sha(p) for p in camp.rglob('*') if p.is_file()}
        dump(camp/'summary.json',report)
        print(camp/'summary.json',flush=True)


if __name__=='__main__':main()
