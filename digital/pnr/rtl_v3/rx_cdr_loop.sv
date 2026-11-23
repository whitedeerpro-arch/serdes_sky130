// Lean RX CDR loop (v3): 250 MHz 2-tick BBPD pre-accumulator -> internal synchronous /2
// (125 MHz / 8.0 ns) Type-II filter & PI commutator with exact physical bitwidths.
module rx_cdr_loop (
    input  wire              ctrl_clk,
    input  wire              rst_n,
    input  wire              enable,
    input  wire              bundle_valid,
    input  wire              previous_data,
    input  wire       [15:0] data_samples,
    input  wire       [15:0] edge_samples,
    output wire       [5:0]  phase_code,
    output wire       [7:0]  select_a,
    output wire       [7:0]  select_b,
    output wire       [7:0]  fine_b,
    output wire              locked,
    output wire              holdover,
    output wire              range_limited,
    output wire              phase_applied,
    output wire signed [16:0] frequency_q,
    output wire signed [22:0] phase_debt_q
);
    // Synchronous /2 clock generator (250 MHz ctrl_clk -> 125 MHz cdr_clk_div2)
    // Keep phase_hi_q separate so cdr_clk_div2 drives ONLY clock pins (pure CTS clock net).
    (* keep = "true" *) reg cdr_clk_div2_q;
    reg phase_hi_q;
    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            cdr_clk_div2_q <= 1'b0;
            phase_hi_q     <= 1'b0;
        end else begin
            cdr_clk_div2_q <= ~cdr_clk_div2_q;
            phase_hi_q     <= ~phase_hi_q;
        end
    end
    (* keep = "true" *) wire cdr_clk_div2;
    assign cdr_clk_div2 = cdr_clk_div2_q;

    wire              pair_valid;
    wire signed [5:0] pair_sum_a, pair_sum_b;
    wire        [4:0] pair_cnt_a, pair_cnt_b;

    bbpd_window_vote voter (
        .ctrl_clk     (ctrl_clk),
        .rst_n        (rst_n),
        .phase_hi     (phase_hi_q),
        .bundle_valid (bundle_valid),
        .previous_data(previous_data),
        .data_samples (data_samples),
        .edge_samples (edge_samples),
        .pair_valid   (pair_valid),
        .pair_sum_a   (pair_sum_a),
        .pair_sum_b   (pair_sum_b),
        .pair_cnt_a   (pair_cnt_a),
        .pair_cnt_b   (pair_cnt_b)
    );

    wire ready, valid, advance, done;

    cdr_phase_frequency filter (
        .ctrl_clk     (cdr_clk_div2),
        .rst_n        (rst_n),
        .enable       (enable),
        .vote_valid   (pair_valid),
        .vote_sum_a   (pair_sum_a),
        .vote_sum_b   (pair_sum_b),
        .trans_cnt_a  (pair_cnt_a),
        .trans_cnt_b  (pair_cnt_b),
        .step_ready   (ready),
        .step_applied (phase_applied),
        .step_done    (done),
        .step_valid   (valid),
        .advance      (advance),
        .frequency_q  (frequency_q),
        .phase_debt_q (phase_debt_q),
        .locked       (locked),
        .holdover     (holdover),
        .range_limited(range_limited)
    );

    pi_step_commutator commutator (
        .ctrl_clk  (cdr_clk_div2),
        .rst_n     (rst_n),
        .step_valid(valid),
        .advance   (advance),
        .step_ready(ready),
        .phase_code(phase_code),
        .select_a  (select_a),
        .select_b  (select_b),
        .fine_b    (fine_b),
        .applied   (phase_applied),
        .done      (done)
    );
endmodule
