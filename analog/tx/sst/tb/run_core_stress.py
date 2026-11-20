"""Stage 1 Core Proof: Quarter-Rate 4-Phase 1 GHz Fused 4:1 N-over-N SST Driver + 2-Tap FFE + LDO.

Runs with MAX 2 concurrent ngspice workers (--workers 2, default 2), binary raw output,
skip_output_before, and num_threads=1.

Suites:
  1. 6-corner PVT+RC core stress (matched diff_rlc16 channel, FFE=0, ZQ-calibrated 50 ohm):
     tt_v1800_t27, ss_hh_v1650_t-40, ss_hh_v1650_t85, fs_hh_v1650_t85, sf_ll_v1650_t-40, ff_ll_v1950_t-40.
     Measures: pad diff swing (mVpp), training-locked signed eye margin (mV), edge spread (UI),
     DC R_out (R_pu/R_pd), S11 return loss (DC/1G/2G), V_drv mean & ripple, total core power (mW & pJ/bit).
  2. Real C2_loss6 (6 dB @ 2 GHz) PCB channel FFE sweep (FFE=0 vs FFE=2 vs FFE=3 post-cursor slices)
     at TT, SS/hh/1.65V/85C, and FS/hh/1.65V/85C.
  3. Quadrature clock IQ skew sensitivity (0, +5, +10, +15 ps on phi90/phi270) at TT and FS/hh/1.65V/85C.

Usage:
  uv run python analog/tx/sst/tb/run_core_stress.py [--workers 2] [--suite all|stress|c2|skew|cal]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import eye, project, serial, spice

ROOT = project.ROOT
RESULTS = ROOT / "results/analog/tx/sst"
UI = 250e-12
T_CLK_PERIOD = 4 * UI  # 1.0 ns (1 GHz quadrature clocks)
T0 = 4.0e-9            # start of bit 0 (after 4 ns LDO/AC settle)
PAYLOAD_BITS = 128     # 64 training + 128 PRBS-7 payload = 192 bits (+8 tail)
TOTAL_BITS = serial.TRAINING_BITS + PAYLOAD_BITS + 8

STRESS_CORNERS = [
    ("tt",    1.80,  27, 16),
    ("ss_hh", 1.65, -40, 18),
    ("ss_hh", 1.65,  85, 22),
    ("fs_hh", 1.65,  85, 22),
    ("sf_ll", 1.65, -40, 13),
    ("ff_ll", 1.95, -40, 12),
]


def build_sequence() -> np.ndarray:
    """64-bit repo-compatible training (32 alternating + 32 marker) + 128 PRBS-7 payload + 8 tail."""
    alt = [i & 1 for i in range(32)]
    # 32-bit marker (same hex words 0xd3a5, 0x6c9e as repo serializer_expected.json, LSB-first or MSB-first)
    marker_words = (0xD3A5, 0x6C9E)
    marker = [(w >> b) & 1 for w in marker_words for b in range(16)]
    payload = eye.prbs7(PAYLOAD_BITS + 8, seed=0x5D)
    return np.array(alt + marker + payload, dtype=int)


def encode_zq_ffe(n_zq: int, n_post: int) -> dict[str, int]:
    """Encode n_main = n_zq - n_post into 5 bits (1,2,4,8,8) and n_post into 3 bits (1,2,2)."""
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


def staggered_4ph_stimuli(bits: np.ndarray, supply: float, t0: float = T0, edge: float = 35e-12) -> str:
    """Generate phase-staggered 1 Gb/s differential data streams (d0..d3, db0..db3).

    For bit index n = 4*m + k (slot k active during [t0 + n*UI, t0 + (n+1)*UI)):
      d_k updates 250 ps (1 UI) BEFORE its active slot, at t_upd = t0 + (n - 1)*UI,
      and holds for 1000 ps (4 UI), covering BOTH slot k (Main) and slot (k+1)%4 (Post-1)!
    Before t0 - 1 ns, all lanes stay DC-balanced alternating (0,1,0,1) so AC coupling caps
    start with zero DC differential offset!
    """
    lines = []
    n_cyc = len(bits) // 4
    # Pre-sequence DC-balanced alternating 1-UI bits: d0=0, d1=1, d2=0, d3=1 -> mean 0 V diff!
    init_val = [0, 1, 0, 1]
    for k in range(4):
        pts_p = [(0.0, supply if init_val[k] else 0.0)]
        pts_n = [(0.0, 0.0 if init_val[k] else supply)]
        prev = init_val[k]
        for m in range(n_cyc):
            b = int(bits[4 * m + k])
            if b != prev:
                t_upd = t0 + (4 * m + k - 1) * UI
                vp0, vp1 = (supply if prev else 0.0), (supply if b else 0.0)
                vn0, vn1 = (0.0 if prev else supply), (0.0 if b else supply)
                pts_p.extend([(t_upd - edge / 2, vp0), (t_upd + edge / 2, vp1)])
                pts_n.extend([(t_upd - edge / 2, vn0), (t_upd + edge / 2, vn1)])
                prev = b
        lines.append(pwl_lines(f"Vd{k} d{k} 0", pts_p))
        lines.append(pwl_lines(f"Vdb{k} db{k} 0", pts_n))
    return "".join(lines)


def build_core_deck(
    *,
    corner: str,
    supply: float,
    temp_c: int,
    n_zq: int,
    n_post: int,
    channel: str,
    iq_skew_s: float = 0.0,
    stim_file: str = "stimuli.inc",
) -> str:
    bits_ctrl = encode_zq_ffe(n_zq, n_post)
    # Ramp enabled slice controls from 0 -> vdd at t=0.5ns (like legacy TX Vtxen) so pads start
    # balanced at Vcm=0.22V (0 mV initial differential DC offset across 10 nF AC-coupling caps!)
    ctrl_lines = "\n".join(
        f"Vctrl_{k} {k} 0 PWL(0 0 0.5e-9 0 0.6e-9 {{vdd_v}})" if v else f"Vctrl_{k} {k} 0 0.0"
        for k, v in bits_ctrl.items()
    )
    if channel == "rlc16":
        ch_inc = f'.include "{ROOT}/verification/models/channel/diff_rlc16.spice"'
        ch_inst = "Xchannel ltp ltn lxp lxn 0 serdes_diff_rlc16"
        t_stop = T0 + TOTAL_BITS * UI + 2.0e-9
    elif channel == "c2":
        ch_inc = (
            f'.include "{ROOT}/verification/models/channel/pcb_family/pcb_foster_cells.spice"\n'
            f'.include "{ROOT}/verification/models/channel/pcb_family/C2_loss6.spice"'
        )
        ch_inst = "Xchannel ltp ltn lxp lxn 0 pcb_c2_loss6"
        t_stop = T0 + TOTAL_BITS * UI + 4.0e-9
    else:
        raise ValueError(f"Unknown channel: {channel}")

    # 1 GHz quadrature clocks (T=1000 ps, 50% duty, tr=tf=30 ps -> pw=470 ps)
    # Valid Slot-0 state at t=0: phi0=1, phi90=0, phi180=0, phi270=1 (no DC op TG contention!)
    # Slot 0 [k+0..k+250ps]:   phi0=1, phi90=0, phi180=0, phi270=1
    # Slot 1 [k+250..k+500ps]: phi0=1, phi90=1, phi180=0, phi270=0
    # Slot 2 [k+500..k+750ps]: phi0=0, phi90=1, phi180=1, phi270=0
    # Slot 3 [k+750..k+1000ps]:phi0=0, phi90=0, phi180=1, phi270=1
    tr = 30e-12
    pw = 0.5 * T_CLK_PERIOD - tr  # 470 ps -> exact 50% duty at mid-swing!
    tf0 = 0.50 * T_CLK_PERIOD - tr / 2
    tr90 = 0.25 * T_CLK_PERIOD - tr / 2 + iq_skew_s
    tr180 = 0.50 * T_CLK_PERIOD - tr / 2
    tf270 = 0.25 * T_CLK_PERIOD - tr / 2 + iq_skew_s

    deck = f"""* TX SST Quarter-Rate 4:1 Core Stress ({corner}, {supply}V, {temp_c}C, Nzq={n_zq}, FFE={n_post}, ch={channel}, skew={iq_skew_s*1e12:.1f}ps)
.lib "{project.model_library()}" {corner}
.include "{ROOT}/analog/common/devices/spice/sky130_primitives.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_driver.spice"
{ch_inc}

.param vdd_v={supply}
Vdd vdd 0 {{vdd_v}}
Vbg vbg 0 1.20

* 4-phase 1 GHz quadrature clocks (50% duty, valid Slot-0 state at t=0, optional IQ skew on phi90/phi270)
Vphi0   phi0   0 PULSE({{vdd_v}} 0 {tf0:.6e}   {tr:.3e} {tr:.3e} {pw:.6e} {T_CLK_PERIOD:.6e})
Vphi90  phi90  0 PULSE(0 {{vdd_v}} {tr90:.6e}  {tr:.3e} {tr:.3e} {pw:.6e} {T_CLK_PERIOD:.6e})
Vphi180 phi180 0 PULSE(0 {{vdd_v}} {tr180:.6e} {tr:.3e} {tr:.3e} {pw:.6e} {T_CLK_PERIOD:.6e})
Vphi270 phi270 0 PULSE({{vdd_v}} 0 {tf270:.6e} {tr:.3e} {tr:.3e} {pw:.6e} {T_CLK_PERIOD:.6e})

* Static ZQ & FFE slice enables
{ctrl_lines}

* Staggered 1 Gb/s 4-phase PRBS-7 stimuli
.include "{stim_file}"

* DUT: Quarter-Rate 4:1 Fused N-over-N SST Driver + 2-Tap FFE + On-Chip Vdrv LDO
Xdut d0 d1 d2 d3 db0 db1 db2 db3 phi0 phi90 phi180 phi270
+ m0 m1 m2 m3 m4 f0 f1 f2 ffe_en vbg lqp lqn vdrv vdd 0 serdes_tx_sst_driver

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

.nodeset v(vdrv)=0.44 v(lqp)=0.22 v(lqn)=0.22 v(xdut.xldo.vgate)=1.0
.temp {temp_c}
.options reltol=2e-4 abstol=1p vntol=2u klu
.save v(lqp) v(lqn) v(lrp) v(lrn) v(vdrv) v(vdd) i(Vdd)
.control
set num_threads=1
tran 4p {t_stop:.6e} 0 5p
let pad = v(lqp) - v(lqn)
let remote = v(lrp) - v(lrn)
let pad_cm = 0.5 * (v(lqp) + v(lqn))
let vdrv_v = v(vdrv)
let power = -v(vdd) * i(Vdd)
wrdata waveforms.tsv pad remote pad_cm vdrv_v power
quit
.endc
.end
"""
    deck = spice.skip_output_before(deck, "2.0e-9")
    deck = spice.binary_output(deck)
    return deck, t_stop


def build_rout_s11_deck(corner: str, supply: float, temp_c: int, n_zq: int, n_post: int = 0) -> str:
    """Fast DC Rout + AC S11 (DC, 1 GHz, 2 GHz) verification of the full ZQ-calibrated SST driver."""
    bits_ctrl = encode_zq_ffe(n_zq, n_post)
    ctrl_lines = "\n".join(
        f"Vctrl_{k} {k} 0 {supply if v else 0.0}" for k, v in bits_ctrl.items()
    )
    # Static slot-0 active: phi0=1, phi270=1, phi90=0, phi180=0; d0=1, db0=0 -> pad_p pulled HIGH, pad_n pulled LOW
    return f"""* SST Full-Driver Rout & S11 Return Loss Check ({corner}, {supply}V, {temp_c}C, Nzq={n_zq})
.lib "{project.model_library()}" {corner}
.include "{ROOT}/analog/common/devices/spice/sky130_primitives.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_driver.spice"

.param vdd_v={supply}
Vdd vdd 0 {{vdd_v}}
Vbg vbg 0 1.20
Vphi0   phi0   0 {{vdd_v}}
Vphi90  phi90  0 0
Vphi180 phi180 0 0
Vphi270 phi270 0 {{vdd_v}}
Vd0  d0  0 {{vdd_v}}
Vd1  d1  0 0
Vd2  d2  0 0
Vd3  d3  0 0
Vdb0 db0 0 0
Vdb1 db1 0 {{vdd_v}}
Vdb2 db2 0 {{vdd_v}}
Vdb3 db3 0 {{vdd_v}}
{ctrl_lines}

Xdut d0 d1 d2 d3 db0 db1 db2 db3 phi0 phi90 phi180 phi270
+ m0 m1 m2 m3 m4 f0 f1 f2 ffe_en vbg lqp lqn vdrv vdd 0 serdes_tx_sst_driver

* Pad cap (200 fF) included for realistic high-frequency S11
Clpp lqp 0 200f
Clpn lqn 0 200f
* AC test source driving pad_p at its DC operating voltage (~0.33 V) & pad_n (~0.11 V) via 100 ohm diff / 50 ohm SE
Vtest_p lqp 0 DC 0.33 AC 1
Vtest_n lqn 0 DC 0.11 AC 0

.nodeset v(vdrv)=0.44 v(lqp)=0.22 v(lqn)=0.22 v(xdut.xldo.vgate)=1.0
.temp {temp_c}
.options reltol=1e-4 abstol=1p vntol=1u klu
.control
set num_threads=1
op
let vdrv_dc = v(vdrv)
let r_pu_dc = (v(vdrv) - 0.33) / i(Vtest_p)
let r_pd_dc = (0.11 - 0.00) / (-i(Vtest_n))
echo ZQ_DC corner={corner} vdd={supply} temp={temp_c} n_zq={n_zq} vdrv=$&vdrv_dc r_pu=$&r_pu_dc r_pd=$&r_pd_dc
ac dec 20 1e6 4e9
let zout = -1 / i(Vtest_p)
let gamma = (zout - 50) / (zout + 50)
let s11_db = 20 * log10(mag(gamma))
let rl_dc = -s11_db[0]
meas ac rl_1g find s11_db at=1e9
meas ac rl_2g find s11_db at=2e9
echo ZQ_AC rl_dc=$&rl_dc s11_1g_db=$&rl_1g s11_2g_db=$&rl_2g
quit
.endc
.end
"""


def parse_zq_log(log_path: Path) -> dict:
    out = {}
    for line in log_path.read_text(errors="replace").splitlines():
        if line.startswith(("ZQ_DC ", "ZQ_AC ")):
            for tok in line.split()[1:]:
                k, v = tok.split("=", 1)
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    return out


def analyze_wave(raw_path: Path, bits: np.ndarray, channel: str) -> dict:
    w = spice.Waves(raw_path)
    seq = serial.Sequence(bits=bits, start_s=T0, ui_s=UI)
    pad_m, _ = serial.check(w.t, w["pad"], seq, PAYLOAD_BITS)
    rem_m, _ = serial.check(w.t, w["remote"], seq, PAYLOAD_BITS)
    pad_eye = eye.signed_eye(w.t, w["pad"], bits.tolist(), UI, T0, first_bit=serial.TRAINING_BITS, n_bits=PAYLOAD_BITS)
    rem_eye = eye.signed_eye(w.t, w["remote"], bits.tolist(), UI, T0, first_bit=serial.TRAINING_BITS, n_bits=PAYLOAD_BITS)

    # Power & Vdrv stats over active payload window
    t_win = (w.t >= T0 + serial.TRAINING_BITS * UI) & (w.t <= T0 + (serial.TRAINING_BITS + PAYLOAD_BITS) * UI)
    pwr_w = float(np.trapezoid(w["power"][t_win], w.t[t_win]) / (w.t[t_win][-1] - w.t[t_win][0]))
    vdrv_seg = w["vdrv_v"][t_win]
    vdrv_mean = float(np.mean(vdrv_seg))
    vdrv_pp_mv = float(np.ptp(vdrv_seg) * 1e3)
    pad_cm_mv = float(np.mean(w["pad_cm"][t_win]) * 1e3)
    return dict(
        channel=channel,
        pad_functional=pad_m["functional"],
        pad_errors=pad_m["bit_errors"],
        pad_pp_mv=pad_m["differential_pp_v"] * 1e3,
        pad_margin_mv=pad_m["minimum_signed_margin_v"] * 1e3,
        pad_eye_h_mv=pad_eye["height_v"] * 1e3,
        pad_eye_w_ui=pad_eye["width_ui"],
        pad_spread_ui=pad_m["transition_spread_ui"],
        pad_meets_spec=serial.meets_draft(pad_m),
        rem_functional=rem_m["functional"],
        rem_errors=rem_m["bit_errors"],
        rem_pp_mv=rem_m["differential_pp_v"] * 1e3,
        rem_margin_mv=rem_m["minimum_signed_margin_v"] * 1e3,
        rem_eye_h_mv=rem_eye["height_v"] * 1e3,
        rem_eye_w_ui=rem_eye["width_ui"],
        rem_spread_ui=rem_m["transition_spread_ui"],
        power_mw=pwr_w * 1e3,
        pj_per_bit=pwr_w * 1e3 / 4.0,  # mW / (Gb/s) = pJ/bit
        vdrv_mean_v=vdrv_mean,
        vdrv_ripple_mvpp=vdrv_pp_mv,
        pad_cm_mv=pad_cm_mv,
    )


def run_or_resume_cases(camp: Path, specs: list[dict], workers: int, smoke: bool = False) -> dict[str, Path]:
    """Case-level resumable runner using spice.case_output + spice.next_run_dir."""
    done: dict[str, Path] = {}
    todo_jobs = []
    todo_tags = []
    for sp in specs:
        tag = sp["tag"]
        existing = spice.case_output(camp, tag, "waveforms.raw", t_end=sp["t_end"])
        if existing is not None:
            done[tag] = existing
            continue
        rdir = spice.next_run_dir(camp, tag)
        todo_jobs.append((sp["deck"], rdir, {"files": sp["files"], "timeout_s": sp["timeout_s"]}))
        todo_tags.append((tag, sp["t_end"]))
    if todo_jobs:
        execs = spice.run_many(todo_jobs, workers=workers, smoke=smoke)
        for ex, (tag, t_end) in zip(execs, todo_tags):
            if ex.ok:
                found = spice.case_output(camp, tag, "waveforms.raw", t_end=t_end)
                if found is not None:
                    done[tag] = found
                else:
                    print(f"WARN {tag}: waveforms incomplete/truncated")
            else:
                print(f"FAIL {tag}: {ex.log_failures}")
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3, help="Max concurrent ngspice (cap <= 3)")
    ap.add_argument("--suite", choices=["all", "stress", "c2", "skew", "zq"], default="all")
    ap.add_argument("--resume", type=Path, default=None, help="Existing campaign dir to resume")
    args = ap.parse_args()
    workers = min(args.workers, 3)

    bits = build_sequence()
    if args.resume is not None:
        camp = args.resume.resolve()
        run_id = camp.name
        camp.mkdir(parents=True, exist_ok=True)
    else:
        run_id = time.strftime("%Y%m%dT%H%M%SZ_core_stage1", time.gmtime())
        camp = RESULTS / run_id
        camp.mkdir(parents=True, exist_ok=True)
    (camp / "bits.json").write_text(json.dumps(bits.tolist()))

    summary_path = camp / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {
        "run_id": run_id, "workers": workers, "zq": [], "stress_rlc16": [], "c2_ffe": [], "iq_skew": []
    }

    # --- 0. ZQ Rout & S11 Check across 6 corners ---
    if args.suite in ("all", "zq", "stress"):
        zq_jobs, zq_tags = [], []
        for corner, vdd, temp_c, n_zq in STRESS_CORNERS:
            tag = f"zq_{corner}_v{round(vdd*1000)}_t{temp_c}"
            log_p = camp / tag / "simulator.log"
            if log_p.exists() and "ZQ_AC " in log_p.read_text(errors="replace"):
                zq_tags.append((tag, log_p))
                continue
            rdir = spice.next_run_dir(camp, tag)
            zq_jobs.append((build_rout_s11_deck(corner, vdd, temp_c, n_zq), rdir, {"timeout_s": 120}))
            zq_tags.append((tag, rdir / "simulator.log"))
        print(f"\n=== [0/3] ZQ Impedance & S11 Verification ({len(STRESS_CORNERS)} corners, {len(zq_jobs)} new, workers={workers}) ===")
        if zq_jobs:
            spice.run_many(zq_jobs, workers=workers, smoke=False)
        summary["zq"] = []
        print(f"{'Corner':<18} {'Nzq':>4} {'Vdrv(V)':>8} {'R_pu':>7} {'R_pd':>7} {'R_avg':>7} {'S11_1G(dB)':>11} {'S11_2G(dB)':>11}")
        for tag, log_p in zq_tags:
            if not log_p.exists():
                print(f"FAIL {tag}: missing log")
                continue
            r = parse_zq_log(log_p)
            if "r_pu" not in r:
                print(f"FAIL {tag}: ZQ_DC/AC missing")
                continue
            r["r_avg"] = 0.5 * (r["r_pu"] + r["r_pd"])
            summary["zq"].append(r)
            print(f"{r['corner']}_v{int(r['vdd']*1000)}_t{int(r['temp']):<4} "
                  f"{int(r['n_zq']):4d} {r['vdrv']:8.4f} {r['r_pu']:7.2f} {r['r_pd']:7.2f} "
                  f"{r['r_avg']:7.2f} {r['s11_1g_db']:11.2f} {r['s11_2g_db']:11.2f}")

    # --- 1. 6-Corner Core Stress (Matched RLC16, FFE=0) ---
    if args.suite in ("all", "stress"):
        specs, meta_list = [], []
        for corner, vdd, temp_c, n_zq in STRESS_CORNERS:
            tag = f"stress_{corner}_v{round(vdd*1000)}_t{temp_c}"
            stim_path = camp / f"stim_{round(vdd*1000)}.inc"
            if not stim_path.exists():
                stim_path.write_text(staggered_4ph_stimuli(bits, vdd))
            deck, t_stop = build_core_deck(corner=corner, supply=vdd, temp_c=temp_c, n_zq=n_zq, n_post=0, channel="rlc16")
            specs.append(dict(tag=tag, deck=deck, t_end=t_stop, files={"stimuli.inc": stim_path}, timeout_s=600))
            meta_list.append((tag, corner, vdd, temp_c, n_zq))
        print(f"\n=== [1/3] 6-Corner Core Stress (RLC16, 192 bits, FFE=0, workers={workers}) ===")
        done = run_or_resume_cases(camp, specs, workers=workers, smoke=True)
        summary["stress_rlc16"] = []
        print(f"{'Corner':<18} {'PadPP':>7} {'Margin':>8} {'Spread':>8} {'Vdrv':>7} {'RipmV':>6} {'Pwr(mW)':>8} {'pJ/b':>6} {'Spec':>5}")
        for tag, corner, vdd, temp_c, n_zq in meta_list:
            if tag not in done:
                continue
            m = analyze_wave(done[tag], bits, "rlc16")
            ex_p = done[tag].parent / "execution.json"
            el = json.loads(ex_p.read_text()).get("elapsed_s", 0.0) if ex_p.exists() else 0.0
            m.update(tag=tag, corner=corner, supply=vdd, temp_c=temp_c, n_zq=n_zq, n_post=0, elapsed_s=el)
            summary["stress_rlc16"].append(m)
            print(f"{corner}_v{int(vdd*1000)}_t{temp_c:<4} "
                  f"{m['pad_pp_mv']:7.1f} {m['pad_margin_mv']:8.1f} {m['pad_spread_ui']:8.4f} "
                  f"{m['vdrv_mean_v']:7.4f} {m['vdrv_ripple_mvpp']:6.2f} {m['power_mw']:8.2f} {m['pj_per_bit']:6.2f} "
                  f"{'PASS' if m['pad_meets_spec'] else 'FAIL':>5}")
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    # --- 2. C2_loss6 (6 dB @ 2 GHz) PCB Channel FFE Comparison ---
    if args.suite in ("all", "c2"):
        c2_cases = [
            ("tt",    1.80, 27, 16, 0),
            ("tt",    1.80, 27, 16, 2),
            ("tt",    1.80, 27, 16, 3),
            ("fs_hh", 1.65, 85, 22, 0),
            ("fs_hh", 1.65, 85, 22, 3),
            ("ss_hh", 1.65, 85, 22, 0),
            ("ss_hh", 1.65, 85, 22, 3),
        ]
        specs, meta_list = [], []
        for corner, vdd, temp_c, n_zq, n_post in c2_cases:
            tag = f"c2_{corner}_v{round(vdd*1000)}_t{temp_c}_ffe{n_post}"
            stim_path = camp / f"stim_{round(vdd*1000)}.inc"
            if not stim_path.exists():
                stim_path.write_text(staggered_4ph_stimuli(bits, vdd))
            deck, t_stop = build_core_deck(corner=corner, supply=vdd, temp_c=temp_c, n_zq=n_zq, n_post=n_post, channel="c2")
            specs.append(dict(tag=tag, deck=deck, t_end=t_stop, files={"stimuli.inc": stim_path}, timeout_s=900))
            meta_list.append((tag, corner, vdd, temp_c, n_zq, n_post))
        print(f"\n=== [2/3] Real C2_loss6 PCB Channel FFE Comparison ({len(specs)} runs, workers={workers}) ===")
        done = run_or_resume_cases(camp, specs, workers=workers, smoke=False)
        summary["c2_ffe"] = []
        print(f"{'Case':<26} {'FFE':>3} {'PadPP':>7} {'C2_PP':>7} {'C2_Marg':>8} {'C2_EyeH':>8} {'C2_EyeW':>8} {'C2_Sprd':>8} {'Pwr':>6}")
        for tag, corner, vdd, temp_c, n_zq, n_post in meta_list:
            if tag not in done:
                continue
            m = analyze_wave(done[tag], bits, "c2")
            ex_p = done[tag].parent / "execution.json"
            el = json.loads(ex_p.read_text()).get("elapsed_s", 0.0) if ex_p.exists() else 0.0
            m.update(tag=tag, corner=corner, supply=vdd, temp_c=temp_c, n_zq=n_zq, n_post=n_post, elapsed_s=el)
            summary["c2_ffe"].append(m)
            spr_s = f"{m['rem_spread_ui']:8.4f}" if m["rem_spread_ui"] is not None else "    None"
            print(f"{corner}_v{int(vdd*1000)}_t{temp_c:<4}       "
                  f"{n_post:3d} {m['pad_pp_mv']:7.1f} {m['rem_pp_mv']:7.1f} {m['rem_margin_mv']:8.1f} "
                  f"{m['rem_eye_h_mv']:8.1f} {m['rem_eye_w_ui']:8.3f} {spr_s} {m['power_mw']:6.2f}")
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    # --- 3. Quadrature Clock IQ Skew Sensitivity ---
    if args.suite in ("all", "skew"):
        skew_cases = [
            ("tt",    1.80, 27, 16,  5e-12),
            ("tt",    1.80, 27, 16, 10e-12),
            ("tt",    1.80, 27, 16, 15e-12),
            ("fs_hh", 1.65, 85, 22,  5e-12),
            ("fs_hh", 1.65, 85, 22, 10e-12),
        ]
        specs, meta_list = [], []
        for corner, vdd, temp_c, n_zq, skew_s in skew_cases:
            tag = f"skew_{corner}_v{round(vdd*1000)}_t{temp_c}_iq{int(round(skew_s*1e12))}ps"
            stim_path = camp / f"stim_{round(vdd*1000)}.inc"
            if not stim_path.exists():
                stim_path.write_text(staggered_4ph_stimuli(bits, vdd))
            deck, t_stop = build_core_deck(corner=corner, supply=vdd, temp_c=temp_c, n_zq=n_zq, n_post=0, channel="rlc16", iq_skew_s=skew_s)
            specs.append(dict(tag=tag, deck=deck, t_end=t_stop, files={"stimuli.inc": stim_path}, timeout_s=600))
            meta_list.append((tag, corner, vdd, temp_c, n_zq, skew_s))
        print(f"\n=== [3/3] Quadrature Clock IQ Skew Sensitivity ({len(specs)} runs, workers={workers}) ===")
        done = run_or_resume_cases(camp, specs, workers=workers, smoke=False)
        summary["iq_skew"] = []
        print(f"{'Corner':<18} {'IQ_ps':>6} {'PadPP':>7} {'Margin':>8} {'Spread(UI)':>10} {'Spec':>5}")
        for tag, corner, vdd, temp_c, n_zq, skew_s in meta_list:
            if tag not in done:
                continue
            m = analyze_wave(done[tag], bits, "rlc16")
            ex_p = done[tag].parent / "execution.json"
            el = json.loads(ex_p.read_text()).get("elapsed_s", 0.0) if ex_p.exists() else 0.0
            m.update(tag=tag, corner=corner, supply=vdd, temp_c=temp_c, n_zq=n_zq, iq_skew_ps=skew_s * 1e12, elapsed_s=el)
            summary["iq_skew"].append(m)
            print(f"{corner}_v{int(vdd*1000)}_t{temp_c:<4} {skew_s*1e12:6.1f} "
                  f"{m['pad_pp_mv']:7.1f} {m['pad_margin_mv']:8.1f} {m['pad_spread_ui']:10.4f} "
                  f"{'PASS' if m['pad_meets_spec'] else 'FAIL':>5}")

    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nStage 1 summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
