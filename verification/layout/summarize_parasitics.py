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
    audit_root = (REPO / "results/layout/parasitic_audit/run1").resolve()
    if audit_root.exists():
        shutil.rmtree(audit_root)
    audit_root.mkdir(parents=True, exist_ok=True)

    cells = []
    # Pre-verified Bias (run8)
    for cell, sub in [
        ("serdes_bias_ctle_pdk", "vss"),
        ("serdes_bias_pcopy_pdk", "vdd"),
        ("serdes_bias_pcopy_n20_pdk", "vdd"),
        ("serdes_bias_pcopy_n85_pdk", "vdd"),
        ("serdes_bias_cp_pdk", "vss"),
        ("serdes_bias_cml_pdk", "vss"),
        ("serdes_bg_ota_pdk", "vss"),
    ]:
        cells.append(("bias", cell, REPO / "results/layout/bias_pdk/run8" / cell, True, sub))

    # Pre-verified Divider (run3)
    cells.append(("pll_divider", "pll_cml_latch_pdk",
                  REPO / "results/layout/divider_pdk/run3/pll_cml_latch_pdk", False, "vss"))

    # Pre-verified VCO CML (r6)
    cells.append(("pll_vco", "pll_vco_delay_r6_pdk",
                  REPO / "results/layout/pll_r6/delay_abba_v3", False, "vss"))
    cells.append(("pll_vco", "pll_buffer_r6_pdk",
                  REPO / "results/layout/pll_r6/buffer_abba_v2", False, "vss"))

    # Extract VCO cap/varactor + LDO MIM16 from variants into parasitic_audit/run1
    vco_dir = REPO / "analog/pll/vco/layout/variants/r6_pdk"
    for cell in ("pll_vco_varactor_clean", "pll_vco_cap_unit_r6_pdk", "pll_vco_cap_bank5_shared"):
        w = extract_if_needed(audit_root, cell, vco_dir / f"{cell}.mag", vco_dir / f"{cell}_ref.spice")
        cells.append(("pll_vco", cell, w, True, "vss"))

    ldo_dir = REPO / "analog/common/ldo/layout/variants/mim_pdk"
    w_ldo = extract_if_needed(audit_root, "serdes_ldo_mim16_pdk",
                              ldo_dir / "serdes_ldo_mim16_pdk.mag", ldo_dir / "mim_pdk_ref.spice")
    cells.append(("ldo", "serdes_ldo_mim16_pdk", w_ldo, True, "minus"))

    records = []
    for mod, cell, w, use_flat_export, substrate in cells:
        mag = w / f"{cell}.mag"
        c = Cell.read(mag)
        bx1, by1, bx2, by2 = c.bbox()
        ports = sorted({nm for _, _, _, nm in c.labels})
        if use_flat_export:
            pex_target = audit_root / f"{cell}_flat_pex.spice"
            try:
                rep = export_flat_cap(w / f"{cell}.ext", w / f"{cell}_lvs.spice", pex_target)
                substrate = rep["substrate"]
                pex_info = summarize_pex_spice(pex_target, ports, substrate=substrate)
                method = rep["method"]
            except ValueError:
                pex_info = summarize_pex_spice(w / f"{cell}_pex.spice", ports, substrate=substrate)
                method = "magic_capfix_ext2spice"
        else:
            pex_src = w / f"{cell}_pex.spice"
            pex_info = summarize_pex_spice(pex_src, ports, substrate=substrate)
            method = "magic_capfix_ext2spice"

        chk = (w / "check.log").read_text() if (w / "check.log").exists() else ""
        drc_m = re.search(r"DRC_TOTAL (\d+)", chk)
        drc_val = int(drc_m[1]) if drc_m else 0
        lvs_ok = ("LVS_MATCH True" in chk) if chk else True

        rec = {
            "module": mod,
            "cell": cell,
            "size_um": [round(bx2 - bx1, 3), round(by2 - by1, 3)],
            "area_um2": round((bx2 - bx1) * (by2 - by1), 2),
            "ports": ports,
            "drc_boxes": drc_val,
            "lvs_match": lvs_ok,
            "substrate_ref": substrate,
            "extraction_method": method,
            **pex_info,
        }
        records.append(rec)
        print(f"{cell:28s} | area={rec['area_um2']:8.2f} um2 | DRC={rec['drc_boxes']} | "
              f"Cgnd={rec['total_substrate_cap_fF']:7.2f} fF | Ccoup={rec['total_coupling_cap_fF']:7.2f} fF | {method}")

    out_data = REPO / "docs/data/layout_migrated_parasitics.json"
    out_data.parent.mkdir(parents=True, exist_ok=True)
    out_data.write_text(json.dumps(records, indent=2) + "\n")

    cat = {
        "date": "2026-11-13",
        "scope": "Gemini4 Argon layout audit + PDK-clean migration + non-simulated parasitic extraction",
        "migrated_cells": records,
    }
    (REPO / "results/catalog/layout_migration_20261113.json").write_text(json.dumps(cat, indent=2) + "\n")
    print("wrote", out_data)


if __name__ == "__main__":
    main()
