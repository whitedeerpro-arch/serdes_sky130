"""Frozen r6 TT local-frequency mismatch pilot; not PLL or yield qualification."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np
from serdes_flow import mc, project, spice, watch

ROOT = project.ROOT
SELF = Path(__file__).resolve()
STOP = 24e-9
ANALYSIS = "\n".join([
    "tran 2p 24n 12n 2p", "let vd = v(v0p)-v(v0n)",
    "meas tran ta when vd=0 rise=2 from=14n",
    "meas tran tb when vd=0 rise=12 from=14n",
    "meas tran vb avg v(vbias_q) from=14n to=24n",
])
LETS = {"freq": "10/(tb-ta)", "vbias_v": "vb"}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def prepare(parent):
    plan = json.loads((parent / "plan.json").read_text())
    for n, h in plan["snapshots"].items():
        if sha(parent / n) != h:
            raise ValueError("Parent snapshot changed: " + n)
    e = next(e for e in plan["entries"] if e["name"] == "f50_a0")
    c = ROOT / "results/analog/pll/vco/mismatch_r6" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    c.mkdir(parents=True)
    shutil.copytree(parent / "snap", c / "snap")
    shutil.copyfile(SELF, c / "runner.py")
    net = (parent / "prepared/f50_a0.cir").read_text().replace(str(parent / "snap"), str(c / "snap"))
    net, n = re.subn(r"(?ims)^\.control\s*.*?^\.endc\s*", "", net)
    if n != 1:
        raise ValueError("Unexpected parent control block")
    net = re.sub(r"(?im)^\.end\s*$", "", net)
    mm, n = re.subn(r'(?im)^(\.lib\s+"[^"]+"\s+)tt\s*$', r'\g<1>tt_mm', net)
    if n != 1:
        raise ValueError("Unexpected parent library")
    entries = []
    for k, seed, count in mc.chunks(8, 6, 4):
        entries.append(dict(name=f"chunk{k:02}", seed=seed, count=count, kind="mismatch"))
    entries += [dict(name="repeat0", seed=6000, count=1, kind="repeat"),
                dict(name="nominal", seed=6000, count=1, kind="nominal")]
    (c / "prepared").mkdir()
    for item in entries:
        text = mc.deck(net if item["kind"] == "nominal" else mm, item["count"],
                       seed=item["seed"], analysis=ANALYSIS, lets=LETS, t_end=STOP, profile=True)
        (c / "prepared" / (item["name"] + ".cir")).write_text(text)
    # Independent one-ns nominal smoke, keeping full PDK and the same DUT.
    smoke = net + "\n.control\nset num_threads=1\nset filetype=binary\ntran 2p 1n 0 2p\nwrite smoke.raw v(v0p) v(v0n)\nquit\n.endc\n.end\n"
    (c / "prepared/smoke.cir").write_text(smoke)
    result = dict(parent=str(parent.relative_to(ROOT)), parent_plan_sha256=sha(parent / "plan.json"),
                  code=e["code"], vctrl_v=e["vctrl_v"], entries=entries,
                  pdk_id=project.pdk_installation_id(), model_sha256=sha(project.model_library()),
                  snapshots={str(p.relative_to(c)): sha(p) for p in c.rglob("*") if p.is_file()},
                  scope="TT/1.8V/27C, code9 fixed map Vctrl, full tt_mm PDK including shared BG and fixed-R; ring+4 buffers30fF, slow tail; original varactor model; eight local samples only, not calibrated range, closed-loop, PVT, stochastic noise or yield qualification")
    (c / "plan.json").write_text(json.dumps(result, indent=2) + "\n")
    return c


def check(c):
    p = json.loads((c / "plan.json").read_text())
    if p["pdk_id"] != project.pdk_installation_id() or p["model_sha256"] != sha(project.model_library()):
        raise ValueError("PDK changed")
    for n, h in p["snapshots"].items():
        if sha(c / n) != h:
            raise ValueError("Snapshot changed: " + n)
    return p


def jobs(c, p):
    return [((c / "prepared" / (e["name"] + ".cir")).read_text(), c / e["name"],
             dict(timeout_s=2400, meta=e)) for e in p["entries"]]


def analyse(c):
    p = check(c)
    runs = mc.completed(jobs(c, p))
    if any(d is None for d in runs):
        raise ValueError("Incomplete pilot; retain explicit sample count")
    rows, other, inputs = [], {}, []
    for e, d in zip(p["entries"], runs):
        read = mc.read(d)
        for i, r in enumerate(read):
            if not all(np.isfinite(r[k]) for k in LETS) or r["freq"] <= 0:
                raise ValueError("Missing or invalid measurement")
            item = dict(r, seed=e["seed"], sample_in_chunk=i, run=str(d.relative_to(ROOT)))
            (rows if e["kind"] == "mismatch" else other.setdefault(e["kind"], [])).append(item)
        inputs.extend(dict(path=str((d / n).relative_to(ROOT)), sha256=sha(d / n))
                      for n in ("tb.cir", "execution.json", "mc.tsv", "simulator.log"))
    repeated = {k: other["repeat"][0][k] == rows[0][k] for k in LETS}
    if len(rows) != 8 or not all(repeated.values()) or len({r["freq"] for r in rows}) < 2:
        raise ValueError("Sample identity/variation check failed")
    freq = np.array([r["freq"] for r in rows])
    result = dict(campaign=str(c.relative_to(ROOT)), plan_sha256=sha(c / "plan.json"),
                  scope=p["scope"], rows=rows, other=other, repeat_exact=repeated, inputs=inputs,
                  samples=len(rows), frequency_mean_hz=float(freq.mean()),
                  frequency_sd_hz=float(freq.std(ddof=1)), relative_sd=float(freq.std(ddof=1) / freq.mean()),
                  frequency_min_hz=float(freq.min()), frequency_max_hz=float(freq.max()))
    out = c / "analysis" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out.mkdir(parents=True)
    (out / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(out / "summary.json", flush=True)


def resume(c):
    with (c / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        p = check(c)
        if len(watch.ngspice_cwds()) >= 4:
            raise ValueError("Global slots occupied")
        text = (c / "prepared/smoke.cir").read_text()
        d = spice.case_output(c, "smoke", "smoke.raw", t_end=1e-9)
        if d is None:
            d = spice.next_run_dir(c, "smoke")
            ex = spice.run(text, d, timeout_s=300)
            if not ex.ok or spice.Waves(d / "smoke.raw").t[-1] < 1e-9 * (1 - 1e-6):
                raise ValueError("Smoke failed")
        mc.run_many(jobs(c, p), workers=1)
        analyse(c)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prepare", type=Path)
    g.add_argument("--resume", type=Path)
    g.add_argument("--analyse", type=Path)
    a = ap.parse_args()
    if a.prepare:
        print(prepare(a.prepare.resolve()))
    elif a.resume:
        resume(a.resume.resolve())
    else:
        analyse(a.analyse.resolve())
