# Simple SerDes — SKY130A 1.8 V Dual-Rate 4/5 Gb/s NRZ SerDes

An open-source **Dual-Rate 4/5 Gb/s NRZ SerDes** design in **SkyWater SKY130A (130 nm CMOS, 1.8 V)**, implemented with ngspice 47, Magic, Netgen, KLayout, OpenROAD, OpenRCX, OpenSTA, and Yosys (with VCS SDF GLS used on the 4G digital signoff baseline).

As of **2026-11-26**, the repository converges on two verified physical design tracks:
- **Primary Design — 5.0 Gb/s Dual-Rate (4/5 Gb/s) LC-PLL SerDes (`serdes_5g_top_pdk`, Plan-C)**: `936 × 650 µm = 0.6084 mm²`, 13 signed-off SKY130A PDK macros (`70.3%` macro density), 131 compacted Direct/Damped/HV33 decap tiles (`147.03 pF` top-level), Magic full `DRC = 0`, `55.43 MB` merged GDSII, and hierarchical `ext2spice lvs` connectivity/isolation signoff (`28/28` connect, `41/41` isolate).
- **4.0 Gb/s Inductorless Ring-VCO Reference Baseline (`v1.0` / `full_v8`)**: `845.4 × 601.4 µm = 0.5084 mm²` core (`full_v8` Magic `DRC = 0`), retained cleanly as an inductorless 4G reference.

![5G SerDes Plan-C full-chip silicon layout (Magic DRC = 0)](docs/figures/layout/serdes_5g_top_pdk_20261126.png)

## Architecture

- **5G Dual-Rate Clocking & Supply**: 250 MHz reference → 5.0 GHz octagonal LC-VCO + quadrature ÷2 (`lc_vco_5g_oct_pdk`), dual-rate A/B divider ÷8/÷10 (`div_ab_5g_v2_pdk`), CP v4 + fused LF + PFD `sc_dly`, and 5G I/Q CML→CMOS clock host, powered by HV18 Kelvin LDO (`v2_cur_kelvin_pdk`) and BIAS v2. *(4G reference uses 2 GHz 4-stage ring VCO `r6` + PTAT `28/66`, SAFF-TSPC ÷8, and 4× `r5` receivers.)*
- **TX**: Static CMOS 16:4 serializer + four-phase N-over-N 28-slice SST line driver with 2-tap FFE (`analog/tx/sst/`, 5G `v5_pdk` & 4G `v4_pdk`).
- **RX**: On-die 100 Ω termination + W3 shunt-peaked CTLE + 2.5 GHz `4→8` I/Q CMOS phase interpolator v3 + 5G quarter-rate Double-Tail samplers (`analog/rx/cmos_rx/`, `rx_top_5g_pdk`; 4G `v2_pdk`).
- **Digital**: Pin-co-optimized 32-bit dual-rate top `serdes_digital_top_v4` (`v4p1`, `160 MHz × 32-bit` host, zero-crossing 33-bit RX bus alignment, multi-rate BBPD CDR, and async FIFO; 4G reference `serdes_digital_top_v3`).

Authoritative verification metrics, stimulus/load boundaries, and open tapeout-closure items live in **[docs/status/current.md](docs/status/current.md)**. Machine-readable signoff ledgers are indexed in [serdes_5g_signoff_20261126.json](results/catalog/serdes_5g_signoff_20261126.json), [chip_physical_audit_20261126.json](results/catalog/chip_physical_audit_20261126.json), [mainline_working_revision.toml](config/mainline_working_revision.toml), and [v1_0_subsystem_evidence.json](results/catalog/v1_0_subsystem_evidence.json).

## Repository Layout

```text
simple_serdes_fork1/
├── analog/
│   ├── pll/            # 5G LC-VCO (vco_5g/), 4G Ring-VCO (vco/), dual-rate & SAFF dividers (divider/), cp/, loop_filter/, pfd/, coarse/, top/
│   ├── tx/             # TX CMOS/SST mainline: sst/ (5G v5_pdk + 4G v4_pdk)
│   ├── rx/             # RX CMOS mainline: cmos_rx/ (5G rx_top_5g_pdk + 4G v2_pdk)
│   ├── ldo/            # HV18 native-NMOS quiet LDO (v2_cur_kelvin_pdk & v2_cur_pdk + bias_filter_r4)
│   ├── bias/           # Bandgap reference & current distribution (BIAS v2)
│   ├── common/         # Shared analog primitives (cml_to_cmos/ r5, devices/, monitor/)
│   └── layout/         # Shared SKY130A Magic/PDK layout engine & preview utilities
├── digital/
│   ├── pnr/            # 5G 32-bit dual-rate RTL (rtl_v4_32b/) & 4G RTL (rtl_v3/), OpenROAD P&R runners, signed-off variants
│   ├── pll/ tx/ rx/    # Subsystem behavioral RTL & unit testbenches
├── src/serdes_flow/    # Python simulation, PVT/MC, eye/jitter analysis, SKY130 gm/Id & Pareto optimizer (gmid/opt)
├── verification/       # Channel S4P models (C0–C5), 5G/4G chip-top builders, route_manhattan/floorplan_opt, PDN stability
├── docs/               # Specifications, current status, module design docs, layout signoff reports, figures
├── config/             # PDK/tool configs, working revisions, boundary conditions, design catalog
├── tests/              # Pytest regression suite (netlist, layout checks, router/floorplan, gmid/opt, doc-link integrity)
└── web/design/         # Interactive browser-based design workbench
```

> Git carries sources, compact summaries, and selected previews. Heavy `.gds`/`.mag`/`.spef` deliverables and raw waveforms stay on local disk (regenerable via tracked Python builders). Retired historical evolution logs and early CML / `v0.1` snapshots are preserved in git history (`v1.0` / `b10e989`).

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
| Execution Plan, First-Silicon DFT & Tapeout Order | [docs/status/prelayout_plan.md](docs/status/prelayout_plan.md), [docs/status/open_issues.md](docs/status/open_issues.md) |
| Module Design Index (5G Plan-C & 4G Ring-VCO) | [docs/design/README.md](docs/design/README.md) |
| Physical Layout, Chip Floorplan & 2026-11-26 Audit | [docs/layout/README.md](docs/layout/README.md), [chip_floorplan_20261123.md](docs/layout/chip_floorplan_20261123.md) |
| Architecture, Specs, Area & Module Map | [docs/overview/architecture.md](docs/overview/architecture.md), [docs/overview/spec.md](docs/overview/spec.md), [docs/overview/area.md](docs/overview/area.md), [docs/overview/development_map.md](docs/overview/development_map.md) |
| Verification Methods, Jitter/Stats & $g_m/I_D$ Optimizer | [docs/verification/methods.md](docs/verification/methods.md), [docs/verification/optimization_toolkit.md](docs/verification/optimization_toolkit.md) |
| Interactive Design Workbench | [web/design/index.html](web/design/index.html) ([guide](web/design/README.md)) |
| Evidence Catalog & Retired Artifact Receipts | [results/catalog/README.md](results/catalog/README.md), [serdes_5g_signoff_20261126.json](results/catalog/serdes_5g_signoff_20261126.json) |
