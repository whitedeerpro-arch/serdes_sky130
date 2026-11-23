"""Stage 2 Full 16:1 All-CMOS + N-over-N SST TX 45-Corner PVT Verification.

Tests the complete 16:1 TX (`serdes_tx_sst_top`: 16:4 pure static CMOS serializer +
/2, /4 dividers + 4-phase stagger retimer + quarter-rate 4:1 fused N-over-N SST driver +
built-in 2-tap FFE + 5-bit ZQ + on-chip V_drv LDO) across all 45 MOS PVT conditions
(TT/SS/FF/SF/FS x 1.65/1.80/1.95 V x -40/27/85 C) in `corners.boundary_first` order.

Hard system constraints enforced:
- MAX 2 concurrent ngspice workers (`--workers <= 2`)
- `num_threads=1`, `spice.binary_output`, `spice.skip_output_before`
- Case-level resume via `spice.case_output(..., t_end=t_stop)` and `spice.next_run_dir`

Step 0: Fast merged-by-process-corner ZQ DC calibration (5 decks, 9 V/T points each -> ~20 s)
        determining exact integer `n_zq` and `R_pu / R_pd` for all 45 corners.
Step 1: Full 45-corner 16:1 transient verification (208 bits = 64 training + 128 PRBS-7 + 16 tail,
        RLC16 matched channel, FFE=0) checking:
        - `serial.bit_mapping` (`in_order=True`, exact 0..15 natural bit mapping)
        - `serial.check` (0 bit errors, signed eye margin >= 75 mV, edge spread <= 0.15 UI)
        - differential pad swing (~400 mVpp target), V_drv regulation & ripple, total TX power (mW & pJ/bit).
Step 2: Full 16:1 TX through real C2_loss6 (6 dB @ 2 GHz) PCB channel on key corners
        (TT, FS 1.65V 85C, SS 1.65V -40C, SS 1.65V 85C) comparing FFE=0 vs FFE=3.

Usage:
  uv run python analog/tx/sst/tb/run_pvt45.py [--workers 2] [--resume <campaign_dir>] [--conds tt_v1800_t27 ...]
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import threading
import time
from pathlib import Path

import numpy as np

from serdes_flow import corners, eye, project, serial, spice

ROOT = project.ROOT
RESULTS = ROOT / "results/analog/tx/sst"
UI = 250e-12
T_CLK = 4 * UI       # 1.0 ns (1 GHz quadrature clocks)
T_WORD = 16 * UI     # 4.0 ns (250 MHz 16-bit parallel words)
PAYLOAD_BITS = 128   # 64 training + 128 PRBS-7 + 16 tail = 208 bits = 13 words
TAIL_BITS = 16
TOTAL_BITS = serial.TRAINING_BITS + PAYLOAD_BITS + TAIL_BITS
T_RST_REL = 1.45e-9  # release async reset before first c0 rising edge at 2.0 ns
T_FIRST_UPD = 4.0e-9 # update word 0 near clk250 falling edge (~2.2 ns setup to 6.2 ns rising)
T_PAD_START = 9.0e-9 # nominal arrival of word 0 bit 0 on pad (before ~0.2 ns driver delay)


def build_sequence() -> np.ndarray:
    """64-bit training (32 alternating + 32 marker 0xD3A5,0x6C9E) + 128 PRBS-7 + 16 tail."""
    alt = [i & 1 for i in range(32)]
    marker_words = (0xD3A5, 0x6C9E)
    marker = [(w >> b) & 1 for w in marker_words for b in range(16)]
    payload = eye.prbs7(PAYLOAD_BITS + TAIL_BITS, seed=0x5D)
    return np.array(alt + marker + payload, dtype=int)


def encode_zq_ffe(n_zq: int, n_post: int) -> dict[str, int]:
    n_main = n_zq - n_post
    if not (0 <= n_main <= 23 and 0 <= n_post <= 5):
        raise ValueError(f"Invalid slice counts: n_zq={n_zq}, n_post={n_post}")
    m4 = 1 if n_main >= 16 else 0
    rem = n_main - 8 * m4
    m3 = (rem >> 3) & 1
    m2 = (rem >> 2) & 1
    m1 = (rem >> 1) & 1
    m0 = rem & 1
    f2 = 1 if n_post >= 4 else 0
    remf = n_post - 2 * f2
    f1 = 1 if remf >= 2 else 0
    f0 = remf - 2 * f1
    return dict(m0=m0, m1=m1, m2=m2, m3=m3, m4=m4, f0=f0, f1=f1, f2=f2, ffe_en=1 if n_post > 0 else 0)


def pwl_lines(head: str, pts: list[tuple[float, float]]) -> str:
    toks = [f"{t:.7e} {v:.5f}" for t, v in pts]
    out = [f"{head} PWL("]
    for i in range(0, len(toks), 6):
        out.append("+ " + " ".join(toks[i:i + 6]))
    return "\n".join(out) + " )\n"


def parallel_word_stimuli(bits: np.ndarray, supply: float, edge: float = 50e-12) -> str:
    """Generate 16 parallel 250 MHz word inputs din0..din15.

    Starts in DC-balanced alternating word (0xAAAA -> bit i = i & 1) before word 0 updates
    at T_FIRST_UPD = 4.0 ns, giving >1.5 ns hold and >2.0 ns setup across all 45 PVT corners.
    """
    n_words = len(bits) // 16
    lines = []
    for bit_idx in range(16):
        init_b = bit_idx & 1
        pts = [(0.0, supply if init_b else 0.0)]
        prev = init_b
        for w in range(n_words):
            b = int(bits[16 * w + bit_idx])
            if b != prev:
                t_upd = T_FIRST_UPD + w * T_WORD
                v0 = supply if prev else 0.0
                v1 = supply if b else 0.0
                pts.extend([(t_upd - edge / 2, v0), (t_upd + edge / 2, v1)])
                prev = b
        lines.append(pwl_lines(f"Vdin{bit_idx} din{bit_idx} 0", pts))
    return "".join(lines)


def build_merged_zq_cal_deck(proc: str, conds: list[corners.Condition]) -> str:
    """Merged single-deck DC unit-slice Rout calibration for all 9 V/T points of one process corner."""
    steps = []
    for c in conds:
        steps.append(
            f"option temp={c.temp}\n"
            f"alter Vdd dc={c.supply}\n"
            f"alter Vdinp dc={c.supply}\n"
            f"alter Ven dc={c.supply}\n"
            f"op\n"
            f"let r_pu = (0.44 - 0.33) / i(Vpadp)\n"
            f"let r_pd = (0.11 - 0.00) / (-i(Vpadn))\n"
            f"echo ZQCAL tag={c.tag} r_pu=$&r_pu r_pd=$&r_pd\n"
        )
    body = "".join(steps)
    return f"""* Merged ZQ Unit-Slice Rout Calibration ({proc}, 9 V/T points)
.lib "{project.model_library()}" {proc}
.include "{ROOT}/analog/common/devices/spice/sky130_primitives.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_driver.spice"

Vdd vdd 0 1.8
Vdrv_ref vdrv_ref 0 0.44
Vdinp dinp 0 1.8
Vdinn dinn 0 0
Ven   en   0 1.8
Vpadp padp 0 0.33
Vpadn padn 0 0.11
Xslice dinp dinn en padp padn vdrv_ref vdd 0 sst_slice_unit

.options reltol=1e-4 abstol=1p vntol=1u klu
.control
set num_threads=1
{body}quit
.endc
.end
"""


def calibrate_zq_45(camp: Path, conds: list[corners.Condition], workers: int) -> dict[str, dict]:
    cal_path = camp / "zq_cal_45.json"
    if cal_path.exists():
        cal = json.loads(cal_path.read_text())
        if all(c.tag in cal for c in conds):
            return cal
    by_proc: dict[str, list[corners.Condition]] = {}
    for c in conds:
        by_proc.setdefault(c.process, []).append(c)
    jobs, procs = [], []
    for proc, clist in sorted(by_proc.items()):
        rdir = spice.next_run_dir(camp, f"zqcal_{proc}")
        jobs.append((build_merged_zq_cal_deck(proc, clist), rdir, {"timeout_s": 120}))
        procs.append((proc, rdir))
    print(f"\n=== [0/2] Fast Merged ZQ Calibration ({len(conds)} corners across {len(jobs)} decks, workers={workers}) ===", flush=True)
    execs = spice.run_many(jobs, workers=workers, smoke=False)
    cal: dict[str, dict] = {}
    for ex, (proc, rdir) in zip(execs, procs):
        if not ex.ok:
            raise RuntimeError(f"ZQ cal failed for {proc}: {ex.log_failures}")
        for line in (rdir / "simulator.log").read_text(errors="replace").splitlines():
            if line.startswith("ZQCAL "):
                row = {}
                for tok in line.split()[1:]:
                    k, v = tok.split("=", 1)
                    row[k] = v if k == "tag" else float(v)
                r_avg = 0.5 * (row["r_pu"] + row["r_pd"])
                n_zq = max(8, min(23, int(round(r_avg / 50.0))))
                cal[row["tag"]] = dict(
                    r_pu_unit=row["r_pu"],
                    r_pd_unit=row["r_pd"],
                    r_avg_unit=r_avg,
                    n_zq=n_zq,
                    r_out_est=r_avg / n_zq,
                )
    cal_path.write_text(json.dumps(cal, indent=2) + "\n")
    r_outs = [cal[c.tag]["r_out_est"] for c in conds]
    n_zqs = [cal[c.tag]["n_zq"] for c in conds]
    print(f"Calibrated {len(cal)} corners: N_zq in [{min(n_zqs)}, {max(n_zqs)}], est R_out in [{min(r_outs):.2f}, {max(r_outs):.2f}] ohm", flush=True)
    return cal


def build_top_deck(
    *,
    corner: str,
    supply: float,
    temp_c: int,
    n_zq: int,
    n_post: int,
    channel: str,
    stim_file: str = "stimuli.inc",
) -> tuple[str, float]:
    bits_ctrl = encode_zq_ffe(n_zq, n_post)
    # Ramp enabled slice controls at t=0.5ns so pads start balanced at Vcm=0.22V (0 mV offset on Clac!)
    ctrl_lines = "\n".join(
        f"Vctrl_{k} {k} 0 PWL(0 0 0.5e-9 0 0.6e-9 {{vdd_v}})" if v else f"Vctrl_{k} {k} 0 0.0"
        for k, v in bits_ctrl.items()
    )
    if channel == "rlc16":
        ch_inc = f'.include "{ROOT}/verification/models/channel/diff_rlc16.spice"'
        ch_inst = "Xchannel ltp ltn lxp lxn 0 serdes_diff_rlc16"
        t_stop = T_PAD_START + TOTAL_BITS * UI + 2.5e-9
    elif channel == "c2":
        ch_inc = (
            f'.include "{ROOT}/verification/models/channel/pcb_family/pcb_foster_cells.spice"\n'
            f'.include "{ROOT}/verification/models/channel/pcb_family/C2_loss6.spice"'
        )
        ch_inst = "Xchannel ltp ltn lxp lxn 0 pcb_c2_loss6"
        t_stop = T_PAD_START + TOTAL_BITS * UI + 4.5e-9
    else:
        raise ValueError(f"Unknown channel: {channel}")

    # Valid Slot-0 quadrature clocks at t=0: phi0=1, phi90=0, phi180=0, phi270=1
    tr = 30e-12
    pw = 0.5 * T_CLK - tr
    tf0 = 0.50 * T_CLK - tr / 2
    tr90 = 0.25 * T_CLK - tr / 2
    tr180 = 0.50 * T_CLK - tr / 2
    tf270 = 0.25 * T_CLK - tr / 2

    deck = f"""* Full 16:1 All-CMOS + N-over-N SST TX ({corner}, {supply}V, {temp_c}C, Nzq={n_zq}, FFE={n_post}, ch={channel})
.lib "{project.model_library()}" {corner}
.include "{ROOT}/analog/common/devices/spice/sky130_primitives.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_driver.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_serializer16.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_top.spice"
{ch_inc}

.param vdd_v={supply}
Vdd vdd 0 {{vdd_v}}
Vbg vbg 0 1.20
Vrst rst_n 0 PWL(0 0 {T_RST_REL - 25e-12:.6e} 0 {T_RST_REL + 25e-12:.6e} {{vdd_v}})

* 4-phase 1 GHz quadrature clocks (50% duty, valid Slot-0 state at t=0)
Vphi0   phi0   0 PULSE({{vdd_v}} 0 {tf0:.6e}   {tr:.3e} {tr:.3e} {pw:.6e} {T_CLK:.6e})
Vphi90  phi90  0 PULSE(0 {{vdd_v}} {tr90:.6e}  {tr:.3e} {tr:.3e} {pw:.6e} {T_CLK:.6e})
Vphi180 phi180 0 PULSE(0 {{vdd_v}} {tr180:.6e} {tr:.3e} {tr:.3e} {pw:.6e} {T_CLK:.6e})
Vphi270 phi270 0 PULSE({{vdd_v}} 0 {tf270:.6e} {tr:.3e} {tr:.3e} {pw:.6e} {T_CLK:.6e})

* Static ZQ & FFE slice enables
{ctrl_lines}

* 16-bit parallel word inputs @ 250 MHz
.include "{stim_file}"

* Full 16:1 All-CMOS + N-over-N SST TX DUT
Xdut din0 din1 din2 din3 din4 din5 din6 din7
+ din8 din9 din10 din11 din12 din13 din14 din15
+ phi0 phi90 phi180 phi270 rst_n
+ m0 m1 m2 m3 m4 f0 f1 f2 ffe_en
+ vbg lqp lqn vdrv clk500_out clk250_out vdd 0 serdes_tx_sst_top

* Exact repo TX pad / package / AC coupling / channel / far-end 50-ohm termination
* Weak 100k DC reference to Vcm=0.22V defines balanced t=0 operating point across Clac (<0.05% on 50 ohm)
Vcm_init vcm_init 0 0.22
Rpad_dc_p lqp vcm_init 100k
Rpad_dc_n lqn vcm_init 100k
Clpp lqp 0 200f
Clpn lqn 0 200f
Rlpp lqp llp 0.3
Rlpn lqn lln 0.3
Llpp llp lap 0.5n
Llpn lln lan 0.5n
Clacp lap ltp 10n
Clacn lan ltn 10n
{ch_inst}
Rlc0 lxp lrp 0.01
Rlc1 lxn lrn 0.01
Clc0 lrp 0 100f
Clc1 lrn 0 100f
Vlcm lcm 0 0.9
Rlterm0 lrp lcm 50
Rlterm1 lrn lcm 50

.nodeset v(vdrv)=0.44 v(lqp)=0.22 v(lqn)=0.22 v(xdut.xdrv.xldo.vgate)=1.0
.temp {temp_c}
.options reltol=2e-4 abstol=1p vntol=2u klu
.save v(lqp) v(lqn) v(lrp) v(lrn) v(vdrv) v(vdd) i(Vdd) v(clk250_out)
.control
set num_threads=1
tran 4p {t_stop:.6e} 0 5p
let pad = v(lqp) - v(lqn)
let remote = v(lrp) - v(lrn)
let pad_cm = 0.5 * (v(lqp) + v(lqn))
let vdrv_v = v(vdrv)
let power = -v(vdd) * i(Vdd)
let clk250 = v(clk250_out)
wrdata waveforms.tsv pad remote pad_cm vdrv_v power clk250
quit
.endc
.end
"""
    deck = spice.skip_output_before(deck, "6.0e-9")
    deck = spice.binary_output(deck)
    return deck, t_stop


def analyze_top_wave(raw_path: Path, bits: np.ndarray, channel: str) -> dict:
    w = spice.Waves(raw_path)
    seq = serial.Sequence(bits=bits, start_s=T_PAD_START, ui_s=UI)
    pad_m, _ = serial.check(w.t, w["pad"], seq, PAYLOAD_BITS)
    rem_m, _ = serial.check(w.t, w["remote"], seq, PAYLOAD_BITS)
    bmap = serial.bit_mapping(w.t, w["pad"], seq, first_bit=serial.TRAINING_BITS, end_margin_s=1.5e-9)
    pad_t0 = T_PAD_START + round(pad_m["training_delay_ui"]) * UI
    rem_t0 = T_PAD_START + round(rem_m["training_delay_ui"]) * UI
    pad_eye = eye.signed_eye(w.t, w["pad"], bits.tolist(), UI, pad_t0, first_bit=serial.TRAINING_BITS, n_bits=PAYLOAD_BITS)
    rem_eye = eye.signed_eye(w.t, w["remote"], bits.tolist(), UI, rem_t0, first_bit=serial.TRAINING_BITS, n_bits=PAYLOAD_BITS)

    t_win = (w.t >= pad_t0 + serial.TRAINING_BITS * UI) & (w.t <= pad_t0 + (serial.TRAINING_BITS + PAYLOAD_BITS) * UI)
    pwr_w = float(np.trapezoid(w["power"][t_win], w.t[t_win]) / (w.t[t_win][-1] - w.t[t_win][0]))
    vdrv_seg = w["vdrv_v"][t_win]
    return dict(
        channel=channel,
        training_delay_ui=float(pad_m["training_delay_ui"]),
        pad_functional=bool(pad_m["functional"]),
        pad_errors=int(pad_m["bit_errors"]),
        pad_in_order=bool(bmap["in_order"]),
        pad_mapping=bmap["mapping"],
        pad_pp_mv=float(pad_m["differential_pp_v"] * 1e3),
        pad_margin_mv=float(pad_m["minimum_signed_margin_v"] * 1e3),
        pad_eye_h_mv=float(pad_eye["height_v"] * 1e3),
        pad_eye_w_ui=float(pad_eye["width_ui"]),
        pad_spread_ui=float(pad_m["transition_spread_ui"]) if pad_m["transition_spread_ui"] is not None else None,
        pad_meets_spec=bool(serial.meets_draft(pad_m) and bmap["in_order"]),
        rem_functional=bool(rem_m["functional"]),
        rem_errors=int(rem_m["bit_errors"]),
        rem_pp_mv=float(rem_m["differential_pp_v"] * 1e3),
        rem_margin_mv=float(rem_m["minimum_signed_margin_v"] * 1e3),
        rem_eye_h_mv=float(rem_eye["height_v"] * 1e3),
        rem_eye_w_ui=float(rem_eye["width_ui"]),
        rem_spread_ui=float(rem_m["transition_spread_ui"]) if rem_m["transition_spread_ui"] is not None else None,
        power_mw=float(pwr_w * 1e3),
        pj_per_bit=float(pwr_w * 1e3 / 4.0),
        vdrv_mean_v=float(np.mean(vdrv_seg)),
        vdrv_ripple_mvpp=float(np.ptp(vdrv_seg) * 1e3),
        pad_cm_mv=float(np.mean(w["pad_cm"][t_win]) * 1e3),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3, help="Max concurrent ngspice (cap <= 3)")
    ap.add_argument("--resume", type=Path, default=None, help="Existing campaign directory to resume")
    ap.add_argument("--conds", nargs="*", default=None, help="Optional subset of condition tags (e.g., tt_v1800_t27)")
    ap.add_argument("--skip-c2", action="store_true", help="Skip Step 2 full-TX C2 FFE checks")
    args = ap.parse_args()
    workers = min(args.workers, 3)

    all_conds = corners.boundary_first(corners.grid45())
    if args.conds:
        wanted = set(args.conds)
        conds = [c for c in all_conds if c.tag in wanted]
        if len(conds) != len(wanted):
            missing = wanted - {c.tag for c in conds}
            raise ValueError(f"Unknown condition tags: {missing}")
    else:
        conds = all_conds

    bits = build_sequence()
    if args.resume is not None:
        camp = args.resume.resolve()
        run_id = camp.name
        camp.mkdir(parents=True, exist_ok=True)
    else:
        run_id = time.strftime("%Y%m%dT%H%M%SZ_top16_pvt45", time.gmtime())
        camp = RESULTS / run_id
        camp.mkdir(parents=True, exist_ok=True)
    (camp / "bits.json").write_text(json.dumps(bits.tolist()))

    cal = calibrate_zq_45(camp, conds, workers=workers)

    # Pre-generate 16-bit parallel stimuli for the 3 supply levels
    stim_paths: dict[int, Path] = {}
    for vdd in sorted({c.supply for c in conds}):
        key = round(vdd * 1000)
        sp = camp / f"stim16_{key}.inc"
        if not sp.exists():
            sp.write_text(parallel_word_stimuli(bits, vdd))
        stim_paths[key] = sp

    summary_path = camp / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {
        "run_id": run_id, "workers": workers, "payload_bits": PAYLOAD_BITS,
        "pvt45": {}, "c2_top": {},
    }

    # --- Step 1: Full 16:1 TX across all selected PVT corners (boundary_first, resumable) ---
    print(f"\n=== [1/2] Full 16:1 All-CMOS + N-over-N SST TX ({len(conds)} corners, {PAYLOAD_BITS} payload bits, workers={workers}) ===", flush=True)
    print(f"{'#':>2} {'Corner':<16} {'Nzq':>3} {'InOrd':>5} {'Err':>3} {'PadPP':>7} {'Margin':>8} {'Spread':>8} {'Vdrv':>7} {'RipmV':>6} {'Pwr(mW)':>8} {'pJ/b':>6} {'Spec':>5}", flush=True)

    lock = threading.Lock()
    todo_items = []
    for c in conds:
        n_zq = cal[c.tag]["n_zq"]
        deck, t_stop = build_top_deck(
            corner=c.process, supply=c.supply, temp_c=c.temp,
            n_zq=n_zq, n_post=0, channel="rlc16",
        )
        existing = spice.case_output(camp, c.tag, "waveforms.raw", t_end=t_stop)
        if existing is not None:
            if c.tag not in summary["pvt45"]:
                m = analyze_top_wave(existing, bits, "rlc16")
                ex_p = existing.parent / "execution.json"
                el = json.loads(ex_p.read_text()).get("elapsed_s", 0.0) if ex_p.exists() else 0.0
                m.update(
                    tag=c.tag, process=c.process, supply=c.supply, temp_c=c.temp,
                    n_zq=n_zq, n_post=0, r_out_est=cal[c.tag]["r_out_est"],
                    elapsed_s=el, raw=str(existing.relative_to(ROOT)),
                )
                summary["pvt45"][c.tag] = m
            else:
                m = summary["pvt45"][c.tag]
            spr_s = f"{m['pad_spread_ui']:8.4f}" if m["pad_spread_ui"] is not None else "    None"
            print(
                f"{len(summary['pvt45']):2d} {c.tag:<16} {n_zq:3d} {str(m['pad_in_order']):>5} {m['pad_errors']:3d} "
                f"{m['pad_pp_mv']:7.1f} {m['pad_margin_mv']:8.1f} {spr_s} "
                f"{m['vdrv_mean_v']:7.4f} {m['vdrv_ripple_mvpp']:6.2f} {m['power_mw']:8.2f} {m['pj_per_bit']:6.2f} "
                f"{'PASS' if m['pad_meets_spec'] else 'FAIL':>5} (cached)",
                flush=True,
            )
        else:
            todo_items.append((c, n_zq, deck, t_stop))

    def _run_one(item):
        c, n_zq, deck, t_stop = item
        rdir = spice.next_run_dir(camp, c.tag)
        ex = spice.run(
            deck, rdir,
            files={"stimuli.inc": stim_paths[round(c.supply * 1000)]},
            timeout_s=1200,
        )
        return c, n_zq, t_stop, ex

    if todo_items:
        # Run 1-ns smoke on first uncached corner only if none cached yet
        if not summary["pvt45"]:
            c0, _, deck0, _ = todo_items[0]
            sdir = spice.next_run_dir(camp, f"{c0.tag}_smoke")
            ex_s = spice.run(spice.smoke_deck(deck0), sdir, files={"stimuli.inc": stim_paths[round(c0.supply * 1000)]}, timeout_s=180)
            if not ex_s.ok:
                raise RuntimeError(f"Smoke test failed on {c0.tag}: {ex_s.log_failures}")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_run_one, item) for item in todo_items]
            for fut in as_completed(futs):
                c, n_zq, t_stop, ex = fut.result()
                if not ex.ok:
                    print(f"FAIL {c.tag}: {ex.log_failures}", flush=True)
                    continue
                found = spice.case_output(camp, c.tag, "waveforms.raw", t_end=t_stop)
                if found is None:
                    print(f"WARN {c.tag}: truncated waveform", flush=True)
                    continue
                m = analyze_top_wave(found, bits, "rlc16")
                m.update(
                    tag=c.tag, process=c.process, supply=c.supply, temp_c=c.temp,
                    n_zq=n_zq, n_post=0, r_out_est=cal[c.tag]["r_out_est"],
                    elapsed_s=ex.elapsed_s, raw=str(found.relative_to(ROOT)),
                )
                with lock:
                    summary["pvt45"][c.tag] = m
                    n_done = len(summary["pvt45"])
                    spr_s = f"{m['pad_spread_ui']:8.4f}" if m["pad_spread_ui"] is not None else "    None"
                    print(
                        f"{n_done:2d} {c.tag:<16} {n_zq:3d} {str(m['pad_in_order']):>5} {m['pad_errors']:3d} "
                        f"{m['pad_pp_mv']:7.1f} {m['pad_margin_mv']:8.1f} {spr_s} "
                        f"{m['vdrv_mean_v']:7.4f} {m['vdrv_ripple_mvpp']:6.2f} {m['power_mw']:8.2f} {m['pj_per_bit']:6.2f} "
                        f"{'PASS' if m['pad_meets_spec'] else 'FAIL':>5}",
                        flush=True,
                    )
                    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    # --- Step 2: Full 16:1 TX through Real C2_loss6 PCB Channel (FFE=0 vs FFE=3 on key corners) ---
    if not args.skip_c2:
        c2_tags = [
            ("tt_v1800_t27", 0),
            ("tt_v1800_t27", 3),
            ("fs_v1650_t85", 0),
            ("fs_v1650_t85", 3),
            ("ss_v1650_t-40", 0),
            ("ss_v1650_t-40", 3),
        ]
        c_by_tag = {c.tag: c for c in conds}
        c2_pairs = [(c_by_tag[t], fp) for t, fp in c2_tags if t in c_by_tag]
        if c2_pairs:
            print(f"\n=== [2/2] Full 16:1 TX -> C2_loss6 PCB Channel ({len(c2_pairs)} runs, workers={workers}) ===", flush=True)
            print(f"{'Case':<24} {'FFE':>3} {'PadPP':>7} {'C2_PP':>7} {'C2_Marg':>8} {'C2_EyeH':>8} {'C2_EyeW':>8} {'C2_Sprd':>8} {'Pwr(mW)':>8}", flush=True)
            for idx in range(0, len(c2_pairs), workers):
                batch = c2_pairs[idx:idx + workers]
                todo_jobs, todo_meta, ready_meta = [], [], []
                for c, n_post in batch:
                    n_zq = cal[c.tag]["n_zq"]
                    case_tag = f"c2_{c.tag}_ffe{n_post}"
                    deck, t_stop = build_top_deck(
                        corner=c.process, supply=c.supply, temp_c=c.temp,
                        n_zq=n_zq, n_post=n_post, channel="c2",
                    )
                    existing = spice.case_output(camp, case_tag, "waveforms.raw", t_end=t_stop)
                    if existing is not None:
                        ready_meta.append((case_tag, c, n_zq, n_post, existing))
                    else:
                        rdir = spice.next_run_dir(camp, case_tag)
                        todo_jobs.append((deck, rdir, {"files": {"stimuli.inc": stim_paths[round(c.supply * 1000)]}, "timeout_s": 1200}))
                        todo_meta.append((case_tag, c, n_zq, n_post, t_stop))
                if todo_jobs:
                    execs = spice.run_many(todo_jobs, workers=workers, smoke=False)
                    for ex, (case_tag, c, n_zq, n_post, t_stop) in zip(execs, todo_meta):
                        if ex.ok:
                            found = spice.case_output(camp, case_tag, "waveforms.raw", t_end=t_stop)
                            if found is not None:
                                ready_meta.append((case_tag, c, n_zq, n_post, found))
                        else:
                            print(f"FAIL {case_tag}: {ex.log_failures}", flush=True)
                for case_tag, c, n_zq, n_post, raw_p in ready_meta:
                    m = analyze_top_wave(raw_p, bits, "c2")
                    m.update(tag=case_tag, corner=c.tag, n_zq=n_zq, n_post=n_post, raw=str(raw_p.relative_to(ROOT)))
                    summary["c2_top"][case_tag] = m
                    rspr = f"{m['rem_spread_ui']:8.4f}" if m["rem_spread_ui"] is not None else "    None"
                    print(
                        f"{case_tag:<24} {n_post:3d} {m['pad_pp_mv']:7.1f} {m['rem_pp_mv']:7.1f} "
                        f"{m['rem_margin_mv']:8.1f} {m['rem_eye_h_mv']:8.1f} {m['rem_eye_w_ui']:8.3f} "
                        f"{rspr} {m['power_mw']:8.2f}",
                        flush=True,
                    )
                summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    # Print aggregate rollup
    rows = list(summary["pvt45"].values())
    if rows:
        n_pass = sum(1 for r in rows if r["pad_meets_spec"])
        print(f"\n=== 45-Corner Summary ({n_pass}/{len(rows)} PASS) ===", flush=True)
        print(f"  Pad margin (mV): min={min(r['pad_margin_mv'] for r in rows):.1f}, max={max(r['pad_margin_mv'] for r in rows):.1f}", flush=True)
        print(f"  Pad spread (UI): min={min(r['pad_spread_ui'] for r in rows):.4f}, max={max(r['pad_spread_ui'] for r in rows):.4f}", flush=True)
        print(f"  Pad swing (mVpp): min={min(r['pad_pp_mv'] for r in rows):.1f}, max={max(r['pad_pp_mv'] for r in rows):.1f}", flush=True)
        print(f"  Total TX Power (mW): min={min(r['power_mw'] for r in rows):.2f}, max={max(r['power_mw'] for r in rows):.2f}", flush=True)
        if "tt_v1800_t27" in summary["pvt45"]:
            tt = summary["pvt45"]["tt_v1800_t27"]
            print(f"  TT 1.80V 27C: margin={tt['pad_margin_mv']:.1f} mV, spread={tt['pad_spread_ui']:.4f} UI, power={tt['power_mw']:.2f} mW ({tt['pj_per_bit']:.2f} pJ/bit)", flush=True)
    print(f"Saved: {summary_path}", flush=True)


if __name__ == "__main__":
    main()
