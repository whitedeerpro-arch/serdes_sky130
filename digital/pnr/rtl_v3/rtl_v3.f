// RTL Golden filelist for serdes_digital_top_v3 (v3.1) — usable by both VCS and Verdi
// Run from repository root:
//   vcs -full64 -sverilog -f digital/pnr/rtl_v3/rtl_v3.f ...
//   verdi -sv -f digital/pnr/rtl_v3/rtl_v3.f -ssf results/digital/gls_v3_1/serdes_digital_top_v3_tt_gls.fsdb

digital/pnr/rtl_v3/mon_sync.sv
digital/pnr/rtl_v3/mon_persist.sv
digital/pnr/rtl_v3/pll_startup_supervisor.sv
digital/pnr/rtl_v3/pll_coarse_ctrl.sv
digital/pnr/rtl_v3/pll_lock_detect.sv
digital/pnr/rtl_v3/pll_control_top.sv
digital/pnr/rtl_v3/tx_ingress_control.sv
digital/pnr/rtl_v3/rx_word_map.sv
digital/pnr/rtl_v3/rx_word_align16.sv
digital/pnr/rtl_v3/rx_async_word_fifo.sv
digital/pnr/rtl_v3/bbpd_window_vote.sv
digital/pnr/rtl_v3/cdr_phase_frequency.sv
digital/pnr/rtl_v3/pi_step_commutator.sv
digital/pnr/rtl_v3/rx_cdr_loop.sv
digital/pnr/rtl_v3/serdes_digital_top_v3.sv
digital/pnr/rtl_v3/tb_serdes_digital_top_v3_gls.sv
