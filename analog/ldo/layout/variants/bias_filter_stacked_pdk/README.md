# Stacked MIM1+MIM2 PLL Tail-Bias Slow Low-Pass Filter (`serdes_pll_bias_lowpass_stacked_pdk`)

1 MΩ (`32 × res_high_po`) / 16 pF (`8 × cap_mim_m3_1` + `8 × cap_mim_m3_2` 2×4 stacked MIM1+MIM2) VCO tail-bias low-pass filter, built by [`build_stacked_mim.py`](../../build_stacked_mim.py) and [`build_stacked_filter.py`](../../build_stacked_filter.py).

- **Physical signoff**: `58.85 × 105.805 µm = 6,226.62 µm²` (**−39.8%** vs single-layer `bias_filter_r4_pdk` `10,339.6 µm²`, saving `4,113 µm²`), `Magic DRC = 0`, `Netgen LVS = MATCH`, `PROP_ERR = False`.
- **Passive PEX evidence**: `docs/design/ldo_cap_area.md` (cutoff shift `0.068%–0.102%` across `TT/FS/SS`, self thermal noise `15.23 → 15.24 µVrms`).
- **Build receipt**: `results/layout/ldo_bias_filter_stacked_20261123/filter/summary.json`.
