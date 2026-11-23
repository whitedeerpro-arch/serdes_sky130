"""Independent1Mohm/16pF peripheral filter with a compact2x4 stacked MIM.

Retains the physical32-resistor snake and connects the new capacitor's actual
ports explicitly. Does not install or replace the PLL tail/reference filter.
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
    ap.add_argument('--cap16',type=Path,required=True);a=ap.parse_args()
    out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    source=out/'source';source.mkdir();cap=a.cap16.resolve()
    for p in (Path(__file__),Path(core.__file__),Path(core.base.__file__),cap):shutil.copyfile(p,source/p.name)
    shutil.copyfile(cap,source/'serdes_ldo_mim16_pdk.mag');core.base.MIM_DIR=source
    mag,ref=core.base.build_slow_filter(out)
    c=Cell.read(mag);mim=Cell.read(cap);ax,ay=mim.pins('a')[0];bx,by=mim.pins('b')[0]
    fx,fy=c.pins('filtered')[0];gx,gy=c.pins('vss')[0]
    c.wire('metal4',[(fx,fy),(fx,ay),(ax,ay)],.5)
    c.wire('metal3',[(gx,gy),(gx,by),(bx,by)],.5)
    cell='serdes_pll_bias_lowpass_stacked_pdk';newmag=mag.parent/(cell+'.mag');c.write(newmag)
    text=ref.read_text().replace('serdes_pll_bias_lowpass_slow_r4_pdk',cell)
    old='Xc filtered vss serdes_ldo_mim16'
    if text.count(old)!=1:raise ValueError('Peripheral capacitor anchor changed')
    text=text.replace(old,'Xc filtered vss serdes_ldo_stack16_pdk')+'\n'+(cap.parent/'reference.spice').read_text()
    newref=mag.parent/(cell+'_ref.spice');newref.write_text(text)
    rec=core.verify_smallcap_cell(newmag,newref,'1Mohm/16pF stacked peripheral filter | no value reduction')
    rec.update(r_ohm=1e6,c_pf=16,source_cap=str(cap),source_cap_sha256=hashlib.sha256(cap.read_bytes()).hexdigest(),
               scope='Peripheral filter physical candidate; source loading/noise/actual PLL integration separate')
    (out/'summary.json').write_text(json.dumps(rec,indent=2)+'\n')
    print(json.dumps({k:rec[k] for k in ('area_um2','width_um','height_um','drc_total','lvs_match')},indent=2))


if __name__=='__main__':main()
