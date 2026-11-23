"""Rough pre-layout area of a netlist hierarchy from ngspice's expanded listing (no simulation).

    uv run python verification/analysis/area_estimate.py <deck.cir> --top xpll [--depth 2] [--json out.json]
    uv run python verification/analysis/area_estimate.py --pll-core              (builds the pll_core_r5k4 deck itself)

ngspice parses the deck (`listing expand`, parameters evaluated) and every element under the --top instance is
grouped by its first --depth hierarchy levels below it.  Per element:
  MOS (m)       finger geometry: (W / nf + 0.6) x (nf (L + 0.6) + 0.6) um^2 (diffusion / contact pitch ~0.6 um)
  resistor      ideal R (r): high_po, w = 1 um unless R < 1012 Ohm (then w = ceil(1012 / R)), l = (R w - 378) / 317
                (passive card), area (w + 1.0) x (l + 2.0); PDK high_po as rhead + rbody (body only, w = 1 um) or as
                B-source bodies (brhrpoly*, width from the name); MIM series resistors (< 5 Ohm), >= 1 GOhm paths skipped
  capacitor (c) inside a PDK MIM unit (".xcap." or "mim" in the name, or >= 20 fF): C / 2 fF/um^2 x 1.3 (spacing);
                smaller capacitors are model or bench proxies and are only counted as such
Layout factors (analog CML / bias / CP: devices x 4, resistors x 1.5, MIM x 1.2; the MIM sits on metal 3-4 and can
overlap circuitry, so its area is reported apart and not added on top by default).  Rough: no extraction, no
guard-ring / well rules, no routing channels between blocks, no pads; a planning number, not a floorplan.
"""
import argparse
import json
import math
import re
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

from serdes_flow.project import ROOT, model_library

NGSPICE = "/opt/ngspice47/bin/ngspice"
LINE = re.compile(r"^\s*\d+\s*:\s*([mrcqb])\.(\S+)\s+(.*)$")
NUM = r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?(?:meg|[tgkmunpf])?)"
UNIT = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
WIDTH = {"0p35": 0.35, "0p69": 0.69, "1p41": 1.41, "2p85": 2.85, "5p73": 5.73}


def val(s):
    m = re.fullmatch(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)(meg|[tgkmunpf])?", s.strip().lower())
    return float(m[1]) * (UNIT[m[2]] if m[2] else 1.0)
F_MOS, F_RES, F_MIM = 4.0, 1.5, 1.2


def mos_area(rest):
    kv = {k: val(v) for k, v in re.findall(r"(\w+)=\s*" + NUM, rest)}
    w, l, nf = kv.get("w", 1.0), kv.get("l", 0.15), kv.get("nf", 1.0) or 1.0
    m = kv.get("m", 1.0)
    if w < 1e-3:                       # metres (no SCALE option)
        w, l = w * 1e6, l * 1e6
    return m * (w / nf + 0.6) * (nf * (l + 0.6) + 0.6), m * w * l


def res_area(value):
    if value < 5 or value >= 1e9:
        return None
    w = 1.0 if value >= 1012 else math.ceil(1012 / value)
    l = max((value * w - 378) / 317, 0.5)
    return (w + 1.0) * (l + 2.0)


def parse(listing, top, depth, exclude=()):
    groups = defaultdict(lambda: defaultdict(float))
    for line in listing.splitlines():
        mt = LINE.match(line)
        if not mt:
            continue
        kind, path, rest = mt.groups()
        parts = path.split(".")
        if top and (not parts or parts[0] != top):
            continue
        # instance path: the x-levels below top (all x-levels when no top), without the element's own name
        xs = [p for p in (parts[1:-1] if top else parts[:-1]) if p.startswith("x")]
        if exclude and xs and xs[0] in exclude:
            continue
        g = ".".join(xs[:depth]) if xs else "(top)"
        if kind == "m":
            a, wl = mos_area(rest)
            groups[g]["mos_um2"] += a
            groups[g]["mos_wl_um2"] += wl
            groups[g]["mos_n"] += 1
        elif kind == "r":
            if parts[-1].startswith("rhead"):               # PDK high_po contact head: inside the +2 um of its body
                continue
            geo = {k: val(v) for k, v in re.findall(r"\b([wl])=\s*" + NUM, rest)}
            mv = re.match(r"\S+\s+\S+\s+(?:r\s*=\s*)?" + NUM, rest)
            if "w" in geo and "l" in geo:                  # PDK body with its own geometry (um)
                a = (geo["w"] + 1.0) * (geo["l"] + 2.0)
            elif mv:
                a = res_area(val(mv[1]))
            else:
                a = None
            if True:
                if a is not None:
                    groups[g]["res_um2"] += a
                    groups[g]["res_n"] += 1
        elif kind == "b" and "brhrpoly" in parts[-1]:
            # PDK poly resistor body: i = v / (R_body * ...); width from the model name, ~317 Ohm/um x 1/w
            mv = re.search(r"/\s*\(\s*\(\s*" + NUM, rest)
            if mv:
                w = next((x for k2, x in WIDTH.items() if k2 in parts[-1]), 1.0)
                length = val(mv[1]) / (317.0 / w if w != 0.69 else 490.0)
                groups[g]["res_um2"] += (w + 1.0) * (length + 2.0)
                groups[g]["res_n"] += 1
        elif kind == "c":
            mv = re.search(r"c=\s*" + NUM, rest) or re.match(r"\S+\s+\S+\s+" + NUM, rest)
            if mv:
                c = val(mv[1])
                if ".xcap." in path or "mim" in path.lower() or c >= 20e-15:
                    groups[g]["mim_um2"] += c / 2e-15 * 1.3
                    groups[g]["mim_f"] += c
                else:
                    groups[g]["small_c_f"] += c
    for v in groups.values():
        v["est_um2"] = F_MOS * v["mos_um2"] + F_RES * v["res_um2"]
        v["mim_layout_um2"] = F_MIM * v["mim_um2"]
    return groups


def expand(deck_text, cwd=None):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "probe.cir"
        cwd = cwd or d
        body = re.sub(r"\.control.*?\.endc\s*", "", deck_text, flags=re.S | re.I)
        body = re.sub(r"^\.end\s*$", "", body, flags=re.M | re.I)
        body = re.sub(r"^(V\S+\s+\S+\s+\S+\s+)external\s*$", r"\g<1>0", body, flags=re.M | re.I)   # co-simulation inputs
        p.write_text(body + "\n.control\nlisting expand\nquit\n.endc\n.end\n")
        out = subprocess.run([NGSPICE, "-b", str(p)], capture_output=True, text=True, timeout=600, cwd=cwd)
        return out.stdout + out.stderr


def pll_core_deck():
    import importlib.util
    s = importlib.util.spec_from_file_location("native_k4", ROOT / "analog/pll/top/tb/native_k4/run.py")
    n = importlib.util.module_from_spec(s)
    s.loader.exec_module(n)
    lines = ["area probe: pll_core_r5k4", f'.lib "{model_library()}" tt'] + [f'.include "{ROOT / p}"' for p in n.INCLUDES]
    lines.append("Xpll ref rst_b vbn vbp ibuf vbias cfg0 cfg1 cfg2 cfg3 pre_ref pre_en ctrl z up dn fb0 c0p c0n c1p c1n c2p c2n c3p c3n vdd vdum 0 pll_core_r5k4")
    return "\n".join(lines) + "\n.end\n"


def report(groups, title):
    rows = sorted(groups.items(), key=lambda kv: -(kv[1]["est_um2"] + kv[1]["mim_layout_um2"]))
    tot = defaultdict(float)
    print(f"{title}\n{'group':40s} {'MOS n':>6s} {'MOS WL':>8s} {'MOS act':>8s} {'R':>8s} {'est':>9s} {'MIM pF':>7s} {'MIM lay':>9s}   (um^2)")
    for g, v in rows:
        print(f"{g:40s} {int(v['mos_n']):6d} {v['mos_wl_um2']:8.0f} {v['mos_um2']:8.0f} {v['res_um2']:8.0f} {v['est_um2']:9.0f} {v['mim_f'] * 1e12:7.2f} {v['mim_layout_um2']:9.0f}")
        for k, x in v.items():
            tot[k] += x
    print(f"{'total':40s} {int(tot['mos_n']):6d} {tot['mos_wl_um2']:8.0f} {tot['mos_um2']:8.0f} {tot['res_um2']:8.0f} {tot['est_um2']:9.0f} {tot['mim_f'] * 1e12:7.2f} {tot['mim_layout_um2']:9.0f}")
    print(f"devices + resistors with layout factors: {tot['est_um2'] / 1e6:.4f} mm^2; MIM {tot['mim_layout_um2'] / 1e6:.4f} mm^2 "
          f"(upper bound if it cannot overlap: {(tot['est_um2'] + tot['mim_layout_um2']) / 1e6:.4f} mm^2)")
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck", nargs="?")
    ap.add_argument("--top", default="xpll", help="instance to measure; '' = every top-level instance (use --exclude for bench parts)")
    ap.add_argument("--exclude", default="", help="comma-separated top-level instances to leave out (channel, bias, loads)")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--pll-core", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    text = pll_core_deck() if a.pll_core else Path(a.deck).read_text()
    excl = tuple(x.strip().lower() for x in a.exclude.split(",") if x.strip())
    groups = parse(expand(text, None if a.pll_core else Path(a.deck).resolve().parent), a.top.lower(), a.depth, excl)
    tot = report(groups, f"top {a.top}, depth {a.depth}")
    if a.json:
        Path(a.json).write_text(json.dumps(dict(top=a.top, depth=a.depth, factors=dict(mos=F_MOS, res=F_RES, mim=F_MIM),
                                                groups={g: dict(v) for g, v in groups.items()}, total=dict(tot)), indent=1))


if __name__ == "__main__":
    main()
