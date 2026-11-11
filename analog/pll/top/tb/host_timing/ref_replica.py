"""Host sensitivity of a replica reference path, to balance the feedback path's (host_timing/run.py) in the PFD.

    uv run python analog/pll/top/tb/host_timing/ref_replica.py [--points ...] [--cl 0,85e-15,170e-15,255e-15] [--workers 2]
        [--resume C]

Candidate reference input (docs/design/pll_loop.md "宿主定时延迟路径"): the 250 MHz reference as complementary CMOS
edges (swing 0..vh, 10 ps) -> one CML stage (serdes_cml_buffer, 600 Ohm loads like the prescaler's last latch, tail W
--wt on vbias, output load --cl per side to set the edge rate) -> the feedback path's own CML->CMOS receiver
(serdes_cml_to_cmos_pvt_candidate, 20 fF per output) -> a PFD input.  The prescaler output it imitates swings ~220-290 mV
single-ended from the supply with 180-240 ps 20-80 % differential edges; --cl 170 fF gives about that edge.  One replica
per --cl value in the same deck, all on the host source vh and the perturbed vbias (as host_timing/run.py: base,
vh +-dh, vbias +-db).  Kd_ref = d(receiver output rise at vh / 2 - ref edge) / dV.  The loop's residual is
Kd_fb0 - Kd_ref (Kd_fb0 from host_timing at the same point; the PFD + CP share is separate).
"""
import argparse
import importlib.util
import json
import time

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_h = importlib.util.spec_from_file_location("host_timing", ROOT / "analog/pll/top/tb/host_timing/run.py")
ht = importlib.util.module_from_spec(_h)
_h.loader.exec_module(ht)
RESULTS = ROOT / "results/analog/pll/top/host_timing_ref_replica"
INCLUDES = ["analog/common/devices/spice/sky130_primitives.spice", "analog/common/devices/spice/sky130_pfet_lvt.spice",
            "analog/common/devices/spice/cmos_logic.spice", "analog/common/devices/spice/cmos_dff_reset.spice",
            "analog/common/cml_buffer/spice/cml_delay_resistive.spice", "analog/common/cml_buffer/spice/cml_buffer.spice",
            "analog/common/cml_to_cmos/spice/cml_to_cmos.spice", "analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice",
            "analog/pll/pfd/spice/cmos_dff_reset.spice", "analog/pll/pfd/spice/pfd_cmos.spice"]
TREF, TR = 4e-9, 10e-12


def deck(c, rc, a, camp):
    cls = [float(x) for x in a.cl.split(",")]
    lines = ["Replica reference path: CMOS ref -> CML stage -> CML->CMOS receiver, host sensitivity",
             f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}']
    lines += [f'.include "{ROOT / p}"' for p in INCLUDES]
    lines += [f".param supply={c.supply}", "Vdd vdd 0 {supply}", "Vh vh 0 {supply}",
              "Iref vdd vbias .85m", "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4", "Vdb vbfe vbias 0",
              f"Vrefi refi 0 PULSE(0 1 2n {TR:.1e} {TR:.1e} {TREF / 2 - TR:.4e} {TREF:.4e})",
              "Bref refp 0 V=v(refi)*v(vh)", "Brefn refn 0 V=(1-v(refi))*v(vh)",
              f"Vfbi fbi 0 PULSE(0 1 {2e-9 + TREF / 2:.4e} {TR:.1e} {TR:.1e} {TREF / 2 - TR:.4e} {TREF:.4e})", "Bfb fbx 0 V=v(fbi)*v(vh)",
              "Erst rst_b 0 vh 0 1"]
    for k, cl in enumerate(cls):
        lines += [f"Xb{k} refp refn c{k}p c{k}n vbfe vh 0 serdes_cml_buffer wn=12 nfin=4 wt={a.wt} rload=600"]
        if cl > 0:
            lines += [f"Cl{k}p c{k}p 0 {cl:.4g}", f"Cl{k}n c{k}n 0 {cl:.4g}"]
        lines += [f"Xr{k} c{k}p c{k}n o{k} o{k}n vbfe vh 0 serdes_cml_to_cmos_pvt_candidate", f"Co{k} o{k} 0 20f", f"Co{k}n o{k}n 0 20f",
                  f"Xp{k} o{k} fbx rst_b up{k} dn{k} vh 0 pll_pfd"]
    probes = "v(refp) " + " ".join(f"v(o{k}) v(c{k}p) v(c{k}n)" for k in range(len(cls)))
    for k in range(len(cls)):
        lines += [f".nodeset v(xr{k}.xrestore.qp)=0 v(xr{k}.xrestore.qn)={{supply}}"]
    lines += [f".temp {c.temp}", ".options reltol=1e-4 abstol=1p vntol=1u", f".save {probes}", ".control", "set num_threads=1"]
    for name, dh, db in ht.runs(a):
        lines += [f"alter Vh dc={c.supply + dh:.4f}", f"alter Vdb dc={db:.4f}",
                  f"tran 2p {a.stop:.4e} {a.stop / 3:.4e} 2p", f"wrdata {name}.tsv {probes}", "destroy all"]
    lines += ["quit", ".endc", ".end"]
    text = bias.real(spice.binary_output("\n".join(lines) + "\n"))
    return bias.section(rcorner.to_pdk(text, camp), c.process, rc)


def measure(path, vh, stop, n):
    w = spice.Waves(path)
    t = w.t
    late = t > stop / 2
    t = t[late]
    ref = ht.crossings(t, w["v(refp)"][late], vh / 2)
    out = []
    for k in range(n):
        o = ht.crossings(t, w[f"v(o{k})"][late], vh / 2)
        d = ht.after(o, ref)
        d = d[np.isfinite(d) & (d < 3e-9)]
        out.append(float(np.median(d)) if len(d) else float("nan"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="ss_v1650_t-40:hh,fs_v1650_t-40:hh,ss_v1650_t85:hh,fs_v1650_t85:hh,sf_v1650_t85:hh,"
                                        "tt_v1800_t27:tt,fs_v1950_t-40:hh")
    ap.add_argument("--cl", default="0,85e-15,170e-15,255e-15")
    ap.add_argument("--wt", type=float, default=11.0, help="CML stage tail W (um, L 0.5): ~0.46 mA, ~280 mV swing at 600 Ohm")
    ap.add_argument("--dh", type=float, default=0.02)
    ap.add_argument("--db", type=float, default=0.005)
    ap.add_argument("--stop", type=float, default=24e-9)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--fb", default="results/analog/pll/top/host_timing/20261111T061902Z,results/analog/pll/top/host_timing/20261111T091746Z")
    ap.add_argument("--resume")
    a = ap.parse_args()
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    specs, cls = a.points.split(","), [float(x) for x in a.cl.split(",")]
    jobs = []
    for spec in specs:
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        d = camp / spec.replace(":", "_")
        if spice.case_output(d, "run", "bm.raw", a.stop) is not None:
            continue
        jobs.append((deck(c, rc, a, camp / "snap"), spice.next_run_dir(d, "run"), dict(timeout_s=3600, meta=dict(point=spec, cl=cls, wt=a.wt))))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    fb = {}
    for cmp in a.fb.split(","):
        fb.update(json.loads((ROOT / cmp / "summary.json").read_text())["rows"])
    rows = {}
    print(f"Kd in ps/mV (host, and per mV of vbias); residual = fb path - replica; CL per side {[round(x * 1e15) for x in cls]} fF")
    for spec in specs:
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        d = camp / spec.replace(":", "_")
        m = {}
        for name, dh, db in ht.runs(a):
            p = spice.case_output(d, "run", f"{name}.raw", a.stop)
            if p is None:
                break
            m[name] = measure(p, c.supply + dh, a.stop, len(cls))
        if len(m) < 5:
            print(f"{spec}: missing")
            continue
        kh = [(m["hp"][k] - m["hm"][k]) / (2 * a.dh) for k in range(len(cls))]
        kb = [(m["bp"][k] - m["bm"][k]) / (2 * a.db) for k in range(len(cls))]
        f = fb.get(spec, {})
        rows[spec] = dict(delay_s=m["base"], kd_ref_h=kh, kd_ref_b=kb, kd_fb_h=f.get("kd_h"), kd_fb_b=f.get("kd_b"))
        line = f"{spec:18s} fb {f.get('kd_h', float('nan')) * 1e9:+.2f}/{f.get('kd_b', float('nan')) * 1e9:+.2f} |"
        for k, cl in enumerate(cls):
            rh = f.get("kd_h", float("nan")) - kh[k]
            rb = f.get("kd_b", float("nan")) - kb[k]
            line += f" CL{cl * 1e15:.0f}: ref {kh[k] * 1e9:+.2f}/{kb[k] * 1e9:+.2f} resid {rh * 1e9:+.2f}/{rb * 1e9:+.2f} (dly {m['base'][k] * 1e12:.0f}) |"
        print(line, flush=True)
    camp.mkdir(parents=True, exist_ok=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
