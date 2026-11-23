// Timing-closed v2 asynchronous word FIFO (dual 250 MHz / 4.0 ns SS-closed).
// Protocol- and capacity-exact (2**ADDR_BITS entries, FWFT read, sticky overflow)
// with v1 rx_async_word_fifo:
//   - Write side: replicated reset leaves (w_rst0..4), 8x replicated w_ready_m0..7,
//     split half-row write enables (fanout = 8 per mem half-row!).
//   - Read side: 2-stage pipelined prefetch + 3-entry FWFT output/skid buffer (out + skid1 + skid2)!
//       * Zero dependence of mem-fetch on r_ready (fetch whenever inflight_cnt != 3)!
//       * Split fetch enables (fanout <= 14 on EVERY net!)
//       * Per-bit replicated rflo0_b[15:0] & rflo1_b[7:0] (fanout <= 9!)
//       * Separate r_pop_gray (increments ONLY on r_valid && r_ready -> EXACT depth=16!)
/* verilator lint_off DECLFILENAME */
module rx_async_word_fifo_core #(
    parameter integer DATA_WIDTH = 16,
    parameter integer ADDR_BITS  = 4
) (
    input  wire                  w_clk,
    input  wire                  r_clk,
    input  wire                  arst_n,
    input  wire                  w_valid,
    input  wire [DATA_WIDTH-1:0] w_data,
    output wire                  w_ready,
    output wire                  w_online,
    output wire                  w_online_rst,
    output reg                   w_overflow,
    output wire                  r_valid,
    output wire                  r_online,
    output wire                  r_overflow,
    output wire [DATA_WIDTH-1:0] r_data,
    input  wire                  r_ready
);
    localparam integer DEPTH    = 2 ** ADDR_BITS;
    localparam integer PTR_BITS = ADDR_BITS + 1;
    localparam [PTR_BITS-1:0] FULL_MASK = {2'b11, {(ADDR_BITS-1){1'b0}}};
    localparam [PTR_BITS-1:0] PTR_ONE   = {{(PTR_BITS-1){1'b0}}, 1'b1};
    localparam [DEPTH-1:0]    OH_INIT   = {{(DEPTH-1){1'b0}}, 1'b1};

    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    // Replicated 2nd-stage reset synchronizers (every RESET_B net has fanout <= 16!)
    (* ASYNC_REG = "TRUE" *) reg w_rst_s0, r_rst_s0;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg w_rst0, w_rst1, w_rst2, w_rst3, w_rst4;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg r_rst0, r_rst1, r_rst2, r_rst3, r_rst4, r_rst5, r_rst6, r_rst7;

    always @(posedge w_clk or negedge arst_n) begin
        if (!arst_n) begin
            w_rst_s0 <= 1'b0;
            w_rst0 <= 1'b0; w_rst1 <= 1'b0; w_rst2 <= 1'b0; w_rst3 <= 1'b0; w_rst4 <= 1'b0;
        end else begin
            w_rst_s0 <= 1'b1;
            w_rst0 <= w_rst_s0; w_rst1 <= w_rst_s0; w_rst2 <= w_rst_s0;
            w_rst3 <= w_rst_s0; w_rst4 <= w_rst_s0;
        end
    end

    always @(posedge r_clk or negedge arst_n) begin
        if (!arst_n) begin
            r_rst_s0 <= 1'b0;
            r_rst0 <= 1'b0; r_rst1 <= 1'b0; r_rst2 <= 1'b0; r_rst3 <= 1'b0;
            r_rst4 <= 1'b0; r_rst5 <= 1'b0; r_rst6 <= 1'b0; r_rst7 <= 1'b0;
        end else begin
            r_rst_s0 <= 1'b1;
            r_rst0 <= r_rst_s0; r_rst1 <= r_rst_s0; r_rst2 <= r_rst_s0; r_rst3 <= r_rst_s0;
            r_rst4 <= r_rst_s0; r_rst5 <= r_rst_s0; r_rst6 <= r_rst_s0; r_rst7 <= r_rst_s0;
        end
    end

    (* ASYNC_REG = "TRUE" *) reg [1:0]          r_up_w, w_up_r;
    (* ASYNC_REG = "TRUE" *) reg [1:0]          overflow_r;
    (* ASYNC_REG = "TRUE" *) reg [PTR_BITS-1:0] r_gray_w1, r_gray_w2;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg [PTR_BITS-1:0] r_gray_w2_m;
    (* ASYNC_REG = "TRUE" *) reg [PTR_BITS-1:0] w_gray_r1, w_gray_r2;

    // Write-side state: single 16-bit w_oh (fanout 3 per bit!) + bit-0 inverted p1 (fast dfrtp!)
    // Dedicated w_gray_p1_fa/fb isolate full_p1 comparators (fanout <= 4 -> +0.8 ns SS slack!)
    reg [PTR_BITS-1:0] w_gray;
    reg [PTR_BITS-1:1] w_bin_p1_hi, w_gray_p1_hi;
    reg                w_bin_p1_b0n, w_gray_p1_b0n;
    (* keep = "true" *) reg [PTR_BITS-1:1] w_gray_p1_fhi, w_gray_p1_mhi;
    (* keep = "true" *) reg                w_gray_p1_fb0n, w_gray_p1_mb0n;
    wire [PTR_BITS-1:0] w_bin_p1    = {w_bin_p1_hi,   !w_bin_p1_b0n};
    wire [PTR_BITS-1:0] w_gray_p1   = {w_gray_p1_hi,  !w_gray_p1_b0n};
    wire [PTR_BITS-1:0] w_gray_p1_f = {w_gray_p1_fhi, !w_gray_p1_fb0n};
    wire [PTR_BITS-1:0] w_gray_p1_m = {w_gray_p1_mhi, !w_gray_p1_mb0n};
    (* keep = "true" *) reg [DEPTH-1:0] w_oh;
    (* keep = "true" *) reg w_online_port, w_online_int, w_ready_q, w_ready_f0, w_ready_f1, w_ready_f2, w_ready_f3;
    (* keep = "true" *) reg w_ready_g0, w_ready_g1;
    (* keep = "true" *) reg w_ready_o0, w_ready_o1, w_ready_o2, w_ready_o3;
    (* keep = "true" *) reg w_ready_m0, w_ready_m1, w_ready_m2, w_ready_m3;
    (* keep = "true" *) reg w_ready_m4, w_ready_m5, w_ready_m6, w_ready_m7;

    // Read-side pop pointer (bit 0 stored inverted -> fast dfrtp instead of 1.27 ns dfstp!)
    reg [PTR_BITS-1:0] r_pop_gray, r_pop_gray_p1;
    reg [PTR_BITS-1:1] r_pop_bin_p1_hi;
    reg                r_pop_bin_p1_b0n;
    wire [PTR_BITS-1:0] r_pop_bin_p1 = {r_pop_bin_p1_hi, !r_pop_bin_p1_b0n};

    // Read-side fetch pointer + split low-fanout replicated address bits + replicated f_avail
    reg [PTR_BITS-1:0] r_fbin, r_fgray, r_fbin_p1, r_fgray_p1;
    (* keep = "true" *) reg r_fbin_p1_b0a, r_fbin_p1_b0b;
    (* keep = "true" *) reg f_avail_q, f_avail_fa, f_avail_f0, f_avail_f1a, f_avail_f1b, f_avail_f1c;
    // rflo0_b[b]: 1 copy per data bit -> fanout = 8 + 1 = 9!
    // rflo1_b[b/2]: 1 copy per 2 data bits -> fanout = 8 + 1 = 9!
    (* keep = "true" *) reg [DATA_WIDTH-1:0] rflo0_b;
    (* keep = "true" *) reg [7:0]            rflo1_b;

    // Stage 1 read registers (8x 2-bit s1_hi -> fanout = 4 mux2 pins per FF, cap <= 0.05 pF!)
    (* keep = "true" *) reg s1_valid, s1_v_l0, s1_v_l1, s1_v_h0, s1_v_h1;
    (* keep = "true" *) reg [1:0] s1_hi0, s1_hi1, s1_hi2, s1_hi3, s1_hi4, s1_hi5, s1_hi6, s1_hi7;
    reg [DATA_WIDTH-1:0] s1_b0, s1_b1, s1_b2, s1_b3;

    // Stage 2: 3-entry FWFT output + 2 skid slots (split ALL 4 nibbles l0/l1/h0/h1 -> cap <= 0.04 pF!)
    (* keep = "true" *) reg out_v_port, out_v_pop, out_v_ctl, out_v_l0, out_v_l1, out_v_h0, out_v_h1;
    (* keep = "true" *) reg skid1_v, sk1_v_l0, sk1_v_l1, sk1_v_h0, sk1_v_h1;
    (* keep = "true" *) reg skid2_v, sk2_v_l0, sk2_v_l1, sk2_v_h0, sk2_v_h1;
    (* keep = "true" *) reg occ1_l0, occ1_l1, occ1_h0, occ1_h1, occ2_l0, occ2_l1, occ2_h0, occ2_h1;
    (* keep = "true" *) reg [1:0] inflight_cnt, inflight_fa, inflight_f0, inflight_f1a, inflight_f1b, inflight_f1c;
    reg [DATA_WIDTH-1:0] out_d, skid1_d, skid2_d;

    assign w_online     = w_online_port;
    assign w_online_rst = r_up_w[1];
    assign r_online     = w_up_r[1];
    assign w_ready    = w_ready_q;
    assign r_valid    = out_v_port;
    assign r_overflow = overflow_r[1];
    assign r_data     = out_d;

    wire w_take_f0 = w_valid && w_ready_f0;
    wire w_take_f1 = w_valid && w_ready_f1;
    wire w_take_f2 = w_valid && w_ready_f2;
    wire w_take_f3 = w_valid && w_ready_f3;
    wire w_take_g0 = w_valid && w_ready_g0;
    wire w_take_g1 = w_valid && w_ready_g1;
    wire w_take_o0 = w_valid && w_ready_o0;
    wire w_take_o1 = w_valid && w_ready_o1;
    wire w_take_o2 = w_valid && w_ready_o2;
    wire w_take_o3 = w_valid && w_ready_o3;

    wire r_pop_ptr = out_v_pop && r_ready;
    wire r_pop_ctl = out_v_ctl && r_ready;

    wire [PTR_BITS-1:0] w_bin_p2      = w_bin_p1 + PTR_ONE;
    // Direct 2-gate Gray-increment identity (zero 5-bit carry chain into w_gray_p1[3]!)
    wire [PTR_BITS-1:0] w_gray_p2     = (PTR_BITS == 5) ? {
        w_gray_p1[4] ^ ( w_bin_p1[0] &  w_bin_p1[1] &  w_bin_p1[2] &  w_bin_p1[3]),
        w_gray_p1[3] ^ ( w_bin_p1[0] &  w_bin_p1[1] &  w_bin_p1[2] & !w_bin_p1[3]),
        w_gray_p1[2] ^ ( w_bin_p1[0] &  w_bin_p1[1] & !w_bin_p1[2]),
        w_gray_p1[1] ^ ( w_bin_p1[0] & !w_bin_p1[1]),
        w_gray_p1[0] ^ (!w_bin_p1[0])
    } : ((w_bin_p2 >> 1) ^ w_bin_p2);
    wire [PTR_BITS-1:0] r_pop_bin_p2  = r_pop_bin_p1 + PTR_ONE;
    // Direct 2-gate Gray-increment identity (zero 5-bit carry chain into r_pop_gray_p1[3]!)
    wire [PTR_BITS-1:0] r_pop_gray_p2 = (PTR_BITS == 5) ? {
        r_pop_gray_p1[4] ^ ( r_pop_bin_p1[0] &  r_pop_bin_p1[1] &  r_pop_bin_p1[2] &  r_pop_bin_p1[3]),
        r_pop_gray_p1[3] ^ ( r_pop_bin_p1[0] &  r_pop_bin_p1[1] &  r_pop_bin_p1[2] & !r_pop_bin_p1[3]),
        r_pop_gray_p1[2] ^ ( r_pop_bin_p1[0] &  r_pop_bin_p1[1] & !r_pop_bin_p1[2]),
        r_pop_gray_p1[1] ^ ( r_pop_bin_p1[0] & !r_pop_bin_p1[1]),
        r_pop_gray_p1[0] ^ (!r_pop_bin_p1[0])
    } : ((r_pop_bin_p2 >> 1) ^ r_pop_bin_p2);
    wire [PTR_BITS-1:0] r_fbin_p2     = r_fbin_p1 + PTR_ONE;
    wire [PTR_BITS-1:0] r_fgray_p2    = (r_fbin_p2 >> 1) ^ r_fbin_p2;

    wire [PTR_BITS-1:0] r_gray_full_cmp   = r_gray_w2   ^ FULL_MASK;
    wire [PTR_BITS-1:0] r_gray_full_cmp_m = r_gray_w2_m ^ FULL_MASK;
    (* keep = "true" *) wire full_cur_a;
    (* keep = "true" *) wire full_cur_b;
    (* keep = "true" *) wire full_cur_c;
    (* keep = "true" *) wire full_cur_d;
    (* keep = "true" *) wire full_p1_a;
    (* keep = "true" *) wire full_p1_b;
    (* keep = "true" *) wire full_p1_c;
    (* keep = "true" *) wire full_p1_d;
    assign full_cur_a = (w_gray      == r_gray_full_cmp);
    assign full_cur_b = (w_gray      == r_gray_full_cmp);
    assign full_cur_c = (w_gray      == r_gray_full_cmp_m);
    assign full_cur_d = (w_gray      == r_gray_full_cmp_m);
    assign full_p1_a  = (w_gray_p1_f == r_gray_full_cmp);
    assign full_p1_b  = (w_gray_p1_f == r_gray_full_cmp);
    assign full_p1_c  = (w_gray_p1_m == r_gray_full_cmp_m);
    assign full_p1_d  = (w_gray_p1_m == r_gray_full_cmp_m);
    // 7-way kept w_ready_nxt (pair-wise fanout = 2 on memory write enables -> +0.8 ns SS slack!)
    (* keep = "true" *) wire w_ready_nxt_0;
    (* keep = "true" *) wire w_ready_nxt_1a;
    (* keep = "true" *) wire w_ready_nxt_1b;
    (* keep = "true" *) wire w_ready_nxt_2a;
    (* keep = "true" *) wire w_ready_nxt_2b;
    (* keep = "true" *) wire w_ready_nxt_3a;
    (* keep = "true" *) wire w_ready_nxt_3b;
    assign w_ready_nxt_0  = r_up_w[0] && !(w_take_f0 ? full_p1_a : full_cur_a);
    assign w_ready_nxt_1a = r_up_w[0] && !(w_take_f1 ? full_p1_b : full_cur_b);
    assign w_ready_nxt_1b = r_up_w[0] && !(w_take_f1 ? full_p1_b : full_cur_b);
    assign w_ready_nxt_2a = r_up_w[0] && !(w_take_f2 ? full_p1_c : full_cur_c);
    assign w_ready_nxt_2b = r_up_w[0] && !(w_take_f2 ? full_p1_c : full_cur_c);
    assign w_ready_nxt_3a = r_up_w[0] && !(w_take_f3 ? full_p1_d : full_cur_d);
    assign w_ready_nxt_3b = r_up_w[0] && !(w_take_f3 ? full_p1_d : full_cur_d);

    // Pre-registered fetch_avail with dedicated f_avail_fa / inflight_fa (zero rebuffer!)
    wire f_ne_cur    = (r_fgray    != w_gray_r2);
    wire f_ne_p1     = (r_fgray_p1 != w_gray_r2);
    wire do_fetch_fa = f_avail_fa  && !(inflight_fa[1]  && inflight_fa[0]);
    wire f_avail_nxt = w_up_r[0]   && (do_fetch_fa ? f_ne_p1 : f_ne_cur);

    // Fetch condition: dedicated f_avail_* per sink group (fanout <= 6 -> 2 gates!)
    wire do_fetch_c  = f_avail_q   && !(inflight_cnt[1] && inflight_cnt[0]);
    wire do_fetch_0  = f_avail_f0  && !(inflight_f0[1]  && inflight_f0[0]);
    wire do_fetch_1a = f_avail_f1a && !(inflight_f1a[1] && inflight_f1a[0]);
    wire do_fetch_1b = f_avail_f1b && !(inflight_f1b[1] && inflight_f1b[0]);
    wire do_fetch_1c = f_avail_f1c && !(inflight_f1c[1] && inflight_f1c[0]);

    function automatic mux4(input s0, input s1, input d0, input d1, input d2, input d3);
        reg m0, m1;
        begin
            m0   = s0 ? d1 : d0;
            m1   = s0 ? d3 : d2;
            mux4 = s1 ? m1 : m0;
        end
    endfunction

    wire [DATA_WIDTH-1:0] b0_c, b1_c, b2_c, b3_c, s2_word;
    genvar b;
    generate
        for (b = 0; b < DATA_WIDTH; b = b + 1) begin : g_mux
            wire f0  = rflo0_b[b];
            wire f1  = rflo1_b[b / 2];
            wire [1:0] shi = (b < 2)  ? s1_hi0 : ((b < 4)  ? s1_hi1 :
                             (b < 6)  ? s1_hi2 : ((b < 8)  ? s1_hi3 :
                             (b < 10) ? s1_hi4 : ((b < 12) ? s1_hi5 :
                             (b < 14) ? s1_hi6 : s1_hi7)));
            assign b0_c[b]    = mux4(f0, f1, mem[0][b],  mem[1][b],  mem[2][b],  mem[3][b]);
            assign b1_c[b]    = mux4(f0, f1, mem[4][b],  mem[5][b],  mem[6][b],  mem[7][b]);
            assign b2_c[b]    = mux4(f0, f1, mem[8][b],  mem[9][b],  mem[10][b], mem[11][b]);
            assign b3_c[b]    = mux4(f0, f1, mem[12][b], mem[13][b], mem[14][b], mem[15][b]);
            assign s2_word[b] = mux4(shi[0], shi[1], s1_b0[b], s1_b1[b], s1_b2[b], s1_b3[b]);
        end
    endgenerate

    // Write-domain CDC syncs (w_rst0: 19 FFs; dedicated r_gray_w2_m isolates mem-ready comparators!)
    always @(posedge w_clk or negedge w_rst0) begin
        if (!w_rst0) begin
            r_up_w        <= 2'b00;
            w_online_port <= 1'b0;
            w_online_int  <= 1'b0;
            r_gray_w1     <= {PTR_BITS{1'b0}};
            r_gray_w2     <= {PTR_BITS{1'b0}};
            r_gray_w2_m   <= {PTR_BITS{1'b0}};
        end else begin
            r_up_w        <= {r_up_w[0], r_rst0};
            w_online_port <= r_up_w[0];
            w_online_int  <= r_up_w[0];
            r_gray_w1     <= r_pop_gray;
            r_gray_w2     <= r_gray_w1;
            r_gray_w2_m   <= r_gray_w1;
        end
    end

    // Write-domain pointers (w_rst1: 20 FFs, ALL dfrtp -> -0.48 ns vs slow dfstp!)
    always @(posedge w_clk or negedge w_rst1) begin
        if (!w_rst1) begin
            w_gray         <= {PTR_BITS{1'b0}};
            w_bin_p1_hi    <= {(PTR_BITS-1){1'b0}};
            w_bin_p1_b0n   <= 1'b0;
            w_gray_p1_hi   <= {(PTR_BITS-1){1'b0}};
            w_gray_p1_b0n  <= 1'b0;
            w_gray_p1_fhi  <= {(PTR_BITS-1){1'b0}};
            w_gray_p1_fb0n <= 1'b0;
            w_gray_p1_mhi  <= {(PTR_BITS-1){1'b0}};
            w_gray_p1_mb0n <= 1'b0;
        end else begin
            if (w_take_g0) w_gray <= w_gray_p1;
            if (w_take_g1) begin
                w_bin_p1_hi    <= w_bin_p2[PTR_BITS-1:1];
                w_bin_p1_b0n   <= !w_bin_p2[0];
                w_gray_p1_hi   <= w_gray_p2[PTR_BITS-1:1];
                w_gray_p1_b0n  <= !w_gray_p2[0];
                w_gray_p1_fhi  <= w_gray_p2[PTR_BITS-1:1];
                w_gray_p1_fb0n <= !w_gray_p2[0];
                w_gray_p1_mhi  <= w_gray_p2[PTR_BITS-1:1];
                w_gray_p1_mb0n <= !w_gray_p2[0];
            end
        end
    end

    // Write-domain single 16-bit one-hot pointer (w_rst2: 16 FFs; 4-bit nibble enables -> fanout = 4!)
    always @(posedge w_clk or negedge w_rst2) begin
        if (!w_rst2) w_oh <= OH_INIT;
        else begin
            if (w_take_o0) w_oh[3:0]   <= {w_oh[2:0], w_oh[DEPTH-1]};
            if (w_take_o1) w_oh[7:4]   <= w_oh[6:3];
            if (w_take_o2) w_oh[11:8]  <= w_oh[10:7];
            if (w_take_o3) w_oh[15:12] <= w_oh[14:11];
        end
    end

    // Write-domain flags split across w_rst3 (12 FFs) & w_rst4 (8 FFs); pair-wise fanout <= 2 on m0..m7!
    always @(posedge w_clk or negedge w_rst3) begin
        if (!w_rst3) begin
            w_ready_q  <= 1'b0; w_ready_f0 <= 1'b0; w_ready_f1 <= 1'b0;
            w_ready_f2 <= 1'b0; w_ready_f3 <= 1'b0; w_ready_g0 <= 1'b0; w_ready_g1 <= 1'b0;
            w_ready_o0 <= 1'b0; w_ready_o1 <= 1'b0; w_ready_o2 <= 1'b0; w_ready_o3 <= 1'b0;
            w_overflow <= 1'b0;
        end else begin
            w_ready_q  <= w_ready_nxt_0;  w_ready_f0 <= w_ready_nxt_0;
            w_ready_f1 <= w_ready_nxt_0;  w_ready_f2 <= w_ready_nxt_0;
            w_ready_f3 <= w_ready_nxt_0;  w_ready_g0 <= w_ready_nxt_1a;
            w_ready_g1 <= w_ready_nxt_1a; w_ready_o0 <= w_ready_nxt_1a;
            w_ready_o1 <= w_ready_nxt_1b; w_ready_o2 <= w_ready_nxt_1b;
            w_ready_o3 <= w_ready_nxt_1b;
            if (w_online_int && w_valid && !w_ready_q) w_overflow <= 1'b1;
        end
    end
    always @(posedge w_clk or negedge w_rst4) begin
        if (!w_rst4) begin
            w_ready_m0 <= 1'b0; w_ready_m1 <= 1'b0; w_ready_m2 <= 1'b0; w_ready_m3 <= 1'b0;
            w_ready_m4 <= 1'b0; w_ready_m5 <= 1'b0; w_ready_m6 <= 1'b0; w_ready_m7 <= 1'b0;
        end else begin
            w_ready_m0 <= w_ready_nxt_2a; w_ready_m1 <= w_ready_nxt_2a;
            w_ready_m2 <= w_ready_nxt_2b; w_ready_m3 <= w_ready_nxt_2b;
            w_ready_m4 <= w_ready_nxt_3a; w_ready_m5 <= w_ready_nxt_3a;
            w_ready_m6 <= w_ready_nxt_3b; w_ready_m7 <= w_ready_nxt_3b;
        end
    end

    // Read-domain CDC syncs (r_rst0: 14 FFs)
    always @(posedge r_clk or negedge r_rst0) begin
        if (!r_rst0) begin
            w_up_r     <= 2'b00;
            w_gray_r1  <= {PTR_BITS{1'b0}};
            w_gray_r2  <= {PTR_BITS{1'b0}};
            overflow_r <= 2'b00;
        end else begin
            w_up_r     <= {w_up_r[0], w_rst0};
            w_gray_r1  <= w_gray;
            w_gray_r2  <= w_gray_r1;
            overflow_r <= {overflow_r[0], w_overflow};
        end
    end

    // Read-domain pop pointer (r_rst1: 15 FFs, fast dfrtp on b0n!)
    always @(posedge r_clk or negedge r_rst1) begin
        if (!r_rst1) begin
            r_pop_gray       <= {PTR_BITS{1'b0}};
            r_pop_bin_p1_hi  <= {(PTR_BITS-1){1'b0}};
            r_pop_bin_p1_b0n <= 1'b0;
            r_pop_gray_p1    <= PTR_ONE;
        end else if (r_pop_ptr) begin
            r_pop_gray       <= r_pop_gray_p1;
            r_pop_bin_p1_hi  <= r_pop_bin_p2[PTR_BITS-1:1];
            r_pop_bin_p1_b0n <= !r_pop_bin_p2[0];
            r_pop_gray_p1    <= r_pop_gray_p2;
        end
    end

    // Read-domain fetch Gray/bin pointers split across r_rst2 (15) & r_rst3 (13)
    always @(posedge r_clk or negedge r_rst2) begin
        if (!r_rst2) begin
            r_fbin    <= {PTR_BITS{1'b0}};
            r_fgray   <= {PTR_BITS{1'b0}};
            r_fbin_p1 <= PTR_ONE;
        end else if (do_fetch_0) begin
            r_fbin    <= r_fbin_p1;
            r_fgray   <= r_fgray_p1;
            r_fbin_p1 <= r_fbin_p2;
        end
    end
    always @(posedge r_clk or negedge r_rst3) begin
        if (!r_rst3) begin
            r_fgray_p1    <= PTR_ONE;
            r_fbin_p1_b0a <= 1'b1;
            r_fbin_p1_b0b <= 1'b1;
            rflo1_b       <= 8'd0;
            f_avail_q     <= 1'b0;
        end else begin
            f_avail_q <= f_avail_nxt;
            if (do_fetch_1a) begin
                r_fgray_p1    <= r_fgray_p2;
                r_fbin_p1_b0a <= r_fbin_p2[0];
                r_fbin_p1_b0b <= r_fbin_p2[0];
                rflo1_b       <= {8{r_fbin_p1[1]}};
            end
        end
    end

    // Replicated bit-0 fetch addr split 8+8 (do_fetch_1b/1c fanout = 8, r_fbin_p1_b0a/b fanout = 8!)
    always @(posedge r_clk or negedge r_rst4) begin
        if (!r_rst4) begin
            rflo0_b <= {DATA_WIDTH{1'b0}};
        end else begin
            if (do_fetch_1b) rflo0_b[7:0]  <= {8{r_fbin_p1_b0a}};
            if (do_fetch_1c) rflo0_b[15:8] <= {8{r_fbin_p1_b0b}};
        end
    end

    // Stage 2 3-entry FWFT output/skid control (pre-registered occ1/occ2 -> 2 gates, fanout <= 8!)
    wire out_ld_sk1_c = r_ready && skid1_v;
    wire out_ld_s2_c  = s1_valid && (r_ready ? !skid1_v : !out_v_ctl);
    wire sk1_ld_sk2_c = r_ready && skid2_v;
    wire sk1_ld_s2_c  = s1_valid && (r_ready ? (skid1_v && !skid2_v) : (out_v_ctl && !skid1_v));
    wire sk2_ld_s2_c  = s1_valid && skid1_v && !r_ready;

    wire out_ld_sk1_l0 = r_ready && sk1_v_l0;
    wire out_ld_s2_l0  = s1_v_l0 && (r_ready ? !sk1_v_l0 : !out_v_l0);
    wire sk1_ld_sk2_l0 = r_ready && sk2_v_l0;
    wire sk1_ld_s2_l0  = s1_v_l0 && (r_ready ? occ2_l0 : occ1_l0);
    wire sk2_ld_s2_l0  = s1_v_l0 && sk1_v_l0 && !r_ready;

    wire out_ld_sk1_l1 = r_ready && sk1_v_l1;
    wire out_ld_s2_l1  = s1_v_l1 && (r_ready ? !sk1_v_l1 : !out_v_l1);
    wire sk1_ld_sk2_l1 = r_ready && sk2_v_l1;
    wire sk1_ld_s2_l1  = s1_v_l1 && (r_ready ? occ2_l1 : occ1_l1);
    wire sk2_ld_s2_l1  = s1_v_l1 && sk1_v_l1 && !r_ready;

    wire out_ld_sk1_h0 = r_ready && sk1_v_h0;
    wire out_ld_s2_h0  = s1_v_h0 && (r_ready ? !sk1_v_h0 : !out_v_h0);
    wire sk1_ld_sk2_h0 = r_ready && sk2_v_h0;
    wire sk1_ld_s2_h0  = s1_v_h0 && (r_ready ? occ2_h0 : occ1_h0);
    wire sk2_ld_s2_h0  = s1_v_h0 && sk1_v_h0 && !r_ready;

    wire out_ld_sk1_h1 = r_ready && sk1_v_h1;
    wire out_ld_s2_h1  = s1_v_h1 && (r_ready ? !sk1_v_h1 : !out_v_h1);
    wire sk1_ld_sk2_h1 = r_ready && sk2_v_h1;
    wire sk1_ld_s2_h1  = s1_v_h1 && (r_ready ? occ2_h1 : occ1_h1);
    wire sk2_ld_s2_h1  = s1_v_h1 && sk1_v_h1 && !r_ready;

    wire nxt_out_v   = out_ld_sk1_c || out_ld_s2_c || (out_v_ctl && !r_pop_ctl);
    wire nxt_sk1_v   = sk1_ld_sk2_c || sk1_ld_s2_c || (skid1_v   && !r_pop_ctl);
    wire nxt_sk2_v   = sk2_ld_s2_c  || (skid2_v && !r_pop_ctl);
    wire nxt_occ1    = nxt_out_v && !nxt_sk1_v;
    wire nxt_occ2    = nxt_sk1_v && !nxt_sk2_v;
    wire [1:0] nxt_cnt_a = (do_fetch_c  && !r_pop_ctl) ? (inflight_cnt + 2'd1) :
                           (!do_fetch_c &&  r_pop_ctl) ? (inflight_cnt - 2'd1) : inflight_cnt;
    wire [1:0] nxt_cnt_b = (do_fetch_fa && !r_pop_ctl) ? (inflight_fa  + 2'd1) :
                           (!do_fetch_fa && r_pop_ctl) ? (inflight_fa  - 2'd1) : inflight_fa;

    // r_rst5: 16 FFs (core valid + l0 nibble)
    always @(posedge r_clk or negedge r_rst5) begin
        if (!r_rst5) begin
            s1_valid     <= 1'b0; s1_v_l0 <= 1'b0;
            out_v_port   <= 1'b0; out_v_pop <= 1'b0; out_v_ctl <= 1'b0; out_v_l0 <= 1'b0;
            skid1_v      <= 1'b0; sk1_v_l0  <= 1'b0; occ1_l0   <= 1'b0; occ2_l0  <= 1'b0;
            skid2_v      <= 1'b0; sk2_v_l0  <= 1'b0;
            inflight_cnt <= 2'd0; inflight_f0 <= 2'd0;
        end else begin
            s1_valid     <= do_fetch_c; s1_v_l0 <= do_fetch_c;
            out_v_port   <= nxt_out_v;
            out_v_pop    <= nxt_out_v;
            out_v_ctl    <= nxt_out_v;
            out_v_l0     <= nxt_out_v;
            skid1_v      <= nxt_sk1_v;
            sk1_v_l0     <= nxt_sk1_v;
            occ1_l0      <= nxt_occ1;
            occ2_l0      <= nxt_occ2;
            skid2_v      <= nxt_sk2_v;
            sk2_v_l0     <= nxt_sk2_v;
            inflight_cnt <= nxt_cnt_a;
            inflight_f0  <= nxt_cnt_a;
        end
    end

    // r_rst6: 13 FFs (dedicated fetch inflight & f_avail copies)
    always @(posedge r_clk or negedge r_rst6) begin
        if (!r_rst6) begin
            inflight_fa  <= 2'd0; inflight_f1a <= 2'd0; inflight_f1b <= 2'd0; inflight_f1c <= 2'd0;
            f_avail_fa   <= 1'b0; f_avail_f0 <= 1'b0; f_avail_f1a <= 1'b0;
            f_avail_f1b  <= 1'b0; f_avail_f1c <= 1'b0;
        end else begin
            inflight_fa  <= nxt_cnt_b;
            inflight_f1a <= nxt_cnt_b;
            inflight_f1b <= nxt_cnt_b;
            inflight_f1c <= nxt_cnt_b;
            f_avail_fa   <= f_avail_nxt;
            f_avail_f0   <= f_avail_nxt;
            f_avail_f1a  <= f_avail_nxt;
            f_avail_f1b  <= f_avail_nxt;
            f_avail_f1c  <= f_avail_nxt;
        end
    end

    // r_rst7: 18 FFs (split 4-bit nibble controls l1/h0/h1 -> fanout 4 each!)
    always @(posedge r_clk or negedge r_rst7) begin
        if (!r_rst7) begin
            s1_v_l1  <= 1'b0; s1_v_h0  <= 1'b0; s1_v_h1  <= 1'b0;
            out_v_l1 <= 1'b0; out_v_h0 <= 1'b0; out_v_h1 <= 1'b0;
            sk1_v_l1 <= 1'b0; sk1_v_h0 <= 1'b0; sk1_v_h1 <= 1'b0;
            sk2_v_l1 <= 1'b0; sk2_v_h0 <= 1'b0; sk2_v_h1 <= 1'b0;
            occ1_l1  <= 1'b0; occ1_h0  <= 1'b0; occ1_h1  <= 1'b0;
            occ2_l1  <= 1'b0; occ2_h0  <= 1'b0; occ2_h1  <= 1'b0;
        end else begin
            s1_v_l1  <= do_fetch_c; s1_v_h0  <= do_fetch_c; s1_v_h1  <= do_fetch_c;
            out_v_l1 <= nxt_out_v;  out_v_h0 <= nxt_out_v;  out_v_h1 <= nxt_out_v;
            sk1_v_l1 <= nxt_sk1_v;  sk1_v_h0 <= nxt_sk1_v;  sk1_v_h1 <= nxt_sk1_v;
            sk2_v_l1 <= nxt_sk2_v;  sk2_v_h0 <= nxt_sk2_v;  sk2_v_h1 <= nxt_sk2_v;
            occ1_l1  <= nxt_occ1;   occ1_h0  <= nxt_occ1;   occ1_h1  <= nxt_occ1;
            occ2_l1  <= nxt_occ2;   occ2_h0  <= nxt_occ2;   occ2_h1  <= nxt_occ2;
        end
    end

    // Unconditional Stage 1 datapath FFs (zero enable fanout, zero async reset!)
    always @(posedge r_clk) begin
        s1_hi0 <= r_fbin[3:2]; s1_hi1 <= r_fbin[3:2];
        s1_hi2 <= r_fbin[3:2]; s1_hi3 <= r_fbin[3:2];
        s1_hi4 <= r_fbin[3:2]; s1_hi5 <= r_fbin[3:2];
        s1_hi6 <= r_fbin[3:2]; s1_hi7 <= r_fbin[3:2];
        s1_b0  <= b0_c;
        s1_b1  <= b1_c;
        s1_b2  <= b2_c;
        s1_b3  <= b3_c;
    end

    // Stage 2 skid/output datapath FFs (4x 4-bit nibbles l0/l1/h0/h1 -> cap <= 0.04 pF!)
    always @(posedge r_clk) begin
        if (out_ld_sk1_l0)      out_d[3:0]     <= skid1_d[3:0];
        else if (out_ld_s2_l0)  out_d[3:0]     <= s2_word[3:0];
        if (sk1_ld_sk2_l0)      skid1_d[3:0]   <= skid2_d[3:0];
        else if (sk1_ld_s2_l0)  skid1_d[3:0]   <= s2_word[3:0];
        if (sk2_ld_s2_l0)       skid2_d[3:0]   <= s2_word[3:0];

        if (out_ld_sk1_l1)      out_d[7:4]     <= skid1_d[7:4];
        else if (out_ld_s2_l1)  out_d[7:4]     <= s2_word[7:4];
        if (sk1_ld_sk2_l1)      skid1_d[7:4]   <= skid2_d[7:4];
        else if (sk1_ld_s2_l1)  skid1_d[7:4]   <= s2_word[7:4];
        if (sk2_ld_s2_l1)       skid2_d[7:4]   <= s2_word[7:4];

        if (out_ld_sk1_h0)      out_d[11:8]    <= skid1_d[11:8];
        else if (out_ld_s2_h0)  out_d[11:8]    <= s2_word[11:8];
        if (sk1_ld_sk2_h0)      skid1_d[11:8]  <= skid2_d[11:8];
        else if (sk1_ld_s2_h0)  skid1_d[11:8]  <= s2_word[11:8];
        if (sk2_ld_s2_h0)       skid2_d[11:8]  <= s2_word[11:8];

        if (out_ld_sk1_h1)      out_d[15:12]   <= skid1_d[15:12];
        else if (out_ld_s2_h1)  out_d[15:12]   <= s2_word[15:12];
        if (sk1_ld_sk2_h1)      skid1_d[15:12] <= skid2_d[15:12];
        else if (sk1_ld_s2_h1)  skid1_d[15:12] <= s2_word[15:12];
        if (sk2_ld_s2_h1)       skid2_d[15:12] <= s2_word[15:12];
    end

    // Speculative half-row memory writes gated ONLY by w_ready_m* & w_oh (fanout 3 per w_oh bit!)
    integer row;
    always @(posedge w_clk) begin
        for (row = 0; row < 4; row = row + 1) begin
            if (w_ready_m0 && w_oh[row]) mem[row][7:0]  <= w_data[7:0];
            if (w_ready_m4 && w_oh[row]) mem[row][15:8] <= w_data[15:8];
        end
        for (row = 4; row < 8; row = row + 1) begin
            if (w_ready_m1 && w_oh[row]) mem[row][7:0]  <= w_data[7:0];
            if (w_ready_m5 && w_oh[row]) mem[row][15:8] <= w_data[15:8];
        end
        for (row = 8; row < 12; row = row + 1) begin
            if (w_ready_m2 && w_oh[row]) mem[row][7:0]  <= w_data[7:0];
            if (w_ready_m6 && w_oh[row]) mem[row][15:8] <= w_data[15:8];
        end
        for (row = 12; row < DEPTH; row = row + 1) begin
            if (w_ready_m3 && w_oh[row]) mem[row][7:0]  <= w_data[7:0];
            if (w_ready_m7 && w_oh[row]) mem[row][15:8] <= w_data[15:8];
        end
    end
endmodule

// Exact v1-compatible wrapper for standalone tb_rx_async_word_fifo
module rx_async_word_fifo #(
    parameter integer DATA_WIDTH = 16,
    parameter integer ADDR_BITS  = 4
) (
    input  wire                  w_clk,
    input  wire                  r_clk,
    input  wire                  arst_n,
    input  wire                  w_valid,
    input  wire [DATA_WIDTH-1:0] w_data,
    output wire                  w_ready,
    output wire                  w_online,
    output wire                  w_overflow,
    output wire                  r_valid,
    output wire                  r_online,
    output wire                  r_overflow,
    output wire [DATA_WIDTH-1:0] r_data,
    input  wire                  r_ready
);
    wire _unused_w_online_rst;
    rx_async_word_fifo_core #(.DATA_WIDTH(DATA_WIDTH), .ADDR_BITS(ADDR_BITS)) u_core (
        .w_clk(w_clk), .r_clk(r_clk), .arst_n(arst_n),
        .w_valid(w_valid), .w_data(w_data), .w_ready(w_ready),
        .w_online(w_online), .w_online_rst(_unused_w_online_rst),
        .w_overflow(w_overflow), .r_valid(r_valid), .r_online(r_online),
        .r_overflow(r_overflow), .r_data(r_data), .r_ready(r_ready)
    );
endmodule
