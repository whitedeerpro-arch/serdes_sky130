// Compact, timing-closed v3.3 asynchronous word FIFO (dual 250 MHz / 4.0 ns ss_n40C_1v60 + 5% OCV).
// Protocol- and capacity-exact (2**ADDR_BITS entries, FWFT read, sticky overflow):
//   - D-C1: Strictly single-fanout 1st-stage CDC synchronizer FFs (zero split-metastability!):
//       r_up_w[0] -> ONLY r_up_w[1];  w_up_r[0] -> ONLY w_up_r[1];
//       r_gray_w1 -> ONLY r_gray_w2 -> r_gray_w3_f/m (with FULL_MASK pre-XORed in register, 0 extra latency!);
//       w_gray_r1 -> ONLY w_gray_r2;  overflow_r[0] -> ONLY overflow_r[1];
//       w_rst_s0  -> ONLY w_rst_s1;   r_rst_s0 -> ONLY r_rst_s1.
//   - D-H3: Single shared per-domain reset synchronizer exported via w_rst_out/r_rst_out;
//           M2 w_valid-gated half-row memory writes (w_ready_m0..7).
//   - Compact footprint (~v3.2 cell count): inverted bit-0 fast dfrtp pointers (zero slow dfstp!),
//     balanced 8:1 Stage-1 + 2:1 Stage-2 read mux, 3-entry FWFT output/skid buffer.
/* verilator lint_off DECLFILENAME */
module rx_async_word_fifo_core #(
    parameter integer DATA_WIDTH = 16,
    parameter integer ADDR_BITS  = 4
) (
    input  wire                  w_clk,
    input  wire                  r_clk,
    input  wire                  arst_n,
    input  wire                  w_valid,
    input  wire                  w_valid_m0,
    input  wire                  w_valid_m1,
    input  wire                  w_valid_m2,
    input  wire                  w_valid_m3,
    input  wire [DATA_WIDTH-1:0] w_data,
    output wire                  w_ready,
    output wire                  w_online,
    output wire                  w_online_rst,
    output wire                  w_rst_out,
    output reg                   w_overflow,
    output wire                  r_valid,
    output wire                  r_online,
    output wire                  r_rst_out,
    output wire                  r_overflow,
    output wire [DATA_WIDTH-1:0] r_data,
    input  wire                  r_ready
);
    localparam integer DEPTH    = 2 ** ADDR_BITS;
    localparam integer PTR_BITS = ADDR_BITS + 1;
    localparam [PTR_BITS-1:0] FULL_MASK = {2'b11, {(ADDR_BITS-1){1'b0}}};
    localparam [PTR_BITS-1:0] PTR_ONE   = {{(PTR_BITS-1){1'b0}}, 1'b1};

    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    // Single per-domain 2-stage reset synchronizer (s0 -> single s1 -> low-fanout leaf resets)
    (* ASYNC_REG = "TRUE", keep = "true" *) reg w_rst_s0, w_rst_s1, r_rst_s0, r_rst_s1;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg w_rst0, w_rst1, w_rst2, w_rst3, w_rst4, w_rst_ext;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg r_rst0, r_rst1, r_rst2, r_rst3, r_rst4, r_rst5, r_rst6, r_rst7, r_rst_ext;

    assign w_rst_out = w_rst_ext;
    assign r_rst_out = r_rst_ext;

    always @(posedge w_clk or negedge arst_n) begin
        if (!arst_n) begin
            w_rst_s0 <= 1'b0;
            w_rst_s1 <= 1'b0;
            w_rst0 <= 1'b0; w_rst1 <= 1'b0; w_rst2 <= 1'b0; w_rst3 <= 1'b0; w_rst4 <= 1'b0; w_rst_ext <= 1'b0;
        end else begin
            w_rst_s0 <= 1'b1;
            w_rst_s1 <= w_rst_s0;
            w_rst0 <= w_rst_s1; w_rst1 <= w_rst_s1; w_rst2 <= w_rst_s1;
            w_rst3 <= w_rst_s1; w_rst4 <= w_rst_s1; w_rst_ext <= w_rst_s1;
        end
    end

    always @(posedge r_clk or negedge arst_n) begin
        if (!arst_n) begin
            r_rst_s0 <= 1'b0;
            r_rst_s1 <= 1'b0;
            r_rst0 <= 1'b0; r_rst1 <= 1'b0; r_rst2 <= 1'b0; r_rst3 <= 1'b0;
            r_rst4 <= 1'b0; r_rst5 <= 1'b0; r_rst6 <= 1'b0; r_rst7 <= 1'b0; r_rst_ext <= 1'b0;
        end else begin
            r_rst_s0 <= 1'b1;
            r_rst_s1 <= r_rst_s0;
            r_rst0 <= r_rst_s1; r_rst1 <= r_rst_s1; r_rst2 <= r_rst_s1; r_rst3 <= r_rst_s1;
            r_rst4 <= r_rst_s1; r_rst5 <= r_rst_s1; r_rst6 <= r_rst_s1; r_rst7 <= r_rst_s1; r_rst_ext <= r_rst_s1;
        end
    end

    // Strictly single-fanout 1st-stage CDC synchronizers (D-C1):
    //   r_up_w[0] -> ONLY r_up_w[1];  w_up_r[0] -> ONLY w_up_r[1];
    //   r_gray_w1 -> ONLY r_gray_w2 -> r_gray_w3_f/m (with FULL_MASK pre-XORed in FF, 0 extra latency!);
    //   w_gray_r1 -> ONLY w_gray_r2;  overflow_r[0] -> ONLY overflow_r[1].
    (* ASYNC_REG = "TRUE", keep = "true" *) reg [1:0]          r_up_w, w_up_r;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg [1:0]          overflow_r;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg [PTR_BITS-1:0] r_gray_w1, r_gray_w2;
    (* keep = "true" *)                     reg [PTR_BITS-1:0] r_gray_w3_f, r_gray_w3_m;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg [PTR_BITS-1:0] w_gray_r1, w_gray_r2;

    // Write-side state: compact single 16-bit w_oh with inverted bit-0 (ALL fast dfrtp, ZERO slow dfstp!)
    (* keep = "true" *) reg [PTR_BITS-1:0] w_gray;
    (* keep = "true" *) reg [PTR_BITS-1:0] w_gray_f, w_gray_m;
    reg [PTR_BITS-1:1] w_bin_p1_hi, w_gray_p1_hi;
    reg                w_bin_p1_b0n, w_gray_p1_b0n;
    (* keep = "true" *) reg [PTR_BITS-1:1] w_gray_p1_fhi, w_gray_p1_mhi;
    (* keep = "true" *) reg                w_gray_p1_fb0n, w_gray_p1_mb0n;
    wire [PTR_BITS-1:0] w_bin_p1    = {w_bin_p1_hi,   !w_bin_p1_b0n};
    wire [PTR_BITS-1:0] w_gray_p1   = {w_gray_p1_hi,  !w_gray_p1_b0n};
    wire [PTR_BITS-1:0] w_gray_p1_f = {w_gray_p1_fhi, !w_gray_p1_fb0n};
    wire [PTR_BITS-1:0] w_gray_p1_m = {w_gray_p1_mhi, !w_gray_p1_mb0n};
    (* keep = "true" *) reg [DEPTH-1:1] w_oh_hi;
    (* keep = "true" *) reg             w_oh_b0n;
    wire [DEPTH-1:0] w_oh = {w_oh_hi, !w_oh_b0n};

    (* keep = "true" *) reg w_online_port, w_online_int, w_online_rst_r;
    (* keep = "true" *) reg w_ready_q, w_ready_f0, w_ready_f1, w_ready_f2, w_ready_f3;
    (* keep = "true" *) reg w_ready_g0, w_ready_g1;
    (* keep = "true" *) reg w_ready_o0, w_ready_o1, w_ready_o2, w_ready_o3;
    (* keep = "true" *) reg w_ready_m0, w_ready_m1, w_ready_m2, w_ready_m3;
    (* keep = "true" *) reg w_ready_m4, w_ready_m5, w_ready_m6, w_ready_m7;

    // Read-side pop pointer (bit 0 stored inverted -> fast dfrtp!)
    (* keep = "true" *) reg [PTR_BITS-1:0] r_pop_gray;
    reg [PTR_BITS-1:1] r_pop_gray_p1_hi, r_pop_bin_p1_hi;
    reg                r_pop_gray_p1_b0n, r_pop_bin_p1_b0n;
    wire [PTR_BITS-1:0] r_pop_gray_p1 = {r_pop_gray_p1_hi, !r_pop_gray_p1_b0n};
    wire [PTR_BITS-1:0] r_pop_bin_p1  = {r_pop_bin_p1_hi,  !r_pop_bin_p1_b0n};

    // Read-side fetch pointer (bit 0 of p1 stored inverted -> fast dfrtp!)
    reg [PTR_BITS-1:0] r_fbin, r_fgray;
    reg [PTR_BITS-1:1] r_fbin_p1_hi, r_fgray_p1_hi;
    reg                r_fbin_p1_b0n, r_fgray_p1_b0n;
    wire [PTR_BITS-1:0] r_fbin_p1  = {r_fbin_p1_hi,  !r_fbin_p1_b0n};
    wire [PTR_BITS-1:0] r_fgray_p1 = {r_fgray_p1_hi, !r_fgray_p1_b0n};
    (* keep = "true" *) reg r_fbin_p1_b0an, r_fbin_p1_b0bn;
    (* keep = "true" *) reg f_avail_q, f_avail_fa, f_avail_f0, f_avail_f1a, f_avail_f1b, f_avail_f1c, f_avail_f1d;

    // Compact low-fanout fetch address copies (32+8+8 = 48 FFs instead of 96!)
    (* keep = "true" *) reg [DATA_WIDTH-1:0] rflo0_lo;
    (* keep = "true" *) reg [DATA_WIDTH-1:0] rflo0_hi;
    (* keep = "true" *) reg [7:0]            rflo1_b;
    (* keep = "true" *) reg [7:0]            rflo2_b;

    // Stage 1 read registers (8:1 mux folded into Stage 1 -> 32 data FFs + 8 select FFs)
    (* keep = "true" *) reg s1_valid, s1_v_l0, s1_v_l1, s1_v_h0, s1_v_h1;
    (* keep = "true" *) reg [7:0] s1_b3_sel;
    reg [DATA_WIDTH-1:0] s1_lo, s1_hi_d;

    // Stage 2: 3-entry FWFT output + 2 skid slots
    (* keep = "true" *) reg out_v_port, out_v_pop, out_v_ctl, out_v_l0, out_v_l1, out_v_h0, out_v_h1;
    (* keep = "true" *) reg skid1_v, sk1_v_l0, sk1_v_l1, sk1_v_h0, sk1_v_h1;
    (* keep = "true" *) reg skid2_v, sk2_v_l0, sk2_v_l1, sk2_v_h0, sk2_v_h1;
    (* keep = "true" *) reg occ1_l0, occ1_l1, occ1_h0, occ1_h1, occ2_l0, occ2_l1, occ2_h0, occ2_h1;
    (* keep = "true" *) reg [1:0] inflight_cnt, inflight_fa, inflight_f0, inflight_f1a, inflight_f1b, inflight_f1c, inflight_f1d;
    reg [DATA_WIDTH-1:0] out_d, skid1_d, skid2_d;

    assign w_online     = w_online_port;
    assign w_online_rst = w_online_rst_r;
    assign r_online     = w_up_r[1];
    assign w_ready      = w_ready_q;
    assign r_valid      = out_v_port;
    assign r_overflow   = overflow_r[1];
    assign r_data       = out_d;

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
    // M2: gate half-row memory writes with w_valid_m* (8 distinct w_ready_m0..7 FFs!)
    wire w_take_m0 = w_valid_m0 && w_ready_m0;
    wire w_take_m1 = w_valid_m1 && w_ready_m1;
    wire w_take_m2 = w_valid_m2 && w_ready_m2;
    wire w_take_m3 = w_valid_m3 && w_ready_m3;
    wire w_take_m4 = w_valid_m0 && w_ready_m4;
    wire w_take_m5 = w_valid_m1 && w_ready_m5;
    wire w_take_m6 = w_valid_m2 && w_ready_m6;
    wire w_take_m7 = w_valid_m3 && w_ready_m7;

    wire r_pop_ptr = out_v_pop && r_ready;
    wire r_pop_ctl = out_v_ctl && r_ready;

    wire [PTR_BITS-1:0] w_bin_p2      = w_bin_p1 + PTR_ONE;
    wire [PTR_BITS-1:0] w_gray_p2     = (PTR_BITS == 5) ? {
        w_gray_p1[4] ^ ( w_bin_p1[0] &  w_bin_p1[1] &  w_bin_p1[2] &  w_bin_p1[3]),
        w_gray_p1[3] ^ ( w_bin_p1[0] &  w_bin_p1[1] &  w_bin_p1[2] & !w_bin_p1[3]),
        w_gray_p1[2] ^ ( w_bin_p1[0] &  w_bin_p1[1] & !w_bin_p1[2]),
        w_gray_p1[1] ^ ( w_bin_p1[0] & !w_bin_p1[1]),
        w_gray_p1[0] ^ (!w_bin_p1[0])
    } : ((w_bin_p2 >> 1) ^ w_bin_p2);
    wire [PTR_BITS-1:0] r_pop_bin_p2  = r_pop_bin_p1 + PTR_ONE;
    wire [PTR_BITS-1:0] r_pop_gray_p2 = (PTR_BITS == 5) ? {
        r_pop_gray_p1[4] ^ ( r_pop_bin_p1[0] &  r_pop_bin_p1[1] &  r_pop_bin_p1[2] &  r_pop_bin_p1[3]),
        r_pop_gray_p1[3] ^ ( r_pop_bin_p1[0] &  r_pop_bin_p1[1] &  r_pop_bin_p1[2] & !r_pop_bin_p1[3]),
        r_pop_gray_p1[2] ^ ( r_pop_bin_p1[0] &  r_pop_bin_p1[1] & !r_pop_bin_p1[2]),
        r_pop_gray_p1[1] ^ ( r_pop_bin_p1[0] & !r_pop_bin_p1[1]),
        r_pop_gray_p1[0] ^ (!r_pop_bin_p1[0])
    } : ((r_pop_bin_p2 >> 1) ^ r_pop_bin_p2);
    wire [PTR_BITS-1:0] r_fbin_p2     = r_fbin_p1 + PTR_ONE;
    wire [PTR_BITS-1:0] r_fgray_p2    = (r_fbin_p2 >> 1) ^ r_fbin_p2;

    // r_gray_w3_f/m ALREADY hold (r_gray_w2 ^ FULL_MASK) from FF (0 extra latency, 0 XOR gate on critical path!)
    (* keep = "true" *) wire full_cur_a;
    (* keep = "true" *) wire full_cur_b;
    (* keep = "true" *) wire full_cur_c;
    (* keep = "true" *) wire full_cur_d;
    (* keep = "true" *) wire full_p1_a;
    (* keep = "true" *) wire full_p1_b;
    (* keep = "true" *) wire full_p1_c;
    (* keep = "true" *) wire full_p1_d;
    assign full_cur_a = (w_gray_f    == r_gray_w3_f);
    assign full_cur_b = (w_gray_f    == r_gray_w3_f);
    assign full_cur_c = (w_gray_m    == r_gray_w3_m);
    assign full_cur_d = (w_gray_m    == r_gray_w3_m);
    assign full_p1_a  = (w_gray_p1_f == r_gray_w3_f);
    assign full_p1_b  = (w_gray_p1_f == r_gray_w3_f);
    assign full_p1_c  = (w_gray_p1_m == r_gray_w3_m);
    assign full_p1_d  = (w_gray_p1_m == r_gray_w3_m);

    // 7-way kept w_ready_nxt derived strictly from 2nd-stage r_up_w[1] (D-C1: ZERO fanout from r_up_w[0]!)
    // w_ready_nxt_2a/2b/3a/3b drive ONLY 2 w_ready_m* FFs each!
    (* keep = "true" *) wire w_ready_nxt_0;
    (* keep = "true" *) wire w_ready_nxt_1a;
    (* keep = "true" *) wire w_ready_nxt_1b;
    (* keep = "true" *) wire w_ready_nxt_2a;
    (* keep = "true" *) wire w_ready_nxt_2b;
    (* keep = "true" *) wire w_ready_nxt_3a;
    (* keep = "true" *) wire w_ready_nxt_3b;
    assign w_ready_nxt_0  = r_up_w[1] && !(w_take_f0 ? full_p1_a : full_cur_a);
    assign w_ready_nxt_1a = r_up_w[1] && !(w_take_f1 ? full_p1_b : full_cur_b);
    assign w_ready_nxt_1b = r_up_w[1] && !(w_take_f1 ? full_p1_b : full_cur_b);
    assign w_ready_nxt_2a = r_up_w[1] && !(w_take_f2 ? full_p1_c : full_cur_c);
    assign w_ready_nxt_2b = r_up_w[1] && !(w_take_f2 ? full_p1_c : full_cur_c);
    assign w_ready_nxt_3a = r_up_w[1] && !(w_take_f3 ? full_p1_d : full_cur_d);
    assign w_ready_nxt_3b = r_up_w[1] && !(w_take_f3 ? full_p1_d : full_cur_d);

    // Pre-registered fetch_avail derived strictly from 2nd-stage w_up_r[1] (D-C1: ZERO fanout from w_up_r[0]!)
    wire f_ne_cur    = (r_fgray    != w_gray_r2);
    wire f_ne_p1     = (r_fgray_p1 != w_gray_r2);
    wire do_fetch_fa = f_avail_fa  && !(inflight_fa[1]  && inflight_fa[0]);
    wire f_avail_nxt = w_up_r[1]   && (do_fetch_fa ? f_ne_p1 : f_ne_cur);

    // Compact fetch enables (6 copies -> f_avail_nxt fanout = 7, nxt_cnt_b fanout = 10!)
    wire do_fetch_c  = f_avail_q   && !(inflight_cnt[1] && inflight_cnt[0]);
    wire do_fetch_0  = f_avail_f0  && !(inflight_f0[1]  && inflight_f0[0]);
    wire do_fetch_1a = f_avail_f1a && !(inflight_f1a[1] && inflight_f1a[0]);
    wire do_fetch_1b = f_avail_f1b && !(inflight_f1b[1] && inflight_f1b[0]);
    wire do_fetch_1c = f_avail_f1c && !(inflight_f1c[1] && inflight_f1c[0]);
    wire do_fetch_1d = f_avail_f1d && !(inflight_f1d[1] && inflight_f1d[0]);

    function automatic mux4(input s0, input s1, input d0, input d1, input d2, input d3);
        reg m0, m1;
        begin
            m0   = s0 ? d1 : d0;
            m1   = s0 ? d3 : d2;
            mux4 = s1 ? m1 : m0;
        end
    endfunction

    wire [DATA_WIDTH-1:0] s1_lo_c, s1_hi_c, s2_word;
    genvar b;
    generate
        for (b = 0; b < DATA_WIDTH; b = b + 1) begin : g_mux
            wire f0l = rflo0_lo[b];
            wire f0h = rflo0_hi[b];
            wire f1  = rflo1_b[b / 2];
            wire f2  = rflo2_b[b / 2];
            wire b0  = mux4(f0l, f1, mem[0][b],  mem[1][b],  mem[2][b],  mem[3][b]);
            wire b1  = mux4(f0l, f1, mem[4][b],  mem[5][b],  mem[6][b],  mem[7][b]);
            wire b2  = mux4(f0h, f1, mem[8][b],  mem[9][b],  mem[10][b], mem[11][b]);
            wire b3  = mux4(f0h, f1, mem[12][b], mem[13][b], mem[14][b], mem[15][b]);
            assign s1_lo_c[b] = f2 ? b1 : b0;
            assign s1_hi_c[b] = f2 ? b3 : b2;
            assign s2_word[b] = s1_b3_sel[b / 2] ? s1_hi_d[b] : s1_lo[b];
        end
    endgenerate

    // Write-domain CDC syncs (D-C1: strictly single-fanout 1st-stage FFs!)
    // r_gray_w3_f/m reset to 0 (fast dfrtp!) and pre-load (r_gray_w2 ^ FULL_MASK) on cycle 1
    // (while r_up_w[1] is still 0, so w_ready is guaranteed 0 until r_gray_w3_f/m are valid!).
    always @(posedge w_clk or negedge w_rst0) begin
        if (!w_rst0) begin
            r_up_w         <= 2'b00;
            w_online_port  <= 1'b0;
            w_online_int   <= 1'b0;
            w_online_rst_r <= 1'b0;
            r_gray_w1      <= {PTR_BITS{1'b0}};
            r_gray_w2      <= {PTR_BITS{1'b0}};
            r_gray_w3_f    <= {PTR_BITS{1'b0}};
            r_gray_w3_m    <= {PTR_BITS{1'b0}};
        end else begin
            r_up_w         <= {r_up_w[0], r_rst0};
            w_online_port  <= r_up_w[1];
            w_online_int   <= r_up_w[1];
            w_online_rst_r <= r_up_w[1];
            r_gray_w1      <= r_pop_gray;
            r_gray_w2      <= r_gray_w1;
            r_gray_w3_f    <= r_gray_w2 ^ FULL_MASK;
            r_gray_w3_m    <= r_gray_w2 ^ FULL_MASK;
        end
    end

    // Write-domain pointers (w_rst1: 30 FFs, ALL fast dfrtp!)
    always @(posedge w_clk or negedge w_rst1) begin
        if (!w_rst1) begin
            w_gray         <= {PTR_BITS{1'b0}};
            w_gray_f       <= {PTR_BITS{1'b0}};
            w_gray_m       <= {PTR_BITS{1'b0}};
            w_bin_p1_hi    <= {(PTR_BITS-1){1'b0}};
            w_bin_p1_b0n   <= 1'b0;
            w_gray_p1_hi   <= {(PTR_BITS-1){1'b0}};
            w_gray_p1_b0n  <= 1'b0;
            w_gray_p1_fhi  <= {(PTR_BITS-1){1'b0}};
            w_gray_p1_fb0n <= 1'b0;
            w_gray_p1_mhi  <= {(PTR_BITS-1){1'b0}};
            w_gray_p1_mb0n <= 1'b0;
        end else begin
            if (w_take_g0) begin
                w_gray   <= w_gray_p1;
                w_gray_f <= w_gray_p1;
                w_gray_m <= w_gray_p1;
            end
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

    // Write-domain single 16-bit one-hot pointer with inverted bit-0 (w_rst2: 16 fast dfrtp FFs!)
    always @(posedge w_clk or negedge w_rst2) begin
        if (!w_rst2) begin
            w_oh_hi  <= {(DEPTH-1){1'b0}};
            w_oh_b0n <= 1'b0;
        end else begin
            if (w_take_o0) begin
                w_oh_b0n     <= !w_oh[DEPTH-1];
                w_oh_hi[3:1] <= w_oh[2:0];
            end
            if (w_take_o1) w_oh_hi[7:4]   <= w_oh[6:3];
            if (w_take_o2) w_oh_hi[11:8]  <= w_oh[10:7];
            if (w_take_o3) w_oh_hi[15:12] <= w_oh[14:11];
        end
    end

    // Write-domain flags split across w_rst3 (12 FFs) & w_rst4 (8 FFs); fanout = 2 on m0..m7!
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

    // Read-domain pop pointer (r_rst1: 15 FFs, ALL fast dfrtp!)
    always @(posedge r_clk or negedge r_rst1) begin
        if (!r_rst1) begin
            r_pop_gray        <= {PTR_BITS{1'b0}};
            r_pop_bin_p1_hi   <= {(PTR_BITS-1){1'b0}};
            r_pop_bin_p1_b0n  <= 1'b0;
            r_pop_gray_p1_hi  <= {(PTR_BITS-1){1'b0}};
            r_pop_gray_p1_b0n <= 1'b0;
        end else if (r_pop_ptr) begin
            r_pop_gray        <= r_pop_gray_p1;
            r_pop_bin_p1_hi   <= r_pop_bin_p2[PTR_BITS-1:1];
            r_pop_bin_p1_b0n  <= !r_pop_bin_p2[0];
            r_pop_gray_p1_hi  <= r_pop_gray_p2[PTR_BITS-1:1];
            r_pop_gray_p1_b0n <= !r_pop_gray_p2[0];
        end
    end

    // Read-domain fetch Gray/bin pointers split across r_rst2 (15) & r_rst3 (24), ALL fast dfrtp!
    always @(posedge r_clk or negedge r_rst2) begin
        if (!r_rst2) begin
            r_fbin        <= {PTR_BITS{1'b0}};
            r_fgray       <= {PTR_BITS{1'b0}};
            r_fbin_p1_hi  <= {(PTR_BITS-1){1'b0}};
            r_fbin_p1_b0n <= 1'b0;
        end else if (do_fetch_0) begin
            r_fbin        <= r_fbin_p1;
            r_fgray       <= r_fgray_p1;
            r_fbin_p1_hi  <= r_fbin_p2[PTR_BITS-1:1];
            r_fbin_p1_b0n <= !r_fbin_p2[0];
        end
    end
    always @(posedge r_clk or negedge r_rst3) begin
        if (!r_rst3) begin
            r_fgray_p1_hi  <= {(PTR_BITS-1){1'b0}};
            r_fgray_p1_b0n <= 1'b0;
            r_fbin_p1_b0an <= 1'b0;
            r_fbin_p1_b0bn <= 1'b0;
            rflo1_b        <= 8'd0;
            rflo2_b        <= 8'd0;
            f_avail_q      <= 1'b0;
        end else begin
            f_avail_q <= f_avail_nxt;
            if (do_fetch_1a) begin
                r_fgray_p1_hi  <= r_fgray_p2[PTR_BITS-1:1];
                r_fgray_p1_b0n <= !r_fgray_p2[0];
                r_fbin_p1_b0an <= !r_fbin_p2[0];
                r_fbin_p1_b0bn <= !r_fbin_p2[0];
            end
            if (do_fetch_1d) begin
                rflo1_b <= {8{r_fbin_p1[1]}};
                rflo2_b <= {8{r_fbin_p1[2]}};
            end
        end
    end

    // Compact bit-0 fetch addr (r_rst4: 32 FFs, 16 FFs per enable!)
    always @(posedge r_clk or negedge r_rst4) begin
        if (!r_rst4) begin
            rflo0_lo <= {DATA_WIDTH{1'b0}};
            rflo0_hi <= {DATA_WIDTH{1'b0}};
        end else begin
            if (do_fetch_1b) begin
                rflo0_lo[7:0]  <= {8{!r_fbin_p1_b0an}};
                rflo0_hi[7:0]  <= {8{!r_fbin_p1_b0an}};
            end
            if (do_fetch_1c) begin
                rflo0_lo[15:8] <= {8{!r_fbin_p1_b0bn}};
                rflo0_hi[15:8] <= {8{!r_fbin_p1_b0bn}};
            end
        end
    end

    // Stage 2 3-entry FWFT output/skid control
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

    (* keep = "true" *) wire nxt_out_v_a, nxt_out_v_b;
    (* keep = "true" *) wire nxt_sk1_v_a, nxt_sk1_v_b;
    (* keep = "true" *) wire nxt_sk2_v_a, nxt_sk2_v_b;
    (* keep = "true" *) wire nxt_occ1_a,  nxt_occ1_b;
    (* keep = "true" *) wire nxt_occ2_a,  nxt_occ2_b;
    assign nxt_out_v_a = out_ld_sk1_c || out_ld_s2_c || (out_v_ctl && !r_pop_ctl);
    assign nxt_out_v_b = out_ld_sk1_c || out_ld_s2_c || (out_v_ctl && !r_pop_ctl);
    assign nxt_sk1_v_a = sk1_ld_sk2_c || sk1_ld_s2_c || (skid1_v   && !r_pop_ctl);
    assign nxt_sk1_v_b = sk1_ld_sk2_c || sk1_ld_s2_c || (skid1_v   && !r_pop_ctl);
    assign nxt_sk2_v_a = sk2_ld_s2_c  || (skid2_v && !r_pop_ctl);
    assign nxt_sk2_v_b = sk2_ld_s2_c  || (skid2_v && !r_pop_ctl);
    assign nxt_occ1_a  = nxt_out_v_a && !nxt_sk1_v_a;
    assign nxt_occ1_b  = nxt_out_v_b && !nxt_sk1_v_b;
    assign nxt_occ2_a  = nxt_sk1_v_a && !nxt_sk2_v_a;
    assign nxt_occ2_b  = nxt_sk1_v_b && !nxt_sk2_v_b;
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
            out_v_port   <= nxt_out_v_a;
            out_v_pop    <= nxt_out_v_a;
            out_v_ctl    <= nxt_out_v_a;
            out_v_l0     <= nxt_out_v_a;
            skid1_v      <= nxt_sk1_v_a;
            sk1_v_l0     <= nxt_sk1_v_a;
            occ1_l0      <= nxt_occ1_a;
            occ2_l0      <= nxt_occ2_a;
            skid2_v      <= nxt_sk2_v_a;
            sk2_v_l0     <= nxt_sk2_v_a;
            inflight_cnt <= nxt_cnt_a;
            inflight_f0  <= nxt_cnt_a;
        end
    end

    // r_rst6: 16 FFs (dedicated fetch inflight & f_avail copies)
    always @(posedge r_clk or negedge r_rst6) begin
        if (!r_rst6) begin
            inflight_fa  <= 2'd0; inflight_f1a <= 2'd0; inflight_f1b <= 2'd0;
            inflight_f1c <= 2'd0; inflight_f1d <= 2'd0;
            f_avail_fa   <= 1'b0; f_avail_f0   <= 1'b0; f_avail_f1a  <= 1'b0;
            f_avail_f1b  <= 1'b0; f_avail_f1c  <= 1'b0; f_avail_f1d  <= 1'b0;
        end else begin
            inflight_fa  <= nxt_cnt_b;
            inflight_f1a <= nxt_cnt_b;
            inflight_f1b <= nxt_cnt_b;
            inflight_f1c <= nxt_cnt_b;
            inflight_f1d <= nxt_cnt_b;
            f_avail_fa   <= f_avail_nxt;
            f_avail_f0   <= f_avail_nxt;
            f_avail_f1a  <= f_avail_nxt;
            f_avail_f1b  <= f_avail_nxt;
            f_avail_f1c  <= f_avail_nxt;
            f_avail_f1d  <= f_avail_nxt;
        end
    end

    // r_rst7: 18 FFs (split 4-bit nibble controls l1/h0/h1)
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
            out_v_l1 <= nxt_out_v_b; out_v_h0 <= nxt_out_v_b; out_v_h1 <= nxt_out_v_b;
            sk1_v_l1 <= nxt_sk1_v_b; sk1_v_h0 <= nxt_sk1_v_b; sk1_v_h1 <= nxt_sk1_v_b;
            sk2_v_l1 <= nxt_sk2_v_b; sk2_v_h0 <= nxt_sk2_v_b; sk2_v_h1 <= nxt_sk2_v_b;
            occ1_l1  <= nxt_occ1_b;  occ1_h0  <= nxt_occ1_b;  occ1_h1  <= nxt_occ1_b;
            occ2_l1  <= nxt_occ2_b;  occ2_h0  <= nxt_occ2_b;  occ2_h1  <= nxt_occ2_b;
        end
    end

    // Unconditional Stage 1 datapath FFs
    always @(posedge r_clk) begin
        s1_b3_sel <= {8{r_fbin[3]}};
        s1_lo     <= s1_lo_c;
        s1_hi_d   <= s1_hi_c;
    end

    // Stage 2 skid/output datapath FFs (4x 4-bit nibbles)
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

    // Compact half-row memory write enables (8 distinct w_ready_m0..7 FFs, M2 w_valid-gated!)
    wire [DEPTH-1:0] wen_lo, wen_hi;
    genvar wr;
    generate
        for (wr = 0; wr < DEPTH; wr = wr + 1) begin : g_wen
            wire tm_lo = (wr < 4) ? w_take_m0 : ((wr < 8) ? w_take_m1 : ((wr < 12) ? w_take_m2 : w_take_m3));
            wire tm_hi = (wr < 4) ? w_take_m4 : ((wr < 8) ? w_take_m5 : ((wr < 12) ? w_take_m6 : w_take_m7));
            assign wen_lo[wr] = tm_lo && w_oh[wr];
            assign wen_hi[wr] = tm_hi && w_oh[wr];
        end
    endgenerate

    integer row;
    always @(posedge w_clk) begin
        for (row = 0; row < DEPTH; row = row + 1) begin
            if (wen_lo[row]) mem[row][7:0]  <= w_data[7:0];
            if (wen_hi[row]) mem[row][15:8] <= w_data[15:8];
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
    wire _unused_w_online_rst, _unused_w_rst_out, _unused_r_rst_out;
    rx_async_word_fifo_core #(.DATA_WIDTH(DATA_WIDTH), .ADDR_BITS(ADDR_BITS)) u_core (
        .w_clk(w_clk), .r_clk(r_clk), .arst_n(arst_n),
        .w_valid(w_valid),
        .w_valid_m0(w_valid), .w_valid_m1(w_valid), .w_valid_m2(w_valid), .w_valid_m3(w_valid),
        .w_data(w_data), .w_ready(w_ready),
        .w_online(w_online), .w_online_rst(_unused_w_online_rst),
        .w_rst_out(_unused_w_rst_out), .w_overflow(w_overflow),
        .r_valid(r_valid), .r_online(r_online), .r_rst_out(_unused_r_rst_out),
        .r_overflow(r_overflow), .r_data(r_data), .r_ready(r_ready)
    );
endmodule
