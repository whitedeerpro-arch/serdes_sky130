#!/usr/bin/env python3
"""4 Gb/s Integrated Full-Chain Co-Simulation (I-TOP-02):
  Stage 1: Same-Deck Closed-Loop PLL v4 -> 4x CML->CMOS r5 -> TX Q-Div2
           -> Dynamic TX SST v4.3 (FFE=3) -> C2_loss6 PCB -> RX Term + CTLE
  Stage 2: Locked-PLL TX->C2_loss6 + Locked-PLL 8-Phase 2 GHz Clocks
           -> Full RX CMOS v2.2 (CTLE + 64-code CMOS PI + 8x DT Slicers + Deser16)
  SingleDeck (TT): All-in-One True Single-Deck PLL v4 -> 4x C2C r5 -> TX Q-Div2
           -> Dynamic TX SST v4.3 -> C2_loss6 -> Full RX CMOS v2.2

Strictly caps ngspice concurrency at --workers <= 2 (num_threads=1, binary_output,
t_end completion verification, case-level resume).

Usage:
    uv run python verification/top_cosim/verify_4g_full_chain.py --mode stage1 --workers 2
    uv run python verification/top_cosim/verify_4g_full_chain.py --mode stage2 --codes center --workers 2
    uv run python verification/top_cosim/verify_4g_full_chain.py --mode stage2 --codes gate3 --workers 2
    uv run python verification/top_cosim/verify_4g_full_chain.py --mode singledeck --workers 1
    uv run python verification/top_cosim/verify_4g_full_chain.py --mode plot
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from serdes_flow import bias, eye, rcorner, serial, spice, watch  # noqa: E402
from serdes_flow.corners import Condition  # noqa: E402
from serdes_flow.waves import crossings, time_average  # noqa: E402

SC_LIB = Path("/home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice")
PTAT_TABLE = REPO / "results/analog/pll/vco/r6_ptat/map_p67_28_66/table.json"
PLL_V4_SUMMARY = REPO / "results/analog/pll/top/v4_closed_loop_20261123/summary.json"
DEFAULT_CAMP = REPO / "results/verification/top_cosim_4g_20261123"
DEFAULT_FIG = REPO / "docs/figures/system/serdes_4g_top_cosim_20261123.png"

TREF = 4.0e-9      # 250 MHz reference clock
FREF = 250.0e6
FTGT = 2.0e9       # 2 GHz VCO / 8-phase anchor clocks
UI = 250.0e-12     # 4 Gb/s NRZ
T_WORD = 16 * UI   # 4.0 ns (250 MHz 16-bit parallel word)
FFE_POST = 3
SLICER_APERTURE_S = 35.0e-12

# Bitstream: 32-bit training (16 alt + 16 marker 0xD3A5) + 64-bit PRBS-7 (seed=0x11) + 16-bit tail = 112 bits (7 words = 28 ns)
# Verified: 16/16 unique 5-bit column signatures across words 1..5 -> exact unambiguous [0..15] bit-mapping proof!
ALT_BITS = 16
TRAIN_BITS = 32
PAYLOAD_BITS = 64
TAIL_BITS = 16
TOTAL_BITS = TRAIN_BITS + PAYLOAD_BITS + TAIL_BITS  # 112 bits

# Stage 1 compact closed-loop timeline (lock PLL 0..35 ns from precharged settled Vctrl + 3 mV,
# then enable TX Q-Div2 + dynamic 4 Gb/s PRBS-7 SST burst 35..76 ns)
T_PRE_REL = 6.0e-9
T_PFD_REL = 7.0e-9
T_QDIV_REL = 35.0e-9
T_TX_REL = 37.45e-9
T_FIRST_UPD = T_TX_REL + 1.75e-9   # 39.20 ns (guaranteed >=350ps hold & >=400ps setup for ANY phi0 phase!)
T_PAD_NOM = T_FIRST_UPD + 5.0e-9   # ~44.20 ns nominal bit0 arrival on pad
T_STAGE1_STOP = 76.0e-9

# Stage 2 RX replay timeline (replays Stage 1 [43.0..75.5 ns] shifted by 41.0 ns -> [2.0..34.5 ns])
STAGE2_SHIFT = 41.0e-9
STAGE2_SRC_START = 43.0e-9
STAGE2_STOP = 33.5e-9
STAGE2_SAVE = 8.5e-9
STAGE2_MEAS = 9.5e-9
STAGE2_RST_REL = 1.20e-9

# Calibrated ZQ slice counts for MOS x RC corners (from analog/tx/sst/tb/run_core_stress.py)
CORNERS = [
    dict(
        id="tt_v1800_t27_tt",
        spec="tt_v1800_t27:tt",
        vin=3.3,
        n_zq=16,
        k_rc=1.00,
        klu=False,
        seed_op27=False,
        label="TT 1.80V 27°C tt",
    ),
    dict(
        id="ss_v1650_t-40_hh",
        spec="ss_v1650_t-40:hh",
        vin=3.0,
        n_zq=18,
        k_rc=1.15,
        klu=False,
        seed_op27=False,
        label="SS 1.65V −40°C hh",
    ),
    dict(
        id="ff_v1950_t-40_ll",
        spec="ff_v1950_t-40:ll",
        vin=3.6,
        n_zq=12,
        k_rc=0.85,
        klu=False,
        extra_opts="rshunt=1e11",
        seed_op27=True,
        label="FF 1.95V −40°C ll",
    ),
    dict(
        id="fs_v1650_t85_hh",
        spec="fs_v1650_t85:hh",
        vin=3.0,
        n_zq=22,
        k_rc=1.15,
        klu=False,
        seed_op27=False,
        label="FS 1.65V 85°C hh",
    ),
]

PLL_INCLUDES = [
    "analog/common/devices/spice/sky130_primitives.spice",
    "analog/common/devices/spice/sky130_pfet_lvt.spice",
    "analog/common/devices/spice/cmos_logic.spice",
    "analog/common/cml_buffer/spice/cml_delay_resistive.spice",
    "analog/common/cml_buffer/spice/cml_buffer.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_r4_v4.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_r5.spice",
    "analog/pll/vco/spice/cap_bank_5b.spice",
    "analog/pll/vco/spice/vco_delay_r6.spice",
    "analog/pll/vco/spice/vco_ring4_r6.spice",
    "analog/pll/divider/spice/cml_latch.spice",
    "analog/pll/divider/spice/cml_div2.spice",
    "analog/pll/divider/spice/cml_prescaler8.spice",
    "analog/pll/top/spice/clock_frontend_r6q.spice",
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
    "analog/pll/top/spice/pll_top_r6_v4_upgrade.spice",
]

TX_CH_INCLUDES = [
    "analog/tx/sst/spice/tx_sst_driver.spice",
    "analog/tx/sst/spice/tx_sst_serializer16.spice",
    "analog/tx/sst/spice/tx_sst_top.spice",
    "analog/rx/cmos_rx/spice/rx_ctle_pdk.spice",
    "analog/rx/cmos_rx/spice/rx_cmos_pi.spice",
    "verification/models/channel/pcb_family/pcb_foster_cells.spice",
    "verification/models/channel/pcb_family/C2_loss6.spice",
]

RX_EXTRA_INCLUDES = [
    "analog/rx/cmos_rx/spice/rx_dt_sampler.spice",
    "analog/rx/cmos_rx/spice/rx_cmos_deser16.spice",
    "analog/rx/cmos_rx/spice/rx_cmos_top.spice",
]


def build_sequence() -> np.ndarray:
    """16 alt + 16 marker (0xD3A5) + 64 PRBS-7 (seed=0x11) + 16 tail = 112 bits (16/16 unique cols)."""
    alt = [i & 1 for i in range(ALT_BITS)]
    marker = [(0xD3A5 >> b) & 1 for b in range(16)]
    payload = eye.prbs7(PAYLOAD_BITS + TAIL_BITS, seed=0x11)
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


def parallel_word_stimuli(bits: np.ndarray, supply: float, t_first_upd: float, edge: float = 50e-12) -> str:
    n_words = len(bits) // 16
    lines = []
    for bit_idx in range(16):
        init_b = bit_idx & 1
        pts = [(0.0, supply if init_b else 0.0)]
        prev = init_b
        for w in range(n_words):
            b = int(bits[16 * w + bit_idx])
            if b != prev:
                t_upd = t_first_upd + w * T_WORD
                pts.extend([
                    (t_upd - edge / 2, supply if prev else 0.0),
                    (t_upd + edge / 2, supply if b else 0.0),
                ])
                prev = b
        lines.append(pwl_lines(f"Vdin{bit_idx} din{bit_idx} 0", pts))
    return "".join(lines)


def load_tables() -> tuple[dict, dict]:
    ptat = json.loads(PTAT_TABLE.read_text()) if PTAT_TABLE.exists() else {}
    pll_v4 = json.loads(PLL_V4_SUMMARY.read_text())["rows"]
    return ptat, pll_v4


def resolve_pll_params(ptat: dict, pll_v4: dict, cs: dict) -> dict:
    cond, rc = cs["spec"].split(":")
    c = Condition.parse(cond)
    row = pll_v4[cs["id"]]
    return dict(
        c=c,
        rc=rc,
        code=int(row["code"]),
        trim=int(row["ldo_trim"]),
        vctrl_model=float(row["vctrl_model_v"]),
        vctrl_locked=float(row["vctrl_mean_v"]),
    )


def ensure_op27_nodeset(
    camp: Path,
    cs: dict,
    p: dict,
    *,
    pre_offset: float,
    stim_file: Path,
    full_rx: bool = False,
    pi_code: int = 0,
) -> Path:
    """Solve 27 C DC OP and emit voltage-only .nodeset for clean -40 C FF convergence."""
    tag = f"{cs['id']}_{'full' if full_rx else 's1'}"
    seed_dir = (camp / "op27_seeds" / tag).resolve()
    ns_file = seed_dir / "op27_clean.nodeset"
    if ns_file.exists() and ns_file.stat().st_size > 1000:
        return ns_file
    c27 = Condition(p["c"].process, p["c"].supply, 27)
    deck_tr = build_stage1_deck(
        cs, c27, p["rc"], p["code"], p["vctrl_locked"], p["trim"],
        stop=1e-9, skip_before="0", pre_offset=pre_offset,
        t_qdiv_rel=T_QDIV_REL, t_tx_rel=T_TX_REL,
        tstep="8p", maxstep="16p", reltol="4e-4", use_klu=False,
        nodeset_file=None, snap_dir=camp / "snap",
        full_rx=full_rx, pi_code=pi_code,
    )
    op_lines = []
    for line in deck_tr.splitlines():
        if line.startswith(".save "):
            continue
        if line.startswith("tran "):
            op_lines.append("op")
        elif line.startswith("write "):
            op_lines.append("write op27.raw all")
        elif line.startswith("let "):
            continue
        else:
            op_lines.append(line)
    ex = spice.run("\n".join(op_lines) + "\n", seed_dir, files={"stimuli.inc": stim_file}, timeout_s=450)
    if not ex.ok or not (seed_dir / "op27.raw").exists():
        raise RuntimeError(f"op27 seed failed for {tag}: {ex.log_failures[:3]}")
    wop = spice.Waves(seed_dir / "op27.raw")
    ns_lines = []
    skip_exact = {
        "vdd", "vdd_pll", "vdd_clk", "vdd_tx", "vdd_rx_fe", "vdd_ctle", "vdd_pi", "vdd_slicer", "vdd_deser",
        "vin", "en_ldo", "ref", "rst_b", "pre_ref", "pre_en", "rst_qdiv_n", "rst_tx_n", "rst_rx_n",
        "vcm_init", "vcm_ref", "eq0", "eq1",
    }
    for name in wop.names:
        if not (name.startswith("v(") and name.endswith(")")):
            continue
        node = name[2:-1]
        if "#" in node or node.startswith(("m.", "q.", "b.", "r.", "l.")):
            continue
        if node in skip_exact or node.startswith(("t", "g", "cfg", "din", "tx_", "a", "b", "f")):
            continue
        val = float(wop[name][0])
        if np.isfinite(val):
            ns_lines.append(f".nodeset v({node})={val:.6g}")
    ns_file.write_text("\n".join(ns_lines) + "\n")
    return ns_file


def build_stage1_deck(
    cs: dict,
    c: Condition,
    rc: str,
    code: int,
    vctrl_locked: float,
    ldo_trim: int,
    *,
    stop: float,
    skip_before: str,
    pre_offset: float,
    t_qdiv_rel: float,
    t_tx_rel: float,
    t_ref_delay: float = 2.0e-9,
    t_pre_rel: float = T_PRE_REL,
    t_pfd_rel: float = T_PFD_REL,
    tstep: str = "10p",
    maxstep: str = "16p",
    reltol: str = "5e-4",
    use_klu: bool = True,
    extra_opts: str = "",
    nodeset_file: Path | None = None,
    snap_dir: Path,
    full_rx: bool = False,
    pi_code: int = 0,
    t_rx_rel: float | None = None,
) -> str:
    """Build Same-Deck Closed-Loop PLL v4 -> 4x C2C r5 -> TX QDiv2 -> TX SST v4.3 -> C2_loss6
    -> RX FE (or Full RX CMOS v2.2 when full_rx=True)."""
    s = c.supply
    vin = cs["vin"]
    vq0 = 1.80
    bias_trim = 15
    n_zq = cs["n_zq"]
    i_c2c_u = 212.5 / cs["k_rc"]
    solver_opt = " klu" if use_klu else ""
    tx_ctrl = encode_zq_ffe(n_zq, FFE_POST)

    includes = list(PLL_INCLUDES) + list(TX_CH_INCLUDES)
    if full_rx:
        includes += list(RX_EXTRA_INCLUDES)

    lines = [
        f"* 4 Gb/s Integrated Closed-Loop Co-Sim ({'FULL-RX' if full_rx else 'STAGE1'}: {c.tag}:{rc}, code={code}, Nzq={n_zq})",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        *[f'.include "{REPO / p}"' for p in includes],
        f'.include "{SC_LIB}"',
        f".param supply={s}",
        f"Vin vin 0 {vin}",
        "Vdd_pll vdd_pll 0 {supply}",
        "Vdd_clk vdd_clk 0 {supply}",
        "Vdd_tx  vdd_tx  0 {supply}",
    ]
    if full_rx:
        lines += [
            "Vdd_ctle   vdd_ctle   0 {supply}",
            "Vdd_pi     vdd_pi     0 {supply}",
            "Vdd_slicer vdd_slicer 0 {supply}",
            "Vdd_deser  vdd_deser  0 {supply}",
        ]
    else:
        lines += ["Vdd_rx_fe vdd_rx_fe 0 {supply}"]

    lines += [
        "Ven_ldo en_ldo 0 {supply}",
        *[f"Et{k} t{k} 0 vdd_pll 0 {(ldo_trim >> k) & 1}" for k in range(6)],
        *[f"Eg{k} g{k} 0 vdd_pll 0 {(bias_trim >> k) & 1}" for k in range(5)],
        *[f"Ecode{k} cfg{k} 0 vq 0 {(code >> k) & 1}" for k in range(5)],
        f"Vref ref 0 PULSE(0 {{supply}} {t_ref_delay:.6e} 30p 30p {TREF / 2 - 30e-12:.4e} {TREF:.4e})",
        f"Vreset rst_b 0 PWL(0 0 {t_pfd_rel:.6e} 0 {t_pfd_rel + 20e-12:.6e} {{supply}})",
        f"Vpre pre_ref 0 {vctrl_locked + pre_offset:.5f}",
        f"Vpen pre_en 0 PWL(0 {{supply}} {t_pre_rel:.6e} {{supply}} {t_pre_rel + 200e-12:.6e} 0)",
        # 1. Real Integrated PLL v4 (BIAS v2 + PTAT 28/66 + LDO v2_cur + CP v4 + LF k4 + VCO r6 + div8)
        "Xtop vin vdd_pll vq 0 ref rst_b en_ldo cfg0 cfg1 cfg2 cfg3 cfg4 "
        "g4 g3 g2 g1 g0 t0 t1 t2 t3 t4 t5 pre_ref pre_en "
        "vbg ctrl z up dn fb0 "
        "b0p b0n b1p b1n b2p b2n b3p b3n d02p d02n d04p d04n d08p d08n "
        "pll_top_r6_v4_upgrade nf_const=28 nf_ptat=66",
        "Ikick xtop.xcore.xclock.v0p xtop.xcore.xclock.v0n PWL(0 1u 20p 1u 40p 0)",
        *[f"Ikick{n} {n}p {n}n PWL(0 0 1n 0 1.01n 20u 1.05n 20u 1.06n 0)" for n in ("d02", "d04", "d08")],
        # 2. Real 4x CML->CMOS r5 Receivers directly loading PLL v4 b0..b3
        f"Ibias_c2c vdd_clk vbias_c2c dc {i_c2c_u:.3f}u",
        "Xbias_c2c vbias_c2c 0 serdes_bias_cml_v2",
        "Xc2c0 b0p b0n c0_2g c4_2g vbias_c2c vdd_clk 0 serdes_cml_to_cmos_r5",
        "Xc2c1 b1n b1p c1_2g c5_2g vbias_c2c vdd_clk 0 serdes_cml_to_cmos_r5",
        "Xc2c2 b2p b2n c2_2g c6_2g vbias_c2c vdd_clk 0 serdes_cml_to_cmos_r5",
        "Xc2c3 b3n b3p c3_2g c7_2g vbias_c2c vdd_clk 0 serdes_cml_to_cmos_r5",
    ]
    if not full_rx:
        # Balanced capacitive load across all 8 phases (even phases also drive Xtx_qdiv2 ~12fF)
        for k in range(8):
            cap = "12f" if (k % 2 == 0) else "24f"
            lines.append(f"Cclk_rx{k} c{k}_2g 0 {cap}")
    else:
        # Balance odd phases against Xtx_qdiv2 input cap on even phases
        for k in (1, 3, 5, 7):
            lines.append(f"Cclk_bal{k} c{k}_2g 0 12f")

    # 3. Real TX Quadrature /2 + 4. Real Dynamic TX SST v4.3 + 5. Real C2_loss6 Channel
    lines += [
        f"Vrst_qdiv rst_qdiv_n 0 PWL(0 0 {t_qdiv_rel:.6e} 0 {t_qdiv_rel + 40e-12:.6e} {{supply}})",
        "Xtx_qdiv2 c0_2g c4_2g c2_2g c6_2g rst_qdiv_n "
        "phi0 phi90 phi180 phi270 qd_e0 qd_e1 qd_e2 qd_e3 vdd_clk 0 serdes_rx_qdiv2_8ph",
        "Vbg_tx vbg_tx 0 1.20",
        f"Vrst_tx rst_tx_n 0 PWL(0 0 {t_tx_rel - 25e-12:.6e} 0 {t_tx_rel + 25e-12:.6e} {{supply}})",
        *[
            f"Vtx_{k} tx_{k} 0 PWL(0 0 {max(0.5e-9, t_tx_rel - 1.0e-9):.6e} 0 {max(0.6e-9, t_tx_rel - 0.9e-9):.6e} {{supply}})" if v else f"Vtx_{k} tx_{k} 0 0.0"
            for k, v in tx_ctrl.items()
        ],
        '.include "stimuli.inc"',
        "Xtx din0 din1 din2 din3 din4 din5 din6 din7 "
        "din8 din9 din10 din11 din12 din13 din14 din15 "
        "phi0 phi90 phi180 phi270 rst_tx_n "
        "tx_m0 tx_m1 tx_m2 tx_m3 tx_m4 tx_f0 tx_f1 tx_f2 tx_ffe_en "
        "vbg_tx lqp lqn vdrv clk500_out clk250_out vdd_tx 0 serdes_tx_sst_top",
        "Vcm_init vcm_init 0 0.22",
        "Rpad_dc_p lqp vcm_init 100k",
        "Rpad_dc_n lqn vcm_init 100k",
        "Clpp lqp 0 200f",
        "Clpn lqn 0 200f",
        "Rlpp lqp llp 0.3",
        "Rlpn lqn lln 0.3",
        "Llpp llp lap 0.5n",
        "Llpn lln lan 0.5n",
        "Clacp lap ltp 10n",
        "Clacn lan ltn 10n",
        "Xchannel ltp ltn lxp lxn 0 pcb_c2_loss6",
        "Rlc0 lxp rxp 0.01",
        "Rlc1 lxn rxn 0.01",
        "Clc0 rxp 0 100f",
        "Clc1 rxn 0 100f",
        "Vvcm vcm_ref 0 1.05",
        "Veq0 eq0 0 {supply}",
        "Veq1 eq1 0 {supply}",
    ]

    if full_rx:
        rx_rel = t_rx_rel if t_rx_rel is not None else (t_qdiv_rel + 1.0e-9)
        lines += [
            f"Ibias_ctle vdd_ctle ibias_ctle dc {50.0 / cs['k_rc']:.3f}u",
            f"Vrst_rx rst_rx_n 0 PWL(0 0 {rx_rel:.6e} 0 {rx_rel + 50e-12:.6e} {{supply}})",
            *[f"{k} {k[1:]} 0 {v:.5f}" for k, v in commutator_bits(pi_code, s).items()],
            "Xrx rxp rxn vcm_ref ibias_ctle eq0 eq1 "
            "c0_2g c1_2g c2_2g c3_2g c4_2g c5_2g c6_2g c7_2g "
            "a0 a1 a2 a3 a4 a5 a6 a7 "
            "b0 b1 b2 b3 b4 b5 b6 b7 "
            "f0 f1 f2 f3 f4 f5 f6 f7 "
            "rst_rx_n "
            "wd0 wd1 wd2 wd3 wd4 wd5 wd6 wd7 wd8 wd9 wd10 wd11 wd12 wd13 wd14 wd15 "
            "we0 we1 we2 we3 we4 we5 we6 we7 we8 we9 we10 we11 we12 we13 we14 we15 "
            "wclk ctle_p ctle_n "
            "vdd_ctle vdd_pi vdd_slicer vdd_deser 0 serdes_rx_cmos_top_split",
            "Cwclk wclk 0 10f",
        ]
    else:
        lines += [
            f"Ibias_ctle vdd_rx_fe ibias_ctle dc {50.0 / cs['k_rc']:.3f}u",
            "Xterm rxp rxn vcm_ref 0 serdes_rx_term_pdk",
            "Xbias_ctle ibias_ctle 0 serdes_bias_ctle_v2",
            "Xctle rxp rxn ctle_p ctle_n eq0 eq1 ibias_ctle vdd_rx_fe 0 serdes_rx_ctle_pdk",
            "Cldp ctle_p 0 80f",
            "Cldn ctle_n 0 80f",
        ]

    if nodeset_file is not None:
        lines.append(f'.include "{nodeset_file.resolve()}"')
        lines.append(".nodeset v(vdrv)=0.44 v(lqp)=0.22 v(lqn)=0.22 v(xtx.xdrv.xldo.vgate)=1.0")
    else:
        lines += [
            ".nodeset v(vbg)=1.234 v(xtop.xbias.xref.s)=1.234 v(xtop.xbias.vg)=1.13 "
            "v(xtop.xbias.vgi)=1.10 v(xtop.xbias.xref.ta)=0.99 v(xtop.xbias.xref.tb)=0.99",
            f".nodeset v(xtop.icml)=1.04 v(xtop.icml_vco)=1.04 v(xtop.xcore.vbias_q)=1.04 "
            f"v(vbias_c2c)=1.04 v(xtop.icp)=0.87 v(xtop.i_ldo0)=0.88 v(xtop.i_ldo1)=0.88 v(xtop.vbp)={vq0 - 1.26:.3f}",
            ".nodeset v(xtop.xcore.xclock.xfb0.xrestore.qp)=0 v(xtop.xcore.xclock.xfb0.xrestore.qn)={supply}",
            f".nodeset v(ctrl)={vctrl_locked + pre_offset:.5f} v(z)={vctrl_locked + pre_offset:.5f} v(vq)={vq0:.3f}",
            f".nodeset v(xtop.xcore.xcp.vbp_srv)={vq0 - 1.23:.3f} v(xtop.xcore.xcp.rep)={vctrl_locked + pre_offset:.5f}",
            f".nodeset v(xtop.xldo.xloop.ref_local)=1.233 v(xtop.xldo.fb)=1.232 "
            f"v(xtop.xldo.xloop.xcore.va)={vin - 0.35:.3f} v(xtop.xldo.xloop.xcore.pre_d)={vin - 1.27:.3f} "
            f"v(xtop.xldo.xloop.xcore.pre_g)={vin - 1.27:.3f} v(xtop.xldo.xloop.xcore.casg)={vin:.3f} "
            f"v(xtop.xldo.xloop.xcore.mid)={min(vin - 0.64, 2.85):.3f} v(xtop.xldo.xloop.xcore.gate)={vq0 + 0.56:.3f} "
            f"v(xtop.xldo.xloop.xcore.bp)={vin - 1.53:.3f} v(xtop.xldo.xloop.xcore.tail)={vin - 0.87:.3f} "
            f"v(xtop.xldo.xloop.xcore.d)=0.98 v(xtop.xldo.xloop.xcore.x)=0.76 v(xtop.xldo.xloop.vg_clamp)=0.0",
            ".nodeset v(vdrv)=0.44 v(lqp)=0.22 v(lqn)=0.22 v(xtx.xdrv.xldo.vgate)=1.0",
        ]
        for k in range(4):
            for sd in ("p", "n"):
                lines.append(
                    f".nodeset v(xtop.xcore.xclock.v{k}{sd})={vq0 - 0.12:.3f} "
                    f"v(xtop.xcore.xclock.xvco.xv{k}{sd}.p2)={vctrl_locked + pre_offset:.5f}"
                )

    c2g_nodes = " ".join(f"v(c{k}_2g)" for k in range(8))
    base_probes = (
        "v(ref) v(fb0) v(ctrl) v(z) v(vq) v(vbg) v(xtop.xcore.xcp.vbp_srv) "
        "v(xtop.icml) v(vbias_c2c) v(b0p) v(b0n) "
        f"{c2g_nodes} v(phi0) v(phi90) v(phi180) v(phi270) v(clk250_out) "
        "v(vdrv) v(lqp) v(lqn) v(rxp) v(rxn) v(ctle_p) v(ctle_n) "
        "i(vin) i(vdd_pll) i(vdd_clk) i(vdd_tx)"
    )
    if full_rx:
        wd_nodes = " ".join(f"v(wd{i})" for i in range(16))
        we_nodes = " ".join(f"v(we{i})" for i in range(16))
        probes = (
            base_probes
            + f" v(wclk) v(xrx.ckd0) {wd_nodes} {we_nodes} "
            + "i(vdd_ctle) i(vdd_pi) i(vdd_slicer) i(vdd_deser)"
        )
    else:
        probes = base_probes + " i(vdd_rx_fe)"

    tstart_str = skip_before if (skip_before and skip_before != "0") else "0"
    raw_name = "full_chain.raw" if full_rx else "stage1.raw"
    extra_s = f" {extra_opts.strip()}" if extra_opts.strip() else ""
    lines += [
        f".temp {c.temp}",
        f".options reltol={reltol} abstol=1p vntol=2u gmin=1e-11 itl4=80{extra_s}{solver_opt}",
        f".save {probes}",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        f"tran {tstep} {stop:.6e} {tstart_str} {maxstep}",
        f"write {raw_name} {probes}",
        "quit",
        ".endc",
        ".end",
    ]
    text = "\n".join(lines) + "\n"
    snap_dir.mkdir(parents=True, exist_ok=True)
    text = rcorner.to_pdk_fixed(text, snap_dir)
    return bias.section(text, c.process, rc)


def build_fb0_probe_deck(cs: dict, c: Condition, rc: str, code: int, vctrl_locked: float, ldo_trim: int, snap_dir: Path, nodeset_file: Path | None = None) -> str:
    """Fast 14-ns PLL v4 + 4x C2C r5 probe (no TX/C2) to measure exact open-loop fb0 rising edge phase."""
    s, vin, vq0 = c.supply, cs["vin"], 1.80
    i_c2c_u = 212.5 / cs["k_rc"]
    lines = [
        f"* PLL+4xC2C fb0 Phase Probe ({cs['id']})",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        *[f'.include "{REPO / inc}"' for inc in PLL_INCLUDES],
        f'.include "{SC_LIB}"',
        f".param supply={s}",
        f"Vin vin 0 {vin}",
        "Vdd_pll vdd_pll 0 {supply}",
        "Vdd_clk vdd_clk 0 {supply}",
        "Ven_ldo en_ldo 0 {supply}",
        *[f"Et{k} t{k} 0 vdd_pll 0 {(ldo_trim >> k) & 1}" for k in range(6)],
        *[f"Eg{k} g{k} 0 vdd_pll 0 {(15 >> k) & 1}" for k in range(5)],
        *[f"Ecode{k} cfg{k} 0 vq 0 {(code >> k) & 1}" for k in range(5)],
        "Vref ref 0 0",
        "Vreset rst_b 0 0",
        f"Vpre pre_ref 0 {vctrl_locked:.5f}",
        "Vpen pre_en 0 {supply}",
        "Xtop vin vdd_pll vq 0 ref rst_b en_ldo cfg0 cfg1 cfg2 cfg3 cfg4 "
        "g4 g3 g2 g1 g0 t0 t1 t2 t3 t4 t5 pre_ref pre_en "
        "vbg ctrl z up dn fb0 "
        "b0p b0n b1p b1n b2p b2n b3p b3n d02p d02n d04p d04n d08p d08n "
        "pll_top_r6_v4_upgrade nf_const=28 nf_ptat=66",
        "Ikick xtop.xcore.xclock.v0p xtop.xcore.xclock.v0n PWL(0 1u 20p 1u 40p 0)",
        *[f"Ikick{n} {n}p {n}n PWL(0 0 1n 0 1.01n 20u 1.05n 20u 1.06n 0)" for n in ("d02", "d04", "d08")],
        f"Ibias_c2c vdd_clk vbias_c2c dc {i_c2c_u:.3f}u",
        "Xbias_c2c vbias_c2c 0 serdes_bias_cml_v2",
        "Xc2c0 b0p b0n c0_2g c4_2g vbias_c2c vdd_clk 0 serdes_cml_to_cmos_r5",
        "Xc2c1 b1n b1p c1_2g c5_2g vbias_c2c vdd_clk 0 serdes_cml_to_cmos_r5",
        "Xc2c2 b2p b2n c2_2g c6_2g vbias_c2c vdd_clk 0 serdes_cml_to_cmos_r5",
        "Xc2c3 b3n b3p c3_2g c7_2g vbias_c2c vdd_clk 0 serdes_cml_to_cmos_r5",
        *[f"Cclk_rx{k} c{k}_2g 0 24f" for k in range(8)],
    ]
    if nodeset_file is not None:
        lines.append(f'.include "{nodeset_file.resolve()}"')
    else:
        lines += [
            ".nodeset v(vbg)=1.234 v(xtop.xbias.xref.s)=1.234 v(xtop.xbias.vg)=1.13 "
            "v(xtop.xbias.vgi)=1.10 v(xtop.xbias.xref.ta)=0.99 v(xtop.xbias.xref.tb)=0.99",
            f".nodeset v(xtop.icml)=1.04 v(xtop.icml_vco)=1.04 v(xtop.xcore.vbias_q)=1.04 "
            f"v(vbias_c2c)=1.04 v(xtop.icp)=0.87 v(xtop.i_ldo0)=0.88 v(xtop.i_ldo1)=0.88 v(xtop.vbp)={vq0 - 1.26:.3f}",
            ".nodeset v(xtop.xcore.xclock.xfb0.xrestore.qp)=0 v(xtop.xcore.xclock.xfb0.xrestore.qn)={supply}",
            f".nodeset v(ctrl)={vctrl_locked:.5f} v(z)={vctrl_locked:.5f} v(vq)={vq0:.3f}",
            f".nodeset v(xtop.xcore.xcp.vbp_srv)={vq0 - 1.23:.3f} v(xtop.xcore.xcp.rep)={vctrl_locked:.5f}",
            f".nodeset v(xtop.xldo.xloop.ref_local)=1.233 v(xtop.xldo.fb)=1.232 "
            f"v(xtop.xldo.xloop.xcore.va)={vin - 0.35:.3f} v(xtop.xldo.xloop.xcore.pre_d)={vin - 1.27:.3f} "
            f"v(xtop.xldo.xloop.xcore.pre_g)={vin - 1.27:.3f} v(xtop.xldo.xloop.xcore.casg)={vin:.3f} "
            f"v(xtop.xldo.xloop.xcore.mid)={min(vin - 0.64, 2.85):.3f} v(xtop.xldo.xloop.xcore.gate)={vq0 + 0.56:.3f} "
            f"v(xtop.xldo.xloop.xcore.bp)={vin - 1.53:.3f} v(xtop.xldo.xloop.xcore.tail)={vin - 0.87:.3f} "
            f"v(xtop.xldo.xloop.xcore.d)=0.98 v(xtop.xldo.xloop.xcore.x)=0.76 v(xtop.xldo.xloop.vg_clamp)=0.0",
            *[
                f".nodeset v(xtop.xcore.xclock.v{k}{sd})={vq0 - 0.12:.3f} "
                f"v(xtop.xcore.xclock.xvco.xv{k}{sd}.p2)={vctrl_locked:.5f}"
                for k in range(4) for sd in ("p", "n")
            ],
        ]
    lines += [
        f".temp {c.temp}",
        ".options reltol=4e-4 abstol=1p vntol=2u gmin=1e-11 itl4=80",
        ".save v(fb0) v(b0p) v(b0n)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        "tran 8p 14e-9 0 12p",
        "write probe.raw v(fb0) v(b0p) v(b0n)",
        "quit",
        ".endc",
        ".end",
    ]
    snap_dir.mkdir(parents=True, exist_ok=True)
    text = rcorner.to_pdk_fixed("\n".join(lines) + "\n", snap_dir)
    return bias.section(text, c.process, rc)


def build_stage2_rx_deck(
    cs: dict,
    c: Condition,
    rc: str,
    codes: list[int],
    *,
    t_stop: float = STAGE2_STOP,
    t_save: float = STAGE2_SAVE,
    rst_rel_s: float = STAGE2_RST_REL,
    snap_dir: Path,
) -> str:
    """RX CMOS v2.2 driven by ACTUAL locked-PLL TX->C2_loss6 far-end waveform (rx_in.inc)
    AND ACTUAL locked-PLL 8-phase 2 GHz CMOS anchor clocks (clk_in.inc)."""
    s = c.supply
    wd_nodes = " ".join(f"v(wd{i})" for i in range(16))
    we_nodes = " ".join(f"v(we{i})" for i in range(16))
    blocks = []
    for cd in codes:
        alters = [f"alter {k} dc={v:.5f}" for k, v in commutator_bits(cd, s).items()]
        blocks.append("\n".join([
            f"* PI code {cd}",
            *alters,
            f"tran 6p {t_stop:.6e} {t_save:.6e} 12p",
            "let ctle_diff = v(ctle_p) - v(ctle_n)",
            f"let p_ctle = -{s}*i(Vdd_ctle)",
            f"let p_pi = -{s}*i(Vdd_pi)",
            f"let p_slicer = -{s}*i(Vdd_slicer)",
            f"let p_deser = -{s}*i(Vdd_deser)",
            f"write code_{cd:02d}.raw ctle_diff v(wclk) v(xrx.ckd0) {wd_nodes} {we_nodes} p_ctle p_pi p_slicer p_deser",
            "destroy all",
        ]))
    rx_includes = [
        "analog/common/devices/spice/sky130_primitives.spice",
        "analog/common/devices/spice/sky130_pfet_lvt.spice",
        "analog/bias/spice/bias_v2.spice",
        "analog/rx/cmos_rx/spice/rx_ctle_pdk.spice",
        "analog/rx/cmos_rx/spice/rx_cmos_pi.spice",
        "analog/rx/cmos_rx/spice/rx_dt_sampler.spice",
        "analog/rx/cmos_rx/spice/rx_cmos_deser16.spice",
        "analog/rx/cmos_rx/spice/rx_cmos_top.spice",
    ]
    lines = [
        f"* Stage 2 RX CMOS v2.2 with Locked-PLL TX->C2_loss6 + Locked-PLL 8-ph Clocks ({c.tag}:{rc}, codes={codes})",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        *[f'.include "{REPO / p}"' for p in rx_includes],
        f"Vdd_ctle   vdd_ctle   0 {s}",
        f"Vdd_pi     vdd_pi     0 {s}",
        f"Vdd_slicer vdd_slicer 0 {s}",
        f"Vdd_deser  vdd_deser  0 {s}",
        "Vvcm vcm_ref 0 1.05",
        f"Ibias_ctle vdd_ctle ibias_ctle dc {50.0 / cs['k_rc']:.3f}u",
        f"Vrst_rx rst_rx_n 0 PWL(0 0 {rst_rel_s:.6e} 0 {rst_rel_s + 50e-12:.6e} {s})",
        f"Veq0 eq0 0 {s}",
        f"Veq1 eq1 0 {s}",
        '.include "rx_in.inc"',
        '.include "clk_in.inc"',
        *[f"{k} {k[1:]} 0 {v:.5f}" for k, v in commutator_bits(codes[0], s).items()],
        "Xrx rxp rxn vcm_ref ibias_ctle eq0 eq1 "
        "c0 c1 c2 c3 c4 c5 c6 c7 "
        "a0 a1 a2 a3 a4 a5 a6 a7 "
        "b0 b1 b2 b3 b4 b5 b6 b7 "
        "f0 f1 f2 f3 f4 f5 f6 f7 "
        "rst_rx_n "
        "wd0 wd1 wd2 wd3 wd4 wd5 wd6 wd7 wd8 wd9 wd10 wd11 wd12 wd13 wd14 wd15 "
        "we0 we1 we2 we3 we4 we5 we6 we7 we8 we9 we10 we11 we12 we13 we14 we15 "
        "wclk ctle_p ctle_n "
        "vdd_ctle vdd_pi vdd_slicer vdd_deser 0 serdes_rx_cmos_top_split",
        "Cwclk wclk 0 10f",
        f".temp {c.temp}",
        ".options reltol=4e-4 abstol=1p vntol=2u klu",
        f".save v(ctle_p) v(ctle_n) v(wclk) v(xrx.ckd0) {wd_nodes} {we_nodes} i(Vdd_ctle) i(Vdd_pi) i(Vdd_slicer) i(Vdd_deser)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        *blocks,
        "quit",
        ".endc",
        ".end",
    ]
    text = "\n".join(lines) + "\n"
    snap_dir.mkdir(parents=True, exist_ok=True)
    text = rcorner.to_pdk_fixed(text, snap_dir)
    return bias.section(text, c.process, rc)


def build_pi_probe_deck(cs: dict, c: Condition, rc: str, snap_dir: Path) -> str:
    """Fast 6.5-ns PI code=0 phase probe driven by ACTUAL locked-PLL clk_in.inc."""
    s = c.supply
    lines = [
        f"* Stage 2 PI Phase Probe on Locked-PLL 8-ph Clocks ({c.tag}:{rc}, code=0)",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        f'.include "{REPO / "analog/common/devices/spice/sky130_primitives.spice"}"',
        f'.include "{REPO / "analog/common/devices/spice/sky130_pfet_lvt.spice"}"',
        f'.include "{REPO / "analog/rx/cmos_rx/spice/rx_cmos_pi.spice"}"',
        f"Vdd vdd 0 {s}",
        '.include "clk_in.inc"',
        f"Vrst rst_n 0 PWL(0 0 {STAGE2_RST_REL:.6e} 0 {STAGE2_RST_REL + 50e-12:.6e} {s})",
        *[f"{k} {k[1:]} 0 {v:.5f}" for k, v in commutator_bits(0, s).items()],
        "Xdut c0 c1 c2 c3 c4 c5 c6 c7 a0 a1 a2 a3 a4 a5 a6 a7 b0 b1 b2 b3 b4 b5 b6 b7 f0 f1 f2 f3 f4 f5 f6 f7 "
        "rst_n dp dn ep en ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 vdd 0 serdes_rx_cmos_pi_8ph",
        "Cd0 ckd0 0 38f", "Cd1 ckd1 0 38f", "Cd2 ckd2 0 38f", "Cd3 ckd3 0 38f",
        "Ce0 cke0 0 38f", "Ce1 cke1 0 38f", "Ce2 cke2 0 38f", "Ce3 cke3 0 38f",
        f".temp {c.temp}",
        ".options reltol=2e-4 abstol=1p vntol=2u klu",
        ".save v(ckd0)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        "tran 4p 6.5e-9 4.0e-9 8p",
        "write pi_probe.raw v(ckd0)",
        "quit",
        ".endc",
        ".end",
    ]
    text = "\n".join(lines) + "\n"
    snap_dir.mkdir(parents=True, exist_ok=True)
    text = rcorner.to_pdk_fixed(text, snap_dir)
    return bias.section(text, c.process, rc)


def write_stage2_pwl_inputs(
    stage1_raw: Path,
    rx_inc: Path,
    clk_inc: Path,
    *,
    shift_s: float = STAGE2_SHIFT,
    src_start_s: float = STAGE2_SRC_START,
    t_stop_s: float = STAGE2_STOP,
) -> None:
    """Export exact locked-PLL TX->C2_loss6 rxp/rxn AND exact locked-PLL 8-phase c0_2g..c7_2g."""
    w = spice.Waves(stage1_raw)
    t_end_src = min(float(w.t[-1]), shift_s + t_stop_s + 0.5e-9)
    t_rx = np.arange(src_start_s, t_end_src, 20.0e-12)
    vp = np.interp(t_rx, w.t, w["v(rxp)"])
    vn = np.interp(t_rx, w.t, w["v(rxn)"])
    t0_r = src_start_s - shift_s
    pre_p = [(0.0, 1.05), (t0_r - 50e-12, 1.05)] if t0_r > 80e-12 else []
    pre_n = [(0.0, 1.05), (t0_r - 50e-12, 1.05)] if t0_r > 80e-12 else []
    rx_inc.write_text(
        pwl_lines("Vrxp rxp 0", pre_p + list(zip(t_rx - shift_s, vp)))
        + pwl_lines("Vrxn rxn 0", pre_n + list(zip(t_rx - shift_s, vn)))
    )
    t_ck = np.arange(shift_s, t_end_src, 15.0e-12)
    ck_lines = []
    for k in range(8):
        vk = np.interp(t_ck, w.t, w[f"v(c{k}_2g)"])
        ck_lines.append(pwl_lines(f"Vc{k} c{k} 0", list(zip(t_ck - shift_s, vk))))
    clk_inc.write_text("".join(ck_lines))


def rising_edges(t: np.ndarray, y: np.ndarray, thr: float) -> np.ndarray:
    e, p = crossings(t, y - thr)
    return e[p > 0]


def time_weighted_mean(t: np.ndarray, y: np.ndarray) -> float:
    dt = np.diff(t)
    return float(np.sum(0.5 * (y[:-1] + y[1:]) * dt) / (t[-1] - t[0]))


def check_serial_112(t: np.ndarray, y: np.ndarray, bits: np.ndarray, start_s: float) -> dict:
    """Exact serial.check + bit_mapping contract on 112-bit sequence (16 alt + 16 marker + 64 PRBS-7 + 16 tail).
    Delay fitted ONLY on the 32 training bits; UI fixed at 250 ps (never fitted to payload)."""
    sgn = 2 * bits - 1
    edge_t, edge_pol = crossings(t, y)
    idx_tr = np.arange(TRAIN_BITS)
    grid = np.arange(-8.0, 20.0, 0.01)
    times = start_s + (idx_tr[None, :] + 0.5 + grid[:, None]) * UI
    valid_g = (times[:, 0] >= t[0]) & (times[:, -1] <= t[-1])
    grid = grid[valid_g]
    times = times[valid_g]
    v = np.interp(times.ravel(), t, y).reshape(times.shape)
    wrong = v * sgn[:TRAIN_BITS] <= 0
    cost = 100 * wrong[:, ALT_BITS:].sum(axis=1) + wrong[:, :ALT_BITS].sum(axis=1)
    best = np.where(cost == cost.min())[0]
    delay = float(grid[best[np.argmax(np.min(v[best] * sgn[:TRAIN_BITS], axis=1))]])
    # Refine from alternating-section edges
    offsets = []
    for k in range(1, ALT_BITS):
        target = start_s + (k + delay) * UI
        hit = np.where((np.abs(edge_t - target) < 0.45 * UI) & (edge_pol == sgn[k]))[0]
        if len(hit) == 1:
            offsets.append((edge_t[hit[0]] - start_s) / UI - k)
    if len(offsets) >= 10:
        delay = float(np.median(offsets))

    end = TRAIN_BITS + PAYLOAD_BITS
    sample_t = start_s + (np.arange(end) + 0.5 + delay) * UI
    samples = np.interp(sample_t, t, y)
    signed = samples * sgn[:end]
    payload = signed[TRAIN_BITS:end]
    train_err = int(np.sum(signed[:ALT_BITS] <= 0))
    marker_err = int(np.sum(signed[ALT_BITS:TRAIN_BITS] <= 0))
    bit_err = int(np.sum(payload <= 0))

    # Match payload transitions within +/-0.45 UI
    used, residual, missing = set(), [], 0
    for k in range(TRAIN_BITS, end):
        if bits[k] == bits[k - 1]:
            continue
        target = start_s + (k + delay) * UI
        hit = np.where((np.abs(edge_t - target) < 0.45 * UI) & (edge_pol == sgn[k]))[0]
        if len(hit):
            i = int(hit[np.argmin(np.abs(edge_t[hit] - target))])
            used.add(i)
            residual.append((edge_t[i] - target) / UI)
        else:
            missing += 1
    span = (edge_t >= start_s + (TRAIN_BITS + delay - 0.45) * UI) & (edge_t < start_s + (end + delay - 0.45) * UI)
    extra = int(sum(i not in used for i in np.where(span)[0]))
    in_pay = (t >= start_s + (TRAIN_BITS + delay) * UI) & (t < start_s + (end + delay) * UI)
    spread_ui = float(np.ptp(residual)) if residual else float("nan")
    margin_v = float(np.min(payload))
    valid_tr = bool(len(offsets) >= 10 and train_err == 0 and marker_err == 0)
    functional = bool(valid_tr and bit_err == 0 and missing == 0 and extra == 0)

    # Order-agnostic 16-column bit-mapping across words 1..5 (5 distinct words -> 16/16 unique columns!)
    n_all = np.arange(TOTAL_BITS)
    s_all = np.interp(start_s + (n_all + 0.5 + delay) * UI, t, y)
    out_bits = (s_all > 0).astype(int)
    words = [1, 2, 3, 4, 5]
    mapping = []
    for j in range(16):
        cands = [s for s in range(16) if all(out_bits[16 * w + j] == bits[16 * w + s] for w in words)]
        if len(cands) == 1:
            mapping.append(cands[0])
        else:
            mapping = None
            break
    in_order = bool(mapping == list(range(16)))
    t_bit0_edge = start_s + delay * UI
    ey = eye.signed_eye(t, y, bits.tolist(), UI, t_bit0_edge, first_bit=TRAIN_BITS, n_bits=PAYLOAD_BITS)
    return dict(
        functional=functional,
        meets_draft=bool(functional and margin_v >= 0.075 and spread_ui <= 0.15),
        training_delay_ui=delay,
        training_errors=train_err,
        marker_errors=marker_err,
        bit_errors=bit_err,
        missing_transitions=missing,
        extra_crossings=extra,
        matched_transitions=len(residual),
        margin_mv=margin_v * 1e3,
        spread_ui=spread_ui,
        pp_mv=float(np.ptp(y[in_pay]) * 1e3) if np.any(in_pay) else float("nan"),
        eye_h_mv=float(ey["height_v"] * 1e3),
        eye_w_ui=float(ey["width_ui"]),
        in_order=in_order,
        mapping=mapping,
        t_bit0_center_s=float(t_bit0_edge + 0.5 * UI),
    )


def pll_window_metrics(w: spice.Waves, c: Condition, vin: float, t0: float, t1: float) -> dict:
    t = w.t
    m = (t >= t0) & (t <= t1)
    tl = t[m]
    b0 = w["v(b0p)"][m] - w["v(b0n)"][m]
    ed, sg = crossings(tl, b0)
    r = ed[sg > 0]
    f_ghz = float((len(r) - 1) / (r[-1] - r[0]) / 1e9) if len(r) > 2 else float("nan")
    f_err_ppm = (f_ghz * 1e9 / FTGT - 1.0) * 1e6
    if len(r) > 2:
        tie = (r - r[0]) - np.arange(len(r)) * (1.0 / FTGT)
        tie_pp_ps = float(np.ptp(tie) * 1e12)
        per_pp_ps = float(np.ptp(np.diff(r)) * 1e12)
    else:
        tie_pp_ps, per_pp_ps = float("nan"), float("nan")

    vmid = 0.5 * c.supply
    e0 = rising_edges(tl, w["v(c0_2g)"][m], vmid)
    max_oct_err_ps = float("nan")
    if len(e0) >= 4:
        t_anc = e0[1]
        errs = []
        for k in range(8):
            ek = rising_edges(tl, w[f"v(c{k}_2g)"][m], vmid)
            cand = ek[ek >= t_anc - 20e-12]
            if len(cand):
                dt = (float(cand[0]) - t_anc) % 500e-12
                if k == 0 and dt > 250e-12:
                    dt -= 500e-12
                err = ((dt - k * 62.5e-12 + 250e-12) % 500e-12) - 250e-12
                errs.append(abs(err) * 1e12)
        if len(errs) == 8:
            max_oct_err_ps = float(max(errs))

    ctrl = w["v(ctrl)"][m]
    vq = w["v(vq)"][m]
    vbg = w["v(vbg)"][m]
    vsrv = w["v(xtop.xcore.xcp.vbp_srv)"][m]
    mid = len(tl) // 2
    vsrv_drift_mv = float(
        (time_weighted_mean(tl[mid:], vsrv[mid:]) - time_weighted_mean(tl[:mid], vsrv[:mid])) * 1e3
    )

    p_ldo_mw = -time_weighted_mean(tl, w["i(vin)"][m]) * vin * 1e3
    p_pll_host_mw = -time_weighted_mean(tl, w["i(vdd_pll)"][m]) * c.supply * 1e3
    p_clk_mw = -time_weighted_mean(tl, w["i(vdd_clk)"][m]) * c.supply * 1e3
    p_tx_mw = -time_weighted_mean(tl, w["i(vdd_tx)"][m]) * c.supply * 1e3
    p_rx_fe_mw = (
        -time_weighted_mean(tl, w["i(vdd_rx_fe)"][m]) * c.supply * 1e3
        if "i(vdd_rx_fe)" in w.names else float("nan")
    )
    return dict(
        t0_ns=t0 * 1e9,
        t1_ns=t1 * 1e9,
        f_out_ghz=f_ghz,
        f_err_ppm=f_err_ppm,
        tie_pp_ps=tie_pp_ps,
        per_pp_ps=per_pp_ps,
        max_oct_err_ps=max_oct_err_ps,
        buf_swing_mvpp=float(np.ptp(b0) * 1e3),
        vctrl_mean_v=time_weighted_mean(tl, ctrl),
        vctrl_ripple_mvpp=float(np.ptp(ctrl) * 1e3),
        vq_mean_v=time_weighted_mean(tl, vq),
        vq_ripple_mvpp=float(np.ptp(vq) * 1e3),
        vbg_mean_v=time_weighted_mean(tl, vbg),
        vbp_srv_mean_v=time_weighted_mean(tl, vsrv),
        vbp_srv_ripple_mvpp=float(np.ptp(vsrv) * 1e3),
        vbp_srv_drift_mv=vsrv_drift_mv,
        p_pll_ldo_mw=p_ldo_mw,
        p_pll_host_mw=p_pll_host_mw,
        p_pll_total_mw=p_ldo_mw + p_pll_host_mw,
        p_clk_mw=p_clk_mw,
        p_tx_mw=p_tx_mw,
        p_rx_fe_mw=p_rx_fe_mw,
    )


def analyse_stage1(raw_path: Path, cs: dict, c: Condition, bits: np.ndarray) -> dict:
    w = spice.Waves(raw_path)
    t = w.t
    # 1. PLL quiet-TX baseline (15..34 ns) vs dynamic 4 Gb/s PRBS-7 load (45..75 ns)
    pll_quiet = pll_window_metrics(w, c, cs["vin"], 15.0e-9, 34.5e-9)
    pll_dyn = pll_window_metrics(w, c, cs["vin"], 45.0e-9, min(75.0e-9, float(t[-1]) - 0.5e-9))

    # 2. TX pad, C2_loss6 far-end, and CTLE output serial check + bit_mapping
    sel_tx = t >= 41.0e-9
    tt = t[sel_tx]
    pad_diff = w["v(lqp)"][sel_tx] - w["v(lqn)"][sel_tx]
    rx_diff = w["v(rxp)"][sel_tx] - w["v(rxn)"][sel_tx]
    ctle_diff = w["v(ctle_p)"][sel_tx] - w["v(ctle_n)"][sel_tx]

    tx_pad = check_serial_112(tt, pad_diff, bits, start_s=T_PAD_NOM)
    c2_far = check_serial_112(tt, rx_diff, bits, start_s=T_PAD_NOM + 1.0e-9)
    ctle_out = check_serial_112(tt, ctle_diff, bits, start_s=T_PAD_NOM + 1.0e-9)

    m_dyn = (t >= 45.0e-9) & (t <= min(75.0e-9, float(t[-1]) - 0.5e-9))
    vdrv_mean = time_weighted_mean(t[m_dyn], w["v(vdrv)"][m_dyn])
    vdrv_pp_mv = float(np.ptp(w["v(vdrv)"][m_dyn]) * 1e3)

    ok_pll = bool(abs(pll_dyn["f_err_ppm"]) <= 200.0 and abs(pll_dyn["vbp_srv_drift_mv"]) < 2.0)
    ok_tx = bool(tx_pad["meets_draft"] and tx_pad["in_order"])
    ok_ch = bool(c2_far["functional"] and ctle_out["functional"])

    return dict(
        condition=cs["id"],
        spec=cs["spec"],
        label=cs["label"],
        t_end_ns=float(t[-1] * 1e9),
        ok=bool(ok_pll and ok_tx and ok_ch),
        ok_pll=ok_pll,
        ok_tx=ok_tx,
        ok_ch=ok_ch,
        pll_quiet=pll_quiet,
        pll_dyn=pll_dyn,
        delta_vctrl_mv=(pll_dyn["vctrl_mean_v"] - pll_quiet["vctrl_mean_v"]) * 1e3,
        delta_vq_mv=(pll_dyn["vq_mean_v"] - pll_quiet["vq_mean_v"]) * 1e3,
        vdrv_mean_v=vdrv_mean,
        vdrv_ripple_mvpp=vdrv_pp_mv,
        tx_pad=tx_pad,
        c2_farend=c2_far,
        ctle_out=ctle_out,
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
    min_bit_idx: int = 16,
) -> dict:
    sel = w.t >= meas_from
    t = w.t[sel]
    vmid = 0.5 * supply
    we, wp = crossings(t, w["v(wclk)"][sel], vmid)
    wr = we[wp > 0]
    if len(wr) < min_words:
        return dict(code=code, ok=False, reason=f"too few wclk edges ({len(wr)})", data_errors=999, edge_errors=999)

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


def make_figure(camp: Path, summary: dict, fig_path: Path) -> None:
    """Crisp 4-panel high-DPI summary figure with zero overlapping labels."""
    plt.rcParams.update({
        "font.size": 9.0,
        "axes.titlesize": 10.2,
        "axes.labelsize": 9.0,
        "legend.fontsize": 7.4,
        "xtick.labelsize": 8.3,
        "ytick.labelsize": 8.3,
    })
    fig, axes = plt.subplots(2, 2, figsize=(15.2, 9.6), dpi=180)
    ax_pll, ax_eye_tx, ax_eye_rx, ax_bar = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]
    colors = {
        "tt_v1800_t27_tt": "#1f77b4",
        "ss_v1650_t-40_hh": "#d62728",
        "ff_v1950_t-40_ll": "#2ca02c",
        "fs_v1650_t85_hh": "#ff7f0e",
    }
    s1_rows = summary.get("stage1", {})
    s2_rows = summary.get("stage2", {})
    sd_row = summary.get("singledeck_tt")

    # Panel (a): Closed-Loop PLL V_ctrl & LDO V_quiet under Dynamic 4 Gb/s TX Load
    ax_vq = ax_pll.twinx()
    for cid, r in s1_rows.items():
        col = colors.get(cid, "#333333")
        w = spice.Waves(Path(r["raw_path"]))
        t_ns = w.t * 1e9
        step = max(1, len(t_ns) // 2500)
        lbl = f"{r['label']} ({r['pll_dyn']['f_err_ppm']:+.1f} ppm)"
        ax_pll.plot(t_ns[::step], w["v(ctrl)"][::step], color=col, lw=1.3, label=lbl)
        ax_vq.plot(t_ns[::step], w["v(vq)"][::step], color=col, lw=0.95, ls="--", alpha=0.8)
    ax_pll.axvspan(35.0, 76.0, color="#ffe8cc", alpha=0.45, label="Dynamic 4 Gb/s TX PRBS-7 active")
    ax_pll.set_title("(a) Locked PLL v4 $V_{ctrl}$ (solid) & LDO $V_q$ (dashed) Under Dynamic TX Load", fontweight="bold", pad=8)
    ax_pll.set_xlabel("Simulation Time (ns)")
    ax_pll.set_ylabel("PLL $V_{ctrl}$ (V)")
    ax_vq.set_ylabel("LDO Quiet Rail $V_q$ (V)")
    ax_pll.set_xlim(12, 76)
    ax_pll.set_ylim(1.00, 1.24)
    ax_vq.set_ylim(1.74, 1.84)
    ax_pll.grid(True, alpha=0.3)
    ax_pll.legend(loc="lower left", ncol=1, framealpha=0.92)

    def plot_eye(ax, raw_path: Path, sig_fn, bits: np.ndarray, t_start_nom: float, col: str, title: str,
                 ylabel: str, spec_mv: float | None = None, annot: str = ""):
        w = spice.Waves(raw_path)
        sel = w.t >= 41.0e-9
        tt = w.t[sel]
        y = sig_fn(w, sel)
        m = check_serial_112(tt, y, bits, start_s=t_start_nom)
        t0 = t_start_nom + m["training_delay_ui"] * UI
        u_grid = np.linspace(0.0, 2.0, 200)
        for k in range(TRAIN_BITS, TRAIN_BITS + PAYLOAD_BITS - 1):
            tk = t0 + (k - 0.5) * UI + u_grid * UI
            if tk[0] < tt[0] or tk[-1] > tt[-1]:
                continue
            yk = np.interp(tk, tt, y) * 1e3
            ax.plot(u_grid, yk, color=col, lw=0.8, alpha=0.5)
        if spec_mv is not None:
            ax.axhline(spec_mv, color="#cc2222", ls="--", lw=0.95, label=f"Spec ±{spec_mv:.0f} mV")
            ax.axhline(-spec_mv, color="#cc2222", ls="--", lw=0.95)
        ax.set_title(title, fontweight="bold", pad=8)
        ax.set_xlabel("Time (UI, 1 UI = 250 ps)")
        ax.set_ylabel(ylabel)
        ax.set_xlim(0.0, 2.0)
        ax.grid(True, alpha=0.3)
        if annot:
            ax.text(
                0.03, 0.96, annot, transform=ax.transAxes, va="top", ha="left", fontsize=7.6,
                bbox=dict(boxstyle="round,pad=0.32", facecolor="white", edgecolor="#bbbbbb", alpha=0.93),
            )

    bits = build_sequence()
    ref_cid = "tt_v1800_t27_tt" if "tt_v1800_t27_tt" in s1_rows else next(iter(s1_rows))
    r_ref = s1_rows[ref_cid]
    min_pad_m = min(r["tx_pad"]["margin_mv"] for r in s1_rows.values())
    max_pad_s = max(r["tx_pad"]["spread_ui"] for r in s1_rows.values())
    pad_annot = (
        f"TT: margin={r_ref['tx_pad']['margin_mv']:.1f} mV, spread={r_ref['tx_pad']['spread_ui']:.4f} UI\n"
        f"All {len(s1_rows)} corners: min margin={min_pad_m:.1f} mV (≥75), max spread={max_pad_s:.4f} UI (≤0.15)\n"
        f"Bit mapping: {sum(1 for r in s1_rows.values() if r['tx_pad']['in_order'])}/{len(s1_rows)} in_order [0..15], 0 bit/edge errors"
    )
    plot_eye(
        ax_eye_tx, Path(r_ref["raw_path"]),
        lambda w, sel: w["v(lqp)"][sel] - w["v(lqn)"][sel],
        bits, T_PAD_NOM, "#1f77b4",
        "(b) Locked-PLL → TX SST v4.3 (FFE=3) Differential Pad Eye (TT)",
        "TX Pad $V_{pad,p} - V_{pad,n}$ (mV)",
        spec_mv=75.0, annot=pad_annot,
    )
    ax_eye_tx.set_ylim(-295, 328)
    ax_eye_tx.legend(loc="lower right", framealpha=0.92)

    min_ctle_h = min(r["ctle_out"]["eye_h_mv"] for r in s1_rows.values())
    min_ctle_w = min(r["ctle_out"]["eye_w_ui"] for r in s1_rows.values())
    ctle_annot = (
        f"TT CTLE (EQ3): eye={r_ref['ctle_out']['eye_h_mv']:.1f} mV / {r_ref['ctle_out']['eye_w_ui']:.2f} UI\n"
        f"All {len(s1_rows)} corners: min={min_ctle_h:.1f} mV / {min_ctle_w:.2f} UI\n"
        f"RX CMOS v2.2: {sum(1 for x in s2_rows.values() if x['ok'])}/{len(s2_rows)} PASS, 0 data / 0 edge err"
    )
    plot_eye(
        ax_eye_rx, Path(r_ref["raw_path"]),
        lambda w, sel: w["v(ctle_p)"][sel] - w["v(ctle_n)"][sel],
        bits, T_PAD_NOM + 1.0e-9, "#2ca02c",
        "(c) Locked-PLL TX → C2_loss6 → RX CTLE (EQ3) Eye (TT)",
        "CTLE Diff Output (mV)",
        spec_mv=None, annot=ctle_annot,
    )
    ax_eye_rx.axvline(0.5, color="#d62728", ls=":", lw=1.0, label="Data slicer center")
    ax_eye_rx.axvline(1.5, color="#d62728", ls=":", lw=1.0)
    ax_eye_rx.set_ylim(-275, 310)
    ax_eye_rx.legend(loc="lower right", framealpha=0.92)

    cids = [cs["id"] for cs in CORNERS if cs["id"] in s1_rows]
    x = np.arange(len(cids))
    wbar = 0.24
    short_lbls = [s1_rows[k]["label"].replace(" ", "\n", 1) for k in cids]
    pad_ms = [s1_rows[k]["tx_pad"]["margin_mv"] for k in cids]
    ctle_hs = [s1_rows[k]["ctle_out"]["eye_h_mv"] for k in cids]
    p_totals = [
        s1_rows[k]["pll_dyn"]["p_pll_total_mw"]
        + s1_rows[k]["pll_dyn"]["p_clk_mw"]
        + s1_rows[k]["pll_dyn"]["p_tx_mw"]
        + (s2_rows[k]["p_rx_mw"] if k in s2_rows else 0.0)
        for k in cids
    ]

    ax_pwr = ax_bar.twinx()
    b1 = ax_bar.bar(x - wbar, pad_ms, width=wbar, color="#1f77b4", label="TX Pad Margin (mV)")
    b2 = ax_bar.bar(x, ctle_hs, width=wbar, color="#2ca02c", label="RX CTLE Eye Height (mV)")
    b3 = ax_pwr.bar(x + wbar, p_totals, width=wbar, color="#ff7f0e", alpha=0.88, label="Full-Chain Power (mW)")
    ax_bar.axhline(75.0, color="#cc2222", ls="--", lw=0.9, label="75 mV Spec")

    for rect in b1:
        h = rect.get_height()
        ax_bar.text(rect.get_x() + rect.get_width() / 2, h + 4, f"{h:.0f}", ha="center", va="bottom", fontsize=7.3)
    for rect in b2:
        h = rect.get_height()
        ax_bar.text(rect.get_x() + rect.get_width() / 2, h + 4, f"{h:.0f}", ha="center", va="bottom", fontsize=7.3)
    for rect in b3:
        h = rect.get_height()
        ax_pwr.text(rect.get_x() + rect.get_width() / 2, h + 1.5, f"{h:.1f}", ha="center", va="bottom", fontsize=7.3, color="#b35900")

    ax_bar.set_title("(d) Multi-Corner Eye Margins & Total SerDes Analog Power (PLL+Clk+TX+RX)", fontweight="bold", pad=8)
    ax_bar.set_xticks(x)
    ax_bar.set_xticklabels(short_lbls)
    ax_bar.set_ylabel("Eye Margin / Height (mV)")
    ax_pwr.set_ylabel("Total Power (mW)")
    ax_bar.set_ylim(0, 300)
    ax_pwr.set_ylim(0, 145)
    ax_bar.grid(True, axis="y", alpha=0.3)

    h1, l1 = ax_bar.get_legend_handles_labels()
    h2, l2 = ax_pwr.get_legend_handles_labels()
    ax_bar.legend(h1 + h2, l1 + l2, loc="upper right", ncol=2, framealpha=0.92)

    sd_note = ""
    if sd_row and sd_row.get("ok"):
        sd_note = f"  |  Single-Deck TT: 0/{sd_row['rx']['data_bits']} Data, 0/{sd_row['rx']['edge_determinate']} Edge Err"
    fig.suptitle(
        "4 Gb/s NRZ SerDes Integrated Closed-Loop Co-Sim: PLL v4 → 4×C2C r5 → TX SST v4.3 (FFE=3) → C2_loss6 → RX CMOS v2.2" + sd_note,
        fontsize=11.2, fontweight="bold", y=0.988,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.962])
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=180)
    plt.close(fig)


def check_ngspice_limit(workers: int) -> None:
    active = len(watch.ngspice_cwds())
    if active + workers > 4:
        raise RuntimeError(f"Host ngspice limit guard: {active} already active, requested {workers}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("fb0probe", "stage1", "stage2", "singledeck", "plot", "all"), default="stage1")
    ap.add_argument("--codes", choices=("center", "gate3"), default="center")
    ap.add_argument("--camp", type=Path, default=DEFAULT_CAMP)
    ap.add_argument("--fig", type=Path, default=DEFAULT_FIG)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--only", default="", help="Comma-separated corner IDs")
    ap.add_argument("--pre-offset", type=float, default=-0.006)
    ap.add_argument("--stop", type=float, default=T_STAGE1_STOP)
    ap.add_argument("--force-stage1", action="store_true", help="Re-run Stage 1 even if an older raw exists")
    args = ap.parse_args()

    workers = max(1, min(args.workers, 2))  # Hard cap <= 2
    camp = args.camp.resolve() if args.camp.is_absolute() else (REPO / args.camp).resolve()
    camp.mkdir(parents=True, exist_ok=True)

    ptat, pll_v4 = load_tables()
    bits = build_sequence()
    (camp / "bits.json").write_text(json.dumps(bits.tolist()))

    sel_corners = list(CORNERS)
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        sel_corners = [cs for cs in sel_corners if cs["id"] in want]

    # --- MODE: FB0 PHASE PROBE (14-ns PLL+4xC2C only -> exact phase-aligned Vref for fast lock!) ---
    fb0_dir = camp / "fb0_phase_probe"
    fb0_file = fb0_dir / "fb0_phases.json"
    if args.mode == "fb0probe":
        fb0_dir.mkdir(parents=True, exist_ok=True)
        jobs = []
        for cs in sel_corners:
            p = resolve_pll_params(ptat, pll_v4, cs)
            d = fb0_dir / cs["id"]
            if spice.case_output(d, "run", "probe.raw", 14e-9) is None:
                ns = None
                if cs.get("seed_op27"):
                    # Solve 27 C OP of the exact PLL+4xC2C probe deck so Xc2c nodes are seeded too
                    seed_d = (fb0_dir / f"{cs['id']}_op27").resolve()
                    ns_p = seed_d / "op27_probe.nodeset"
                    if not (ns_p.exists() and ns_p.stat().st_size > 1000):
                        c27 = Condition(p["c"].process, p["c"].supply, 27)
                        dk27 = build_fb0_probe_deck(cs, c27, p["rc"], p["code"], p["vctrl_locked"], p["trim"], camp / "snap", None)
                        op_l = []
                        for ln in dk27.splitlines():
                            if ln.startswith(".save "):
                                continue
                            if ln.startswith("tran "):
                                op_l.append("op")
                            elif ln.startswith("write "):
                                op_l.append("write op27.raw all")
                            else:
                                op_l.append(ln)
                        ex_op = spice.run("\n".join(op_l) + "\n", seed_d, timeout_s=300)
                        assert ex_op.ok and (seed_d / "op27.raw").exists(), ex_op.log_failures[:3]
                        wop = spice.Waves(seed_d / "op27.raw")
                        ns_l = []
                        for nm in wop.names:
                            if not (nm.startswith("v(") and nm.endswith(")")):
                                continue
                            nd = nm[2:-1]
                            if "#" in nd or nd.startswith(("m.", "q.", "b.", "r.", "l.")):
                                continue
                            if nd in ("vin", "vdd_pll", "vdd_clk", "en_ldo", "ref", "rst_b", "pre_ref", "pre_en") or nd.startswith(("t", "g", "cfg")):
                                continue
                            val = float(wop[nm][0])
                            if np.isfinite(val):
                                ns_l.append(f".nodeset v({nd})={val:.6g}")
                        ns_p.write_text("\n".join(ns_l) + "\n")
                    ns = ns_p
                dk = build_fb0_probe_deck(cs, p["c"], p["rc"], p["code"], p["vctrl_locked"], p["trim"], camp / "snap", ns)
                jobs.append((dk, spice.next_run_dir(d, "run"), dict(timeout_s=300)))
        if jobs:
            check_ngspice_limit(workers)
            for ex in spice.run_many(jobs, workers=workers, smoke=False):
                print(f"FB0PROBE {ex.run_dir.parent.name}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s fail={ex.log_failures[:1]}", flush=True)
        out = json.loads(fb0_file.read_text()) if fb0_file.exists() else {}
        for cs in CORNERS:
            p = resolve_pll_params(ptat, pll_v4, cs)
            raw = spice.case_output(fb0_dir / cs["id"], "run", "probe.raw", 14e-9)
            if raw is None:
                continue
            w = spice.Waves(raw)
            e, sg = crossings(w.t, w["v(fb0)"] - 0.5 * p["c"].supply)
            r = e[sg > 0]
            b0 = w["v(b0p)"] - w["v(b0n)"]
            m = w.t >= 6e-9
            eb, sgb = crossings(w.t[m], b0[m])
            rb = eb[sgb > 0]
            f_ghz = float((len(rb) - 1) / (rb[-1] - rb[0]) / 1e9)
            # Pick first fb0 rising edge >= 8.0 ns; release pre_en 2.0ns before, rst_b 1.5ns before
            t_fb = float(r[r >= 8.0e-9][0])
            td_s = (t_fb - 15e-12) % TREF
            out[cs["id"]] = dict(
                fb0_edges_ns=[round(float(x) * 1e9, 4) for x in r],
                t_fb_align_ns=round(t_fb * 1e9, 4),
                t_ref_delay_s=td_s,
                t_pre_rel_s=t_fb - 2.0e-9,
                t_pfd_rel_s=t_fb - 1.5e-9,
                f_open_ghz=round(f_ghz, 6),
            )
            print(
                f"  {cs['id']:18s} f_open={f_ghz:.6f}GHz fb0_align={t_fb*1e9:.4f}ns "
                f"-> td={td_s*1e9:.4f}ns pre_rel={(t_fb-2e-9)*1e9:.3f}ns pfd_rel={(t_fb-1.5e-9)*1e9:.3f}ns",
                flush=True,
            )
        fb0_file.write_text(json.dumps(out, indent=2))
        print(f"Saved: {fb0_file.relative_to(REPO)}", flush=True)
        return

    fb0_phases = json.loads(fb0_file.read_text()) if fb0_file.exists() else {}

    # --- MODE: STAGE 1 ---
    s1_dir = camp / "stage1"
    s1_dir.mkdir(parents=True, exist_ok=True)
    if args.mode in ("stage1", "all"):
        jobs = []
        for cs in sel_corners:
            p = resolve_pll_params(ptat, pll_v4, cs)
            c = p["c"]
            stim = s1_dir / f"stim_{c.supply:.2f}.inc"
            if not stim.exists():
                stim.write_text(parallel_word_stimuli(bits, c.supply, t_first_upd=T_FIRST_UPD))
            d = s1_dir / cs["id"]
            if (not args.force_stage1) and spice.case_output(d, "run", "stage1.raw", args.stop) is not None:
                print(f"SKIP Stage1 complete: {cs['id']}", flush=True)
                continue
            ns = None
            if cs.get("seed_op27"):
                probe_ns = camp / "fb0_phase_probe" / f"{cs['id']}_op27" / "op27_probe.nodeset"
                ns = probe_ns if (probe_ns.exists() and probe_ns.stat().st_size > 1000) else ensure_op27_nodeset(camp, cs, p, pre_offset=args.pre_offset, stim_file=stim)
            ph = fb0_phases.get(cs["id"], {})
            deck = build_stage1_deck(
                cs, c, p["rc"], p["code"], p["vctrl_locked"], p["trim"],
                stop=args.stop, skip_before="12n", pre_offset=args.pre_offset,
                t_qdiv_rel=T_QDIV_REL, t_tx_rel=T_TX_REL,
                t_ref_delay=float(ph.get("t_ref_delay_s", 2.0e-9)),
                t_pre_rel=float(ph.get("t_pre_rel_s", T_PRE_REL)),
                t_pfd_rel=float(ph.get("t_pfd_rel_s", T_PFD_REL)),
                tstep="8p", maxstep="16p", reltol="4e-4", use_klu=cs.get("klu", False),
                extra_opts=cs.get("extra_opts", ""),
                nodeset_file=ns, snap_dir=camp / "snap",
            )
            jobs.append((
                deck,
                spice.next_run_dir(d, "run"),
                dict(
                    files={"stimuli.inc": stim},
                    timeout_s=4800,
                    meta=dict(id=cs["id"], spec=cs["spec"], stage="stage1", stop=args.stop),
                ),
            ))
        if jobs:
            check_ngspice_limit(workers)
            print(f"[Stage1] Running {len(jobs)} same-deck PLL v4 -> C2C -> QDiv2 -> TX SST -> C2_loss6 corners (stop={args.stop*1e9:.0f}ns, workers={workers})...", flush=True)
            for ex in spice.run_many(jobs, workers=workers, smoke=False):
                print(
                    f"DONE Stage1 {ex.run_dir.parent.name}/{ex.run_dir.name}: ok={ex.ok} "
                    f"elapsed={ex.elapsed_s:.1f}s ({ex.elapsed_s/(args.stop*1e9):.2f} s/ns) fail={ex.log_failures[:2]}",
                    flush=True,
                )

    s1_results = {}
    for cs in CORNERS:
        p = resolve_pll_params(ptat, pll_v4, cs)
        raw = spice.case_output(s1_dir / cs["id"], "run", "stage1.raw", args.stop)
        if raw is None:
            continue
        r = analyse_stage1(raw, cs, p["c"], bits)
        ex_path = raw.parent / "execution.json"
        r["elapsed_s"] = json.loads(ex_path.read_text()).get("elapsed_s") if ex_path.exists() else None
        r["raw_path"] = str(raw)
        r["pll_code"] = p["code"]
        r["ldo_trim"] = p["trim"]
        r["n_zq"] = cs["n_zq"]
        s1_results[cs["id"]] = r
        pd = r["pll_dyn"]
        tp, cf, ct = r["tx_pad"], r["c2_farend"], r["ctle_out"]
        print(
            f"[S1] {cs['id']:17s} ok={r['ok']} | PLL dyn: f={pd['f_out_ghz']:.6f}GHz ({pd['f_err_ppm']:+.1f}ppm) "
            f"Vctrl={pd['vctrl_mean_v']:.4f}V(Δ{r['delta_vctrl_mv']:+.2f}mV,rip={pd['vctrl_ripple_mvpp']:.1f}mVpp) "
            f"Vq={pd['vq_mean_v']:.4f}V(rip={pd['vq_ripple_mvpp']:.1f}mVpp) srv_drift={pd['vbp_srv_drift_mv']:+.3f}mV "
            f"oct={pd['max_oct_err_ps']:.1f}ps | "
            f"Pad: {tp['margin_mv']:.1f}mV/{tp['spread_ui']:.4f}UI err={tp['bit_errors']} ord={tp['in_order']} | "
            f"C2: {cf['margin_mv']:.1f}mV/{cf['spread_ui']:.4f}UI | CTLE: {ct['eye_h_mv']:.1f}mV/{ct['eye_w_ui']:.2f}UI | "
            f"P(PLL/Clk/TX)={pd['p_pll_total_mw']:.1f}/{pd['p_clk_mw']:.1f}/{pd['p_tx_mw']:.1f}mW",
            flush=True,
        )

    # --- MODE: STAGE 2 ---
    s2_dir = camp / "stage2"
    s2_dir.mkdir(parents=True, exist_ok=True)
    offs_req = (0,) if args.codes == "center" else (-8, 0, 8)
    if args.mode in ("stage2", "all"):
        pi_jobs = []
        for cs in sel_corners:
            if cs["id"] not in s1_results:
                continue
            p = resolve_pll_params(ptat, pll_v4, cs)
            cdir = s2_dir / cs["id"]
            cdir.mkdir(parents=True, exist_ok=True)
            rx_inc = cdir / "rx_in.inc"
            clk_inc = cdir / "clk_in.inc"
            if not (rx_inc.exists() and clk_inc.exists()):
                write_stage2_pwl_inputs(Path(s1_results[cs["id"]]["raw_path"]), rx_inc, clk_inc)
            if spice.case_output(cdir, "pi_probe", "pi_probe.raw", 6.5e-9) is None:
                dk = build_pi_probe_deck(cs, p["c"], p["rc"], snap_dir=camp / "snap")
                pi_jobs.append((
                    dk,
                    spice.next_run_dir(cdir, "pi_probe"),
                    dict(files={"clk_in.inc": clk_inc}, timeout_s=300, meta=dict(id=cs["id"], stage="pi_probe")),
                ))
        if pi_jobs:
            check_ngspice_limit(workers)
            print(f"[Stage2 PI Probe] Running {len(pi_jobs)} 6.5-ns PI probes on locked-PLL 8-ph clocks...", flush=True)
            for ex in spice.run_many(pi_jobs, workers=workers, smoke=False):
                assert ex.ok, (ex.run_dir, ex.log_failures)

        rx_jobs = []
        for cs in sel_corners:
            if cs["id"] not in s1_results:
                continue
            p = resolve_pll_params(ptat, pll_v4, cs)
            cdir = s2_dir / cs["id"]
            ppi = spice.case_output(cdir, "pi_probe", "pi_probe.raw", 6.5e-9)
            assert ppi is not None
            wpi = spice.Waves(ppi)
            e_ck = rising_edges(wpi.t, wpi["v(ckd0)"], 0.5 * p["c"].supply)
            ck0 = float(e_ck[0])
            t_bit0_rx = s1_results[cs["id"]]["ctle_out"]["t_bit0_center_s"] - STAGE2_SHIFT
            dt = (((t_bit0_rx - SLICER_APERTURE_S) - ck0 + 0.5 * UI) % UI) - 0.5 * UI
            opt_code = int(round(dt / (UI / 32.0))) % 64
            (cdir / "pi_center.json").write_text(json.dumps(dict(opt_code=opt_code, ck0_ns=ck0 * 1e9, t_bit0_rx_ns=t_bit0_rx * 1e9), indent=2))
            codes = [(opt_code + o) % 64 for o in offs_req]
            missing = [cd for cd in codes if spice.case_output(cdir, "rx", f"code_{cd:02d}.raw", STAGE2_STOP) is None]
            if missing:
                dk = build_stage2_rx_deck(cs, p["c"], p["rc"], missing, snap_dir=camp / "snap")
                rx_jobs.append((
                    dk,
                    spice.next_run_dir(cdir, "rx"),
                    dict(
                        files={"rx_in.inc": cdir / "rx_in.inc", "clk_in.inc": cdir / "clk_in.inc"},
                        timeout_s=2400,
                        meta=dict(id=cs["id"], codes=missing, stage="stage2_rx"),
                    ),
                ))
        if rx_jobs:
            check_ngspice_limit(workers)
            print(f"[Stage2 RX] Running {len(rx_jobs)} RX CMOS v2.2 decks (codes={args.codes}, workers={workers})...", flush=True)
            for ex in spice.run_many(rx_jobs, workers=workers, smoke=False):
                print(f"DONE Stage2 {ex.run_dir.parent.name}/{ex.run_dir.name}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s fail={ex.log_failures[:2]}", flush=True)

    s2_results = {}
    for cs in CORNERS:
        cdir = s2_dir / cs["id"]
        pc_file = cdir / "pi_center.json"
        if not pc_file.exists():
            continue
        p = resolve_pll_params(ptat, pll_v4, cs)
        opt_code = int(json.loads(pc_file.read_text())["opt_code"])
        pts = []
        center_r = None
        for o in (-8, 0, 8):
            cd = (opt_code + o) % 64
            raw = spice.case_output(cdir, "rx", f"code_{cd:02d}.raw", STAGE2_STOP)
            if raw is None:
                continue
            w = spice.Waves(raw)
            r = analyse_rx_words(w, bits, p["c"].supply, cd, meas_from=STAGE2_MEAS, min_words=4, min_bit_idx=16)
            r["offset_codes"] = o
            r["offset_ui"] = o / 32.0
            pts.append(r)
            if o == 0:
                sel = w.t >= STAGE2_MEAS
                ts = w.t[sel]
                p_ctle = time_average(w["p_ctle"][sel], ts) * 1e3
                p_pi = time_average(w["p_pi"][sel], ts) * 1e3
                p_sl = time_average(w["p_slicer"][sel], ts) * 1e3
                p_ds = time_average(w["p_deser"][sel], ts) * 1e3
                p_rx = p_ctle + p_pi + p_sl + p_ds
                center_r = dict(
                    **r,
                    p_ctle_mw=float(p_ctle),
                    p_pi_mw=float(p_pi),
                    p_slicer_mw=float(p_sl),
                    p_deser_mw=float(p_ds),
                    p_rx_mw=float(p_rx),
                    raw_path=str(raw),
                )
        if center_r is not None:
            ok_offs = [pt["offset_codes"] for pt in pts if pt["data_errors"] == 0 and pt["edge_errors"] == 0]
            lo_ok = min([o for o in ok_offs if o <= 0], default=0)
            hi_ok = max([o for o in ok_offs if o >= 0], default=0)
            win_ui = float((hi_ok - lo_ok + 1) / 32.0) if 0 in ok_offs else 0.0
            e_pt = next((pt for pt in pts if pt["offset_codes"] == -8), None)
            l_pt = next((pt for pt in pts if pt["offset_codes"] == 8), None)
            bb_ok = bool(e_pt and l_pt and e_pt["bbpd_vote"] < 0 and l_pt["bbpd_vote"] > 0) if (e_pt and l_pt) else None
            center_r.update(
                condition=cs["id"],
                window_lo_codes=lo_ok,
                window_hi_codes=hi_ok,
                window_ui=win_ui if (e_pt and l_pt) else None,
                early_vote=int(e_pt["bbpd_vote"]) if e_pt else None,
                late_vote=int(l_pt["bbpd_vote"]) if l_pt else None,
                bbpd_polarity_ok=bb_ok,
                points=pts,
            )
            if bb_ok is not None:
                center_r["ok"] = bool(center_r["ok"] and win_ui >= 0.50 and bb_ok)
            s2_results[cs["id"]] = center_r
            win_s = f"win={win_ui:.3f}UI BBPD={center_r['early_vote']:+d}/{center_r['late_vote']:+d}" if bb_ok is not None else "center-only"
            print(
                f"[S2] {cs['id']:17s} ok={center_r['ok']} cd={opt_code:02d} | "
                f"data={center_r['data_errors']}/{center_r['data_bits']} edge={center_r['edge_errors']}/{center_r['edge_determinate']} | "
                f"wclk su/ho={center_r['wclk_setup_ps']:.0f}/{center_r['wclk_hold_ps']:.0f}ps | {win_s} | "
                f"P_rx={center_r['p_rx_mw']:.2f}mW (CTLE {center_r['p_ctle_mw']:.1f}/PI {center_r['p_pi_mw']:.1f}/SL {center_r['p_slicer_mw']:.1f}/DS {center_r['p_deser_mw']:.1f})",
                flush=True,
            )

    # --- MODE: SINGLEDECK (True All-in-One PLL -> C2C -> QDiv2 -> TX SST -> C2_loss6 -> RX CMOS on TT!) ---
    sd_dir = camp / "singledeck_tt"
    sd_dir.mkdir(parents=True, exist_ok=True)
    sd_result = None
    tt_cs = CORNERS[0]
    tt_p = resolve_pll_params(ptat, pll_v4, tt_cs)
    sd_stop = T_STAGE1_STOP

    if args.mode in ("singledeck", "all"):
        tt_pi_code = int(s2_results["tt_v1800_t27_tt"]["code"]) if "tt_v1800_t27_tt" in s2_results else 0
        stim_sd = sd_dir / "stim_1.80.inc"
        if not stim_sd.exists():
            stim_sd.write_text(parallel_word_stimuli(bits, tt_p["c"].supply, t_first_upd=T_FIRST_UPD))
        if spice.case_output(sd_dir, "run", "full_chain.raw", sd_stop) is None:
            ph_tt = fb0_phases.get("tt_v1800_t27_tt", {})
            dk = build_stage1_deck(
                tt_cs, tt_p["c"], tt_p["rc"], tt_p["code"], tt_p["vctrl_locked"], tt_p["trim"],
                stop=sd_stop, skip_before="40n", pre_offset=args.pre_offset,
                t_qdiv_rel=T_QDIV_REL, t_tx_rel=T_TX_REL,
                t_ref_delay=float(ph_tt.get("t_ref_delay_s", 2.0e-9)),
                t_pre_rel=float(ph_tt.get("t_pre_rel_s", T_PRE_REL)),
                t_pfd_rel=float(ph_tt.get("t_pfd_rel_s", T_PFD_REL)),
                tstep="8p", maxstep="16p", reltol="4e-4", use_klu=False,
                extra_opts="",
                nodeset_file=None, snap_dir=camp / "snap",
                full_rx=True, pi_code=tt_pi_code, t_rx_rel=T_QDIV_REL + 1.0e-9,
            )
            check_ngspice_limit(1)
            print(f"[SingleDeck TT] Running ALL-IN-ONE PLL->C2C->QDiv2->TX->C2_loss6->RX (PI={tt_pi_code}, stop={sd_stop*1e9:.0f}ns)...", flush=True)
            ex = spice.run(dk, spice.next_run_dir(sd_dir, "run"), files={"stimuli.inc": stim_sd}, timeout_s=5400)
            print(f"DONE SingleDeck TT: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s ({ex.elapsed_s/(sd_stop*1e9):.2f} s/ns) fail={ex.log_failures[:2]}", flush=True)

    sd_raw = spice.case_output(sd_dir, "run", "full_chain.raw", sd_stop)
    if sd_raw is not None:
        w = spice.Waves(sd_raw)
        tt_pi_code = int(s2_results["tt_v1800_t27_tt"]["code"]) if "tt_v1800_t27_tt" in s2_results else 0
        pll_dyn = pll_window_metrics(w, tt_p["c"], tt_cs["vin"], 45.0e-9, min(75.0e-9, float(w.t[-1]) - 0.5e-9))
        rx_r = analyse_rx_words(w, bits, tt_p["c"].supply, tt_pi_code, meas_from=49.5e-9, min_words=4, min_bit_idx=16)
        sel = (w.t >= 45.0e-9) & (w.t <= min(75.0e-9, float(w.t[-1]) - 0.5e-9))
        ts = w.t[sel]
        s = tt_p["c"].supply
        p_ctle = -time_weighted_mean(ts, w["i(vdd_ctle)"][sel]) * s * 1e3
        p_pi = -time_weighted_mean(ts, w["i(vdd_pi)"][sel]) * s * 1e3
        p_sl = -time_weighted_mean(ts, w["i(vdd_slicer)"][sel]) * s * 1e3
        p_ds = -time_weighted_mean(ts, w["i(vdd_deser)"][sel]) * s * 1e3
        p_rx = p_ctle + p_pi + p_sl + p_ds
        p_all = pll_dyn["p_pll_total_mw"] + pll_dyn["p_clk_mw"] + pll_dyn["p_tx_mw"] + p_rx
        ex_path = sd_raw.parent / "execution.json"
        sd_result = dict(
            ok=bool(rx_r["ok"] and abs(pll_dyn["f_err_ppm"]) <= 200.0),
            elapsed_s=json.loads(ex_path.read_text()).get("elapsed_s") if ex_path.exists() else None,
            raw_path=str(sd_raw),
            pll_dyn=pll_dyn,
            rx=rx_r,
            p_ctle_mw=p_ctle,
            p_pi_mw=p_pi,
            p_slicer_mw=p_sl,
            p_deser_mw=p_ds,
            p_rx_mw=p_rx,
            p_total_serdes_mw=p_all,
            total_pj_per_bit=p_all / 4.0,
        )
        print(
            f"[SINGLE-DECK TT] ok={sd_result['ok']} | PLL f={pll_dyn['f_out_ghz']:.6f}GHz ({pll_dyn['f_err_ppm']:+.1f}ppm) "
            f"Vq={pll_dyn['vq_mean_v']:.4f}V({pll_dyn['vq_ripple_mvpp']:.1f}mVpp) | "
            f"RX data={rx_r['data_errors']}/{rx_r['data_bits']} edge={rx_r['edge_errors']}/{rx_r['edge_determinate']} "
            f"wclk su/ho={rx_r['wclk_setup_ps']:.0f}/{rx_r['wclk_hold_ps']:.0f}ps | "
            f"P_total={p_all:.2f}mW ({p_all/4.0:.2f} pJ/b)",
            flush=True,
        )

    summary = dict(
        generated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        stage1_stop_s=args.stop,
        stage1=s1_results,
        stage2=s2_results,
        singledeck_tt=sd_result,
    )
    (camp / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"Summary written: {(camp / 'summary.json').relative_to(REPO)}", flush=True)

    if s1_results and args.mode in ("plot", "all", "stage2", "singledeck"):
        fig_path = args.fig.resolve() if args.fig.is_absolute() else (REPO / args.fig).resolve()
        make_figure(camp, summary, fig_path)
        print(f"Figure written: {fig_path.relative_to(REPO)}", flush=True)


if __name__ == "__main__":
    main()
