`timescale 1fs/1fs
// Co-simulation wrapper. KP is an explicit smoke-test override, not a production edit.
module mixed_cdr_top #(parameter integer KP=8192)(
    input wire pair_clk, ctrl_clk, rst_n, enable, pair_valid, training_enable,
    input wire [1:0] pair_bits,
    input wire bundle_valid, previous_data,
    input wire [15:0] data_samples, edge_samples,
    output wire [15:0] word_data,
    output wire word_valid, aligned,
    output wire [5:0] phase_code,
    output wire [7:0] select_a, select_b, fine_b,
    output wire signed [5:0] vote_sum,
    output wire [4:0] transition_count,
    output wire vote_valid, step_valid, step_ready, step_applied, step_done,
    output wire locked, holdover, range_limited,
    output wire signed [31:0] frequency_q, phase_debt_q
);
    wire advance;
    bbpd_window_vote voter(ctrl_clk,rst_n,bundle_valid,previous_data,data_samples,edge_samples,
        vote_valid,vote_sum,transition_count);
    cdr_phase_frequency #(.KP(KP)) filter(ctrl_clk,rst_n,enable,vote_valid,vote_sum,transition_count,
        step_ready,step_applied,step_done,step_valid,advance,frequency_q,phase_debt_q,
        locked,holdover,range_limited);
    pi_step_commutator commutator(ctrl_clk,rst_n,step_valid,advance,step_ready,phase_code,
        select_a,select_b,fine_b,step_applied,step_done);
    rx_deserializer16 deserializer(pair_clk,rst_n,pair_valid,training_enable,pair_bits,
        word_data,word_valid,aligned);
endmodule
