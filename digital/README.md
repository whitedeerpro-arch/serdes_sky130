# Digital Subsystems (`digital/`)

SystemVerilog RTL, behavioral testbenches, unified OpenROAD SKY130A (`sky130_fd_sc_hd`) Place & Route flow, and VCS SDF post-layout gate-level signoff for the 4 Gb/s SerDes.

## 1. Active Signed-Off Macro — `serdes_digital_top_v3` (v3.1)

- **RTL Source**: [`pnr/rtl_v3/`](pnr/rtl_v3/) (`serdes_digital_top_v3.sv` integrating `pll_control_top`, `tx_ingress_control`, shared `rx_word_map`, `rx_word_align16` + `rx_async_word_fifo`, and 2nd-order `rx_cdr_loop`).
- **P&R & GLS Flows**: [`pnr/run_unified_v3_pnr.py`](pnr/run_unified_v3_pnr.py) (Yosys + OpenROAD + OpenRCX + Magic DRC + Netgen LVS) and [`pnr/run_v3_gls_vcs.py`](pnr/run_v3_gls_vcs.py) (4-mode RTL + 3-corner SDF 3.0 GLS + SVA + Verdi FSDB).
- **Deliverables**: [`pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/`](pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/) — tracked post-P&R Verilog (`serdes_digital_top_v3.v`), layout preview (`.png`), and machine-readable [`summary.json`](pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/summary.json) (`.gds`/`.def`/`_pg.v` stay on local disk / GitHub Releases).
- **Verification** covers physical review, three-corner STA, an RTL reference, and three SDF gate-level modes. The design report gives the clock boundaries, assertions, and CDC exceptions. [Design and signoff report](../docs/design/digital_top_v3.md)

## 2. Subsystem Unit RTL & Reference Directories

| Directory | Contents |
|---|---|
| [`pll/`](pll/README.md) | Standalone PLL coarse-search, lock-detect, and startup-supervisor RTL & unit testbenches |
| [`tx/`](tx/) | Standalone TX word-capture & ingress control RTL |
| [`rx/`](rx/README.md) | Standalone RX word-map, aligner, async FIFO, and BBPD CDR RTL & closed-loop tests |
| [`common/`](common/) | Shared synchronizer & persistence helper modules |
| [`pnr/rtl_v2/`](pnr/rtl_v2/) | Previous 4-block standalone RTL snapshot (superseded by `pnr/rtl_v3/`) |
