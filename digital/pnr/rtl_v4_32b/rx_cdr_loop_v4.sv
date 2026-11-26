// Single-clock 32-UI RX CDR loop running natively on rx_clk_div2 (125 MHz @ 4G / 156.25 MHz @ 5G, 6.40 ns!).
// Zero 250/312.5 MHz voting logic! Per-domain external rst_n 2-FF sync releases voter, filter,
// and PI commutator on the exact same rx_clk_div2 cycle with zero cross-clock async removal violations.
module rx_cdr_loop_v4 (
    input  wire              rx_clk_div2,
    input  wire              rst_n,
    input  wire              enable,
    input  wire              bundle_valid,
    input  wire              previous_data,
    input  wire       [31:0] data_samples,
    input  wire       [31:0] edge_samples,
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
    // Per-domain 2-FF reset synchronizer directly from external rst_n on rx_clk_div2.
    // Matching 3rd-stage leaf FFs: rst_v0, rst_v1, rst_pi_r, and filter.rst_a..d!
    (* ASYNC_REG = "TRUE", keep = "true" *) reg cdr_rst_s0, cdr_rst_s1;
    (* keep = "true" *) reg rst_v0, rst_v1, rst_pi_r;
    always @(posedge rx_clk_div2 or negedge rst_n) begin
        if (!rst_n) begin
            cdr_rst_s0 <= 1'b0;
            cdr_rst_s1 <= 1'b0;
            rst_v0     <= 1'b0;
            rst_v1     <= 1'b0;
            rst_pi_r   <= 1'b0;
        end else begin
            cdr_rst_s0 <= 1'b1;
            cdr_rst_s1 <= cdr_rst_s0;
            rst_v0     <= cdr_rst_s1;
            rst_v1     <= cdr_rst_s1;
            rst_pi_r   <= cdr_rst_s1;
        end
    end

    wire              v_valid, v_has_trans, v_err_pos, v_err_neg;
    wire signed [6:0] v_sum;
    wire        [5:0] v_cnt;

    bbpd_window_vote32 voter (
        .ctrl_clk     (rx_clk_div2),
        .rst_n_0      (rst_v0),
        .rst_n_1      (rst_v1),
        .bundle_valid (bundle_valid),
        .previous_data(previous_data),
        .data_samples (data_samples),
        .edge_samples (edge_samples),
        .vote_valid   (v_valid),
        .has_trans    (v_has_trans),
        .err_pos      (v_err_pos),
        .err_neg      (v_err_neg),
        .vote_sum     (v_sum),
        .trans_cnt    (v_cnt)
    );

    wire ready, valid, advance, done;

    cdr_phase_frequency_v4 filter (
        .ctrl_clk     (rx_clk_div2),
        .rst_n        (rst_n),
        .rst_sync_in  (cdr_rst_s1),
        .enable       (enable),
        .vote_valid   (v_valid),
        .has_trans    (v_has_trans),
        .err_pos      (v_err_pos),
        .err_neg      (v_err_neg),
        .vote_sum     (v_sum),
        .trans_cnt    (v_cnt),
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
        .ctrl_clk  (rx_clk_div2),
        .rst_n     (rst_pi_r),
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
