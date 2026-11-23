// Timing-closed v2 16-bit word aligner (250 MHz / 4.0 ns SS-closed).
// Balanced low-latency pipeline (EVERY stage <= 3-4 SS gates, fanout <= 16!):
//   - Training path: Stage 1 (8-bit halves) -> Stage 2a (nibble prio) -> Stage 2b (4:1 prio) -> Stage 3 (hit lock).
//   - Payload data path (1 cycle shorter!): Stage 1 (sh1) -> Stage 2a (sh2) -> Output (sh4+sh8 = 2 mux2 levels!).
//   - Only 9 control/valid FFs use async rst_n (word_online fanout <= 15!).
module rx_word_align16 #(
    parameter [15:0]  TRAIN_WORD = 16'hb5e3,
    parameter integer TRAIN_HITS = 4
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        sclr,
    input  wire        chunk_valid,
    input  wire        training_enable,
    input  wire [15:0] chunk,
    output reg  [15:0] word_data,
    output reg         word_valid,
    output reg         aligned,
    output reg  [3:0]  offset
);
    reg [15:0] prev;
    wire [31:0] s0_stream = {chunk, prev};

    reg        s1_train;
    reg [15:0] s1_mlo, s1_mhi;
    reg [29:0] s1_sh1;

    reg        s2a_train;
    reg [3:0]  s2a_v;
    reg [1:0]  s2a_i0, s2a_i1, s2a_i2, s2a_i3;
    reg [27:0] s2a_sh2;

    reg        s2b_train, s2b_found;
    reg [3:0]  s2b_at;
    (* keep = "true" *) reg [3:0] s2b_at_cmp;

    reg [3:0]  cand;
    (* keep = "true" *) reg off0_a, off0_b, off0_c;
    (* keep = "true" *) reg off1_a, off1_b;
    (* keep = "true" *) reg off2_a, off2_b;
    (* keep = "true" *) reg off3_a, off3_b;

    // Control registers with async rst_n (total = 9 FFs!)
    reg       s1_valid, s2a_valid, s2b_valid;
    reg [2:0] hit_sr;

    // Stage 1: 8-bit constant equality + sh1 (offset[0], fanout = 10 each!)
    reg [15:0] mlo_c, mhi_c;
    integer s;
    always @* begin
        for (s = 0; s < 16; s = s + 1) begin
            mlo_c[s] = (s0_stream[s     +: 8] == TRAIN_WORD[7:0]);
            mhi_c[s] = (s0_stream[s + 8 +: 8] == TRAIN_WORD[15:8]);
        end
    end
    wire [9:0] sh1_a = off0_a ? s0_stream[10:1]  : s0_stream[9:0];
    wire [9:0] sh1_b = off0_b ? s0_stream[20:11] : s0_stream[19:10];
    wire [9:0] sh1_c = off0_c ? s0_stream[30:21] : s0_stream[29:20];

    // Stage 2a: combine half-matches + nibble priority + sh2 (offset[1], fanout = 14 each!)
    wire [15:0] match_c = s1_mlo & s1_mhi;
    wire [3:0] m0 = match_c[3:0];
    wire [3:0] m1 = match_c[7:4];
    wire [3:0] m2 = match_c[11:8];
    wire [3:0] m3 = match_c[15:12];
    wire [3:0] v_c = {|m3, |m2, |m1, |m0};
    wire [1:0] i0_c = m0[0] ? 2'd0 : (m0[1] ? 2'd1 : (m0[2] ? 2'd2 : 2'd3));
    wire [1:0] i1_c = m1[0] ? 2'd0 : (m1[1] ? 2'd1 : (m1[2] ? 2'd2 : 2'd3));
    wire [1:0] i2_c = m2[0] ? 2'd0 : (m2[1] ? 2'd1 : (m2[2] ? 2'd2 : 2'd3));
    wire [1:0] i3_c = m3[0] ? 2'd0 : (m3[1] ? 2'd1 : (m3[2] ? 2'd2 : 2'd3));

    wire [13:0] sh2_lo = off1_a ? s1_sh1[15:2]  : s1_sh1[13:0];
    wire [13:0] sh2_hi = off1_b ? s1_sh1[29:16] : s1_sh1[27:14];

    // Stage 2b: 4:1 priority mux (training path)
    wire found_c = |s2a_v;
    wire [3:0] at_c = s2a_v[0] ? {2'd0, s2a_i0} :
                      s2a_v[1] ? {2'd1, s2a_i1} :
                      s2a_v[2] ? {2'd2, s2a_i2} : {2'd3, s2a_i3};

    // Payload output stage: 2 mux2 levels directly from s2a_sh2 (saves 1 cycle + 24 FFs!)
    wire [11:0] sh4_lo = off2_a ? s2a_sh2[15:4]  : s2a_sh2[11:0];
    wire [11:0] sh4_hi = off2_b ? s2a_sh2[27:16] : s2a_sh2[23:12];
    wire [23:0] sh4    = {sh4_hi, sh4_lo};
    wire [7:0]  sh8_lo = off3_a ? sh4[15:8]  : sh4[7:0];
    wire [7:0]  sh8_hi = off3_b ? sh4[23:16] : sh4[15:8];
    wire [15:0] shifted_word = {sh8_hi, sh8_lo};

    // Fast flat thermometer hit check -> registered Stage 2c lock pulse (breaks 115 um training->shifter path!)
    // Payload data path latency is 100% unchanged; training lock completes in TRAIN_HITS+1 cycles (+2.0 ns SS slack!).
    (* keep = "true" *) reg s2b_vtf_0;
    (* keep = "true" *) reg s2c_lock_off, s2c_lock_0, s2c_lock_12, s2c_lock_3, s2c_clear;
    reg [3:0] s2c_at;
    wire at_eq_cand = (s2b_at_cmp == cand);
    wire same_cand  = s2b_found && at_eq_cand && hit_sr[0];
    wire hit_gate   = (TRAIN_HITS <= 1) ? 1'b1 : (TRAIN_HITS == 2) ? hit_sr[0] : (TRAIN_HITS == 3) ? hit_sr[1] : hit_sr[2];
    wire hit_lock_c = s2b_vtf_0 && at_eq_cand && hit_gate;

    // Async-reset (clean arst_n) + synchronous epoch-clear (sclr) control & X-safe offset/cand FFs (32 FFs)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s1_valid     <= 1'b0;
            s2a_valid    <= 1'b0;
            s2b_valid    <= 1'b0;
            s2b_vtf_0    <= 1'b0;
            hit_sr       <= 3'b000;
            s2c_lock_off <= 1'b0;
            s2c_lock_0   <= 1'b0;
            s2c_lock_12  <= 1'b0;
            s2c_lock_3   <= 1'b0;
            s2c_clear    <= 1'b0;
            aligned      <= 1'b0;
            word_valid   <= 1'b0;
            offset       <= 4'd0;
            cand         <= 4'd0;
            off0_a       <= 1'b0; off0_b <= 1'b0; off0_c <= 1'b0;
            off1_a       <= 1'b0; off1_b <= 1'b0;
            off2_a       <= 1'b0; off2_b <= 1'b0;
            off3_a       <= 1'b0; off3_b <= 1'b0;
        end else if (sclr) begin
            s1_valid     <= 1'b0;
            s2a_valid    <= 1'b0;
            s2b_valid    <= 1'b0;
            s2b_vtf_0    <= 1'b0;
            hit_sr       <= 3'b000;
            s2c_lock_off <= 1'b0;
            s2c_lock_0   <= 1'b0;
            s2c_lock_12  <= 1'b0;
            s2c_lock_3   <= 1'b0;
            s2c_clear    <= 1'b0;
            aligned      <= 1'b0;
            word_valid   <= 1'b0;
            offset       <= 4'd0;
            cand         <= 4'd0;
            off0_a       <= 1'b0; off0_b <= 1'b0; off0_c <= 1'b0;
            off1_a       <= 1'b0; off1_b <= 1'b0;
            off2_a       <= 1'b0; off2_b <= 1'b0;
            off3_a       <= 1'b0; off3_b <= 1'b0;
        end else begin
            s1_valid  <= chunk_valid;
            s2a_valid <= s1_valid;
            s2b_valid <= s2a_valid;
            s2b_vtf_0 <= s2a_valid && s2a_train && found_c;

            // Payload valid emits at Stage 2a (1 cycle faster!) once aligned
            word_valid <= s2a_valid && !s2a_train && aligned;

            // Registered Stage 2c lock/clear pulses (zero high-fanout combinational comparator across shifter!)
            s2c_lock_off <= hit_lock_c;
            s2c_lock_0   <= hit_lock_c;
            s2c_lock_12  <= hit_lock_c;
            s2c_lock_3   <= hit_lock_c;
            s2c_clear    <= s2b_valid && s2b_train && !same_cand;

            if (s2c_clear) aligned <= 1'b0;
            else if (s2c_lock_off) aligned <= 1'b1;

            if (s2b_valid && s2b_train) begin
                if (same_cand) begin
                    hit_sr <= {hit_sr[1:0], 1'b1};
                end else if (s2b_found) begin
                    hit_sr <= 3'b001;
                end else begin
                    hit_sr <= 3'b000;
                end
            end

            if (s2c_lock_off) offset <= s2c_at;
            if (s2c_lock_0) begin
                off0_a <= s2c_at[0]; off0_b <= s2c_at[0]; off0_c <= s2c_at[0];
            end
            if (s2c_lock_12) begin
                off1_a <= s2c_at[1]; off1_b <= s2c_at[1];
                off2_a <= s2c_at[2]; off2_b <= s2c_at[2];
            end
            if (s2c_lock_3) begin
                off3_a <= s2c_at[3]; off3_b <= s2c_at[3];
            end
            if (s2b_vtf_0) begin
                cand <= s2b_at;
            end
        end
    end

    // Unconditional datapath pipeline registers
    always @(posedge clk) begin
        if (chunk_valid) prev <= chunk;
        s1_train  <= training_enable;
        s1_mlo    <= mlo_c;
        s1_mhi    <= mhi_c;
        s1_sh1    <= {sh1_c, sh1_b, sh1_a};

        s2a_train <= s1_train;
        s2a_v     <= v_c;
        s2a_i0    <= i0_c; s2a_i1 <= i1_c; s2a_i2 <= i2_c; s2a_i3 <= i3_c;
        s2a_sh2   <= {sh2_hi, sh2_lo};

        s2b_train  <= s2a_train;
        s2b_found  <= found_c;
        s2b_at     <= at_c;
        s2b_at_cmp <= at_c;
        s2c_at     <= s2b_at;

        word_data <= shifted_word;
    end
endmodule
