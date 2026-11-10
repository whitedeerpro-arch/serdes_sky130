"""Extend a selected quiet-pin capacitance endpoint over all 255 AC boundaries.

Reuse the r4 source/deck/measurement checks and fixed per-model voltage codes.
Extra capacitance is an ideal shunt, not a pad/package model or proof of all
intermediate capacitances. Root uses at most two simulator slots globally.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
from uuid import uuid4

from serdes_flow import project

ROOT = project.ROOT
SELF = Path(__file__).resolve()
spec = importlib.util.spec_from_file_location("ldo_r4", SELF.with_name("run.py"))
r4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r4)
OUT = ROOT / "results/analog/common/ldo/r4_cap_pvt"


def prepare(grid_path, extra_pf, crossed=False):
    data = json.loads(grid_path.read_text())
    if data["missing"] or len(data["rows"]) != 1215:
        raise ValueError("Require complete original DC grid")
    source = ROOT / data["campaign"]
    parent = r4.verify(source)
    if r4.sha(source / "plan.json") != data["plan_sha256"]:
        raise ValueError("Grid identity changed")
    for path in r4.CELLS:
        if r4.sha(path) != parent["cell_sha256"][str(path.relative_to(ROOT))]:
            raise ValueError("Current DUT changed")
    campaign = OUT / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid4().hex[:8])
    (campaign / "source").mkdir(parents=True)
    (campaign / "prepared").mkdir()
    for path in [SELF, *r4.RUNTIME, *r4.CELLS]:
        target = campaign / "source" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    entries = [dict(parent["entries"][0])]
    for old in parent["entries"][1:]:
        if crossed and old["rc"] not in ("ll", "hh"):
            continue
        entry = dict(old, cases=[dict(x) for x in old["cases"] if x["ac"]])
        if crossed:
            # The first letter selects R, the second C. Keep the original
            # per-die code when only the capacitor corner changes.
            rc = {"ll": "lh", "hh": "hl"}[old["rc"]]
            entry.update(rc=rc, name=old["mos"] + "_" + rc, section=r4.section(old["mos"], rc))
        entries.append(entry)
    if any(len(e["cases"]) != 17 for e in entries[1:]):
        raise ValueError("Expected16 corners plus nominal per MOS/RC")
    for entry in entries:
        text = r4.deck(entry).replace(".control\n", f"Cpin_extra quiet 0 {extra_pf}p\n.control\n", 1)
        path = campaign / "prepared" / (entry["name"] + ".cir")
        path.write_text(text)
        entry.update(deck=str(path.relative_to(campaign)), deck_sha256=r4.sha(path))
    plan = dict(suite="pin_cap_pvt", entries=entries, pdk_sha256=parent["pdk_sha256"],
                cell_sha256=parent["cell_sha256"], extra_pin_capacitance_pf=extra_pf,
                crossed_rc=crossed, expected_ac_points=170 if crossed else 255,
                calibration_policy="retain original code from same R corner; capacitor DC leakage not assumed, compare nominal DC output",
                parent_grid_summary=str(grid_path.relative_to(ROOT)), parent_grid_sha256=r4.sha(grid_path),
                calibration_summary=parent["calibration_summary"], calibration_sha256=parent["calibration_sha256"],
                runtime={str(p.relative_to(ROOT)): r4.sha(p) for p in [SELF, *r4.RUNTIME]},
                sources={str(p.relative_to(campaign)): r4.sha(p) for p in (campaign / "source").rglob("*") if p.is_file()},
                scope=f"HV18 r4, additional{extra_pf}pF ideal quiet-pin capacitance,{170 if crossed else 255} AC boundary/nominal conditions,RC {'hl/lh' if crossed else 'll/tt/hh'}; fixed original same-R calibrated code; no pad/ESD/PEX/package or full interval qualification")
    (campaign / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return campaign


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", type=Path)
    mode.add_argument("--resume", type=Path)
    mode.add_argument("--analyse", type=Path)
    ap.add_argument("--extra-pf", type=float, default=100)
    ap.add_argument("--rc-crossed", action="store_true", help="check hl/lh with codes retained from hh/ll of the same R extreme")
    ap.add_argument("--workers", type=int, choices=(1, 2), default=1)
    args = ap.parse_args()
    if args.prepare:
        if args.extra_pf <= 0:
            raise ValueError("Extra capacitance must be positive")
        print(prepare(args.prepare.resolve(), args.extra_pf, args.rc_crossed).relative_to(ROOT))
    elif args.resume:
        r4.resume(args.resume.resolve(), args.workers)
    else:
        r4.analyse(args.analyse.resolve(), r4.verify(args.analyse.resolve()))
