"""Boundary conditions: upstream waveforms reused as stimuli of a downstream bench.

A boundary condition (BC) is any stimulus copied or derived from another
simulation: a frozen edge record idealised into sources, a recorded node
voltage replayed as PWL, a measured curve turned into a behavioural model.
Conclusions drawn on a BC hold only while the conditions it was made under
hold, so every BC is registered once, referenced by id, and checked.

Registry: config/boundary_conditions.json (git-tracked), one entry per id:

    id, kind, description
    upstream     module and working revision that produced it
    nodes        what is replayed and where it enters the consumer
    load         the consumer input stage present when it was recorded
                 (signature from `input_stage_signature`); None if not applicable
    points       per operating point: condition tag, operating values, source
                 run directory, its git revision and deck hash
    processing   how the stimulus is derived from the source runs
    validation   comparison against the un-cut co-simulation, if any
    valid_while  conditions that invalidate it when broken

Consumers resolve sources through `point_run`, never by "latest run" lookups,
and call `check_load` with the signature of the input stage they actually
simulate.  A mismatch raises; exploratory runs may override it, and must then
record that they did.
"""
import hashlib
import json
import re
from pathlib import Path

from . import project

REGISTRY = project.ROOT / "config" / "boundary_conditions.json"


class BoundaryMismatch(RuntimeError):
    pass


def registry() -> dict:
    if not REGISTRY.exists():
        return {}
    return {e["id"]: e for e in json.loads(REGISTRY.read_text())}


def get(bc_id: str) -> dict:
    reg = registry()
    if bc_id not in reg:
        raise KeyError(f"boundary condition {bc_id!r} not registered in {REGISTRY.relative_to(project.ROOT)}")
    return reg[bc_id]


def register(entry: dict, *, extend: bool = False) -> dict:
    """Add a BC.  With extend=True an existing id may gain new points, provided
    every other field is identical and no existing point is changed."""
    reg = registry()
    old = reg.get(entry["id"])
    if old is not None:
        if not extend:
            raise BoundaryMismatch(f"{entry['id']} already registered")
        same = {k: v for k, v in old.items() if k != "points"} == {k: v for k, v in entry.items() if k != "points"}
        clash = [p for p in entry["points"] if p in old["points"] and old["points"][p] != entry["points"][p]]
        if not same or clash:
            raise BoundaryMismatch(f"{entry['id']}: fields differ or points changed ({clash})")
        entry = dict(old, points={**old["points"], **entry["points"]})
    reg[entry["id"]] = entry
    REGISTRY.write_text(json.dumps(sorted(reg.values(), key=lambda e: e["id"]), indent=1, ensure_ascii=False) + "\n")
    return entry


def point_run(bc_id: str, point: str) -> Path:
    bc = get(bc_id)
    if point not in bc["points"]:
        raise KeyError(f"{bc_id} has no point {point!r} (has {sorted(bc['points'])})")
    run = project.ROOT / bc["points"][point]["run"]
    if not run.exists():
        raise FileNotFoundError(f"{bc_id}/{point}: source run {run} missing")
    return run


def _subckt_body(text: str, name: str):
    lines, cur = [], None
    for raw in text.splitlines():
        s = raw.split("*", 1)[0].rstrip() if not raw.lstrip().startswith("*") else ""
        if not s:
            continue
        if s.lstrip().startswith("+") and cur is not None:
            cur += " " + s.lstrip()[1:]
            continue
        if cur is not None:
            lines.append(cur)
        cur = s.strip()
    if cur is not None:
        lines.append(cur)
    body, inside, ports = [], False, None
    for l in lines:
        t = l.split()
        if t[0].lower() == ".subckt" and t[1] == name:
            inside = True
            ports = [x for x in t[2:] if "=" not in x and x.lower() != "params:"]
            continue
        if inside and t[0].lower().startswith(".ends"):
            return ports, body
        if inside:
            body.append(l)
    raise ValueError(f"subckt {name} not found")


def input_stage_signature(netlist: str | Path, subckt: str, inputs) -> dict:
    """Normalised instances of `subckt` that touch any of the `inputs` ports.

    Instance names and non-input node names are dropped, parameters sorted, so
    two netlists that present the same devices to the inputs get the same sha.
    Output-side loading of those stages (Miller) is not part of it.
    """
    text = Path(netlist).read_text() if isinstance(netlist, Path) else netlist
    _, body = _subckt_body(text, subckt)
    inputs = set(inputs)
    stages = []
    for l in body:
        t = l.split()
        nodes = [x for x in t[1:] if "=" not in x]
        if not inputs & set(nodes):
            continue
        cell = nodes[-1] if t[0][0].upper() == "X" else ""
        pins = [x if x in inputs else "_" for x in (nodes[:-1] if cell else nodes)]
        params = sorted(re.sub(r"\s+", "", x) for x in t[1:] if "=" in x)
        stages.append(" ".join([t[0][0].upper(), *pins, cell, *params]).strip())
    stages.sort()
    return dict(stages=stages, sha=hashlib.sha256("\n".join(stages).encode()).hexdigest()[:16])


def check_load(bc_id: str, signature: dict, *, allow_mismatch: bool = False) -> bool:
    """True if the consumer input stage equals the recording load."""
    load = get(bc_id).get("load")
    if load is None or load["sha"] == signature["sha"]:
        return True
    msg = (f"{bc_id} was recorded with input stage {load['sha']} but the consumer has {signature['sha']}:\n"
           f"  recorded: {load['stages']}\n  consumer: {signature['stages']}")
    if not allow_mismatch:
        raise BoundaryMismatch(msg)
    print("WARNING (load mismatch allowed): " + msg, flush=True)
    return False


def run_record(run_dir: Path, **values) -> dict:
    """Per-point registry record for a source run directory."""
    ex = json.loads((Path(run_dir) / "execution.json").read_text())
    return dict(run=str(Path(run_dir).resolve().relative_to(project.ROOT)), git_revision=ex.get("git_revision"),
                deck_sha256=ex.get("deck_sha256"), **values)
