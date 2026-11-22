"""Post-Layout CPEX & Native Magic RCX Electrical Signoff for TX v4.2 Zero-CML SST PDK Layout.

Verifies `serdes_tx_sst_driver_pdk` and `serdes_tx_sst_top_pdk` (v4.2, 231.50 x 146.98 um)
against the exact schematic baseline (`run_core_stress.py` & `run_pvt45.py`).

Hard constraints enforced:
- MAX 2 concurrent ngspice workers (`--workers <= 2`, `num_threads=1`)
- `spice.binary_output`, `spice.skip_output_before`
- Case-level resume via `spice.case_output(..., t_end=t_stop)` and `spice.next_run_dir`
- Does not touch schematic SPICE, layout, or config files.

Stages:
  1. Driver ZQ 50 ohm & S11 @ 2 GHz (`serdes_tx_sst_driver_pdk_pex.spice` & `_rcx.spice`)
     across 6 extreme MOSxRC corners (`tt`, `ss_hh -40`, `ss_hh 85`, `fs_hh 85`, `sf_ll -40`, `ff_ll -40`).
  2. Full 16:1 Top Post-Layout CPEX (`serdes_tx_sst_top_pdk_pex.spice`):
     - 6 extreme PVT corners (`tt_v1800_t27`, `ss_v1650_t-40`, `ss_v1650_t85`,
       `fs_v1650_t-40`, `fs_v1650_t85`, `ff_v1950_t-40`) over matched RLC16 (`FFE=0`).
     - 2 corners over `C2_loss6` PCB channel (`FFE=3`): `tt_v1800_t27`, `ss_v1650_t-40`.
  3. Full 16:1 Top Native Magic RCX Spot-Check (`serdes_tx_sst_top_pdk_rcx.spice`):
     - 2 corners (`tt_v1800_t27`, `ss_v1650_t-40`) over matched RLC16 (`FFE=0`).

Usage:
  uv run python analog/tx/sst/tb/postlayout/verify_tx_v4_pex.py --stage all --workers 2
  uv run python analog/tx/sst/tb/postlayout/verify_tx_v4_pex.py --stage 1 --workers 2
  uv run python analog/tx/sst/tb/postlayout/verify_tx_v4_pex.py --stage 2 --workers 2
  uv run python analog/tx/sst/tb/postlayout/verify_tx_v4_pex.py --stage 3 --workers 2
  uv run python analog/tx/sst/tb/postlayout/verify_tx_v4_pex.py --smoke-only
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import threading
import time
from pathlib import Path

import numpy as np

from serdes_flow import eye, project, serial, spice

ROOT = project.ROOT
DEFAULT_OUT = ROOT / "results/analog/tx/sst/postlayout_v4_2"

DRIVER_PEX = ROOT / "results/layout/tx_sst_v4/review/serdes_tx_sst_driver_pdk/serdes_tx_sst_driver_pdk_pex.spice"
DRIVER_RCX = ROOT / "results/layout/tx_sst_v4/review/serdes_tx_sst_driver_pdk/serdes_tx_sst_driver_pdk_rcx.spice"
TOP_PEX = ROOT / "results/layout/tx_sst_v4/review/serdes_tx_sst_top_pdk/serdes_tx_sst_top_pdk_pex.spice"
TOP_RCX = ROOT / "results/layout/tx_sst_v4/review/serdes_tx_sst_top_pdk/serdes_tx_sst_top_pdk_rcx.spice"
TOP_RC_SUMMARY = ROOT / "results/layout/tx_sst_v4/review/serdes_tx_sst_top_pdk/rc_summary.json"

SCHEM_STAGE1_SUMMARY = ROOT / "results/analog/tx/sst/20261120T155335Z_core_stage1/summary.json"
SCHEM_STAGE2_SUMMARY = ROOT / "results/analog/tx/sst/20261120T163338Z_top16_pvt45/summary.json"

# Exact timing/sequence constants matching analog/tx/sst/tb/run_pvt45.py
UI = 250e-12
T_CLK = 4 * UI       # 1.0 ns (1 GHz quadrature clocks)
T_WORD = 16 * UI     # 4.0 ns (250 MHz 16-bit parallel words)
PAYLOAD_BITS = 128   # 64 training + 128 PRBS-7 + 16 tail = 208 bits = 13 words
TAIL_BITS = 16
TOTAL_BITS = serial.TRAINING_BITS + PAYLOAD_BITS + TAIL_BITS
T_RST_REL = 1.45e-9
T_FIRST_UPD = 4.0e-9
T_PAD_START = 9.0e-9

# Stage 1: 6 extreme MOSxRC corners (matching run_core_stress.py)
STAGE1_CORNERS = [
    ("tt",    1.80,  27, 16),
    ("ss_hh", 1.65, -40, 18),
    ("ss_hh", 1.65,  85, 22),
    ("fs_hh", 1.65,  85, 22),
    ("sf_ll", 1.65, -40, 13),
    ("ff_ll", 1.95, -40, 12),
]

# Stage 2: 6 extreme PVT corners for full 16:1 Top CPEX (matching zq_cal_45.json)
STAGE2_PVT_CORNERS = [
    ("tt_v1800_t27",   "tt", 1.80,  27, 16),
    ("ss_v1650_t-40",  "ss", 1.65, -40, 17),
    ("ss_v1650_t85",   "ss", 1.65,  85, 20),
    ("fs_v1650_t-40",  "fs", 1.65, -40, 17),
    ("fs_v1650_t85",   "fs", 1.65,  85, 20),
    ("ff_v1950_t-40",  "ff", 1.95, -40, 14),
]

# Stage 2b: 2 C2_loss6 PCB channel FFE=3 corners
STAGE2_C2_CORNERS = [
    ("tt_v1800_t27",   "tt", 1.80,  27, 16, 3),
    ("ss_v1650_t-40",  "ss", 1.65, -40, 17, 3),
]

# Stage 3: 2 Native Magic RCX spot-check corners
STAGE3_RCX_CORNERS = [
    ("tt_v1800_t27",   "tt", 1.80,  27, 16),
    ("ss_v1650_t-40",  "ss", 1.65, -40, 17),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
    """Generate 16 parallel 250 MHz word inputs din0..din15 (exact match to run_pvt45.py)."""
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


def build_driver_zq_s11_deck(
    *,
    netlist: Path,
    subckt: str,
    corner: str,
    supply: float,
    temp_c: int,
    n_zq: int,
    n_post: int = 0,
    ext_pad_cap_f: float = 200e-15,
) -> str:
    """DC Rout + AC S11 (DC, 1 GHz, 2 GHz) on extracted serdes_tx_sst_driver_pdk.

    Includes external 200 fF pad/ESD cap (`Clpp`/`Clpn`) on top of extracted layout cap
    (`46.53 / 42.86 fF`) for exact apples-to-apples comparison with schematic Stage 1.
    """
    bits_ctrl = encode_zq_ffe(n_zq, n_post)
    ctrl_lines = "\n".join(
        f"Vctrl_{k} {k} 0 {supply if v else 0.0}" for k, v in bits_ctrl.items()
    )
    cap_line = (
        f"Clpp lqp 0 {ext_pad_cap_f:.6e}\nClpn lqn 0 {ext_pad_cap_f:.6e}"
        if ext_pad_cap_f > 0
        else "* No external pad cap (extracted layout cap only)"
    )
    is_rcx = "_rcx" in netlist.name
    opt_extra = " noopiter" if is_rcx else ""
    return f"""* Post-Layout SST Driver Rout & S11 Check ({subckt}, {corner}, {supply}V, {temp_c}C, Nzq={n_zq})
.lib "{project.model_library()}" {corner}
.include "{netlist}"

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
+ m0 m1 m2 m3 m4 f0 f1 f2 ffe_en vbg lqp lqn vdrv vdd 0 {subckt}

* External pad/ESD cap (200 fF, identical to schematic bench) + real extracted layout pad cap
{cap_line}
Vtest_p lqp 0 DC 0.33 AC 1
Vtest_n lqn 0 DC 0.11 AC 0

.nodeset v(vdrv)=0.44 v(lqp)=0.22 v(lqn)=0.22
.temp {temp_c}
.options reltol=1e-4 abstol=1p vntol=1u klu{opt_extra}
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
    out: dict = {}
    for line in log_path.read_text(errors="replace").splitlines():
        if line.startswith(("ZQ_DC ", "ZQ_AC ")):
            for tok in line.split()[1:]:
                k, v = tok.split("=", 1)
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    return out


def build_top_postlayout_deck(
    *,
    netlist: Path,
    subckt: str,
    corner: str,
    supply: float,
    temp_c: int,
    n_zq: int,
    n_post: int,
    channel: str,
    stim_file: str = "stimuli.inc",
    t_stop_override: float | None = None,
    skip_before: str | None = "6.0e-9",
) -> tuple[str, float]:
    """Full 16:1 TX post-layout transient deck matching run_pvt45.py boundary conditions."""
    bits_ctrl = encode_zq_ffe(n_zq, n_post)
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
    if t_stop_override is not None:
        t_stop = t_stop_override

    is_rcx = "_rcx" in netlist.name
    opt_extra = " noopiter" if is_rcx else ""
    tr = 30e-12
    pw = 0.5 * T_CLK - tr
    tf0 = 0.50 * T_CLK - tr / 2
    tr90 = 0.25 * T_CLK - tr / 2
    tr180 = 0.50 * T_CLK - tr / 2
    tf270 = 0.25 * T_CLK - tr / 2

    deck = f"""* Post-Layout Full 16:1 SST TX ({subckt}, {corner}, {supply}V, {temp_c}C, Nzq={n_zq}, FFE={n_post}, ch={channel})
.lib "{project.model_library()}" {corner}
.include "{netlist}"
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

* Full 16:1 Post-Layout Extracted DUT
Xdut din0 din1 din2 din3 din4 din5 din6 din7
+ din8 din9 din10 din11 din12 din13 din14 din15
+ phi0 phi90 phi180 phi270 rst_n
+ m0 m1 m2 m3 m4 f0 f1 f2 ffe_en
+ vbg lqp lqn vdrv clk500_out clk250_out vdd 0 {subckt}

* Exact repo TX pad / package / AC coupling / channel / far-end 50-ohm termination
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

.nodeset v(vdrv)=0.44 v(lqp)=0.22 v(lqn)=0.22
.temp {temp_c}
.options reltol=2e-4 abstol=1p vntol=2u klu{opt_extra}
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
    if skip_before is not None:
        deck = spice.skip_output_before(deck, skip_before)
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
        rem_meets_spec=bool(serial.meets_draft(rem_m)),
        power_mw=float(pwr_w * 1e3),
        pj_per_bit=float(pwr_w * 1e3 / 4.0),
        vdrv_mean_v=float(np.mean(vdrv_seg)),
        vdrv_ripple_mvpp=float(np.ptp(vdrv_seg) * 1e3),
        pad_cm_mv=float(np.mean(w["pad_cm"][t_win]) * 1e3),
    )


def ensure_stimuli(camp: Path, bits: np.ndarray, supplies: set[float]) -> dict[int, Path]:
    stim_paths: dict[int, Path] = {}
    for vdd in sorted(supplies):
        key = round(vdd * 1000)
        sp = camp / f"stim16_{key}.inc"
        if not sp.exists():
            sp.write_text(parallel_word_stimuli(bits, vdd))
        stim_paths[key] = sp
    return stim_paths


def run_smoke_tests(camp: Path, stim_paths: dict[int, Path]) -> dict:
    """1-ns smoke test on both CPEX and RCX top netlists to verify convergence & estimate speed."""
    results = {}
    for label, netlist in [("top_cpex", TOP_PEX), ("top_rcx", TOP_RCX)]:
        tag = f"smoke_{label}_tt"
        existing = spice.case_output(camp, tag, "waveforms.raw", t_end=1.0e-9)
        if existing is not None:
            ex_p = existing.parent / "execution.json"
            ex_d = json.loads(ex_p.read_text()) if ex_p.exists() else {}
            if ex_d.get("exit_code") == 0 and not ex_d.get("log_failures"):
                el = ex_d.get("elapsed_s", 0.0)
                w = spice.Waves(existing)
                results[label] = dict(ok=True, elapsed_s=el, t_end=float(w.t[-1]), vdrv_end=float(w["vdrv_v"][-1]), cached=True)
                print(f"[SMOKE] {label}: OK (cached, {el:.1f}s, t_end={w.t[-1]*1e9:.3f}ns, vdrv={w['vdrv_v'][-1]:.4f}V)", flush=True)
                continue
        deck, t_stop = build_top_postlayout_deck(
            netlist=netlist, subckt="serdes_tx_sst_top_pdk",
            corner="tt", supply=1.80, temp_c=27, n_zq=16, n_post=0,
            channel="rlc16", t_stop_override=1.0e-9, skip_before=None,
        )
        rdir = spice.next_run_dir(camp, tag)
        ex = spice.run(deck, rdir, files={"stimuli.inc": stim_paths[1800]}, timeout_s=300)
        if not ex.ok:
            raise RuntimeError(f"Smoke test failed for {label} ({rdir}): {ex.log_failures}")
        w = spice.Waves(rdir / "waveforms.raw")
        if w.t[-1] < t_stop * (1 - 1e-6):
            raise RuntimeError(f"Smoke test truncated for {label}: t_end={w.t[-1]}")
        results[label] = dict(ok=True, elapsed_s=ex.elapsed_s, t_end=float(w.t[-1]), vdrv_end=float(w["vdrv_v"][-1]), cached=False)
        print(f"[SMOKE] {label}: OK ({ex.elapsed_s:.1f}s, t_end={w.t[-1]*1e9:.3f}ns, vdrv={w['vdrv_v'][-1]:.4f}V)", flush=True)
    return results


def run_stage1_driver_zq_s11(camp: Path, summary: dict, summary_path: Path, workers: int) -> None:
    """Stage 1: Driver ZQ 50 ohm & S11 @ 2 GHz on CPEX (and RCX) across 6 extreme MOSxRC corners."""
    print(f"\n=== Stage 1: Driver ZQ 50 ohm & S11 @ 2 GHz (6 extreme MOSxRC corners, workers={workers}) ===", flush=True)
    for variant, netlist in [("cpex", DRIVER_PEX), ("rcx", DRIVER_RCX)]:
        key = f"stage1_driver_{variant}"
        jobs, meta = [], []
        for corner, vdd, temp_c, n_zq in STAGE1_CORNERS:
            tag = f"s1_{variant}_{corner}_v{round(vdd*1000)}_t{temp_c}"
            # Check latest attempt log
            existing_logs = sorted(camp.glob(f"{tag}*/simulator.log"))
            cached_log = None
            for lp in reversed(existing_logs):
                if "ZQ_AC " in lp.read_text(errors="replace"):
                    cached_log = lp
                    break
            if cached_log is not None:
                meta.append((tag, corner, vdd, temp_c, n_zq, cached_log))
            else:
                rdir = spice.next_run_dir(camp, tag)
                deck = build_driver_zq_s11_deck(
                    netlist=netlist, subckt="serdes_tx_sst_driver_pdk",
                    corner=corner, supply=vdd, temp_c=temp_c, n_zq=n_zq,
                )
                jobs.append((deck, rdir, {"timeout_s": 240}))
                meta.append((tag, corner, vdd, temp_c, n_zq, rdir / "simulator.log"))
        if jobs:
            execs = spice.run_many(jobs, workers=workers, smoke=False)
            for ex in execs:
                if not ex.ok:
                    print(f"FAIL {ex.run_dir.name}: {ex.log_failures}", flush=True)
        rows = []
        print(f"\n[{variant.upper()}] {'Corner':<18} {'Nzq':>4} {'Vdrv(V)':>8} {'R_pu':>7} {'R_pd':>7} {'R_avg':>7} {'S11_1G(dB)':>11} {'S11_2G(dB)':>11}", flush=True)
        for tag, corner, vdd, temp_c, n_zq, log_p in meta:
            if not log_p.exists():
                print(f"FAIL {tag}: missing log", flush=True)
                continue
            r = parse_zq_log(log_p)
            if "r_pu" not in r or "s11_2g_db" not in r:
                print(f"FAIL {tag}: ZQ_DC/AC missing", flush=True)
                continue
            r["tag"] = tag
            r["variant"] = variant
            r["r_avg"] = 0.5 * (r["r_pu"] + r["r_pd"])
            r["r_unit_est"] = r["r_avg"] * r["n_zq"]
            r["n_zq_opt"] = max(8, min(23, int(round(r["r_unit_est"] / 50.0))))
            r["log"] = str(log_p.relative_to(ROOT))
            rows.append(r)
            print(
                f"{corner}_v{int(round(vdd*1000))}_t{temp_c:<4} "
                f"{int(r['n_zq']):4d} {r['vdrv']:8.4f} {r['r_pu']:7.2f} {r['r_pd']:7.2f} "
                f"{r['r_avg']:7.2f} {r['s11_1g_db']:11.2f} {r['s11_2g_db']:11.2f}",
                flush=True,
            )
        summary[key] = rows
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")


def run_top_batch(
    *,
    camp: Path,
    cases: list[dict],
    bits: np.ndarray,
    stim_paths: dict[int, Path],
    summary: dict,
    summary_key: str,
    summary_path: Path,
    workers: int,
    timeout_s: int,
    banner: str,
) -> None:
    """Run a list of full 16:1 Top post-layout cases with workers<=2 and case-level resume."""
    print(f"\n=== {banner} ({len(cases)} cases, workers={workers}) ===", flush=True)
    print(
        f"{'Case':<26} {'FFE':>3} {'InOrd':>5} {'Err':>3} {'PadPP':>7} {'PadMrg':>7} {'PadSpr':>7} "
        f"{'RemMrg':>7} {'RemSpr':>7} {'Vdrv':>7} {'RipmV':>6} {'Pwr':>6} {'pJ/b':>5} {'Spec':>5}",
        flush=True,
    )
    summary.setdefault(summary_key, {})
    lock = threading.Lock()
    todo = []

    for cs in cases:
        tag = cs["case_tag"]
        deck, t_stop = build_top_postlayout_deck(
            netlist=cs["netlist"], subckt="serdes_tx_sst_top_pdk",
            corner=cs["process"], supply=cs["supply"], temp_c=cs["temp_c"],
            n_zq=cs["n_zq"], n_post=cs["n_post"], channel=cs["channel"],
        )
        existing = spice.case_output(camp, tag, "waveforms.raw", t_end=t_stop)
        if existing is not None:
            if tag not in summary[summary_key]:
                m = analyze_top_wave(existing, bits, cs["channel"])
                ex_p = existing.parent / "execution.json"
                el = json.loads(ex_p.read_text()).get("elapsed_s", 0.0) if ex_p.exists() else 0.0
                m.update(
                    case_tag=tag, corner_tag=cs["corner_tag"], variant=cs["variant"],
                    process=cs["process"], supply=cs["supply"], temp_c=cs["temp_c"],
                    n_zq=cs["n_zq"], n_post=cs["n_post"], elapsed_s=el,
                    raw=str(existing.relative_to(ROOT)),
                )
                summary[summary_key][tag] = m
                summary_path.write_text(json.dumps(summary, indent=2) + "\n")
            else:
                m = summary[summary_key][tag]
            _print_top_row(tag, m, cached=True)
        else:
            todo.append((cs, deck, t_stop))

    def _run_one(item):
        cs, deck, t_stop = item
        rdir = spice.next_run_dir(camp, cs["case_tag"])
        ex = spice.run(
            deck, rdir,
            files={"stimuli.inc": stim_paths[round(cs["supply"] * 1000)]},
            timeout_s=timeout_s,
        )
        return cs, t_stop, ex

    if todo:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_run_one, item) for item in todo]
            for fut in as_completed(futs):
                cs, t_stop, ex = fut.result()
                tag = cs["case_tag"]
                if not ex.ok:
                    print(f"FAIL {tag}: {ex.log_failures}", flush=True)
                    continue
                found = spice.case_output(camp, tag, "waveforms.raw", t_end=t_stop)
                if found is None:
                    print(f"WARN {tag}: truncated/missing waveforms.raw (t_end={t_stop:.3e})", flush=True)
                    continue
                m = analyze_top_wave(found, bits, cs["channel"])
                m.update(
                    case_tag=tag, corner_tag=cs["corner_tag"], variant=cs["variant"],
                    process=cs["process"], supply=cs["supply"], temp_c=cs["temp_c"],
                    n_zq=cs["n_zq"], n_post=cs["n_post"], elapsed_s=ex.elapsed_s,
                    raw=str(found.relative_to(ROOT)),
                )
                with lock:
                    summary[summary_key][tag] = m
                    _print_top_row(tag, m, cached=False)
                    summary_path.write_text(json.dumps(summary, indent=2) + "\n")


def _print_top_row(tag: str, m: dict, cached: bool = False) -> None:
    ps = f"{m['pad_spread_ui']:7.4f}" if m["pad_spread_ui"] is not None else "   None"
    rs = f"{m['rem_spread_ui']:7.4f}" if m["rem_spread_ui"] is not None else "   None"
    spec_ok = m["rem_meets_spec"] if m["channel"] == "c2" else m["pad_meets_spec"]
    sfx = " (cached)" if cached else f" ({m.get('elapsed_s', 0.0):.0f}s)"
    print(
        f"{tag:<26} {m['n_post']:3d} {str(m['pad_in_order']):>5} {m['pad_errors']:3d} "
        f"{m['pad_pp_mv']:7.1f} {m['pad_margin_mv']:7.1f} {ps} "
        f"{m['rem_margin_mv']:7.1f} {rs} "
        f"{m['vdrv_mean_v']:7.4f} {m['vdrv_ripple_mvpp']:6.2f} "
        f"{m['power_mw']:6.2f} {m['pj_per_bit']:5.2f} {'PASS' if spec_ok else 'FAIL':>5}{sfx}",
        flush=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", choices=["all", "1", "2", "2a", "2b", "3"], default="all")
    ap.add_argument("--workers", type=int, default=2, help="Max concurrent ngspice (strictly capped <= 2)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Campaign output directory (resumable)")
    ap.add_argument("--smoke-only", action="store_true", help="Only run 1-ns CPEX + RCX smoke tests")
    args = ap.parse_args()

    workers = max(1, min(args.workers, 2))
    camp = args.out.resolve()
    camp.mkdir(parents=True, exist_ok=True)

    # Verify extracted netlists exist and record hashes
    for p in (DRIVER_PEX, DRIVER_RCX, TOP_PEX, TOP_RCX):
        if not p.exists():
            raise FileNotFoundError(f"Missing extracted netlist: {p}")

    identity = {
        "driver_pex": {"path": str(DRIVER_PEX.relative_to(ROOT)), "sha256": sha256_file(DRIVER_PEX)},
        "driver_rcx": {"path": str(DRIVER_RCX.relative_to(ROOT)), "sha256": sha256_file(DRIVER_RCX)},
        "top_pex": {"path": str(TOP_PEX.relative_to(ROOT)), "sha256": sha256_file(TOP_PEX)},
        "top_rcx": {"path": str(TOP_RCX.relative_to(ROOT)), "sha256": sha256_file(TOP_RCX)},
    }
    (camp / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")

    bits = build_sequence()
    (camp / "bits.json").write_text(json.dumps(bits.tolist()))
    stim_paths = ensure_stimuli(camp, bits, {1.65, 1.80, 1.95})

    summary_path = camp / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {
        "identity": identity,
        "rc_summary_top": json.loads(TOP_RC_SUMMARY.read_text()) if TOP_RC_SUMMARY.exists() else {},
        "workers": workers,
        "payload_bits": PAYLOAD_BITS,
    }
    summary["identity"] = identity

    if args.smoke_only:
        summary["smoke"] = run_smoke_tests(camp, stim_paths)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        return

    if args.stage in ("all", "1"):
        run_stage1_driver_zq_s11(camp, summary, summary_path, workers=workers)

    if args.stage in ("all", "2", "2a", "2b", "3"):
        summary["smoke"] = run_smoke_tests(camp, stim_paths)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    if args.stage in ("all", "2", "2a"):
        cases_2a = [
            dict(
                case_tag=f"cpex_{ctag}", corner_tag=ctag, variant="cpex",
                netlist=TOP_PEX, process=proc, supply=vdd, temp_c=temp_c,
                n_zq=n_zq, n_post=0, channel="rlc16",
            )
            for ctag, proc, vdd, temp_c, n_zq in STAGE2_PVT_CORNERS
        ]
        run_top_batch(
            camp=camp, cases=cases_2a, bits=bits, stim_paths=stim_paths,
            summary=summary, summary_key="stage2_top_cpex_pvt", summary_path=summary_path,
            workers=workers, timeout_s=5400,
            banner="Stage 2A: Full 16:1 Top Post-Layout CPEX (6 extreme PVT corners, RLC16, FFE=0)",
        )

    if args.stage in ("all", "2", "2b"):
        cases_2b = [
            dict(
                case_tag=f"cpex_c2_{ctag}_ffe{n_post}", corner_tag=ctag, variant="cpex",
                netlist=TOP_PEX, process=proc, supply=vdd, temp_c=temp_c,
                n_zq=n_zq, n_post=n_post, channel="c2",
            )
            for ctag, proc, vdd, temp_c, n_zq, n_post in STAGE2_C2_CORNERS
        ]
        run_top_batch(
            camp=camp, cases=cases_2b, bits=bits, stim_paths=stim_paths,
            summary=summary, summary_key="stage2_top_cpex_c2", summary_path=summary_path,
            workers=workers, timeout_s=5400,
            banner="Stage 2B: Full 16:1 Top Post-Layout CPEX over C2_loss6 PCB (FFE=3)",
        )

    if args.stage in ("all", "3"):
        cases_3 = [
            dict(
                case_tag=f"rcx_{ctag}", corner_tag=ctag, variant="rcx",
                netlist=TOP_RCX, process=proc, supply=vdd, temp_c=temp_c,
                n_zq=n_zq, n_post=0, channel="rlc16",
            )
            for ctag, proc, vdd, temp_c, n_zq in STAGE3_RCX_CORNERS
        ]
        run_top_batch(
            camp=camp, cases=cases_3, bits=bits, stim_paths=stim_paths,
            summary=summary, summary_key="stage3_top_rcx", summary_path=summary_path,
            workers=workers, timeout_s=10800,
            banner="Stage 3: Full 16:1 Top Native Magic RCX Spot-Check (RLC16, FFE=0)",
        )

    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nSaved post-layout signoff summary: {summary_path}", flush=True)


if __name__ == "__main__":
    main()
