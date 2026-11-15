"""Recheck a frozen flat layout in an append-only review directory.

This extracts device geometry and capacitance, not distributed wire resistance.
The input .mag and LVS reference are copied and hashed before any tool runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import magicutil as mu
from check import exported_ports
from geometry import Cell
from summarize_parasitics import summarize_pex_spice


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review(mag: Path, reference: Path, out: Path) -> dict:
    mag, reference, out = mag.resolve(), reference.resolve(), out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cell = mag.stem
    inputs = {}
    for source, name in ((mag, mag.name), (reference, "reference.spice")):
        shutil.copy2(source, out / name)
        inputs[name] = {"source": str(source.relative_to(mu.REPO)), "sha256": sha256(source)}
    (out / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    proc = subprocess.run([sys.executable, str(HERE / "check.py"), str(out), cell,
                           "--ref", str(out / "reference.spice")], capture_output=True, text=True)
    log = proc.stdout + proc.stderr
    (out / "check.log").write_text(log)
    ports = exported_ports(out / f"{cell}_lvs.spice", cell)
    bbox = Cell.read(mag).bbox()
    report = dict(cell=cell, inputs=inputs, checker_exit=proc.returncode,
                  physical_passed=proc.returncode == 0, ports=ports,
                  bbox_um=bbox, size_um=[bbox[2]-bbox[0], bbox[3]-bbox[1]],
                  magic=mu.MAGIC, extraction="C + device AD/AS/PD/PS; wire R not extracted",
                  parasitics=summarize_pex_spice(out / f"{cell}_pex.spice", ports))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def extract_rc(work: Path, cell: str) -> dict:
    """Native Magic reduced RC, separately from the preserved CPEX matrix.

    Magic redistributes capacitance on resistor-extracted nets (including
    grounding coupling). This is a second screening model, not an exact
    coupled RC matrix. Keep both exports and quantify the difference.
    """
    work = work.resolve()
    script = work / "_rc.tcl"
    output = work / f"{cell}_rcx.spice"
    if output.exists():
        raise FileExistsError(output)
    script.write_text("\n".join([
        "drc off", f"cd {work}", f"load {cell}", "select top cell",
        "extresist threshold 1000", "extresist minres 1000",
        "extract do resistance", "extract all", "ext2spice lvs",
        "ext2spice cthresh 0", "ext2spice extresist on",
        f"ext2spice -o {output.name}", "quit -noprompt", ""]))
    result = mu.run_magic(script, work)
    (work / "rc.log").write_text(result.log)
    result.need("RC extraction")
    cpex = (work / f"{cell}_pex.spice").read_text()
    rcx = output.read_text()
    a = [line.split() for line in cpex.splitlines() if line.startswith("X")]
    b = [line.split() for line in rcx.splitlines() if line.startswith("X")]
    nets = {node for row in a for node in row[1:row.index(next(t for t in row if t.startswith("sky130_")))]}

    def original(node):
        base = re.sub(r"\.[nt]\d+$", "", node)
        return base + "#" if base + "#" in nets else base

    # Exact device/attribute identity and terminal parent-net identity.
    def normalized(row):
        idx = row.index(next(t for t in row if t.startswith("sky130_")))
        return row[:1] + [original(n) for n in row[1:idx]] + row[idx:]
    device_ok = len(a) == len(b) and all(normalized(x) == normalized(y) for x, y in zip(a, b))
    resistors = [line.split() for line in rcx.splitlines() if re.match(r"^R\S+\s", line)]
    # Every split terminal must have a DC path through R back to its original
    # net; no tool-created isolated device terminal may silently pass.
    adj = {}
    for row in resistors:
        n, m = row[1:3]
        if original(n) != original(m):
            raise ValueError(f"RC extractor bridged original nets: {row}")
        adj.setdefault(n, set()).add(m)
        adj.setdefault(m, set()).add(n)
    seen, components = set(), []
    for node in adj:
        if node in seen:
            continue
        stack, component = [node], set()
        while stack:
            n = stack.pop()
            if n in component:
                continue
            component.add(n)
            stack.extend(adj.get(n, set()) - component)
        seen |= component
        components.append(component)
    parents = [original(next(iter(c))) for c in components]
    if len(parents) != len(set(parents)):
        raise ValueError("Disconnected resistor subnetworks on the same original net")
    if not device_ok:
        raise ValueError("RC extraction changed device graph or geometry")
    summary = dict(method="Magic native reduced RC", threshold_ohm=1, minres_ohm=1,
                   resistor_count=len(resistors), resistor_nets=sorted(parents),
                   devices_preserved=device_ok, cpex_sha256=sha256(work / f"{cell}_pex.spice"),
                   rcx_sha256=sha256(output),
                   limits="Native extresist redistributes/grounds C on extracted nets; use alongside coupled CPEX, not as exact coupled-RC signoff")
    (work / "rc_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mag", type=Path)
    ap.add_argument("reference", type=Path)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--rc", action="store_true")
    args = ap.parse_args()
    r = review(args.mag, args.reference, args.output_dir)
    if args.rc and r["physical_passed"]:
        r["rc"] = extract_rc(args.output_dir, args.mag.stem)
    print(json.dumps(r, indent=2))
    raise SystemExit(0 if r["physical_passed"] else 1)


if __name__ == "__main__":
    main()
