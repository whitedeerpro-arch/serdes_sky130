#!/usr/bin/env python3
"""Extract and summarize basic parasitic parameters across all migrated PDK leaves (no simulation).

Uses `flat_cap_export.export()` (audited EXT node/cap matrix + LVS devices) for
flat MOS/MIM/varactor cells without resistors, and Magic-capfix `_pex.spice`
for cells containing `res_high_po*` resistor bodies.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "verification/layout"))
from flat_cap_export import export as export_flat_cap  # noqa: E402
from geometry import Cell  # noqa: E402


UNIT_MAP = {
    "": 1.0,
    "f": 1e-15,
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "a": 1e-18,
}


def parse_cap_val_fF(tok: str) -> float:
    m = re.match(r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)([a-zA-Z]*)$", tok.strip())
    if not m:
        raise ValueError(f"Unrecognized cap value: {tok}")
    val = float(m.group(1))
    sfx = m.group(2).lower()
    if sfx not in UNIT_MAP:
        raise ValueError(f"Unrecognized cap suffix: {tok}")
    scale = UNIT_MAP[sfx]
    return val * (scale * 1e15 if scale != 1.0 else 1e15)


def summarize_pex_spice(pex_path: Path, ports: list[str], substrate: str = "vss") -> dict:
    text = pex_path.read_text()
    ad_sum = as_sum = pd_sum = ps_sum = 0.0
    mos_count = 0
    for line in text.splitlines():
        if line.startswith("X"):
            if "nfet" in line or "pfet" in line:
                mos_count += 1
            for key, acc_name in (("ad", "ad"), ("as", "as"), ("pd", "pd"), ("ps", "ps")):
                m = re.search(rf"\b{key}=([0-9.eE+-]+)\b", line)
                if m:
                    v = float(m.group(1))
                    if acc_name == "ad":
                        ad_sum += v
                    elif acc_name == "as":
                        as_sum += v
                    elif acc_name == "pd":
                        pd_sum += v
                    else:
                        ps_sum += v

    gnd_fF: dict[str, float] = defaultdict(float)
    couple_fF: dict[tuple[str, str], float] = defaultdict(float)
    cap_count = 0
    for line in text.splitlines():
        if not line.startswith("C"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        cap_count += 1
        n1, n2, raw_v = parts[1], parts[2], parts[3]
        v_fF = parse_cap_val_fF(raw_v)
        if n1 == substrate and n2 != substrate:
            gnd_fF[n2] += v_fF
        elif n2 == substrate and n1 != substrate:
            gnd_fF[n1] += v_fF
        elif n1 != n2:
            couple_fF[tuple(sorted((n1, n2)))] += v_fF

    port_caps = {}
    for p in ports:
        if p == substrate:
            continue
        cg = gnd_fF.get(p, 0.0)
        cc = sum(v for (a, b), v in couple_fF.items() if p in (a, b))
        port_caps[p] = {
            "to_substrate_fF": round(cg, 3),
            "coupling_sum_fF": round(cc, 3),
            "total_node_fF": round(cg + cc, 3),
        }

    top_coupling = [
        {"node_a": a, "node_b": b, "cap_fF": round(v, 3)}
        for (a, b), v in sorted(couple_fF.items(), key=lambda kv: -kv[1])[:8]
    ]
    return {
        "extracted_mos_segments": mos_count,
        "ad_um2": round(ad_sum, 3),
        "as_um2": round(as_sum, 3),
        "pd_um": round(pd_sum, 3),
        "ps_um": round(ps_sum, 3),
        "pex_cap_elements": cap_count,
        "total_substrate_cap_fF": round(sum(gnd_fF.values()), 3),
        "total_coupling_cap_fF": round(sum(couple_fF.values()), 3),
        "port_caps_fF": port_caps,
        "top_coupling_fF": top_coupling,
    }


def extract_if_needed(work_root: Path, cell: str, mag_src: Path, ref_src: Path) -> Path:
    w = (work_root / cell).resolve()
    w.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mag_src, w / f"{cell}.mag")
    shutil.copy2(ref_src, w / "reference.spice")
    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"),
         str(w), cell, "--ref", str(w / "reference.spice")],
        capture_output=True, text=True, check=False,
    )
    (w / "check.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"check failed for {cell}:\n{proc.stdout}\n{proc.stderr}")
    return w


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Summarize extracted parasitic capacitances from a Magic PEX SPICE file.")
    ap.add_argument("pex_spice", type=Path, help="Path to extracted *_pex.spice file")
    ap.add_argument("--mag", type=Path, default=None, help="Optional .mag file to auto-detect ports and bbox")
    ap.add_argument("--ports", default="", help="Comma-separated port list (overrides --mag labels)")
    ap.add_argument("--substrate", default="vss", help="Substrate net name (default: vss)")
    ap.add_argument("--out", type=Path, default=None, help="Optional JSON output path")
    args = ap.parse_args()

    pex_path = args.pex_spice.resolve()
    ports = [p.strip() for p in args.ports.split(",") if p.strip()]
    size_meta: dict = {}
    if args.mag is not None:
        c = Cell.read(args.mag.resolve())
        bx1, by1, bx2, by2 = c.bbox()
        size_meta = {
            "size_um": [round(bx2 - bx1, 3), round(by2 - by1, 3)],
            "area_um2": round((bx2 - bx1) * (by2 - by1), 2),
        }
        if not ports:
            ports = sorted({nm for _, _, _, nm in c.labels})

    rec = {
        "pex_spice": str(pex_path),
        "substrate_ref": args.substrate,
        "ports": ports,
        **size_meta,
        **summarize_pex_spice(pex_path, ports, substrate=args.substrate),
    }
    text = json.dumps(rec, indent=2) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
