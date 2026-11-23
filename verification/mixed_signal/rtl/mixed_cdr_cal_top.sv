`timescale 1fs/1fs
// Co-simulation wrapper: mixed_cdr_words_top plus the sampler offset calibration (rx_offset_cal) on
// the same word clock and the same 32 readout outputs.  Start-up order: cal_start (input in
// electrical idle) -> SAR on all four lanes -> cal_done; the CDR loop is enabled only after
// cal_done.  cal_codes = {e1, e0, d1, d0}, 6 bits each, drive the trim DAC code pins of
// serdes_rx_half_rate_samples_ac_trim_rk.  NW / SETTLE: words counted / discarded per SAR step.
module mixed_cdr_cal_top #(parameter integer KP=8192, NW=2, SETTLE=4)(
    input wire clk, rst_n, enable, training_enable, sample_known, cal_start,
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
    output wire signed [31:0] frequency_q, phase_debt_q,
    output wire [23:0] cal_codes,
    output wire cal_busy, cal_done
);
    mixed_cdr_words_top #(.KP(KP)) core(
        .clk(clk), .rst_n(rst_n), .enable(enable & cal_done), .training_enable(training_enable),
        .sample_known(sample_known), .phys(phys), .word_data(word_data), .data_samples(data_samples),
        .edge_samples(edge_samples), .word_valid(word_valid), .aligned(aligned), .bundle_valid(bundle_valid),
        .offset(offset), .phase_code(phase_code), .select_a(select_a), .select_b(select_b), .fine_b(fine_b),
        .vote_sum(vote_sum), .transition_count(transition_count), .vote_valid(vote_valid),
        .step_valid(step_valid), .step_ready(step_ready), .step_applied(step_applied), .step_done(step_done),
        .locked(locked), .holdover(holdover), .range_limited(range_limited),
        .frequency_q(frequency_q), .phase_debt_q(phase_debt_q));
    rx_offset_cal #(.NW(NW), .SETTLE(SETTLE)) cal(
        .clk(clk), .rst_n(rst_n), .start(cal_start), .phys(phys), .codes(cal_codes), .busy(cal_busy), .done(cal_done));
endmodule
