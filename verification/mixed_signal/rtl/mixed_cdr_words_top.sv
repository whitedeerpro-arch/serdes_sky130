`timescale 1fs/1fs
// Co-simulation wrapper for the physical readout (rx_readout_deser16): everything runs on the
// readout word clock w.  phys = the 32 readout outputs read after w rising (rx_word_map order);
// sample_known = 0 when any edge output was in the unknown band (the bundle is not voted).
// KP is an explicit smoke-test override, not a production edit.
module mixed_cdr_words_top #(parameter integer KP=8192)(
    input wire clk, rst_n, enable, training_enable, sample_known,
    input wire [31:0] phys,
    output wire [15:0] word_data, data_samples, edge_samples,
    output wire word_valid, aligned, bundle_valid,
    output wire [3:0] offset,
    output wire [5:0] phase_code,
    output wire [7:0] select_a, select_b, fine_b,
    output wire signed [5:0] vote_sum,
    output wire [4:0] transition_count,
    output wire vote_valid, step_valid, step_ready, step_applied, step_done,
    output wire locked, holdover, range_limited,
    output wire signed [31:0] frequency_q, phase_debt_q
);
    wire previous_data, map_valid, advance;
    reg known_q;
    always @(posedge clk or negedge rst_n) if(!rst_n) known_q<=0; else known_q<=sample_known;
    assign bundle_valid = map_valid & known_q;
    rx_word_map map(clk,rst_n,phys,data_samples,edge_samples,previous_data,map_valid);
    bbpd_window_vote voter(clk,rst_n,bundle_valid,previous_data,data_samples,edge_samples,
        vote_valid,vote_sum,transition_count);
    cdr_phase_frequency #(.KP(KP)) filter(clk,rst_n,enable,vote_valid,vote_sum,transition_count,
        step_ready,step_applied,step_done,step_valid,advance,frequency_q,phase_debt_q,
        locked,holdover,range_limited);
    pi_step_commutator commutator(clk,rst_n,step_valid,advance,step_ready,phase_code,
        select_a,select_b,fine_b,step_applied,step_done);
    rx_word_align16 align(clk,rst_n,map_valid,training_enable,data_samples,word_data,word_valid,aligned,offset);
endmodule
