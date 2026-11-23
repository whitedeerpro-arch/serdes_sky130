# HV18 Quiet-Supply LDO (`analog/ldo/`)

SKY130A 1.8 V → Quiet-Rail Native-NMOS LDO subsystem powering the 2 GHz PLL VCO and low-noise clock front-end.

## 1. Active 4 Gb/s Mainline (`v2_cur`)

- **Top-Level Netlist**: [`spice/pll_supply_hv18_v2_cur.spice`](spice/pll_supply_hv18_v2_cur.spice) (`ldo_hv18_core_v2.spice` + `ldo_v2_passives.spice`)
- **Signed-Off PDK Layout**:
  - [`layout/variants/v2_cur_pdk/`](layout/variants/v2_cur_pdk/README.md) — `serdes_pll_supply_hv18_v2_cur_pdk` (`27,826 µm²`, Magic full-rule DRC=0, Netgen LVS=MATCH, CPEX + RCX verified)
  - [`layout/variants/bias_filter_r4_pdk/`](layout/variants/bias_filter_r4_pdk/README.md) — `serdes_pll_bias_lowpass_slow_r4_pdk` (`33.58 × 60.53 = 2,033 µm²`, 1 MΩ / 16 pF slow tail-bias LPF retained for VCO tail-bias isolation)
- **Design Report**: [docs/design/ldo_v2.md](../../docs/design/ldo_v2.md)
- **Testbenches**: [`tb/v2/`](tb/v2/) (`run_v2.py`, `verify_rcx.py`)

## 2. Historical LDO Studies & Cap-Sizing Iterations

Earlier `r4`, `smallcap` (`70 pF`), and stacked-MIM studies remain in `spice/` and `tb/` for regression traceability (`tests/test_ldo_cap_sizing.py`):

- [docs/design/ldo_r4.md](../../docs/design/ldo_r4.md) · [docs/design/ldo_smallcap.md](../../docs/design/ldo_smallcap.md) · [docs/design/ldo_cap_area.md](../../docs/design/ldo_cap_area.md) · [docs/design/ldo.md](../../docs/design/ldo.md)
- Working revision metadata: [`config/ldo_working_revision.toml`](../../config/ldo_working_revision.toml)
- Retired legacy layout variants (`mim_pdk`, `r4_pdk`, `smallcap_pdk`, `v2_pdk`, and loose Nov-13 `.mag`/`.tcl`) are archived with SHA-256 receipts in [`results/catalog/retired_pre_release_20261123.json`](../../results/catalog/retired_pre_release_20261123.json).
