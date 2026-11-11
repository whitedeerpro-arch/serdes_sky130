"""Independently verify and publish the inverter folding / guard-ring examples."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from serdes_flow.project import ROOT


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


audit_module = load('folded_pin_audit', ROOT / 'verification/layout_training/inverter_audit.py')
sha = load('folded_training_runner', ROOT / 'verification/layout_training/run.py').sha


def geometry(path):
    layer, rects, labels = None, [], []
    text = path.read_text()
    if 'magscale 1 2' not in text or re.search(r'^use ', text, re.M):
        raise ValueError('expected the calibrated flat teaching geometry')
    for line in text.splitlines():
        if m := re.fullmatch(r'<< (\S+) >>', line):
            layer = m[1]
        elif m := re.fullmatch(r'rect (-?\d+) (-?\d+) (-?\d+) (-?\d+)', line):
            rects.append((layer, *[int(v) / 200 for v in m.groups()]))
        elif line.startswith('rlabel '):
            f = line.split()
            labels.append((f[-1], int(f[2]) / 200, int(f[3]) / 200))
    return rects, labels


def explicit_d_cap(path):
    caps = []
    for line in path.read_text().splitlines():
        f = line.split()
        if len(f) != 4 or not f[0].lower().startswith('c') or 'd' not in f[1:3]:
            continue
        m = re.fullmatch(r'([0-9.eE+-]+)([fpnu]?)', f[3])
        if m is None:
            raise ValueError('unknown explicit capacitance unit')
        farads = float(m[1]) * {'': 1., 'f': 1e-15, 'p': 1e-12, 'n': 1e-9, 'u': 1e-6}[m[2]]
        caps.append(dict(instance=f[0], nodes=f[1:3], fF=farads * 1e15))
    return dict(explicit_output_cap_sum_fF=sum(c['fF'] for c in caps), elements=caps,
                scope='Explicit Magic capacitors incident on D only; not total or bias-dependent Cout; MOS junction/overlap models remain separate.')


def draw(ax, path, title, *, ring=False):
    rects, labels = geometry(path)
    colors = dict(nwell='#f2e3ac', pwell='#dce6f2', ndiff='#65a5d4', pdiff='#db9292', poly='#d77b28',
                  psubdiff='#57945e', nsubdiff='#57945e', locali='#baa9d1', metal1='#536db4', metal2='#21988e',
                  ndiffc='#222222', pdiffc='#222222', psubdiffcont='#222222', nsubdiffcont='#222222',
                  polycont='#222222', viali='#222222', via1='#d33142')
    priority = {k: i for i,k in enumerate(colors)}
    for layer,x1,y1,x2,y2 in sorted(rects,key=lambda r:priority.get(r[0],-1)):
        if layer in colors:
            ax.add_patch(Rectangle((x1,y1),x2-x1,y2-y1,facecolor=colors[layer],edgecolor='none',alpha=.82))
    for layer, name in [('nmos','N'),('pmos','P')]:
        rs=[r for r in rects if r[0]==layer]
        if rs:
            ax.text(min(r[1] for r in rs)-.7,(min(r[2] for r in rs)+max(r[4] for r in rs))/2,name,weight='bold',fontsize=11)
    for name,x,y in labels:
        if name not in ('g','d','vdd','vss'):
            continue
        if ring:
            tx,ty={'g':(-3.4,y+.5),'d':(9.5,y-.5),'vdd':(8.8,10.4),'vss':(8.8,-.7)}[name]
        else:
            tx,ty={'g':(-1.2,y),'d':(7.8,y+.3),'vdd':(7.8,y),'vss':(7.8,y)}[name]
        ax.annotate(name.upper(),xy=(x,y),xytext=(tx,ty),fontsize=9,ha='center',va='center',
                    arrowprops=dict(arrowstyle='-',lw=.8,color='#333333'))
    ax.set(title=title,xlabel='µm',ylabel='µm',aspect='equal')
    ax.set_xlim((-4,11) if ring else (-2,9))
    ax.set_ylim((-2.8,17.5) if ring else (-.2,17.3))
    ax.grid(alpha=.15)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('summary',type=Path)
    a=p.parse_args()
    summary=a.summary.resolve()
    result=json.loads(summary.read_text())
    rows={}
    for name,r in result['rows'].items():
        for rel,expected in r['files_sha256'].items():
            if sha(ROOT/rel)!=expected:
                raise ValueError('variant identity changed: '+rel)
        facts=audit_module.audit(ROOT/r['paths']['lvs'],r['cell'])
        if facts!=r['port_and_width_audit']:
            raise ValueError('port/width geometry audit does not reproduce')
        text=(ROOT/r['paths']['log']).read_text()
        if r['checker_exit'] or not all(s in text for s in ('DRC_TOTAL 0','LVS_MATCH True','LVS_PROPERTY_ERRORS False')):
            raise ValueError('variant failed its layout checks')
        if facts['status'] != ('fail' if name=='captured_seed' else 'pass'):
            raise ValueError('unexpected exported-pin verdict')
        rects,_=geometry(ROOT/r['paths']['mag'])
        bounds=[min(t[1] for t in rects),min(t[2] for t in rects),max(t[3] for t in rects),max(t[4] for t in rects)]
        rows[name]=dict(r,audit_reproduced=True,drawn_bounds_um=bounds,
                       drawn_bbox_area_um2=(bounds[2]-bounds[0])*(bounds[3]-bounds[1]),
                       explicit_cap=explicit_d_cap(ROOT/r['paths']['pex']) if facts['status']=='pass' else None)
    parent=ROOT/result['parent_workspace']
    baseline_mag=parent/'student/analog/common/layout_practice/inv_std.mag'
    baseline_lvs=baseline_mag.with_name('inv_std_lvs.spice')
    baseline_audit=audit_module.audit(baseline_lvs,'inv_std')
    if baseline_audit['status']!='pass':
        raise ValueError('straight source pins invalid')
    fig,axes=plt.subplots(1,3,figsize=(11.5,7),layout='constrained')
    draw(axes[0],baseline_mag,'Original straight\nN W4 / P W8')
    draw(axes[1],ROOT/rows['straight_compact_mid_wide']['paths']['mag'],'Straight, trimmed D region\nCentral G; D depth 0.85 µm')
    draw(axes[2],ROOT/rows['fold2_mid_wide']['paths']['mag'],'Two fingers, shared D\nN 2×W2 / P 2×W4')
    fig.suptitle('Folding preserves total W/L while reducing shared-drain diffusion',fontsize=13)
    fig.supxlabel('Middle/right: S/D M1 trunks 0.6 µm, rails 0.8 µm; central gate access. Dimensions are layout candidates, not EM signoff.\nEqual D-depth comparison: PMOS D area 6.8 → 3.4 µm²; junction perimeter 17.7 → 9.7 µm. Total Cout is not halved automatically.',fontsize=8)
    figure=ROOT/'docs/figures/layout/inverter_folding_comparison.png'
    fig.savefig(figure,dpi=170)
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(8.5,8),layout='constrained')
    draw(ax,ROOT/rows['fold2_mid_wide_ring']['paths']['mag'],'Outer P+ substrate tap ring + existing N-well tap',ring=True)
    ax.annotate('P+ tap + LI/M1 closed ring → VSS',xy=(2.5,12.7),xytext=(2.5,16),ha='center',fontsize=10,
                arrowprops=dict(arrowstyle='->',color='#416c45'))
    ax.annotate('N+ well tap → VDD',xy=(4.25,10.8),xytext=(7.4,14.5),ha='center',fontsize=9,
                arrowprops=dict(arrowstyle='->',color='#416c45'))
    ax.annotate('G / D cross the M1 ring in M2\nNo M1-M2 via at the crossing',xy=(-1.2,4.8),xytext=(.2,-1.7),ha='center',va='top',fontsize=9,
                arrowprops=dict(arrowstyle='->',color='#16877d'))
    fig.supxlabel('Blue: M1. Teal: M2. Red: M1-M2 vias. Black: lower-level contacts. P-substrate ring, not deep-N-well isolation.\nLocal DRC/LVS and exported-pin audit pass; substrate-noise, current-capacity and latch-up immunity remain unqualified.',fontsize=8)
    guard_figure=ROOT/'docs/figures/layout/inverter_guard_ring.png'
    fig.savefig(guard_figure,dpi=170)
    plt.close(fig)
    archive=ROOT/'results/layout_training/folded_publication'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    archive.mkdir(parents=True)
    shutil.copyfile(__file__,archive/'publisher.py')
    data=ROOT/'docs/data/inverter_folding_variants.json'
    publication=dict(status='local_layout_VARs_verified; no_production_adoption',summary=str(summary.relative_to(ROOT)),
        summary_sha256=sha(summary),rows=rows,original_straight=dict(mag=str(baseline_mag.relative_to(ROOT)),mag_sha256=sha(baseline_mag),
            lvs=str(baseline_lvs.relative_to(ROOT)),lvs_sha256=sha(baseline_lvs),audit=baseline_audit),
        publisher_snapshot=str((archive/'publisher.py').relative_to(ROOT)),publisher_sha256=sha(Path(__file__)),
        audit_source_sha256=sha(ROOT/'verification/layout_training/inverter_audit.py'),
        scope='Compared extracted AD/AS and PD/PS of actual output terminals, including reversed D/S fingers. Explicit PEX capacitors are separate from MOS intrinsic junction/overlap capacitance. Wider metal, central G and ring routing are candidates, not timing/noise/current/latch-up qualification.')
    data.write_text(json.dumps(publication,indent=2,allow_nan=False)+'\n')
    index=dict(data=str(data.relative_to(ROOT)),data_sha256=sha(data),figure=str(figure.relative_to(ROOT)),figure_sha256=sha(figure),
               guard_figure=str(guard_figure.relative_to(ROOT)),guard_figure_sha256=sha(guard_figure),status=publication['status'])
    (ROOT/'results/catalog/inverter_folding_variants.json').write_text(json.dumps(index,indent=2)+'\n')
    for name,r in rows.items():
        print(name,r['port_and_width_audit']['status'],r['port_and_width_audit']['output_junction'],r['explicit_cap'],flush=True)


if __name__=='__main__':
    main()
