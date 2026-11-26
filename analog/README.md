# Analog Subsystems (`analog/`)

SKY130A 1.8 V 4.0 Gb/s (`v1.0` mainline) & 5.0 Gb/s Dual-Rate Plan-C NRZ SerDes analog circuits, testbenches, and programmatic PDK layout generators. Project-wide status lives in [docs/status/current.md](../docs/status/current.md), with fixed signoff receipts in [v1_0_subsystem_evidence.json](../results/catalog/v1_0_subsystem_evidence.json) and [serdes_5g_signoff_20261126.json](../results/catalog/serdes_5g_signoff_20261126.json).

## Top-Level Structure

| Directory | Role | 4 Gb/s `v1.0` Mainline | 5 Gb/s Plan-C Dual-Rate (2026-11-26) |
|---|---|---|---|
| [`pll/`](pll/README.md) | 250 MHz → 2.0 / 2.5 GHz clock generation | `pll_top_r6_v4_upgrade` (`vco` r6 + PTAT, `cp` v4, `loop_filter` fused, `pfd` `sc_dly`, `divider` SAFF-TSPC ÷8) | [`vco_5g/`](pll/vco_5g/README.md) (`lc_vco_5g_oct_pdk`), `divider/div_ab_5g_v2_pdk` (`÷8/÷10`), shared `cp v4` / `lf_k4_fused` / `pfd` |
| [`tx/`](tx/README.md) | 16:1 NRZ transmitter | `tx/sst/` (`v4_pdk`, CMOS 16:4 + 4-phase N-over-N 28-slice SST + 2-tap FFE) | `tx/sst/layout/variants/v5_pdk/` + `v4p5_pdk` VDRV LDO (CPEX 16/16 5G+4G PASS) |
| [`rx/`](rx/README.md) | NRZ receiver & 1:16 deserializer | `rx/cmos_rx/` (`v2_pdk`, 100 Ω term + CTLE + 2 GHz CMOS PI + DT slicers + 8→32 deser) | `rx/cmos_rx/layout/variants/rx_top_5g_pdk/` (`W3 CTLE` + `slicer_5g_pdk` + `v5g_4ph_v3_pdk`) |
| [`ldo/`](ldo/README.md) | HV18 native-NMOS quiet-rail LDO | `pll_supply_hv18_v2_cur.spice` (`v2_cur_pdk`) + `bias_filter_r4_pdk` | `v2_cur_kelvin_pdk` (Kelvin `R_eff -92.9%`) + `bias_filter_stacked_pdk` |
| [`bias/`](bias/README.md) | Bandgap reference, FC-OTA, `ref_pbuf` & current distribution | `bias_v2.spice` (`v2_pdk`) + PTAT tap (`v2_ptat_pdk`) | Shared `BIAS v2` macro |
| [`common/`](common/README.md) | Shared analog primitives & clock receivers | `cml_to_cmos/` (`r5_pdk` v6), `devices/`, `monitor/`, `cml_buffer/` | Shared `r5_pdk` v6 & device wrappers |
| [`layout/`](layout/README.md) | Shared SKY130A Magic PDK drawing engine | `scripts/layout_core.py` & layout review utilities | Shared PDK drawing core |

> Each module keeps **DUT netlists in `spice/`**, **testbenches in `tb/<case>/`**, and **PDK layout generators + signoff summaries in `layout/`**. Simulation outputs write append-only to `results/analog/<module>/<case>/<run_id>/`.
