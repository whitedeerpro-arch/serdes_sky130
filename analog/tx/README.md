# Transmitter (`analog/tx/`)

SKY130A 1.8 V Zero-CML SST transmitter subsystems covering both the **5.0 Gb/s Dual-Rate Plan-C** (`v5_pdk`) and **4.0 Gb/s `v1.0` mainline** (`v4_pdk`). Project-wide status lives in [docs/status/current.md](../../docs/status/current.md) and [docs/design/tx_sst_v4.md](../../docs/design/tx_sst_v4.md).

## 1. 5.0 Gb/s Plan-C Dual-Rate TX SST (`sst/layout/variants/v5_pdk/`)

- **Netlists & Builder**: [`sst/spice/tx_sst_top_5g.spice`](sst/spice/tx_sst_top_5g.spice) (`tx_sst_driver_5g.spice` + `tx_sst_serializer16_5g.spice`) · [`sst/layout/build_tx_sst_v5_pdk.py`](sst/layout/build_tx_sst_v5_pdk.py)
- **Signed-Off Deliverables**:
  - [`sst/layout/variants/v5_pdk/`](sst/layout/variants/v5_pdk/) ([`summary.json`](sst/layout/variants/v5_pdk/summary.json)) — `256.8 × 169.58 µm`, 38 ports, `DRC = 0 / LVS = MATCH`, true CPEX **16/16 (12× 5G + 4× 4G) PASS** (spread `0.006–0.145 UI`, `Vdrv_rip ≤ 44.3 mVpp`, margin `100.1–226.7 mV`);
  - [`sst/layout/variants/v4p5_pdk/`](sst/layout/variants/v4p5_pdk/) — hardened TX `V_drv` LDO (`DRC = 0 / LVS = MATCH`, 3/3 skew CPEX PM `71.1–85.2°`, 200× MC `3σ ≤ 15.60 mV`).
- **Signoff Catalog**: [`results/catalog/serdes_5g_signoff_20261126.json`](../../results/catalog/serdes_5g_signoff_20261126.json)

## 2. 4.0 Gb/s `v1.0` Mainline — TX SST `v4.3` (`sst/`)

- **Netlists & Layout**: [`sst/spice/tx_sst_top.spice`](sst/spice/tx_sst_top.spice) (`tx_sst_serializer16.spice` + `tx_sst_driver.spice`) · [`sst/layout/variants/v4_pdk/`](sst/layout/variants/v4_pdk/README.md) (`5/5` cells `DRC=0 / LVS=MATCH`).
- **Architecture**: Static CMOS 16:4 serializer + 4-phase stagger retimers + 28-slice (23 Main + 5 Post-1 FFE) N-over-N **Source-Series-Terminated (SST)** line driver powered by a compact `1.8 V → 0.44 V` sub-regulator (`sst_vdrv_ldo_pdk`).
- **Testbenches**: [`sst/tb/`](sst/tb/) (`run_core_stress.py`, `run_pvt45.py`, `calibrate_core.py`, `postlayout/verify_tx_v4_pex.py`).

> Historical full-CML transmitter sources/testbenches (`v3/extra5`) were retired from the working tree and remain preserved in git history (`v1.0` / `b10e989`).
