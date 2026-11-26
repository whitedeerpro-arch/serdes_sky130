# Simple SerDes — SKY130A 1.8 V 4 Gb/s NRZ SerDes

An open-source **4 Gb/s NRZ SerDes** design in **SkyWater SKY130A (130 nm CMOS, 1.8 V)**. The v1.0 baseline covers subsystem verification and chip floorplanning. The transistor and physical implementation flows use ngspice 47, Magic, Netgen, OpenROAD, OpenRCX, OpenSTA, and Yosys. The published SDF gate-level regression uses Synopsys VCS.

## Architecture

- **Clocking** uses a 250 MHz reference and a four-stage 2 GHz differential CML ring PLL, with independent HV18 quiet supply and BIAS v2. The chip integration targets the SAFF-TSPC feedback divider and r5 CML-to-CMOS receiver.
- **TX** uses a static CMOS 16:4 serializer and a four-phase N-over-N source-series-terminated (SST) driver with two-tap FFE.
- **RX** uses on-die termination, CTLE, a CMOS phase interpolator, quarter-rate double-tail samplers, and separate 16-bit data and edge outputs.
- **Digital** integrates PLL startup control, TX ingress, RX word alignment and CDC, and a multi-rate BBPD CDR.

![Chip floorplan and planned damped PDN](docs/figures/system/serdes_chip_floorplan_20261123.png)

The [current status](docs/status/current.md) records measured results, stimulus and load boundaries, and open integration items. See the [adopted sources](config/mainline_working_revision.toml) and [fixed evidence index](results/catalog/v1_0_subsystem_evidence.json) for revision and result identity.

## Repository Layout

```text
simple_serdes_fork1/
├── analog/
│   ├── pll/            # 2 GHz PLL v4 (vco/, cp/, loop_filter/, pfd/, divider/, coarse/, top/)
│   ├── tx/             # TX mainline: sst/ (4 Gb/s NRZ SST); legacy CML in serializer/, output_driver/, ...
│   ├── rx/             # RX mainline: cmos_rx/ (4 Gb/s NRZ RX); legacy CML in ctle/, pi/, sampler/, ...
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

> Git carries the sources, compact summaries and selected previews. Generated layout and timing databases and raw waveforms are local artifacts. Use the module layout guides for generation inputs and tool requirements.

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
