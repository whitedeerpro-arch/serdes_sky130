"""Joint CP/window threshold mismatch pilot. Prepare/check only until smoke reviewed.

Same sample, shared reference: three OPs at VDD/2, ladder vhi, and vhi+20mV.
The ladder threshold excludes comparator offset; this is not PLL startup/noise.
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

from serdes_flow import mc, project, spice, watch

ROOT = project.ROOT
SELF = Path(__file__).resolve()
OUT = ROOT / 'results/analog/pll/coarse/cp_handoff_mc'
INCLUDES = (
    'analog/common/devices/spice/sky130_primitives.spice',
    'analog/common/devices/spice/sky130_pfet_lvt.spice',
    'analog/common/devices/spice/cmos_logic.spice',
    'analog/bias/spice/bandgap.spice',
    'analog/bias/spice/bias_dist.spice',
    'analog/common/monitor/spice/monitor.spice',
    'analog/pll/coarse/spice/vctrl_window.spice',
    'analog/pll/cp/spice/charge_pump.spice',
    'analog/pll/cp/spice/charge_pump_steer.spice',
)
SOURCES = (str(SELF.relative_to(ROOT)), 'src/serdes_flow/mc.py', 'src/serdes_flow/spice.py',
           'src/serdes_flow/project.py', 'config/pdk.toml', 'config/tools.toml') + INCLUDES
CP = 'wn=20 wp=80 wsn=8 wsp=16 up_wn=2 up_wp=8 dn_wn=4 dn_wp=8 pnf=16 nnf=4 ntail=2 cdum=0.3p'
KEYS = ('midup', 'middn', 'vhi', 'hiup', 'hidn', 'plusup', 'plusdn',
        'vbg', 'vgi', 'vmid', 'vathigh', 'vatplus')
# Qualified writes preserve the same sample across OP plots; smoke must validate this ngspice syntax.
ANALYSIS = '''let const.midup = -1e30
let const.middn = -1e30
let const.vhi = -1e30
let const.hiup = -1e30
let const.hidn = -1e30
let const.plusup = -1e30
let const.plusdn = -1e30
let const.vbg = -1e30
let const.vgi = -1e30
let const.vmid = -1e30
let const.vathigh = -1e30
let const.vatplus = -1e30
alter Vout dc=0.825
op
let const.midup = i(eu)
let const.middn = i(ed)
let const.vhi = v(xw.vhi)
let const.vbg = v(vbg)
let const.vgi = v(vgi)
let const.vmid = v(sweep)
alter Vout dc=$&vhi
op
let const.hiup = i(eu)
let const.hidn = i(ed)
let const.vathigh = v(sweep)
let const.vplus = const.vhi + 0.020
alter Vout dc=$&vplus
op
let const.plusup = i(eu)
let const.plusdn = i(ed)
let const.vatplus = v(sweep)'''
LETS = {k: 'const.' + k for k in KEYS}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''): h.update(block)
    return h.hexdigest()


def pdk_manifest():
    root = project.model_library().parents[2]
    files = sorted(p for d in (root / 'libs.tech/ngspice', root / 'libs.ref/sky130_fd_pr/spice')
                   for p in d.rglob('*') if p.is_file())
    if not files: raise ValueError('missing PDK model files')
    return {str(p): sha(p) for p in files}


def netlist(camp, section, code_hi):
    includes = '\n'.join(f'.include "{camp / "snap" / rel}"' for rel in INCLUDES)
    return f'''Joint k4 CP and window ladder, same bias and mismatch sample
.lib "{project.model_library()}" {section}
{includes}
Vdd vdd 0 1.65
Vbias vb 0 1.65
Xref vbg i0 i1 i2 i3 vgi vdd 0 serdes_bias_ref
Vi0 i0 0 0.7
Vi1 i1 0 0.7
Vi2 i2 0 0.7
Vi3 i3 0 0.7
XIn vbn vgi vdd serdes_bias_pcopy n=20
XIp vbp vbn 0 0 serdes_nfet w=5 l=1
Xbn vbn vbn 0 0 serdes_nfet w=5 l=1
Xbp vbp vbp vb vb serdes_pfet w=20 l=1 nf=4
XIbu ibu vgi vdd serdes_bias_pcopy n=4
XIbd ibd vgi vdd serdes_bias_pcopy n=4
Xup vdd 0 ou vbn vbp ibu vdd 0 pll_cp_steer {CP}
Xdn 0 vdd od vbn vbp ibd vdd 0 pll_cp_steer {CP}
Vout sweep 0 0.825
Eu ou 0 sweep 0 1
Ed od 0 sweep 0 1
Xc1 ilo vgi vdd serdes_bias_pcopy n=2
Xc2 ihi vgi vdd serdes_bias_pcopy n=2
Xc3 ibh vgi vdd serdes_bias_pcopy n=1
Xc4 ibl vgi vdd serdes_bias_pcopy n=1
Xw z hi lo ilo ihi ibh ibl vdd 0 pll_vctrl_window code_lo=5 code_hi={code_hi}
Vz z 0 1.1
.nodeset v(vbg)=1.23 v(xref.xbg.s)=1.23 v(xref.vg)=0.9 v(vgi)=0.9 v(xref.xbg.ta)=0.95 v(xref.xbg.tb)=0.95
.temp 85
.options reltol=1e-4 abstol=1p vntol=1u
'''


def smoke_deck(camp, code_hi):
    lets = '\n'.join(f'let {k} = const.{k}' for k in KEYS)
    return (netlist(camp, 'sf_ll', code_hi) + '\n.control\nset num_threads=1\nset wr_vecnames\nset wr_singlescale\n'
            + ANALYSIS + '\n' + lets + '\nwrdata smoke.tsv ' + ' '.join(KEYS) + '\nquit\n.endc\n.end\n')


def prepare(samples, chunk, seed, code_hi):
    camp = OUT / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid4().hex[:8])
    camp.mkdir(parents=True, exist_ok=False)
    for rel in SOURCES:
        dest = camp / 'snap' / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest)
    for rel in INCLUDES:
        if re.search(r'^\s*\.(include|lib)\b', (camp / 'snap' / rel).read_text(), re.M | re.I):
            raise ValueError(f'nested include needs closure: {rel}')
    (camp / 'prepared').mkdir()
    (camp / 'prepared/smoke.cir').write_text(smoke_deck(camp, code_hi))
    chunks = []
    for index, chunk_seed, count in mc.chunks(samples, seed, chunk):
        name = f'chunk{index:02d}'
        path = camp / 'prepared' / (name + '.cir')
        path.write_text(mc.deck(netlist(camp, 'sf_ll_mm', code_hi), count, seed=chunk_seed, analysis=ANALYSIS, lets=LETS))
        chunks.append(dict(name=name, seed=chunk_seed, samples=count, deck=str(path.relative_to(camp))))
    files = sorted(p for sub in ('snap', 'prepared') for p in (camp / sub).rglob('*') if p.is_file())
    plan = dict(scope='pilot ungraded; SF/ll 1.65V 85C ladder vhi; comparator offset, startup and noise excluded',
                samples=samples, seed=seed, chunk=chunk, code_hi=code_hi, workers=1, cp_params=CP, chunks=chunks,
                pdk_installation_id=project.pdk_installation_id(), pdk_sha256=pdk_manifest(),
                snapshots={str(p.relative_to(camp)): sha(p) for p in files})
    (camp / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    return camp


def verify(camp):
    plan = json.loads((camp / 'plan.json').read_text())
    if plan['pdk_installation_id'] != project.pdk_installation_id() or plan['pdk_sha256'] != pdk_manifest():
        raise ValueError('PDK identity changed')
    if (plan['samples'] < 1 or plan['chunk'] < 1 or plan['seed'] < 0 or not 0 <= plan['code_hi'] <= 15
            or plan['workers'] != 1 or plan['cp_params'] != CP):
        raise ValueError('campaign identity changed')
    for rel, digest in plan['snapshots'].items():
        if sha(camp / rel) != digest: raise ValueError(f'snapshot changed: {rel}')
    for rel in SOURCES:
        if sha(ROOT / rel) != sha(camp / 'snap' / rel): raise ValueError(f'source changed: {rel}')
    if (camp / 'prepared/smoke.cir').read_text() != smoke_deck(camp, plan['code_hi']): raise ValueError('smoke deck changed')
    expected = mc.chunks(plan['samples'], plan['seed'], plan['chunk'])
    if len(plan['chunks']) != len(expected): raise ValueError('chunk count changed')
    for c, (index, seed, count) in zip(plan['chunks'], expected):
        text = mc.deck(netlist(camp, 'sf_ll_mm', plan['code_hi']), count, seed=seed, analysis=ANALYSIS, lets=LETS)
        if (c['name'], c['seed'], c['samples']) != (f'chunk{index:02d}', seed, count) or (camp / c['deck']).read_text() != text:
            raise ValueError('chunk identity changed')
    return plan


def validate(row):
    if any(k not in row or not math.isfinite(row[k]) for k in KEYS): return False
    return (0 < row['vhi'] < 1.63 and 0 < row['vbg'] < 1.65 and 0 < row['vgi'] < 1.65
            and abs(row['vmid'] - .825) < 1e-5 and abs(row['vathigh'] - row['vhi']) < 1e-5
            and abs(row['vatplus'] - row['vhi'] - .020) < 1e-5
            and all(row[k] > 1e-12 for k in ('midup', 'hiup', 'plusup'))
            and all(row[k] < -1e-12 for k in ('middn', 'hidn', 'plusdn')))


def smoke_valid(run, expected):
    try:
        ex = json.loads((run / 'execution.json').read_text())
        if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures'] or sha(run / 'tb.cir') != sha(expected): return False
        lines = (run / 'smoke.tsv').read_text().splitlines()
        if len(lines) != 2: return False
        fields = dict(zip(lines[0].split(), map(float, lines[1].split())))
        return validate(fields)
    except (OSError, ValueError, KeyError): return False


def resume(camp, smoke_only=False):
    with (camp / '.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = verify(camp)
        active = watch.ngspice_cwds()
        if len(active) >= 4 or any(p == camp or p.is_relative_to(camp) for p in active):
            raise RuntimeError('global quota or active campaign')
        smoke = camp / 'prepared/smoke.cir'
        attempts = [camp / 'smoke'] + sorted(camp.glob('smoke.r[0-9]*'))
        if not any(smoke_valid(p, smoke) for p in attempts):
            target = spice.next_run_dir(camp, 'smoke')
            spice.run(smoke.read_text(), target, timeout_s=240, meta={'phase': 'deterministic_three_op_smoke'})
            if not smoke_valid(target, smoke): raise RuntimeError(f'smoke failed: {target}; MC not started')
        if smoke_only:
            print('deterministic three-OP smoke complete; MC not started')
            return
        jobs = [( (camp / c['deck']).read_text(), camp / c['name'],
                  dict(timeout_s=240, meta={'seed': c['seed'], 'samples': c['samples'], 'scope': plan['scope']}))
                for c in plan['chunks']]
        dirs = mc.run_many(jobs, workers=1)
        rows = mc.read_all(dirs)
        failures = [i for i, r in enumerate(rows) if not validate(r)]
        # Check all log failures, beyond mc.complete's narrower convergence filter.
        for d in dirs:
            if json.loads((d / 'execution.json').read_text())['log_failures']:
                raise RuntimeError(f'log failures: {d}; no summary')
        if len(rows) != plan['samples'] or failures:
            raise RuntimeError(f'invalid sample rows {failures}; no summary')
        for r in rows:
            r['up_droop_hi'] = 1-r['hiup']/r['midup']
            r['dn_droop_hi'] = 1-r['hidn']/r['middn']
            r['up_droop_plus20mv'] = 1-r['plusup']/r['midup']
            r['dn_droop_plus20mv'] = 1-r['plusdn']/r['middn']
        out = camp / 'analysis' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid4().hex[:8])
        out.mkdir(parents=True, exist_ok=False)
        (out / 'summary.json').write_text(json.dumps(dict(scope=plan['scope'], spec_status='ungraded',
                                                          samples=plan['samples'], seed=plan['seed'], chunk=plan['chunk'],
                                                          code_hi=plan['code_hi'], rows=rows,
                                                          runs=[str(d.relative_to(ROOT)) for d in dirs]), indent=2, allow_nan=False) + '\n')
        print(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--check', type=Path)
    group.add_argument('--smoke', type=Path)
    group.add_argument('--resume', type=Path)
    ap.add_argument('--samples', type=int)
    ap.add_argument('--chunk', type=int)
    ap.add_argument('--seed', type=int)
    ap.add_argument('--code-hi', type=int)
    args = ap.parse_args()
    overrides = (args.samples, args.chunk, args.seed, args.code_hi)
    if not args.prepare and any(x is not None for x in overrides):
        ap.error('sample parameters may only be supplied with --prepare; resume uses the plan')
    samples, chunk, seed, code_hi = (x if x is not None else default for x, default in zip(overrides, (8, 4, 1, 3)))
    if samples < 1 or chunk < 1 or seed < 0 or not 0 <= code_hi <= 15:
        ap.error('samples/chunk must be positive, seed nonnegative, code-hi in 0..15')
    if args.prepare: print(prepare(samples, chunk, seed, code_hi))
    elif args.check: verify(args.check.resolve()); print('snapshot valid; no ngspice')
    elif args.smoke: resume(args.smoke.resolve(), smoke_only=True)
    else: resume(args.resume.resolve())


if __name__ == '__main__': main()
