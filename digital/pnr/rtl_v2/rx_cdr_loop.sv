// Timing-closed v2 RX CDR loop top (250 MHz / 4.0 ns SS-closed).
// Exact same port list as v1 rx_cdr_loop.
module rx_cdr_loop (
    input  wire               ctrl_clk,
    input  wire               rst_n,
    input  wire               enable,
    input  wire               bundle_valid,
    input  wire               previous_data,
    input  wire        [15:0] data_samples,
    input  wire        [15:0] edge_samples,
    output wire        [5:0]  phase_code,
    output wire        [7:0]  select_a,
    output wire        [7:0]  select_b,
    output wire        [7:0]  fine_b,
    output wire               locked,
    output wire               holdover,
    output wire               range_limited,
    output wire               phase_applied,
    output wire signed [31:0] frequency_q,
    output wire signed [31:0] phase_debt_q
);
    wire vote_valid, ready, valid, advance, done;
    wire signed [5:0] vote;
    wire [4:0] transitions;

    bbpd_window_vote voter (
        .ctrl_clk(ctrl_clk), .rst_n(rst_n), .bundle_valid(bundle_valid),
        .previous_data(previous_data), .data_samples(data_samples), .edge_samples(edge_samples),
        .vote_valid(vote_valid), .vote_sum(vote), .transition_count(transitions)
    );

    cdr_phase_frequency filter (
        .ctrl_clk(ctrl_clk), .rst_n(rst_n), .enable(enable), .vote_valid(vote_valid),
        .vote_sum(vote), .transition_count(transitions),
        .step_ready(ready), .step_applied(phase_applied), .step_done(done),
        .step_valid(valid), .advance(advance),
        .frequency_q(frequency_q), .phase_debt_q(phase_debt_q),
        .locked(locked), .holdover(holdover), .range_limited(range_limited)
    );

    pi_step_commutator #(.PIPE_IN(1)) commutator (
        .ctrl_clk(ctrl_clk), .rst_n(rst_n), .step_valid(valid), .advance(advance),
        .step_ready(ready), .phase_code(phase_code),
        .select_a(select_a), .select_b(select_b), .fine_b(fine_b),
        .applied(phase_applied), .done(done)
    );
endmodule
