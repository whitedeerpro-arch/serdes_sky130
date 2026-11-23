# LDO Physical Layout (`analog/ldo/layout/`)

Programmatic SKY130A PDK Magic layout generators and signed-off deliverables for the HV18 quiet-supply LDO subsystem.

## Active Signed-Off Variants

| Variant | Generator | Deliverables | Status |
|---|---|---|---|
| [`variants/v2_cur_pdk/`](variants/v2_cur_pdk/README.md) | [`build_ldo_v2_cur_pdk.py`](build_ldo_v2_cur_pdk.py) | `serdes_pll_supply_hv18_v2_cur_pdk` & probe twin (`27,826 µm²`) | **Active 4 Gb/s Mainline** (DRC=0, LVS=MATCH, CPEX/RCX verified) |
| [`variants/bias_filter_r4_pdk/`](variants/bias_filter_r4_pdk/README.md) | [`build_ldo_pdk.py`](build_ldo_pdk.py) | `serdes_pll_bias_lowpass_slow_r4_pdk` (`33.58 × 60.53 µm`, 1 MΩ/16 pF) | **Active 4 Gb/s Mainline** (VCO tail-bias slow LPF, DRC=0, LVS=MATCH) |

> Superseded layout variants (`mim_pdk`, `r4_pdk`, `smallcap_pdk`, `v2_pdk`) and loose legacy Gemini `.mag`/`.tcl` drafts have been archived off-repo with SHA-256 verification ([retired_pre_release_20261123.json](../../../results/catalog/retired_pre_release_20261123.json)).
> Heavy `.mag` binaries are `.gitignore`d and distributed via GitHub Releases or regenerated locally via the tracked Python scripts.
