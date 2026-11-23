"""Render the actual current r6 CML leaf candidates."""
import argparse
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from serdes_flow.project import ROOT
sys.path.insert(0,str(ROOT/"analog/layout/scripts"))
from layout_core import load_mag_as_canvas,plot_canvas  # noqa: E402


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--delay-run",type=Path,required=True)
    ap.add_argument("--buffer-run",type=Path,required=True)
    args=ap.parse_args()
    fig,axes=plt.subplots(1,2,figsize=(13,10),dpi=150)
    for ax,run,cell,title in [
        (axes[0],args.delay_run,"pll_vco_delay_r6_pdk","r6 delay: W40+40 / tail W25.2 / 4 x 2p85 L4.77"),
        (axes[1],args.buffer_run,"pll_buffer_r6_pdk","r6 buffer: W12+12 / tail W12 / 2 x 2p85 L4.14")]:
        canvas=load_mag_as_canvas(run/f"{cell}.mag",cell)
        plot_canvas(ax,canvas,title,"Actual PDK devices / full DRC 0 / LVS / 7 ports",show_cuts=True)
    handles,labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc="lower center",ncol=5,fontsize=8,frameon=False)
    fig.text(.08,.11,"A B B A input groups and symmetric guards; same total width and finger count as current circuits.\n"
             "First routing candidate: electrical/mismatch adoption pending. Source-end diffusion and extracted coupling included in local backannotation.",fontsize=9)
    fig.subplots_adjust(bottom=.22,top=.91,wspace=.25)
    out=ROOT/"docs/figures/layout/pll/pll_r6_cml_leaves.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out,bbox_inches="tight");plt.close(fig)
    print(out)


if __name__=="__main__":
    main()
