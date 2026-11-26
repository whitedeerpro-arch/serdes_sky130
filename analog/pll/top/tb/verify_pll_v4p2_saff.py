#!/usr/bin/env python3
"""Closed-Loop Verification of Chip-Level 2 GHz PLL v4.2 (Zero Legacy CML /8!).

Closes the 2 GHz PLL loop directly through the real chip-level clock chain:
  r6 Ring VCO (PTAT 28/66 + HV18 LDO v2_cur + CP v4.1 + Fused LF k4)
  -> 4x Matched r5 CML->CMOS (8-phase 2 GHz CMOS spine c0..c7)
  -> Hardened SAFF-TSPC /8 Prescaler (`v2_cand`, I-TOP-03) -> q8p (fb0) -> PFD

Removes legacy `pll_clock_frontend_r6q` (legacy CML /8 + legacy C2C + 3x dummies),
verifying closed-loop lock, 8-phase CMOS spacing/duty, 250 MHz feedback integrity,
and true chip-level PLL power savings across TT, SS -40C hh, and FS 85C hh.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from serdes_flow import bias, rcorner, spice  # noqa: E402
from serdes_flow.corners import Condition  # noqa: E402

SC_LIB = Path("/home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice")
REF_PARAMS_JSON = REPO / "results/analog/pll/top/v4_closed_loop_20261123/summary.json"
TREF = 4.0e-9

V4P2_INCLUDES = [
    "analog/common/devices/spice/sky130_primitives.spice",
    "analog/common/devices/spice/sky130_pfet_lvt.spice",
    "analog/common/devices/spice/cmos_logic.spice",
    "analog/common/cml_buffer/spice/cml_delay_resistive.spice",
    "analog/common/cml_buffer/spice/cml_buffer.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_r4_v4.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_r5.spice",
    "analog/pll/vco/spice/cap_bank_5b.spice",
    "analog/pll/vco/spice/vco_delay_r6.spice",
    "analog/pll/vco/spice/vco_ring4_r6.spice",
    "analog/pll/divider/spice/tspc_reclock_prescaler8_2g_v2_cand.spice",
    "analog/pll/pfd/spice/pfd_sc.spice",
    "analog/pll/cp/spice/charge_pump_steer_v4.spice",
    "analog/pll/loop_filter/spice/passive_rc_precharge.spice",
    "analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice",
    "analog/ldo/spice/ldo_passives.spice",
    "analog/ldo/spice/pll_bias_filter_r4.spice",
    "analog/ldo/spice/ldo_v2_passives.spice",
    "analog/ldo/spice/ldo_hv18_core_v2.spice",
    "analog/ldo/spice/pll_supply_hv18_v2_cur.spice",
    "analog/bias/spice/bias_v2.spice",
    "analog/pll/vco/spice/vco_ptat_bias.spice",
    "analog/pll/top/spice/pll_top_r6_v4p2_saff.spice",
]

CORNERS = [
    dict(id="tt_v1800_t27_tt", spec="tt_v1800_t27:tt", vin=3.3, klu=False, label="TT 1.80V 27C tt"),
    dict(id="ss_v1650_t-40_hh", spec="ss_v1650_t-40:hh", vin=3.0, klu=False, label="SS 1.65V -40C hh"),
    dict(id="fs_v1650_t85_hh", spec="fs_v1650_t85:hh", vin=3.0, klu=False, label="FS 1.65V 85C hh"),
]


def load_ref_params(cid: str, spec: str) -> dict:
    data = json.loads(REF_PARAMS_JSON.read_text())
    row = data["rows"][cid]
    base, rc = spec.split(":")
    c = Condition.parse(base)
    return dict(
        c=c,
        rc=rc,
        code=int(row["code"]),
        trim=int(row["ldo_trim"]),
        vctrl_locked=float(row["vctrl_mean_v"]),
        legacy_p_total_mw=float(row.get("p_total_mw", 0.0)),
    )


def build_deck(
    cs: dict,
    p: dict,
    *,
    snap_dir: Path,
    stop_ns: float,
    skip_ns: float,
    pre_offset: float = 0.0,
    t_ref_delay: float = 2.0e-9,
    t_pre_rel: float = 12.0e-9,
    t_pfd_rel: float = 12.0e-9,
) -> str:
    c: Condition = p["c"]
    s = c.supply
    vin = cs["vin"]
    code = p["code"]
    trim = p["trim"]
    bias_trim = 15
    solver = " klu" if cs["klu"] else ""
    tstop = stop_ns * 1e-9
    lines = [
        f"* Chip-Level PLL v4.2 (4x r5 C2C + Hardened SAFF-TSPC /8): {cs['spec']} code={code}",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        *[f'.include "{REPO / inc}"' for inc in V4P2_INCLUDES],
        f'.include "{SC_LIB}"',
        f".param supply={s}",
        f"Vin vin 0 {vin}",
        "Vdd vdd 0 {supply}",
        "Ven_ldo en_ldo 0 {supply}",
        *[f"Et{k} t{k} 0 vdd 0 {(trim >> k) & 1}" for k in range(6)],
        *[f"Eg{k} g{k} 0 vdd 0 {(bias_trim >> k) & 1}" for k in range(5)],
        *[f"Ecode{k} cfg{k} 0 vq 0 {(code >> k) & 1}" for k in range(5)],
        f"Vref ref 0 PULSE(0 {{supply}} {t_ref_delay:.6e} 30p 30p {TREF / 2 - 30e-12:.4e} {TREF:.4e})",
        f"Vreset rst_b 0 PWL(0 0 {t_pfd_rel:.6e} 0 {t_pfd_rel + 20e-12:.6e} {{supply}})",
        f"Vpre pre_ref 0 {p['vctrl_locked'] + pre_offset:.5f}",
        f"Vpen pre_en 0 PWL(0 {{supply}} {t_pre_rel:.6e} {{supply}} {t_pre_rel + 200e-12:.6e} 0)",
        "Xtop vin vdd vq 0 ref rst_b en_ldo cfg0 cfg1 cfg2 cfg3 cfg4 "
        "g4 g3 g2 g1 g0 t0 t1 t2 t3 t4 t5 pre_ref pre_en "
        "vbg ctrl z up dn fb0 "
        "c0 c1 c2 c3 c4 c5 c6 c7 q2p q2n q4p q4n q8p q8n "
        "pll_top_r6_v4p2_saff nf_const=28 nf_ptat=66 cclk=12f cdiv=15f cfb=25f",
        "Ikick xtop.xcore.xclock.v0p xtop.xcore.xclock.v0n PWL(0 1u 20p 1u 40p 0)",
        # Validated DC OP nodesets for BIAS v2 + HV18 LDO v2_cur + CP v4.1 + VCO r6 (NO uic!)
        ".nodeset v(vbg)=1.234 v(xtop.xbias.xref.s)=1.234 v(xtop.xbias.vg)=1.13 "
        "v(xtop.xbias.vgi)=1.10 v(xtop.xbias.xref.ta)=0.99 v(xtop.xbias.xref.tb)=0.99",
        f".nodeset v(xtop.icml)=1.04 v(xtop.icml_vco)=1.04 v(xtop.xcore.vbias_q)=1.04 "
        f"v(xtop.icp)=0.87 v(xtop.i_ldo0)=0.88 v(xtop.i_ldo1)=0.88 v(xtop.vbp)={1.80 - 1.26:.3f}",
        f".nodeset v(ctrl)={p['vctrl_locked'] + pre_offset:.5f} v(z)={p['vctrl_locked'] + pre_offset:.5f} v(vq)=1.800",
        f".nodeset v(xtop.xcore.xcp.vbp_srv)={1.80 - 1.23:.3f} v(xtop.xcore.xcp.rep)={p['vctrl_locked'] + pre_offset:.5f}",
        f".nodeset v(xtop.xldo.xloop.ref_local)=1.233 v(xtop.xldo.fb)=1.232 "
        f"v(xtop.xldo.xloop.xcore.va)={vin - 0.35:.3f} v(xtop.xldo.xloop.xcore.pre_d)={vin - 1.27:.3f} "
        f"v(xtop.xldo.xloop.xcore.pre_g)={vin - 1.27:.3f} v(xtop.xldo.xloop.xcore.casg)={vin:.3f} "
        f"v(xtop.xldo.xloop.xcore.mid)={min(vin - 0.64, 2.85):.3f} v(xtop.xldo.xloop.xcore.gate)={1.80 + 0.56:.3f} "
        f"v(xtop.xldo.xloop.xcore.bp)={vin - 1.53:.3f} v(xtop.xldo.xloop.xcore.tail)={vin - 0.87:.3f} "
        f"v(xtop.xldo.xloop.xcore.d)=0.98 v(xtop.xldo.xloop.xcore.x)=0.76 v(xtop.xldo.xloop.vg_clamp)=0.0",
        *[
            f".nodeset v(xtop.xcore.xclock.v{k}{sd})={1.80 - 0.12:.3f} "
            f"v(xtop.xcore.xclock.xvco.xv{k}{sd}.p2)={p['vctrl_locked'] + pre_offset:.5f}"
            for k in range(4) for sd in ("p", "n")
        ],
        f".temp {c.temp}",
        f".options reltol=5e-4 abstol=1p vntol=2u gmin=1e-11 itl4=80{solver}",
        ".save v(vbg) v(vq) v(ctrl) v(z) v(ref) v(fb0) v(up) v(dn) "
        "v(c0) v(c1) v(c2) v(c3) v(c4) v(c5) v(c6) v(c7) v(q2p) v(q4p) v(q8p) "
        "i(Vin) i(Vdd)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        f"tran 8p {tstop:.6e} {skip_ns * 1e-9:.6e} 16p",
        "write pll_v4p2.raw",
        "quit 0",
        ".endc",
        ".end",
    ]
    text = "\n".join(lines) + "\n"
    snap_dir.mkdir(parents=True, exist_ok=True)
    text = rcorner.to_pdk_fixed(text, snap_dir)
    return bias.section(text, c.process, p["rc"])


def crossings(t: np.ndarray, y: np.ndarray, thr: float, *, rising: bool = True) -> np.ndarray:
    d = y - thr
    idx = np.where((d[:-1] < 0) & (d[1:] >= 0))[0] if rising else np.where((d[:-1] > 0) & (d[1:] <= 0))[0]
    if len(idx) == 0:
        return np.array([], dtype=float)
    frac = -d[idx] / (d[idx + 1] - d[idx])
    return t[idx] + frac * (t[idx + 1] - t[idx])


def measure_raw(raw_path: Path, cs: dict, p: dict, win_ns: float = 40.0) -> dict:
    w = spice.Waves(raw_path)
    t = w["time"]
    t_end = float(t[-1])
    t0 = max(float(t[0]), t_end - min(win_ns * 1e-9, 0.7 * (t_end - float(t[0]))))
    m = t >= t0
    s = p["c"].supply
    thr = 0.5 * s

    c0 = w["v(c0)"]
    fb0 = w["v(fb0)"]
    ref = w["v(ref)"]
    ctrl = w["v(ctrl)"]
    vq = w["v(vq)"]
    vbg = w["v(vbg)"]
    ivin = w["i(vin)"] if "i(vin)" in w.names else w["i(Vin)"]
    ivdd = w["i(vdd)"] if "i(vdd)" in w.names else w["i(Vdd)"]

    tr_c0 = crossings(t[m], c0[m], thr, rising=True)
    tf_c0 = crossings(t[m], c0[m], thr, rising=False)
    tr_fb = crossings(t[m], fb0[m], thr, rising=True)
    tf_fb = crossings(t[m], fb0[m], thr, rising=False)
    tr_ref = crossings(t[m], ref[m], thr, rising=True)

    f_2g_ghz = float((len(tr_c0) - 1) / (tr_c0[-1] - tr_c0[0]) / 1e9) if len(tr_c0) >= 4 else 0.0
    f_fb_mhz = float((len(tr_fb) - 1) / (tr_fb[-1] - tr_fb[0]) / 1e6) if len(tr_fb) >= 2 else 0.0
    f_err_ppm = (f_2g_ghz - 2.0) / 2.0 * 1e6 if f_2g_ghz > 0 else float("nan")

    # Fixed 2.0 GHz grid TIE peak-to-peak on c0
    if len(tr_c0) >= 8:
        idx_k = np.arange(len(tr_c0), dtype=float)
        # Fit slope to check jitter vs ideal 500 ps grid
        tie_grid = (tr_c0 - tr_c0[0]) - idx_k * 0.5e-9
        tie_pp_ps = float((np.max(tie_grid) - np.min(tie_grid)) * 1e12)
        per_std_ps = float(np.std(np.diff(tr_c0)) * 1e12)
    else:
        tie_pp_ps = float("nan")
        per_std_ps = float("nan")

    # 8-phase CMOS spacing & duty cycle across last min(10 ns, window)
    m8 = t >= max(t0, t_end - 10e-9)
    duties = []
    tr_ph = []
    for k in range(8):
        yk = w[f"v(c{k})"][m8]
        tk = t[m8]
        rk = crossings(tk, yk, thr, rising=True)
        fk = crossings(tk, yk, thr, rising=False)
        tr_ph.append(rk)
        if len(rk) >= 4 and len(fk) >= 4:
            # Pair each rise with next fall
            hs = []
            for r in rk[:-1]:
                nxt = fk[fk > r]
                if len(nxt):
                    hs.append(nxt[0] - r)
            per_k = np.mean(np.diff(rk))
            duties.append(float(np.mean(hs) / per_k))
    step_errs_ps = []
    if all(len(r) >= 4 for r in tr_ph):
        t_per = float(np.mean(np.diff(tr_ph[0])))
        ideal_step = t_per / 8.0
        for k in range(8):
            ra = tr_ph[k]
            rb = tr_ph[(k + 1) % 8]
            dts = []
            for r in ra[:-2]:
                nxt = rb[rb > r]
                if len(nxt):
                    dts.append(nxt[0] - r)
            if dts:
                step_errs_ps.append(float((np.mean(dts) - ideal_step) * 1e12))

    # FB0 duty
    fb_duty = float("nan")
    if len(tr_fb) >= 3 and len(tf_fb) >= 3:
        hs = [tf_fb[tf_fb > r][0] - r for r in tr_fb[:-1] if np.any(tf_fb > r)]
        if hs:
            fb_duty = float(np.mean(hs) / np.mean(np.diff(tr_fb)))

    # Ref-to-FB phase offset (folded to [-2 ns, +2 ns])
    ref_fb_ps = float("nan")
    if len(tr_ref) >= 3 and len(tr_fb) >= 3:
        offs = []
        for rr in tr_ref:
            j = int(np.argmin(np.abs(tr_fb - rr)))
            offs.append((tr_fb[j] - rr) * 1e12)
        ref_fb_ps = float(np.mean(offs))

    p_vin_mw = float(np.mean(-ivin[m]) * cs["vin"] * 1e3)
    p_vdd_mw = float(np.mean(-ivdd[m]) * s * 1e3)
    p_total_mw = p_vin_mw + p_vdd_mw
    div_ratio = (f_2g_ghz * 1e3 / f_fb_mhz) if f_fb_mhz > 10 else 0.0
    ok = (
        abs(f_err_ppm) < 1000.0
        and abs(div_ratio - 8.0) < 0.02
        and (len(step_errs_ps) == 8 and max(abs(x) for x in step_errs_ps) < 25.0)
        and (len(duties) == 8 and all(0.42 <= d <= 0.58 for d in duties))
    )
    return dict(
        id=cs["id"],
        spec=cs["spec"],
        label=cs["label"],
        code=p["code"],
        t_end_ns=round(t_end * 1e9, 3),
        ok=bool(ok),
        f_2g_ghz=round(f_2g_ghz, 6),
        f_fb_mhz=round(f_fb_mhz, 4),
        div_ratio=round(div_ratio, 5),
        f_err_ppm=round(f_err_ppm, 1),
        tie_pp_ps=round(tie_pp_ps, 2),
        per_std_ps=round(per_std_ps, 3),
        ref_fb_offset_ps=round(ref_fb_ps, 1),
        fb_duty=round(fb_duty, 4),
        vctrl_mean_v=round(float(np.mean(ctrl[m])), 5),
        vctrl_ripple_mv=round(float((np.max(ctrl[m]) - np.min(ctrl[m])) * 1e3), 2),
        vq_mean_v=round(float(np.mean(vq[m])), 5),
        vbg_mean_v=round(float(np.mean(vbg[m])), 5),
        c8_duty_min=round(min(duties), 4) if duties else None,
        c8_duty_max=round(max(duties), 4) if duties else None,
        c8_max_step_err_ps=round(max(abs(x) for x in step_errs_ps), 2) if step_errs_ps else None,
        c8_step_errs_ps=[round(x, 2) for x in step_errs_ps],
        p_vin_mw=round(p_vin_mw, 3),
        p_vdd_mw=round(p_vdd_mw, 3),
        p_total_mw=round(p_total_mw, 3),
        legacy_p_total_mw=round(p["legacy_p_total_mw"], 3),
        p_saved_mw=round(p["legacy_p_total_mw"] - p_total_mw, 3) if p["legacy_p_total_mw"] > 0 else None,
    )


def run_corner(out_dir: Path, cs: dict, *, stop_ns: float, skip_ns: float, pre_offset: float) -> dict:
    p = load_ref_params(cs["id"], cs["spec"])
    case_dir = out_dir / cs["id"]
    raw_path = spice.case_output(case_dir, "run", "pll_v4p2.raw", t_end=stop_ns * 1e-9)
    if raw_path is None:
        run_dir = spice.next_run_dir(case_dir, "run")
        deck = build_deck(
            cs, p, snap_dir=out_dir / "snap", stop_ns=stop_ns, skip_ns=skip_ns,
            pre_offset=pre_offset, t_pre_rel=8.0e-9, t_pfd_rel=9.0e-9,
        )
        ex = spice.run(deck, run_dir, timeout_s=3600)
        cand_raw = run_dir / "pll_v4p2.raw"
        if not cand_raw.exists():
            return dict(id=cs["id"], spec=cs["spec"], ok=False, error=ex.log_failures[:5])
        w_chk = spice.Waves(cand_raw)
        if float(w_chk["time"][-1]) < 0.995 * stop_ns * 1e-9:
            return dict(id=cs["id"], spec=cs["spec"], ok=False, error=["truncated_raw"] + ex.log_failures[:5])
        raw_path = cand_raw
    return measure_raw(raw_path, cs, p, win_ns=min(40.0, max(10.0, stop_ns - skip_ns - 15.0)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, default=REPO / "results/analog/pll/top/v4p2_saff_20261123")
    ap.add_argument("--corners", nargs="*", default=[c["id"] for c in CORNERS])
    ap.add_argument("--stop-ns", type=float, default=120.0)
    ap.add_argument("--skip-ns", type=float, default=10.0)
    ap.add_argument("--pre-offset", type=float, default=0.02, help="Initial Vctrl step (V) to verify active closed-loop pull-in")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--smoke", action="store_true", help="Fast 10 ns TT smoke test")
    args = ap.parse_args()

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.smoke:
        cs = CORNERS[0]
        res = run_corner(out_dir / "smoke_10ns_op", cs, stop_ns=10.0, skip_ns=0.0, pre_offset=0.0)
        print(json.dumps(res, indent=2))
        return

    sel = [c for c in CORNERS if c["id"] in set(args.corners)]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(2, args.workers))) as ex:
        futs = [
            ex.submit(run_corner, out_dir, cs, stop_ns=args.stop_ns, skip_ns=args.skip_ns, pre_offset=args.pre_offset)
            for cs in sel
        ]
        for fut in concurrent.futures.as_completed(futs):
            r = fut.result()
            results.append(r)
            print(
                f"[pll_v4p2] {r['id']:18s} ok={r.get('ok')} f2g={r.get('f_2g_ghz')} GHz "
                f"err={r.get('f_err_ppm')} ppm TIE={r.get('tie_pp_ps')} ps "
                f"P={r.get('p_total_mw')} mW (saved {r.get('p_saved_mw')} mW vs legacy)"
            )
    results.sort(key=lambda r: [c["id"] for c in CORNERS].index(r["id"]))
    summary = dict(
        dut="analog/pll/top/spice/pll_top_r6_v4p2_saff.spice",
        divider="analog/pll/divider/spice/tspc_reclock_prescaler8_2g_v2_cand.spice",
        stop_ns=args.stop_ns,
        pre_offset_v=args.pre_offset,
        passed=sum(1 for r in results if r.get("ok")),
        total=len(results),
        corners=results,
    )
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"[pll_v4p2] Saved {out_dir / 'summary.json'} ({summary['passed']}/{summary['total']} PASS)")


if __name__ == "__main__":
    main()
