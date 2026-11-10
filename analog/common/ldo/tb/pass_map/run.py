"""Characterize HV PMOS and 5 V native NMOS pass units; no LDO qualification.

One MOS-corner deck combines 3 input voltages x 3 temperatures. A separate
short DC smoke precedes the five decks. Raw/device/source identities and exact
DC grids are checked before data are used. Unit multiplication is a sizing
model; this campaign does not simulate a regulator or a bypass switch.
"""
import argparse
import fcntl
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from serdes_flow import project, spice, watch

ROOT = project.ROOT
SELF = Path(__file__).resolve()
OUT = ROOT / "results/analog/common/ldo/pass_map"
DEVICES = {"n": "nfet_05v0_nvt", "p": "pfet_g5v0d10v5"}
PROBES = [f"@m.x{kind}.msky130_fd_pr__{model}[{param}]"
          for kind, model in DEVICES.items() for param in ("gm", "gds", "vdsat")]
SOURCES = [SELF, ROOT / "src/serdes_flow/spice.py", ROOT / "src/serdes_flow/project.py", ROOT / "src/serdes_flow/watch.py",
           ROOT / "config/pdk.toml", ROOT / "config/tools.toml"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pdk_identity():
    root = project.model_library().parents[2]
    return {str(p): sha(p) for folder in ("libs.tech/ngspice", "libs.ref/sky130_fd_pr/spice")
            for p in sorted((root / folder).rglob("*")) if p.is_file()}


def filename(v, t):
    return f"v{round(v * 1000)}_t{t}.raw"


def deck(process, cases, smoke=False):
    probes = " ".join(PROBES)
    text = ["* LDO pass-unit DC map: native NMOS body at ground, PMOS body at input", f'.lib "{project.model_library()}" {process}',
            "Vdd dd 0 3.3", "Von sn 0 1.8", "Vop dp 0 1.8", "Vsweep sweep 0 0",
            "Bgn gn 0 V=v(sn)+v(sweep)", "Bgp gp 0 V=v(dd)-v(sweep)",
            "Xn dd gn sn 0 sky130_fd_pr__nfet_05v0_nvt w=10 l=0.9 nf=1 ad=2.9 as=2.9 pd=20.58 ps=20.58",
            "Xp dp gp dd dd sky130_fd_pr__pfet_g5v0d10v5 w=15 l=1 nf=1 ad=4.35 as=4.35 pd=30.58 ps=30.58",
            ".options reltol=1e-5 abstol=1p vntol=1u", f".save v(sweep) v(gn) v(gp) i(Vdd) i(Von) i(Vop) {probes}",
            ".control", "set num_threads=1", "set filetype=binary"]
    for v, t in cases:
        text += [f"option temp={t}", f"alter Vdd dc={v}", f"dc Vsweep 0 {0.01 if smoke else 3.6} 0.005",
                 f"write {filename(v,t)} v(sweep) v(gn) v(gp) i(Von) i(Vop) {probes}", "destroy all"]
    return "\n".join(text + ["quit", ".endc", ".end", ""])


def prepare():
    camp = OUT / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid4().hex[:8])
    camp.mkdir(parents=True)
    for path in SOURCES:
        target = camp / "source" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (camp / "prepared").mkdir()
    cases = [(v, t) for v in (3.0, 3.3, 3.6) for t in (-40, 27, 85)]
    entries = [dict(name="smoke", process="tt", cases=[(3.3, 27)], smoke=True)]
    entries += [dict(name=p, process=p, cases=cases, smoke=False) for p in ("ss", "sf", "fs", "ff", "tt")]
    for e in entries:
        path = camp / "prepared" / f"{e['name']}.cir"
        path.write_text(deck(e["process"], e["cases"], e["smoke"]))
        e.update(deck=str(path.relative_to(camp)), deck_sha256=sha(path))
    plan = dict(scope="PDK pass-unit DC characterization only, unit multiplication is a model, not LDO qualification",
                pdk_installation_id=project.pdk_installation_id(), pdk_sha256=pdk_identity(), entries=entries,
                sources={str(p.relative_to(ROOT)): sha(p) for p in SOURCES}, output_v=1.8,
                units=dict(n=dict(model=DEVICES['n'], w_um=10, l_um=.9), p=dict(model=DEVICES['p'], w_um=15, l_um=1)),
                constraints="NMOS gate <= Vin-0.1 V; PMOS gate >=0.1 V; no charge pump; all selected points within characterized grid")
    (camp / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return camp


def verify(camp):
    p = json.loads((camp / "plan.json").read_text())
    if project.pdk_installation_id() != p["pdk_installation_id"] or pdk_identity() != p["pdk_sha256"]:
        raise ValueError("PDK changed")
    for rel, digest in p["sources"].items():
        if sha(camp / "source" / rel) != digest:
            raise ValueError(f"Saved source changed: {rel}")
    if sha(SELF) != p["sources"][str(SELF.relative_to(ROOT))]:
        raise ValueError("Runner changed; create a new campaign")
    for e in p["entries"]:
        if sha(camp / e["deck"]) != e["deck_sha256"]:
            raise ValueError("Prepared deck changed")
    return p


def completed(camp, entry):
    for run in reversed([camp / entry["name"]] + sorted(camp.glob(entry["name"] + ".r[0-9]*"))):
        try:
            e = json.loads((run / "execution.json").read_text())
            if e["exit_code"] != 0 or e["timed_out"] or e["log_failures"] or e["deck_sha256"] != entry["deck_sha256"] or sha(run / "tb.cir") != entry["deck_sha256"]:
                continue
            expected = np.arange(3 if entry["smoke"] else 721) * .005
            waves = {}
            for v, t in entry["cases"]:
                path = run / filename(v, t)
                w = spice.Waves(path)
                if len(w.t) != len(expected) or not np.allclose(w.t, expected, atol=1e-9, rtol=0):
                    raise ValueError("DC sweep incomplete")
                if any(x not in w for x in PROBES):
                    raise ValueError("Missing device vectors")
                waves[(v, t)] = w
            return run, waves
        except (OSError, ValueError, KeyError):
            continue
    return None


def analyse(camp, plan):
    rows, missing = [], []
    for entry in plan["entries"]:
        if entry["smoke"]:
            continue
        got = completed(camp, entry)
        if got is None:
            missing.append(entry["name"])
            continue
        run, waves = got
        for (vin, temp), w in waves.items():
            for kind, model in DEVICES.items():
                current = w["i(von)"] if kind == "n" else w["i(vop)"]
                gate = w["v(gn)"] if kind == "n" else w["v(gp)"]
                for units in (25, 50, 100, 200, 400):
                    for ma in (2, 6, 10):
                        want = ma * 1e-3 / units
                        if not current[0] <= want <= current[-1] or np.any(np.diff(current) < -1e-10):
                            rows.append(dict(process=entry["process"], vin_v=vin, temp_c=temp, kind=kind, units=units, load_ma=ma, status="outside_measured_current_range"))
                            continue
                        vg = float(np.interp(want, current, gate))
                        gm = float(np.interp(want, current, w[f"@m.x{kind}.msky130_fd_pr__{model}[gm]"])) * units
                        gds = float(np.interp(want, current, w[f"@m.x{kind}.msky130_fd_pr__{model}[gds]"])) * units
                        head = vin - vg if kind == "n" else vg
                        rows.append(dict(process=entry["process"], vin_v=vin, temp_c=temp, kind=kind, units=units, load_ma=ma,
                                         gate_v=vg, gate_driver_room_v=head, gm_s=gm, gds_s=gds, intrinsic_gm_gds=gm/gds,
                                         status="measured_unit_scaling_driver_feasible" if head >= .1 else "gate_driver_headroom_shortfall",
                                         raw=str((run / filename(vin,temp)).relative_to(ROOT)), raw_sha256=sha(run / filename(vin,temp)),
                                         deck_sha256=entry["deck_sha256"], execution_sha256=sha(run / "execution.json")))
    out = camp / "analysis" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out.mkdir(parents=True)
    (out / "summary.json").write_text(json.dumps(dict(plan_sha256=sha(camp/"plan.json"), rows=rows, missing=missing, spec_status="ungraded"), indent=2, allow_nan=False) + "\n")
    print(out.relative_to(ROOT), flush=True)


def resume(camp, workers):
    with (camp / ".runner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = verify(camp)
        active = watch.ngspice_cwds()
        if any(p.is_relative_to(camp) for p in active) or len(active) + workers > 4:
            raise ValueError("Active campaign or no simulation slots")
        smoke = plan["entries"][0]
        if completed(camp, smoke) is None:
            spice.run((camp/smoke["deck"]).read_text(), spice.next_run_dir(camp,"smoke"), timeout_s=240)
        if completed(camp, smoke) is None:
            raise ValueError("DC smoke failed")
        jobs = []
        for entry in plan["entries"][1:]:
            if completed(camp, entry) is None:
                jobs.append(((camp/entry["deck"]).read_text(), spice.next_run_dir(camp, entry["name"]), dict(timeout_s=300)))
        spice.run_many(jobs, workers=workers, smoke=False)
        analyse(camp, plan)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--resume", type=Path)
    group.add_argument("--analyse", type=Path)
    ap.add_argument("--workers", type=int, choices=(1, 2), default=2)
    args = ap.parse_args()
    if args.prepare:
        print(prepare().relative_to(ROOT))
    elif args.resume:
        resume(args.resume.resolve(), args.workers)
    else:
        camp=args.analyse.resolve(); analyse(camp,verify(camp))
