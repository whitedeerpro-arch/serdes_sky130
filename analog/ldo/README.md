# HV18 Quiet-Supply LDO (`analog/ldo/`)

SKY130A native-NMOS LDO providing the PLL's 1.8 V quiet rail from the 3.0–3.6 V HV18 input, plus the slow tail-bias low-pass filter (`1 MΩ / 16 pF`) protecting the VCO bias line.

## 1. Active Mainline & 5G Kelvin-Hardened Variants

- **Top-Level Netlists**:
  - [`spice/pll_supply_hv18_v2_cur.spice`](spice/pll_supply_hv18_v2_cur.spice) (`ldo_hv18_core_v2.spice` + `ldo_v2_passives.spice`) — current-reference HV18 LDO fed from `BIAS v2` `i_ldo0`.
  - [`spice/pll_bias_filter_r4.spice`](spice/pll_bias_filter_r4.spice) — slow tail-bias RC filter (`1 MΩ / 16 pF`).
- **Signed-Off PDK Layouts** ([`layout/README.md`](layout/README.md)):
  - **4 Gb/s `v1.0` Mainline**: [`layout/variants/v2_cur_pdk/`](layout/variants/v2_cur_pdk/README.md) (`37,958.68 µm²`, `DRC=0 / LVS=MATCH`, CPEX + RCX) + [`layout/variants/bias_filter_r4_pdk/`](layout/variants/bias_filter_r4_pdk/README.md).
  - **5 Gb/s Plan-C Kelvin-Hardened**: [`layout/variants/v2_cur_kelvin_pdk/`](layout/variants/v2_cur_kelvin_pdk/README.md) (`R_eff −92.9%`, `PSRR ≥ 28.7 dB`, 100× RCX MC `3σ ≤ 10.8 mV`, `DRC=0 / LVS=MATCH`) + [`layout/variants/bias_filter_stacked_pdk/`](layout/variants/bias_filter_stacked_pdk/README.md).
- **Testbenches & Verification**:
  - Kelvin A/B RCX verification: [`tb/v2/verify_kelvin_ab.py`](tb/v2/verify_kelvin_ab.py)
  - Standalone `v2_cur` PVT check: [`verification/unit_checks/verify_ldo_v2_cur_pvt.py`](../../verification/unit_checks/verify_ldo_v2_cur_pvt.py)
  - Closed-loop PLL v4 bench (using `v2_cur`): [`analog/pll/top/tb/lock_v4/verify_pll_v4_closed_loop.py`](../pll/top/tb/lock_v4/verify_pll_v4_closed_loop.py)
- **Design Report & Evidence**: [docs/design/ldo_v2.md](../../docs/design/ldo_v2.md) · [`config/mainline_working_revision.toml`](../../config/mainline_working_revision.toml) · [5G Signoff Catalog](../../results/catalog/serdes_5g_signoff_20261126.json)

## 2. Historical & Archive Receipts

Superseded layout variants (`mim_pdk`, `r4_pdk`, `smallcap_pdk`, voltage-input `v2_pdk`, and early drafts) are archived off-repo with SHA-256 receipts in [`results/catalog/retired_pre_release_20261123.json`](../../results/catalog/retired_pre_release_20261123.json). Note SKY130A 5 V MOS mismatch and `high_po`/`xhigh_po` thermal-noise pitfalls documented in [docs/verification/statistics.md](../../docs/verification/statistics.md#sky130a-失配与高阻多晶硅热噪声边界pdk-实测核对).
