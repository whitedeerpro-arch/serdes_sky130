# Phase-Locked Loop (`analog/pll/`)

SKY130A 250 MHz → **2 GHz 8-phase PLL v4** subsystem providing quadrature/octature clocks for both the 4 Gb/s Zero-CML TX (`sst`) and RX (`cmos_rx`).

## Active 4 Gb/s Mainline (`pll_top_r6_v4_upgrade`)

- **Integrated Top**: [`top/spice/pll_top_r6_v4_upgrade.spice`](top/spice/pll_top_r6_v4_upgrade.spice) — closed-loop lock verified across **7/7 PVT corners** via [`top/tb/lock_v4/verify_pll_v4_closed_loop.py`](top/tb/lock_v4/verify_pll_v4_closed_loop.py) (`−4.75..+2.25 ppm`, `TT 35.8 mW`, RMS jitter `1.91 ps` TT / `2.29 ps` worst, `FoM_jitter = −222.1..−224.4 dB`).
- **Design Reports**: [pll_vco_r6_perf.md](../../docs/design/pll_vco_r6_perf.md), [pll_vco_r6_ptat.md](../../docs/design/pll_vco_r6_ptat.md), [pll_cp_v4.md](../../docs/design/pll_cp_v4.md), [pll_tspc_reclock_divider.md](../../docs/design/pll_tspc_reclock_divider.md), [pll_loop.md](../../docs/design/pll_loop.md).

## Submodules

| Submodule | Active Mainline Implementation | Signed-Off PDK Layout | Notes |
|---|---|---|---|
| [`vco/`](vco/) | 4-stage `r6` 5-bit ring VCO + BIAS v2 PTAT tail bias (`28/66`) | `layout/variants/sym9_clean/`, `ptat_bias_pdk/` | `sym9_clean` CPEX 8-phase err `≤ 0.76 ps` (5/5 corners); 45/45 single-code across `−40..85 °C` |
| [`cp/`](cp/) | 200 µA steering CP with 1/4-replica active servo (`v4` / `v4.1`) | `layout/variants/v4_pdk/` | Wide `Vctrl` compliance; v4.1 cuts `Vctrl` glitch `2.2–3.5×` (`−60 dBc` ref spur) |
| [`loop_filter/`](loop_filter/) | Passive 2nd-order RC (`Rz = 4.13 kΩ`, `Ci = 18 pF`, `Cp`) + precharge | `layout/variants/fused_pdk/` | 6-site stacked MIM1+MIM2 (`6,382 µm²`, DRC=0/LVS=MATCH) |
| [`pfd/`](pfd/) | Standard-cell PFD (`pll_pfd_sc_dly`) + phase-window lock detector | `layout/variants/pdk/` | Zero dead-zone; 200-sample cold MC 0 stall |
| [`divider/`](divider/README.md) | Equalized Nikolic SAFF-TSPC reclocked ÷8 (`tspc_reclock_prescaler8_2g`) | `layout/variants/saff_reclock_2g_pdk/` | `1,705 µm²` CMOS ÷8 (legacy CML `r3` retained in `review_clean/`) |
| [`coarse/`](coarse/) | 5-bit coarse-band handoff & window benches | Digital FSM in `digital/pnr/rtl_v3/` | — |
| [`top/`](top/) | Closed-loop PLL v4 & legacy r5/r6 verification testbenches | Chip floorplan integration | `tb/lock_v4/` (mainline) + `tb/native_r6/`, `tb/frontend_r6/` |
