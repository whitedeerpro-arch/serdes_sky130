# LDO Physical Layout (`analog/ldo/layout/`)

Programmatic SKY130A PDK Magic layout generators and signed-off deliverables for the HV18 quiet-supply LDO and slow tail-bias filter subsystem.

## Active Signed-Off Variants

| Variant | Generator | Deliverables | Status |
|---|---|---|---|
| [`variants/v2_cur_kelvin_pdk/`](variants/v2_cur_kelvin_pdk/README.md) | [`build_ldo_v2_cur_pdk.py`](build_ldo_v2_cur_pdk.py) (`--kelvin-opt`) | Coaxial-shielded Kelvin return & shortened FB production + probe macros (`312.52 × 121.42 µm`, `R_eff −92.9%`) | **Active 5 Gb/s Plan-C** (DRC=0, LVS=MATCH, 100 mΩ RCX + 100× MC) |
| [`variants/v2_cur_pdk/`](variants/v2_cur_pdk/README.md) | [`build_ldo_v2_cur_pdk.py`](build_ldo_v2_cur_pdk.py) | Current-reference production macro and probe twin ([summary.json](variants/v2_cur_pdk/summary.json)) | **Active 4 Gb/s `v1.0` Mainline** (DRC=0, LVS=MATCH, CPEX/RCX) |
| [`variants/bias_filter_stacked_pdk/`](variants/bias_filter_stacked_pdk/README.md) | [`build_stacked_filter.py`](build_stacked_filter.py) | Stacked-MIM slow tail-bias LPF (compact footprint) | **Active 4G `full_v3+` / 5G Plan-C** (DRC=0, LVS=MATCH) |
| [`variants/bias_filter_r4_pdk/`](variants/bias_filter_r4_pdk/README.md) | [`build_ldo_pdk.py`](build_ldo_pdk.py) | `serdes_pll_bias_lowpass_slow_r4_pdk` (`33.58 × 60.53 µm`, 1 MΩ/16 pF) | **Active 4 Gb/s `v1.0` Baseline** (DRC=0, LVS=MATCH) |

> Superseded layout variants (`mim_pdk`, `r4_pdk`, `smallcap_pdk`, `v2_pdk`) and loose legacy drafts are archived off-repo with SHA-256 verification ([retired_pre_release_20261123.json](../../../results/catalog/retired_pre_release_20261123.json)).
> Five historical reference copies are archived with their canonical SPICE paths ([retired_gemini_duplicate_references_20261124.json](../../../results/catalog/retired_gemini_duplicate_references_20261124.json)).
> Heavy `.mag` binaries are regenerated locally via the tracked Python scripts.
