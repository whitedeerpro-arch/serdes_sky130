#!/usr/bin/env python3
"""Shared SKY130A PDK layout primitives, cached device builder, frozen SPICE
reference flattener, CPEX/RCX/metal-share analyzers, and Magic/Netgen runners
for RX v2 Zero-CML Front-End (`analog/rx/cmos_rx/layout/`).

Hard safety guarantees:
  - Never invokes ngspice.
  - All temporary files, Magic/Netgen logs, `.ext`, `.spice`, `.sim` live
    strictly under `results/layout/rx_cmos_v2/` (never inside `analog/`).
  - Always passes `-dnull -noconsole`, `quit -noprompt`, resolved absolute
    paths, and bounded Python `timeout=120` to Magic and Netgen.
"""
from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

REPO = Path(__file__).resolve().parents[4]
LAYOUT_VERIF = REPO / "verification/layout"
if str(LAYOUT_VERIF) not in sys.path:
    sys.path.insert(0, str(LAYOUT_VERIF))

from check import exported_ports  # noqa: E402
from geometry import Cell, pdk_device  # noqa: E402
import magicutil as mu  # noqa: E402
from summarize_parasitics import parse_cap_val_fF, summarize_pex_spice  # noqa: E402

RX_SPICE_DIR = REPO / "analog/rx/cmos_rx/spice"
COMMON_SPICE_DIR = REPO / "analog/common/devices/spice"

N_STD = "sky130_fd_pr__nfet_01v8"
N_LVT = "sky130_fd_pr__nfet_01v8_lvt"
P_STD = "sky130_fd_pr__pfet_01v8"
P_LVT = "sky130_fd_pr__pfet_01v8_lvt"
R_0P35 = "sky130_fd_pr__res_high_po_0p35"
R_0P69 = "sky130_fd_pr__res_high_po_0p69"
R_2P85 = "sky130_fd_pr__res_high_po_2p85"
R_5P73 = "sky130_fd_pr__res_high_po_5p73"
MIM1 = "sky130_fd_pr__cap_mim_m3_1"

W_M1 = 0.180
W_M2 = 0.280
W_M3 = 0.340
W_M4 = 0.400


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def clone_cell(src: Cell) -> Cell:
    c = Cell()
    c.rects = {k: list(v) for k, v in src.rects.items()}
    c.labels = list(src.labels)
    return c


class PdkCache:
    """Cache Magic `pdk_device` calls strictly inside a resolved scratch directory."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir.resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, Cell] = {}
        self._mos_mem: dict[str, tuple[Cell, dict]] = {}

    def _key(self, model: str, params: dict[str, Any]) -> str:
        items = "_".join(
            f"{k}{str(v).replace('.', 'p').replace('-', 'm')}"
            for k, v in sorted(params.items())
        )
        short_mdl = model.replace("sky130_fd_pr__", "")
        return f"{short_mdl}__{items}"

    def device(self, model: str, params: dict[str, Any]) -> Cell:
        key = self._key(model, params)
        if key not in self._mem:
            mag_path = self.cache_dir / f"{key}.mag"
            if mag_path.exists():
                c = Cell.read(mag_path)
            else:
                c = self._pdk_device_bounded(key, model, params)
            c.rects.pop("checkpaint", None)
            self._mem[key] = c
        return clone_cell(self._mem[key])

    def _pdk_device_bounded(self, name: str, model: str, params: dict[str, Any], timeout_s: int = 120) -> Cell:
        mag_path = self.cache_dir / f"{name}.mag"
        mu.new_cell(mag_path)
        pstr = " ".join(f"{k} {v}" for k, v in params.items())
        script = self.cache_dir / f"{name}.tcl"
        script.write_text(
            f"drc off\nload {name}\nbox values 0 0 0 0\n"
            f"set p [dict merge [sky130::{model}_defaults] [dict create {pstr}]]\n"
            f"sky130::{model}_draw $p\nsave {name}\nquit -noprompt\n"
        )
        res = run_magic_bounded(script, self.cache_dir, timeout_s=timeout_s)
        (self.cache_dir / f"{name}.log").write_text(res.log)
        res.need(name)
        return Cell.read(mag_path)

    def build_mos(
        self,
        model: str,
        w_f: float,
        l_f: float,
        nf: int,
        dy: float,
        is_pmos: bool,
        keep_m1: bool = False,
    ) -> tuple[Cell, dict]:
        """Draw a compact guard=0 MOS centered in X at 0 and in Y at `dy`, with clipped poly."""
        w_f, l_f, dy = grid(w_f), grid(l_f), grid(dy)
        key = f"{model}_{w_f:.3f}_{l_f:.3f}_{nf}_{dy:.3f}_{int(is_pmos)}_{int(keep_m1)}"
        if key not in self._mos_mem:
            p = self.device(model, dict(w=w_f, l=l_f, nf=nf, conn_gates=0, topc=0, botc=0, guard=0))
            out = Cell()
            cut_layer = "pdiffc" if is_pmos else "ndiffc"
            diff_layer = "pdiff" if is_pmos else "ndiff"
            h_clip = grid(w_f / 2.0 + 0.140)
            skip = ("pwell", "nwell", "checkpaint") if keep_m1 else ("viali", "metal1", "pwell", "nwell", "checkpaint")

            for layer, rects in p.rects.items():
                if layer in skip:
                    continue
                for x1, y1, x2, y2 in rects:
                    if layer == "poly":
                        y1 = max(y1, -h_clip)
                        y2 = min(y2, h_clip)
                        if y2 <= y1:
                            continue
                    out.rect(layer, grid(x1), grid(y1 + dy), grid(x2), grid(y2 + dy))

            sds = sorted({grid((r[0] + r[2]) / 2.0) for r in p.rects[cut_layer]})
            gxs = sorted({grid((r[0] + r[2]) / 2.0) for r in p.rects["poly"]})
            diffs = out.rects[diff_layer]
            diff_x1 = grid(min(r[0] for r in diffs))
            diff_x2 = grid(max(r[2] for r in diffs))
            c_y1 = grid(min(r[1] for r in p.rects[cut_layer]) + dy)
            c_y2 = grid(max(r[3] for r in p.rects[cut_layer]) + dy)
            info = {
                "w_diff": grid(diff_x2 - diff_x1),
                "hw_diff": grid((diff_x2 - diff_x1) / 2.0),
                "diff_x1": diff_x1,
                "diff_x2": diff_x2,
                "s_xs": sds[::2],
                "d_xs": sds[1::2],
                "all_sd_xs": sds,
                "g_xs": gxs,
                "l_f": l_f,
                "w_f": w_f,
                "nf": nf,
                "c_y1": c_y1,
                "c_y2": c_y2,
                "diff_y1": grid(dy - w_f / 2.0),
                "diff_y2": grid(dy + w_f / 2.0),
                "poly_y1": grid(dy - h_clip),
                "poly_y2": grid(dy + h_clip),
                "dy": dy,
            }
            self._mos_mem[key] = (out, info)
        cell, info = self._mos_mem[key]
        return clone_cell(cell), dict(info)


# ---------------------------------------------------------------------------
# DRC-clean low-level drawing primitives
# ---------------------------------------------------------------------------

def poly_cont_pad(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.pad("poly", x, y, 0.27, 0.34)
    c.pad("polycont", x, y, 0.17, 0.17)
    c.pad("locali", x, y, 0.18, 0.34)


def viali_pad(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.pad("viali", x, y, 0.17)
    # 0.29 x 0.29 = 0.0841 um^2 > 0.083 um^2 Metal1 minimum area rule (met1.6)
    c.pad("metal1", x, y, 0.29, 0.29)


def via1_clean(c: Cell, x: float, y: float) -> None:
    c.via1(grid(x), grid(y))


def via2_clean(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.via2(x, y)
    c.pad("metal3", x, y, 0.52)


def via3_pad(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.pad("metal3", x, y, 0.52)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.52)


def via4_pad(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.pad("metal4", x, y, 1.56)
    c.pad("via4", x, y, 1.18)
    c.pad("metal5", x, y, 1.80)


def locali_v(c: Cell, x: float, y1: float, y2: float) -> None:
    ya, yb = sorted((grid(y1), grid(y2)))
    c.rect("locali", grid(x - 0.085), ya, grid(x + 0.085), yb)


def locali_h(c: Cell, x1: float, x2: float, y: float) -> None:
    xa, xb = sorted((grid(x1), grid(x2)))
    c.rect("locali", grid(xa - 0.085), grid(y - 0.085), grid(xb + 0.085), grid(y + 0.085))


def draw_tap_h(
    c: Cell,
    diff_layer: str,
    x1: float,
    x2: float,
    y: float,
    half_w: float = 0.175,
    with_m1: bool = False,
    m1_w: float = 0.360,
    viali_pitch: float = 0.800,
) -> None:
    x1, x2, y = grid(x1), grid(x2), grid(y)
    c.rect(diff_layer, x1, grid(y - half_w), x2, grid(y + half_w))
    c.rect("locali", x1, grid(y - 0.085), x2, grid(y + 0.085))
    if (x2 - x1) >= 0.48:
        c.rect(diff_layer + "cont", grid(x1 + 0.14), grid(y - 0.085), grid(x2 - 0.14), grid(y + 0.085))
    if with_m1:
        c.rect("metal1", x1, grid(y - m1_w / 2.0), x2, grid(y + m1_w / 2.0))
        xv = grid(x1 + 0.30)
        while xv <= x2 - 0.30 + 1e-6:
            c.pad("viali", xv, y, 0.17)
            xv = grid(xv + viali_pitch)


def draw_tap_v(
    c: Cell,
    diff_layer: str,
    x: float,
    y1: float,
    y2: float,
    half_w: float = 0.180,
    with_m1: bool = False,
    m1_w: float = 0.360,
    viali_pitch: float = 0.800,
) -> None:
    x, y1, y2 = grid(x), grid(min(y1, y2)), grid(max(y1, y2))
    c.rect(diff_layer, grid(x - half_w), grid(y1 - 0.085), grid(x + half_w), grid(y2 + 0.085))
    c.rect("locali", grid(x - 0.085), grid(y1 - 0.085), grid(x + 0.085), grid(y2 + 0.085))
    if (y2 - y1) >= 0.90:
        c.rect(diff_layer + "cont", grid(x - 0.085), grid(y1 + 0.360), grid(x + 0.085), grid(y2 - 0.360))
    if with_m1:
        c.rect("metal1", grid(x - m1_w / 2.0), y1, grid(x + m1_w / 2.0), y2)
        yv = grid(y1 + 0.36)
        while yv <= y2 - 0.36 + 1e-6:
            c.pad("viali", x, yv, 0.17)
            yv = grid(yv + viali_pitch)


def tie_mos_gates(
    c: Cell,
    cx: float,
    info: dict,
    y_bar: float,
    y_cont: float,
    tap_xs: list[float] | None = None,
) -> list[tuple[float, float]]:
    """Connect all poly fingers of a `build_mos` instance to a poly bar at `y_bar` and contact at `y_cont`."""
    lf = info["l_f"]
    hw = grid(lf / 2.0)
    gxs = [grid(cx + g) for g in info["g_xs"]]
    y_bar, y_cont = grid(y_bar), grid(y_cont)
    # Overlap PDK poly endcap cleanly (0.05 um outside diff edge, well inside the 0.13 um PDK endcap)
    y_from = grid(info["diff_y2"] + 0.050) if y_bar >= info["dy"] else grid(info["diff_y1"] - 0.050)
    ya, yb = sorted((y_from, y_bar))
    for gx in gxs:
        c.rect("poly", grid(gx - hw), ya, grid(gx + hw), yb)
    bar_h = max(0.180, lf)
    if tap_xs is None:
        tap_xs = [grid(cx)]
    bx1 = min(gxs[0] - hw, min(grid(tx) - max(0.135, hw) for tx in tap_xs))
    bx2 = max(gxs[-1] + hw, max(grid(tx) + max(0.135, hw) for tx in tap_xs))
    if bx2 - bx1 > 2 * hw + 0.005:
        c.rect("poly", grid(bx1), grid(y_bar - bar_h / 2.0),
               grid(bx2), grid(y_bar + bar_h / 2.0))
    pts = []
    for tx in tap_xs:
        tx = grid(tx)
        y1, y2 = sorted((y_bar, y_cont))
        c.rect("poly", grid(tx - max(0.135, hw)), grid(y1 - 0.09), grid(tx + max(0.135, hw)), grid(y2 + 0.09))
        poly_cont_pad(c, tx, y_cont)
        viali_pad(c, tx, y_cont)
        pts.append((tx, y_cont))
    return pts


def add_tied_poly_dummy(
    c: Cell,
    x_poly: float,
    y_lo: float,
    y_hi: float,
    l_f: float,
    y_cont: float,
    x_cont: float | None = None,
) -> tuple[float, float]:
    """Draw a gate-length-matched field-poly dummy with guaranteed polycont -> locali -> viali -> M1."""
    x_poly, y_lo, y_hi, y_cont = grid(x_poly), grid(y_lo), grid(y_hi), grid(y_cont)
    hw = grid(l_f / 2.0)
    xc = grid(x_cont if x_cont is not None else x_poly)
    c.rect("poly", grid(x_poly - hw), min(y_lo, grid(y_cont - 0.17)),
           grid(x_poly + hw), max(y_hi, grid(y_cont + 0.17)))
    if abs(xc - x_poly) > 0.005:
        c.rect("poly", grid(min(x_poly, xc) - hw), grid(y_cont - 0.17),
               grid(max(x_poly, xc) + hw), grid(y_cont + 0.17))
    poly_cont_pad(c, xc, y_cont)
    viali_pad(c, xc, y_cont)
    return (xc, y_cont)


# ---------------------------------------------------------------------------
# Frozen SPICE Reference Netlist Evaluator (exact 1:1 from analog/rx/cmos_rx/spice/)
# ---------------------------------------------------------------------------

def _eval_expr(expr: str, env: dict[str, float]) -> float:
    s = expr.strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1].strip()
    safe_globals = {
        "__builtins__": {},
        "max": max, "min": min, "floor": math.floor, "ceil": math.ceil, "abs": abs,
    }
    return float(eval(s, safe_globals, env))


def _fmt_num(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.6g}"


def _parse_spice_subckts(paths: list[Path]) -> dict[str, dict]:
    subckts: dict[str, dict] = {}
    for p in paths:
        raw_lines = p.read_text().splitlines()
        logical: list[str] = []
        for ln in raw_lines:
            s = ln.strip()
            if not s or s.startswith("*"):
                continue
            if s.startswith("+") and logical:
                logical[-1] += " " + s[1:].strip()
            else:
                logical.append(s)

        cur: dict | None = None
        for ln in logical:
            low = ln.lower()
            if low.startswith(".subckt "):
                toks = ln.split()
                name = toks[1]
                ports: list[str] = []
                defaults: dict[str, str] = {}
                in_params = False
                for tok in toks[2:]:
                    if tok.lower() == "params:":
                        in_params = True
                        continue
                    if in_params or "=" in tok:
                        in_params = True
                        k, v = tok.split("=", 1)
                        defaults[k.lower()] = v
                    else:
                        ports.append(tok)
                cur = {"name": name, "ports": ports, "defaults": defaults, "insts": []}
                subckts[name] = cur
            elif low.startswith(".ends"):
                cur = None
            elif cur is not None and ln[0].upper() == "X":
                toks = ln.split()
                inst_name = toks[0]
                param_idx = len(toks)
                for i in range(2, len(toks)):
                    if "=" in toks[i]:
                        param_idx = i
                        break
                model = toks[param_idx - 1]
                conns = toks[1 : param_idx - 1]
                ov: dict[str, str] = {}
                for tok in toks[param_idx:]:
                    k, v = tok.split("=", 1)
                    ov[k.lower()] = v
                cur["insts"].append((inst_name, conns, model, ov))
    return subckts


def generate_rx_ref_spice(
    top_src_subckt: str,
    top_out_subckt: str,
    out_path: Path,
    param_overrides: dict[str, float] | None = None,
) -> list[str]:
    """Flatten frozen RX v2 SPICE into an exact SKY130 primitive reference netlist for Netgen."""
    subckts = _parse_spice_subckts([
        COMMON_SPICE_DIR / "sky130_primitives.spice",
        COMMON_SPICE_DIR / "sky130_pfet_lvt.spice",
        REPO / "analog/common/bias/spice/bias_v2.spice",
        RX_SPICE_DIR / "rx_ctle_pdk.spice",
        RX_SPICE_DIR / "rx_dt_sampler.spice",
        RX_SPICE_DIR / "rx_cmos_pi.spice",
        RX_SPICE_DIR / "rx_cmos_deser16.spice",
        RX_SPICE_DIR / "rx_cmos_top.spice",
    ])
    if top_src_subckt not in subckts:
        raise KeyError(f"Unknown subckt {top_src_subckt}")

    top_def = subckts[top_src_subckt]
    top_ports = list(top_def["ports"])
    lines: list[str] = [
        f"* Exact flattened LVS reference netlist for {top_out_subckt}",
        f"* Source subckt: {top_src_subckt} (frozen analog/rx/cmos_rx/spice/*.spice)",
        f".subckt {top_out_subckt} " + " ".join(top_ports),
    ]
    dev_idx = 0

    def expand(sub_name: str, port_map: dict[str, str], env: dict[str, float], prefix: str) -> None:
        nonlocal dev_idx
        sdef = subckts[sub_name]
        local_env = {}
        for k, v in sdef["defaults"].items():
            local_env[k] = _eval_expr(v, env)
        local_env.update(env)

        for inst_name, conns, model, ov in sdef["insts"]:
            mapped_conns = [port_map.get(c, f"{prefix}_{c}") for c in conns]
            child_env = {k: _eval_expr(v, local_env) for k, v in ov.items()}
            if model.startswith("sky130_fd_pr__"):
                dev_idx += 1
                p_strs = []
                if "nfet" in model or "pfet" in model:
                    p_strs.append(f"w={_fmt_num(child_env['w'])}")
                    p_strs.append(f"l={_fmt_num(child_env['l'])}")
                elif "res_high_po_" in model:
                    p_strs.append(f"l={_fmt_num(child_env['l'])}")
                elif "cap_mim_" in model:
                    p_strs.append(f"w={_fmt_num(child_env['w'])}")
                    p_strs.append(f"l={_fmt_num(child_env['l'])}")
                else:
                    for k, v in sorted(child_env.items()):
                        p_strs.append(f"{k}={_fmt_num(v)}")
                lines.append(f"X{dev_idx} " + " ".join(mapped_conns) + f" {model} " + " ".join(p_strs))
            elif model in subckts:
                cdef = subckts[model]
                if len(mapped_conns) != len(cdef["ports"]):
                    raise ValueError(f"Port count mismatch calling {model}: {len(mapped_conns)} != {len(cdef['ports'])}")
                cmap = dict(zip(cdef["ports"], mapped_conns))
                expand(model, cmap, child_env, f"{prefix}_{inst_name}")
            else:
                raise KeyError(f"Unknown model {model} inside {sub_name}")

    init_env = {k: _eval_expr(v, {}) for k, v in top_def["defaults"].items()}
    if param_overrides:
        init_env.update(param_overrides)
    expand(top_src_subckt, {p: p for p in top_ports}, init_env, "t")
    lines.append(f".ends {top_out_subckt}")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    return top_ports


# ---------------------------------------------------------------------------
# Bounded Magic / Netgen / review_cell.py / Quality & Parasitic Audits
# ---------------------------------------------------------------------------

def run_magic_bounded(script: Path, cwd: Path, timeout_s: int = 120) -> mu.MagicResult:
    proc = subprocess.run(
        [mu.MAGIC, "-dnull", "-noconsole", "-rcfile", str(mu.RCFILE), str(script.resolve())],
        cwd=cwd.resolve(),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    log = proc.stdout + proc.stderr
    clean = "\n".join(
        l for l in log.splitlines()
        if "tk_version" not in l and "version_check.tcl" not in l
    )
    bad = re.search(r"Error parsing|no such|No such cell", clean)
    return mu.MagicResult(log=log, ok=(proc.returncode == 0 and bad is None))


def run_netgen_bounded(
    layout: Path, top: str, ref: Path, out_log: Path, cwd: Path, timeout_s: int = 120
) -> subprocess.CompletedProcess:
    cwd = cwd.resolve()
    shim = cwd / "_netgen_local.tcl"
    text = mu.NETGEN_TCL.read_text().replace(
        "load /usr/lib/netgen/tcl/tclnetgen.so",
        f"load {mu.NGC}/tcl/tclnetgen.so",
    )
    shim.write_text(text)
    script = cwd / "_netgen_run.tcl"
    script.write_text(
        "set argv [list lvs {%s %s} {%s %s} %s %s]\n"
        "source %s\n" % (layout.resolve(), top, ref.resolve(), top, mu.NETGEN_SETUP, out_log.resolve(), shim.resolve())
    )
    return subprocess.run(
        [str(mu.NETGENEXEC), str(script.resolve())], cwd=cwd, capture_output=True, text=True, timeout=timeout_s
    )


def verify_flat_cell(
    work: Path,
    cell: str,
    mag_src: Path,
    ref_src: Path,
    expected_ports: list[str],
    timeout_s: int = 120,
) -> dict:
    """Run full-rule Magic DRC, LVS extraction, Netgen LVS, and CPEX inside `work`."""
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    mag = work / f"{cell}.mag"
    ref = work / f"{cell}_ref.spice"
    if mag_src.resolve() != mag:
        shutil.copy2(mag_src, mag)
    if ref_src.resolve() != ref:
        shutil.copy2(ref_src, ref)

    lvs_sp = work / f"{cell}_lvs.spice"
    pex_sp = work / f"{cell}_pex.spice"
    lvs_log = work / f"{cell}_lvs.log"

    tcl = work / "_drc_ext.tcl"
    tcl.write_text("\n".join([
        "drc off",
        f"load {cell}",
        "select top cell",
        "drc on",
        "drc euclidean on",
        "drc style drc(full)",
        "drc check",
        "drc catchup",
        'puts "DRC_TOTAL=[drc list count total]"',
        'foreach {why boxes} [drc listall why] { puts "DRC_RULE [llength $boxes] | $why" }',
        "drc off",
        "extract all",
        "ext2spice lvs",
        f"ext2spice -o {lvs_sp.name}",
        "ext2spice cthresh 0",
        "ext2spice rthresh infinite",
        f"ext2spice -o {pex_sp.name}",
        "quit -noprompt",
        "",
    ]))
    res = run_magic_bounded(tcl, work, timeout_s=timeout_s)
    (work / "_drc_ext.log").write_text(res.log)
    res.need(f"DRC+EXT {cell}")

    m_drc = re.search(r"DRC_TOTAL=(\d+)", res.log)
    drc_total = int(m_drc.group(1)) if m_drc else -1
    drc_rules = sorted(
        (l[len("DRC_RULE "):] for l in res.log.splitlines() if l.startswith("DRC_RULE ")),
        key=lambda l: -int(l.split("|")[0]),
    )

    ng = run_netgen_bounded(lvs_sp, cell, ref, lvs_log, work, timeout_s=timeout_s)
    lvs_txt = lvs_log.read_text() if lvs_log.exists() else (ng.stdout + ng.stderr)
    full_txt = ng.stdout + "\n" + lvs_txt
    lvs_match = "Circuits match uniquely" in full_txt
    lvs_prop_err = "Property errors were found" in full_txt
    lvs_disc = sorted(set(re.findall(r"disconnected node:\s*(\S+)", full_txt, re.I)))

    ports = exported_ports(lvs_sp, cell) if lvs_sp.exists() else []
    port_set_ok = set(ports) == set(expected_ports) and len(ports) == len(expected_ports)
    parasitics = summarize_pex_spice(pex_sp, ports) if pex_sp.exists() else {}

    box = Cell.read(mag).bbox()
    w_um = round(box[2] - box[0], 3)
    h_um = round(box[3] - box[1], 3)
    return {
        "cell": cell,
        "bbox_um": [round(x, 3) for x in box],
        "width_um": w_um,
        "height_um": h_um,
        "area_um2": round(w_um * h_um, 2),
        "aspect_ratio": round(w_um / max(h_um, 1e-6), 2),
        "drc_total": drc_total,
        "drc_rules": drc_rules,
        "lvs_match": lvs_match,
        "lvs_property_errors": lvs_prop_err,
        "lvs_disconnected": lvs_disc,
        "exported_ports": ports,
        "expected_port_count": len(expected_ports),
        "port_count_match": port_set_ok,
        "floating_poly": count_floating_poly(mag),
        "metal_shares": compute_metal_shares(mag),
        "parasitics": parasitics,
        "work_dir": str(work),
    }


def run_independent_review(mag: Path, ref: Path, review_dir: Path, timeout_s: int = 120) -> dict:
    """Invoke `verification/layout/review_cell.py --rc` into a fresh append-only review directory."""
    review_dir = review_dir.resolve()
    if review_dir.exists():
        shutil.rmtree(review_dir)
    proc = subprocess.run(
        [sys.executable, str(LAYOUT_VERIF / "review_cell.py"),
         str(mag.resolve()), str(ref.resolve()),
         "--output-dir", str(review_dir), "--rc"],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"review_cell.py failed for {mag.name}:\n{proc.stdout}\n{proc.stderr}")
    rep = json.loads((review_dir / "summary.json").read_text())
    rc_path = review_dir / "rc_summary.json"
    if rc_path.exists():
        rep["rc"] = json.loads(rc_path.read_text())
    return rep


def count_floating_poly(mag_path: Path) -> int:
    """Count connected components of SKY130A poly/gate/res-poly shapes lacking any polycont/xpolycontact."""
    cell = Cell.read(mag_path)
    poly_layers = (
        "poly", "polysilicon",
        "nmos", "nmoslvt", "mvnmos", "mvnnmos", "ntransistor", "nfetlvt",
        "pmos", "pmoslvt", "mvpmos", "ptransistor", "pfetlvt",
        "ppolyres", "xpolyres", "polyresistor",
    )
    cont_layers = ("polycont", "polycontact", "xpolycontact")
    polys = [r for lyr in poly_layers for r in cell.rects.get(lyr, [])]
    conts = [r for lyr in cont_layers for r in cell.rects.get(lyr, [])]
    if not polys:
        return 0

    eps = 0.002

    def touch(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
        return not (a[2] + eps < b[0] or b[2] + eps < a[0] or a[3] + eps < b[1] or b[3] + eps < a[1])

    bins: dict[tuple[int, int], list[int]] = {}
    for idx, r in enumerate(polys):
        for bx in range(int(math.floor(r[0] / 5.0)), int(math.floor(r[2] / 5.0)) + 1):
            for by in range(int(math.floor(r[1] / 5.0)), int(math.floor(r[3] / 5.0)) + 1):
                bins.setdefault((bx, by), []).append(idx)

    parent = list(range(len(polys)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for idxs in bins.values():
        n = len(idxs)
        for i in range(n):
            a = idxs[i]
            ra = polys[a]
            for j in range(i + 1, n):
                b = idxs[j]
                if touch(ra, polys[b]):
                    union(a, b)

    contacted_roots: set[int] = set()
    for cr in conts:
        for bx in range(int(math.floor(cr[0] / 5.0)), int(math.floor(cr[2] / 5.0)) + 1):
            for by in range(int(math.floor(cr[1] / 5.0)), int(math.floor(cr[3] / 5.0)) + 1):
                for idx in bins.get((bx, by), []):
                    if touch(cr, polys[idx]):
                        contacted_roots.add(find(idx))

    all_roots = {find(i) for i in range(len(polys))}
    return len(all_roots - contacted_roots)


def _rect_union_area(rects: list[tuple[float, float, float, float]]) -> float:
    """Exact 2D sweep-line union area of axis-aligned rectangles."""
    if not rects:
        return 0.0
    xs = sorted({x for r in rects for x in (r[0], r[2])})
    area = 0.0
    for x1, x2 in zip(xs, xs[1:]):
        if x2 <= x1:
            continue
        intervals = sorted((r[1], r[3]) for r in rects if r[0] <= x1 + 1e-9 and r[2] >= x2 - 1e-9)
        if not intervals:
            continue
        covered = 0.0
        cy1, cy2 = intervals[0]
        for y1, y2 in intervals[1:]:
            if y1 <= cy2:
                cy2 = max(cy2, y2)
            else:
                covered += cy2 - cy1
                cy1, cy2 = y1, y2
        covered += cy2 - cy1
        area += (x2 - x1) * covered
    return area


def compute_metal_shares(mag_path: Path) -> dict[str, Any]:
    """Compute exact union area (um^2) and percentage share across M1..M5."""
    cell = Cell.read(mag_path)
    areas: dict[str, float] = {}
    for k in range(1, 6):
        rs = cell.rects.get(f"metal{k}", []) + cell.rects.get(f"m{k}", [])
        areas[f"M{k}"] = round(_rect_union_area(rs), 3)
    tot = sum(areas.values())
    pct = {k: round((100.0 * v / tot) if tot > 0 else 0.0, 1) for k, v in areas.items()}
    return {"area_um2": areas, "total_metal_um2": round(tot, 3), "share_pct": pct}


def parse_all_pex_node_caps(pex_path: Path, substrate: str = "vss") -> dict[str, dict[str, float]]:
    """Return {node: {to_substrate_fF, coupling_sum_fF, total_node_fF}} for EVERY node in `_pex.spice`."""
    gnd_fF: dict[str, float] = defaultdict(float)
    couple_fF: dict[tuple[str, str], float] = defaultdict(float)
    nodes: set[str] = set()
    for line in pex_path.read_text().splitlines():
        if not line.startswith("C"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        n1, n2, raw_v = parts[1], parts[2], parts[3]
        v_fF = parse_cap_val_fF(raw_v)
        nodes.add(n1)
        nodes.add(n2)
        if n1 == substrate and n2 != substrate:
            gnd_fF[n2] += v_fF
        elif n2 == substrate and n1 != substrate:
            gnd_fF[n1] += v_fF
        elif n1 != n2:
            couple_fF[tuple(sorted((n1, n2)))] += v_fF

    out: dict[str, dict[str, float]] = {}
    for n in sorted(nodes):
        if n == substrate:
            continue
        cg = gnd_fF.get(n, 0.0)
        cc = sum(v for (a, b), v in couple_fF.items() if n in (a, b))
        out[n] = {
            "to_substrate_fF": round(cg, 3),
            "coupling_sum_fF": round(cc, 3),
            "total_node_fF": round(cg + cc, 3),
        }
    return out


def render_png_plot_mag(mag: Path, out_png: Path) -> None:
    """Render white-background PNG using `verification/layout/plot_mag.py` palette with outside legend."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import plot_mag as pm  # noqa: E402

    rects, labels = pm.parse(mag)
    xs = [r[1] for r in rects] + [r[3] for r in rects]
    ys = [r[2] for r in rects] + [r[4] for r in rects]
    x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
    w, h = x2 - x1, y2 - y1

    fig_w = 16.0
    fig_h = max(7.0, min(14.5, fig_w * (h + 5.0) / max(w + 5.0, 1.0)))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    present: set[str] = set()
    for layer, rx1, ry1, rx2, ry2 in rects:
        if layer not in pm.COLORS:
            continue
        present.add(layer)
        is_mim = layer in ("mimcap", "mimcap2")
        alpha = 0.28 if is_mim else (0.65 if layer in ("m1", "m2", "m3", "m4", "m5") else 0.88)
        ec = "#d97706" if layer == "mimcap" else ("#059669" if layer == "mimcap2" else "none")
        ax.add_patch(
            Rectangle(
                (rx1, ry1), rx2 - rx1, ry2 - ry1,
                facecolor=pm.COLORS[layer],
                edgecolor=ec,
                linewidth=0.8 if is_mim else 0.0,
                hatch="//" if is_mim else None,
                alpha=alpha,
                zorder=pm.Z[layer],
            )
        )

    pad_x = max(2.2, 0.08 * w)
    pad_y = max(2.2, 0.08 * h)
    placed: list[tuple[str, float, float, float, float]] = []
    min_dy = max(1.1, 0.042 * h)
    min_dx = max(2.0, 0.075 * w)
    for nm, px, py in sorted(labels, key=lambda t: (round(t[2] / max(min_dy, 1.0)), t[1])):
        tx, ty = px, py
        on_west = abs(px - x1) < 1.2
        on_east = abs(px - x2) < 1.2
        on_south = abs(py - y1) < 1.2
        on_north = abs(py - y2) < 1.2
        if on_west:
            tx = px - 0.05 * w
        elif on_east:
            tx = px + 0.05 * w
        if on_south:
            ty = py - 0.04 * h
        elif on_north:
            ty = py + 0.04 * h
        for _ in range(20):
            conflict = False
            for _, _, _, otx, oty in placed:
                if abs(tx - otx) < min_dx and abs(ty - oty) < min_dy:
                    conflict = True
                    if on_west or on_east:
                        ty = oty + min_dy
                    else:
                        # Stagger South/North row labels cleanly in Y (below/above) so close pins never collide!
                        ty = oty - min_dy * 0.95 if on_south else oty + min_dy * 0.95
                    break
            if not conflict:
                break
        placed.append((nm, px, py, tx, ty))

    for nm, px, py, tx, ty in placed:
        ax.plot([px], [py], marker="o", ms=3.2, color="#111827", zorder=99)
        if abs(tx - px) > 0.25 or abs(ty - py) > 0.25:
            ax.plot([px, tx], [py, ty], color="#2563eb", lw=0.65, alpha=0.80, zorder=98)
        ha = "right" if abs(px - x1) < 1.2 else ("left" if abs(px - x2) < 1.2 else "center")
        ax.text(
            tx, ty, nm, fontsize=7.5, fontweight="bold", color="#111827", ha=ha, va="center", zorder=100,
            bbox=dict(boxstyle="round,pad=0.14", facecolor="white", edgecolor="#2563eb", alpha=0.94, lw=0.65),
        )

    ax.set_xlim(x1 - pad_x * 1.5, x2 + pad_x * 1.5)
    ax.set_ylim(y1 - pad_y * 1.4, y2 + pad_y * 1.4)
    ax.set_aspect("equal")
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    ax.set_title(f"{mag.name}  ({w:.2f} x {h:.2f} um = {w*h:,.1f} um^2)")
    ax.grid(True, lw=0.25, alpha=0.35)

    legend_keys = [k for k in pm.COLORS if k in present]
    handles = [
        Rectangle(
            (0, 0), 1, 1,
            facecolor=pm.COLORS[k],
            edgecolor="#d97706" if k == "mimcap" else ("#059669" if k == "mimcap2" else "none"),
            hatch="//" if k in ("mimcap", "mimcap2") else None,
        )
        for k in legend_keys
    ]
    ax.legend(handles, legend_keys, fontsize=7.0, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0.0)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=160, facecolor="white")
    plt.close(fig)
