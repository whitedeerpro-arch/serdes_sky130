"""TT physical reference-string DC comparison; prepare/resume only.

One calibration deck plus one physical deck containing fifteen independent
mode/trim instances, evaluated at three temperatures. This is not a startup qualification.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import uuid

import numpy as np

from serdes_flow import poly_geometry, project, scalar_raw, spice, watch

ROOT = project.ROOT
HERE = Path(__file__).resolve()
WIDE = ROOT / 'analog/common/devices/tb/passive_card/wide_load_card.py'
WIDE_DATA = ROOT / 'docs/data/wide_load_card.json'
WIDE_INDEX = ROOT / 'results/catalog/wide_load_card.json'
BG = ROOT / 'analog/bias/spice/bandgap.spice'
DIST = ROOT / 'analog/bias/spice/bias_dist.spice'
DEPS = [ROOT / p for p in ('analog/common/devices/spice/sky130_primitives.spice',
                             'analog/common/devices/spice/sky130_pfet_lvt.spice')]
RESULTS = ROOT / 'results/analog/bias/physical_reference_card'
TRIMS = (0, 14, 15, 16, 31)
TEMPS = (-40, 27, 85)
NOMINAL = {'rref': 112000, 'rt4': 12480, 'rt3': 6240, 'rt2': 3120, 'rt1': 1560, 'rt0': 780}
MODES = ('generic', 'fixed_s1', 'fixed_s8')
NODES = ('vbg', 's', 'rt5', 'rt4', 'rt3', 'rt2', 'rt1', 'vg', 'vgi', 'vbias')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def read(path): return json.loads(Path(path).read_text())
def dump(path, data): Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def wide_module():
    spec = importlib.util.spec_from_file_location('physical_reference_wide', WIDE)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def identity():
    wide = read(WIDE_DATA); index = read(WIDE_INDEX)
    if index['data_sha256'] != sha(WIDE_DATA) or wide['status'] != 'calibrated_wide_poly_planning_no_adoption':
        raise ValueError('wide card data identity/status mismatch')
    if sha(ROOT / wide['summary']) != wide['summary_sha256']:
        raise ValueError('wide card measurement identity mismatch')
    overlay = wide_module().overlay()
    if wide['overlay'] != overlay: raise ValueError('wide overlay differs')
    curve = wide['curves']['1p41']
    if curve['max_error_ohm'] > 1e-3: raise ValueError('wide calibration curve inaccurate')
    return dict(wide_data_sha256=sha(WIDE_DATA), wide_index_sha256=sha(WIDE_INDEX),
                wide_summary=wide['summary'], wide_summary_sha256=wide['summary_sha256'], curve=curve, overlay=overlay)


def calibration_deck(library):
    lines = ['actual w=1 bandgap reference segment calibration', f'.lib "{library}" tt', 'Vrail rail 0 1.8']
    for name, nominal in NOMINAL.items():
        lines += [f'Vport_{name} out_{name} 0 1.55',
                  f'X{name} rail out_{name} 0 sky130_fd_pr__res_high_po w=1 l={(nominal-378)/317:.15g}']
    lines += ['.temp 27', '.options reltol=1e-6 abstol=1p vntol=1n', '.control', 'set num_threads=1', 'set filetype=binary', 'op']
    lines += [f'let r_{name}=0.25/i(Vport_{name})' for name in NOMINAL]
    lines += ['write calibration.raw ' + ' '.join('r_' + name for name in NOMINAL), 'quit', '.endc', '.end']
    return '\n'.join(lines) + '\n'


def geometries(curve, measured):
    result = {}
    for name in NOMINAL:
        target = float(measured['r_' + name])
        if not np.isfinite(target) or target <= 0: raise ValueError('invalid generic resistance')
        for sections in ((1, 8) if name == 'rref' else (1,)):
            g = poly_geometry.parallel(target / sections, 1, curve, minimum_length=.5, grid=.01)
            if g is None: raise ValueError(f'{name} {sections} sections outside calibrated domain')
            result[f'{name}_{sections}'] = g
    return result


def variant(text, mode, dimensions):
    if mode not in MODES: raise ValueError('unknown variant')
    name = 'serdes_bandgap_' + mode
    for subckt in ('serdes_bandgap', 'serdes_bg_amp', 'serdes_bg_ota', 'serdes_ref_vbuf'):
        text = re.sub(r'\b' + subckt + r'\b', subckt + '_' + mode, text)
    if text.count('.subckt ' + name + ' ') != 1 or text.count('.ends ' + name) != 1:
        raise ValueError('bandgap subcircuit identity mismatch')
    if mode == 'generic': return text
    replacements = {'rref': ('s', 'rt5'), 'rt4': ('rt5', 'rt4'), 'rt3': ('rt4', 'rt3'),
                    'rt2': ('rt3', 'rt2'), 'rt1': ('rt2', 'rt1'), 'rt0': ('rt1', 'vss')}
    for label, (left, right) in replacements.items():
        count = 8 if label == 'rref' and mode == 'fixed_s8' else 1
        nodes = [left] + [f'rref_mid{i}' for i in range(1, count)] + [right]
        g = dimensions[f'{label}_{count}']
        lines = [poly_geometry.instances(label + '_' + str(i), nodes[i], nodes[i+1], 'vss', g, '1p41') for i in range(count)]
        text, n = re.subn(rf'(?m)^X{label} .*$', lambda _: '\n'.join(lines), text)
        if n != 1: raise ValueError('original reference resistor missing or duplicated: ' + label)
    return text


def case_name(mode, trim):
    if mode not in MODES or trim not in TRIMS: raise ValueError('unsupported case')
    return f'{mode}_trim{trim}'


def wrapper(mode, trim):
    # Distinct external nodes and source names per case; only ideal VDD/ground are shared.
    case = case_name(mode, trim)
    n = lambda signal: f'{case}_{signal}'
    bg = 'Xbg_' + case
    lines = [f'{bg} {n("vbg")} {n("i0")} {n("i1")} {n("i2")} {n("i3")} {n("vg")} {n("vgi")} vdd 0 serdes_bandgap_{mode} trim={trim} cvgi=2p',
             f'Cbg_{case} {n("vbg")} 0 5p']
    lines += [f'Vi{k}_{case} {n("i" + str(k))} 0 0.7' for k in range(4)]
    lines += [f'Vcopy_{case} vdd {n("vcopy")} 0',
              f'Xcopy_{case} {n("vbias")} {n("vgi")} {n("vcopy")} serdes_bias_pcopy n=85',
              f'Xdiode_{case} {n("vbias")} 0 serdes_bias_cml',
              f'.nodeset v({n("vbg")})=1.23 v({bg}.s)=1.23 v({n("vg")})=0.9 v({n("vgi")})=0.9 v({bg}.ta)=0.95 v({bg}.tb)=0.95']
    return '\n'.join(lines)


def signal_map(mode, trim):
    case = case_name(mode, trim)
    n = lambda signal: f'{case}_{signal}'
    bg = 'xbg_' + case
    return {'vbg': f'v({n("vbg")})', 's': f'v({bg}.s)',
            **{f'rt{k}': f'v({bg}.rt{k})' for k in range(1, 6)},
            'vg': f'v({n("vg")})', 'vgi': f'v({n("vgi")})', 'vbias': f'v({n("vbias")})',
            **{f'iout{k}': f'i(Vi{k}_{case})' for k in range(4)}, 'icopy': f'i(Vcopy_{case})'}


def output_names():
    return [f'{case_name(mode, trim)}_t{temp}.raw' for temp in TEMPS for mode in MODES for trim in TRIMS]


def physical_deck(camp, library):
    paths = [camp/'snap'/p.relative_to(ROOT) for p in DEPS + [DIST]]
    lines = ['physical reference: 15 independent mode/trim circuits', f'.lib "{library}" tt']
    lines += [f'.include "{p}"' for p in paths]
    lines += [f'.include "{camp / "variants" / (mode + ".spice")}"' for mode in MODES]
    lines += ['Vdd vdd 0 1.8']
    lines += [wrapper(mode, trim) for mode in MODES for trim in TRIMS]
    lines += ['.options reltol=1e-5 abstol=1p vntol=1u', '.control', 'set num_threads=1', 'set filetype=binary']
    for temp in TEMPS:
        lines += [f'option temp={temp}', 'op']
        for mode in MODES:
            for trim in TRIMS:
                case = case_name(mode, trim)
                signals = signal_map(mode, trim)
                lines += [f'let obs_{k}={v}' for k, v in signals.items()]
                lines += [f'write {case}_t{temp}.raw ' + ' '.join('obs_' + k for k in signals)]
        lines += ['destroy all']
    return '\n'.join(lines + ['quit', '.endc', '.end', '']) + '\n'


def source_paths():
    paths = [HERE, WIDE, WIDE.with_name('fixed_load_card.py'), WIDE_DATA, WIDE_INDEX, BG, DIST, *DEPS,
             Path(poly_geometry.__file__), Path(scalar_raw.__file__), Path(spice.__file__), Path(watch.__file__),
             Path(project.__file__), ROOT/'config/pdk.toml', ROOT/'config/tools.toml',
             ROOT/'config/ngspice/spiceinit', Path(project.ngspice())]
    return list(dict.fromkeys(paths))


def prepare():
    ident = identity(); camp = RESULTS/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    camp.mkdir(parents=True, exist_ok=False)
    for source in source_paths():
        dst = camp/'execution'/str(source).lstrip('/'); dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source,dst)
    for source in [BG,DIST,*DEPS]:
        dst=camp/'snap'/source.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dst)
    (camp/'prepared').mkdir(); (camp/'prepared/calibration.cir').write_text(calibration_deck(ident['overlay']['library']))
    plan = dict(status='prepared_not_simulated', identity=ident, python=sys.version, numpy=np.__version__,
                temperatures=list(TEMPS), trims=list(TRIMS), modes=list(MODES), supply_v=1.8,
                sources={str(p):sha(p) for p in source_paths()},
                snapshots={str(p.relative_to(camp)):sha(p) for d in ('snap','prepared') for p in (camp/d).rglob('*') if p.is_file()},
                scope='TT DC operating points only; real bandgap and five trim MOS, n85 CML copy and diode. Other bandgap Rs generic; amplifier Rz ideal. A selected OP is not startup, PVT, noise or physical-layout qualification.',
                output_current_convention='iout0..3 positive into ideal 0.7 V sink; icopy positive from VDD into n85 PMOS copy.')
    dump(camp/'plan.json',plan); check(camp);return camp


def check(camp):
    plan=read(camp/'plan.json')
    if plan['identity']!=identity() or (plan['python'],plan['numpy'])!=(sys.version,np.__version__) or plan['trims']!=list(TRIMS) or plan['modes']!=list(MODES) or plan['temperatures']!=list(TEMPS):raise ValueError('plan identity differs')
    for path,h in plan['sources'].items():
        if sha(path)!=h or sha(camp/'execution'/path.lstrip('/'))!=h:raise ValueError('source changed: '+path)
    for path,h in plan['snapshots'].items():
        if sha(camp/path)!=h:raise ValueError('snapshot changed: '+path)
    return plan


def complete(camp,label,text,outputs):
    candidates=[camp/label]+[p for p in camp.glob(label+'.r*') if p.name.rsplit('.r',1)[1].isdigit()]
    expected=hashlib.sha256(text.encode()).hexdigest()
    for path in sorted(candidates,key=lambda p:spice._rerun_index(p,label),reverse=True):
        try:
            ex=read(path/'execution.json')
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures']:continue
            if ex['deck_sha256']!=expected or sha(path/'tb.cir')!=expected or ex.get('case')!=label:raise ValueError('case execution identity mismatch')
            for name in outputs:scalar_raw.read(path/name)
            return path
        except FileNotFoundError:continue
    return None


def run_case(camp,label,text,outputs):
    run=complete(camp,label,text,outputs)
    if run:return run
    if len(watch.ngspice_cwds())>=4:raise RuntimeError('global ngspice limit')
    ex=spice.run(text,spice.next_run_dir(camp,label),timeout_s=240,meta=dict(case=label))
    if not ex.ok:raise RuntimeError('case failed: '+str(ex.run_dir))
    run=complete(camp,label,text,outputs)
    if run is None:raise RuntimeError('missing complete outputs')
    return run


def resume(camp):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);plan=check(camp)
        if any(p.is_relative_to(camp) for p in watch.ngspice_cwds()):raise RuntimeError('campaign active')
        out=spice.next_run_dir(camp/'analysis','measurement');out.mkdir(parents=True)
        report=dict(status='failed',plan_sha256=sha(camp/'plan.json'),rows=[],evidence={})
        try:
            cal=run_case(camp,'calibration',(camp/'prepared/calibration.cir').read_text(),['calibration.raw'])
            raw=scalar_raw.read(cal/'calibration.raw'); dims=geometries(plan['identity']['curve'],raw)
            frozen=dict(calibration_values={k:raw['r_'+k] for k in NOMINAL},geometry=dims)
            path=camp/'dimensions.json'
            if path.exists() and read(path)!=frozen:raise ValueError('calibration geometry identity changed')
            if not path.exists():dump(path,frozen)
            (camp/'variants').mkdir(exist_ok=True)
            for mode in MODES:
                path=camp/'variants'/(mode+'.spice'); expected=variant((camp/'snap'/BG.relative_to(ROOT)).read_text(),mode,dims)
                if path.exists() and path.read_text()!=expected:raise ValueError('variant snapshot changed')
                if not path.exists():path.write_text(expected)
            report['dimensions_sha256']=sha(camp/'dimensions.json')
            report['variant_sha256']={m:sha(camp/'variants'/(m+'.spice')) for m in MODES}
            def evidence(run, outputs):
                for p in [run/n for n in ['tb.cir','execution.json','simulator.log',*outputs]]:report['evidence'][str(p.relative_to(ROOT))]=sha(p)
            evidence(cal,['calibration.raw'])
            label='physical'; text=physical_deck(camp,plan['identity']['overlay']['library'])
            path=camp/'prepared'/(label+'.cir')
            if path.exists() and path.read_text()!=text:raise ValueError('prepared deck changed')
            if not path.exists():path.write_text(text)
            outputs=output_names();run=run_case(camp,label,text,outputs);evidence(run,outputs)
            for mode in MODES:
                for trim in TRIMS:
                    for temp in TEMPS:
                        rawname=f'{case_name(mode, trim)}_t{temp}.raw'
                        data=scalar_raw.read(run/rawname);keys=[*NODES,*[f'iout{k}' for k in range(4)],'icopy']
                        row={k:data['obs_'+k] for k in keys}
                        report['rows'].append(dict(mode=mode,trim=trim,temp_c=temp,raw=str((run/rawname).relative_to(ROOT)),observables=row))
            if len(report['rows'])!=45:raise ValueError('missing operating point')
            report['status']='selected_DC_operating_points_complete_not_startup_or_adoption'
        except Exception as exc:
            report['error']=f'{type(exc).__name__}: {exc}';raise
        finally:dump(out/'summary.json',report)
    return out/'summary.json'


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--check',type=Path);g.add_argument('--resume',type=Path);a=p.parse_args()
    print(prepare() if a.prepare else (check(a.check.resolve()) if a.check else resume(a.resume.resolve())))


if __name__=='__main__':main()
