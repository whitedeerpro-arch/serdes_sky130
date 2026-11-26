# HV18 Quiet-Supply LDO (`analog/ldo/`)

SKY130A native-NMOS LDO providing the PLL's 1.8 V quiet rail from the HV18 input supplied at 3.0–3.6 V.

## 1. Active 4 Gb/s Mainline (`v2_cur`)

- **Top-Level Netlist**: [`spice/pll_supply_hv18_v2_cur.spice`](spice/pll_supply_hv18_v2_cur.spice) (`ldo_hv18_core_v2.spice` + `ldo_v2_passives.spice`)
- **Signed-Off PDK Layout**:
  - [`layout/variants/v2_cur_pdk/`](layout/variants/v2_cur_pdk/README.md) contains the current-input production and probe macros.
  - [`layout/variants/bias_filter_r4_pdk/`](layout/variants/bias_filter_r4_pdk/README.md) contains the slow tail-bias filter for the VCO.
- **Design Report**: [docs/design/ldo_v2.md](../../docs/design/ldo_v2.md)
- **Bench**: The precharged PLL bench uses the current-input supply macro. [PLL v4 bench](../pll/top/tb/lock_v4/verify_pll_v4_closed_loop.py)

## 2. Historical LDO Studies & Cap-Sizing Iterations

Earlier `r4`, `smallcap` (`70 pF`), and stacked-MIM studies remain in `spice/` and `tb/` for regression traceability (`tests/test_ldo_cap_sizing.py`):

- The voltage-input v2 replay uses `verify_rcx.py --rcx <archived-probe.spice>`. The retirement receipt locates the original `serdes_pll_supply_hv18_v2_probe_pdk_rcx.spice`. [RCX replay](tb/v2/verify_rcx.py) · [Retirement receipt](../../results/catalog/retired_pre_release_20261123.json)

- [docs/design/ldo_r4.md](../../docs/design/ldo_r4.md) · [docs/design/ldo_smallcap.md](../../docs/design/ldo_smallcap.md) · [docs/design/ldo_cap_area.md](../../docs/design/ldo_cap_area.md) · [docs/design/ldo.md](../../docs/design/ldo.md)
- Working revision metadata: [`config/ldo_working_revision.toml`](../../config/ldo_working_revision.toml)
- Retired legacy layout variants (`mim_pdk`, `r4_pdk`, `smallcap_pdk`, `v2_pdk`, and loose Nov-13 `.mag`/`.tcl`) are archived with SHA-256 receipts in [`results/catalog/retired_pre_release_20261123.json`](../../results/catalog/retired_pre_release_20261123.json).
