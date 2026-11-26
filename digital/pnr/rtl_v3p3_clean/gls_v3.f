// Post-Route Gate-Level Simulation (GLS) filelist for serdes_digital_top_v3 (v3.1)
// Usable by both VCS and Verdi from repository root:
//   vcs -full64 -sverilog -f digital/pnr/rtl_v3/gls_v3.f ...
//   verdi -sv -f digital/pnr/rtl_v3/gls_v3.f -ssf results/digital/gls_v3_1/serdes_digital_top_v3_tt_gls.fsdb

+define+SKY130_FD_SC_HD__LPFLOW_BLEEDER_1_TIMING_V
results/digital/gls_v3_1/sky130_primitives_vcs.v
-v /home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v
digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/serdes_digital_top_v3.v
digital/pnr/rtl_v3/tb_serdes_digital_top_v3_gls.sv
