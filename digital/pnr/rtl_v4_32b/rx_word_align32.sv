// 32-bit word aligner running on rx_clk_div2 (125 MHz @ 4G / 156.25 MHz @ 5G, 6.40 ns!).
// Slides over 48-bit window {in_word[31:0], prev_hi16[15:0]} to detect {TRAIN_WORD, TRAIN_WORD}
// (32'hB5E3_B5E3) at any bit offset 0..15, then outputs aligned 32-bit words into the 16x32 RX FIFO.
// Clean 2-stage pipeline keeps every stage <= 5 gate levels (~2.5 ns << 6.40 ns!).
module rx_word_align32 #(
    parameter [15:0]  TRAIN_WORD = 16'hb5e3,
    parameter integer TRAIN_HITS = 4
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        in_valid,
    input  wire        training_enable,
    input  wire [31:0] in_word,
    output reg  [31:0] out_word,
    output reg         out_valid,
    output reg         aligned,
    output reg  [3:0]  offset
);
    localparam [31:0] TRAIN_WORD_32 = {TRAIN_WORD, TRAIN_WORD};
    localparam integer HW = (TRAIN_HITS <= 1) ? 1 : $clog2(TRAIN_HITS + 1);
    localparam integer HL_I = (TRAIN_HITS > 1) ? (TRAIN_HITS - 1) : 1;
    localparam [HW-1:0] HITS_LAST = HL_I[HW-1:0];

    // 2-FF synchronizer for training_enable onto rx_clk_div2 (D-C1 safe)
    (* ASYNC_REG = "TRUE", keep = "true" *) reg [1:0] tr_sync;
    wire tr_en = tr_sync[1];

    // Stage 0 -> Stage 1: capture 48-bit sliding window & 16 parallel 32-bit training matches
    reg        have_prev;
    reg [15:0] prev_hi16;

    wire [47:0] win48_c = {in_word, prev_hi16};
    wire [15:0] match16_c;
    genvar gi;
    generate
        for (gi = 0; gi < 16; gi = gi + 1) begin : g_match
            assign match16_c[gi] = (win48_c[gi +: 32] == TRAIN_WORD_32);
        end
    endgenerate

    reg        s1_valid;
    reg        s1_tr_en;
    reg [47:0] s1_win48;
    reg [15:0] s1_match16;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tr_sync    <= 2'b00;
            have_prev  <= 1'b0;
            s1_valid   <= 1'b0;
            s1_tr_en   <= 1'b0;
            s1_match16 <= 16'd0;
        end else begin
            tr_sync  <= {tr_sync[0], training_enable};
            s1_valid <= in_valid && have_prev;
            s1_tr_en <= tr_en;
            if (in_valid) begin
                have_prev  <= 1'b1;
                s1_match16 <= (have_prev && tr_en) ? match16_c : 16'd0;
            end else begin
                s1_match16 <= 16'd0;
            end
        end
    end

    // Non-reset datapath window registers (dfxtp -> 0 RESET_B pins!)
    always @(posedge clk) begin
        if (in_valid) begin
            prev_hi16 <= in_word[31:16];
            s1_win48  <= win48_c;
        end
    end

    // Stage 2: balanced 4-nibble parallel tree priority encoder (4 gates instead of 8-deep ripple!)
    wire       v_n0 = |s1_match16[3:0];
    wire       v_n1 = |s1_match16[7:4];
    wire       v_n2 = |s1_match16[11:8];
    wire       v_n3 = |s1_match16[15:12];
    wire [1:0] i_n0 = s1_match16[0] ? 2'd0 : (s1_match16[1] ? 2'd1 : (s1_match16[2] ? 2'd2 : 2'd3));
    wire [1:0] i_n1 = s1_match16[4] ? 2'd0 : (s1_match16[5] ? 2'd1 : (s1_match16[6] ? 2'd2 : 2'd3));
    wire [1:0] i_n2 = s1_match16[8] ? 2'd0 : (s1_match16[9] ? 2'd1 : (s1_match16[10] ? 2'd2 : 2'd3));
    wire [1:0] i_n3 = s1_match16[12] ? 2'd0 : (s1_match16[13] ? 2'd1 : (s1_match16[14] ? 2'd2 : 2'd3));

    wire       has_hit = v_n0 || v_n1 || v_n2 || v_n3;
    wire [1:0] hi_sel  = v_n0 ? 2'd0 : (v_n1 ? 2'd1 : (v_n2 ? 2'd2 : 2'd3));
    wire [1:0] lo_sel  = v_n0 ? i_n0 : (v_n1 ? i_n1 : (v_n2 ? i_n2 : i_n3));
    wire [3:0] hit_off = {hi_sel, lo_sel};

    // Stage 1b: register priority-encoded hit (7 FFs only!) to split 11-gate chain into 4 + 5 gates!
    reg       s1b_valid;
    reg       s1b_tr_en;
    reg       s1b_has_hit;
    reg [3:0] s1b_hit_off;

    reg [3:0]    cand_off;
    reg [HW-1:0] hit_cnt;
    // Duplicate offset[3:0] into lo/hi copies for low-fanout 32-bit 16:1 barrel shift (mux4_2!)
    (* keep = "true" *) reg [3:0] off_lo_r;
    (* keep = "true" *) reg [3:0] off_hi_r;

    wire [15:0] shifted_lo = s1_win48[{2'b00, off_lo_r} +: 16];
    wire [15:0] shifted_hi = s1_win48[{2'b01, off_hi_r} +: 16]; // off_hi_r + 16

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s1b_valid   <= 1'b0;
            s1b_tr_en   <= 1'b0;
            s1b_has_hit <= 1'b0;
            s1b_hit_off <= 4'd0;
            aligned     <= 1'b0;
            offset      <= 4'd0;
            off_lo_r    <= 4'd0;
            off_hi_r    <= 4'd0;
            cand_off    <= 4'd0;
            hit_cnt     <= {HW{1'b0}};
            out_valid   <= 1'b0;
        end else begin
            s1b_valid   <= s1_valid;
            s1b_tr_en   <= s1_tr_en;
            s1b_has_hit <= has_hit;
            s1b_hit_off <= hit_off;

            // Training FSM runs cleanly from registered s1b_* (only 5 gate levels!)
            if (s1b_valid && s1b_tr_en && !aligned) begin
                if (s1b_has_hit) begin
                    if ((hit_cnt != {HW{1'b0}}) && (s1b_hit_off == cand_off)) begin
                        if (hit_cnt >= HITS_LAST) begin
                            aligned  <= 1'b1;
                            offset   <= s1b_hit_off;
                            off_lo_r <= s1b_hit_off;
                            off_hi_r <= s1b_hit_off;
                            hit_cnt  <= hit_cnt;
                        end else begin
                            hit_cnt <= hit_cnt + 1'b1;
                        end
                    end else begin
                        cand_off <= s1b_hit_off;
                        hit_cnt  <= {{(HW-1){1'b0}}, 1'b1};
                        if (TRAIN_HITS <= 1) begin
                            aligned  <= 1'b1;
                            offset   <= s1b_hit_off;
                            off_lo_r <= s1b_hit_off;
                            off_hi_r <= s1b_hit_off;
                        end
                    end
                end else begin
                    hit_cnt <= {HW{1'b0}};
                end
            end

            // Data path stays zero-extra-latency directly off s1_valid && !s1_tr_en && aligned!
            out_valid <= s1_valid && !s1_tr_en && aligned;
        end
    end

    // Non-reset aligned 32-bit word output register
    always @(posedge clk) begin
        if (s1_valid && !s1_tr_en && aligned) begin
            out_word <= {shifted_hi, shifted_lo};
        end
    end
endmodule
