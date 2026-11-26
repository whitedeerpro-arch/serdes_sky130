// Lean Type-II bang-bang CDR filter running on synchronous /2 (125 MHz / 8.0 ns) clock (v3.3).
// One control tick = 32 recovered UI (2x 16-UI bundles summed by bbpd_window_vote).
// Dead constant-0 Q7 LSBs [6:0] trimmed from frequency_q, phase_debt_q, and s2_delta_q (D-H4):
//   freq_q9             : 10-bit signed (Q9 PI steps / 32-UI tick, +/-384 => +/-732 ppm; frequency_q = {freq_q9, 7'd0})
//   debt_q9             : 16-bit signed (Q9 PI steps, [-16384, +16383] => +/-32 PI steps; phase_debt_q = {debt_q9, 7'd0})
//   s2_delta_q9         : 11-bit signed (Q9 stage-1->2 delta)
//   age                 :  9-bit unsigned (NO_TRANSITION_TICKS = 128 => 4096 UI)
//   quality_ticks       :  7-bit unsigned (QUALITY_TICKS = 64 => 2048 UI)
//   quality_transitions : 12-bit unsigned (max 64 * 32 = 2048)
//   quality_sum         : 13-bit signed   (range -2048 .. +2048)
//   good_count/bad_count:  3-bit unsigned (GOOD_WINDOWS = 4, BAD_WINDOWS = 4)
// Uses 3+3+3 carry-select 9-bit lower adder + 4+4 carry-select upper adder for huge
// 125 MHz cold-slow ss_n40C_1v60 + 5% OCV timing margin with minimal area.
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
    output wire signed [16:0] frequency_q,
    output wire signed [22:0] phase_debt_q,
    output reg               locked,
    output reg               holdover,
    output reg               range_limited
);
    // Fixed power-of-two gains in trimmed Q9 format (1 PI step = 512 = 1<<9):
    //   KP = 128 (1<<7, equiv. 16384 in Q16), KI = 1 (equiv. 128 in Q16), ONE = 512 (1<<9, equiv. 65536 in Q16)
    //   FREQ_LIMIT = +/-384 (equiv. +/-49152 in Q16 => +/-732 ppm)
    //   DEBT_LIMIT = [-16384, +16383] (+/-32 PI steps, exact 3-bit MSB clamp!)
    localparam signed [10:0] FHI_LIMIT_11   = 11'sd384;
    localparam signed [9:0]  FREQ_LIMIT_10  = 10'sd384;
    localparam [8:0]         NO_TRANS_9     = NO_TRANSITION_TICKS[8:0];
    localparam [6:0]         QTICKS_LAST    = QUALITY_TICKS[6:0] - 7'd1;
    localparam [2:0]         GOOD_W_3       = GOOD_WINDOWS[2:0];
    localparam [2:0]         GOOD_W_M1      = GOOD_WINDOWS[2:0] - 3'd1;
    localparam [2:0]         BAD_W_3        = BAD_WINDOWS[2:0];
    localparam [2:0]         BAD_W_M1       = BAD_WINDOWS[2:0] - 3'd1;

    // Local low-fanout reset leaves on 125 MHz ctrl_clk (eliminates 13-repeater daisy chain on rx_rst_n!)
    (* keep = "true" *) reg rst_a, rst_b, rst_c, rst_d;
    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            rst_a <= 1'b0; rst_b <= 1'b0; rst_c <= 1'b0; rst_d <= 1'b0;
        end else begin
            rst_a <= 1'b1; rst_b <= 1'b1; rst_c <= 1'b1; rst_d <= 1'b1;
        end
    end

    // Direct zero-logic capture on 125 MHz cdr_clk_div2 (eliminates 4.0 ns rx_word_clk->cdr_clk_div2 adder path!
    // Exact same cycle latency: sums computed inside the 8.0 ns cdr_clk_div2 domain.)
    reg              in_valid_r;
    reg signed [5:0] in_vote_a_r, in_vote_b_r;
    reg        [4:0] in_trans_a_r, in_trans_b_r;
    (* ASYNC_REG = "TRUE" *) reg enable_s0, enable_r;

    always @(posedge ctrl_clk or negedge rst_a) begin
        if (!rst_a) begin
            in_valid_r   <= 1'b0;
            in_vote_a_r  <= 6'sd0;
            in_vote_b_r  <= 6'sd0;
            in_trans_a_r <= 5'd0;
            in_trans_b_r <= 5'd0;
            enable_s0    <= 1'b0;
            enable_r     <= 1'b0;
        end else begin
            in_valid_r   <= vote_valid;
            in_vote_a_r  <= vote_sum_a;
            in_vote_b_r  <= vote_sum_b;
            in_trans_a_r <= trans_cnt_a;
            in_trans_b_r <= trans_cnt_b;
            enable_s0    <= enable;
            enable_r     <= enable_s0;
        end
    end

    wire signed [6:0] va7_r = {in_vote_a_r[5], in_vote_a_r};
    wire signed [6:0] vb7_r = {in_vote_b_r[5], in_vote_b_r};
    wire        [3:0] pv_lo4 = {1'b0, va7_r[2:0]} + {1'b0, vb7_r[2:0]};
    /* verilator lint_off UNUSED */
    (* keep = "true" *) wire [4:0] pv_hi0w;
    (* keep = "true" *) wire [4:0] pv_hi1w;
    /* verilator lint_on UNUSED */
    assign pv_hi0w = {va7_r[6:3], 1'b0} + {vb7_r[6:3], 1'b0};
    assign pv_hi1w = {va7_r[6:3], 1'b1} + {vb7_r[6:3], 1'b1};
    wire signed [6:0] in_vote_r      = $signed({pv_lo4[3] ? pv_hi1w[4:1] : pv_hi0w[4:1], pv_lo4[2:0]});
    wire              in_has_trans_r = in_valid_r && (|in_trans_a_r || |in_trans_b_r);

    // Evaluate sign/nonzero in the 125 MHz (8.0 ns) domain
    wire in_err_pos_r = in_has_trans_r && (!in_vote_r[6]) && (in_vote_r[5:0] != 6'd0);
    wire in_err_neg_r = in_has_trans_r && in_vote_r[6];

    reg signed [9:0]  freq_q9;
    reg signed [15:0] debt_q9;
    assign frequency_q  = $signed({freq_q9, 7'd0});
    assign phase_debt_q = $signed({debt_q9, 7'd0});

    reg               inflight, issued_advance;
    reg        [8:0]  age;
    reg        [6:0]  quality_ticks;
    reg        [11:0] quality_transitions;
    reg signed [12:0] quality_sum;
    reg        [2:0]  good_count, bad_count;

    // Exact MSB check for |debt_q9| < 2*ONE (1<<10 in Q9 == 1<<17 in Q16)
    wire debt_in_2one = (debt_q9[15:10] == 6'b000000) || (debt_q9[15:10] == 6'b111111);

    // Zero-latency shadow registers of (|debt_q9| >= ONE) and (!debt_q9[15])
    reg debt_ge1_r, debt_adv_r;
    assign step_valid = enable_r && !inflight && debt_ge1_r;
    assign advance    = debt_adv_r;

    reg signed [10:0] f_hi_raw;
    reg signed [9:0]  fnext;
    reg               f_sat;

    // Stage 1 -> Stage 2 clean 1-cycle pipeline for Q9 phase debt increment:
    //   Stage 1 (3 gate levels): s2_delta_q9 = freq_q9 + KP_term (only upper 4 bits [10:7] add!)
    //   Stage 2 (~5 gate levels): debt_q9 = sat16(debt_q9 + s2_delta_q9 + step_term)
    //     - Lower 9 bits [8:0]:  3+3+3 carry-select 2-operand adder (~4 gate levels!)
    //     - Upper 7 bits [15:9]: 4+4 carry-select with cin=0/1 in parallel
    reg               s2_enable;
    reg signed [10:0] s2_delta_q9;

    wire signed [3:0]  kp_hi4        = in_err_pos_r ? 4'sd1 : (in_err_neg_r ? -4'sd1 : 4'sd0);
    wire signed [3:0]  d_hi4_s1      = $signed({freq_q9[9], freq_q9[9:7]}) + kp_hi4;
    wire signed [10:0] delta_s1_next = enable_r ? $signed({d_hi4_s1, freq_q9[6:0]}) : 11'sd0;

    // Lower 9 bits [8:0]: 3+3+3 parallel carry-select -> c9_out in 4 gate levels!
    /* verilator lint_off UNUSED */
    (* keep = "true" *) wire [3:0] p_lo3;
    (* keep = "true" *) wire [4:0] p_m3_0w;
    (* keep = "true" *) wire [4:0] p_m3_1w;
    (* keep = "true" *) wire [4:0] p_h3_0w;
    (* keep = "true" *) wire [4:0] p_h3_1w;
    (* keep = "true" *) wire       c6_out;
    /* verilator lint_on UNUSED */
    assign p_lo3   = {1'b0, debt_q9[2:0]} + {1'b0, s2_delta_q9[2:0]};
    assign p_m3_0w = {1'b0, debt_q9[5:3], 1'b0} + {1'b0, s2_delta_q9[5:3], 1'b0};
    assign p_m3_1w = {1'b0, debt_q9[5:3], 1'b1} + {1'b0, s2_delta_q9[5:3], 1'b1};
    assign p_h3_0w = {1'b0, debt_q9[8:6], 1'b0} + {1'b0, s2_delta_q9[8:6], 1'b0};
    assign p_h3_1w = {1'b0, debt_q9[8:6], 1'b1} + {1'b0, s2_delta_q9[8:6], 1'b1};

    assign c6_out    = p_m3_0w[4] | (p_m3_1w[4] & p_lo3[3]);
    wire c9_if0      = p_h3_0w[4] | (p_h3_1w[4] & p_m3_0w[4]);
    wire c9_if1      = p_h3_0w[4] | (p_h3_1w[4] & p_m3_1w[4]);
    (* keep = "true" *) wire c9_lo0;
    (* keep = "true" *) wire c9_lo1;
    (* keep = "true" *) wire c9_hi0;
    (* keep = "true" *) wire c9_hi1;
    (* keep = "true" *) wire c9_ovf;
    assign c9_lo0    = p_lo3[3] ? c9_if1 : c9_if0;
    assign c9_lo1    = p_lo3[3] ? c9_if1 : c9_if0;
    assign c9_hi0    = p_lo3[3] ? c9_if1 : c9_if0;
    assign c9_hi1    = p_lo3[3] ? c9_if1 : c9_if0;
    assign c9_ovf    = p_lo3[3] ? c9_if1 : c9_if0;
    wire [2:0] p_m3  = p_lo3[3] ? p_m3_1w[3:1] : p_m3_0w[3:1];
    wire [2:0] p_h3  = c6_out   ? p_h3_1w[3:1] : p_h3_0w[3:1];
    wire [8:0] p_lo9 = {p_h3, p_m3, p_lo3[2:0]};

    // Upper 8 bits (sign-extended [15:9]) = pd_u8 + k, where k in [-3..+3]:
    // Fast 4+4 literal sums for all 7 offsets -> pre-saturated sat/ge1/ovf in parallel.
    wire [7:0] pd_u8 = {debt_q9[15], debt_q9[15:9]};
    wire [3:0] pd_hi_m1 = pd_u8[7:4] - 4'd1;
    wire [3:0] pd_hi_p0 = pd_u8[7:4];
    wire [3:0] pd_hi_p1 = pd_u8[7:4] + 4'd1;

    wire [4:0] lo_m3 = {1'b0, pd_u8[3:0]} + 5'h0D;
    wire [4:0] lo_m2 = {1'b0, pd_u8[3:0]} + 5'h0E;
    wire [4:0] lo_m1 = {1'b0, pd_u8[3:0]} + 5'h0F;
    wire [4:0] lo_p1 = {1'b0, pd_u8[3:0]} + 5'h01;
    wire [4:0] lo_p2 = {1'b0, pd_u8[3:0]} + 5'h02;
    wire [4:0] lo_p3 = {1'b0, pd_u8[3:0]} + 5'h03;

    wire [7:0] sum_m3 = {lo_m3[4] ? pd_hi_p0 : pd_hi_m1, lo_m3[3:0]};
    wire [7:0] sum_m2 = {lo_m2[4] ? pd_hi_p0 : pd_hi_m1, lo_m2[3:0]};
    wire [7:0] sum_m1 = {lo_m1[4] ? pd_hi_p0 : pd_hi_m1, lo_m1[3:0]};
    wire [7:0] sum_p0 = pd_u8;
    wire [7:0] sum_p1 = {lo_p1[4] ? pd_hi_p1 : pd_hi_p0, lo_p1[3:0]};
    wire [7:0] sum_p2 = {lo_p2[4] ? pd_hi_p1 : pd_hi_p0, lo_p2[3:0]};
    wire [7:0] sum_p3 = {lo_p3[4] ? pd_hi_p1 : pd_hi_p0, lo_p3[3:0]};

    // Direct zero-adder overflow detection from pd_u8 in [-32..+31] (2 levels instead of 6!):
    wire pd_pos_hi = !pd_u8[7] && !pd_u8[6] && !pd_u8[5] && &pd_u8[4:2]; // pd_u8 in {28,29,30,31}
    wire pd_neg_hi =  pd_u8[7] &&  pd_u8[6] &&  pd_u8[5] && (pd_u8[4:2] == 3'b000); // pd_u8 in {-32,-31,-30,-29}
    wire ovp_p1 = pd_pos_hi &&  pd_u8[1] &&  pd_u8[0];                  // pd_u8 == 31
    wire ovp_p2 = pd_pos_hi &&  pd_u8[1];                               // pd_u8 >= 30
    wire ovp_p3 = pd_pos_hi && (pd_u8[1] ||  pd_u8[0]);                 // pd_u8 >= 29
    wire ovn_m1 = pd_neg_hi && !pd_u8[1] && !pd_u8[0];                  // pd_u8 == -32
    wire ovn_m2 = pd_neg_hi && !pd_u8[1];                               // pd_u8 <= -31
    wire ovn_m3 = pd_neg_hi && !(pd_u8[1] && pd_u8[0]);                 // pd_u8 <= -30

    // Direct zero-adder |debt| >= ONE detection: u == 0 or u == -1 iff pd_u8 == -k or -k-1 (2 levels!)
    wire pd_near0_p = (pd_u8[7:3] == 5'b00000); //  0..+7
    wire pd_near0_n = (pd_u8[7:3] == 5'b11111); // -8..-1
    wire ge1_m3 = !(pd_near0_p && (pd_u8[2:0] == 3'd3 || pd_u8[2:0] == 3'd2));
    wire ge1_m2 = !(pd_near0_p && (pd_u8[2:0] == 3'd2 || pd_u8[2:0] == 3'd1));
    wire ge1_m1 = !(pd_near0_p && (pd_u8[2:0] == 3'd1 || pd_u8[2:0] == 3'd0));
    wire ge1_p0 = !((pd_near0_p && pd_u8[2:0] == 3'd0) || (pd_near0_n && pd_u8[2:0] == 3'd7));
    wire ge1_p1 = !(pd_near0_n && (pd_u8[2:0] == 3'd7 || pd_u8[2:0] == 3'd6));
    wire ge1_p2 = !(pd_near0_n && (pd_u8[2:0] == 3'd6 || pd_u8[2:0] == 3'd5));
    wire ge1_p3 = !(pd_near0_n && (pd_u8[2:0] == 3'd5 || pd_u8[2:0] == 3'd4));

    wire [9:0] pk_m3 = {1'b0,   ovn_m3, ge1_m3, ovn_m3 ? 7'b110_0000 : sum_m3[6:0]};
    wire [9:0] pk_m2 = {1'b0,   ovn_m2, ge1_m2, ovn_m2 ? 7'b110_0000 : sum_m2[6:0]};
    wire [9:0] pk_m1 = {1'b0,   ovn_m1, ge1_m1, ovn_m1 ? 7'b110_0000 : sum_m1[6:0]};
    wire [9:0] pk_p0 = {1'b0,   1'b0,   ge1_p0, sum_p0[6:0]};
    wire [9:0] pk_p1 = {ovp_p1, 1'b0,   ge1_p1, ovp_p1 ? 7'b001_1111 : sum_p1[6:0]};
    wire [9:0] pk_p2 = {ovp_p2, 1'b0,   ge1_p2, ovp_p2 ? 7'b001_1111 : sum_p2[6:0]};
    wire [9:0] pk_p3 = {ovp_p3, 1'b0,   ge1_p3, ovp_p3 ? 7'b001_1111 : sum_p3[6:0]};

    // Direct 3-bit signed offset k0 = d_s3 + step_k (range -3..+2, computed in 2 gates in parallel
    // with lo_m3..lo_p3!), followed by a single mux4_2+mux2_2 stage for pk_c0/pk_c1 and ONE final
    // mux2 on c9 (cuts debt_q9 -> debt_q9 from 11 gates down to 6 gates!).
    wire signed [2:0] d_ext3 = {s2_delta_q9[10], s2_delta_q9[10], s2_delta_q9[9]};
    wire signed [2:0] step_k = step_applied ? (issued_advance ? -3'sd1 : 3'sd1) : 3'sd0;
    wire [2:0]        k0     = d_ext3 + step_k;

    reg [9:0] pk_c0, pk_c1;
    always @* begin
        case (k0)
            3'b101:  begin pk_c0 = pk_m3; pk_c1 = pk_m2; end // -3
            3'b110:  begin pk_c0 = pk_m2; pk_c1 = pk_m1; end // -2
            3'b111:  begin pk_c0 = pk_m1; pk_c1 = pk_p0; end // -1
            3'b000:  begin pk_c0 = pk_p0; pk_c1 = pk_p1; end //  0
            3'b001:  begin pk_c0 = pk_p1; pk_c1 = pk_p2; end // +1
            default: begin pk_c0 = pk_p2; pk_c1 = pk_p3; end // +2
        endcase
    end

    // Pre-saturate p_lo9 for c9==0 and c9==1 IN PARALLEL with c9 -> ONLY ONE final mux2 after c9!
    wire [8:0] p_lo9_c0 = pk_c0[9] ? 9'h1FF : (pk_c0[8] ? 9'h000 : p_lo9);
    wire [8:0] p_lo9_c1 = pk_c1[9] ? 9'h1FF : (pk_c1[8] ? 9'h000 : p_lo9);
    wire [8:0] p_lo9_sat = {
        c9_lo1 ? p_lo9_c1[8:5] : p_lo9_c0[8:5],
        c9_lo0 ? p_lo9_c1[4:0] : p_lo9_c0[4:0]
    };

    wire [6:0] p_hi7         = {
        c9_hi1 ? pk_c1[6:4] : pk_c0[6:4],
        c9_hi0 ? pk_c1[3:0] : pk_c0[3:0]
    };
    wire       debt_ge1_next = c9_ovf ? pk_c1[7] : pk_c0[7];
    wire       p_ovf_any     = c9_ovf ? (pk_c1[9] || pk_c1[8]) : (pk_c0[9] || pk_c0[8]);
    wire signed [15:0] pnext = $signed({p_hi7, p_lo9_sat});
    wire       debt_adv_next = !p_hi7[6];

    // 1-cycle quality-only input pipeline (q_valid_r, q_vote_sum_r, q_trans_sum_r):
    //   Zero impact on CDR phase/frequency tracking loop (only shifts 64-tick quality window by 1 tick),
    //   cuts quality accumulator from 12 levels -> 5 levels (+3.0 ns slack) and removes CSA gate bloat!
    wire [5:0] in_trans_sum_c = {1'b0, in_trans_a_r} + {1'b0, in_trans_b_r};
    reg               q_valid_r;
    reg signed [6:0]  q_vote_sum_r;
    reg        [5:0]  q_trans_sum_r;

    // 2-stage pipelined quality window evaluation
    reg        q_eval_r;
    reg        q_tok_r;
    reg        q_age_ok_r;
    reg        q_debt_ok_r;
    reg [12:0] q_sum_r;
    reg [11:0] q_thr_r;

    // Fast 4+4+5 carry-select 2-operand adder for 13-bit qsum_next = quality_sum + q_vote_sum_r
    wire [12:0] qv_ext = {{6{q_vote_sum_r[6]}}, q_vote_sum_r};
    wire [4:0]  qs_n0    = {1'b0, quality_sum[3:0]} + {1'b0, qv_ext[3:0]};
    wire [4:0]  qs_n1_0  = {1'b0, quality_sum[7:4]} + {1'b0, qv_ext[7:4]};
    wire [4:0]  qs_n1_1  = {1'b0, quality_sum[7:4]} + {1'b0, qv_ext[7:4]} + 5'd1;
    wire        qs_c8    = qs_n0[4] ? qs_n1_1[4] : qs_n1_0[4];
    wire [4:0]  qs_n2_0  = quality_sum[12:8] + qv_ext[12:8];
    wire [4:0]  qs_n2_1  = quality_sum[12:8] + qv_ext[12:8] + 5'd1;
    wire signed [12:0] qsum_next = $signed({
        qs_c8    ? qs_n2_1 : qs_n2_0,
        qs_n0[4] ? qs_n1_1[3:0] : qs_n1_0[3:0],
        qs_n0[3:0]
    });

    // Fast 4+4+4 carry-select 2-operand adder for 12-bit qtrans_next = quality_transitions + q_trans_sum_r
    wire [4:0] qt_n0   = {1'b0, quality_transitions[3:0]} + {1'b0, q_trans_sum_r[3:0]};
    wire [4:0] qt_n1_0 = {1'b0, quality_transitions[7:4]} + {3'd0, q_trans_sum_r[5:4]};
    wire [4:0] qt_n1_1 = {1'b0, quality_transitions[7:4]} + {3'd0, q_trans_sum_r[5:4]} + 5'd1;
    wire       qt_c8   = qt_n0[4] ? qt_n1_1[4] : qt_n1_0[4];
    wire [3:0] qt_hi4  = qt_c8 ? (quality_transitions[11:8] + 4'd1) : quality_transitions[11:8];
    wire [11:0] qtrans_next = {qt_hi4, qt_n0[4] ? qt_n1_1[3:0] : qt_n1_0[3:0], qt_n0[3:0]};

    // Stage 2a: parallel 4+4+4 nibble compare -> registered q_eval_s2_r/q_pass_s2_r/q_tok_s2_r
    // Cuts quality lock comparator path from 11 gates -> 5 gates (zero impact on phase/freq loop!)
    wire [11:0] q_mag_s2 = q_sum_r[12] ? ~q_sum_r[11:0] : q_sum_r[11:0];
    wire        q_lt_hi  = (q_mag_s2[11:8] < q_thr_r[11:8]);
    wire        q_eq_hi  = (q_mag_s2[11:8] == q_thr_r[11:8]);
    wire        q_lt_md  = (q_mag_s2[7:4]  < q_thr_r[7:4]);
    wire        q_eq_md  = (q_mag_s2[7:4]  == q_thr_r[7:4]);
    wire        q_ok_lo  = q_sum_r[12] ? (q_mag_s2[3:0] < q_thr_r[3:0]) : (q_mag_s2[3:0] <= q_thr_r[3:0]);
    wire        q_cmp_ok = q_lt_hi || (q_eq_hi && (q_lt_md || (q_eq_md && q_ok_lo)));
    wire        q_pass_r = q_tok_r && q_cmp_ok && q_debt_ok_r && q_age_ok_r;
    reg         q_eval_s2_r, q_pass_s2_r, q_tok_s2_r;

    // Fast parallel +/-1 frequency update & exact +/-384 clamp (5 levels instead of 15-level ripple+cmp!)
    // freq_q9 is always in [-384, +384], so +/-1 saturates iff already at +/-384!
    wire [5:0] fp_lo5 = {1'b0, freq_q9[4:0]} + 6'd1;
    wire [4:0] fp_hi5 = fp_lo5[5] ? (freq_q9[9:5] + 5'd1) : freq_q9[9:5];
    wire signed [9:0] freq_p1 = $signed({fp_hi5, fp_lo5[4:0]});

    wire [5:0] fm_lo5 = {1'b0, freq_q9[4:0]} + 6'h1F; // -1 mod 32, borrow iff freq_q9[4:0] == 0
    wire       fm_brw = (freq_q9[4:0] == 5'd0);
    wire [4:0] fm_hi5 = fm_brw ? (freq_q9[9:5] - 5'd1) : freq_q9[9:5];
    wire signed [9:0] freq_m1 = $signed({fm_hi5, fm_lo5[4:0]});

    wire at_pos_lim = (freq_q9 == FREQ_LIMIT_10);
    wire at_neg_lim = (freq_q9 == -FREQ_LIMIT_10);
    (* keep = "true" *) wire do_f_inc_lo;
    (* keep = "true" *) wire do_f_inc_hi;
    (* keep = "true" *) wire do_f_dec_lo;
    (* keep = "true" *) wire do_f_dec_hi;
    assign do_f_inc_lo = in_err_pos_r && !at_pos_lim;
    assign do_f_inc_hi = in_err_pos_r && !at_pos_lim;
    assign do_f_dec_lo = in_err_neg_r && !at_neg_lim;
    assign do_f_dec_hi = in_err_neg_r && !at_neg_lim;

    always @* begin
        f_sat = (in_err_pos_r && at_pos_lim) || (in_err_neg_r && at_neg_lim);
        fnext = $signed({
            do_f_inc_hi ? freq_p1[9:5] : (do_f_dec_hi ? freq_m1[9:5] : freq_q9[9:5]),
            do_f_inc_lo ? freq_p1[4:0] : (do_f_dec_lo ? freq_m1[4:0] : freq_q9[4:0])
        });
    end

    // Block B (rst_b: 41 FFs — freq/debt/handshake datapath)
    always @(posedge ctrl_clk or negedge rst_b) begin
        if (!rst_b) begin
            freq_q9        <= 10'sd0;
            debt_q9        <= 16'sd0;
            debt_ge1_r     <= 1'b0;
            debt_adv_r     <= 1'b1;
            s2_enable      <= 1'b0;
            s2_delta_q9    <= 11'sd0;
            inflight       <= 1'b0;
            issued_advance <= 1'b0;
            range_limited  <= 1'b0;
        end else begin
            if (step_valid && step_ready) begin
                inflight       <= 1'b1;
                issued_advance <= advance;
            end
            if (step_done) inflight <= 1'b0;

            s2_enable   <= enable_r;
            s2_delta_q9 <= delta_s1_next;

            if (enable_r && (s2_enable || step_applied)) begin
                debt_q9    <= pnext;
                debt_ge1_r <= debt_ge1_next;
                debt_adv_r <= debt_adv_next;
                if (s2_enable && p_ovf_any) begin
                    range_limited <= 1'b1;
                end
            end

            if (enable_r) begin
                freq_q9 <= fnext;
                if (f_sat) range_limited <= 1'b1;
            end else begin
                freq_q9       <= 10'sd0;
                debt_q9       <= 16'sd0;
                debt_ge1_r    <= 1'b0;
                debt_adv_r    <= 1'b1;
                s2_enable     <= 1'b0;
                s2_delta_q9   <= 11'sd0;
                range_limited <= 1'b0;
            end
        end
    end

    // Block C (rst_c: quality window accumulators, 1-cycle input pipe & age/holdover)
    always @(posedge ctrl_clk or negedge rst_c) begin
        if (!rst_c) begin
            q_valid_r           <= 1'b0;
            q_vote_sum_r        <= 7'sd0;
            q_trans_sum_r       <= 6'd0;
            holdover            <= 1'b0;
            age                 <= 9'd0;
            quality_ticks       <= 7'd0;
            quality_sum         <= 13'sd0;
            quality_transitions <= 12'd0;
        end else if (enable_r) begin
            q_valid_r     <= in_valid_r;
            q_vote_sum_r  <= in_vote_r;
            q_trans_sum_r <= in_trans_sum_c;
            if (in_has_trans_r) begin
                age      <= 9'd0;
                holdover <= 1'b0;
            end else begin
                if (age < NO_TRANS_9) age <= age + 9'd1;
                holdover <= 1'b1;
            end
            if (q_valid_r) begin
                if (quality_ticks == QTICKS_LAST) begin
                    quality_ticks       <= 7'd0;
                    quality_sum         <= 13'sd0;
                    quality_transitions <= 12'd0;
                end else begin
                    quality_ticks       <= quality_ticks + 7'd1;
                    quality_sum         <= qsum_next;
                    quality_transitions <= qtrans_next;
                end
            end
        end else begin
            q_valid_r           <= 1'b0;
            q_vote_sum_r        <= 7'sd0;
            q_trans_sum_r       <= 6'd0;
            holdover            <= 1'b0;
            age                 <= 9'd0;
            quality_ticks       <= 7'd0;
            quality_sum         <= 13'sd0;
            quality_transitions <= 12'd0;
        end
    end

    // Block D (rst_d: quality evaluation stage 2/3 & lock state)
    always @(posedge ctrl_clk or negedge rst_d) begin
        if (!rst_d) begin
            locked      <= 1'b0;
            q_eval_r    <= 1'b0;
            q_eval_s2_r <= 1'b0;
            q_pass_s2_r <= 1'b0;
            q_tok_s2_r  <= 1'b0;
            q_tok_r     <= 1'b0;
            q_age_ok_r  <= 1'b0;
            q_debt_ok_r <= 1'b0;
            q_sum_r     <= 13'd0;
            q_thr_r     <= 12'd0;
            good_count  <= 3'd0;
            bad_count   <= 3'd0;
        end else if (enable_r) begin
            if (age >= NO_TRANS_9) begin
                locked     <= 1'b0;
                good_count <= 3'd0;
            end
            q_eval_r    <= 1'b0;
            q_eval_s2_r <= q_eval_r;
            q_pass_s2_r <= q_pass_r;
            q_tok_s2_r  <= q_tok_r;
            if (q_valid_r && (quality_ticks == QTICKS_LAST)) begin
                q_eval_r    <= 1'b1;
                q_sum_r     <= qsum_next;
                q_thr_r     <= {2'b00, qtrans_next[11:2]};
                q_tok_r     <= (qtrans_next >= 12'd128);
                q_age_ok_r  <= (age < NO_TRANS_9);
                q_debt_ok_r <= debt_in_2one && !range_limited;
            end
            if (q_eval_s2_r) begin
                if (q_pass_s2_r) begin
                    bad_count <= 3'd0;
                    if (good_count < GOOD_W_3) good_count <= good_count + 3'd1;
                    if (good_count >= GOOD_W_M1) locked <= 1'b1;
                end else if (q_tok_s2_r) begin
                    good_count <= 3'd0;
                    if (bad_count < BAD_W_3) bad_count <= bad_count + 3'd1;
                    if (bad_count >= BAD_W_M1) locked <= 1'b0;
                end
            end
            if (range_limited) locked <= 1'b0;
        end else begin
            locked      <= 1'b0;
            q_eval_r    <= 1'b0;
            q_eval_s2_r <= 1'b0;
            q_pass_s2_r <= 1'b0;
            q_tok_s2_r  <= 1'b0;
            good_count  <= 3'd0;
            bad_count   <= 3'd0;
        end
    end
endmodule
