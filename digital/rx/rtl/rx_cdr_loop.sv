// All ports except reset are in the recovered /16-UI control domain.
// Physical sample demux/alignment and control CDC/retiming are external.
module rx_cdr_loop(
    input wire ctrl_clk, rst_n, enable, bundle_valid, previous_data,
    input wire [15:0] data_samples, edge_samples,
    output wire [5:0] phase_code,
    output wire [7:0] select_a, select_b, fine_b,
    output wire locked, holdover, range_limited, phase_applied,
    output wire signed [31:0] frequency_q, phase_debt_q
);
    wire vote_valid,ready,valid,advance,done;
    wire signed [5:0] vote;
    wire [4:0] transitions;
    bbpd_window_vote voter(ctrl_clk,rst_n,bundle_valid,previous_data,data_samples,edge_samples,vote_valid,vote,transitions);
    cdr_phase_frequency filter(ctrl_clk,rst_n,enable,vote_valid,vote,transitions,ready,phase_applied,done,
        valid,advance,frequency_q,phase_debt_q,locked,holdover,range_limited);
    pi_step_commutator commutator(ctrl_clk,rst_n,valid,advance,ready,phase_code,select_a,select_b,fine_b,phase_applied,done);
endmodule
