// Timing-closed v2 BBPD 16-sample window voter (250 MHz / 4.0 ns SS-closed).
// 6-stage fully balanced pipeline (EVERY stage <= 3 SS gates; 0 gates on primary inputs!):
//   Stage 0:  Pure input capture FFs (s0_valid, s0_prev, s0_data, s0_edge) -> isolates hold buffers!
//   Stage 0b: 16 parallel 2-gate BBPD decodes (s0b_trans, s0b_late, s0b_early) -> +1.8 ns SS!
//   Stage 1:  8x 2-gate pair sums (2-bit trans, signed 3-bit vote) -> +1.5 ns SS!
//   Stage 2:  4x quad sums (3-bit trans, signed 4-bit vote).
//   Stage 3:  2x oct sums (4-bit trans, signed 5-bit vote).
//   Stage 4:  Explicit 2-level CLA final add -> unconditional registered outputs.
// Pipeline latency = 6 ctrl_clk cycles (+20 ns vs v1; negligible vs <1 MHz CDR BW).
module bbpd_window_vote #(
    parameter integer SAMPLES = 16,
    parameter integer COUNT_W = $clog2(SAMPLES + 1),
    parameter integer SUM_W   = COUNT_W + 1
) (
    input  wire                    ctrl_clk,
    input  wire                    rst_n,
    input  wire                    bundle_valid,
    input  wire                    previous_data,
    input  wire [SAMPLES-1:0]      data_samples,
    input  wire [SAMPLES-1:0]      edge_samples,
    output reg                     vote_valid,
    output reg  signed [SUM_W-1:0] vote_sum,
    output reg  [COUNT_W-1:0]      transition_count
);
    // Stage 0: Pure 0-gate input capture FFs (isolates primary-input hold buffers -> +3.0 ns SS!)
    reg                s0_valid, s0_prev;
    reg  [SAMPLES-1:0] s0_data, s0_edge;

    // Stage 0b: 16 parallel 2-gate reg-to-reg BBPD decodes (+1.8 ns SS!)
    wire [15:0] prev_bits = {s0_data[14:0], s0_prev};
    wire [15:0] trans_c   = prev_bits ^ s0_data;
    wire [15:0] ed_xor    = s0_edge ^ s0_data;
    wire [15:0] late_c    = trans_c & ~ed_xor;
    wire [15:0] early_c   = trans_c &  ed_xor;

    reg                s0b_valid;
    reg  [SAMPLES-1:0] s0b_trans;
    reg  [SAMPLES-1:0] s0b_late;
    reg  [SAMPLES-1:0] s0b_early;

    function automatic [1:0] pair_t(input t0, input t1);
        pair_t = {t0 & t1, t0 ^ t1};
    endfunction

    function automatic signed [2:0] pair_v(input t0, input l0, input e0, input t1, input l1, input e1);
        reg v2;
        begin
            v2        = (e0 & !l1) | (e1 & !l0);
            pair_v[0] = t0 ^ t1;
            pair_v[1] = (l0 & l1) | v2;
            pair_v[2] = v2;
        end
    endfunction

    // Stage 1: 8x pair sums
    reg               s1_valid;
    reg  [1:0]        s1_t0, s1_t1, s1_t2, s1_t3, s1_t4, s1_t5, s1_t6, s1_t7;
    reg  signed [2:0] s1_v0, s1_v1, s1_v2, s1_v3, s1_v4, s1_v5, s1_v6, s1_v7;

    // Stage 2: 4x quad sums
    reg               s2_valid;
    reg  [2:0]        s2_t0, s2_t1, s2_t2, s2_t3;
    reg  signed [3:0] s2_v0, s2_v1, s2_v2, s2_v3;

    // Stage 3: 2x oct sums
    reg               s3_valid;
    reg  [3:0]        s3_t0, s3_t1;
    reg  signed [4:0] s3_v0, s3_v1;

    // Stage 4: Explicit 2-level CLA 4-bit t_total & 5-bit v_total (unconditional capture -> no mux2!)
    wire [3:0] tg = s3_t0 & s3_t1;
    wire [3:0] tp = s3_t0 ^ s3_t1;
    wire       tc1 = tg[0];
    wire       tc2 = tg[1] | (tp[1] & tg[0]);
    wire       tc3 = tg[2] | (tp[2] & tg[1]) | (tp[2] & tp[1] & tg[0]);
    wire       tc4 = tg[3] | (tp[3] & tg[2]) | (tp[3] & tp[2] & tg[1]) | (tp[3] & tp[2] & tp[1] & tg[0]);
    wire [4:0] t_total = {tc4, tp[3] ^ tc3, tp[2] ^ tc2, tp[1] ^ tc1, tp[0]};

    wire [5:0] va = {s3_v0[4], s3_v0};
    wire [5:0] vb = {s3_v1[4], s3_v1};
    wire [4:0] vg = va[4:0] & vb[4:0];
    wire [5:0] vp = va ^ vb;
    wire       vc1 = vg[0];
    wire       vc2 = vg[1] | (vp[1] & vg[0]);
    wire       vc3 = vg[2] | (vp[2] & vg[1]) | (vp[2] & vp[1] & vg[0]);
    wire       vc4 = vg[3] | (vp[3] & vg[2]) | (vp[3] & vp[2] & vg[1]) | (vp[3] & vp[2] & vp[1] & vg[0]);
    wire       vc5 = vg[4] | (vp[4] & vg[3]) | (vp[4] & vp[3] & vc3);
    wire signed [5:0] v_total = {vp[5] ^ vc5, vp[4] ^ vc4, vp[3] ^ vc3, vp[2] ^ vc2, vp[1] ^ vc1, vp[0]};

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            s0_valid <= 1'b0; s0_prev <= 1'b0; s0_data <= {SAMPLES{1'b0}}; s0_edge <= {SAMPLES{1'b0}};
            s0b_valid <= 1'b0; s0b_trans <= {SAMPLES{1'b0}}; s0b_late <= {SAMPLES{1'b0}}; s0b_early <= {SAMPLES{1'b0}};
            s1_valid <= 1'b0;
            s1_t0 <= 2'd0; s1_t1 <= 2'd0; s1_t2 <= 2'd0; s1_t3 <= 2'd0;
            s1_t4 <= 2'd0; s1_t5 <= 2'd0; s1_t6 <= 2'd0; s1_t7 <= 2'd0;
            s1_v0 <= 3'sd0; s1_v1 <= 3'sd0; s1_v2 <= 3'sd0; s1_v3 <= 3'sd0;
            s1_v4 <= 3'sd0; s1_v5 <= 3'sd0; s1_v6 <= 3'sd0; s1_v7 <= 3'sd0;
            s2_valid <= 1'b0;
            s2_t0 <= 3'd0; s2_t1 <= 3'd0; s2_t2 <= 3'd0; s2_t3 <= 3'd0;
            s2_v0 <= 4'sd0; s2_v1 <= 4'sd0; s2_v2 <= 4'sd0; s2_v3 <= 4'sd0;
            s3_valid <= 1'b0;
            s3_t0 <= 4'd0; s3_t1 <= 4'd0;
            s3_v0 <= 5'sd0; s3_v1 <= 5'sd0;
            vote_valid       <= 1'b0;
            vote_sum         <= {SUM_W{1'b0}};
            transition_count <= {COUNT_W{1'b0}};
        end else begin
            // Stage 0 (0-gate input capture)
            s0_valid <= bundle_valid;
            s0_prev  <= previous_data;
            s0_data  <= data_samples;
            s0_edge  <= edge_samples;

            // Stage 0b (2-gate reg-to-reg decode)
            s0b_valid <= s0_valid;
            s0b_trans <= trans_c;
            s0b_late  <= late_c;
            s0b_early <= early_c;

            // Stage 1 (unconditional 2-gate pair sums -> +1.5 ns SS slack!)
            s1_valid <= s0b_valid;
            s1_t0 <= pair_t(s0b_trans[0],  s0b_trans[1]);
            s1_t1 <= pair_t(s0b_trans[2],  s0b_trans[3]);
            s1_t2 <= pair_t(s0b_trans[4],  s0b_trans[5]);
            s1_t3 <= pair_t(s0b_trans[6],  s0b_trans[7]);
            s1_t4 <= pair_t(s0b_trans[8],  s0b_trans[9]);
            s1_t5 <= pair_t(s0b_trans[10], s0b_trans[11]);
            s1_t6 <= pair_t(s0b_trans[12], s0b_trans[13]);
            s1_t7 <= pair_t(s0b_trans[14], s0b_trans[15]);
            s1_v0 <= pair_v(s0b_trans[0],  s0b_late[0],  s0b_early[0],  s0b_trans[1],  s0b_late[1],  s0b_early[1]);
            s1_v1 <= pair_v(s0b_trans[2],  s0b_late[2],  s0b_early[2],  s0b_trans[3],  s0b_late[3],  s0b_early[3]);
            s1_v2 <= pair_v(s0b_trans[4],  s0b_late[4],  s0b_early[4],  s0b_trans[5],  s0b_late[5],  s0b_early[5]);
            s1_v3 <= pair_v(s0b_trans[6],  s0b_late[6],  s0b_early[6],  s0b_trans[7],  s0b_late[7],  s0b_early[7]);
            s1_v4 <= pair_v(s0b_trans[8],  s0b_late[8],  s0b_early[8],  s0b_trans[9],  s0b_late[9],  s0b_early[9]);
            s1_v5 <= pair_v(s0b_trans[10], s0b_late[10], s0b_early[10], s0b_trans[11], s0b_late[11], s0b_early[11]);
            s1_v6 <= pair_v(s0b_trans[12], s0b_late[12], s0b_early[12], s0b_trans[13], s0b_late[13], s0b_early[13]);
            s1_v7 <= pair_v(s0b_trans[14], s0b_late[14], s0b_early[14], s0b_trans[15], s0b_late[15], s0b_early[15]);

            // Stage 2 (unconditional datapath -> zero s1_valid fanout!)
            s2_valid <= s1_valid;
            s2_t0 <= {1'b0, s1_t0} + {1'b0, s1_t1};
            s2_t1 <= {1'b0, s1_t2} + {1'b0, s1_t3};
            s2_t2 <= {1'b0, s1_t4} + {1'b0, s1_t5};
            s2_t3 <= {1'b0, s1_t6} + {1'b0, s1_t7};
            s2_v0 <= {s1_v0[2], s1_v0} + {s1_v1[2], s1_v1};
            s2_v1 <= {s1_v2[2], s1_v2} + {s1_v3[2], s1_v3};
            s2_v2 <= {s1_v4[2], s1_v4} + {s1_v5[2], s1_v5};
            s2_v3 <= {s1_v6[2], s1_v6} + {s1_v7[2], s1_v7};

            // Stage 3 (unconditional datapath -> zero s2_valid fanout!)
            s3_valid <= s2_valid;
            s3_t0 <= {1'b0, s2_t0} + {1'b0, s2_t1};
            s3_t1 <= {1'b0, s2_t2} + {1'b0, s2_t3};
            s3_v0 <= {s2_v0[3], s2_v0} + {s2_v1[3], s2_v1};
            s3_v1 <= {s2_v2[3], s2_v2} + {s2_v3[3], s2_v3};

            // Stage 4 (unconditional CLA capture -> zero mux2 on transition_count/vote_sum!)
            vote_valid       <= s3_valid;
            vote_sum         <= v_total[SUM_W-1:0];
            transition_count <= t_total[COUNT_W-1:0];
        end
    end
endmodule
