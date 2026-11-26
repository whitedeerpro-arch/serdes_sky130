# Phase-Locked Loop (`analog/pll/`)

SKY130A 250 MHz → **2.0 GHz 8-phase Ring-VCO PLL v4** (4 Gb/s `v1.0` mainline) and **5.0 Gb/s Dual-Rate (4/5 Gb/s) Octagonal LC-VCO + A/B Divider** (Plan-C, 2026-11-26), sharing the Type-II `PFD sc_dly + CP v4 + fused LF k4` loop core.

- **Status & Signoff Catalogs**: [docs/status/current.md](../../docs/status/current.md) · [v1_0_subsystem_evidence.json](../../results/catalog/v1_0_subsystem_evidence.json) · [serdes_5g_signoff_20261126.json](../../results/catalog/serdes_5g_signoff_20261126.json)
- **Design Reports**: [pll_loop.md](../../docs/design/pll_loop.md) · [pll_vco_r6_ptat.md](../../docs/design/pll_vco_r6_ptat.md) · [pll_vco_r6_perf.md](../../docs/design/pll_vco_r6_perf.md) · [pll_cp_v4.md](../../docs/design/pll_cp_v4.md) · [pll_tspc_reclock_divider.md](../../docs/design/pll_tspc_reclock_divider.md) · [pll_feedback_data_dividers.md](../../docs/design/pll_feedback_data_dividers.md)
- **4G Closed-Loop Baseline**: [`top/spice/pll_top_r6_v4_upgrade.spice`](top/spice/pll_top_r6_v4_upgrade.spice) · [`top/tb/lock_v4/verify_pll_v4_closed_loop.py`](top/tb/lock_v4/verify_pll_v4_closed_loop.py)

## Submodules

| Submodule | Active Implementation | Signed-Off PDK Layout | Notes |
|---|---|---|---|
| [`vco_5g/`](vco_5g/README.md) | **5G** Octagonal LC-VCO + sync `÷2` I/Q (`lc_5g_div2_oct_pdk.spice`) | `layout/variants/lc_vco_5g_oct_pdk/` | 6/6 + 125 °C frozen-code PASS (`4.469–5.350 GHz` intersection), 24/24 SS85 MC (`I/Q σ=0.65 ps`) |
| [`vco/`](vco/README.md) | **4G** 4-stage `r6` 5-bit ring VCO + BIAS v2 PTAT tail bias (`28/66`) | `layout/variants/sym9_clean/`, `ptat_bias_pdk/` | `sym9_clean` CPEX 8-phase err `≤ 0.76 ps` (5/5 corners); 45/45 single-code across `−40..85 °C` |
| [`divider/`](divider/README.md) | **5G** Dual-rate A/B `÷8/÷10` (`pll_div_ab_5g_v2.spice`) & **4G** SAFF-TSPC `÷8` (`tspc_reclock_prescaler8_2g.spice`) | `div_ab_5g_v2_pdk/` · `saff_reclock_2g_pdk/` | `div_ab_5g_v2_pdk` 12/12 + 50/50 SS-40 MC PASS (`M5=0%`); `saff_reclock_2g_pdk` `1,705 µm²` |
| [`cp/`](cp/README.md) | Shared 200 µA steering CP with 1/4-replica active servo (`v4` / `v4.1`) | `layout/variants/v4_pdk/` | 135-corner UP/DN mismatch `0.193%`, 1.65 V compliance up to `1.49 V` |
| [`loop_filter/`](loop_filter/README.md) | Shared passive 2nd-order RC (`Rz = 4.13 kΩ`, `Ci = 18.38 pF`, 12/6 split) + precharge | `layout/variants/fused_pdk/` | 6-site stacked MIM1+MIM2 (`6,382 µm²`, `DRC=0/LVS=MATCH`) |
| [`pfd/`](pfd/README.md) | Shared standard-cell PFD (`pll_pfd_sc_dly`) + phase-window lock detector | `layout/variants/pdk/` | Zero dead-zone; 200-sample cold MC 0 stall |
| [`coarse/`](coarse/README.md) | `Vctrl` window comparator (`vctrl_window_cmos.spice`) & handoff benches | Digital FSM in `digital/pnr/rtl_v3/` & `rtl_v4_32b/` | — |
| [`top/`](top/README.md) | Closed-loop PLL v4 / v4.2 testbenches & analytical loop/noise theory scripts | Chip integration in `verification/layout/` | `tb/lock_v4/`, `tb/verify_pll_v4p2_saff.py`, `theory/` |
