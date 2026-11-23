"""Small-signal capacitance the steering CP and the LF precharge gate put on the VCO control node (PLL closure step 7).

    uv run python analog/pll/cp/tb/out_cap/run.py [--variants cp4,cp8,tgate] [--freq 20e6] [--workers 4] [--analyse C]

The loop and supply models carry the control node's own C as VCO input (analog/pll/vco/tb/ctrl_load) + an extra
term; the supply fit (analog/pll/top/theory/supply_split.py) puts that extra at 140-165 fF, the loop model had 40 fF.
This bench measures it: the k = 4 steering CP of psrr_lf (real bias, both switches off, follower on) and the LF's
fast precharge gate (pll_lf_tgate_lvt 4 / 8, enable low) on node ctrl, driven by a DC + AC source at the code-table
Vctrl of every condition x RC section; C = -Im(I) / (2 pi f) at --freq.  Variants:
  cp4    CP at the k = 4 sizes of pll_core_r5k4 + the precharge gate
  cp8    CP with the output mirrors, switches and drivers doubled (k = 8 candidate, follower unchanged) + the gate
  tgate  the precharge gate alone
One deck per variant x MOS corner x RC section; its nine supply / temperature conditions in the control block.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import PROCESS, SUPPLY_V, TEMP_C
from serdes_flow.project import ROOT, model_library

RESULTS = ROOT / "results/analog/pll/cp/out_cap"
TABLE = json.loads((ROOT / "config/pll_code_table.json").read_text())["table"]
CP = {"cp4": "wn=20 wp=80 wsn=8 wsp=16 up_wn=2 up_wp=8 dn_wn=4 dn_wp=8 pnf=16 nnf=4 ntail=2 cdum=0.3p",
      "cp8": "wn=40 wp=160 wsn=16 wsp=32 up_wn=4 up_wp=16 dn_wn=8 dn_wp=16 pnf=32 nnf=8 ntail=2 cdum=0.3p"}
INCLUDES = ["analog/common/devices/spice/sky130_primitives.spice", "analog/common/devices/spice/sky130_pfet_lvt.spice",
            "analog/common/devices/spice/cmos_logic.spice", "analog/pll/cp/spice/charge_pump.spice",
            "analog/pll/cp/spice/charge_pump_steer.spice", "analog/pll/loop_filter/spice/passive_rc_precharge.spice"]


def deck(variant, proc, rc, conds, freq, snap):
    lines = ["* steering CP + precharge gate on the control node: small-signal C", f'.lib "{model_library()}" {proc}']
    lines += [f'.include "{ROOT / p}"' for p in INCLUDES]
    lines += [".param supply=1.8", "Vdd vdd 0 {supply}", "Vc ctrl 0 DC 1.1 AC 1", "Vpre pre_ref 0 1.1",
              "Xtg pre_ref ctrl 0 vdd vdd 0 pll_lf_tgate_lvt wn=4 wp=8"]
    if variant != "tgate":
        lines += ["Vup up 0 0", "Vdn dn 0 0", "Vbcp vbcp 0 {supply}", "Incp vbcp vbn 50u", "Ipcp vbp 0 50u",
                  "Xbncp vbn vbn 0 0 serdes_nfet w=5 l=1", "Xbpcp vbp vbp vdd vdd serdes_pfet w=20 l=1 nf=4",
                  f"Xcp up dn ctrl vbn vbp ibcp vdd 0 pll_cp_steer {CP[variant]}"]
    lines += [".end"]
    text = "\n".join(lines) + "\n"
    if variant != "tgate":
        text = rcorner.to_pdk(bias.real(text), snap)
        text = text.replace(".end\n", "XIbcp ibcp vgi_bias vdd serdes_bias_pcopy n=4\n.end\n", 1)
    text = bias.section(text, proc, rc)
    ctl = [".control", "set num_threads=1"]
    for v, t, vc in conds:
        ctl += [f"option temp={t}", f"alter Vdd dc={v}", f"alter Vpre dc={vc}", f"alter Vc dc={vc}"]
        if variant != "tgate":
            ctl += [f"alter Vbcp dc={v}"]
        ctl += [f"ac lin 1 {freq:.6e} {freq:.6e}", f"let cval = -imag(i(vc)) / (2 * pi * {freq:.6e})",
                f"let gval = -real(i(vc))", f'echo "RESULT v{round(v * 1000)}_t{t} $&cval $&gval"', "destroy all"]
    return text[:text.rindex(".end")] + "\n".join(ctl + ["quit", ".endc", ".end", ""])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="cp4,cp8,tgate")
    ap.add_argument("--freq", type=float, default=20e6)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--analyse")
    a = ap.parse_args()
    camp = ROOT / a.analyse if a.analyse else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    variants = a.variants.split(",")
    groups = {}
    for p in PROCESS:
        for rc in ("tt", "hh", "ll"):
            groups[(p, rc)] = [(v, t, TABLE[f"{p}_v{round(v * 1000)}_t{t}:{rc}"]["vctrl"]) for v in SUPPLY_V for t in TEMP_C]
    if not a.analyse:
        jobs = [(deck(var, p, rc, conds, a.freq, camp / "snap" / f"{var}_{p}_{rc}"), camp / f"{var}_{p}_{rc}",
                 dict(timeout_s=1800, meta=dict(variant=var, process=p, rc=rc, freq=a.freq)))
                for var in variants for (p, rc), conds in groups.items()]
        for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
            if not ex.ok:
                print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}", flush=True)
    rows = {}
    for var in variants:
        for (p, rc), conds in groups.items():
            d = camp / f"{var}_{p}_{rc}"
            logs = sorted(d.glob("*.log"))
            if not logs:
                continue
            for line in logs[0].read_text().splitlines():
                if line.startswith("RESULT "):
                    _, tag, c, g = line.split()
                    v, t = tag[1:].split("_t")
                    vc = TABLE[f"{p}_v{v}_t{t}:{rc}"]["vctrl"]
                    rows[f"{var}:{p}_v{v}_t{t}:{rc}"] = dict(c_f=float(c), g_s=float(g), vctrl=vc)
    (camp / "summary.json").write_text(json.dumps(dict(freq=a.freq, cp=CP, rows=rows), indent=1))
    for var in variants:
        cs = [r["c_f"] for k, r in rows.items() if k.startswith(var + ":")]
        if cs:
            print(f"{var:6s} {len(cs):3d} points: C {min(cs) * 1e15:6.1f} .. {max(cs) * 1e15:6.1f} fF (median {np.median(cs) * 1e15:6.1f})")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
