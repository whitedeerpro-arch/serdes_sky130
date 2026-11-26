# Digital Subsystems (`digital/`)

SystemVerilog RTL, behavioral testbenches, unified OpenROAD SKY130A (`sky130_fd_sc_hd`) Place & Route flows, multi-corner OCV STA, and VCS SDF post-layout gate-level signoff for both the **5.0 Gb/s Dual-Rate Plan-C** and **4.0 Gb/s `v1.0`** SerDes macros.

## 1. 5.0 Gb/s Dual-Rate 32-bit Digital Top — `serdes_digital_top_v4` (`v4p1`, 2026-11-26)

- **RTL Source**: [`pnr/rtl_v4_32b/`](pnr/rtl_v4_32b/) (`serdes_digital_top_v4.sv` integrating 32-bit rate-divided TX ingress, RX 16→32 packer / word aligner / async 32-bit FIFO, 32-bit BBPD CDR loop, shared `rx_word_map`, and 5-bit dual-rate `pll_control_top`, plus `mon_sync` / `mon_persist`).
- **P&R Scripts**: [`pnr/run_v4p1_5g_coopt_pnr.py`](pnr/run_v4p1_5g_coopt_pnr.py) (pin-co-optimized for Plan-C East RX zero-crossing bus) and [`pnr/run_v4_32b_pnr.py`](pnr/run_v4_32b_pnr.py).
- **Signed-Off Deliverables**: [`pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/`](pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/) ([`summary.json`](pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/summary.json)) — `385.9 × 353.6 µm` (`−7.2%` vs `v4_32b`), `DRC=0 / LVS=MATCH`, 6-corner ±5% OCV 5G/4G all MET (`setup ≥ +0.059 ns / hold ≥ +0.073 ns`), CDC `26/26`, RX 33-bit `0` crossings. Earlier `v4_32b` macro preserved in [`pnr/variants/hd_pnr_v4_32b/`](pnr/variants/hd_pnr_v4_32b/).
- **Signoff Catalog**: [`results/catalog/serdes_5g_signoff_20261126.json`](../results/catalog/serdes_5g_signoff_20261126.json)

## 2. 4.0 Gb/s `v1.0` Signed-Off Macro — `serdes_digital_top_v3` (`v3.1`)

- **RTL Source**: [`pnr/rtl_v3/`](pnr/rtl_v3/) (`serdes_digital_top_v3.sv` integrating `pll_control_top`, `tx_ingress_control`, shared `rx_word_map`, `rx_word_align16` + `rx_async_word_fifo`, and 2nd-order `rx_cdr_loop`).
- **P&R & GLS Flows**: [`pnr/run_unified_v3_pnr.py`](pnr/run_unified_v3_pnr.py) (Yosys + OpenROAD + OpenRCX + Magic DRC + Netgen LVS) and [`pnr/run_v3_gls_vcs.py`](pnr/run_v3_gls_vcs.py) (4-mode RTL + 3-corner SDF 3.0 GLS + SVA + Verdi FSDB).
- **Deliverables**: [`pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/`](pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/) — post-P&R Verilog (`serdes_digital_top_v3.v`), layout preview (`.png`), and [`summary.json`](pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/summary.json) (`338.1 × 307.4 µm`, 3-corner STA MET, 122,608 SVA checks/mode PASS). Subsequent `v3.2` CMOS-RX polarity snapshot lives in [`pnr/variants/hd_pnr_v3p2_cmos_rx/`](pnr/variants/hd_pnr_v3p2_cmos_rx/).
- **Design Report**: [docs/design/digital_top_v3.md](../docs/design/digital_top_v3.md) · [docs/status/current.md](../docs/status/current.md)

## 3. Standalone Helper RTL

- [`rx/rtl/rx_deserializer16.sv`](rx/rtl/rx_deserializer16.sv) — standalone 1:16 RX deserializer behavioral RTL reference.
