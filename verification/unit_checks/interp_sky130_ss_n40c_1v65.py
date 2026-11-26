#!/usr/bin/env python3
"""Generate a physically interpolated SKY130A `ss_n40C_1v65` Liberty library
from the official `1.44 V / 1.60 V / 1.76 V` (`ss`, `-40 C`) libraries, validate
it against real ngspice SKY130A `ss -40 C` transistor simulations, and evaluate
real OpenROAD STA across `v3.2` and `v3.3` digital netlists.
"""
from __future__ import annotations

import json
import math
import pathlib
import re
import subprocess
import sys
import time
import tomllib

import numpy as np

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "results/digital/interp_ss_n40c_1v65_20261125"
LIB_DIR = pathlib.Path("/home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib")
SPICE_LIB = pathlib.Path("/home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice")
OPENROAD = "/opt/eda_pnr/envs/pnr/bin/openroad"
NGSPICE = "/opt/ngspice47/bin/ngspice"

TABLE_RE = re.compile(
    r'\b(cell_rise|cell_fall|rise_transition|fall_transition|rise_constraint|fall_constraint)\s*\("([^"]+)"\)\s*\{([^{}]*?)\}',
    re.S,
)
IDX1_RE = re.compile(r'index_1\s*\(\s*"([^"]+)"\s*\)')
IDX2_RE = re.compile(r'index_2\s*\(\s*"([^"]+)"\s*\)')
VALS_RE = re.compile(r'values\s*\((.*?)\)\s*;', re.S)


def parse_float_list(s: str) -> np.ndarray:
    return np.fromstring(s.replace(",", " "), sep=" ", dtype=np.float64)


def parse_table(body: str) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray, tuple[int, int]]:
    m1 = IDX1_RE.search(body)
    m2 = IDX2_RE.search(body)
    mv = VALS_RE.search(body)
    if not mv:
        raise ValueError("Missing values in timing table")
    idx1 = parse_float_list(m1.group(1)) if m1 else None
    idx2 = parse_float_list(m2.group(1)) if m2 else None
    rows = re.findall(r'"([^"]+)"', mv.group(1))
    arr = np.vstack([parse_float_list(r) for r in rows])
    return idx1, idx2, arr, mv.span(1)


def interp_1d_extrap(x: np.ndarray, y: np.ndarray, xq: np.ndarray) -> np.ndarray:
    """Piecewise linear 1D interpolation with linear edge extrapolation."""
    out = np.empty_like(xq, dtype=np.float64)
    n = len(x)
    if n == 1:
        out[:] = y[0]
        return out
    for i, xv in enumerate(xq):
        if xv <= x[0]:
            j = 0
        elif xv >= x[-1]:
            j = n - 2
        else:
            j = int(np.searchsorted(x, xv) - 1)
        t = (xv - x[j]) / (x[j + 1] - x[j])
        out[i] = y[j] + t * (y[j + 1] - y[j])
    return out


def regrid_2d(
    x: np.ndarray | None, y: np.ndarray | None, z: np.ndarray, xq: np.ndarray | None, yq: np.ndarray | None
) -> np.ndarray:
    """2D bilinear regridding onto (xq, yq) with smooth linear edge extrapolation."""
    if x is None or xq is None:
        return z.copy()
    if y is None or yq is None:
        return interp_1d_extrap(x, z.ravel(), xq).reshape(1, -1)
    # First interpolate along y (columns) for each source row
    tmp = np.empty((len(x), len(yq)), dtype=np.float64)
    for r in range(len(x)):
        tmp[r, :] = interp_1d_extrap(y, z[r, :], yq)
    # Then interpolate along x (rows) for each target column
    out = np.empty((len(xq), len(yq)), dtype=np.float64)
    for c in range(len(yq)):
        out[:, c] = interp_1d_extrap(x, tmp[:, c], xq)
    return out


def lagrange_weights(xs: tuple[float, float, float], xq: float) -> tuple[float, float, float]:
    x0, x1, x2 = xs
    w0 = (xq - x1) * (xq - x2) / ((x0 - x1) * (x0 - x2))
    w1 = (xq - x0) * (xq - x2) / ((x1 - x0) * (x1 - x2))
    w2 = (xq - x0) * (xq - x1) / ((x2 - x0) * (x2 - x1))
    return w0, w1, w2


def format_values(arr: np.ndarray, indent: str = "                        ") -> str:
    rows = []
    for r in range(arr.shape[0]):
        s = ", ".join(f"{v:.10f}" for v in arr[r])
        rows.append(f'"{s}"')
    return (", \\\n" + indent).join(rows)


def generate_interpolated_lib(v_target: float, out_lib: pathlib.Path) -> dict:
    t0 = time.time()
    t44 = (LIB_DIR / "sky130_fd_sc_hd__ss_n40C_1v44.lib").read_text()
    t60 = (LIB_DIR / "sky130_fd_sc_hd__ss_n40C_1v60.lib").read_text()
    t76 = (LIB_DIR / "sky130_fd_sc_hd__ss_n40C_1v76.lib").read_text()

    m44 = list(TABLE_RE.finditer(t44))
    m60 = list(TABLE_RE.finditer(t60))
    m76 = list(TABLE_RE.finditer(t76))
    assert len(m44) == len(m60) == len(m76), f"Table count mismatch: {len(m44)}, {len(m60)}, {len(m76)}"

    w0, w1, w2 = lagrange_weights((1.44, 1.60, 1.76), v_target)
    parts: list[str] = []
    cursor = 0
    ratios: list[float] = []

    for a, b, c in zip(m44, m60, m76):
        assert a.group(1) == b.group(1) == c.group(1), "Table type alignment error"
        ttype = b.group(1)
        x44, y44, z44, _ = parse_table(a.group(3))
        x60, y60, z60, val_span = parse_table(b.group(3))
        x76, y76, z76, _ = parse_table(c.group(3))

        z44_g = regrid_2d(x44, y44, z44, x60, y60)
        z76_g = regrid_2d(x76, y76, z76, x60, y60)

        if ttype in ("cell_rise", "cell_fall", "rise_transition", "fall_transition"):
            # Quadratic in log-delay space where strictly positive (matches alpha-power curvature)
            pos = (z44_g > 1e-9) & (z60 > 1e-9) & (z76_g > 1e-9)
            z_out = w0 * z44_g + w1 * z60 + w2 * z76_g
            if np.any(pos):
                log_interp = (
                    w0 * np.log(np.where(pos, z44_g, 1.0))
                    + w1 * np.log(np.where(pos, z60, 1.0))
                    + w2 * np.log(np.where(pos, z76_g, 1.0))
                )
                z_out = np.where(pos, np.exp(log_interp), z_out)
            if ttype in ("cell_rise", "cell_fall") and z60.shape == (7, 7):
                # Record mid-table speedup ratio
                ratios.append(float(z_out[2, 3] / z60[2, 3]))
        else:
            # Constraints (setup/hold can be negative): direct quadratic Lagrange
            z_out = w0 * z44_g + w1 * z60 + w2 * z76_g

        body_start = b.start(3)
        abs_vstart = body_start + val_span[0]
        abs_vend = body_start + val_span[1]
        parts.append(t60[cursor:abs_vstart])
        parts.append(format_values(z_out))
        cursor = abs_vend

    parts.append(t60[cursor:])
    out_txt = "".join(parts)

    tag = f"ss_n40C_{int(round(v_target * 100)):d}".replace("ss_n40C_1", "ss_n40C_1v")
    out_txt = out_txt.replace("ss_n40C_1v60", tag)
    out_txt = re.sub(r"voltage\s*:\s*1\.6000000000\s*;", f"voltage : {v_target:.10f};", out_txt)
    out_txt = re.sub(r"nom_voltage\s*:\s*1\.6000000000\s*;", f"nom_voltage : {v_target:.10f};", out_txt)
    out_lib.write_text(out_txt)
    return {
        "out_lib": str(out_lib),
        "tables_interpolated": len(m60),
        "weights_144_160_176": [round(w0, 5), round(w1, 5), round(w2, 5)],
        "median_cell_delay_ratio_vs_1v60": round(float(np.median(ratios)), 4),
        "p10_p90_ratio_vs_1v60": [round(float(np.percentile(ratios, 10)), 4), round(float(np.percentile(ratios, 90)), 4)],
        "elapsed_s": round(time.time() - t0, 2),
    }


def extract_subckts(cells: list[str], dst: pathlib.Path) -> None:
    lines = SPICE_LIB.read_text().splitlines()
    out: list[str] = []
    keep = False
    target = set(cells)
    for ln in lines:
        if ln.lower().startswith(".subckt "):
            parts = ln.split()
            keep = len(parts) >= 2 and parts[1] in target
        if keep:
            out.append(ln)
        if keep and ln.lower().startswith(".ends"):
            keep = False
            out.append("")
    dst.write_text("\n".join(out) + "\n")


def lookup_lib_delay(lib_path: pathlib.Path, cell: str, pin: str, related: str, table: str, slew: float, cap: float) -> float:
    txt = lib_path.read_text()
    c_idx = txt.find(f'cell ("{cell}")')
    c_end = txt.find('\n  cell ("', c_idx + 10)
    c_blk = txt[c_idx:c_end if c_end > 0 else len(txt)]
    p_idx = c_blk.find(f'pin ("{pin}")')
    p_blk = c_blk[p_idx:]
    # Find timing block with related_pin
    for m in re.finditer(r'timing\s*\(\s*\)\s*\{', p_blk):
        start = m.start()
        # Simple brace match
        depth, i = 0, start
        while i < len(p_blk):
            if p_blk[i] == "{":
                depth += 1
            elif p_blk[i] == "}":
                depth -= 1
                if depth == 0:
                    blk = p_blk[start:i + 1]
                    break
            i += 1
        if f'related_pin : "{related}"' in blk and f"{table} (" in blk:
            tm = TABLE_RE.search(blk)
            for tm in TABLE_RE.finditer(blk):
                if tm.group(1) == table:
                    x, y, z, _ = parse_table(tm.group(3))
                    val = regrid_2d(x, y, z, np.array([slew]), np.array([cap]))
                    return float(val[0, 0])
    raise ValueError(f"Table not found: {cell} {pin}<-{related} {table}")


def run_spice_validation(interp_lib: pathlib.Path) -> dict:
    pdk = tomllib.loads((REPO / "config/pdk.toml").read_text())["pdk"]
    model_lib = pathlib.Path(pdk["resolved_path"]) / pdk["model_library"]
    cells = [
        "sky130_fd_sc_hd__inv_2",
        "sky130_fd_sc_hd__nand2_4",
        "sky130_fd_sc_hd__mux2_4",
        "sky130_fd_sc_hd__a21oi_4",
    ]
    sub_inc = OUT_DIR / "stdcells_4.spice"
    extract_subckts(cells, sub_inc)

    slew_20_80 = 0.20  # ns (20%-80% SKY130 Liberty definition)
    tr_full = slew_20_80 / 0.60  # 0.3333 ns 0->100% linear ramp
    cload_pf = 0.040

    tb = OUT_DIR / "tb_validate_1v65.cir"
    # Note: inv_2(A VGND VNB VPB VPWR Y), nand2_4(A B ... Y), mux2_4(A0 A1 S ... X), a21oi_4(A1 A2 B1 ... Y)
    tb.write_text(f"""* SKY130A ss -40C voltage scaling validation (1.60V / 1.65V / 1.76V)
.option temp=-40
.lib {model_lib} ss
.include {sub_inc}

.param vdd=1.60
Vdd vdd 0 DC {{vdd}}
Vss vss 0 DC 0
* Linear 0->vdd and vdd->0 ramps with exact 20%-80% slew = 0.20 ns (full ramp = 0.33333 ns)
Vin in 0 PWL(0 0 1n 0 {{1n+{tr_full:.6f}n}} {{vdd}} 6n {{vdd}} {{6n+{tr_full:.6f}n}} 0 12n 0)

Xinv  in            vss vss vdd vdd y_inv  sky130_fd_sc_hd__inv_2
Xn2   in  vdd       vss vss vdd vdd y_n2   sky130_fd_sc_hd__nand2_4
Xmux  vss vdd in    vss vss vdd vdd y_mux  sky130_fd_sc_hd__mux2_4
Xa21  in  vdd vss   vss vss vdd vdd y_a21  sky130_fd_sc_hd__a21oi_4

Cinv y_inv 0 {cload_pf}p
Cn2  y_n2  0 {cload_pf}p
Cmux y_mux 0 {cload_pf}p
Ca21 y_a21 0 {cload_pf}p

.control
set num_threads=1
foreach vv 1.60 1.65 1.76
  alterparam vdd = $vv
  reset
  tran 2p 11n
  let v50 = 0.5 * $vv
  meas tran inv_hl  trig v(in) val=v50 rise=1 targ v(y_inv) val=v50 fall=1
  meas tran inv_lh  trig v(in) val=v50 fall=1 targ v(y_inv) val=v50 rise=1
  meas tran n2_hl   trig v(in) val=v50 rise=1 targ v(y_n2)  val=v50 fall=1
  meas tran n2_lh   trig v(in) val=v50 fall=1 targ v(y_n2)  val=v50 rise=1
  meas tran mux_lh  trig v(in) val=v50 rise=1 targ v(y_mux) val=v50 rise=1
  meas tran mux_hl  trig v(in) val=v50 fall=1 targ v(y_mux) val=v50 fall=1
  meas tran a21_hl  trig v(in) val=v50 rise=1 targ v(y_a21) val=v50 fall=1
  meas tran a21_lh  trig v(in) val=v50 fall=1 targ v(y_a21) val=v50 rise=1
  echo "MEAS_V=$vv inv_hl=$&inv_hl inv_lh=$&inv_lh n2_hl=$&n2_hl n2_lh=$&n2_lh mux_lh=$&mux_lh mux_hl=$&mux_hl a21_hl=$&a21_hl a21_lh=$&a21_lh"
end
quit
.endc
.end
""")
    r = subprocess.run([NGSPICE, "-b", str(tb)], capture_output=True, text=True, check=True)
    spice_res: dict[str, dict[str, float]] = {}
    for ln in r.stdout.splitlines():
        if ln.startswith("MEAS_V="):
            toks = dict(kv.split("=") for kv in ln.split())
            vkey = toks.pop("MEAS_V")
            spice_res[vkey] = {k: float(v) * 1e9 for k, v in toks.items()}

    arcs = [
        ("inv_hl", "sky130_fd_sc_hd__inv_2", "Y", "A", "cell_fall"),
        ("inv_lh", "sky130_fd_sc_hd__inv_2", "Y", "A", "cell_rise"),
        ("n2_hl",  "sky130_fd_sc_hd__nand2_4", "Y", "A", "cell_fall"),
        ("n2_lh",  "sky130_fd_sc_hd__nand2_4", "Y", "A", "cell_rise"),
        ("mux_lh", "sky130_fd_sc_hd__mux2_4", "X", "S", "cell_rise"),
        ("mux_hl", "sky130_fd_sc_hd__mux2_4", "X", "S", "cell_fall"),
        ("a21_hl", "sky130_fd_sc_hd__a21oi_4", "Y", "A1", "cell_fall"),
        ("a21_lh", "sky130_fd_sc_hd__a21oi_4", "Y", "A1", "cell_rise"),
    ]
    lib60 = LIB_DIR / "sky130_fd_sc_hd__ss_n40C_1v60.lib"
    lib76 = LIB_DIR / "sky130_fd_sc_hd__ss_n40C_1v76.lib"

    rows = []
    for k, cell, pin, rel, tbl in arcs:
        sp60 = spice_res["1.60"][k]
        sp65 = spice_res["1.65"][k]
        sp76 = spice_res["1.76"][k]
        lb60 = lookup_lib_delay(lib60, cell, pin, rel, tbl, slew_20_80, cload_pf)
        lb65 = lookup_lib_delay(interp_lib, cell, pin, rel, tbl, slew_20_80, cload_pf)
        lb76 = lookup_lib_delay(lib76, cell, pin, rel, tbl, slew_20_80, cload_pf)
        sp_ratio = sp65 / sp60
        lb_ratio = lb65 / lb60
        ratio_err_pct = (lb_ratio / sp_ratio - 1.0) * 100.0
        abs_err_pct = (lb65 / sp65 - 1.0) * 100.0
        rows.append({
            "arc": k,
            "spice_ns": {"1.60": round(sp60, 4), "1.65": round(sp65, 4), "1.76": round(sp76, 4)},
            "lib_ns": {"1.60": round(lb60, 4), "1.65": round(lb65, 4), "1.76": round(lb76, 4)},
            "spice_165_over_160": round(sp_ratio, 4),
            "lib_165_over_160": round(lb_ratio, 4),
            "ratio_err_pct": round(ratio_err_pct, 2),
            "abs_err_pct": round(abs_err_pct, 2),
        })
    return {"slew_20_80_ns": slew_20_80, "cload_pf": cload_pf, "arcs": rows}


def run_sta_comparison(interp_lib: pathlib.Path, label: str, work: pathlib.Path, spef_name: str, sdc_name: str) -> dict:
    tcl = OUT_DIR / f"sta_{label}.tcl"
    tcl.write_text(f"""
define_corners ss100_1v60 ssn40_1v60 ssn40_1v65 ssn40_1v76 tt_1v80
read_lef /home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef
read_lef /home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef
read_liberty -corner ss100_1v60 {LIB_DIR}/sky130_fd_sc_hd__ss_100C_1v60.lib
read_liberty -corner ssn40_1v60 {LIB_DIR}/sky130_fd_sc_hd__ss_n40C_1v60.lib
read_liberty -corner ssn40_1v65 {interp_lib}
read_liberty -corner ssn40_1v76 {LIB_DIR}/sky130_fd_sc_hd__ss_n40C_1v76.lib
read_liberty -corner tt_1v80    {LIB_DIR}/sky130_fd_sc_hd__tt_025C_1v80.lib
read_def {work}/serdes_digital_top_v3.def
read_sdc {work}/{sdc_name}
foreach c {{ss100_1v60 ssn40_1v60 ssn40_1v65 ssn40_1v76 tt_1v80}} {{
    read_spef -corner $c {work}/{spef_name}
}}
set_propagated_clock [all_clocks]
set_timing_derate -early 1.00
set_timing_derate -late 1.00
foreach mode {{NO_OCV OCV_5PCT}} {{
    if {{$mode eq "OCV_5PCT"}} {{
        set_timing_derate -early 0.95
        set_timing_derate -late 1.05
    }}
    foreach c {{ss100_1v60 ssn40_1v60 ssn40_1v65 ssn40_1v76 tt_1v80}} {{
        set wns [worst_slack -corner $c -max]
        set tns [total_negative_slack -corner $c -max]
        set hld [worst_slack -corner $c -min]
        puts [format "STA %s %s WNS=%.4f TNS=%.2f HOLD=%.4f" $mode $c $wns $tns $hld]
    }}
}}
""")
    r = subprocess.run([OPENROAD, "-threads", "1", "-no_init", "-exit", str(tcl)], capture_output=True, text=True, check=True)
    res: dict[str, dict[str, dict[str, float]]] = {}
    for ln in r.stdout.splitlines():
        if ln.startswith("STA "):
            _, mode, corner, w, t, h = ln.split()
            res.setdefault(mode, {})[corner] = {
                "wns_ns": float(w.split("=")[1]),
                "tns_ns": float(t.split("=")[1]),
                "hold_ns": float(h.split("=")[1]),
            }
    return res


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    interp_lib = OUT_DIR / "sky130_fd_sc_hd__ss_n40C_1v65_interp.lib"
    print("[1/3] Interpolating ss_n40C_1v65.lib from 1.44V / 1.60V / 1.76V...")
    lib_info = generate_interpolated_lib(1.65, interp_lib)
    print(" ", lib_info)

    print("[2/3] Validating 1.65V -40C against real ngspice SKY130A ss corner...")
    spice_info = run_spice_validation(interp_lib)
    for row in spice_info["arcs"]:
        print(
            f"  {row['arc']:6s} | SPICE 1.60/1.65/1.76={row['spice_ns']['1.60']:.4f}/{row['spice_ns']['1.65']:.4f}/{row['spice_ns']['1.76']:.4f} ns"
            f" | LIB={row['lib_ns']['1.60']:.4f}/{row['lib_ns']['1.65']:.4f}/{row['lib_ns']['1.76']:.4f} ns"
            f" | ratio_err={row['ratio_err_pct']:+.2f}% | abs_err={row['abs_err_pct']:+.2f}%"
        )

    print("[3/3] Running OpenROAD STA on v3.2 (signed-off) and v3.3 (current)...")
    sta_v32 = run_sta_comparison(
        interp_lib,
        "v32",
        REPO / "results/digital/pnr_v3p2_signoff_met/serdes_digital_top_v3",
        "serdes_digital_top_v3_max.spef",
        "serdes_digital_top_v3_postroute.sdc",
    )
    sta_v33 = run_sta_comparison(
        interp_lib,
        "v33",
        REPO / "results/digital/pnr_v3p3_20261124/serdes_digital_top_v3",
        "serdes_digital_top_v3_eco_max.spef",
        "serdes_digital_top_v3_eco.sdc",
    )
    for name, sta in [("v3.2 (signed-off)", sta_v32), ("v3.3 (current)", sta_v33)]:
        print(f"=== {name} ===")
        for mode in ("NO_OCV", "OCV_5PCT"):
            print(f"  [{mode}]")
            for c, m in sta[mode].items():
                print(f"    {c:12s} WNS={m['wns_ns']:+.4f} ns  TNS={m['tns_ns']:+.2f} ns  HOLD={m['hold_ns']:+.4f} ns")

    summary = {"interp_lib": lib_info, "spice_validation": spice_info, "sta_v32": sta_v32, "sta_v33": sta_v33}
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"Saved {OUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
