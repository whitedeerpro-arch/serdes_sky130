"""Complete sym9 ring+four buffers, frozen physical reference/CPEX/RC endpoints.

Schematic real bias, ideal quiet rail/ctrl/config; 30 fF per buffer output.
No residual 12 fF phase budget is added to a complete physical core.
The schematic comparison is this sym9 candidate's own LVS reference.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
from pathlib import Path
import re
import sys

import numpy as np
from serdes_flow import bias, boundary, clock, netlist, project, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.phase_grid import spacing

ROOT = project.ROOT
sys.path.insert(0, str(ROOT / "verification/layout"))
from review_sim import execute, save_analysis

TOP = "pll_vco_core_sym9_s32p5"
STOP, START = 24e-9, 14e-9
POINTS = ["tt_v1800_t27:tt:9:1.166", "fs_v1650_t85:hh:0:1.21", "sf_v1650_t-40:ll:31:0.90",
          "ss_v1650_t85:hh:16:1.055", "sf_v1650_t85:hh:16:1.055"]


def bias_load_signature(path,top):
    """DC-only bias gate signature, folding equivalent parallel fingers.

    This intentionally excludes dynamic Miller/metal loading; it is only valid
    for the calibrated DC voltage clamp, never a bias transient/noise replay.
    """
    devices,unknown=netlist.flatten(netlist.parse([path]),top)
    if unknown:raise ValueError(f"Unknown load definitions: {unknown}")
    groups=defaultdict(float)
    for device in devices:
        if "nfet" in device.model and len(device.nodes)==4 and device.nodes[1]=="vbias_q":
            if "vss" not in (device.nodes[0],device.nodes[2]) or device.nodes[3]!="vss":
                raise ValueError("Bias tail source/body changed")
            groups[(device.model,device.l)]+=device.w*device.nf
    if not groups:raise ValueError("No bias gate load")
    lines=[".subckt dc_bias_load vbias vss"]
    for i,((model,length),width) in enumerate(sorted(groups.items())):
        lines.append(f"Xg{i} _ vbias vss vss {model} w={width:.9g} l={length:.9g}")
    lines.append(".ends")
    return boundary.input_stage_signature("\n".join(lines),"dc_bias_load",["vbias"])


def deck(point, variant, physical, out, method="gear", bias_voltage=None, ramp=False):
    tag, rc, code, ctrl = point.split(":")
    c, code = Condition.parse(tag), int(code)
    source = physical / {"schematic":"reference.spice", "devices":TOP+"_lvs.spice", "cpex":TOP+"_pex.spice", "rcx":TOP+"_rcx.spice"}[variant]
    cpex_text=(physical/(TOP+"_pex.spice")).read_text()
    phase_nets=set()
    for line in cpex_text.splitlines():
        t=line.split()
        if line.startswith("X") and "sky130_fd_pr__nfet_01v8_lvt" in t:
            phase_nets.add(t[2])
    anchors=[]
    if variant=="schematic":
        for stage in range(4):
            for sign in "pn":
                for block,bit in [("b4_l",4),("b3_l",3),("b2_l",2),("b1_l",1),("b0_c",0),
                                  ("b1_r",1),("b2_r",2),("b3_r",3),("b4_r",4)]:
                    u=2**bit/(1 if bit==0 else 2)
                    anchors.append(f"Rdc{len(anchors)} xcore.xtank{stage}{sign}.x{block}.plate 0 {1e12/u:.12g}")
    else:
        for line in cpex_text.splitlines():
            t=line.split()
            if line.startswith("X") and "sky130_fd_pr__cap_mim_m3_1" in t:
                plate=next(n for n in t[1:3] if n not in phase_nets)
                switches=[l.split() for l in cpex_text.splitlines() if l.startswith("X") and
                          "sky130_fd_pr__nfet_01v8 " in l and plate in l.split()[1:5]]
                gates={s[2] for s in switches}
                if len(gates)!=1 or not next(iter(gates)).startswith("cfg"):
                    raise ValueError("Ambiguous plate control")
                bit=int(next(iter(gates))[-1]);u=2**bit/(1 if bit==0 else 2)
                anchors.append(f"Rdc{len(anchors)} xcore.{plate} 0 {1e12/u:.12g}")
    # Identify the local phase driving buffer 0p from its actual extracted
    # w=3 LVT input gates. This avoids hard-coded extractor coordinates.
    if variant == "schematic":
        phase = "v0p"
    else:
        gates = []
        for line in cpex_text.splitlines():
            t = line.split()
            if (line.startswith("X") and "sky130_fd_pr__nfet_01v8_lvt" in t and
                "b0n" in (t[1],t[3]) and "w=3" in t):
                gates.append(t[2])
        if len(set(gates)) != 1:
            raise ValueError("Ambiguous buffer-0 input phase")
        phase = gates[0]
        if variant == "rcx":
            # Kicks must hit a real terminal in the R-split graph.
            target = re.escape(phase.removesuffix("#")) + r"\.[nt]\d+"
            match = re.search(target, source.read_text())
            if match:
                phase = match[0]
    lines = ["PLL complete physical VCO local review", f'.lib "{project.model_library()}" {c.process}',
             f'.include "{ROOT / "analog/common/devices/spice/sky130_primitives.spice"}"',
             f'.include "{source}"', f"Vdd vdd 0 {c.supply}", f"Vref vref 0 {c.supply}",
             "Iref vref vbias .85m", "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
             f"Vctrl ctrl 0 {ctrl}"]
    lines += [f"Vb{i} cfg{i} 0 {c.supply if code>>i&1 else 0}" for i in range(5)]
    outputs = [f"b{i}{s}" for i in range(4) for s in "pn"]
    lines += [f"Xcore ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vbias {' '.join(outputs)} vdd 0 {TOP}"]
    lines += [f"Cload{i} {n} 0 30f" for i,n in enumerate(outputs)]
    lines += anchors
    # Finite DC reference on each MIM floating plate, as in the adopted r6
    # schematic. These are numerical anchors, not layout resistors.
    if variant=="schematic":
        lines += [f".nodeset v(xcore.v{k}{s})={c.supply-.12}" for k in range(4) for s in "pn"]
    else:
        # R-split nodes get their own terminal voltages from the solver.
        if variant=="cpex":lines += [f".nodeset v(xcore.{n})={c.supply-.12}" for n in sorted(phase_nets)]
    lines += [f"Ikick xcore.{phase} 0 PWL(0 0 100p 0 101p 1u 121p 1u 122p 0)",
              f".temp {c.temp}", f".options reltol=1e-4 abstol=1p vntol=1u klu method={method}"]
    probes = " ".join(f"v({n})" for n in outputs) + " i(Vdd) v(vbias)"
    lines += [f".save {probes}", ".control", "set num_threads=1", f"tran 4p {STOP:.12g} 0 4p",
              f"wrdata waveforms.tsv {probes}", "quit", ".endc", ".end", ""]
    text=bias.real(spice.binary_output("\n".join(lines)))
    if bias_voltage is not None:
        # Isolate the physical VCO from the excluded BG transient solver. The
        # voltage comes from a complete, explicit real-bias schematic run at
        # this very PVT/code/ctrl point, and is common to all compared models.
        text=re.sub(r"^Xbias_ref .*\n|^\.nodeset v\(bias_vbg\).*\n", "", text, flags=re.M)
        text=re.sub(r"^XIref .*\n",f"Vbias vbias 0 {bias_voltage:.12g}\n",text,flags=re.M)
    if ramp:
        if bias_voltage is None:raise ValueError("A local ramp requires a calibrated clamped bias")
        text=re.sub(r"^(Vdd|Vctrl|Vbias|Vb[0-4]) (\S+) 0 ([-+0-9.eE]+)$",
                    lambda m:f"{m[1]} {m[2]} 0 PWL(0 0 5n {m[3]})",text,flags=re.M)
        text=re.sub(r"^\.nodeset v\(xcore\..*\n", "",text,flags=re.M)
        text=re.sub(r"^Ikick (\S+) 0 .*",r"Ikick \1 0 PWL(0 0 6n 0 6.001n 1u 6.021n 1u 6.022n 0)",text,flags=re.M)
    return bias.section(rcorner.to_pdk_fixed(text, out / "resistors"), c.process, rc)


def measure(path):
    w = spice.Waves(path)
    outputs, rising = [], []
    for i in range(4):
        y = w[f"b{i}p"]-w[f"b{i}n"]
        stat = clock.period_stats(w.t, y, start=START, stop=STOP)
        amp = clock.cycle_amplitudes(w.t,y,START,STOP)
        e = clock.edges(w.t,y,start=START,stop=STOP)
        drift = None
        if len(e) >= 8:
            h = len(e)//2
            f1, f2 = h/(e[h]-e[0]), (len(e)-h-1)/(e[-1]-e[h])
            drift = float(f2/f1-1)
        outputs.append(dict(period=stat, amplitude=amp, drift=drift,
                            settled=drift is not None and abs(drift)<=5e-4))
        rising.append(e)
    f = outputs[0]["period"]["frequency_hz"] if outputs[0]["period"] else None
    signals=[w[f"b{i}p"]-w[f"b{i}n"] for i in range(4)]
    grid=spacing(w.t,signals,[(0,1),(1,-1),(2,1),(3,-1),(0,-1),(1,1),(2,-1),(3,1)],start=START,stop=STOP)
    return dict(outputs=outputs, frequency_hz=f, settled=all(r["settled"] for r in outputs),phase_grid=grid,
                supply_current_a=float(-np.trapezoid(w["i(vdd)"][w.t>=START], w.t[w.t>=START])/(STOP-START)))


def main():
    global TOP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--physical-dir", type=Path, required=True)
    ap.add_argument("--top", default=TOP)
    ap.add_argument("--method", choices=("trap","gear"), default="gear")
    ap.add_argument("--bias-reference",type=Path,help="Explicit completed schematic campaign; clamp bias to its measured mean")
    ap.add_argument("--bias-id",help="Registered calibrated DC source; required for new clamp runs")
    ap.add_argument("--ramp",action="store_true",help="Ramp local rail/bias/ctrl/config over 5 ns, kick at 6 ns")
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--points", nargs="+", default=POINTS)
    ap.add_argument("--variants", nargs="+", default=["schematic","cpex","rcx"])
    ap.add_argument("--workers", type=int, default=2, choices=(1,2))
    a = ap.parse_args()
    TOP = a.top
    if a.bias_reference and not a.bias_id:
        raise ValueError("Register the explicit DC calibration and use --bias-id; direct historical source paths alone are not accepted")
    if a.bias_id:
        bc=boundary.get(a.bias_id)
        if bc["kind"]!="calibrated_dc_bias":raise ValueError("Expected a calibrated DC bias boundary")
        boundary.check_load(a.bias_id,bias_load_signature(a.physical_dir/(TOP+"_pex.spice"),TOP))
    cases, ids, calibration = {}, {}, {}
    for point in a.points:
        voltage=None
        if a.bias_id:
            record=bc["points"][point]
            source=boundary.point_run(a.bias_id,point)/"waveforms.raw"
            ex=json.loads(source.with_name("execution.json").read_text())
            if ex["exit_code"]!=0 or ex["log_failures"]:raise ValueError("Invalid bias calibration execution")
            if hashlib.sha256(source.read_bytes()).hexdigest()!=record["waveform_sha256"]:
                raise ValueError("Calibration waveform changed")
            w=spice.Waves(source)
            if w.t[-1]<STOP*(1-1e-6):raise ValueError("Calibration waveform truncated")
            voltage=float(np.mean(w["vbias"][w.t>=START]))
            if abs(voltage-record["voltage_v"])>1e-12:raise ValueError("Calibration processing changed")
            calibration[point]=dict(path=str(source.relative_to(ROOT)),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),voltage=voltage)
        for variant in a.variants:
            key = point.replace(":","_")+"_"+variant
            cases[key] = deck(point,variant,a.physical_dir.resolve(),a.output_dir.resolve(),a.method,voltage,a.ramp), STOP
            ids[key] = point,variant
    paths = execute(cases,a.output_dir,workers=a.workers)
    rows = {key:measure(path) for key,path in paths.items()}
    save_analysis(a.output_dir,dict(scope=__doc__,cases=ids,rows=rows,bias_calibration=calibration,boundary_id=a.bias_id))


if __name__ == "__main__":
    main()
