// Lean Type-II bang-bang CDR filter running natively on rx_clk_div2 (125 MHz @ 4G / 156.25 MHz @ 5G, 6.40 ns!).
// One control tick = 32 recovered UI (directly from bbpd_window_vote32 with REGISTERED err_pos/err_neg/has_trans!).
// Dead constant-0 Q7 LSBs [6:0] trimmed from frequency_q, phase_debt_q, and s2_delta_q (D-H4):
//   freq_q9             : 10-bit signed (Q9 PI steps / 32-UI tick, +/-384 => +/-732 ppm; frequency_q = {freq_q9, 7'd0})
//   debt_q9             : 16-bit signed (Q9 PI steps, [-16384, +16383] => +/-32 PI steps; phase_debt_q = {debt_q9, 7'd0})
//   s2_delta_q9         : 11-bit signed (Q9 stage-1->2 delta)
// Every single datapath stage is <= 6 gate levels (~4.0 ns << 6.40 ns at 5G ss_n40C_1v60 + 5% OCV!).
module cdr_phase_frequency_v4 #(
    parameter integer QUALITY_TICKS       = 64,
    parameter integer GOOD_WINDOWS        = 4,
    parameter integer BAD_WINDOWS         = 4,
    parameter integer NO_TRANSITION_TICKS = 128
) (
    input  wire              ctrl_clk,
    input  wire              rst_n,
    input  wire              rst_sync_in,
    input  wire              enable,
    input  wire              vote_valid,
    input  wire              has_trans,
    input  wire              err_pos,
    input  wire              err_neg,
    input  wire signed [6:0] vote_sum,
    input  wire        [5:0] trans_cnt,
    /* verilator lint_off UNUSED */
    input  wire              step_ready,
    input  wire              step_applied,
    /* verilator lint_on UNUSED */
    input  wire              step_done,
    output wire              step_valid,
    output wire              advance,
    output wire signed [16:0] frequency_q,
    output wire signed [22:0] phase_debt_q,
    output reg               locked,
    output reg               holdover,
    output reg               range_limited
);
    localparam signed [9:0] FREQ_LIMIT_10 = 10'sd384;
    localparam [8:0]        NO_TRANS_9    = NO_TRANSITION_TICKS[8:0];
    localparam [6:0]        QTICKS_LAST   = QUALITY_TICKS[6:0] - 7'd1;
    localparam [2:0]        GOOD_W_3      = GOOD_WINDOWS[2:0];
    localparam [2:0]        GOOD_W_M1     = GOOD_WINDOWS[2:0] - 3'd1;
    localparam [2:0]        BAD_W_3       = BAD_WINDOWS[2:0];
    localparam [2:0]        BAD_W_M1      = BAD_WINDOWS[2:0] - 3'd1;

    // Local low-fanout 3rd-stage reset leaves on rx_clk_div2 (async-assert on rst_n, sync-deassert on rst_sync_in!)
    (* keep = "true" *) reg rst_a, rst_b, rst_c, rst_d;
    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            rst_a <= 1'b0; rst_b <= 1'b0; rst_c <= 1'b0; rst_d <= 1'b0;
        end else begin
            rst_a <= rst_sync_in; rst_b <= rst_sync_in; rst_c <= rst_sync_in; rst_d <= rst_sync_in;
        end
    end

    // Synchronize async enable onto rx_clk_div2 (strict D-C1 fanout=1 on enable_s0!)
    // + 5 low-fanout 3rd-stage local copies so enable_r NEVER fans out to 47 FFs / 3 repeaters!
    (* ASYNC_REG = "TRUE", keep = "true" *) reg enable_s0, enable_r;
    (* keep = "true" *) reg en_b, en_sv, en_dlo, en_dhi, en_c, en_d;
    always @(posedge ctrl_clk or negedge rst_a) begin
        if (!rst_a) begin
            enable_s0 <= 1'b0;
            enable_r  <= 1'b0;
            en_b      <= 1'b0;
            en_sv     <= 1'b0;
            en_dlo    <= 1'b0;
            en_dhi    <= 1'b0;
            en_c      <= 1'b0;
            en_d      <= 1'b0;
        end else begin
            enable_s0 <= enable;
            enable_r  <= enable_s0;
            en_b      <= enable_r;
            en_sv     <= enable_r;
            en_dlo    <= enable_r;
            en_dhi    <= enable_r;
            en_c      <= enable_r;
            en_d      <= enable_r;
        end
    end

    reg signed [9:0]  freq_q9;
    // 2-stage carry-pipelined 16-bit phase debt accumulator:
    //   debt_lo9 [8:0] (5-gate 9-bit add) -> debt_c9_r -> debt_hi7 [15:9] (5-gate 7-bit add + direct step_issue +/-1!)
    //   Zero extra delay on step_issue refund (exact 21 ps closed-loop CDR!), cuts Stage 2 from 11 gates -> 5 gates!
    reg        [8:0]  debt_lo9;
    reg signed [6:0]  debt_hi7;
    reg        [1:0]  s3_k_sel_r; // 0:-1, 1:0, 2:+1, 3:+2 (encodes s3_en_r=0 as 1:0!)
    reg               s3_en_r;
    reg               debt_ge1_r, debt_adv_r;
    wire signed [15:0] debt_q9 = $signed({debt_hi7, debt_lo9});
    assign frequency_q  = $signed({freq_q9, 7'd0});
    assign phase_debt_q = $signed({debt_q9, 7'd0});

    reg               inflight;
    reg        [8:0]  age;
    reg        [6:0]  quality_ticks;
    reg        [5:0]  qt_lo6, qt_hi6;
    /* verilator lint_off UNUSED */
    reg        [5:0]  qt_lo6_snap;
    /* verilator lint_on UNUSED */
    reg               qt_c6;
    reg        [5:0]  qs_lo6, qs_lo6_snap;
    reg        [6:0]  qs_hi7;
    reg               qs_c6, qs_sgn;
    reg               q_v_d1, q_last_d1, q_age_ok_s0, q_debt_ok_s0;
    reg        [2:0]  good_count, bad_count;

    // |debt_q9| < 4*ONE (31.25 ps = 0.125 UI): prevents false lock-drop on +/-300 ppm bang-bang peaks
    wire debt_in_2one = (debt_hi7[6:2] == 5'b00000) || (debt_hi7[6:2] == 5'b11111);

    // Pure registered step request -> 1 gate into pi_step_commutator (dedicated 1-fanout en_sv!)
    // Exact invariant: whenever inflight==0, commutator is ALWAYS in IDLE (step_ready==1),
    // so step_issue == step_valid with ZERO cross-chip wire from commutator.state into filter!
    assign step_valid = en_sv && !inflight && debt_ge1_r;
    assign advance    = debt_adv_r;

    wire step_issue = step_valid;

    // Stage 1 (5 gates, 0 extra loop latency!): 2+2+3 carry-select on [6:0] + parallel c7_out=0/1 mux on [8:7]+k_sel!
    wire [2:0] d7_b0  = {1'b0, debt_lo9[1:0]} + {1'b0, freq_q9[1:0]};
    wire [2:0] d7_b10 = {1'b0, debt_lo9[3:2]} + {1'b0, freq_q9[3:2]};
    wire [2:0] d7_b11 = {1'b0, debt_lo9[3:2]} + {1'b0, freq_q9[3:2]} + 3'd1;
    wire [3:0] d7_b20 = {1'b0, debt_lo9[6:4]} + {1'b0, freq_q9[6:4]};
    wire [3:0] d7_b21 = {1'b0, debt_lo9[6:4]} + {1'b0, freq_q9[6:4]} + 4'd1;
    wire       c4_out = d7_b0[2] ? d7_b11[2] : d7_b10[2];
    wire [6:0] p_lo7  = {c4_out ? d7_b21[2:0] : d7_b20[2:0], d7_b0[2] ? d7_b11[1:0] : d7_b10[1:0], d7_b0[1:0]};
    wire       c7_out = c4_out ? d7_b21[3] : d7_b20[3];

    // Precompute BOTH c7_out=0 and c7_out=1 results IN PARALLEL with c7_out (c7_out drives ONLY 1 final mux2!)
    // b4_0 = freq_q9[9:7] (signed -3..+3) + debt_lo9[8:7] (0..3) + 4 (offset +4 shifts [-4..+8] -> [0..+12], 4-bit unsigned!)
    wire [3:0] b4_off = {freq_q9[9], freq_q9[9:7]} + {2'b00, debt_lo9[8:7]} + 4'd4;
    wire [3:0] t4_m1  = b4_off - 4'd1;
    wire [3:0] t4_0   = b4_off;
    wire [3:0] t4_p1  = b4_off + 4'd1;
    wire [3:0] t4_p2  = b4_off + 4'd2;
    // Notice t4_x = (sum + 4): bits [1:0] are exact p_lo9[8:7], and bits [3:2] are ALREADY (k + 1) in {0,1,2,3} (ZERO +1 adder!)
    wire [3:0] t4_c0  = err_neg ? t4_m1 : (err_pos ? t4_p1 : t4_0);
    wire [3:0] t4_c1  = err_neg ? t4_0  : (err_pos ? t4_p2 : t4_p1);
    wire [3:0] t4_sel = c7_out  ? t4_c1 : t4_c0;
    wire [8:0] p_lo9      = {t4_sel[1:0], p_lo7};
    wire [1:0] s3_k_sel_n = t4_sel[3:2];

    // Stage 2 (5 gates max!): 3 parallel 3+4 carry-select adds for no-step/advance/retard (step_issue ONLY at final mux2!)
    wire debt_ovp_r = (!debt_hi7[6] &&  debt_hi7[5]);
    wire debt_ovn_r = ( debt_hi7[6] && !debt_hi7[5]);
    wire do_hi_upd  = s3_en_r || step_issue;
    wire p_ovf_any  = debt_ovp_r || debt_ovn_r;

    wire [3:0] hi4_0  = debt_hi7[6:3];
    wire [3:0] hi4_m1 = debt_hi7[6:3] - 4'd1;
    wire [3:0] hi4_p1 = debt_hi7[6:3] + 4'd1;

    wire [2:0] k_no_3  = (s3_k_sel_r == 2'd0) ? 3'd7 : (s3_k_sel_r == 2'd1) ? 3'd0 : (s3_k_sel_r == 2'd2) ? 3'd1 : 3'd2;
    wire       k_no_n  = (s3_k_sel_r == 2'd0);
    wire [2:0] k_adv_3 = (s3_k_sel_r == 2'd0) ? 3'd6 : (s3_k_sel_r == 2'd1) ? 3'd7 : (s3_k_sel_r == 2'd2) ? 3'd0 : 3'd1;
    wire       k_adv_n = !s3_k_sel_r[1]; // 0 (-2) or 1 (-1)
    wire [2:0] k_ret_3 = {1'b0, s3_k_sel_r}; // 0, 1, 2, 3 (always non-negative!)

    wire [3:0] lo3_no  = {1'b0, debt_hi7[2:0]} + {1'b0, k_no_3};
    wire [3:0] lo3_adv = {1'b0, debt_hi7[2:0]} + {1'b0, k_adv_3};
    wire [3:0] lo3_ret = {1'b0, debt_hi7[2:0]} + {1'b0, k_ret_3};

    wire signed [6:0] hi7_no  = $signed({k_no_n  ? (lo3_no[3]  ? hi4_0 : hi4_m1) : (lo3_no[3]  ? hi4_p1 : hi4_0), lo3_no[2:0]});
    wire signed [6:0] hi7_adv = $signed({k_adv_n ? (lo3_adv[3] ? hi4_0 : hi4_m1) : (lo3_adv[3] ? hi4_p1 : hi4_0), lo3_adv[2:0]});
    wire signed [6:0] hi7_ret = $signed({                                           lo3_ret[3] ? hi4_p1 : hi4_0,  lo3_ret[2:0]});

    wire signed [6:0] hi7_step = advance ? hi7_adv : hi7_ret;
    wire signed [6:0] hi7_sel  = step_issue ? hi7_step : hi7_no;

    wire signed [6:0] debt_hi7_next = !en_dhi    ? 7'sd0 :
                                      debt_ovp_r ? 7'sb001_1111 :
                                      debt_ovn_r ? 7'sb110_0000 : hi7_sel;

    // Direct 3-gate constant compares for ge1 & adv (step_issue drives ONLY 1 final mux2!)
    wire eq_p2 = (debt_hi7 ==  7'sd2);
    wire eq_p1 = (debt_hi7 ==  7'sd1);
    wire eq_0  = (debt_hi7 ==  7'sd0);
    wire eq_m1 = (debt_hi7 == -7'sd1);
    wire eq_m2 = (debt_hi7 == -7'sd2);
    wire eq_m3 = (debt_hi7 == -7'sd3);
    wire eq_m4 = (debt_hi7 == -7'sd4);

    wire ge1_m2 = !(eq_p2 | eq_p1);
    wire ge1_m1 = !(eq_p1 | eq_0);
    wire ge1_0  = !(eq_0  | eq_m1);
    wire ge1_p1 = !(eq_m1 | eq_m2);
    wire ge1_p2 = !(eq_m2 | eq_m3);
    wire ge1_p3 = !(eq_m3 | eq_m4);

    wire pos0   = !debt_hi7[6];
    wire adv_m2 = pos0 & !eq_0 & !eq_p1;
    wire adv_m1 = pos0 & !eq_0;
    wire adv_0  = pos0;
    wire adv_p1 = pos0 | eq_m1;
    wire adv_p2 = pos0 | eq_m1 | eq_m2;
    wire adv_p3 = pos0 | eq_m1 | eq_m2 | eq_m3;

    wire ge1_no  = (s3_k_sel_r == 2'd0) ? ge1_m1 : (s3_k_sel_r == 2'd1) ? ge1_0  : (s3_k_sel_r == 2'd2) ? ge1_p1 : ge1_p2;
    wire ge1_adv = (s3_k_sel_r == 2'd0) ? ge1_m2 : (s3_k_sel_r == 2'd1) ? ge1_m1 : (s3_k_sel_r == 2'd2) ? ge1_0  : ge1_p1;
    wire ge1_ret = (s3_k_sel_r == 2'd0) ? ge1_0  : (s3_k_sel_r == 2'd1) ? ge1_p1 : (s3_k_sel_r == 2'd2) ? ge1_p2 : ge1_p3;

    wire adv_no  = (s3_k_sel_r == 2'd0) ? adv_m1 : (s3_k_sel_r == 2'd1) ? adv_0  : (s3_k_sel_r == 2'd2) ? adv_p1 : adv_p2;
    wire adv_adv = (s3_k_sel_r == 2'd0) ? adv_m2 : (s3_k_sel_r == 2'd1) ? adv_m1 : (s3_k_sel_r == 2'd2) ? adv_0  : adv_p1;
    wire adv_ret = (s3_k_sel_r == 2'd0) ? adv_0  : (s3_k_sel_r == 2'd1) ? adv_p1 : (s3_k_sel_r == 2'd2) ? adv_p2 : adv_p3;

    wire ge1_sel = step_issue ? (advance ? ge1_adv : ge1_ret) : ge1_no;
    wire adv_sel = step_issue ? (advance ? adv_adv : adv_ret) : adv_no;

    wire debt_ge1_next = en_dhi && (p_ovf_any ? 1'b1 : ge1_sel);
    wire debt_adv_next = !en_dhi ? 1'b0 : (debt_ovp_r ? 1'b1 : (debt_ovn_r ? 1'b0 : adv_sel));

    // 2-stage 6+6 / 6+7 pipelined quality accumulators (5 gates/stage, 100% bit-exact, 0-bubble!)
    reg        q_eval_r;
    reg        q_age_ok_r;
    reg        q_debt_ok_r;
    reg [12:0] q_sum_r;
    reg [11:0] q_thr_r;

    wire [6:0] qs_lo7      = {1'b0, qs_lo6} + {1'b0, vote_sum[5:0]};
    wire [6:0] qt_lo7      = {1'b0, qt_lo6} + {1'b0, trans_cnt};
    wire [6:0] qs_hi7_inc  = qs_hi7 + 7'd1;
    wire [6:0] qs_hi7_dec  = qs_hi7 - 7'd1;
    wire [6:0] qs_hi7_next = (!qs_sgn && qs_c6) ? qs_hi7_inc :
                             ( qs_sgn && !qs_c6) ? qs_hi7_dec : qs_hi7;
    wire [5:0] qt_hi6_next = qt_c6 ? (qt_hi6 + 6'd1) : qt_hi6;

    // Stage 2a -> 2b pipelined 4+4+4 nibble compare (5 gates + 3 gates, quality flag only!)
    wire [11:0] q_mag_s2 = q_sum_r[12] ? ~q_sum_r[11:0] : q_sum_r[11:0];
    wire        q_lt_hi  = (q_mag_s2[11:8] < q_thr_r[11:8]);
    wire        q_eq_hi  = (q_mag_s2[11:8] == q_thr_r[11:8]);
    wire        q_lt_md  = (q_mag_s2[7:4]  < q_thr_r[7:4]);
    wire        q_eq_md  = (q_mag_s2[7:4]  == q_thr_r[7:4]);
    wire        q_ok_lo  = q_sum_r[12] ? (q_mag_s2[3:0] < q_thr_r[3:0]) : (q_mag_s2[3:0] <= q_thr_r[3:0]);
    wire        q_tok_s1 = |q_thr_r[9:5];
    reg         q_eval_s1b_r, q_lt_hi_r, q_eq_hi_r, q_lt_md_r, q_eq_md_r, q_ok_lo_r;
    reg         q_tok_s1b_r, q_age_s1b_r, q_debt_s1b_r;
    wire        q_cmp_ok = q_lt_hi_r || (q_eq_hi_r && (q_lt_md_r || (q_eq_md_r && q_ok_lo_r)));
    wire        q_pass_r = q_tok_s1b_r && q_cmp_ok && q_debt_s1b_r && q_age_s1b_r;
    reg         q_eval_s2_r, q_pass_s2_r, q_tok_s2_r;

    // Fast parallel +/-1 frequency update with PRE-REGISTERED at_pos_r / at_neg_r (0-gate clamp check!)
    wire [5:0] fp_lo5 = {1'b0, freq_q9[4:0]} + 6'd1;
    wire [4:0] fp_hi5 = fp_lo5[5] ? (freq_q9[9:5] + 5'd1) : freq_q9[9:5];
    wire signed [9:0] freq_p1 = $signed({fp_hi5, fp_lo5[4:0]});

    wire [4:0] fm_lo5 = freq_q9[4:0] + 5'h1F;
    wire       fm_brw = (freq_q9[4:0] == 5'd0);
    wire [4:0] fm_hi5 = fm_brw ? (freq_q9[9:5] - 5'd1) : freq_q9[9:5];
    wire signed [9:0] freq_m1 = $signed({fm_hi5, fm_lo5});

    reg at_pos_r, at_neg_r;
    wire do_f_inc   = err_pos && !at_pos_r;
    wire do_f_dec   = err_neg && !at_neg_r;
    wire f_sat      = (err_pos && at_pos_r) || (err_neg && at_neg_r);
    wire signed [9:0] fnext = do_f_inc ? freq_p1 : (do_f_dec ? freq_m1 : freq_q9);
    wire at_pos_next = ((freq_q9 == (FREQ_LIMIT_10 - 10'sd1)) && err_pos) || (at_pos_r && !err_neg);
    wire at_neg_next = ((freq_q9 == (-FREQ_LIMIT_10 + 10'sd1)) && err_neg) || (at_neg_r && !err_pos);

    // Pre-registered quality_ticks == QTICKS_LAST flag (0-gate end-of-window trigger!)
    localparam [6:0] QTICKS_PREV = QTICKS_LAST - 7'd1;
    reg qticks_last_c;
    wire qticks_hit_next = (quality_ticks == QTICKS_PREV) && vote_valid;

    // Block B (rst_b: freq/debt/handshake datapath)
    always @(posedge ctrl_clk or negedge rst_b) begin
        if (!rst_b) begin
            freq_q9       <= 10'sd0;
            at_pos_r      <= 1'b0;
            at_neg_r      <= 1'b0;
            debt_lo9      <= 9'd0;
            debt_hi7      <= 7'sd0;
            s3_k_sel_r    <= 2'd1;
            s3_en_r       <= 1'b0;
            debt_ge1_r    <= 1'b0;
            debt_adv_r    <= 1'b0;
            inflight      <= 1'b0;
            range_limited <= 1'b0;
        end else begin
            if (step_issue) begin
                inflight <= 1'b1;
            end
            if (step_done) inflight <= 1'b0;

            // Stage 1: low 9-bit debt update + 2-bit k_sel register (1 => k=0 when disabled/clamped!)
            if (!en_dlo) begin
                debt_lo9   <= 9'd0;
                s3_k_sel_r <= 2'd1;
                s3_en_r    <= 1'b0;
            end else if (debt_ovp_r) begin
                debt_lo9   <= 9'h1FF;
                s3_k_sel_r <= 2'd1;
                s3_en_r    <= 1'b0;
            end else if (debt_ovn_r) begin
                debt_lo9   <= 9'h000;
                s3_k_sel_r <= 2'd1;
                s3_en_r    <= 1'b0;
            end else begin
                debt_lo9   <= p_lo9;
                s3_k_sel_r <= s3_k_sel_n;
                s3_en_r    <= 1'b1;
            end

            // Stage 2: high 7-bit debt update + exact 0-extra-cycle step request flags!
            debt_hi7   <= debt_hi7_next;
            debt_ge1_r <= debt_ge1_next;
            debt_adv_r <= debt_adv_next;

            if (en_b) begin
                freq_q9  <= fnext;
                at_pos_r <= at_pos_next;
                at_neg_r <= at_neg_next;
                if (f_sat || (do_hi_upd && p_ovf_any)) range_limited <= 1'b1;
            end else begin
                freq_q9       <= 10'sd0;
                at_pos_r      <= 1'b0;
                at_neg_r      <= 1'b0;
                range_limited <= 1'b0;
            end
        end
    end

    // Block C (rst_c: 2-stage 6+6/7 quality window accumulators & age/holdover)
    always @(posedge ctrl_clk or negedge rst_c) begin
        if (!rst_c) begin
            holdover      <= 1'b0;
            age           <= 9'd0;
            quality_ticks <= 7'd0;
            qticks_last_c <= 1'b0;
            qs_lo6        <= 6'd0;
            qs_lo6_snap   <= 6'd0;
            qs_hi7        <= 7'd0;
            qs_c6         <= 1'b0;
            qs_sgn        <= 1'b0;
            qt_lo6        <= 6'd0;
            qt_lo6_snap   <= 6'd0;
            qt_hi6        <= 6'd0;
            qt_c6         <= 1'b0;
            q_v_d1        <= 1'b0;
            q_last_d1     <= 1'b0;
            q_age_ok_s0   <= 1'b0;
            q_debt_ok_s0  <= 1'b0;
        end else if (en_c) begin
            if (has_trans) begin
                age      <= 9'd0;
                holdover <= 1'b0;
            end else begin
                if (age < NO_TRANS_9) age <= age + 9'd1;
                holdover <= 1'b1;
            end

            // Stage 1: low 6-bit accumulate
            q_v_d1    <= vote_valid;
            q_last_d1 <= vote_valid && qticks_last_c;
            if (vote_valid) begin
                qs_c6  <= qs_lo7[6];
                qs_sgn <= vote_sum[6];
                qt_c6  <= qt_lo7[6];
                if (qticks_last_c) begin
                    quality_ticks <= 7'd0;
                    qticks_last_c <= 1'b0;
                    qs_lo6        <= 6'd0;
                    qt_lo6        <= 6'd0;
                    qs_lo6_snap   <= qs_lo7[5:0];
                    qt_lo6_snap   <= qt_lo7[5:0];
                    q_age_ok_s0   <= (age < NO_TRANS_9);
                    q_debt_ok_s0  <= debt_in_2one && !range_limited;
                end else begin
                    quality_ticks <= quality_ticks + 7'd1;
                    qticks_last_c <= qticks_hit_next;
                    qs_lo6        <= qs_lo7[5:0];
                    qt_lo6        <= qt_lo7[5:0];
                end
            end

            // Stage 2: high 7-bit / 6-bit carry-in update (4 gates!)
            if (q_v_d1) begin
                if (q_last_d1) begin
                    qs_hi7 <= 7'd0;
                    qt_hi6 <= 6'd0;
                end else begin
                    qs_hi7 <= qs_hi7_next;
                    qt_hi6 <= qt_hi6_next;
                end
            end
        end else begin
            holdover      <= 1'b0;
            age           <= 9'd0;
            quality_ticks <= 7'd0;
            qticks_last_c <= 1'b0;
            qs_lo6        <= 6'd0;
            qs_lo6_snap   <= 6'd0;
            qs_hi7        <= 7'd0;
            qs_c6         <= 1'b0;
            qs_sgn        <= 1'b0;
            qt_lo6        <= 6'd0;
            qt_lo6_snap   <= 6'd0;
            qt_hi6        <= 6'd0;
            qt_c6         <= 1'b0;
            q_v_d1        <= 1'b0;
            q_last_d1     <= 1'b0;
            q_age_ok_s0   <= 1'b0;
            q_debt_ok_s0  <= 1'b0;
        end
    end

    // Block D (rst_d: quality evaluation & lock state)
    always @(posedge ctrl_clk or negedge rst_d) begin
        if (!rst_d) begin
            locked       <= 1'b0;
            q_eval_r     <= 1'b0;
            q_eval_s1b_r <= 1'b0;
            q_lt_hi_r    <= 1'b0;
            q_eq_hi_r    <= 1'b0;
            q_lt_md_r    <= 1'b0;
            q_eq_md_r    <= 1'b0;
            q_ok_lo_r    <= 1'b0;
            q_tok_s1b_r  <= 1'b0;
            q_age_s1b_r  <= 1'b0;
            q_debt_s1b_r <= 1'b0;
            q_eval_s2_r  <= 1'b0;
            q_pass_s2_r  <= 1'b0;
            q_tok_s2_r   <= 1'b0;
            q_age_ok_r   <= 1'b0;
            q_debt_ok_r  <= 1'b0;
            q_sum_r      <= 13'd0;
            q_thr_r      <= 12'd0;
            good_count   <= 3'd0;
            bad_count    <= 3'd0;
        end else if (en_d) begin
            if (age >= NO_TRANS_9) begin
                locked     <= 1'b0;
                good_count <= 3'd0;
            end
            q_eval_r     <= 1'b0;
            q_eval_s1b_r <= q_eval_r;
            q_lt_hi_r    <= q_lt_hi;
            q_eq_hi_r    <= q_eq_hi;
            q_lt_md_r    <= q_lt_md;
            q_eq_md_r    <= q_eq_md;
            q_ok_lo_r    <= q_ok_lo;
            q_tok_s1b_r  <= q_tok_s1;
            q_age_s1b_r  <= q_age_ok_r;
            q_debt_s1b_r <= q_debt_ok_r;
            q_eval_s2_r  <= q_eval_s1b_r;
            q_pass_s2_r  <= q_pass_r;
            q_tok_s2_r   <= q_tok_s1b_r;
            if (q_last_d1) begin
                q_eval_r    <= 1'b1;
                q_sum_r     <= {qs_hi7_next, qs_lo6_snap};
                q_thr_r     <= {2'b00, qt_hi6_next, qt_lo6_snap[5:2]};
                q_age_ok_r  <= q_age_ok_s0;
                q_debt_ok_r <= q_debt_ok_s0;
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
            locked       <= 1'b0;
            q_eval_r     <= 1'b0;
            q_eval_s1b_r <= 1'b0;
            q_eval_s2_r  <= 1'b0;
            q_pass_s2_r  <= 1'b0;
            q_tok_s2_r   <= 1'b0;
            good_count   <= 3'd0;
            bad_count    <= 3'd0;
        end
    end
endmodule
