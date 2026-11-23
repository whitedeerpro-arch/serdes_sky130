// Lean Type-II bang-bang CDR filter running on synchronous /2 (125 MHz / 8.0 ns) clock (v3).
// One control tick = 32 recovered UI (2x 16-UI bundles summed by bbpd_window_vote).
// All registers trimmed to exact physical ranges (eliminates redundant 32-bit counters/adders):
//   frequency_q         : 17-bit signed (Q16 PI steps / 32-UI tick, +/-49152 => +/-732 ppm)
//   phase_debt_q        : 23-bit signed (Q16 PI steps, [-2,097,152, +2,097,151] => +/-32 PI steps)
//   age                 :  9-bit unsigned (NO_TRANSITION_TICKS = 128 => 4096 UI)
//   quality_ticks       :  7-bit unsigned (QUALITY_TICKS = 64 => 2048 UI)
//   quality_transitions : 12-bit unsigned (max 64 * 32 = 2048)
//   quality_sum         : 13-bit signed   (range -2048 .. +2048)
//   good_count/bad_count:  3-bit unsigned (GOOD_WINDOWS = 4, BAD_WINDOWS = 4)
// Uses 3-chunk parallel carry-select (7+7+10 bit) + 3-bit power-of-2 saturation check for
// huge 125 MHz SS timing margin (> +2.0 ns) with minimal area.
module cdr_phase_frequency #(
    parameter integer QUALITY_TICKS       = 64,
    parameter integer GOOD_WINDOWS        = 4,
    parameter integer BAD_WINDOWS         = 4,
    parameter integer NO_TRANSITION_TICKS = 128
) (
    input  wire              ctrl_clk,
    input  wire              rst_n,
    input  wire              enable,
    input  wire              vote_valid,
    input  wire signed [5:0] vote_sum_a,
    input  wire signed [5:0] vote_sum_b,
    input  wire        [4:0] trans_cnt_a,
    input  wire        [4:0] trans_cnt_b,
    input  wire              step_ready,
    input  wire              step_applied,
    input  wire              step_done,
    output wire              step_valid,
    output wire              advance,
    output reg signed [16:0] frequency_q,
    output reg signed [22:0] phase_debt_q,
    output reg               locked,
    output reg               holdover,
    output reg               range_limited
);
    // Fixed power-of-two gains for 32-UI tick (125 MHz):
    //   KP = 16384 (1<<14), KI = 128 (1<<7), ONE = 65536 (4<<14)
    //   FREQ_LIMIT = +/-49152 (+/-384 << 7 => +/-732 ppm)
    //   DEBT_LIMIT = [-2,097,152, +2,097,151] (+/-32 PI steps, exact 3-bit MSB clamp!)
    localparam signed [22:0] ONE_23         = 23'sd65536;
    localparam signed [10:0] FHI_LIMIT_11   = 11'sd384;
    localparam signed [16:0] FREQ_LIMIT_17  = 17'sd49152;
    localparam [8:0]         NO_TRANS_9     = NO_TRANSITION_TICKS[8:0];
    localparam [6:0]         QTICKS_LAST    = QUALITY_TICKS[6:0] - 7'd1;
    localparam [2:0]         GOOD_W_3       = GOOD_WINDOWS[2:0];
    localparam [2:0]         GOOD_W_M1      = GOOD_WINDOWS[2:0] - 3'd1;
    localparam [2:0]         BAD_W_3        = BAD_WINDOWS[2:0];
    localparam [2:0]         BAD_W_M1       = BAD_WINDOWS[2:0] - 3'd1;

    // Input capture on 125 MHz cdr_clk_div2 (ZERO extra cycle latency!):
    // 3b+4b carry-select sums the two 16-UI ticks on rx_word_clk -> cdr_clk_div2 (~2.8 ns vs ~5.8 ns window!).
    wire signed [6:0] va7 = {vote_sum_a[5], vote_sum_a};
    wire signed [6:0] vb7 = {vote_sum_b[5], vote_sum_b};
    wire        [3:0] pv_lo4 = {1'b0, va7[2:0]} + {1'b0, vb7[2:0]};
    /* verilator lint_off UNUSED */
    (* keep = "true" *) wire [4:0] pv_hi0w;
    (* keep = "true" *) wire [4:0] pv_hi1w;
    (* keep = "true" *) wire [3:0] pc_hi0w;
    (* keep = "true" *) wire [3:0] pc_hi1w;
    /* verilator lint_on UNUSED */
    assign pv_hi0w = {va7[6:3], 1'b0} + {vb7[6:3], 1'b0};
    assign pv_hi1w = {va7[6:3], 1'b1} + {vb7[6:3], 1'b1};
    wire signed [6:0] pair_vote_c = $signed({pv_lo4[3] ? pv_hi1w[4:1] : pv_hi0w[4:1], pv_lo4[2:0]});

    wire        [3:0] pc_lo4 = {1'b0, trans_cnt_a[2:0]} + {1'b0, trans_cnt_b[2:0]};
    assign pc_hi0w = {1'b0, trans_cnt_a[4:3], 1'b0} + {1'b0, trans_cnt_b[4:3], 1'b0};
    assign pc_hi1w = {1'b0, trans_cnt_a[4:3], 1'b1} + {1'b0, trans_cnt_b[4:3], 1'b1};
    wire        [5:0] pair_cnt_c = {pc_lo4[3] ? pc_hi1w[3:1] : pc_hi0w[3:1], pc_lo4[2:0]};
    wire              has_trans_c = vote_valid && (|trans_cnt_a || |trans_cnt_b);
    wire              err_pos_c   = has_trans_c && (!pair_vote_c[6]) && (pair_vote_c[5:0] != 6'd0);
    wire              err_neg_c   = has_trans_c && pair_vote_c[6];

    reg              in_valid_r;
    reg              in_has_trans_r;
    reg              in_err_pos_r;
    reg              in_err_neg_r;
    reg signed [6:0] in_vote_r;
    reg        [5:0] in_trans_r;
    reg              enable_r;

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            in_valid_r     <= 1'b0;
            in_has_trans_r <= 1'b0;
            in_err_pos_r   <= 1'b0;
            in_err_neg_r   <= 1'b0;
            in_vote_r      <= 7'sd0;
            in_trans_r     <= 6'd0;
            enable_r       <= 1'b0;
        end else begin
            in_valid_r     <= vote_valid;
            in_has_trans_r <= has_trans_c;
            in_err_pos_r   <= err_pos_c;
            in_err_neg_r   <= err_neg_c;
            in_vote_r      <= pair_vote_c;
            in_trans_r     <= pair_cnt_c;
            enable_r       <= enable;
        end
    end

    reg               inflight, issued_advance;
    reg        [8:0]  age;
    reg        [6:0]  quality_ticks;
    reg        [11:0] quality_transitions;
    reg signed [12:0] quality_sum;
    reg        [2:0]  good_count, bad_count;

    // Exact MSB check for |phase_debt_q| < 2*ONE (1<<17)
    wire debt_in_2one = (phase_debt_q[22:17] == 6'b000000) || (phase_debt_q[22:17] == 6'b111111);

    // Zero-latency shadow registers of (|phase_debt_q| >= ONE) and (!phase_debt_q[22])!
    // Bit-for-bit identical to combinational debt_pos_ge1/debt_neg_le1 on every cycle,
    // while cutting cdr_phase_frequency -> pi_step_commutator to a single 3-input AND (+3.0 ns SS!).
    reg debt_ge1_r, debt_adv_r;
    assign step_valid = enable_r && !inflight && debt_ge1_r;
    assign advance    = debt_adv_r;

    reg signed [10:0] f_hi_raw;
    reg signed [16:0] fnext;
    reg               f_sat;

    // Stage 1 -> Stage 2 clean 1-cycle pipeline for phase_debt_q increment:
    //   Stage 1 (3 gate levels): s2_delta_q = frequency_q + KP_term (only upper 4 bits [17:14] add!)
    //   Stage 2 (~6 gate levels): phase_debt_q = sat22(phase_debt_q + s2_delta_q + step_term)
    //     - Lower 16 bits [15:0]: 4+4+4+4 carry-select 2-operand adder (~2.6 ns SS)
    //     - Upper 8 bits  [23:16]: 4+4 carry-select with cin=0/1 in parallel (~2.8 ns SS)
    //     - Cuts critical path from 14 levels (-0.62 ns) -> ~6-7 levels (+2.5 ns SS) & shrinks area!
    reg               s2_enable;
    reg signed [17:0] s2_delta_q;

    wire signed [3:0] kp_hi4   = in_err_pos_r ? 4'sd1 : (in_err_neg_r ? -4'sd1 : 4'sd0);
    wire signed [3:0] d_hi4_s1 = $signed({frequency_q[16], frequency_q[16:14]}) + kp_hi4;
    wire signed [17:0] delta_s1_next = enable_r ? $signed({d_hi4_s1, frequency_q[13:0]}) : 18'sd0;

    // Lower 16 bits [15:0]: 2-level parallel carry-select (4+4 lo8 || 4+4 hi8 for cin=0/1) -> c16_out in ~3.0 ns!
    wire [4:0] p_n0 = {1'b0, phase_debt_q[3:0]} + {1'b0, s2_delta_q[3:0]};
    /* verilator lint_off UNUSED */
    (* keep = "true" *) wire [5:0] p_n1_0w;
    (* keep = "true" *) wire [5:0] p_n1_1w;
    (* keep = "true" *) wire [5:0] p_n2_0w;
    (* keep = "true" *) wire [5:0] p_n2_1w;
    (* keep = "true" *) wire [5:0] p_n3_0w;
    (* keep = "true" *) wire [5:0] p_n3_1w;
    /* verilator lint_on UNUSED */
    assign p_n1_0w = {1'b0, phase_debt_q[7:4],   1'b0} + {1'b0, s2_delta_q[7:4],   1'b0};
    assign p_n1_1w = {1'b0, phase_debt_q[7:4],   1'b1} + {1'b0, s2_delta_q[7:4],   1'b1};
    wire [3:0] p_n1    = p_n0[4] ? p_n1_1w[4:1] : p_n1_0w[4:1];
    wire       c8_out  = p_n1_0w[5] | (p_n1_1w[5] & p_n0[4]);

    assign p_n2_0w = {1'b0, phase_debt_q[11:8],  1'b0} + {1'b0, s2_delta_q[11:8],  1'b0};
    assign p_n2_1w = {1'b0, phase_debt_q[11:8],  1'b1} + {1'b0, s2_delta_q[11:8],  1'b1};
    assign p_n3_0w = {1'b0, phase_debt_q[15:12], 1'b0} + {1'b0, s2_delta_q[15:12], 1'b0};
    assign p_n3_1w = {1'b0, phase_debt_q[15:12], 1'b1} + {1'b0, s2_delta_q[15:12], 1'b1};

    // Speculative hi8 for c8_out=0 and c8_out=1 in parallel with lo8!
    wire       c16_if0 = p_n3_0w[5] | (p_n3_1w[5] & p_n2_0w[5]);
    wire       c16_if1 = p_n3_0w[5] | (p_n3_1w[5] & p_n2_1w[5]);
    wire       c16_out = c8_out ? c16_if1 : c16_if0;
    wire       c12_out = c8_out ? p_n2_1w[5] : p_n2_0w[5];
    wire [3:0] p_n2    = c8_out  ? p_n2_1w[4:1] : p_n2_0w[4:1];
    wire [3:0] p_n3    = c12_out ? p_n3_1w[4:1] : p_n3_0w[4:1];
    wire [15:0] p_lo16 = {p_n3, p_n2, p_n1, p_n0[3:0]};

    // Upper 8 bits [23:16] = {phase_debt_q[22], phase_debt_q[22:16]} + delta_hi + step_hi + c16_out
    // delta_hi is in [-2, +1], step_hi is in [-1, +1] -> combined inc_u4 is in [-3, +2] (4-bit signed)
    wire signed [3:0] step_hi4 = step_applied ? (issued_advance ? -4'sd1 : 4'sd1) : 4'sd0;
    wire signed [3:0] inc_u4   = $signed({{2{s2_delta_q[17]}}, s2_delta_q[17:16]}) + step_hi4;
    wire [7:0]        inc_u8   = {{4{inc_u4[3]}}, inc_u4};
    wire [7:0]        pd_u8    = {phase_debt_q[22], phase_debt_q[22:16]};

    // Parallel 4b + 4b carry-select + speculative saturation for cin=0 and cin=1 (c16_out drives ONLY final 2:1 mux!)
    /* verilator lint_off UNUSED */
    (* keep = "true" *) wire [5:0] u_lo0w;
    (* keep = "true" *) wire [5:0] u_lo1w;
    (* keep = "true" *) wire [4:0] u_hi0w;
    (* keep = "true" *) wire [4:0] u_hi1w;
    /* verilator lint_on UNUSED */
    assign u_lo0w = {1'b0, pd_u8[3:0], 1'b0} + {1'b0, inc_u8[3:0], 1'b0};
    assign u_lo1w = {1'b0, pd_u8[3:0], 1'b1} + {1'b0, inc_u8[3:0], 1'b1};
    assign u_hi0w = {pd_u8[7:4], 1'b0} + {inc_u8[7:4], 1'b0};
    assign u_hi1w = {pd_u8[7:4], 1'b1} + {inc_u8[7:4], 1'b1};
    wire [7:0] u_sum0 = {u_lo0w[5] ? u_hi1w[4:1] : u_hi0w[4:1], u_lo0w[4:1]};
    wire [7:0] u_sum1 = {u_lo1w[5] ? u_hi1w[4:1] : u_hi0w[4:1], u_lo1w[4:1]};

    wire       ovf_p0 = (!u_sum0[7]) && (u_sum0[6] || u_sum0[5]);
    wire       ovf_n0 = ( u_sum0[7]) && (!u_sum0[6] || !u_sum0[5]);
    wire [6:0] sat_u0 = ovf_p0 ? 7'b001_1111 : (ovf_n0 ? 7'b110_0000 : u_sum0[6:0]);
    wire       ovf_p1 = (!u_sum1[7]) && (u_sum1[6] || u_sum1[5]);
    wire       ovf_n1 = ( u_sum1[7]) && (!u_sum1[6] || !u_sum1[5]);
    wire [6:0] sat_u1 = ovf_p1 ? 7'b001_1111 : (ovf_n1 ? 7'b110_0000 : u_sum1[6:0]);

    wire p_ovf_pos = c16_out ? ovf_p1 : ovf_p0;
    wire p_ovf_neg = c16_out ? ovf_n1 : ovf_n0;
    wire [6:0] p_hi7 = c16_out ? sat_u1 : sat_u0;
    wire signed [22:0] pnext = $signed({p_hi7, p_lo16});
    wire ge1_u0 = (!sat_u0[6] && (|sat_u0[5:0])) || (sat_u0[6] && (sat_u0[5:0] != 6'h3f));
    wire ge1_u1 = (!sat_u1[6] && (|sat_u1[5:0])) || (sat_u1[6] && (sat_u1[5:0] != 6'h3f));
    wire debt_ge1_next = c16_out ? ge1_u1 : ge1_u0;
    wire debt_adv_next = !p_hi7[6];

    // 2-stage pipelined quality window evaluation (zero-adder exact 2's-complement identity:
    //   for x < 0, -x <= T  <=>  (~x) + 1 <= T  <=>  (~x) < T  ->  1 XOR level, +5 ns SS slack!)
    reg        q_eval_r;
    reg        q_neg_r;
    reg        q_tok_r;
    reg        q_age_ok_r;
    reg        q_debt_ok_r;
    reg [11:0] q_mag_r;
    reg [11:0] q_thr_r;

    reg signed [12:0] qsum_next;
    reg        [11:0] qtrans_next;
    wire       [11:0] qsum_mag_c = quality_sum[12] ? ~quality_sum[11:0] : quality_sum[11:0];
    wire              q_cmp_ok   = q_neg_r ? (q_mag_r < q_thr_r) : (q_mag_r <= q_thr_r);
    wire              q_pass_r   = q_tok_r && q_cmp_ok && q_debt_ok_r && q_age_ok_r;

    always @* begin
        // KI = 128 (1<<7): 11-bit +/-1 update & clamp on upper bits only
        f_hi_raw = {frequency_q[16], frequency_q[16:7]}
                 + (in_err_pos_r ? 11'sd1 : (in_err_neg_r ? -11'sd1 : 11'sd0));
        if (f_hi_raw >= FHI_LIMIT_11) begin
            fnext = FREQ_LIMIT_17;
            f_sat = 1'b1;
        end else if (f_hi_raw <= -FHI_LIMIT_11) begin
            fnext = -FREQ_LIMIT_17;
            f_sat = 1'b1;
        end else begin
            fnext = {f_hi_raw[9:0], frequency_q[6:0]};
            f_sat = 1'b0;
        end

        qsum_next   = quality_sum + {{6{in_vote_r[6]}}, in_vote_r};
        qtrans_next = quality_transitions + {6'd0, in_trans_r};
    end

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            frequency_q         <= 17'sd0;
            phase_debt_q        <= 23'sd0;
            debt_ge1_r          <= 1'b0;
            debt_adv_r          <= 1'b1;
            s2_enable           <= 1'b0;
            s2_delta_q          <= 18'sd0;
            inflight            <= 1'b0;
            issued_advance      <= 1'b0;
            locked              <= 1'b0;
            holdover            <= 1'b0;
            range_limited       <= 1'b0;
            age                 <= 9'd0;
            quality_ticks       <= 7'd0;
            quality_sum         <= 13'sd0;
            quality_transitions <= 12'd0;
            q_eval_r            <= 1'b0;
            q_neg_r             <= 1'b0;
            q_tok_r             <= 1'b0;
            q_age_ok_r          <= 1'b0;
            q_debt_ok_r         <= 1'b0;
            q_mag_r             <= 12'd0;
            q_thr_r             <= 12'd0;
            good_count          <= 3'd0;
            bad_count           <= 3'd0;
        end else begin
            // Exact original 0-extra-latency handshake with pi_step_commutator!
            if (step_valid && step_ready) begin
                inflight       <= 1'b1;
                issued_advance <= advance;
            end
            if (step_done) inflight <= 1'b0;

            // Stage 1 -> Stage 2 delta pipeline
            s2_enable  <= enable_r;
            s2_delta_q <= delta_s1_next;

            // Stage 2 phase_debt_q update + zero-latency debt_ge1_r/debt_adv_r shadow
            if (s2_enable || step_applied) begin
                phase_debt_q <= pnext;
                debt_ge1_r   <= debt_ge1_next;
                debt_adv_r   <= debt_adv_next;
                if (s2_enable && (p_ovf_pos || p_ovf_neg)) begin
                    range_limited <= 1'b1;
                end
            end

            if (enable_r) begin
                frequency_q <= fnext;
                if (f_sat) begin
                    range_limited <= 1'b1;
                end

                if (in_has_trans_r) begin
                    age      <= 9'd0;
                    holdover <= 1'b0;
                end else begin
                    if (age < NO_TRANS_9) age <= age + 9'd1;
                    holdover <= 1'b1;
                end
                if (age >= NO_TRANS_9) begin
                    locked     <= 1'b0;
                    good_count <= 3'd0;
                end

                // Stage 1 of quality evaluation: capture |quality_sum| and threshold on window end
                q_eval_r <= 1'b0;
                if (in_valid_r) begin
                    if (quality_ticks == QTICKS_LAST) begin
                        quality_ticks       <= 7'd0;
                        quality_sum         <= 13'sd0;
                        quality_transitions <= 12'd0;
                        q_eval_r            <= 1'b1;
                        q_neg_r             <= quality_sum[12];
                        q_mag_r             <= qsum_mag_c;
                        q_thr_r             <= {2'b00, quality_transitions[11:2]};
                        q_tok_r             <= (quality_transitions >= 12'd128);
                        q_age_ok_r          <= (age < NO_TRANS_9);
                        q_debt_ok_r         <= debt_in_2one && !range_limited;
                    end else begin
                        quality_ticks       <= quality_ticks + 7'd1;
                        quality_sum         <= qsum_next;
                        quality_transitions <= qtrans_next;
                    end
                end

                // Stage 2 of quality evaluation: unsigned 12-bit compare -> update good/bad/locked
                if (q_eval_r) begin
                    if (q_pass_r) begin
                        bad_count <= 3'd0;
                        if (good_count < GOOD_W_3) good_count <= good_count + 3'd1;
                        if (good_count >= GOOD_W_M1) locked <= 1'b1;
                    end else if (q_tok_r) begin
                        good_count <= 3'd0;
                        if (bad_count < BAD_W_3) bad_count <= bad_count + 3'd1;
                        if (bad_count >= BAD_W_M1) locked <= 1'b0;
                    end
                end

                // Registered range_limited clears locked on next cycle (breaks p_ovf -> locked path!)
                if (range_limited) locked <= 1'b0;
            end else begin
                locked              <= 1'b0;
                holdover            <= 1'b0;
                age                 <= 9'd0;
                q_eval_r            <= 1'b0;
                good_count          <= 3'd0;
                bad_count           <= 3'd0;
                quality_ticks       <= 7'd0;
                quality_sum         <= 13'sd0;
                quality_transitions <= 12'd0;
            end
        end
    end
endmodule
