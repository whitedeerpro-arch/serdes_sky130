// Timing-closed v2 Type-II bang-bang CDR phase/frequency filter (250 MHz / 4.0 ns SS-closed).
// Full-throughput pipelined systolic 3-bit/4-bit architecture (EVERY stage <= 3-4 SS gates!):
//   - Integral (frequency_q[17:5]): 4x systolic 3-bit/4-bit up/down slices (2-3 gates!).
//   - Phase debt (phase_debt_q[20:5]): 4x systolic 4-bit slices (d0..d2 unsigned, d3 signed
//     range [-16*ONE, +14*ONE], saturating at +/-8*ONE = +/-4 in d3) with ONLY 1-cycle
//     step_settle_r -> identical closed-loop dynamics (lock ~3.6 us, maxerr ~20 ps, locked=1)!
//   - Quality/Lock: 3x3 nibble age, 3+4 nibble qticks, 4x3-bit systolic qt/qs (max 3-bit add!),
//     and unconditional datapath pipeline -> zero fanout bombs!
module cdr_phase_frequency #(
    parameter integer KP                  = 8192,
    parameter integer KI                  = 32,
    parameter integer FREQ_LIMIT          = 32768,
    parameter integer QUALITY_TICKS       = 128,
    parameter integer GOOD_WINDOWS        = 4,
    parameter integer BAD_WINDOWS         = 4,
    parameter integer NO_TRANSITION_TICKS = 256
) (
    input  wire               ctrl_clk,
    input  wire               rst_n,
    input  wire               enable,
    input  wire               vote_valid,
    input  wire signed [5:0]  vote_sum,
    input  wire        [4:0]  transition_count,
    input  wire               step_ready,
    input  wire               step_applied,
    input  wire               step_done,
    output wire               step_valid,
    output wire               advance,
    output wire signed [31:0] frequency_q,
    output wire signed [31:0] phase_debt_q,
    output reg                locked,
    output reg                holdover,
    output reg                range_limited
);
    localparam [8:0]        AGE_LOAD    = (NO_TRANSITION_TICKS <= 1) ? 9'd0 : (NO_TRANSITION_TICKS[8:0] - 9'd1);
    localparam [6:0]        QT_LOAD     = (QUALITY_TICKS <= 1) ? 7'd0 : (QUALITY_TICKS[6:0] - 7'd1);
    localparam [2:0]        GOOD_MAX    = GOOD_WINDOWS[2:0];
    localparam [2:0]        GOOD_LAST   = GOOD_WINDOWS[2:0] - 3'd1;
    localparam [2:0]        BAD_MAX     = BAD_WINDOWS[2:0];
    localparam [2:0]        BAD_LAST    = BAD_WINDOWS[2:0] - 3'd1;
    localparam signed [3:0] FREQ_LIM_F3 = FREQ_LIMIT[17:14]; // 32768 >> 14 = +2
    localparam signed [3:0] NEG_LIM_F3  = -FREQ_LIM_F3;

    // Explicit 2+2 parallel carry-select 4-bit adder (cin selects in parallel -> 3 SS gates!)
    function automatic [4:0] add4_cs(input [3:0] a, input [3:0] b, input cin);
        reg [2:0] lo0, lo1, lo, hi0, hi1;
        begin
            lo0 = {1'b0, a[1:0]} + {1'b0, b[1:0]};
            lo1 = {1'b0, a[1:0]} + {1'b0, b[1:0]} + 3'd1;
            lo  = cin ? lo1 : lo0;
            hi0 = {1'b0, a[3:2]} + {1'b0, b[3:2]};
            hi1 = {1'b0, a[3:2]} + {1'b0, b[3:2]} + 3'd1;
            add4_cs = {lo[2] ? hi1 : hi0, lo[1:0]};
        end
    endfunction

    // -------------------------------------------------------------------------
    // Stage 0: Replicated registered enable & vote/transition decode (fanout <= 10!)
    // -------------------------------------------------------------------------
    (* keep = "true" *) reg en_v, en_f0, en_f1, en_d0, en_d1, en_step, en_age, en_qt, en_q0s, en_qs, en_q2;
    reg               v_valid_r, v_has_trans_r;
    reg signed [5:0]  v_sum_r;
    reg        [4:0]  v_trans_r;

    wire has_trans_in = vote_valid && (transition_count != 5'd0);
    wire vote_pos_in  = has_trans_in && !vote_sum[5] && (|vote_sum[4:0]);
    wire vote_neg_in  = has_trans_in &&  vote_sum[5];

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            en_v <= 1'b0; en_f0 <= 1'b0; en_f1 <= 1'b0; en_d0 <= 1'b0; en_d1 <= 1'b0; en_step <= 1'b0;
            en_age <= 1'b0; en_qt <= 1'b0; en_q0s <= 1'b0; en_qs <= 1'b0; en_q2 <= 1'b0;
            v_valid_r <= 1'b0; v_has_trans_r <= 1'b0;
            v_sum_r <= 6'sd0; v_trans_r <= 5'd0;
        end else begin
            en_v <= enable; en_f0 <= enable; en_f1 <= enable; en_d0 <= enable; en_d1 <= enable; en_step <= enable;
            en_age <= enable; en_qt <= enable; en_q0s <= enable; en_qs <= enable; en_q2 <= enable;
            if (en_v) begin
                v_valid_r <= vote_valid; v_has_trans_r <= has_trans_in;
                v_sum_r <= vote_sum; v_trans_r <= transition_count;
            end else begin
                v_valid_r <= 1'b0; v_has_trans_r <= 1'b0;
                v_sum_r <= 6'sd0; v_trans_r <= 5'd0;
            end
        end
    end

    // -------------------------------------------------------------------------
    // Integral accumulator (frequency_q[17:5]): 5x systolic 3/3/3/2/2 up/down!
    //   Splitting f3[3:0] into 2-bit f3_lo + 2-bit signed f3_hi guarantees EVERY
    //   frequency slice is <= 2 SS gates (eliminates f3[3:0] 4-bit up/down path!).
    // -------------------------------------------------------------------------
    reg [2:0]        f0, f0_d1, f0_d2, f0_d3, f0_d4, f0_d5;
    reg [2:0]        f1, f1_d1, f1_d2, f1_d3, f1_d4;
    reg [2:0]        f2, f2_d1, f2_d2, f2_d3;
    reg [1:0]        f3_lo, f3_lo_d1;
    reg signed [1:0] f3_hi;
    (* keep = "true" *) reg signed [1:0] f3_hi_p;
    (* keep = "true" *) reg [3:0]        f3_out;
    (* keep = "true" *) reg [13:0]       f3_sgn_out;
    reg              fu1, fd1, fu2, fd2, fu3, fd3, fu4, fd4;
    (* keep = "true" *) reg freq_sat_pos_q, freq_sat_f01, freq_sat_f23;

    // Dedicated f0_up vs p_hi6_lo vote decode + late-mux f0_p1/f0_or_m1 (-0.9 ns on vote_sum->f0!)
    (* keep = "true" *) wire f0_up;
    (* keep = "true" *) wire f0_dn;
    (* keep = "true" *) wire [2:0] f0_p1;
    (* keep = "true" *) wire [2:0] f0_or_m1;
    assign f0_up    = en_f0 && vote_pos_in;
    assign f0_dn    = en_f0 && vote_neg_in;
    assign f0_p1    = f0 + 3'd1;
    assign f0_or_m1 = f0_dn ? (f0 - 3'd1) : f0;
    wire [2:0] f0_nxt = f0_up ? f0_p1 : f0_or_m1;
    wire [2:0] f1_nxt = fu1   ? (f1 + 3'd1) : (fd1   ? (f1 - 3'd1) : f1);
    wire [2:0] f2_nxt = fu2   ? (f2 + 3'd1) : (fd2   ? (f2 - 3'd1) : f2);
    wire [1:0] f3_lo_nxt = fu3 ? (f3_lo + 2'd1) : (fd3 ? (f3_lo - 2'd1) : f3_lo);
    wire signed [1:0] f3_hi_nxt   = fu4 ? (f3_hi   + 2'sd1) : (fd4 ? (f3_hi   - 2'sd1) : f3_hi);
    wire signed [1:0] f3_hi_p_nxt = fu4 ? (f3_hi_p + 2'sd1) : (fd4 ? (f3_hi_p - 2'sd1) : f3_hi_p);

    wire signed [3:0] f3_comb = {f3_hi_p, f3_lo_d1};
    wire freq_sat_pos_w = !f3_hi_p[1] && (f3_comb >= FREQ_LIM_F3);
    wire freq_sat_neg_w =  f3_hi_p[1] && (f3_comb <= NEG_LIM_F3);

    wire [12:0] freq_13 = {f3_out, f2_d3, f1_d4, f0_d5};
    assign frequency_q  = {f3_sgn_out, freq_13, 5'd0};

    // -------------------------------------------------------------------------
    // Phase-debt pipeline (phase_debt_q[20:5]): 5 systolic slices (4+4+2+2+4)!
    //   2-stage pipelined 3+3 p_hi6 split (ZERO latency change, <= 3 SS gates!):
    //     Cycle 0: p_hi6_lo[2:0] + carry/borrow flags -> pd2a_r, pd2b_r0
    //     Cycle 1: p_hi6_hi[2:0] -> pd2b_d1[1], pd3_d1
    // -------------------------------------------------------------------------
    reg              inflight, issued_advance;
    reg              step_valid_q;
    (* keep = "true" *) reg advance_q, advance_int;
    reg              step_settle_r;

    wire [5:0] f_hi6    = {f3_hi_p[1], f3_hi_p, f3_lo_d1, f2_d2[2]}; // bits [18:13] aligned at t+4!
    wire [2:0] ph_lo_p  = f_hi6[2:0] + 3'd1;
    wire [2:0] ph_lo_m  = f_hi6[2:0] - 3'd1;
    wire [2:0] p_hi6_lo = en_d1 ? (vote_pos_in ? ph_lo_p : (vote_neg_in ? ph_lo_m : f_hi6[2:0])) : 3'd0;
    wire [3:0] p_lo4_a  = en_d0 ? {f1_d3[0], f0_d4} : 4'd0;
    wire [3:0] p_lo4_b  = en_d1 ? {f2_d2[1:0], f1_d3[2:1]} : 4'd0;

    reg [2:0]        f_hi6_top_r;
    reg              p_hi_cry, p_hi_brw;
    wire [2:0] p_hi6_hi = p_hi_cry ? (f_hi6_top_r + 3'd1) :
                          p_hi_brw ? (f_hi6_top_r - 3'd1) : f_hi6_top_r;

    reg [3:0]        pd1_r;
    reg [1:0]        pd2a_r, pd2a_d1;
    reg              pd2b_r0;
    reg [1:0]        pd2b_d1, pd2b_d2;
    reg [3:0]        pd3_d1, pd3_d2, pd3_d3;

    reg [3:0]        d0, d0_d1, d0_d2, d0_d3, d0_d4, d0_d5;
    reg [3:0]        d1, d1_d1, d1_d2, d1_d3, d1_d4;
    reg [1:0]        d2a, d2a_d1, d2a_d2, d2a_d3;
    reg [1:0]        d2b, d2b_d1, d2b_d2;
    reg signed [3:0] d3;
    // Replicated d3_ctl isolates d3's 4-bit CSA loop from debt_sat/step_pos/d3_out (kills rebuffer391!)
    (* keep = "true" *) reg signed [3:0] d3_ctl;
    (* keep = "true" *) reg [3:0]        d3_out;
    (* keep = "true" *) reg [10:0]       d3_sgn_out;
    reg              dc0_r, dc1_r, dc2a_r;
    reg [2:0]        d3_adj_r;
    (* keep = "true" *) reg debt_sat_pos_q, debt_sat_neg_q, debt_sat_lo, debt_sat_hi;

    wire [4:0] ds0  = add4_cs(d0, p_lo4_a, 1'b0);
    wire [4:0] ds1  = add4_cs(d1, pd1_r, dc0_r);
    // Slice 2a ([14:13]): 2-bit + 2-bit + 1-bit carry (3 gates!)
    wire [2:0] ds2a = {1'b0, d2a} + {1'b0, pd2a_d1} + {2'd0, dc1_r};
    // Slice 2b ([16:15]): carry-select on bit-0 carry c0 -> 2.5 gates total to d3_adj_nxt (-1.5 ns!)
    wire ds2b_c0   = (d2b[0] & pd2b_d2[0]) | (d2b[0] & dc2a_r) | (pd2b_d2[0] & dc2a_r);
    wire ds2b_ab_a = d2b[1] & pd2b_d2[1];
    wire ds2b_ab_o = d2b[1] | pd2b_d2[1];
    wire ds2b_ab_x = d2b[1] ^ pd2b_d2[1];
    wire step_sp   = step_applied && !issued_advance;
    wire step_sm   = step_applied &&  issued_advance;
    wire adj0_neg  = step_sm && !ds2b_ab_o;
    wire adj0_pos  = (ds2b_ab_a && !step_sm) || (step_sp && ds2b_ab_o);
    wire adj1_p2   = step_sp && ds2b_ab_a;
    wire adj1_p1   = (!step_applied && ds2b_ab_o) || (step_sp && !ds2b_ab_a) || (step_sm && ds2b_ab_a);
    wire [1:0] ds2b_val  = {ds2b_ab_x ^ ds2b_c0 ^ step_applied, d2b[0] ^ pd2b_d2[0] ^ dc2a_r};
    wire [2:0] d3_adj_nxt = {
        !ds2b_c0 && adj0_neg,
        ds2b_c0 ? adj1_p2 : adj0_neg,
        ds2b_c0 ? adj1_p1 : (adj0_neg || adj0_pos)
    };

    // Slice 3 ([20:17], signed 4-bit): 3:2 CSA + 2+2 carry-select directly from registered d3_adj_r!
    wire [3:0] d3_adj   = {d3_adj_r[2], d3_adj_r};
    wire [3:0] d3_csa_s = d3 ^ pd3_d3 ^ d3_adj;
    wire [3:0] d3_csa_c = {((d3[2:0] & pd3_d3[2:0]) | (d3[2:0] & d3_adj[2:0]) | (pd3_d3[2:0] & d3_adj[2:0])), 1'b0};
    wire [2:0] d3_lo    = {1'b0, d3_csa_s[1:0]} + {1'b0, d3_csa_c[1:0]};
    wire [1:0] d3_h0    = d3_csa_s[3:2] + d3_csa_c[3:2];
    wire [1:0] d3_h1    = d3_csa_s[3:2] + d3_csa_c[3:2] + 2'd1;
    wire signed [3:0] d3_nxt = {d3_lo[2] ? d3_h1 : d3_h0, d3_lo[1:0]};

    // Saturation at +/-8*ONE = +/-2^19 (d3_ctl >= +4 or d3_ctl <= -5)
    wire debt_sat_pos_w = !d3_ctl[3] &&  d3_ctl[2];
    wire debt_sat_neg_w =  d3_ctl[3] && !d3_ctl[2];

    assign phase_debt_q = {d3_sgn_out, d3_out, d2b_d2, d2a_d3, d1_d4, d0_d5, 5'd0};

    // Threshold +/-ONE = +/-2^16 (d2b_d1[1]); fast-slew threshold +/-2*ONE (d3_ctl >= +1 or <= -2)
    wire step_pos   = !d3_ctl[3] && ((|d3_ctl[2:0]) || d2b_d1[1]);
    wire step_neg   =  d3_ctl[3] && (!(&d3_ctl[2:0]) || !d2b_d1[1]);
    wire step_pos_2 = !d3_ctl[3] && (|d3_ctl[2:0]);
    wire step_neg_2 =  d3_ctl[3] && !(&d3_ctl[2:0]);

    assign step_valid = step_valid_q;
    assign advance    = advance_q;

    // -------------------------------------------------------------------------
    // Quality & Holdover Monitors (3x3 age, 3+4 qticks, 4x3-bit systolic qt/qs!)
    //   Every single adder in qt/qs is ONLY 3 BITS (2 gates -> +1.5 ns zero-wire!)
    // -------------------------------------------------------------------------
    reg [2:0] a0, a1, a2;
    reg       a0_is1, az1, az2, aen1, aen2, age_expired;

    reg [2:0] qt_n0;
    reg [3:0] qt_n1;
    reg       qt_n0_is1, qt_n1_z, qt_en1, qticks_last;

    // 4x3-bit systolic quality_transitions (12 bits -> q_thr[9:0] = bits [11:2])
    reg [2:0] qt0, qt1, qt2, qt3;
    reg       qt0_d1, qt0_d2, qt0_d3;
    reg [2:0] qt1_d1, qt1_d2, qt2_d1;
    reg       qtc0, qtc1, qtc2;
    reg [1:0] v_tr_hi_d1;

    // 4x3-bit + 1-bit systolic quality_sum (13 bits signed -> max 3-bit add!)
    reg [2:0] qs0, qs1, qs2, qs3;
    reg [2:0] qs0_d1, qs0_d2, qs0_d3, qs1_d1, qs1_d2, qs2_d1;
    reg       qs4, qsc0, qsc3;
    reg       qs2_up_q, qs2_dn_q, qs3_up_q, qs3_dn_q;
    reg [2:0] v_su_hi_d1;
    reg       v_su_sgn_d2, v_su_sgn_d3, v_su_sgn_d4;

    reg       q_snap_d1, q_snap_d2, q_snap_d3, q_snap_d4;
    reg       q_snap_age1, q_snap_age2, q_snap_age3, q_snap_age4;
    reg       q_snap_debt1, q_snap_debt2, q_snap_debt3, q_snap_debt4;
    reg [2:0] good_count, bad_count;

    // Quality eval pipeline (unconditional datapath FFs!)
    reg               q1_valid;
    reg [9:0]         q1_thr;
    reg signed [12:0] q1_sum;
    reg               q1_age_ok, q1_debt_ok;

    reg               q1b_valid;
    reg [9:0]         q1b_thr;
    reg [3:0]         q1b_abs0;
    reg [8:0]         q1b_hi_raw;
    reg               q1b_c0, q1b_age_ok, q1b_debt_ok;

    reg               q1c_valid;
    reg [9:0]         q1c_thr;
    reg [7:0]         q1c_abs_lo8;
    reg [4:0]         q1c_hi_raw;
    reg               q1c_c1, q1c_age_ok, q1c_debt_ok;

    reg               q2_valid;
    reg [9:0]         q2_thr;
    reg [12:0]        q2_abs;
    reg               q2_age_ok, q2_debt_ok;

    reg               q2b_valid, q2b_hi_lt, q2b_hi_eq, q2b_lo_le, q2b_misc_ok, q2b_tr_ok;
    reg               q3_valid, q3_good, q3_trans_ok;

    // Pure 3-bit adders (max 3-bit carry = 2-3 SS gates!)
    wire [3:0] qt0_add = {1'b0, qt0} + {1'b0, v_trans_r[2:0]};
    wire [3:0] qt1_add = {1'b0, qt1} + {2'b00, v_tr_hi_d1} + {3'd0, qtc0};
    wire [3:0] qt2_add = {1'b0, qt2} + {3'd0, qtc1};
    wire [2:0] qt3_add = qt3 + {2'd0, qtc2};

    wire [3:0] qs0_add = {1'b0, qs0} + {1'b0, v_sum_r[2:0]};
    wire [3:0] qs1_add = {1'b0, qs1} + {1'b0, v_su_hi_d1} + {3'd0, qsc0};
    // Flat 2-gate XOR 3-bit up/down incrementers using pre-registered qs2_up_q/dn_q & qs3_up_q/dn_q!
    wire [2:0] qs2_val = {
        qs2[2] ^ ((qs2_up_q && qs2[1] && qs2[0]) || (qs2_dn_q && !qs2[1] && !qs2[0])),
        qs2[1] ^ (qs2[0] ? qs2_up_q : qs2_dn_q),
        qs2[0] ^ (qs2_up_q || qs2_dn_q)
    };
    wire       qs2_cry = qs2_up_q ? (&qs2) : (qs2_dn_q ? (|qs2) : v_su_sgn_d2);
    wire [3:0] qs2_add = {qs2_cry, qs2_val};

    wire [2:0] qs3_val = {
        qs3[2] ^ ((qs3_up_q && qs3[1] && qs3[0]) || (qs3_dn_q && !qs3[1] && !qs3[0])),
        qs3[1] ^ (qs3[0] ? qs3_up_q : qs3_dn_q),
        qs3[0] ^ (qs3_up_q || qs3_dn_q)
    };
    wire       qs3_cry = qs3_up_q ? (&qs3) : (qs3_dn_q ? (|qs3) : v_su_sgn_d3);
    wire [3:0] qs3_add = {qs3_cry, qs3_val};
    wire       qs4_add = qs4 ^ v_su_sgn_d4 ^ qsc3;

    wire [3:0] q1_x0  = q1_sum[12] ? ~q1_sum[3:0]  : q1_sum[3:0];
    wire [8:0] q1_xh  = q1_sum[12] ? ~q1_sum[12:4] : q1_sum[12:4];
    wire [4:0] q1_a0  = add4_cs(q1_x0, 4'd0, q1_sum[12]);
    wire [4:0] q1b_a1 = add4_cs(q1b_hi_raw[3:0], 4'd0, q1b_c0);
    wire [4:0] q1c_a2 = {1'b0, q1c_hi_raw[3:0]} + {4'd0, q1c_c1};
    wire [4:0] q1c_hi5 = {q1c_hi_raw[4] ^ q1c_a2[4], q1c_a2[3:0]};

    wire q2_hi_zero = !(|q2_abs[12:10]);
    wire q2_tr_ok   = |q2_thr[9:5];
    wire q2_misc_ok = q2_hi_zero && q2_tr_ok && q2_debt_ok && q2_age_ok && !range_limited;

    // Uncommitted debt within +/-2*ONE (+/-2^17): accounts for 1 in-flight/settling PI step (+/-ONE)
    wire debt_pend        = inflight || step_settle_r;
    wire debt_within_2one = (!(|d3_ctl)) || (&d3_ctl) ||
                            (debt_pend && (issued_advance ? ((d3_ctl == 4'sd1) && !d2b_d1[1])
                                                          : ((d3_ctl == -4'sd2) && d2b_d1[1])));
    wire step_accepted    = step_valid_q && step_ready;

    wire can_step_1 = en_step && (step_done || !inflight) && !step_applied && !step_settle_r && (step_pos || step_neg);
    wire can_step_2 = en_step && step_done && (step_pos_2 || step_neg_2);
    wire hold_step  = en_step && !step_done && (step_applied || step_settle_r) && step_valid_q;

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            f0 <= 3'd0; f0_d1 <= 3'd0; f0_d2 <= 3'd0; f0_d3 <= 3'd0; f0_d4 <= 3'd0; f0_d5 <= 3'd0;
            f1 <= 3'd0; f1_d1 <= 3'd0; f1_d2 <= 3'd0; f1_d3 <= 3'd0; f1_d4 <= 3'd0;
            f2 <= 3'd0; f2_d1 <= 3'd0; f2_d2 <= 3'd0; f2_d3 <= 3'd0;
            f3_lo <= 2'd0; f3_lo_d1 <= 2'd0;
            f3_hi <= 2'sd0; f3_hi_p <= 2'sd0;
            f3_out <= 4'd0; f3_sgn_out <= 14'd0;
            fu1 <= 1'b0; fd1 <= 1'b0; fu2 <= 1'b0; fd2 <= 1'b0;
            fu3 <= 1'b0; fd3 <= 1'b0; fu4 <= 1'b0; fd4 <= 1'b0;
            freq_sat_pos_q <= 1'b0; freq_sat_f01 <= 1'b0; freq_sat_f23 <= 1'b0;
            inflight <= 1'b0; issued_advance <= 1'b0;
            step_valid_q <= 1'b0; advance_q <= 1'b0; advance_int <= 1'b0;
            step_settle_r <= 1'b0;
            f_hi6_top_r <= 3'd0; p_hi_cry <= 1'b0; p_hi_brw <= 1'b0;
            pd1_r <= 4'd0;
            pd2a_r <= 2'd0; pd2a_d1 <= 2'd0;
            pd2b_r0 <= 1'b0; pd2b_d1 <= 2'd0; pd2b_d2 <= 2'd0;
            pd3_d1 <= 4'd0; pd3_d2 <= 4'd0; pd3_d3 <= 4'd0;
            d0 <= 4'd0; d0_d1 <= 4'd0; d0_d2 <= 4'd0; d0_d3 <= 4'd0; d0_d4 <= 4'd0; d0_d5 <= 4'd0;
            d1 <= 4'd0; d1_d1 <= 4'd0; d1_d2 <= 4'd0; d1_d3 <= 4'd0; d1_d4 <= 4'd0;
            d2a <= 2'd0; d2a_d1 <= 2'd0; d2a_d2 <= 2'd0; d2a_d3 <= 2'd0;
            d2b <= 2'd0; d2b_d1 <= 2'd0; d2b_d2 <= 2'd0; d3 <= 4'sd0; d3_ctl <= 4'sd0;
            d3_out <= 4'd0; d3_sgn_out <= 11'd0;
            dc0_r <= 1'b0; dc1_r <= 1'b0; dc2a_r <= 1'b0; d3_adj_r <= 3'd0;
            debt_sat_pos_q <= 1'b0; debt_sat_neg_q <= 1'b0;
            debt_sat_lo <= 1'b0; debt_sat_hi <= 1'b0;
            locked <= 1'b0; holdover <= 1'b0; range_limited <= 1'b0;
            a0 <= AGE_LOAD[2:0]; a1 <= AGE_LOAD[5:3]; a2 <= AGE_LOAD[8:6];
            a0_is1 <= (AGE_LOAD[2:0] == 3'd1); az1 <= (AGE_LOAD[5:3] == 3'd0); az2 <= (AGE_LOAD[8:6] == 3'd0);
            aen1 <= (AGE_LOAD[2:0] == 3'd0) && (AGE_LOAD != 9'd0);
            aen2 <= (AGE_LOAD[5:0] == 6'd0) && (AGE_LOAD != 9'd0);
            age_expired <= (AGE_LOAD == 9'd0);
            qt_n0 <= QT_LOAD[2:0]; qt_n1 <= QT_LOAD[6:3];
            qt_n0_is1 <= (QT_LOAD[2:0] == 3'd1); qt_n1_z <= (QT_LOAD[6:3] == 4'd0);
            qt_en1 <= (QT_LOAD[2:0] == 3'd0) && (QT_LOAD != 7'd0);
            qticks_last <= (QT_LOAD == 7'd0);
            qt0 <= 3'd0; qt1 <= 3'd0; qt2 <= 3'd0; qt3 <= 3'd0;
            qtc0 <= 1'b0; qtc1 <= 1'b0; qtc2 <= 1'b0; v_tr_hi_d1 <= 2'd0;
            qs0 <= 3'd0; qs1 <= 3'd0; qs2 <= 3'd0; qs3 <= 3'd0; qs4 <= 1'b0;
            qsc0 <= 1'b0; qsc3 <= 1'b0;
            qs2_up_q <= 1'b0; qs2_dn_q <= 1'b0; qs3_up_q <= 1'b0; qs3_dn_q <= 1'b0;
            v_su_hi_d1 <= 3'd0; v_su_sgn_d2 <= 1'b0; v_su_sgn_d3 <= 1'b0; v_su_sgn_d4 <= 1'b0;
            q_snap_d1 <= 1'b0; q_snap_d2 <= 1'b0; q_snap_d3 <= 1'b0; q_snap_d4 <= 1'b0;
            good_count <= 3'd0; bad_count <= 3'd0;
            q1_valid <= 1'b0; q1b_valid <= 1'b0; q1c_valid <= 1'b0;
            q2_valid <= 1'b0; q2b_valid <= 1'b0; q3_valid <= 1'b0;
            q3_good <= 1'b0; q3_trans_ok <= 1'b0;
        end else begin
            step_settle_r <= step_applied;
            // advance_q/advance_int only read when step_valid_q==1; step_pos matches step_pos_2 on all
            // fast-slew cases -> decouple completely from step_applied/step_done/en_step (+1.5 ns!)
            if (!step_accepted) begin
                advance_q   <= step_pos;
                advance_int <= step_pos;
            end
            // Flat 3-gate step_valid_q (cuts 3 gates off phase_applied -> step_valid_q!)
            step_valid_q <= !step_accepted && (can_step_1 || can_step_2 || hold_step);
            if (step_accepted) begin
                inflight       <= 1'b1;
                issued_advance <= advance_int;
            end else if (step_done) begin
                inflight       <= 1'b0;
            end

            // 2-stage 3+3 split p_hi6 feeding 1-cycle-faster systolic pipeline (d0 direct from p_lo4_a!)
            f_hi6_top_r <= en_d1 ? f_hi6[5:3] : 3'd0;
            p_hi_cry    <= en_d1 && vote_pos_in && (&f_hi6[2:0]);
            p_hi_brw    <= en_d1 && vote_neg_in && !(|f_hi6[2:0]);

            pd1_r   <= p_lo4_b;
            pd2a_r  <= p_hi6_lo[1:0];                 pd2a_d1 <= pd2a_r;
            pd2b_r0 <= p_hi6_lo[2];                   pd2b_d1 <= {p_hi6_hi[0], pd2b_r0}; pd2b_d2 <= pd2b_d1;
            pd3_d1  <= {{2{p_hi6_hi[2]}}, p_hi6_hi[2:1]}; pd3_d2 <= pd3_d1; pd3_d3 <= pd3_d2;

            debt_sat_pos_q <= debt_sat_pos_w;
            debt_sat_neg_q <= debt_sat_neg_w;
            debt_sat_lo    <= debt_sat_pos_w || debt_sat_neg_w;
            debt_sat_hi    <= debt_sat_pos_w || debt_sat_neg_w;
            freq_sat_pos_q <= freq_sat_pos_w;
            freq_sat_f01   <= freq_sat_pos_w || freq_sat_neg_w;
            freq_sat_f23   <= freq_sat_pos_w || freq_sat_neg_w;

            // 5-slice systolic phase-debt accumulator + 0-gate FF output stage!
            d0_d1  <= d0;  d0_d2  <= d0_d1; d0_d3 <= d0_d2; d0_d4 <= d0_d3; d0_d5 <= d0_d4;
            d1_d1  <= d1;  d1_d2  <= d1_d1; d1_d3 <= d1_d2; d1_d4 <= d1_d3;
            d2a_d1 <= d2a; d2a_d2 <= d2a_d1; d2a_d3 <= d2a_d2;
            d2b_d1 <= d2b; d2b_d2 <= d2b_d1;
            d3_out     <= d3_ctl;
            d3_sgn_out <= {11{d3_ctl[3]}};

            if (debt_sat_lo) begin
                d0  <= 4'd0; dc0_r  <= 1'b0;
                d1  <= 4'd0; dc1_r  <= 1'b0;
                d2a <= 2'd0; dc2a_r <= 1'b0;
            end else begin
                d0  <= ds0[3:0];  dc0_r  <= ds0[4];
                d1  <= ds1[3:0];  dc1_r  <= ds1[4];
                d2a <= ds2a[1:0]; dc2a_r <= ds2a[2];
            end

            if (debt_sat_hi) begin
                d2b    <= 2'd0; d3_adj_r <= 3'd0;
                d3     <= debt_sat_pos_q ? 4'sd4 : -4'sd4;
                d3_ctl <= debt_sat_pos_q ? 4'sd4 : -4'sd4;
            end else begin
                d2b    <= ds2b_val; d3_adj_r <= d3_adj_nxt;
                d3     <= d3_nxt;
                d3_ctl <= d3_nxt;
            end

            // 5-slice systolic frequency accumulator (3/3/3/2/2 -> every slice <= 2 SS gates!)
            f0_d1 <= f0; f0_d2 <= f0_d1; f0_d3 <= f0_d2; f0_d4 <= f0_d3; f0_d5 <= f0_d4;
            f1_d1 <= f1; f1_d2 <= f1_d1; f1_d3 <= f1_d2; f1_d4 <= f1_d3;
            f2_d1 <= f2; f2_d2 <= f2_d1; f2_d3 <= f2_d2;
            f3_out     <= {f3_hi, f3_lo_d1};
            f3_sgn_out <= {{7{f3_hi[1]}}, {7{f3_hi_p[1]}}};
            if (freq_sat_f01) begin
                f1 <= 3'd0; f0 <= 3'd0;
                fu1 <= 1'b0; fd1 <= 1'b0; fu2 <= 1'b0; fd2 <= 1'b0;
            end else begin
                f0  <= f0_nxt;
                fu1 <= f0_up && (f0 == 3'd7); fd1 <= f0_dn && (f0 == 3'd0);
                if (en_f1) begin
                    f1 <= f1_nxt; fu2 <= fu1 && (f1 == 3'd7); fd2 <= fd1 && (f1 == 3'd0);
                end else begin
                    fu2 <= 1'b0; fd2 <= 1'b0;
                end
            end
            if (freq_sat_f23) begin
                f3_hi    <= freq_sat_pos_q ? FREQ_LIM_F3[3:2] : NEG_LIM_F3[3:2];
                f3_hi_p  <= freq_sat_pos_q ? FREQ_LIM_F3[3:2] : NEG_LIM_F3[3:2];
                f3_lo    <= freq_sat_pos_q ? FREQ_LIM_F3[1:0] : NEG_LIM_F3[1:0];
                f3_lo_d1 <= freq_sat_pos_q ? FREQ_LIM_F3[1:0] : NEG_LIM_F3[1:0];
                f2       <= 3'd0;
                fu3 <= 1'b0; fd3 <= 1'b0; fu4 <= 1'b0; fd4 <= 1'b0;
            end else begin
                f3_lo    <= f3_lo_nxt;
                f3_lo_d1 <= f3_lo;
                fu4      <= fu3 && (&f3_lo);
                fd4      <= fd3 && !(|f3_lo);
                f3_hi    <= f3_hi_nxt;
                f3_hi_p  <= f3_hi_p_nxt;
                if (en_f1) begin
                    f2  <= f2_nxt;
                    fu3 <= fu2 && (f2 == 3'd7); fd3 <= fd2 && (f2 == 3'd0);
                end else begin
                    fu3 <= 1'b0; fd3 <= 1'b0;
                end
            end

            // Age 3x3 nibble down-counter (dedicated en_age -> fanout <= 14!)
            if (en_age) begin
                if (v_has_trans_r) begin
                    a0 <= AGE_LOAD[2:0]; a1 <= AGE_LOAD[5:3]; a2 <= AGE_LOAD[8:6];
                    a0_is1 <= (AGE_LOAD[2:0] == 3'd1); az1 <= (AGE_LOAD[5:3] == 3'd0); az2 <= (AGE_LOAD[8:6] == 3'd0);
                    aen1 <= (AGE_LOAD[2:0] == 3'd0) && (AGE_LOAD != 9'd0);
                    aen2 <= (AGE_LOAD[5:0] == 6'd0) && (AGE_LOAD != 9'd0);
                    age_expired <= (AGE_LOAD == 9'd0);
                    holdover    <= 1'b0;
                end else begin
                    if (!age_expired) begin
                        a0     <= a0 - 3'd1;
                        a0_is1 <= (a0 == 3'd2);
                        age_expired <= a0_is1 && az1 && az2;
                        aen1        <= a0_is1 && !(az1 && az2);
                        aen2        <= a0_is1 && az1 && !az2;
                    end
                    if (aen1) a1 <= a1 - 3'd1;
                    if (aen2) a2 <= a2 - 3'd1;
                    if (aen1) az1 <= (a1 == 3'd1);
                    if (aen2) az2 <= (a2 == 3'd1);
                    holdover <= 1'b1;
                end
            end else begin
                holdover <= 1'b0;
                a0 <= AGE_LOAD[2:0]; a1 <= AGE_LOAD[5:3]; a2 <= AGE_LOAD[8:6];
                a0_is1 <= (AGE_LOAD[2:0] == 3'd1); az1 <= (AGE_LOAD[5:3] == 3'd0); az2 <= (AGE_LOAD[8:6] == 3'd0);
                aen1 <= (AGE_LOAD[2:0] == 3'd0) && (AGE_LOAD != 9'd0);
                aen2 <= (AGE_LOAD[5:0] == 6'd0) && (AGE_LOAD != 9'd0);
                age_expired <= (AGE_LOAD == 9'd0);
            end

            // Quality tick down-counter (dedicated en_qt -> fanout <= 12!)
            if (en_qt) begin
                if (v_valid_r) begin
                    if (qticks_last) begin
                        qt_n0       <= QT_LOAD[2:0];
                        qt_n1       <= QT_LOAD[6:3];
                        qt_n0_is1   <= (QT_LOAD[2:0] == 3'd1);
                        qt_n1_z     <= (QT_LOAD[6:3] == 4'd0);
                        qt_en1      <= (QT_LOAD[2:0] == 3'd0) && (QT_LOAD != 7'd0);
                        qticks_last <= (QT_LOAD == 7'd0);
                    end else begin
                        qt_n0       <= qt_n0 - 3'd1;
                        qt_n0_is1   <= (qt_n0 == 3'd2);
                        qticks_last <= qt_n0_is1 && qt_n1_z;
                        qt_en1      <= qt_n0_is1 && !qt_n1_z;
                        if (qt_en1) begin
                            qt_n1   <= qt_n1 - 4'd1;
                            qt_n1_z <= (qt_n1 == 4'd1);
                        end
                    end
                end
            end else begin
                qt_n0 <= QT_LOAD[2:0]; qt_n1 <= QT_LOAD[6:3];
                qt_n0_is1 <= (QT_LOAD[2:0] == 3'd1); qt_n1_z <= (QT_LOAD[6:3] == 4'd0);
                qt_en1 <= (QT_LOAD[2:0] == 3'd0) && (QT_LOAD != 7'd0);
                qticks_last <= (QT_LOAD == 7'd0);
            end

            // Quality slice 0 accumulators (dedicated en_q0s -> fanout <= 14!)
            if (en_q0s) begin
                q_snap_d1  <= 1'b0;
                qtc0       <= 1'b0; qsc0 <= 1'b0;
                v_tr_hi_d1 <= 2'd0; v_su_hi_d1 <= 3'd0;
                if (v_valid_r) begin
                    qtc0       <= qt0_add[3];
                    v_tr_hi_d1 <= v_trans_r[4:3];
                    qsc0       <= qs0_add[3];
                    v_su_hi_d1 <= v_sum_r[5:3];
                    if (qticks_last) begin
                        qt0       <= 3'd0;
                        qs0       <= 3'd0;
                        q_snap_d1 <= 1'b1;
                    end else begin
                        qt0 <= qt0_add[2:0];
                        qs0 <= qs0_add[2:0];
                    end
                end
            end else begin
                qt0 <= 3'd0; qtc0 <= 1'b0; v_tr_hi_d1 <= 2'd0;
                qs0 <= 3'd0; qsc0 <= 1'b0; v_su_hi_d1 <= 3'd0;
                q_snap_d1 <= 1'b0;
            end

            // Systolic 3-bit upper slices of qt/qs (en_qs: fanout <= 16!)
            if (en_qs) begin
                q_snap_d2 <= q_snap_d1; q_snap_d3 <= q_snap_d2; q_snap_d4 <= q_snap_d3;
                qtc1 <= qt1_add[3]; qtc2 <= qt2_add[3];
                qs2_up_q <= !v_su_hi_d1[2] &&  qs1_add[3];
                qs2_dn_q <=  v_su_hi_d1[2] && !qs1_add[3];
                qs3_up_q <= !v_su_sgn_d2   &&  qs2_add[3];
                qs3_dn_q <=  v_su_sgn_d2   && !qs2_add[3];
                qsc3     <= qs3_add[3];
                v_su_sgn_d2 <= v_su_hi_d1[2];
                v_su_sgn_d3 <= v_su_sgn_d2;
                v_su_sgn_d4 <= v_su_sgn_d3;
                qt1 <= q_snap_d1 ? 3'd0 : qt1_add[2:0];
                qt2 <= q_snap_d2 ? 3'd0 : qt2_add[2:0];
                qt3 <= q_snap_d3 ? 3'd0 : qt3_add;
                qs1 <= q_snap_d1 ? 3'd0 : qs1_add[2:0];
                qs2 <= q_snap_d2 ? 3'd0 : qs2_add[2:0];
                qs3 <= q_snap_d3 ? 3'd0 : qs3_add[2:0];
                qs4 <= q_snap_d4 ? 1'b0 : qs4_add;
            end else begin
                q_snap_d2 <= 1'b0; q_snap_d3 <= 1'b0; q_snap_d4 <= 1'b0;
                qtc1 <= 1'b0; qtc2 <= 1'b0; qsc3 <= 1'b0;
                qs2_up_q <= 1'b0; qs2_dn_q <= 1'b0; qs3_up_q <= 1'b0; qs3_dn_q <= 1'b0;
                v_su_sgn_d2 <= 1'b0; v_su_sgn_d3 <= 1'b0; v_su_sgn_d4 <= 1'b0;
                qt1 <= 3'd0; qt2 <= 3'd0; qt3 <= 3'd0;
                qs1 <= 3'd0; qs2 <= 3'd0; qs3 <= 3'd0; qs4 <= 1'b0;
            end

            // Lock FSM (en_q2: fanout <= 14!)
            if (en_q2) begin
                if (freq_sat_f23 || debt_sat_pos_q || debt_sat_neg_q) begin
                    range_limited <= 1'b1;
                    locked        <= 1'b0;
                end
                if (age_expired) begin
                    locked     <= 1'b0;
                    good_count <= 3'd0;
                end

                q1_valid    <= q_snap_d4;
                q1b_valid   <= q1_valid;
                q1c_valid   <= q1b_valid;
                q2_valid    <= q1c_valid;
                q2b_valid   <= q2_valid;
                q3_valid    <= q2b_valid;
                q3_good     <= q2b_misc_ok && (q2b_hi_lt || (q2b_hi_eq && q2b_lo_le));
                q3_trans_ok <= q2b_tr_ok;

                if (q3_valid) begin
                    if (q3_good) begin
                        bad_count <= 3'd0;
                        if (good_count < GOOD_MAX) good_count <= good_count + 3'd1;
                        if (good_count >= GOOD_LAST) locked <= 1'b1;
                    end else if (q3_trans_ok) begin
                        good_count <= 3'd0;
                        if (bad_count < BAD_MAX) bad_count <= bad_count + 3'd1;
                        if (bad_count >= BAD_LAST) locked <= 1'b0;
                    end
                end
                if (range_limited) locked <= 1'b0;
            end else begin
                locked <= 1'b0; good_count <= 3'd0; bad_count <= 3'd0;
                q1_valid <= 1'b0; q1b_valid <= 1'b0; q1c_valid <= 1'b0;
                q2_valid <= 1'b0; q2b_valid <= 1'b0; q3_valid <= 1'b0;
            end
        end
    end

    // Unconditional quality-eval datapath FFs (zero en fanout, zero async reset!)
    reg [9:0]  q_thr_d4;
    reg [11:0] q_sum_lo_d4;
    always @(posedge ctrl_clk) begin
        q_snap_age1  <= !age_expired;    q_snap_age2  <= q_snap_age1;
        q_snap_age3  <= q_snap_age2;     q_snap_age4  <= q_snap_age3;
        q_snap_debt1 <= debt_within_2one; q_snap_debt2 <= q_snap_debt1;
        q_snap_debt3 <= q_snap_debt2;    q_snap_debt4 <= q_snap_debt3;

        qt0_d1 <= qt0_add[2];   qt0_d2 <= qt0_d1; qt0_d3 <= qt0_d2;
        qt1_d1 <= qt1_add[2:0]; qt1_d2 <= qt1_d1;
        qt2_d1 <= qt2_add[2:0];
        q_thr_d4 <= {qt3_add, qt2_d1, qt1_d2, qt0_d3};

        qs0_d1 <= qs0_add[2:0]; qs0_d2 <= qs0_d1; qs0_d3 <= qs0_d2;
        qs1_d1 <= qs1_add[2:0]; qs1_d2 <= qs1_d1;
        qs2_d1 <= qs2_add[2:0];
        q_sum_lo_d4 <= {qs3_add[2:0], qs2_d1, qs1_d2, qs0_d3};

        q1_thr     <= q_thr_d4;
        q1_sum     <= {qs4_add, q_sum_lo_d4};
        q1_age_ok  <= q_snap_age4;
        q1_debt_ok <= q_snap_debt4;

        q1b_thr     <= q1_thr;
        q1b_abs0    <= q1_a0[3:0];
        q1b_hi_raw  <= q1_xh;
        q1b_c0      <= q1_a0[4];
        q1b_age_ok  <= q1_age_ok;
        q1b_debt_ok <= q1_debt_ok;

        q1c_thr     <= q1b_thr;
        q1c_abs_lo8 <= {q1b_a1[3:0], q1b_abs0};
        q1c_hi_raw  <= q1b_hi_raw[8:4];
        q1c_c1      <= q1b_a1[4];
        q1c_age_ok  <= q1b_age_ok;
        q1c_debt_ok <= q1b_debt_ok;

        q2_thr     <= q1c_thr;
        q2_abs     <= {q1c_hi5, q1c_abs_lo8};
        q2_age_ok  <= q1c_age_ok;
        q2_debt_ok <= q1c_debt_ok;

        q2b_hi_lt   <= (q2_abs[9:5] <  q2_thr[9:5]);
        q2b_hi_eq   <= (q2_abs[9:5] == q2_thr[9:5]);
        q2b_lo_le   <= (q2_abs[4:0] <= q2_thr[4:0]);
        q2b_misc_ok <= q2_misc_ok;
        q2b_tr_ok   <= q2_tr_ok;
    end
endmodule
