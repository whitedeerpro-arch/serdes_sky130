#!/usr/bin/env python3
"""DRC, LVS and parasitic extraction for a generated Magic cell.

Usage:
    python verification/layout/check.py <layout-dir> <cell-name> [--ref <ref.spice>]

Runs (each in its own Magic session):
  * DRC with the full sky130A rule set,
  * flat extraction -> <cell>_lvs.spice, netgen LVS against <ref>,
  * capacitive extraction (cthresh 0, extresist) -> <cell>_pex.spice.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import magicutil as mu  # noqa: E402


def drc(work: Path, cell: str) -> tuple[int, str]:
    """Full-rule DRC; returns (error-box count, per-rule summary).

    In batch mode `drc check` only queues the check: without `drc catchup` the
    count is taken before the checker ran and always reads 0 (the 2026-11-11
    loop-filter "DRC clean" was that false pass).
    """
    script = work / "_drc.tcl"
    script.write_text(
        "\n".join([
            "drc off",
            f"cd {work}",
            f"load {cell}",
            "select top cell",
            "drc on",
            "drc style drc(full)",
            "drc check",
            "drc catchup",
            'puts "DRC_TOTAL [drc list count total]"',
            'foreach {why boxes} [drc listall why] { puts "DRC_RULE [llength $boxes] | $why" }',
            "quit -noprompt",
        ]) + "\n"
    )
    res = mu.run_magic(script, work)
    m = re.search(r"^DRC_TOTAL\s+(\d+)", res.log, re.M)
    if m is None:
        raise RuntimeError(f"DRC did not report a total:\n{res.log[-3000:]}")
    rules = sorted((l[len("DRC_RULE "):] for l in res.log.splitlines() if l.startswith("DRC_RULE ")),
                   key=lambda l: -int(l.split("|")[0]))
    return int(m[1]), "\n".join(rules)


def extract(work: Path, cell: str, cellname: str) -> None:
    script = work / "_ext.tcl"
    script.write_text(
        "\n".join([
            "drc off",
            f"cd {work}",
            f"load {cell}",
            "select top cell",
            "extract all",
            "ext2spice lvs",
            f"ext2spice -o {cellname}_lvs.spice",
            "ext2spice cthresh 0",
            "ext2spice extresist on",
            f"ext2spice -o {cellname}_pex.spice",
            "quit",
        ]) + "\n"
    )
    mu.run_magic(script, work).need("extraction")


def exported_ports(path: Path, cell: str) -> list[str]:
    """Read the extracted top interface; internal labels are not ports.

    Netgen can match a labelled graph whose .subckt header has no pins. Such a
    cell is unusable hierarchically, even when its internal devices match.
    """
    logical = re.sub(r"\n[ \t]*\+", " ", path.read_text())
    header = re.search(rf"^\.subckt[ \t]+{re.escape(cell)}(?:[ \t]+([^\n]*))?$", logical, re.M | re.I)
    if header is None:
        return []
    ports = []
    for token in (header[1] or "").split():
        if token.lower() == "params:" or "=" in token:
            break
        ports.append(token)
    return ports


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("layout_dir", type=Path)
    ap.add_argument("cell")
    ap.add_argument("--ref", type=Path, default=None)
    args = ap.parse_args()
    work = args.layout_dir.resolve()
    cell = args.cell

    total, rules = drc(work, cell)
    print(f"DRC_TOTAL {total}")
    if rules:
        print(rules)
    extract(work, cell, cell)
    if args.ref:
        log = work / f"{cell}_lvs.log"
        res = mu.netgen(work / f"{cell}_lvs.spice", cell, args.ref.resolve(), log, work)
        tail = [
            l for l in res.stdout.splitlines()
            if re.search(r"match|mismatch|Result|devices,|nets,|Warning|Error", l, re.I)
        ]
        print("\n".join(tail[-25:]))
        prop_err = "Property errors were found" in res.stdout
        text = res.stdout + (log.read_text() if log.exists() else "")
        # netgen still reports a unique match when a port label sits on an isolated shape ("disconnected node: d",
        # found by Codex's inverter audit, 2026-11-11): count it as a failure.
        disc = sorted(set(re.findall(r"disconnected node:\s*(\S+)", text, re.I)))
        ports = exported_ports(work / f"{cell}_lvs.spice", cell)
        lvs_ok = "Circuits match uniquely" in res.stdout and not prop_err and not disc and bool(ports)
        print(f"LVS_MATCH {'Circuits match uniquely' in res.stdout}  LVS_PROPERTY_ERRORS {prop_err}  (see {log.name})")
        print(f"LVS_DISCONNECTED {' '.join(disc) if disc else 'none'}")
        print(f"LVS_EXPORTED_PORTS {' '.join(ports) if ports else 'none (invalid DUT interface)'}")
    else:
        lvs_ok = None
    # Exit status is the verdict: nonzero unless DRC is 0 and (with --ref) LVS matches uniquely.
    sys.exit(0 if total == 0 and lvs_ok is not False else 1)


if __name__ == "__main__":
    main()
