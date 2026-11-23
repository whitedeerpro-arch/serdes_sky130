# Analog Subsystems (`analog/`)

SKY130A 1.8 V 4 Gb/s Zero-CML SerDes analog circuits, testbenches, and programmatic PDK layout generators.

## Top-Level Structure

| Directory | Role | Active 4 Gb/s Mainline |
|---|---|---|
| [`pll/`](pll/README.md) | 250 MHz → 2 GHz 8-phase clock generation | `top/spice/pll_top_r6_v4_upgrade.spice` (`vco` r6 + PTAT, `cp` v4/v4.1, `loop_filter` fused, `pfd`, `divider` SAFF-TSPC ÷8) |
| [`tx/`](tx/README.md) | 16:1 4 Gb/s transmitter | **`tx/sst/`** (Zero-CML 16:4 CMOS serializer + 4-phase N-over-N SST driver + 2-tap FFE, `v4_pdk`) |
| [`rx/`](rx/README.md) | 4 Gb/s receiver & 1:16 deserializer | **`rx/cmos_rx/`** (100 Ω term + CTLE + 2 GHz CMOS PI + 4× quarter-rate DT slicers + 8→32 deser, `v2_pdk`) |
| [`ldo/`](ldo/README.md) | HV18 native-NMOS isolated quiet-rail LDO | `spice/pll_supply_hv18_v2_cur.spice` (`layout/variants/v2_cur_pdk/`) + slow bias LPF (`bias_filter_r4_pdk/`) |
| [`bias/`](bias/README.md) | Bandgap reference, FC-OTA, `ref_pbuf` & current distribution | `spice/bias_v2.spice` (`layout/variants/v2_pdk/`) |
| [`common/`](common/README.md) | Shared analog primitives & receivers | `cml_to_cmos/` (`r5_pdk`), `devices/`, `monitor/`, `pads/`, CML primitives |
| [`layout/`](layout/README.md) | Shared SKY130A Magic PDK drawing engine | `scripts/layout_core.py` & layout review utilities |

> Each module keeps **DUT netlists in `spice/`**, **testbenches in `tb/<case>/`**, and **PDK layout generators + signoff summaries in `layout/`**. Simulation outputs write append-only to `results/analog/<module>/<case>/<run_id>/`.
