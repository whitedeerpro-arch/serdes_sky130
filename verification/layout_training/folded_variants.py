"""Compare folded inverter geometry, central G access, wider M1 and an outer tap ring.

All changes stay in new teaching copies. The captured folded seed deliberately
remains visible as an unaccepted port-connectivity example; it is never repaired
in the other agent's working directory.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from serdes_flow.project import ROOT
from inverter_audit import audit
from run import LAYOUT, SEED, sha, verify

BUILDER = LAYOUT / 'build_inv_std2.py'
REF = LAYOUT / 'inv_std2_ref.spice'
STRAIGHT_BUILDER = LAYOUT / 'build_inv_std.py'
STRAIGHT_REF = LAYOUT / 'inv_std_ref.spice'


def between(text, start, end, replacement):
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError('folded source shape changed')
    i, j = text.index(start), text.index(end)
    return text[:i] + replacement + text[j:]


def variant(source, ring):
    text = between(source, '    # gate bus on the left and the gate contact',
                   '    # source/drain contact rows', '''    # Common gate bus in the P/N gap, with its contact to the left.
    mid = (NY2 + PY1) / 2
    R("poly", 0.30, mid - .15, G2 + GL, mid + .15)
    R("polycont", .45, mid - .085, .62, mid + .085)
    R("locali", .36, mid - .17, .71, mid + .17)
    R("viali", .45, mid - .085, .62, mid + .085)
    R("m1", -.20, mid - .20, .75, mid + .20)

''')
    extras = '''    # Wider continuous current-carrying trunks; dimensions are a
    # teaching candidate, not an EM/current-capacity signoff.
    for low, high in ((NY1 - .525, NY2), (PY1, PY2 + .525)):
        for x in (1.6, 4.2):
            R("m1", x - .30, low, x + .30, high)
    for y in (NY1 - .525, PY2 + .525):
        R("m1", .9, y - .40, 4.9, y + .40)
    outx = (G1 + GL + G2) / 2
    R("m1", outx - .30, NY1 + .2, outx + .30, PY2 - .9)
    outy = mid - .7
'''
    if ring:
        extras += '''    # P+ substrate-tap ring outside the whole inverter, tied to VSS.
    # Existing N+ N-well tap remains tied to VDD. No deep-N-well is added.
    xl, xr, yb, yt, half = -1.2, 6.8, -.8, 12.7, .4
    frame = [(xl-half, yb-half, xl+half, yt+half),
             (xr-half, yb-half, xr+half, yt+half),
             (xl-half, yb-half, xr+half, yb+half),
             (xl-half, yt-half, xr+half, yt+half)]
    for layer in ("psubdiff", "locali", "m1"):
        for bounds in frame:
            R(layer, *bounds)
    centers = [(xl,yb),(xr,yb),(xl,yt),(xr,yt)]
    for k in range(1, int((xr-xl)/.5)):
        centers.extend([(xl+k*.5,yb), (xl+k*.5,yt)])
    for k in range(1, int((yt-yb)/.5)):
        centers.extend([(xl,yb+k*.5), (xr,yb+k*.5)])
    for x,y in centers:
        R("psubdiffcont", x-.085, y-.085, x+.085, y+.085)
        R("viali", x-.085, y-.085, x+.085, y+.085)
    R("m1", 1.3, yb, 1.9, NY1-.525)
    # Cross the closed M1 ring in M2, without a via at the crossing.
    R("via1", -.13, mid-.13, .13, mid+.13)
    R("m2", -2.6, mid-.2, .2, mid+.2)
    R("via1", outx-.13, outy-.13, outx+.13, outy+.13)
    R("m2", outx-.30, outy-.30, 8.3, outy+.30)
    pin_d, pin_g = (8.0, outy), (-2.3, mid)
'''
    else:
        extras += '    pin_d, pin_g = (outx, outy), (.4, mid)\n'
    extras += '''    # Pins label actual routed nets; no isolated output pad.
    for name, (x,y) in (("d",pin_d),("g",pin_g),
                        ("vdd",(2.9,PY2+.525)),("vss",(2.9,NY1-.525))):
        t.append(f"L {name} {x} {y}")
'''
    return between(text, '    # ports\n', '    t += ["select top cell", "save"]', extras)


def compact_straight(source):
    """Keep W/L and set D diffusion depth to the folded cell's 0.85 µm.

    Compare junction geometry with the same drain-depth constraint; do not
    attribute all improvement over the much wider original D to folding.
    """
    replacements = {
        'XL, XR = 1.20, 4.60': 'XL, XR = 1.20, 3.60',
        '    t.append(f"R poly {XG - 0.20} 0.95 {XG + GL + 0.20} 1.45")':
            '    t.append("R poly 2.05 6.15 2.875 6.65")',
        'CF pc 2.675 1.20': 'CF pc 2.25 6.40',
        'VIA 2.675 1.20': 'VIA 2.25 6.40',
        'R m1 2.55 1.05 3.60 1.35': 'R m1 .20 6.20 2.425 6.60',
        'L g 3.40 1.20': 'L g .40 6.40',
        '(3.40, 1.20)': '(.40, 6.40)',
    }
    text = source
    for old, new in replacements.items():
        if old not in text:
            raise ValueError('straight contact example changed: ' + old)
        text = text.replace(old, new)
    for old, new in [('4.15', '3.175'), ('4.01', '3.035'), ('4.29', '3.315')]:
        text = text.replace(old, new)
    start = '    # ---- ports -------------------------------------------------------------'
    if text.count(start) != 1:
        raise ValueError('straight port section changed')
    extras = '''    # Match the folded comparison's 0.6 µm trunks / 0.8 µm rails.
    for low, high in ((.575, 5.425), (7.375, 16.225)):
        t.append(f"R m1 1.50 {low} 2.10 {high}")
    for y in (.575, 16.225):
        t.append(f"R m1 .9 {y-.4} 4.9 {y+.4}")
    t.append("R m1 2.875 1.775 3.475 14.925")
    # Merge well-tap metal into the wider source trunks without 0.1 µm notches.
    t.append("R m1 1.30 .90 1.80 1.30")
    t.append("R m1 1.30 15.50 1.80 16.30")
'''
    return text.replace(start, extras + '\n' + start)


def command(argv, cwd, log):
    proc = subprocess.run([str(s) for s in argv], cwd=cwd, capture_output=True, text=True, timeout=1800)
    log.write_text(proc.stdout + proc.stderr)
    return proc.returncode


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('workspace', type=Path)
    a = p.parse_args()
    parent = a.workspace.resolve()
    verify(parent)
    origin = json.loads((SEED / 'ORIGIN.json').read_text())
    frozen = {r['snapshot']: r['sha256'] for r in origin['files']}
    for rel in (BUILDER, REF):
        if sha(SEED / rel) != frozen[str(rel)]:
            raise ValueError('folded teaching seed changed')
    out = ROOT / 'results/layout_training/folded' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:8])
    out.mkdir(parents=True)
    for script in (Path(__file__), Path(__file__).parent / 'inverter_audit.py'):
        shutil.copyfile(script, out / script.name)
    rows = {}
    source = (SEED / BUILDER).read_text()
    straight_source = (parent / 'student' / STRAIGHT_BUILDER).read_text()
    checker = parent / 'baseline/verification/layout/check.py'
    for name, text, builder, reference, cell in [
            ('captured_seed', source, BUILDER, REF, 'inv_std2'),
            ('straight_compact_mid_wide', compact_straight(straight_source), STRAIGHT_BUILDER, STRAIGHT_REF, 'inv_std'),
            ('fold2_mid_wide', variant(source, False), BUILDER, REF, 'inv_std2'),
            ('fold2_mid_wide_ring', variant(source, True), BUILDER, REF, 'inv_std2')]:
        base = out / name
        target = base / LAYOUT
        target.mkdir(parents=True)
        shutil.copytree(parent / 'baseline/verification/layout', base / 'verification/layout')
        (base / builder).write_text(text)
        shutil.copyfile(SEED / reference, base / reference)
        build_code = command([sys.executable, base / builder], base, base / 'build.log')
        if build_code:
            raise RuntimeError('variant build failed: ' + str(base))
        check_code = command([sys.executable, checker, target, cell, '--ref', base / reference], base, base / 'check.log')
        facts = audit(target / (cell + '_lvs.spice'), cell)
        rows[name] = dict(build_exit=build_code, checker_exit=check_code, port_and_width_audit=facts,
            cell=cell, paths={k: str(p.relative_to(ROOT)) for k,p in dict(builder=base/builder, reference=base/reference,
                mag=target/(cell+'.mag'), lvs=target/(cell+'_lvs.spice'), pex=target/(cell+'_pex.spice'),
                log=base/'check.log').items()},
            files_sha256={str(p.relative_to(ROOT)): sha(p) for p in
                (base/builder,base/reference,target/(cell+'.mag'),target/(cell+'_lvs.spice'),target/(cell+'_pex.spice'),base/'check.log')})
        print(name, 'checker', check_code, 'audit', facts['status'], flush=True)
    result = dict(status='teaching_variants; inspect_each_verdict', parent_workspace=str(parent.relative_to(ROOT)),
                  parent_manifest_sha256=sha(parent/'manifest.json'), source_sha256={str(p):sha(SEED/p) for p in (BUILDER,REF)},
                  straight_contact_source_sha256=sha(parent / 'student' / STRAIGHT_BUILDER),
                  scripts_sha256={p.name:sha(p) for p in (Path(__file__),Path(__file__).parent/'inverter_audit.py')}, rows=rows,
                  scope='N4/P8 total width, two fingers, central G access, M1 source/drain 0.6µm and rails 0.8µm candidates; optional P+ VSS ring with signal M2 crossings. No EM, current, timing, noise, latch-up immunity or tapeout signoff.')
    (out/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print('RESULT',out.relative_to(ROOT),flush=True)
    if any(r['checker_exit'] or r['port_and_width_audit']['status']!='pass' for n,r in rows.items() if n!='captured_seed'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
