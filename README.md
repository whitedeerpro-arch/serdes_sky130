# Simple SerDes — SKY130A 1.8 V 4 Gb/s Zero-CML NRZ SerDes

An open-source, transistor-level and layout-signed-off **4 Gb/s NRZ SerDes transceiver** designed in the **SkyWater SKY130A (130 nm CMOS, 1.8 V)** PDK using 100% open-source EDA flows (`ngspice 47`, `Magic`, `Netgen`, `OpenROAD` / `OpenRCX` / `OpenSTA`, `Yosys`, `Verilator` / `Icarus Verilog`) plus post-layout SDF gate-level signoff.

> **Architecture Highlight (4 Gb/s Zero-CML Mainline)**:
> - **Clocking (PLL v4)**: 250 MHz reference → 2 GHz 4-stage symmetric-load ring VCO (`r6` + PTAT `28/66` tail bias, `sym9_clean` CPEX 8-phase quadrature error `≤ 0.76 ps`) → active-servo wide-swing steering CP (`v4` / `v4.1`) → fused MIM1+MIM2 loop filter → SAFF-TSPC ÷8 prescaler + `r5` CML→CMOS receiver, powered by an isolated HV18 native-NMOS LDO (`v2_cur`) and folded-cascode bandgap/bias (`BIAS v2`).
> - **TX (`tx_sst` v4.3)**: Zero-CML 16:4 static CMOS serializer + 4-phase N-over-N **Source-Series-Terminated (SST)** line driver (`0.44 V` sub-regulator, 28 slices = 23 Main + 5 Post-1 FFE) driving `100 Ω` differential PCB channels (`C0–C5`).
> - **RX (`cmos_rx` v2.2)**: `100 Ω` on-die termination + 4-level tunable CTLE → 2 GHz 64-code pure-CMOS Phase Interpolator + 8-phase 1 GHz quadrature ÷2 → quarter-rate double-tail dynamic CMOS slicers (4 Data + 4 Edge) → 8→32 static CMOS deserializer.
> - **Digital (`serdes_digital_top_v3` v3.1)**: Unified multi-rate `sky130_fd_sc_hd` macro (`250 MHz` TX/RX/Host, `125 MHz` 2nd-order BBPD CDR, `62.5 MHz` 5-bit PLL coarse/startup controller), `103,932 µm²`, `4,932` std cells, 3-corner OpenRCX STA MET + 4-mode SDF GLS (`122,608/122,608` SVA PASS, `0` sync violations).
> - **Chip Floorplan**: **`845.4 × 601.4 µm = 0.5084 mm²`** core (`21` signed-off functional macros + `12` damped PDN decap banks, `957.9 pF` total on-chip capacitance, `0.0 µm²` overlap).

![Chip-Level Signed-Off Floorplan](docs/figures/system/serdes_chip_floorplan_20261123.png)

## 4 Gb/s First-Draft Signoff Summary

Project-wide authoritative status and exact verification boundaries are maintained in [docs/status/current.md](docs/status/current.md).

| Subsystem | Signed-Off Revision | Physical Area (`µm²`) | DRC / LVS | Electrical / Post-Layout Verification | Design Doc |
|---|---|---:|---|---|---|
| **PLL v4** (VCO r6 PTAT + CP v4 + LF fused + PFD + SAFF-TSPC ÷8 + `r5` rx) | `pll_top_r6_v4_upgrade` | `32,684` (all PLL macros) | **0 / MATCH** | **7/7 PVT** closed-loop lock (`−4.75..+2.25 ppm`, `TT 1.91 ps` / worst `2.29 ps` RMS jitter, `35.8 mW` TT); `sym9_clean` CPEX 8-ph err `≤ 0.76 ps` | [pll_vco_r6_perf.md](docs/design/pll_vco_r6_perf.md), [pll_cp_v4.md](docs/design/pll_cp_v4.md), [pll_tspc_reclock_divider.md](docs/design/pll_tspc_reclock_divider.md) |
| **LDO** (HV18 Native-NMOS Quiet Supply) | `ldo_hv18_v2_cur` (`v2_cur_pdk`) | `27,826` (+ `2,033` bias LPF) | **0 / MATCH** | Full PVT DC/AC/RCX verified (`v2_cur` + bleed trim `PM 58.3°` at light load, `quiet 1.781–1.797 V`) | [ldo_v2.md](docs/design/ldo_v2.md) |
| **BIAS** (Bandgap + Distribution + Buffers) | `bias_v2` (`v2_pdk`) | `28,274` (top + local copies) | **0 / MATCH** | 135-corner PVT + 200-sample MC + RCX verified (`Vbg`, `Vcm`, `Ibias`, PTAT) | [bias_v2.md](docs/design/bias_v2.md) |
| **TX** (Zero-CML 16:1 SST + 2-tap FFE) | `tx_sst_v4` (`v4_pdk`, v4.3) | `34,026` (`231.5 × 147.0 µm`) | **0 / MATCH** | **22/22 RCX** post-layout corners PASS across `C2_loss6`; `pad_p/n = 46.5/42.9 fF` | [tx_sst_v4.md](docs/design/tx_sst_v4.md) |
| **RX** (Zero-CML CTLE + CMOS PI + 4×Q-rate DT Slicers + Deser16) | `rx_cmos_v2.2` (`v2_pdk`) | `47,932` (`245.3 × 195.4 µm`) | **0 / MATCH** | **45/45** schematic link + **3/3 CPEX** post-layout PASS (`0/64` data, `0/27..30` edge, `TT 36.1 mW`); PI 64-code TT CPEX `\|INL\| = 0.0177 UI` | [rx_cmos_v2.md](docs/design/rx_cmos_v2.md) |
| **Digital Top** (PLL Ctrl + TX Ingress + RX Align/FIFO + BBPD CDR) | `serdes_digital_top_v3` (v3.1) | `103,932` (`338.1 × 307.4 µm`) | **0 / MATCH** | **3-corner OpenRCX STA** (6 clocks MET, `TNS = 0`); **4/4 VCS SDF GLS** PASS (`122,608` SVA, `0` sync violations, `±300 ppm` CDR) | [digital_top_v3.md](docs/design/digital_top_v3.md) |
| **System Floorplan & Damped PDN** | `chip_floorplan_20261123` | `508,424` (`0.5084 mm²`) | 0 overlap | 21 functional macros (`59.5%`) + 12 damped MIM1+MIM2 decap banks (`761 pF`, `R_eq = 1.51 Ω`, `957.9 pF` grand total) | [chip_floorplan_20261123.md](docs/layout/chip_floorplan_20261123.md) |

## Repository Layout

```text
simple_serdes_fork1/
├── analog/
│   ├── pll/            # 2 GHz PLL v4 (vco/, cp/, loop_filter/, pfd/, divider/, coarse/, top/)
│   ├── tx/             # TX mainline: sst/ (4 Gb/s Zero-CML SST); legacy CML in serializer/, output_driver/, ...
│   ├── rx/             # RX mainline: cmos_rx/ (4 Gb/s Zero-CML RX); legacy CML in ctle/, pi/, sampler/, ...
│   ├── ldo/            # HV18 native-NMOS quiet LDO (v2_cur mainline + historical r4/smallcap studies)
│   ├── bias/           # Bandgap reference & current distribution (BIAS v2 mainline + v1 reference)
│   ├── common/         # Shared analog primitives (cml_to_cmos/, devices/, monitor/, pads/, CML cells)
│   └── layout/         # Shared SKY130A Magic/PDK layout engine & preview utilities
├── digital/
│   ├── pnr/            # Unified digital top RTL (rtl_v3/), OpenROAD P&R & VCS SDF GLS runners, signoff netlist
│   ├── pll/ tx/ rx/    # Subsystem behavioral RTL, testbenches & unit verification
├── src/serdes_flow/    # Python simulation, PVT/MC, eye/jitter analysis, SKY130 gm/Id & Pareto optimizer (gmid/opt)
├── verification/       # Channel S4P models (C0–C5), layout review/floorplan scripts, PDN stability, plotting
├── docs/               # Specifications, current status, module design docs, layout reports, figures
├── config/             # PDK/tool configs, working revisions, boundary conditions, design catalog
├── tests/              # Pytest regression suite (netlist, layout checks, optimization toolkit, doc/catalog integrity)
└── web/design/         # Interactive browser-based design workbench
```

> **Lightweight Pure-Source Git Policy**: Heavy binary/generated physical outputs (`*.gds`, `*.def`, `*_pg.v`, `*.mag`, `*.spef`, `*.sdf`, `*.fsdb`, vector `*.svg`, raw `results/**` waveforms) are `.gitignore`d to keep git clones fast and clean. Every `.mag` and `.gds` deliverable is **100% reproducible** from the tracked Python/OpenROAD generators in `analog/**/layout/` and `digital/pnr/`, and pre-built layout/GDSII archives are distributed via GitHub Releases.

## Quick Start

```bash
# 1. Install Python environment (Python 3.12 + numpy/scipy/matplotlib/pytest)
uv sync

# 2. Run the full repository verification & doc-integrity test suite
uv run pytest -q

# 3. Verify repository hygiene (zero stray extraction/waveform artifacts)
uv run python verification/maintenance/repository_hygiene.py audit

# 4. Launch the interactive design workbench
uv run python -m serdes_flow.design_viewer --open
```

Simulator & PDK paths are configured in [config/pdk.toml](config/pdk.toml) and [config/tools.toml](config/tools.toml) (`ngspice 47` at `/opt/ngspice47/bin/ngspice`). Contributor and handoff conventions are documented in [AGENTS.md](AGENTS.md) and [docs/README.md](docs/README.md).

## Documentation Map

| Topic | Entry Point |
|---|---|
| Authoritative Status & Verification Boundaries | [docs/status/current.md](docs/status/current.md) |
| Complete Module Design Index (4G Mainline vs Legacy CML) | [docs/design/README.md](docs/design/README.md) |
| Physical Layout & Chip Floorplan Signoff | [docs/layout/README.md](docs/layout/README.md), [chip_floorplan_20261123.md](docs/layout/chip_floorplan_20261123.md) |
| Architecture, Specs & Module Map | [docs/overview/architecture.md](docs/overview/architecture.md), [docs/overview/spec.md](docs/overview/spec.md), [docs/overview/development_map.md](docs/overview/development_map.md) |
| Verification Methods, Jitter/Stats & $g_m/I_D$ Optimizer | [docs/verification/methods.md](docs/verification/methods.md), [docs/verification/optimization_toolkit.md](docs/verification/optimization_toolkit.md) |
| Interactive Design Workbench | [web/design/index.html](web/design/index.html) ([guide](web/design/README.md)) |
| Historical Logs & Retired Artifacts | [docs/history/index.md](docs/history/index.md), [results/catalog/README.md](results/catalog/README.md) |
