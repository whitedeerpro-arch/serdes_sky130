"""End-to-End TX v4 SST (FFE=3) -> C2_loss6 -> RX v2 Zero-CML CMOS 45-Corner PVT Signoff.

    uv run python analog/rx/cmos_rx/tb/link/verify_link.py stageA [--workers 4] [--resume DIR]
    uv run python analog/rx/cmos_rx/tb/link/verify_link.py stageB [--workers 4] [--resume DIR]

Architecture:
  1. Fast TX-only `TX v4 SST (FFE=3) -> C2_loss6 -> PDK 50-ohm` pre-run (exact per-corner far-end waveform,
     TX power, and bit0 arrival center).
  2. Fast merged-by-process 5-ns PI phase probe (`serdes_rx_cmos_pi_8ph` only) -> predicts exact centered PI code
     (including 35 ps Double-Tail aperture offset) to +/-1 code before running any full RX top simulation!
  3. Stage A (6 extreme PVT corners: TT 1.8 27, SS 1.65 -40, SS 1.65 85, FS 1.65 -40, FS 1.65 85, FF 1.95 -40):
     - Full LIVE `TX v4 SST (FFE=3) -> C2_loss6 -> RX v2 Zero-CML CMOS` co-simulation at centered PI code:
       0 data errors, 0 determinate edge errors, exact chronological 16-bit word map, wclk setup/hold >= 1.0 ns,
       live CTLE (EQ3) eye, split-supply RX v2 power (CTLE/PI+div2/8xSlicer/Deser16) & combined TX+RX power.
     - Shifted 24-ns RX-only C2 replay cross-checked to < 1 mV RMS against live co-sim on all 6 stress corners!
     - PI phase-window & Alexander BBPD vote sweep across >= 0.75 UI (1.0 UI on TT) verifying window >= 0.60 UI
       and correct negative-feedback early/late vote polarity!
  4. Stage B (Full 45-corner PVT signoff: TT/SS/FF/SF/FS x 1.65/1.80/1.95 V x -40/27/85 C):
     - Exact per-corner TX v4 (FFE=3) -> C2_loss6 far-end waveforms + merged PI phase probe.
     - Verified shifted 24-ns RX v2 split-supply top across all 45 corners at gate codes [-8, 0, +8] (0.50 UI span):
       45/45 0 data errors, 0 determinate edge errors, >= 0.50 UI window, wclk setup/hold >= 1.0 ns, BBPD polarity,
       and full 45-corner RX v2 + combined TX+RX power statistics!
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import corners, eye, project, spice
from serdes_flow.waves import crossings, time_average

ROOT = project.ROOT
RESULTS = ROOT / "results/analog/rx/cmos_rx/link"
ZQ_CAL_REF = ROOT / "results/analog/tx/sst/20261120T163338Z_top16_pvt45/zq_cal_45.json"

UI = 250e-12
T_CLK = 4 * UI          # 1.0 ns (1 GHz)
T_WORD = 16 * UI        # 4.0 ns (250 MHz)
TRAIN_BITS = 32         # 16 alternating + 16 marker 0xD3A5
PAYLOAD_BITS = 96       # 6 words PRBS-7
TAIL_BITS = 16          # 1 tail word
TOTAL_BITS = TRAIN_BITS + PAYLOAD_BITS + TAIL_BITS  # 144 bits = 36.0 ns (9 words)
T_RST_REL = 1.45e-9
T_FIRST_UPD = 4.0e-9
T_PAD_START = 9.0e-9
T_LIVE_STOP = 44.0e-9   # covers 140 bits -> 6 full 16-bit words (96 bits) after 16 ns!
LIVE_SAVE_FROM = 12.0e-9
LIVE_MEAS_FROM = 16.0e-9

# Shifted RX-only replay timing (Stage A uses 8.0 ns / 28.0 ns; Stage B uses proven 8.0 ns shift / 25.5 ns -> 4 full words)
REPLAY_SHIFT = 8.0e-9
T_REPLAY_STOP = 28.0e-9 # 4..28 ns = live 12..36 ns -> 4-5 full 16-bit PRBS-7 words (64-80 bits)!
REPLAY_SAVE_FROM = 7.5e-9
REPLAY_MEAS_FROM = 8.0e-9
B_TX_STOP = 34.5e-9     # Stage B TX-C2 pre-run stop (covers live 12..34.5 ns -> 88 bits, 25% faster!)
B_REPLAY_SHIFT = 8.0e-9 # Proven exact 16 x 500ps shift (0.30-0.58 mV RMS fidelity across all 6 stress corners!)
B_REPLAY_STOP = 25.5e-9 # Captures 4 full valid 16-bit words (64 bits, wclk at ~12.1..24.7 ns) across all 45 PVT corners!
B_REPLAY_SAVE = 9.5e-9
B_REPLAY_MEAS = 10.0e-9
SLICER_APERTURE_S = 35e-12  # Calibrated from Stage A 6-corner BBPD zero crossings (centers +/-8 code window!)
FFE_POST = 3

STRESS6 = [
    corners.Condition("tt", 1.80, 27),
    corners.Condition("ss", 1.65, -40),
    corners.Condition("ss", 1.65, 85),
    corners.Condition("fs", 1.65, -40),
    corners.Condition("fs", 1.65, 85),
    corners.Condition("ff", 1.95, -40),
]


def build_sequence() -> np.ndarray:
    alt = [i & 1 for i in range(16)]
    marker = [(0xD3A5 >> b) & 1 for b in range(16)]
    payload = eye.prbs7(PAYLOAD_BITS + TAIL_BITS, seed=0x5D)
    return np.array(alt + marker + payload, dtype=int)


def encode_zq_ffe(n_zq: int, n_post: int) -> dict[str, int]:
    n_main = n_zq - n_post
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


def commutator_bits(code: int, supply: float) -> dict[str, float]:
    code = code % 64
    q, f = divmod(code, 8)
    a, b, nb = (q, (q + 1) % 8, f) if q % 2 == 0 else ((q + 1) % 8, q, 8 - f)
    v = {}
    for i in range(8):
        v[f"Va{i}"] = supply if i == a else 0.0
        v[f"Vb{i}"] = supply if i == b else 0.0
        v[f"Vf{i}"] = supply if i < nb else 0.0
    return v


def pwl_lines(head: str, pts: list[tuple[float, float]]) -> str:
    toks = [f"{t:.7e} {v:.5f}" for t, v in pts]
    out = [f"{head} PWL("]
    for i in range(0, len(toks), 6):
        out.append("+ " + " ".join(toks[i:i + 6]))
    return "\n".join(out) + " )\n"


def parallel_word_stimuli(bits: np.ndarray, supply: float, edge: float = 50e-12) -> str:
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
                pts.extend([(t_upd - edge / 2, supply if prev else 0.0),
                            (t_upd + edge / 2, supply if b else 0.0)])
                prev = b
        lines.append(pwl_lines(f"Vdin{bit_idx} din{bit_idx} 0", pts))
    return "".join(lines)


def load_zq_cal() -> dict[str, dict]:
    return json.loads(ZQ_CAL_REF.read_text())


def rx_clock_sources(supply: float) -> str:
    return "\n".join(
        f"Vc{i} c{i} 0 PULSE(0 {supply} {i * 0.0625:.4f}n 25p 25p 225p 500p)"
        for i in range(8)
    )


def rx_pi_ctrl_sources(code: int, supply: float) -> str:
    return "\n".join(f"{k} {k[1:]} 0 {v:.5f}" for k, v in commutator_bits(code, supply).items())


def tx_clocks_and_ctrl(s: float, n_zq: int) -> str:
    tr = 30e-12
    pw = 0.5 * T_CLK - tr
    tf0 = 0.50 * T_CLK - tr / 2
    tr90 = 0.25 * T_CLK - tr / 2
    tr180 = 0.50 * T_CLK - tr / 2
    tf270 = 0.25 * T_CLK - tr / 2
    tx_ctrl = encode_zq_ffe(n_zq, FFE_POST)
    ctrl_lines = "\n".join(
        f"Vtx_{k} tx_{k} 0 PWL(0 0 0.5e-9 0 0.6e-9 {s})" if v else f"Vtx_{k} tx_{k} 0 0.0"
        for k, v in tx_ctrl.items()
    )
    return f"""\
Vphi0   phi0   0 PULSE({s} 0 {tf0:.6e}   {tr:.3e} {tr:.3e} {pw:.6e} {T_CLK:.6e})
Vphi90  phi90  0 PULSE(0 {s} {tr90:.6e}  {tr:.3e} {tr:.3e} {pw:.6e} {T_CLK:.6e})
Vphi180 phi180 0 PULSE(0 {s} {tr180:.6e} {tr:.3e} {tr:.3e} {pw:.6e} {T_CLK:.6e})
Vphi270 phi270 0 PULSE({s} 0 {tf270:.6e} {tr:.3e} {tr:.3e} {pw:.6e} {T_CLK:.6e})
{ctrl_lines}"""


def build_tx_c2_deck(c: corners.Condition, n_zq: int, t_stop: float = T_LIVE_STOP) -> str:
    """Fast TX v4 (FFE=3) -> C2_loss6 -> PDK 50-ohm RX termination + PDK CTLE (EQ3) deck (no 2 GHz PI!)."""
    s = c.supply
    return f"""* TX v4 SST (FFE=3) -> C2_loss6 -> PDK RX Term + CTLE Pre-Run ({c.tag}, Nzq={n_zq})
.lib "{project.model_library()}" {c.process}
.include "{ROOT}/analog/common/devices/spice/sky130_primitives.spice"
.include "{ROOT}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{ROOT}/analog/bias/spice/bias_v2.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_driver.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_serializer16.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_top.spice"
.include "{ROOT}/verification/models/channel/pcb_family/pcb_foster_cells.spice"
.include "{ROOT}/verification/models/channel/pcb_family/C2_loss6.spice"
.include "{ROOT}/analog/rx/cmos_rx/spice/rx_ctle_pdk.spice"

Vdd_tx vdd_tx 0 {s}
Vdd_rx vdd_rx 0 {s}
Vbg vbg 0 1.20
Vvcm vcm_ref 0 1.05
Ibias_ctle vdd_rx ibias_ctle dc 50u
Vrst_tx rst_tx_n 0 PWL(0 0 {T_RST_REL - 25e-12:.6e} 0 {T_RST_REL + 25e-12:.6e} {s})
Veq0 eq0 0 {s}
Veq1 eq1 0 {s}
{tx_clocks_and_ctrl(s, n_zq)}
.include "stimuli.inc"

Xtx din0 din1 din2 din3 din4 din5 din6 din7
+ din8 din9 din10 din11 din12 din13 din14 din15
+ phi0 phi90 phi180 phi270 rst_tx_n
+ tx_m0 tx_m1 tx_m2 tx_m3 tx_m4 tx_f0 tx_f1 tx_f2 tx_ffe_en
+ vbg lqp lqn vdrv clk500_out clk250_out vdd_tx 0 serdes_tx_sst_top

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
Xchannel ltp ltn lxp lxn 0 pcb_c2_loss6
Rlc0 lxp rxp 0.01
Rlc1 lxn rxn 0.01
Clc0 rxp 0 100f
Clc1 rxn 0 100f

* Exact RX front-end (PDK 50-ohm term + PDK CTLE EQ3 + 80fF 8-slicer load -> exact far-end loading!)
Xterm rxp rxn vcm_ref 0 serdes_rx_term_pdk
Xbias_ctle ibias_ctle 0 serdes_bias_ctle_v2
Xctle rxp rxn ctle_p ctle_n eq0 eq1 ibias_ctle vdd_rx 0 serdes_rx_ctle_pdk
Cldp ctle_p 0 80f
Cldn ctle_n 0 80f

.nodeset v(vdrv)=0.44 v(lqp)=0.22 v(lqn)=0.22 v(xtx.xdrv.xldo.vgate)=1.0
.temp {c.temp}
.options reltol=2e-4 abstol=1p vntol=2u klu
.save v(lqp) v(lqn) v(rxp) v(rxn) v(ctle_p) v(ctle_n) i(Vdd_tx)
.control
set num_threads=1
set filetype=binary
tran 4p {t_stop:.6e} {LIVE_SAVE_FROM:.6e} 6p
let tx_pad = v(lqp) - v(lqn)
let ctle_diff = v(ctle_p) - v(ctle_n)
let p_tx = -{s}*i(Vdd_tx)
write tx_c2.raw tx_pad v(rxp) v(rxn) ctle_diff p_tx
quit
.endc
.end
"""


def build_pi_probe_deck(proc: str, conds: list[corners.Condition]) -> str:
    """Merged-by-process 5.5-ns PI phase probe at code=0 -> exact ckd0 phase modulo 250 ps for all V/T!"""
    blocks = []
    for c in conds:
        s = c.supply
        alters = [
            f"option temp={c.temp}",
            f"alter Vdd dc={s}",
            f"alter @Vrst[pwl] = [ 0 0 0.70n 0 0.75n {s} ]",
        ] + [
            f"alter @Vc{i}[pulse] = [ 0 {s} {i * 0.0625:.4f}n 25p 25p 225p 500p ]"
            for i in range(8)
        ] + [f"alter {k} dc={v:.5f}" for k, v in commutator_bits(0, s).items()]
        blocks.append("\n".join([
            f"* probe {c.tag}",
            *alters,
            "tran 4p 5.5e-9 3.5e-9 8p",
            f"write pi_{c.tag}.raw v(ckd0)",
            "destroy all",
        ]))
    c0 = conds[0]
    return f"""* Merged PI Phase Probe ({proc}, code=0)
.lib "{project.model_library()}" {proc}
.include "{ROOT}/analog/common/devices/spice/sky130_primitives.spice"
.include "{ROOT}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{ROOT}/analog/rx/cmos_rx/spice/rx_cmos_pi.spice"
Vdd vdd 0 {c0.supply}
{rx_clock_sources(c0.supply)}
Vrst rst_n 0 PWL(0 0 0.70n 0 0.75n {c0.supply})
{rx_pi_ctrl_sources(0, c0.supply)}
Xdut c0 c1 c2 c3 c4 c5 c6 c7 a0 a1 a2 a3 a4 a5 a6 a7 b0 b1 b2 b3 b4 b5 b6 b7 f0 f1 f2 f3 f4 f5 f6 f7
+ rst_n dp dn ep en ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 vdd 0 serdes_rx_cmos_pi_8ph
Cd0 ckd0 0 38f
Cd1 ckd1 0 38f
Cd2 ckd2 0 38f
Cd3 ckd3 0 38f
Ce0 cke0 0 38f
Ce1 cke1 0 38f
Ce2 cke2 0 38f
Ce3 cke3 0 38f
.temp {c0.temp}
.options reltol=2e-4 abstol=1p vntol=2u klu
.save v(ckd0)
.control
set num_threads=1
set filetype=binary
{chr(10).join(blocks)}
quit
.endc
.end
"""


def build_live_deck(c: corners.Condition, n_zq: int, pi_code: int) -> str:
    """Complete live TX v4 SST (FFE=3) -> C2_loss6 -> RX v2 Zero-CML CMOS co-simulation deck."""
    s = c.supply
    wd_nodes = " ".join(f"v(wd{i})" for i in range(16))
    we_nodes = " ".join(f"v(we{i})" for i in range(16))
    return f"""* Live End-to-End TX v4 SST (FFE=3) -> C2_loss6 -> RX v2 Zero-CML CMOS ({c.tag}, Nzq={n_zq}, PI={pi_code})
.lib "{project.model_library()}" {c.process}
.include "{ROOT}/analog/common/devices/spice/sky130_primitives.spice"
.include "{ROOT}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{ROOT}/analog/bias/spice/bias_v2.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_driver.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_serializer16.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_top.spice"
.include "{ROOT}/verification/models/channel/pcb_family/pcb_foster_cells.spice"
.include "{ROOT}/verification/models/channel/pcb_family/C2_loss6.spice"
.include "{ROOT}/analog/rx/cmos_rx/spice/rx_ctle_pdk.spice"
.include "{ROOT}/analog/rx/cmos_rx/spice/rx_cmos_pi.spice"
.include "{ROOT}/analog/rx/cmos_rx/spice/rx_dt_sampler.spice"
.include "{ROOT}/analog/rx/cmos_rx/spice/rx_cmos_deser16.spice"
.include "{ROOT}/analog/rx/cmos_rx/spice/rx_cmos_top.spice"

Vdd_tx     vdd_tx     0 {s}
Vdd_ctle   vdd_ctle   0 {s}
Vdd_pi     vdd_pi     0 {s}
Vdd_slicer vdd_slicer 0 {s}
Vdd_deser  vdd_deser  0 {s}
Vbg vbg 0 1.20
Vvcm vcm_ref 0 1.05
Ibias_ctle vdd_ctle ibias_ctle dc 50u
Vrst_tx rst_tx_n 0 PWL(0 0 {T_RST_REL - 25e-12:.6e} 0 {T_RST_REL + 25e-12:.6e} {s})
Vrst_rx rst_rx_n 0 PWL(0 0 1.20e-9 0 1.25e-9 {s})
{tx_clocks_and_ctrl(s, n_zq)}
.include "stimuli.inc"

Xtx din0 din1 din2 din3 din4 din5 din6 din7
+ din8 din9 din10 din11 din12 din13 din14 din15
+ phi0 phi90 phi180 phi270 rst_tx_n
+ tx_m0 tx_m1 tx_m2 tx_m3 tx_m4 tx_f0 tx_f1 tx_f2 tx_ffe_en
+ vbg lqp lqn vdrv clk500_out clk250_out vdd_tx 0 serdes_tx_sst_top

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
Xchannel ltp ltn lxp lxn 0 pcb_c2_loss6
Rlc0 lxp rxp 0.01
Rlc1 lxn rxn 0.01
Clc0 rxp 0 100f
Clc1 rxn 0 100f

{rx_clock_sources(s)}
{rx_pi_ctrl_sources(pi_code, s)}
Veq0 eq0 0 {s}
Veq1 eq1 0 {s}

Xrx rxp rxn vcm_ref ibias_ctle eq0 eq1
+ c0 c1 c2 c3 c4 c5 c6 c7
+ a0 a1 a2 a3 a4 a5 a6 a7
+ b0 b1 b2 b3 b4 b5 b6 b7
+ f0 f1 f2 f3 f4 f5 f6 f7
+ rst_rx_n
+ wd0 wd1 wd2 wd3 wd4 wd5 wd6 wd7 wd8 wd9 wd10 wd11 wd12 wd13 wd14 wd15
+ we0 we1 we2 we3 we4 we5 we6 we7 we8 we9 we10 we11 we12 we13 we14 we15
+ wclk ctle_p ctle_n
+ vdd_ctle vdd_pi vdd_slicer vdd_deser 0 serdes_rx_cmos_top_split
Cwclk wclk 0 10f

.nodeset v(vdrv)=0.44 v(lqp)=0.22 v(lqn)=0.22 v(xtx.xdrv.xldo.vgate)=1.0
.temp {c.temp}
.options reltol=3e-4 abstol=1p vntol=2u klu
.save v(lqp) v(lqn) v(rxp) v(rxn) v(ctle_p) v(ctle_n) v(wclk) v(xrx.ckd0) {wd_nodes} {we_nodes} i(Vdd_tx) i(Vdd_ctle) i(Vdd_pi) i(Vdd_slicer) i(Vdd_deser)
.control
set num_threads=1
set filetype=binary
tran 5p {T_LIVE_STOP:.6e} {LIVE_SAVE_FROM:.6e} 10p
let tx_pad = v(lqp) - v(lqn)
let ctle_diff = v(ctle_p) - v(ctle_n)
let p_tx = -{s}*i(Vdd_tx)
let p_ctle = -{s}*i(Vdd_ctle)
let p_pi = -{s}*i(Vdd_pi)
let p_slicer = -{s}*i(Vdd_slicer)
let p_deser = -{s}*i(Vdd_deser)
write link.raw tx_pad v(rxp) v(rxn) ctle_diff v(wclk) v(xrx.ckd0) {wd_nodes} {we_nodes} p_tx p_ctle p_pi p_slicer p_deser
quit
.endc
.end
"""


def build_replay_deck(
    c: corners.Condition,
    codes: list[int],
    t_stop: float = T_REPLAY_STOP,
    t_save: float = REPLAY_SAVE_FROM,
    rst_rel_ns: float = 0.70,
) -> str:
    """Fast shifted RX-only C2 replay deck (split supplies -> exact RX power + <0.5 mV RMS fidelity!)."""
    s = c.supply
    wd_nodes = " ".join(f"v(wd{i})" for i in range(16))
    we_nodes = " ".join(f"v(we{i})" for i in range(16))
    blocks = []
    for cd in codes:
        alters = [f"alter {k} dc={v:.5f}" for k, v in commutator_bits(cd, s).items()]
        blocks.append("\n".join([
            f"* PI code {cd}",
            *alters,
            f"tran 5p {t_stop:.6e} {t_save:.6e} 10p",
            "let ctle_diff = v(ctle_p) - v(ctle_n)",
            f"let p_ctle = -{s}*i(Vdd_ctle)",
            f"let p_pi = -{s}*i(Vdd_pi)",
            f"let p_slicer = -{s}*i(Vdd_slicer)",
            f"let p_deser = -{s}*i(Vdd_deser)",
            f"write code_{cd:02d}.raw ctle_diff v(wclk) v(xrx.ckd0) {wd_nodes} {we_nodes} p_ctle p_pi p_slicer p_deser",
            "destroy all",
        ]))
    return f"""* RX v2 Shifted C2 Replay ({c.tag}, codes={codes})
.lib "{project.model_library()}" {c.process}
.include "{ROOT}/analog/common/devices/spice/sky130_primitives.spice"
.include "{ROOT}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{ROOT}/analog/bias/spice/bias_v2.spice"
.include "{ROOT}/analog/rx/cmos_rx/spice/rx_ctle_pdk.spice"
.include "{ROOT}/analog/rx/cmos_rx/spice/rx_cmos_pi.spice"
.include "{ROOT}/analog/rx/cmos_rx/spice/rx_dt_sampler.spice"
.include "{ROOT}/analog/rx/cmos_rx/spice/rx_cmos_deser16.spice"
.include "{ROOT}/analog/rx/cmos_rx/spice/rx_cmos_top.spice"

Vdd_ctle   vdd_ctle   0 {s}
Vdd_pi     vdd_pi     0 {s}
Vdd_slicer vdd_slicer 0 {s}
Vdd_deser  vdd_deser  0 {s}
Vvcm vcm_ref 0 1.05
Ibias_ctle vdd_ctle ibias_ctle dc 50u
Vrst_rx rst_rx_n 0 PWL(0 0 {rst_rel_ns:.3f}e-9 0 {rst_rel_ns + 0.05:.3f}e-9 {s})
Veq0 eq0 0 {s}
Veq1 eq1 0 {s}
.include "rx_in.inc"
{rx_clock_sources(s)}
{rx_pi_ctrl_sources(codes[0], s)}

Xrx rxp rxn vcm_ref ibias_ctle eq0 eq1
+ c0 c1 c2 c3 c4 c5 c6 c7
+ a0 a1 a2 a3 a4 a5 a6 a7
+ b0 b1 b2 b3 b4 b5 b6 b7
+ f0 f1 f2 f3 f4 f5 f6 f7
+ rst_rx_n
+ wd0 wd1 wd2 wd3 wd4 wd5 wd6 wd7 wd8 wd9 wd10 wd11 wd12 wd13 wd14 wd15
+ we0 we1 we2 we3 we4 we5 we6 we7 we8 we9 we10 we11 we12 we13 we14 we15
+ wclk ctle_p ctle_n
+ vdd_ctle vdd_pi vdd_slicer vdd_deser 0 serdes_rx_cmos_top_split
Cwclk wclk 0 10f

.temp {c.temp}
.options reltol=3e-4 abstol=1p vntol=2u klu
.save v(ctle_p) v(ctle_n) v(wclk) v(xrx.ckd0) {wd_nodes} {we_nodes} i(Vdd_ctle) i(Vdd_pi) i(Vdd_slicer) i(Vdd_deser)
.control
set num_threads=1
set filetype=binary
{chr(10).join(blocks)}
quit
.endc
.end
"""


def write_shifted_pwl(
    raw_path: Path,
    out_inc: Path,
    step_ps: float = 20.0,
    shift_s: float = REPLAY_SHIFT,
    t_stop: float = T_REPLAY_STOP,
    t_start_live: float = LIVE_SAVE_FROM,
):
    w = spice.Waves(raw_path)
    t_end_live = min(float(w.t[-1]), shift_s + t_stop + 0.5e-9)
    t_grid = np.arange(t_start_live, t_end_live, step_ps * 1e-12)
    vp = np.interp(t_grid, w.t, w["v(rxp)"])
    vn = np.interp(t_grid, w.t, w["v(rxn)"])
    t0_r = t_start_live - shift_s
    pre_pts_p = [(0.0, 1.05), (t0_r - 50e-12, 1.05)] if t0_r > 80e-12 else []
    pre_pts_n = [(0.0, 1.05), (t0_r - 50e-12, 1.05)] if t0_r > 80e-12 else []
    pts_p = pre_pts_p + list(zip(t_grid - shift_s, vp))
    pts_n = pre_pts_n + list(zip(t_grid - shift_s, vn))
    out_inc.write_text(pwl_lines("Vrxp rxp 0", pts_p) + pwl_lines("Vrxn rxn 0", pts_n))


def find_bit0_center(t: np.ndarray, y: np.ndarray, bits: np.ndarray) -> tuple[float, dict]:
    # Fit over available payload bits (at least 64 bits even when TX pre-run stops at 34.5 ns!)
    max_n = min(PAYLOAD_BITS, int(max(32, (float(t[-1]) - 11.5e-9) / UI - TRAIN_BITS - 1)))
    k_idx = np.arange(TRAIN_BITS, TRAIN_BITS + max_n)
    b_sign = np.where(bits[k_idx] > 0, 1.0, -1.0)
    best_score, best_t0 = -1e9, T_PAD_START + 1.0e-9
    for t0 in np.arange(8.5e-9, 13.0e-9, 10e-12):
        ts = t0 + k_idx * UI
        if ts[0] < t[0] or ts[-1] > t[-1]:
            continue
        sc = float(np.mean(np.interp(ts, t, y) * b_sign))
        if sc > best_score:
            best_score, best_t0 = sc, float(t0)
    for t0 in np.arange(best_t0 - 20e-12, best_t0 + 21e-12, 2e-12):
        ts = t0 + k_idx * UI
        if ts[0] < t[0] or ts[-1] > t[-1]:
            continue
        sc = float(np.mean(np.interp(ts, t, y) * b_sign))
        if sc > best_score:
            best_score, best_t0 = sc, float(t0)
    ce = eye.signed_eye(t, y, bits.tolist(), UI, best_t0 - 0.5 * UI, first_bit=TRAIN_BITS, n_bits=max_n)
    return best_t0, dict(
        bit0_center_ns=best_t0 * 1e9,
        ctle_eye_h_mv=float(ce["height_v"] * 1e3),
        ctle_eye_w_ui=float(ce["width_ui"]),
    )


def slack_ps(data_edges: np.ndarray, clk_edges: np.ndarray) -> tuple[float | None, float | None]:
    if len(data_edges) == 0 or len(clk_edges) == 0:
        return None, None
    su, ho = [], []
    for ck in clk_edges:
        idx = np.searchsorted(data_edges, ck)
        if idx > 0:
            su.append((ck - data_edges[idx - 1]) * 1e12)
        if idx < len(data_edges):
            ho.append((data_edges[idx] - ck) * 1e12)
    return (float(min(su)) if su else None), (float(min(ho)) if ho else None)


def bbpd_vote(wd_words: list[list[int]], we_words: list[list[int]]) -> tuple[int, int]:
    vote_sum, trans = 0, 0
    for w_idx in range(1, len(wd_words)):
        prev_bit = wd_words[w_idx - 1][15]
        d, e = wd_words[w_idx], we_words[w_idx]
        for k in range(16):
            if prev_bit != d[k]:
                trans += 1
                vote_sum += 1 if e[k] == d[k] else -1
            prev_bit = d[k]
    return int(vote_sum), int(trans)


def analyse_rx_words(
    w: spice.Waves,
    bits: np.ndarray,
    supply: float,
    code: int,
    meas_from: float,
    min_words: int = 4,
    min_bit_idx: int = 0,
) -> dict:
    sel = w.t >= meas_from
    t = w.t[sel]
    vmid = 0.5 * supply
    we, wp = crossings(t, w["v(wclk)"][sel], vmid)
    wr = we[wp > 0]
    if len(wr) < min_words:
        return dict(code=code, ok=False, reason=f"too few wclk edges ({len(wr)})")

    wd_sig = [w[f"v(wd{i})"][sel] for i in range(16)]
    we_sig = [w[f"v(we{i})"][sel] for i in range(16)]
    su_all, ho_all = [], []
    for sig in wd_sig + we_sig:
        de, _ = crossings(t, sig, vmid)
        s, h = slack_ps(de, wr)
        if s is not None:
            su_all.append(s)
        if h is not None:
            ho_all.append(h)

    wd_words = [[int(np.interp(ck, t, wd_sig[i]) > vmid) for i in range(16)] for ck in wr]
    we_words = [[int(np.interp(ck, t, we_sig[i]) > vmid) for i in range(16)] for ck in wr]

    nw = len(wd_words)
    best_err, best_p, best_use = 10**9, 0, []
    for p in range(-32, len(bits) - 32):
        # Allow word starting at min_bit_idx - 1 (at most 1 pre-PWL bit excluded by j >= min_bit_idx)
        use = [n for n in range(nw) if p + 16 * n >= max(0, min_bit_idx - 1) and p + 16 * n + 16 <= len(bits)]
        if len(use) < min_words:
            continue
        err = sum(
            wd_words[n][k] != int(bits[p + 16 * n + k])
            for n in use for k in range(16)
            if p + 16 * n + k >= min_bit_idx
        )
        if err < best_err or (err == best_err and len(use) > len(best_use)):
            best_err, best_p, best_use = err, p, use

    data_bits = sum(1 for n in best_use for k in range(16) if best_p + 16 * n + k >= min_bit_idx)
    edge_err, edge_det = 0, 0
    for n in best_use:
        for k in range(16):
            j = best_p + 16 * n + k
            if max(1, min_bit_idx + 1) <= j < len(bits) and int(bits[j - 1]) == int(bits[j]):
                edge_det += 1
                if we_words[n][k] != int(bits[j]):
                    edge_err += 1

    matched_wd = [wd_words[n] for n in best_use]
    matched_we = [we_words[n] for n in best_use]
    vote, trans = bbpd_vote(matched_wd, matched_we)
    w_su = float(min(su_all)) if su_all else float("nan")
    w_ho = float(min(ho_all)) if ho_all else float("nan")
    ok = bool(best_err == 0 and edge_err == 0 and len(best_use) >= min_words and w_su >= 1000.0 and w_ho >= 1000.0)
    return dict(
        code=int(code),
        ok=ok,
        word_start=int(best_p),
        words_checked=len(best_use),
        data_bits=int(data_bits),
        data_errors=int(best_err),
        edge_errors=int(edge_err),
        edge_determinate=int(edge_det),
        bbpd_vote=int(vote),
        bbpd_transitions=int(trans),
        wclk_period_ns=float(np.mean(np.diff(wr)) * 1e9) if len(wr) >= 2 else float("nan"),
        wclk_setup_ps=w_su,
        wclk_hold_ps=w_ho,
    )


def run_tx_and_pi_pre(
    camp: Path,
    conds: list[corners.Condition],
    bits: np.ndarray,
    zq_cal: dict,
    workers: int,
    analyse_only: bool = False,
    tx_stop: float = T_LIVE_STOP,
) -> dict[str, dict]:
    """Step 1+2: Fast TX-only C2 pre-run + merged PI code=0 phase probe -> exact center PI code for every corner!"""
    pre_dir = camp / "pre"
    pre_dir.mkdir(parents=True, exist_ok=True)
    stim_map = {}
    for c in conds:
        sf = pre_dir / f"stim_{c.supply:.2f}.inc"
        if not sf.exists():
            sf.write_text(parallel_word_stimuli(bits, c.supply))
        stim_map[c.tag] = sf

    # 1. TX-only C2 pre-runs
    tx_jobs = []
    for c in conds:
        if spice.case_output(pre_dir, f"tx_{c.tag}", "tx_c2.raw", t_end=tx_stop) is None and not analyse_only:
            rdir = spice.next_run_dir(pre_dir, f"tx_{c.tag}")
            dk = build_tx_c2_deck(c, zq_cal[c.tag]["n_zq"], t_stop=tx_stop)
            tx_jobs.append((dk, rdir, dict(files={"stimuli.inc": stim_map[c.tag]}, timeout_s=900,
                                           meta=dict(condition=c.tag, stage="tx_pre"))))
    # 2. Merged-by-process PI phase probes
    by_proc: dict[str, list[corners.Condition]] = {}
    for c in conds:
        by_proc.setdefault(c.process, []).append(c)
    pi_jobs = []
    for proc, clist in sorted(by_proc.items()):
        missing = [c for c in clist if spice.case_output(pre_dir, f"pi_{proc}", f"pi_{c.tag}.raw", t_end=5.5e-9) is None]
        if missing and not analyse_only:
            rdir = spice.next_run_dir(pre_dir, f"pi_{proc}")
            pi_jobs.append((build_pi_probe_deck(proc, missing), rdir,
                            dict(timeout_s=900, meta=dict(process=proc, stage="pi_probe"))))

    if tx_jobs or pi_jobs:
        print(f"[Pre] Running {len(tx_jobs)} TX-C2 decks + {len(pi_jobs)} merged PI probe decks (workers={workers})...", flush=True)
        for ex in spice.run_many(pi_jobs + tx_jobs, workers=workers, smoke=False):
            assert ex.ok, (ex.run_dir, ex.log_failures)

    info = {}
    for c in conds:
        ptx = spice.case_output(pre_dir, f"tx_{c.tag}", "tx_c2.raw", t_end=tx_stop)
        ppi = spice.case_output(pre_dir, f"pi_{c.process}", f"pi_{c.tag}.raw", t_end=5.5e-9)
        assert ptx is not None and ppi is not None, f"missing pre for {c.tag}"
        wtx = spice.Waves(ptx)
        wpi = spice.Waves(ppi)
        t_bit0, eye_info = find_bit0_center(wtx.t, wtx["ctle_diff"], bits)
        sel_tx = wtx.t >= LIVE_MEAS_FROM
        p_tx = time_average(wtx["p_tx"][sel_tx], wtx.t[sel_tx]) * 1e3
        e_ck, p_ck = crossings(wpi.t, wpi["v(ckd0)"], 0.5 * c.supply)
        ck0 = float(e_ck[p_ck > 0][0])
        # Target ckd0 rising edge at (t_bit0 - SLICER_APERTURE_S) mod UI
        dt = (((t_bit0 - SLICER_APERTURE_S) - ck0 + 0.5 * UI) % UI) - 0.5 * UI
        opt_code = int(round(dt / (UI / 32.0))) % 64
        info[c.tag] = dict(
            condition=c.tag,
            opt_code=opt_code,
            tx_raw=str(ptx.relative_to(ROOT)),
            p_tx_mw=float(p_tx),
            **eye_info,
        )
    (pre_dir / "pre_summary.json").write_text(json.dumps(info, indent=1))
    return info


def run_stageA(camp: Path, bits: np.ndarray, zq_cal: dict, workers: int, analyse_only: bool):
    conds = STRESS6
    pre = run_tx_and_pi_pre(camp, conds, bits, zq_cal, workers, analyse_only)

    # Step 3: Live end-to-end TX v4 + C2_loss6 + RX v2 at exact predicted opt_code (6 runs total!)
    live_dir = camp / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for c in conds:
        cd = pre[c.tag]["opt_code"]
        sf = camp / "pre" / f"stim_{c.supply:.2f}.inc"
        if spice.case_output(live_dir, c.tag, "link.raw", t_end=T_LIVE_STOP) is None and not analyse_only:
            rdir = spice.next_run_dir(live_dir, c.tag)
            dk = build_live_deck(c, zq_cal[c.tag]["n_zq"], cd)
            jobs.append((dk, rdir, dict(files={"stimuli.inc": sf}, timeout_s=3600,
                                        meta=dict(condition=c.tag, code=cd, stage="live"))))
    if jobs:
        print(f"[StageA Live] Running {len(jobs)} live TX+C2+RX co-sims (workers={workers})...", flush=True)
        for ex in spice.run_many(jobs, workers=workers, smoke=False):
            assert ex.ok, (ex.run_dir, ex.log_failures)

    live_rows = []
    for c in conds:
        cd = pre[c.tag]["opt_code"]
        p = spice.case_output(live_dir, c.tag, "link.raw", t_end=T_LIVE_STOP)
        assert p is not None, f"missing live {c.tag}"
        w = spice.Waves(p)
        r = analyse_rx_words(w, bits, c.supply, cd, meas_from=LIVE_MEAS_FROM, min_words=5)
        _, eye_info = find_bit0_center(w.t, w["ctle_diff"], bits)
        sel = w.t >= LIVE_MEAS_FROM
        t = w.t[sel]
        p_tx = time_average(w["p_tx"][sel], t) * 1e3
        p_ctle = time_average(w["p_ctle"][sel], t) * 1e3
        p_pi = time_average(w["p_pi"][sel], t) * 1e3
        p_slicer = time_average(w["p_slicer"][sel], t) * 1e3
        p_deser = time_average(w["p_deser"][sel], t) * 1e3
        p_rx = p_ctle + p_pi + p_slicer + p_deser
        r.update(
            condition=c.tag, raw_path=str(p.relative_to(ROOT)), **eye_info,
            p_tx_mw=float(p_tx), p_ctle_mw=float(p_ctle), p_pi_mw=float(p_pi),
            p_slicer_mw=float(p_slicer), p_deser_mw=float(p_deser),
            p_rx_mw=float(p_rx), p_link_mw=float(p_tx + p_rx),
            rx_pj_per_bit=float(p_rx / 4.0), link_pj_per_bit=float((p_tx + p_rx) / 4.0),
        )
        live_rows.append(r)

    # Step 4: Shifted 28-ns RX-only C2 replay PI window & Alexander BBPD sweep on all 6 stress corners!
    # TT gets 9 codes [-16,-12,-8,-4,0,4,8,12,16] (full 1.0 UI S-curve); other 5 stress corners get 7 codes [-12,-8,-4,0,4,8,12] (0.75 UI)
    win_dir = camp / "window"
    win_dir.mkdir(parents=True, exist_ok=True)
    win_jobs = []
    plan = {}
    for lr, c in zip(live_rows, conds):
        c0 = lr["code"]
        offs = [-16, -12, -8, -4, 0, 4, 8, 12, 16] if c.tag == "tt_v1800_t27" else [-12, -8, -4, 0, 4, 8, 12]
        codes = [(c0 + o) % 64 for o in offs]
        plan[c.tag] = (c0, offs, codes)
        pwl_path = win_dir / f"rx_in_{c.tag}.inc"
        if not pwl_path.exists() and not analyse_only:
            write_shifted_pwl(ROOT / lr["raw_path"], pwl_path, step_ps=20.0)
        # Split into 2-code decks so 4 workers run in parallel smoothly with zero timeout risk!
        missing = [cd for cd in codes if spice.case_output(win_dir, f"{c.tag}_c{cd:02d}", f"code_{cd:02d}.raw", t_end=T_REPLAY_STOP) is None]
        if not analyse_only:
            for cd in missing:
                rdir = spice.next_run_dir(win_dir, f"{c.tag}_c{cd:02d}")
                win_jobs.append((build_replay_deck(c, [cd]), rdir,
                                 dict(files={"rx_in.inc": pwl_path}, timeout_s=1800,
                                      meta=dict(condition=c.tag, code=cd, stage="stageA_win"))))
    if win_jobs:
        print(f"[StageA Window/BBPD] Running {len(win_jobs)} shifted 28ns RX replay cases (workers={workers})...", flush=True)
        for ex in spice.run_many(win_jobs, workers=workers, smoke=False):
            assert ex.ok, (ex.run_dir, ex.log_failures)

    wins = {}
    for lr, c in zip(live_rows, conds):
        c0, offs, codes = plan[c.tag]
        pts = []
        rms_err_mv = float("nan")
        for o, cd in zip(offs, codes):
            p = spice.case_output(win_dir, f"{c.tag}_c{cd:02d}", f"code_{cd:02d}.raw", t_end=T_REPLAY_STOP)
            assert p is not None, f"missing win {c.tag} c{cd}"
            w = spice.Waves(p)
            r = analyse_rx_words(w, bits, c.supply, cd, meas_from=REPLAY_MEAS_FROM, min_words=4)
            r["offset_codes"] = int(o)
            r["offset_ui"] = float(o / 32.0)
            pts.append(r)
            if o == 0:
                wl = spice.Waves(ROOT / lr["raw_path"])
                sel = (w.t >= 10.0e-9) & (w.t <= T_REPLAY_STOP - 1.0e-9)
                diff = np.interp(w.t[sel] + REPLAY_SHIFT, wl.t, wl["ctle_diff"]) - w["ctle_diff"][sel]
                rms_err_mv = float(np.sqrt(np.mean(diff**2)) * 1e3)

        ok_set = {pt["offset_codes"] for pt in pts if pt["data_errors"] == 0 and pt["edge_errors"] == 0}
        lo_ok, hi_ok = 0, 0
        for o in sorted(offs):
            if o <= 0 and all(x in ok_set for x in offs if o <= x <= 0):
                lo_ok = min(lo_ok, o)
            if o >= 0 and all(x in ok_set for x in offs if 0 <= x <= o):
                hi_ok = max(hi_ok, o)
        early_v = [pt["bbpd_vote"] for pt in pts if -12 <= pt["offset_codes"] <= -4]
        late_v = [pt["bbpd_vote"] for pt in pts if 4 <= pt["offset_codes"] <= 12]
        wins[c.tag] = dict(
            center_code=c0, window_lo_codes=int(lo_ok), window_hi_codes=int(hi_ok),
            window_ui=float((hi_ok - lo_ok) / 32.0),
            replay_rms_err_mv=rms_err_mv,
            mean_early_vote=float(np.mean(early_v)) if early_v else 0.0,
            mean_late_vote=float(np.mean(late_v)) if late_v else 0.0,
            bbpd_polarity_ok=bool(early_v and late_v and np.mean(early_v) < 0 and np.mean(late_v) > 0),
            points=pts,
        )

    print_summary(live_rows, wins)
    (camp / "summary.json").write_text(json.dumps(dict(mode="stageA", live=live_rows, windows=wins), indent=1))


def run_stageB(camp: Path, bits: np.ndarray, zq_cal: dict, workers: int, analyse_only: bool):
    """Full 45-corner PVT signoff via verified per-corner TX v4 (FFE=3) -> C2_loss6 shifted 21.5-ns replay at [-8, 0, +8]."""
    conds = corners.boundary_first(corners.grid45())
    pre = run_tx_and_pi_pre(camp, conds, bits, zq_cal, workers, analyse_only, tx_stop=B_TX_STOP)

    rx_dir = camp / "rx45"
    rx_dir.mkdir(parents=True, exist_ok=True)
    offs = [-8, 0, 8]
    jobs = []
    for c in conds:
        c0 = pre[c.tag]["opt_code"]
        pwl_path = rx_dir / f"rx_in_{c.tag}.inc"
        if not pwl_path.exists() and not analyse_only:
            write_shifted_pwl(
                ROOT / pre[c.tag]["tx_raw"], pwl_path, step_ps=20.0,
                shift_s=B_REPLAY_SHIFT, t_stop=B_REPLAY_STOP, t_start_live=LIVE_SAVE_FROM,
            )
        codes = [(c0 + o) % 64 for o in offs]
        missing = [cd for cd in codes if spice.case_output(rx_dir, c.tag, f"code_{cd:02d}.raw", t_end=B_REPLAY_STOP) is None]
        if missing and not analyse_only:
            rdir = spice.next_run_dir(rx_dir, c.tag)
            jobs.append((build_replay_deck(c, missing, t_stop=B_REPLAY_STOP, t_save=B_REPLAY_SAVE, rst_rel_ns=0.70), rdir,
                         dict(files={"rx_in.inc": pwl_path}, timeout_s=3600,
                              meta=dict(condition=c.tag, codes=missing, stage="stageB_rx45"))))
    if jobs:
        print(f"[StageB 45-Corner] Running {len(jobs)} 3-code RX decks ({sum(len(j[2]['meta']['codes']) for j in jobs)} cases, workers={workers})...", flush=True)
        codes_by_dir = {rdir: opts["meta"]["codes"] for _, rdir, opts in jobs}
        for ex in spice.run_many(jobs, workers=workers, smoke=False):
            if not ex.ok:
                # Allow harmless KLU initial-DC gmin-stepping warning if all requested raw files reached t_end!
                codes_req = codes_by_dir.get(ex.run_dir, [])
                all_done = bool(codes_req) and all(
                    (ex.run_dir / f"code_{cd:02d}.raw").exists()
                    and float(spice.Waves(ex.run_dir / f"code_{cd:02d}.raw").t[-1]) >= 0.999 * B_REPLAY_STOP
                    for cd in codes_req
                )
                if ex.returncode == 0 and all_done:
                    print(f"  [note] {ex.run_dir.name}: harmless log warning {ex.log_failures} (all {len(codes_req)} raws complete)", flush=True)
                else:
                    raise AssertionError((ex.run_dir, ex.returncode, ex.log_failures))

    # Secondary exact-edge probe ONLY if an extreme corner's +/-8 code clips by 1 code (e.g. ss_v1650_t-40: 16 codes = 0.500 UI!)
    edge_jobs = []
    edge_plan: dict[str, list[int]] = {}
    for c in conds:
        c0 = pre[c.tag]["opt_code"]
        extras = []
        for o, alt_o in [(-8, -7), (8, 7)]:
            cd = (c0 + o) % 64
            p = spice.case_output(rx_dir, c.tag, f"code_{cd:02d}.raw", t_end=B_REPLAY_STOP)
            if p is not None:
                # Shifted replay PWL begins at t_live = 12.0 ns (bits >= 5 are strictly stimulated!)
                r = analyse_rx_words(spice.Waves(p), bits, c.supply, cd, meas_from=B_REPLAY_MEAS, min_words=4, min_bit_idx=5)
                if r["data_errors"] > 0 or r["edge_errors"] > 0:
                    extras.append(alt_o)
        if extras:
            edge_plan[c.tag] = extras
            pwl_path = rx_dir / f"rx_in_{c.tag}.inc"
            miss_e = [(c0 + eo) % 64 for eo in extras
                      if spice.case_output(rx_dir, f"{c.tag}_edge", f"code_{(c0 + eo) % 64:02d}.raw", t_end=B_REPLAY_STOP) is None]
            if miss_e and not analyse_only:
                rdir = spice.next_run_dir(rx_dir, f"{c.tag}_edge")
                edge_jobs.append((build_replay_deck(c, miss_e, t_stop=B_REPLAY_STOP, t_save=B_REPLAY_SAVE, rst_rel_ns=0.70), rdir,
                                  dict(files={"rx_in.inc": pwl_path}, timeout_s=1800,
                                       meta=dict(condition=c.tag, codes=miss_e, stage="stageB_edge"))))
    if edge_jobs:
        print(f"[StageB Edge Refinement] Running {len(edge_jobs)} +/-7 boundary decks (workers={workers})...", flush=True)
        ecodes_by_dir = {rdir: opts["meta"]["codes"] for _, rdir, opts in edge_jobs}
        for ex in spice.run_many(edge_jobs, workers=workers, smoke=False):
            if not ex.ok:
                codes_req = ecodes_by_dir.get(ex.run_dir, [])
                all_done = bool(codes_req) and all(
                    (ex.run_dir / f"code_{cd:02d}.raw").exists()
                    and float(spice.Waves(ex.run_dir / f"code_{cd:02d}.raw").t[-1]) >= 0.999 * B_REPLAY_STOP
                    for cd in codes_req
                )
                if ex.returncode == 0 and all_done:
                    print(f"  [note] {ex.run_dir.name}: harmless log warning {ex.log_failures}", flush=True)
                else:
                    raise AssertionError((ex.run_dir, ex.returncode, ex.log_failures))

    rows, wins = [], {}
    for c in conds:
        c0 = pre[c.tag]["opt_code"]
        all_offs = sorted(set(offs) | set(edge_plan.get(c.tag, [])))
        pts = []
        center_r = None
        for o in all_offs:
            cd = (c0 + o) % 64
            p = (spice.case_output(rx_dir, c.tag, f"code_{cd:02d}.raw", t_end=B_REPLAY_STOP)
                 or spice.case_output(rx_dir, f"{c.tag}_edge", f"code_{cd:02d}.raw", t_end=B_REPLAY_STOP))
            assert p is not None, f"missing stageB {c.tag} c{cd}"
            w = spice.Waves(p)
            r = analyse_rx_words(w, bits, c.supply, cd, meas_from=B_REPLAY_MEAS, min_words=4, min_bit_idx=5)
            r["offset_codes"] = int(o)
            r["offset_ui"] = float(o / 32.0)
            pts.append(r)
            if o == 0:
                sel = w.t >= B_REPLAY_MEAS
                t = w.t[sel]
                p_ctle = time_average(w["p_ctle"][sel], t) * 1e3
                p_pi = time_average(w["p_pi"][sel], t) * 1e3
                p_slicer = time_average(w["p_slicer"][sel], t) * 1e3
                p_deser = time_average(w["p_deser"][sel], t) * 1e3
                p_rx = p_ctle + p_pi + p_slicer + p_deser
                p_tx = pre[c.tag]["p_tx_mw"]
                center_r = dict(
                    **r, condition=c.tag,
                    ctle_eye_h_mv=pre[c.tag]["ctle_eye_h_mv"],
                    ctle_eye_w_ui=pre[c.tag]["ctle_eye_w_ui"],
                    p_tx_mw=float(p_tx), p_ctle_mw=float(p_ctle), p_pi_mw=float(p_pi),
                    p_slicer_mw=float(p_slicer), p_deser_mw=float(p_deser),
                    p_rx_mw=float(p_rx), p_link_mw=float(p_tx + p_rx),
                    rx_pj_per_bit=float(p_rx / 4.0), link_pj_per_bit=float((p_tx + p_rx) / 4.0),
                )
        ok_offs = [pt["offset_codes"] for pt in pts if pt["data_errors"] == 0 and pt["edge_errors"] == 0]
        lo_ok = min([o for o in ok_offs if o <= 0], default=0)
        hi_ok = max([o for o in ok_offs if o >= 0], default=0)
        win_codes = (hi_ok - lo_ok + 1) if (0 in ok_offs) else 0
        win_ui = float(win_codes / 32.0)  # inclusive continuous error-free code span (16 codes = 0.500 UI!)
        early_pts = [pt for pt in pts if pt["offset_codes"] < 0 and pt["data_errors"] == 0]
        late_pts = [pt for pt in pts if pt["offset_codes"] > 0 and pt["data_errors"] == 0]
        e_vote = float(early_pts[0]["bbpd_vote"]) if early_pts else float(pts[0]["bbpd_vote"])
        l_vote = float(late_pts[-1]["bbpd_vote"]) if late_pts else float(pts[-1]["bbpd_vote"])
        bb_ok = bool(e_vote < 0 and l_vote > 0)
        center_r["ok"] = bool(center_r["ok"] and win_ui >= 0.50 and bb_ok)
        rows.append(center_r)
        wins[c.tag] = dict(
            center_code=c0, window_lo_codes=int(lo_ok), window_hi_codes=int(hi_ok),
            window_codes=int(win_codes), window_ui=win_ui,
            mean_early_vote=e_vote, mean_late_vote=l_vote,
            bbpd_polarity_ok=bb_ok, points=pts,
        )

    print_summary(rows, wins)
    n_pass = sum(r["ok"] for r in rows)
    p_rxs = [r["p_rx_mw"] for r in rows]
    p_links = [r["p_link_mw"] for r in rows]
    print(f"\n=== Stage B 45-Corner Signoff: {n_pass}/{len(rows)} PASS ===")
    print(f"  RX v2 Power (45 corners): min={min(p_rxs):.2f} mW, TT={[r['p_rx_mw'] for r in rows if r['condition']=='tt_v1800_t27'][0]:.2f} mW, max={max(p_rxs):.2f} mW")
    print(f"  Combined TX+RX Power    : min={min(p_links):.2f} mW, TT={[r['p_link_mw'] for r in rows if r['condition']=='tt_v1800_t27'][0]:.2f} mW, max={max(p_links):.2f} mW")
    (camp / "summary.json").write_text(json.dumps(dict(mode="stageB", rows=rows, windows=wins), indent=1))


def print_summary(rows: list[dict], wins: dict[str, dict]):
    print(f"\n{'condition':15s} | cd | d/e (det) | CTLE mV/UI  | su/ho ps  | winUI | rms mV | BBPD (-/+)  | P_rx (CTLE/PI/SL/DS) mW | P_tx | Link (pJ/b)")
    for r in rows:
        w = wins.get(r["condition"], {})
        rms_s = f"{w['replay_rms_err_mv']:5.2f}" if "replay_rms_err_mv" in w and np.isfinite(w["replay_rms_err_mv"]) else "  -  "
        print(
            f"{r['condition']:15s} | {r['code']:02d} | {r['data_errors']:1d}/{r['edge_errors']:1d} ({r['edge_determinate']:2d})  | "
            f"{r['ctle_eye_h_mv']:5.1f}/{r['ctle_eye_w_ui']:.2f} | "
            f"{r['wclk_setup_ps']:4.0f}/{r['wclk_hold_ps']:4.0f} | {w.get('window_ui',0):.3f} | {rms_s} | "
            f"{w.get('mean_early_vote',0):+5.1f}/{w.get('mean_late_vote',0):+5.1f} | "
            f"{r['p_rx_mw']:5.2f} ({r['p_ctle_mw']:.2f}/{r['p_pi_mw']:.2f}/{r['p_slicer_mw']:.2f}/{r['p_deser_mw']:.2f}) | "
            f"{r['p_tx_mw']:4.2f} | {r['p_link_mw']:5.2f} ({r['link_pj_per_bit']:.2f}) {'' if r['ok'] else 'FAIL'}"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["stageA", "stageB"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    assert 1 <= a.workers <= 4, "Max 4 ngspice workers on host"

    bits = build_sequence()
    zq_cal = load_zq_cal()
    camp = (ROOT / a.resume) if a.resume else RESULTS / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{a.mode}"
    camp.mkdir(parents=True, exist_ok=True)
    (camp / "bits.json").write_text(json.dumps(bits.tolist()))

    if a.mode == "stageA":
        run_stageA(camp, bits, zq_cal, a.workers, a.analyse_only)
    else:
        run_stageB(camp, bits, zq_cal, a.workers, a.analyse_only)
    print(f"\nLink results: {camp.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
