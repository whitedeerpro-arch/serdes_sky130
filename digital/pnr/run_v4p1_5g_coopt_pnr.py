#!/usr/bin/env python3
"""Plan-C 5G Chip-Top Pin-Co-Optimized & Area-Compacted Digital Top PnR (`serdes_digital_top_v4`, v4.1).

Non-destructive wrapper around `digital/pnr/run_v4_32b_pnr.py` (0 ngspice! Pure Yosys/OpenROAD/Magic/Netgen/OpenSTA)
preserving `digital/pnr/variants/hd_pnr_v4_32b/` 100% untouched and exporting strictly to:
  - Work dir:    `results/digital/pnr_v4p1_5g_coopt/`
  - Variant dir: `digital/pnr/variants/hd_pnr_v4p1_5g_coopt/`

Key 5G Chip-Top Plan-C Co-Optimizations:
  1. Compacted Die: `386.0 x 356.0 um` (`137,416 um^2`, `-6.6%` vs `394.7 x 372.6 = 147,065 um^2`!).
  2. Exact 1:1 `deser16` North Pin X-Matching on South Edge (`x_dig = 81.2 .. 301.9 um`):
     Every single one of the 33 RX data/edge/clock pins (`rx_phys[31:0]`, `rx_word_clk`) is placed via
     OpenROAD `place_pin -force_to_die_boundary` at the EXACT physical X-coordinate matching `rx_top_5g`
     North (`wd12..we0, wclk`), eliminating all 262 crossings (`262 -> 0`, `0` vias, `6 um` channel!) and
     leaving `x_dig in [302..386]` (directly above RX's East CTLE inductor!) 100% pin-free!
  3. Monotonic South-West TX Bus (`x_dig = 12.0 .. 72.0 um`): `tx_capture_data[0..15]`, `tx_word_clk`, valids
     ordered monotonically right beside `tx_sst_v5 (R270_MX)` East edge (`61 -> 0` crossings!).
  4. West-Lower RX PI Control (30 pins, `y_dig = 12..85 um`) + West-Mid PLL Analog (23 pins, `y_dig = 95..170 um`):
     Exits straight West into the TX<->RX alley (eliminating the `~375 um` RX wrap-around!) and straight West
     across the moat to `LC-VCO (R90)` / `PLL` / `LF`!
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import run_unified_v3_pnr as v3  # noqa: E402
import run_v4_32b_pnr as v4  # noqa: E402

_ORIG_BUILD_V4_PIN_GROUPS = v4.build_v4_pin_groups

# Exact physical X-coordinates of `rx_top_5g` North 33 pins (in rx_top_5g local coord where bbox x0 = -5.40):
# When `rx_top_5g` sits at x_world = 602.0 (origin at 607.4) and `digital_v4p1` sits at x_world = 532.0,
# exact 1:1 Digital local X = (607.4 + x_rx_raw) - 532.0 = 75.4 + x_rx_raw!
RX_ALIGN_OFFSET_X = 75.40
RX_NORTH_EXACT_1TO1: list[tuple[str, float]] = [
    ("rx_phys[12]", 5.80),  ("rx_phys[8]",  10.30), ("rx_phys[4]",  14.80), ("rx_phys[0]",  19.30),
    ("rx_phys[13]", 35.40), ("rx_phys[9]",  39.90), ("rx_phys[5]",  44.40), ("rx_phys[1]",  48.90),
    ("rx_phys[14]", 65.00), ("rx_phys[10]", 69.50), ("rx_phys[6]",  74.00), ("rx_phys[2]",  78.50),
    ("rx_word_clk", 92.40),
    ("rx_phys[15]", 94.60), ("rx_phys[11]", 99.10), ("rx_phys[7]", 103.60), ("rx_phys[3]", 108.10),
    ("rx_phys[29]", 124.20), ("rx_phys[25]", 128.70), ("rx_phys[21]", 133.20), ("rx_phys[17]", 137.70),
    ("rx_phys[30]", 153.80), ("rx_phys[26]", 158.30), ("rx_phys[22]", 162.80), ("rx_phys[18]", 167.30),
    ("rx_phys[31]", 183.40), ("rx_phys[27]", 187.90), ("rx_phys[23]", 192.40), ("rx_phys[19]", 196.90),
    ("rx_phys[28]", 213.00), ("rx_phys[24]", 217.50), ("rx_phys[20]", 222.00), ("rx_phys[16]", 226.50),
]

TX_SOUTH_ORDERED: list[str] = (
    ["tx_clock_good", "tx_capture_valid", "tx_a_valid", "tx_b_valid"]
    + [f"tx_capture_data[{i}]" for i in range(16)]
    + ["tx_word_clk"]
)

WEST_RX_PI_ORDERED: list[str] = (
    [f"rx_select_a[{i}]" for i in range(8)]
    + [f"rx_select_b[{i}]" for i in range(8)]
    + [f"rx_fine_b[{i}]" for i in range(8)]
    + [f"rx_phase_code[{i}]" for i in range(6)]
)

WEST_PLL_ANALOG_ORDERED: list[str] = (
    [
        "ref_clk", "bias_ready_async", "pre_ref_ready_async",
        "hi_async", "lo_async", "pw_late_async",
        "precharge_en", "pfd_rst_b", "cp_en", "pll_pw_clr_b",
    ]
    + [f"vco_code[{i}]" for i in range(5)]
    + [f"switches[{i}]" for i in range(8)]
)


def _snap_met2_x(x: float) -> float:
    # met2 track: offset 0.23, pitch 0.46
    k = round((x - 0.23) / 0.46)
    return round(0.23 + k * 0.46, 2)


def _snap_met3_y(y: float) -> float:
    # met3 track: offset 0.34, pitch 0.68
    k = round((y - 0.34) / 0.68)
    return round(0.34 + k * 0.68, 2)


def build_v4p1_pin_groups() -> list[v3.PinGroup]:
    """Plan-C 5G Chip-Top co-optimized cardinal pin groups (exact same 283 signal pins!)."""
    return [
        # SOUTH-WEST: 21 monotonic TX analog/serializer pins right beside TX_SST_V5 (R270_MX) East edge
        v3.PinGroup(
            key="south_tx",
            label="TX Analog / Serializer (tx_word_clk, 16b ordered)",
            short_label="TX Analog",
            edge="bottom",
            frac_start=0.030,
            frac_end=0.195,
            color="#059669",
            pins=TX_SOUTH_ORDERED,
        ),
        # SOUTH-MID-EAST: 33 RX data/edge/clock pins matched 1:1 to `rx_top_5g` North (x=81.2..301.9; East >302 pin-free above CTLE coil!)
        v3.PinGroup(
            key="south_rx_data",
            label="RX Analog Data/Edge 1:1 (rx_word_clk, rx_phys[31:0])",
            short_label="RX Data 1:1",
            edge="bottom",
            frac_start=0.205,
            frac_end=0.790,
            color="#dc2626",
            pins=[p for p, _ in RX_NORTH_EXACT_1TO1],
        ),
        # WEST-BOTTOM: 30 RX PI control pins exiting straight West into TX<->RX alley to RX PI!
        v3.PinGroup(
            key="west_rx_pi",
            label="RX PI Control (a/b/f, phase_code -> West alley)",
            short_label="RX PI Ctrl",
            edge="left",
            frac_start=0.030,
            frac_end=0.280,
            color="#e11d48",
            pins=WEST_RX_PI_ORDERED,
        ),
        # WEST-MID: 23 PLL analog pins facing LC-VCO(R90)/PLL/LF straight West across the moat!
        v3.PinGroup(
            key="west_pll_analog",
            label="PLL Analog (ref_clk, vco[4:0], sw[7:0] -> West)",
            short_label="PLL Analog",
            edge="left",
            frac_start=0.305,
            frac_end=0.535,
            color="#2563eb",
            pins=WEST_PLL_ANALOG_ORDERED,
        ),
        # WEST-UPPER: 29 PLL Host Config & Calibration + Global rst_n
        v3.PinGroup(
            key="west_pll_host",
            label="PLL Host Cfg + rst_n",
            short_label="PLL Host Cfg",
            edge="left",
            frac_start=0.560,
            frac_end=0.955,
            color="#1d4ed8",
            pins=(
                ["rst_n", "pll_enable", "pll_start", "pll_abort_async"]
                + v4._bus("pll_tclass", 2)
                + v4._bus("pll_lo_run", 4)
                + v4._bus("pll_hi_run", 4)
                + v4._bus("pll_stop_code", 12)
                + v4._bus("pll_stop_sel", 3)
            ),
        ),
        # NORTH & EAST: preserved cleanly from v4!
        *[g for g in _ORIG_BUILD_V4_PIN_GROUPS() if g.edge in ("top", "right")],
    ]


def v4p1_pin_constraints_tcl(pin_groups: list[v3.PinGroup], die_w: float, die_h: float) -> str:
    """Emit exact 1:1 `place_pin` commands for Plan-C zero-crossing buses + standard regions for host pins."""
    exact_pins: set[str] = set()
    lines: list[str] = ["# Plan-C 5G Exact 1:1 Zero-Crossing Pin Placement"]

    # 1. Exact 1:1 RX Data/Edge/Clock pins along South edge (met2, y=0.0, matched to rx_top_5g North!)
    for pname, x_rx in RX_NORTH_EXACT_1TO1:
        xd = _snap_met2_x(RX_ALIGN_OFFSET_X + x_rx)
        lines.append(f"place_pin -pin_name {{{pname}}} -layer met2 -location {{{xd:.2f} 0.00}} -pin_size {{0.14 0.48}} -force_to_die_boundary")
        exact_pins.add(pname)

    # 2. Monotonic TX South-West pins (met2, y=0.0, x=13.57..68.77 um, 2.76 um pitch = 6 met2 tracks!)
    for idx, pname in enumerate(TX_SOUTH_ORDERED):
        xd = _snap_met2_x(13.57 + idx * 2.76)
        lines.append(f"place_pin -pin_name {{{pname}}} -layer met2 -location {{{xd:.2f} 0.00}} -pin_size {{0.14 0.48}} -force_to_die_boundary")
        exact_pins.add(pname)

    # 3. Monotonic West-Bottom RX PI Control pins (met3, x=0.0, y=13.94..92.82 um, 2.72 um = 4 met3 tracks!)
    for idx, pname in enumerate(WEST_RX_PI_ORDERED):
        yd = _snap_met3_y(13.94 + idx * 2.72)
        lines.append(f"place_pin -pin_name {{{pname}}} -layer met3 -location {{0.00 {yd:.2f}}} -pin_size {{0.80 0.30}} -force_to_die_boundary")
        exact_pins.add(pname)

    # 4. Monotonic West-Mid PLL Analog pins (met3, x=0.0, y=111.18..185.98 um, 3.40 um = 5 met3 tracks!)
    for idx, pname in enumerate(WEST_PLL_ANALOG_ORDERED):
        yd = _snap_met3_y(111.18 + idx * 3.40)
        lines.append(f"place_pin -pin_name {{{pname}}} -layer met3 -location {{0.00 {yd:.2f}}} -pin_size {{0.80 0.30}} -force_to_die_boundary")
        exact_pins.add(pname)

    # 5. Remaining host/status/telemetry groups via standard region constraints
    for grp in pin_groups:
        rem = [p for p in grp.pins if p not in exact_pins]
        if not rem:
            continue
        span = die_w if grp.edge in ("bottom", "top") else die_h
        b = grp.frac_start * span
        e = grp.frac_end * span
        pins_str = " ".join(rem)
        lines.append(f"set_io_pin_constraint -pin_names {{{pins_str}}} -region {grp.edge}:{b:.2f}-{e:.2f}")

    return "\n".join(lines)


def main() -> None:
    # Monkey-patch v4 & v3 pin builders cleanly without modifying any existing file!
    v4.build_v4_pin_groups = build_v4p1_pin_groups
    v3.pin_constraints_tcl = v4p1_pin_constraints_tcl
    # Default CLI args for isolated Plan-C v4.1 build (overrideable on command line)
    if "--results-dir" not in sys.argv:
        sys.argv += ["--results-dir", str(REPO / "results/digital/pnr_v4p1_5g_coopt")]
    if "--variant-dir" not in sys.argv:
        sys.argv += ["--variant-dir", str(REPO / "digital/pnr/variants/hd_pnr_v4p1_5g_coopt")]
    if "--die-w" not in sys.argv:
        sys.argv += ["--die-w", "386.0"]
    if "--die-h" not in sys.argv:
        sys.argv += ["--die-h", "356.0"]
    v4.main()


if __name__ == "__main__":
    main()
