"""Independent 12pF cascode-filter layout trial, using a2x6 MIM array.

Freeze the current compact core builder and private references. Do not modify
the installed70pF layout, its generator, or the selected schematic parameters.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import build_ldo_smallcap as core
import build_mim_pdk as mim


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output-dir',type=Path,required=True)
    a=ap.parse_args();out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    source=out/'source';source.mkdir()
    identities={}
    for p in (Path(__file__),Path(core.__file__),Path(mim.__file__),Path(core.base.__file__)):
        shutil.copyfile(p,source/p.name);identities[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    original=core.SPICE_DIR
    for name in ('ldo_hv18_core_r4.spice','ldo_passives.spice'):
        shutil.copyfile(original/name,source/name)
        identities[str(original/name)]=hashlib.sha256((original/name).read_bytes()).hexdigest()
    passive=source/'ldo_passives.spice'
    passive.write_text(passive.read_text()+'\n.subckt serdes_ldo_mim12 a b\nX0 a b serdes_ldo_mim8\nX1 a b serdes_ldo_mim4\n.ends serdes_ldo_mim12\n')
    mim.REFERENCE=passive;mim.GRID[12]=(2,6);mim.GRID[32]=(4,8)
    core.SPICE_DIR=source
    records=[];paths={}
    for n in (12,32):
        records.append(mim.build(out,n));paths[n]=out/f'serdes_ldo_mim{n}_pdk'/f'serdes_ldo_mim{n}_pdk.mag'
    mag,ref=core.build_core(out,32,12,2000,500000/12,paths)
    rec=core.verify_smallcap_cell(mag,ref,'12pF cascode-filter trial | 2x6 MIM | local experiment')
    rec.update(total_pf=66,ccas_pf=12,rcas_ohm=500000/12,chv_pf=32,rhv_ohm=2000,
               cap_arrays=records,source_sha256=identities,
               scope='66pF schematic candidate core only; no whole-macro qualification or adoption')
    (out/'summary.json').write_text(json.dumps(rec,indent=2)+'\n')
    print(json.dumps({k:rec[k] for k in ('area_um2','width_um','height_um','drc_total','lvs_match')},indent=2))


if __name__=='__main__':main()
