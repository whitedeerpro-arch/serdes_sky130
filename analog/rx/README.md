# Receiver (`analog/rx/`)

SKY130A 1.8 V CMOS SerDes receiver subsystems covering both the **5.0 Gb/s Plan-C** integrated top and the **4.0 Gb/s `v1.0` mainline**. Project-wide status lives in [docs/status/current.md](../../docs/status/current.md) and [docs/design/rx_cmos_v2.md](../../docs/design/rx_cmos_v2.md).

## 1. 5.0 Gb/s Plan-C Integrated RX (`cmos_rx/layout/variants/rx_top_5g_pdk/`)

- **Top-Level Netlist & Builder**: [`cmos_rx/spice/rx_cmos_top_5g_pdk.spice`](cmos_rx/spice/rx_cmos_top_5g_pdk.spice) · [`cmos_rx/layout/build_rx_cmos_top_5g_pdk.py`](cmos_rx/layout/build_rx_cmos_top_5g_pdk.py)
- **Signed-Off Deliverables**: [`cmos_rx/layout/variants/rx_top_5g_pdk/`](cmos_rx/layout/variants/rx_top_5g_pdk/) ([`summary.json`](cmos_rx/layout/variants/rx_top_5g_pdk/summary.json)) — `312.1 × 199.4 µm`, `DRC = 0 / FP = 0 / DC & Open LVS = MATCH` (72/74 ports), integrating:
  - **W3 Shunt-Peaked CTLE** (`ctle_shunt_5g_w3_pdk`): 45/45 AC + 400× MC `3σ ≤ 20.28 mV`, `M5 = 0%`;
  - **5G Double-Tail Slicer** (`slicer_5g_pdk`): 6/6 PVT + 250/250 MC `3σ ≤ 20.30 mV`, `M5 = 0%`;
  - **5G 4-Phase CMOS PI v3** (`v5g_4ph_v3_pdk`): 6/6 nominal `ALL_OK` + 24× cold MC `0/24` flips/dead (`20/24 < 30 ps`, `M5 = 0%`). Earlier 5G PI candidate documented in [`v5g_pdk/README.md`](cmos_rx/layout/variants/v5g_pdk/README.md).
- **Signoff Catalog**: [`results/catalog/serdes_5g_signoff_20261126.json`](../../results/catalog/serdes_5g_signoff_20261126.json)

## 2. 4.0 Gb/s `v1.0` Mainline — CMOS RX `v2.2` (`cmos_rx/`)

- **Top-Level Netlist & Layout**: [`cmos_rx/spice/rx_cmos_top.spice`](cmos_rx/spice/rx_cmos_top.spice) · [`cmos_rx/layout/variants/v2_pdk/`](cmos_rx/layout/variants/v2_pdk/README.md) (`245.3 × 195.4 µm`, 8/8 cells `DRC=0 / LVS=MATCH`).
- **Architecture**: On-die `100 Ω` termination + 4-level tunable PDK CTLE → 2 GHz 64-code pure-CMOS PI + 8-phase 1 GHz quadrature `÷2` → 8× quarter-rate Double-Tail dynamic CMOS slicers → pitch-matched 8→32 static CMOS deserializer (`250 MHz` word clock).
- **Verification**: [`cmos_rx/tb/`](cmos_rx/tb/) (`ctle/`, `pi/`, `slicer/`, `link/`, `postlayout/verify_rx_v2_pex.py`) — 45/45 schematic replay + 3/3 CPEX replay driven by TX SST `FFE=3 → C2_loss6` waveforms (0 data / 0 edge errors).

> Historical full-CML receiver sources/testbenches (`ac_trim/c2/W40`) were retired from the working tree and remain preserved in git history (`v1.0` / `b10e989`).
