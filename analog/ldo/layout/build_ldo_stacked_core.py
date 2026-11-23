"""Independent70pF core with equal nominal32/16pF, using two-level MIM.

Reuse the compact active layout unchanged, move its rightmost cascode resistor
and attached horizontal routes into the narrower capacitor bay, then verify.
Installed first-layer layouts and their generator are never edited.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import build_ldo_smallcap as core
from geometry import Cell


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--cap32',type=Path,required=True);ap.add_argument('--cap16',type=Path,required=True)
    a=ap.parse_args();out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    source=out/'source';source.mkdir();identities={}
    for p in (Path(__file__),Path(core.__file__),Path(core.base.__file__)):
        shutil.copyfile(p,source/p.name);identities[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    paths={32:a.cap32.resolve(),16:a.cap16.resolve()}
    for n,p in paths.items():
        shutil.copyfile(p,source/p.name);shutil.copyfile(p.parent/'reference.spice',source/f'stack{n}_reference.spice')
        identities[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    mag,ref=core.build_core(out,32,16,2000,31250,paths)
    shutil.copyfile(mag,mag.with_suffix('.unrelocated.mag'))
    c=Cell.read(mag)
    # All capacitor geometry ends below x145um. Only the resistor centred at
    # x180 and routes to that resistor lie beyond x160 in this explicit input.
    # A monotonic coordinate contraction shortens those routes without folds.
    right=max(Cell.read(p).bbox()[2]-Cell.read(p).bbox()[0] for p in paths.values())
    if right>65:raise ValueError('Unexpected stacked-array width')
    def move(x):return x-50 if x>160 else x
    for layer,rects in c.rects.items():
        c.rects[layer]=[(move(x1),y1,move(x2),y2) for x1,y1,x2,y2 in rects]
        if any(x1>=x2 for x1,y1,x2,y2 in c.rects[layer]):raise ValueError('Relocation folds geometry')
    c.labels=[(layer,move(x),y,name) for layer,x,y,name in c.labels];c.write(mag)
    text=ref.read_text()
    for n,p in paths.items():
        old=f'X{"chv" if n==32 else "ccas"} {"va" if n==32 else "casg"} vss serdes_ldo_mim{n}'
        if text.count(old)!=1:raise ValueError('Core capacitor anchor changed')
        text=text.replace(old,old.replace(f'serdes_ldo_mim{n}',f'serdes_ldo_stack{n}_pdk'))
        text+='\n'+(p.parent/'reference.spice').read_text()
    ref.write_text(text)
    rec=core.verify_smallcap_cell(mag,ref,'Equal nominal70pF LDO | two-level MIM | independent core trial')
    rec.update(total_pf=70,chv_pf=32,ccas_pf=16,rhv_ohm=2000,rcas_ohm=31250,
               source_sha256=identities,capacitor_layers=['M3-M4','M4-M5'],
               scope='Core physical trial only; unchanged nominal capacitance/MOS; full-rule DRC/LVS before electrical PEX screening')
    (out/'summary.json').write_text(json.dumps(rec,indent=2)+'\n')
    print(json.dumps({k:rec[k] for k in ('area_um2','width_um','height_um','drc_total','lvs_match')},indent=2))


if __name__=='__main__':main()
