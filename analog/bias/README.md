# Bandgap & Global Bias (`analog/bias/`)

SKY130A 1.8 V bandgap reference, folded-cascode OTA, true-CMOS reference buffer (`ref_pbuf`), and distributed current-mirror bias network (`BIAS v2`) serving the PLL, TX, and RX subsystems.

## 1. Active 4 Gb/s Mainline (`BIAS v2`)

- **Top-Level Netlist**: [`spice/bias_v2.spice`](spice/bias_v2.spice) (single-stage FC-OTA bandgap + true-CMOS `ref_pbuf` + `ref_vbuf` + integrated `bias_top_v2` + local mirrors `bias_cml`, `bias_cp`, `bias_ctle` + PTAT tap for VCO r6).
- **Signed-Off PDK Layout**: [`layout/variants/v2_pdk/`](layout/variants/v2_pdk/README.md) (`serdes_bias_top_v2_pdk` + local distribution cells, Magic full-rule `DRC = 0`, Netgen `LVS = MATCH`, CPEX + RCX verified).
- **Design Report**: [docs/design/bias_v2.md](../../docs/design/bias_v2.md)
- **Testbenches**: [`tb/v2/`](tb/v2/) (`run_pvt_ac.py`, `run_mc.py`, `run_startup.py`, `run_postlayout.py`).

## 2. Historical v1 Reference & Cap-Sizing Studies

Original v1 bandgap/distribution netlists (`spice/bandgap.spice`, `spice/bias_dist.spice`) and characterization testbenches (`tb/bandgap_*`, `tb/dist_*`, `tb/cap_sizing/`, `tb/physical_reference_card/`) are retained for regression traceability (`tests/test_bias_cap_sizing.py`, `tests/test_physical_reference_card.py`):

- [docs/design/bias.md](../../docs/design/bias.md) · [docs/design/bias_cap_review.md](../../docs/design/bias_cap_review.md) · [docs/design/physical_reference_card.md](../../docs/design/physical_reference_card.md)
- Working revision metadata: [`config/bias_working_revision.toml`](../../config/bias_working_revision.toml)
- Retired v1 layout variant (`pdk/`) and loose legacy `.mag`/`.tcl` drafts are archived with SHA-256 receipts in [`results/catalog/retired_pre_release_20261123.json`](../../results/catalog/retired_pre_release_20261123.json).
