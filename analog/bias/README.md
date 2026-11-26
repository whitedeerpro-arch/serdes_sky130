# Bandgap & Global Bias (`analog/bias/`)

SKY130A 1.8 V bandgap reference, folded-cascode OTA, true-CMOS reference buffer (`ref_pbuf`), and distributed current-mirror bias network (`BIAS v2`) serving both the 4 Gb/s `v1.0` mainline and 5 Gb/s Plan-C subsystems.

## 1. Active Mainline (`BIAS v2`)

- **Top-Level Netlist**: [`spice/bias_v2.spice`](spice/bias_v2.spice) (single-stage FC-OTA bandgap + true-CMOS `ref_pbuf` + `ref_vbuf` + integrated `bias_top_v2` + local mirrors `bias_cml`, `bias_cp`, `bias_ctle` + PTAT tap for VCO r6).
- **Signed-Off PDK Layout**:
  - [`layout/variants/v2_pdk/`](layout/variants/v2_pdk/README.md) (`serdes_bias_top_v2_pdk` + 6 local cells, Magic full-rule `DRC = 0`, Netgen `LVS = MATCH`, CPEX + RCX verified);
  - [`layout/variants/v2_ptat_pdk/`](layout/variants/v2_ptat_pdk/) (PTAT-enabled bias top variant for VCO `r6` `28/66` temperature compensation);
  - Generators & layout notes: [`layout/README.md`](layout/README.md), [`layout/build_bias_v2_pdk.py`](layout/build_bias_v2_pdk.py), [`layout/build_bias_top_v2.py`](layout/build_bias_top_v2.py).
- **Design Report & Mainline Identity**: [docs/design/bias_v2.md](../../docs/design/bias_v2.md) · [`config/mainline_working_revision.toml`](../../config/mainline_working_revision.toml)
- **Testbenches**: [`tb/v2/`](tb/v2/) (`run_pvt_ac.py`, `run_mc.py`, `run_startup.py`, `run_postlayout.py`).

## 2. Historical v1 Reference

Original v1 bandgap and distribution netlists ([`spice/bandgap.spice`](spice/bandgap.spice), [`spice/bias_dist.spice`](spice/bias_dist.spice)) remain in `spice/` for monitor/legacy compatibility. Retired v1 layout drafts and duplicate reference copies are archived with SHA-256 receipts in [`results/catalog/retired_pre_release_20261123.json`](../../results/catalog/retired_pre_release_20261123.json) and [`results/catalog/retired_gemini_duplicate_references_20261124.json`](../../results/catalog/retired_gemini_duplicate_references_20261124.json).
