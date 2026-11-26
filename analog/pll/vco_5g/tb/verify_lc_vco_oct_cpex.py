#!/usr/bin/env python3
"""Post-layout Magic CPEX 4-Corner Tuning, Startup, Quadrature I/Q & Phase-Noise Verification
for the 5.0 GHz Octagonal LC-VCO + Quadrature /2 Macro (`vco5g_lc_div2_oct_pdk`).

Combines:
  - Magic CPEX extracted active macro: `vco5g_lc_active_div2_oct_pdk_pex.spice` (LVS=MATCH, DRC=0)
  - Extracted 45-degree octagonal inductor model: `vco5g_ind_oct_2n5_pdk`
    (Neumann L_diff=2.408 nH, Q_5G=7.26, C_sub=410.49 fF, Magic+KLayout DRC=0)

Rules enforced:
  - Strictly workers=1, num_threads=1.
  - Strict sparse solver (NEVER klu, NEVER cshunt — sky130_fd_pr__cap_var_lvt is in the deck!).
  - Proper `.ic` on `vbias_f` & `vbias_lc` (or DCOP) so the 1 pF RC tail filter does not starve
    startup during short `uic` windows.
  - Evaluates ALL 4 extreme PVT/RC corners:
      TT 1.80V 27C tt | SS 1.65V +85C hh | SS 1.65V -40C hh | FF 1.95V -40C ll
  - Also computes tank-Q + Leeson/Hajimiri-Lee phase noise L(1 MHz) and K_vco across V_ctrl.
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from serdes_flow import spice  # noqa: E402

PDK_LIB = "/home/host/.volare/sky130A/libs.tech/ngspice/sky130.lib.spice"
PRIM_SPICE = REPO / "analog/common/devices/spice/sky130_primitives.spice"
PFET_LVT_SPICE = REPO / "analog/common/devices/spice/sky130_pfet_lvt.spice"
OCT_SPICE = REPO / "analog/pll/vco_5g/spice/lc_5g_div2_oct_pdk.spice"
PEX_SPICE = REPO / "analog/pll/vco_5g/layout/variants/lc_vco_5g_oct_pdk/vco5g_lc_active_div2_oct_pdk_pex.spice"
OUT_ROOT = REPO / "results/analog/pll/vco_5g_oct_cpex_20261125"

CORNERS = {
    "tt_v1800_t27_tt": {"lib": "tt", "vdd": 1.80, "temp": 27, "rm_scale": 1.00, "c_scale": 1.00},
    "ss_v1650_t85_hh": {"lib": "ss_hh", "vdd": 1.65, "temp": 85, "rm_scale": 1.22, "c_scale": 1.12},
    "ss_v1650_t-40_hh": {"lib": "ss_hh", "vdd": 1.65, "temp": -40, "rm_scale": 1.22, "c_scale": 1.12},
    "ff_v1950_t-40_ll": {"lib": "ff_ll", "vdd": 1.95, "temp": -40, "rm_scale": 0.75, "c_scale": 0.88},
}


def rising_crossings(t: np.ndarray, y: np.ndarray, thr: float = 0.0) -> np.ndarray:
    s = y - thr
    idx = np.where((s[:-1] <= 0.0) & (s[1:] > 0.0))[0]
    if len(idx) == 0:
        return np.array([], dtype=float)
    dy = s[idx + 1] - s[idx]
    frac = np.where(dy != 0.0, -s[idx] / dy, 0.5)
    return t[idx] + frac * (t[idx + 1] - t[idx])


def find_tail_node(pex_path: Path) -> str | None:
    """Locate the internal `tail` node name in the extracted Magic CPEX netlist (drain of 12-finger Xtail)."""
    txt = pex_path.read_text()
    # Look for nfet_01v8 w=5e+06u / l=5e+05u (Xtail fingers: w=5um l=0.5um, 12 parallel devices)
    counts: dict[str, int] = {}
    for m in re.finditer(r"^X\S+\s+(\S+)\s+\S+\s+vss\s+vss\s+sky130_fd_pr__nfet_01v8\b.*l=0\.5", txt, re.M):
        nd = m.group(1)
        if nd not in ("vdd", "vss", "vp", "vn"):
            counts[nd] = counts.get(nd, 0) + 1
    if not counts:
        return None
    best = max(counts.items(), key=lambda kv: kv[1])
    return best[0] if best[1] >= 8 else None


def build_cpex_deck(corner_key: str, points: list[tuple[str, int, float]], tail_node: str | None) -> str:
    c = CORNERS[corner_key]
    vdd = c["vdd"]
    save_tail = f" v(xact.{tail_node})" if tail_node else ""
    is_ff = corner_key.startswith("ff_")
    opts = (
        ".options reltol=1e-3 abstol=100p vntol=100u gmin=1e-11 method=trap trtol=5"
        if is_ff else
        ".options reltol=3e-4 abstol=10p vntol=10u gmin=1e-11 method=gear"
    )
    tran_cmd = "tran 1p 18n 10n 1p" if is_ff else "tran 2p 20n 11n 2p"
    lines = [
        f"* Octagonal 5.0 GHz LC-VCO + /2 Post-Layout Magic CPEX Check @ {corner_key}",
        f'.lib "{PDK_LIB}" {c["lib"]}',
        f'.include "{PRIM_SPICE}"',
        f'.include "{PFET_LVT_SPICE}"',
        f'.include "{OCT_SPICE}"',
        f'.include "{PEX_SPICE}"',
        f"Vdd vdd 0 {vdd:.6f}",
        "Vctrl vctrl 0 0.850000",
        "Vb0 b0 0 0.0",
        "Vb1 b1 0 0.0",
        "Vb2 b2 0 0.0",
        "Vb3 b3 0 0.0",
        f"Xind vp vn ct 0 vco5g_ind_oct_2n5_pdk rm_scale={c['rm_scale']} c_scale={c['c_scale']}",
        "Xact vp vn ip in qp qn vctrl b0 b1 b2 b3 vdd 0 vco5g_lc_active_div2_oct_pdk",
        "Cip ip 0 30f",
        "Cin in 0 30f",
        "Cqp qp 0 30f",
        "Cqn qn 0 30f",
        "Ikick vp vn PWL(0 0 0.2n 0 0.21n 80u 0.26n 80u 0.27n 0)",
        "Ikick_d ip in PWL(0 0 6.5n 0 6.51n 60u 6.56n 60u 6.57n 0)",
        f".temp {c['temp']}",
        # Strict sparse solver (NO klu, NO cshunt because cap_var_lvt is present!)
        # Run WITHOUT `uic` so DCOP initializes the 1 pF RC tail bias filter (`vbias_f`) cleanly!
        opts,
        f".save v(vp) v(vn) v(ip) v(in) v(qp) v(qn){save_tail} i(Vdd)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
    ]
    for tag, code, vctrl in points:
        b0 = vdd if (code & 1) else 0.0
        b1 = vdd if (code & 2) else 0.0
        b2 = vdd if (code & 4) else 0.0
        b3 = vdd if (code & 8) else 0.0
        lines.extend([
            f"alter Vctrl dc={vctrl:.6f}",
            f"alter Vb0 dc={b0:.6f}",
            f"alter Vb1 dc={b1:.6f}",
            f"alter Vb2 dc={b2:.6f}",
            f"alter Vb3 dc={b3:.6f}",
            tran_cmd,
            f"write {tag}.raw v(vp) v(vn) v(ip) v(in) v(qp) v(qn){save_tail} i(Vdd)",
            "destroy all",
        ])
    lines.extend(["quit", ".endc", ".end", ""])
    return "\n".join(lines)


def analyze_raw(raw_path: Path, tail_node: str | None, temp_c: float, t_win_start: float = 13e-9) -> dict:
    w = spice.Waves(raw_path)
    t = w.t
    mask = t >= t_win_start
    tm = t[mask]
    vp = w["v(vp)"][mask]
    vn = w["v(vn)"][mask]
    vdiff = vp - vn
    vi = (w["v(ip)"] - w["v(in)"])[mask]
    vq = (w["v(qp)"] - w["v(qn)"])[mask]
    itot_ma = float(-np.mean(w["i(vdd)"][mask]) * 1e3)
    vtail_pp_mv = None
    if tail_node:
        k_t = f"v(xact.{tail_node.lower()})"
        if k_t in w:
            vt = w[k_t][mask]
            vtail_pp_mv = round(float((np.max(vt) - np.min(vt)) * 1e3), 2)

    vpp_tank = float(np.max(vdiff) - np.min(vdiff))
    vpp_i = float(np.max(vi) - np.min(vi))
    vpp_q = float(np.max(vq) - np.min(vq))

    tx_vco = rising_crossings(tm, vdiff, 0.0)
    f_vco_ghz = float(1.0 / np.median(np.diff(tx_vco)) / 1e9) if len(tx_vco) >= 4 and vpp_tank > 0.2 else 0.0
    tx_i = rising_crossings(tm, vi, 0.0)
    tx_q = rising_crossings(tm, vq, 0.0)
    if len(tx_i) >= 4 and len(tx_q) >= 4 and vpp_i > 0.15 and vpp_q > 0.15 and f_vco_ghz > 1.0:
        f_i_ghz = float(1.0 / np.median(np.diff(tx_i)) / 1e9)
        f_q_ghz = float(1.0 / np.median(np.diff(tx_q)) / 1e9)
        errs = []
        for k in range(len(tx_i) - 1):
            t0, t1 = tx_i[k], tx_i[k + 1]
            dt = t1 - t0
            qs = tx_q[(tx_q >= t0) & (tx_q < t1)]
            if len(qs) == 1:
                phi = (qs[0] - t0) / dt
                errs.append(min(abs(phi - 0.25), abs(phi - 0.75)) * dt * 1e12)
        q_err_mean = float(np.mean(errs)) if errs else float("nan")
        div_locked = abs(f_i_ghz / (0.5 * f_vco_ghz) - 1.0) < 0.01 and abs(f_q_ghz / (0.5 * f_vco_ghz) - 1.0) < 0.01
    else:
        f_i_ghz = f_q_ghz = 0.0
        q_err_mean = float("nan")
        div_locked = False

    # Analytical Leeson-Hajimiri phase noise at 1 MHz offset from real post-layout tank amplitude & Q_5G=7.26
    # L(df) = 10*log10( (2*F*k*T / P_sig) * (f0 / (2*Q*df))^2 ), F ~ 2.5 (complementary high-Z tail), R_p ~ 611 Ohm
    pn_1m_dbc = None
    if f_vco_ghz > 1.0 and vpp_tank > 0.2:
        kT = 1.380649e-23 * (temp_c + 273.15)
        v_amp = 0.5 * vpp_tank
        rp = 611.0
        q_tank = 7.15
        p_sig = (v_amp ** 2) / (2.0 * rp)
        F_excess = 2.5
        df = 1.0e6
        l_lin = (2.0 * F_excess * kT / p_sig) * ((f_vco_ghz * 1e9) / (2.0 * q_tank * df)) ** 2
        pn_1m_dbc = round(10.0 * math.log10(l_lin), 2)

    return {
        "f_vco_ghz": round(f_vco_ghz, 5),
        "vpp_tank_v": round(vpp_tank, 4),
        "vtail_pp_mv": vtail_pp_mv,
        "itot_ma": round(itot_ma, 3),
        "div_locked": div_locked,
        "f_i_ghz": round(f_i_ghz, 5),
        "vpp_i_v": round(vpp_i, 4),
        "vpp_q_v": round(vpp_q, 4),
        "q_err_mean_ps": None if math.isnan(q_err_mean) else round(q_err_mean, 3),
        "pn_1mhz_dbc_hz_est": pn_1m_dbc,
    }


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, default=OUT_ROOT)
    ap.add_argument("--pex", type=Path, default=PEX_SPICE)
    ap.add_argument("corners", nargs="*")
    args = ap.parse_args()
    out_root = args.out_dir.resolve()
    pex_path = args.pex.resolve()
    globals()["PEX_SPICE"] = pex_path
    out_root.mkdir(parents=True, exist_ok=True)
    only = args.corners
    tail_node = find_tail_node(pex_path)
    print(f"Detected CPEX tail node: {tail_node} (pex={pex_path.name})", flush=True)

    # 4 extreme PVT/RC corners: check high edge (c0_hi), mid-bank +/- Vctrl (K_vco & 5.00 GHz lockability), low edge (c15_lo)
    cases = [
        ("tt_v1800_t27_tt", [
            ("c0_hi", 0, 1.40), ("c6_lo", 6, 0.45), ("c6_mid", 6, 0.90), ("c6_hi", 6, 1.35), ("c15_lo", 15, 0.35),
        ]),
        ("ss_v1650_t85_hh", [
            ("c0_hi", 0, 1.30), ("c4_mid", 4, 0.825), ("c6_mid", 6, 0.825), ("c15_lo", 15, 0.35),
        ]),
        ("ss_v1650_t-40_hh", [
            ("c0_hi", 0, 1.30), ("c6_mid", 6, 0.825), ("c15_lo", 15, 0.35),
        ]),
        ("ff_v1950_t-40_ll", [
            ("c0_hi", 0, 1.50), ("c8_mid", 8, 0.975), ("c15_lo", 15, 0.35),
        ]),
    ]

    sum_path = out_root / "summary.json"
    summary = json.loads(sum_path.read_text()) if (only and sum_path.exists()) else {"pex_spice": str(pex_path), "inductor": "vco5g_ind_oct_2n5_pdk", "corners": {}}
    for ck, pts in cases:
        if only and ck not in only:
            continue
        deck = build_cpex_deck(ck, pts, tail_node)
        run_dir = spice.next_run_dir(out_root, f"cpex__{ck}")
        print(f"=== Running Octagonal VCO CPEX @ {ck} ({len(pts)} pts) ===", flush=True)
        t0 = time.time()
        ex = spice.run(deck, run_dir, timeout_s=900, meta={"corner": ck, "mode": "oct_cpex"})
        dt = time.time() - t0
        rec = {"ok": ex.ok, "elapsed_s": round(dt, 2), "run_dir": str(run_dir), "log_failures": ex.log_failures, "points": {}}
        if ex.ok:
            t_ws = 12e-9 if ck.startswith("ff_") else 13e-9
            for tag, code, vc in pts:
                m = analyze_raw(run_dir / f"{tag}.raw", tail_node, CORNERS[ck]["temp"], t_win_start=t_ws)
                m["code"] = code
                m["vctrl"] = vc
                rec["points"][tag] = m
                print(
                    f"  {tag:7s} (c={code:2d}, vc={vc:.3f}): f={m['f_vco_ghz']:.4f}G Vpp={m['vpp_tank_v']:.3f}V "
                    f"Itot={m['itot_ma']:.2f}mA lock={m['div_locked']} fI={m['f_i_ghz']:.4f}G "
                    f"VppI={m['vpp_i_v']:.3f}V qerr={m['q_err_mean_ps']}ps PN@1M={m['pn_1mhz_dbc_hz_est']}dBc/Hz",
                    flush=True,
                )
            f_max = rec["points"]["c0_hi"]["f_vco_ghz"]
            f_min = rec["points"]["c15_lo"]["f_vco_ghz"]
            covers_5g = (f_max > 5.05) and (f_min < 4.95)
            all_locked = all(p["div_locked"] for p in rec["points"].values())
            rec["f_min_ghz"] = f_min
            rec["f_max_ghz"] = f_max
            rec["covers_5ghz_with_margin"] = covers_5g
            rec["all_div_locked"] = all_locked
            if ck == "tt_v1800_t27_tt":
                f_hi = rec["points"]["c6_hi"]["f_vco_ghz"]
                f_lo = rec["points"]["c6_lo"]["f_vco_ghz"]
                rec["kvco_mhz_per_v_c6"] = round((f_hi - f_lo) * 1e3 / (1.35 - 0.45), 1)
        else:
            print(f"  FAILED elapsed={dt:.1f}s failures={ex.log_failures[:3]}", flush=True)
        summary["corners"][ck] = rec
        summary["all_ok"] = (
            len(summary["corners"]) == 4
            and all(
                v.get("ok") and v.get("covers_5ghz_with_margin") and v.get("all_div_locked")
                for v in summary["corners"].values()
            )
        )
        sum_path.write_text(json.dumps(summary, indent=2) + "\n")

    print(f"ALL_OK={summary.get('all_ok')} -> {sum_path}", flush=True)


if __name__ == "__main__":
    main()
