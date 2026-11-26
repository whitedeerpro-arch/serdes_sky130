# Bias Physical Layout (`analog/bias/layout/`)

Programmatic SKY130A PDK Magic layout generators and signed-off deliverables for the **BIAS v2** reference and distribution subsystem.

## Active Signed-Off Variant

| Variant | Generators | Deliverables | Status |
|---|---|---|---|
| [`variants/v2_pdk/`](variants/v2_pdk/README.md) | [`build_bias_v2_pdk.py`](build_bias_v2_pdk.py), [`build_bias_top_v2.py`](build_bias_top_v2.py) | `serdes_bias_top_v2_pdk`, `serdes_bandgap_v2_pdk`, `serdes_ref_pbuf_v2_pdk`, `serdes_ref_vbuf_v2_pdk`, `serdes_bias_{cml,cp,ctle}_v2_pdk` | **Active 4 Gb/s Mainline** (DRC=0, LVS=MATCH, CPEX/RCX verified) |

> Superseded v1 layout variant (`variants/pdk/`), early floorplan drafts (`plan/`), and loose Nov-13 Gemini `.mag`/`.tcl` files have been archived off-repo with SHA-256 verification ([retired_pre_release_20261123.json](../../../results/catalog/retired_pre_release_20261123.json)).
> Two historical reference copies are archived with their canonical SPICE paths. [Reference receipt](../../../results/catalog/retired_gemini_duplicate_references_20261124.json)
> Heavy `.mag` binaries are `.gitignore`d and distributed via GitHub Releases or regenerated locally via the tracked Python scripts.
