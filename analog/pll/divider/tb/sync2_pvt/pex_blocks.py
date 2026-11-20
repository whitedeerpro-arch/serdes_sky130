"""Compare schematic vs block-level C-PEX vs block-level RCX for pll_sync_prescaler8_2stack.

    uv run python analog/pll/divider/tb/sync2_pvt/pex_blocks.py --pdk-dir results/layout/sync2_divider/pdk_blocks_r5 --workers 4
"""
import argparse
import importlib.util
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_sp = importlib.util.spec_from_file_location("sync2_pvt", ROOT / "analog/pll/divider/tb/sync2_pvt/run.py")
sp = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(sp)

RESULTS = ROOT / "results/analog/pll/divider/sync2_block_pex"
PROBES = "v(bp) v(bn) v(d02p) v(d02n) v(d04p) v(d04n) v(d08p) v(d08n) v(fb0) v(fb0n) i(Vdd)"
BLOCKS = ("sync2_buf_out_pdk", "sync2_buf_ckpre_pdk", "sync2_buf_ckdrv_pdk", "sync2_latch_pdk", "sync2_mux2_pdk", "sync2_dff_pdk")


def build_pex_lib(pdk_dir: Path, mode: str, out_spice: Path, include_dff: bool = False) -> None:
    suf = "_pex.spice" if mode == "cpex" else "_rcx.spice"
    parts = [f"* Combined {mode} blocks from {pdk_dir}"]
    for b in BLOCKS:
        if b == "sync2_dff_pdk" and not include_dff:
            continue
        parts.append((pdk_dir / b / f"{b}{suf}").read_text())
    out_spice.write_text("\n".join(parts) + "\n")


def patch_deck(c: Condition, rc: str, mode: str, pex_lib: Path | None, snap_dir: Path, use_dff: bool = False, use_rshunt: bool = True) -> str:
    text = sp.deck(c, rc, 2.0e9, 0.3, snap_dir)
    # Remove internal node probes that do not exist inside flattened PEX/RCX subckts
    text = re.sub(r"^\.save .*$", f".save {PROBES}", text, flags=re.M)
    text = re.sub(r"^write pre\.raw .*$", f"write pre.raw {PROBES}", text, flags=re.M)
    if use_rshunt:
        text = text.replace(".options reltol=1e-4 abstol=1p vntol=1u", ".options reltol=1e-4 abstol=1p vntol=1u rshunt=1e12")
    if mode == "schematic":
        return text
    if mode == "top_cpex":
        assert pex_lib is not None
        # Parse exported subckt port order from Magic _pex.spice (continuation '+' allowed)
        hdr_m = re.search(r"^\.subckt\s+pll_sync_prescaler8_2stack_pdk\s+([^\n]+(?:\n\+[^\n]+)*)", pex_lib.read_text(), flags=re.M)
        assert hdr_m, f"Missing .subckt header in {pex_lib}"
        pins = [t for t in hdr_m.group(1).replace("\n+", " ").split() if t]
        net_map = dict(clkp="bp", clkn="bn", q2p="d02p", q2n="d02n", q4p="d04p", q4n="d04n", q8p="d08p", q8n="d08n", vbias="vbias", vdd="vdd", vss="0")
        call_nets = " ".join(net_map[p] for p in pins)
        text = text.replace(
            "Xpre bp bn d02p d02n d04p d04n d08p d08n vbias vdd 0 pll_sync_prescaler8_2stack",
            f"Xpre {call_nets} pll_sync_prescaler8_2stack_pdk",
        )
        text, n = re.subn(r'^\.include\s+"[^"]*sync_prescaler8_2stack\.spice"', f'.include "{pex_lib}"', text, count=1, flags=re.M)
        assert n == 1
        return text
    src = (ROOT / "analog/pll/divider/spice/sync_prescaler8_2stack.spice").read_text()
    if use_dff:
        src = src.replace("sync2_dff wdata={wdata} whold={whold} wclock={wclock} rload={rload}", "sync2_dff_pdk")
    else:
        src = src.replace("sync2_latch wdata={wdata} whold={whold} wclock={wclock} rload={rload}", "sync2_latch_pdk")
    src = src.replace("sync2_mux2\n", "sync2_mux2_pdk\n").replace(" sync2_mux2\n", " sync2_mux2_pdk\n")
    src = src.replace("sync2_buf wn=20 nfin=4 wt=12 nft=4 rload=850", "sync2_buf_ckpre_pdk")
    src = src.replace("sync2_buf wn=32 nfin=4 wt=24 nft=4 rload=550", "sync2_buf_ckdrv_pdk")
    src = src.replace("sync2_buf wn=24 nfin=4 wt=12 nft=4 rload=550", "sync2_buf_out_pdk")
    # Inject pex_lib BEFORE patched sync_prescaler8 wrapper
    wrap_path = snap_dir / f"sync2_wrap_{mode}.spice"
    wrap_path.write_text(f'.include "{pex_lib}"\n' + src)
    text, n = re.subn(r'^\.include\s+"[^"]*sync_prescaler8_2stack\.spice"', f'.include "{wrap_path}"', text, count=1, flags=re.M)
    assert n == 1
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-dir", type=Path, default=None)
    ap.add_argument("--top-cpex", type=Path, default=None, help="Full-chip _pex.spice for schematic vs top_cpex check")
    ap.add_argument("--points", default="tt_v1800_t27:tt,fs_v1650_t85:hh,ss_v1650_t-40:hh,ff_v1950_t85:ll")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--use-dff", action="store_true", help="Substitute sync2_dff_pdk directly instead of separate latch_pdk + schematic Xseed")
    ap.add_argument("--no-rshunt", action="store_true", help="Omit rshunt=1e12 to prove zero floating nodes")
    a = ap.parse_args()
    if a.top_cpex is None and a.pdk_dir is None:
        ap.error("Provide --pdk-dir or --top-cpex")
    pdk_dir = a.pdk_dir.resolve() if a.pdk_dir else a.top_cpex.resolve().parent
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    snap = camp / "snap"
    snap.mkdir(parents=True, exist_ok=True)
    if a.top_cpex is not None:
        modes = ("schematic", "top_cpex")
        libs = {"top_cpex": a.top_cpex.resolve()}
    else:
        modes = ("schematic", "cpex", "rcx")
        libs = {}
        for mode in ("cpex", "rcx"):
            libs[mode] = snap / f"blocks_{mode}.spice"
            build_pex_lib(pdk_dir, mode, libs[mode], include_dff=a.use_dff)
    jobs = []
    specs = a.points.split(",")
    for s in specs:
        cond, rc = s.split(":")
        c = Condition.parse(cond)
        for mode in modes:
            txt = patch_deck(c, rc, mode, libs.get(mode), snap, use_dff=a.use_dff, use_rshunt=not a.no_rshunt)
            jobs.append((txt, spice.next_run_dir(camp / f"{cond}_{rc}" / mode, "run"), dict(timeout_s=1800, meta=dict(point=s, mode=mode))))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    for s in specs:
        cond, rc = s.split(":")
        rows[s] = {}
        for mode in modes:
            p = spice.case_output(camp / f"{cond}_{rc}" / mode, "run", "pre.raw", sp.STOP)
            if p is None:
                print(f"{s:22s} {mode:9s} MISSING")
                continue
            w = spice.Waves(p)
            tm = w.t[w.t >= 14e-9]
            m_idx = w.t >= 14e-9
            q2, _, f2, tr2, tf2 = sp._edges(tm, w["v(d02p)"][m_idx] - w["v(d02n)"][m_idx])
            q4, _, f4, tr4, tf4 = sp._edges(tm, w["v(d04p)"][m_idx] - w["v(d04n)"][m_idx])
            q8, _, f8, tr8, _ = sp._edges(tm, w["v(d08p)"][m_idx] - w["v(d08n)"][m_idx])
            fb, _, ffb, _, _ = sp._edges(tm, w["v(fb0)"][m_idx] - w["v(fb0n)"][m_idx])
            sk4 = float(np.mean([x - tf2[np.argmin(np.abs(tf2 - x))] for x in tr4[1:-1]])) * 1e12 if len(tr4) > 2 else float("nan")
            sk8 = float(np.mean([x - tf4[np.argmin(np.abs(tf4 - x))] for x in tr8[1:-1]])) * 1e12 if len(tr8) > 2 else float("nan")
            idd = float(-np.mean(w["i(Vdd)"][m_idx]) * 1e3)
            rows[s][mode] = dict(q2=q2, q4=q4, q8=q8, fb=fb, f2=f2, f4=f4, f8=f8, ffb=ffb, sk4_ps=sk4, sk8_ps=sk8, idd_ma=idd)
            print(f"{s:22s} {mode:9s} | q2={q2*1e3:5.1f}({f2/1e6:6.1f}) q4={q4*1e3:5.1f}({f4/1e6:5.1f}) q8={q8*1e3:5.1f}({f8/1e6:5.1f}) fb={fb*1e3:6.1f} | sk4={sk4:+5.2f}ps sk8={sk8:+5.2f}ps | Id={idd:4.2f}mA")
    (camp / "summary.json").write_text(json.dumps(dict(pdk_dir=str(pdk_dir), rows=rows), indent=2))
    print(camp)


if __name__ == "__main__":
    main()
