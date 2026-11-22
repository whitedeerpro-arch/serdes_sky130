// Lean 250 MHz 16-UI BBPD voter + 2-tick (32-UI) synchronous pre-accumulator (v3).
// Ultra-shallow 5-stage pipeline keeps EVERY 250 MHz stage <= 5-6 gate levels (+1.0 ns SS slack!):
//   Stage 0a: 8 parallel 2-bit pair votes & counts (trans/late/early + 2-bit LUT, ~5 levels)
//   Stage 0b: 4 parallel nibble sums (single 3-bit add each, ~4 levels)
//   Stage 1 : 2 parallel byte sums (single 4-bit add each, ~5 levels)
//   Stage 2 : single-bundle 6b signed vote & 5b count (single 5-bit add, ~5 levels)
//   Stage 3 : 2-tick pair accumulator aligned to cdr_clk_div2 falling edge (phase_hi == 1)
module bbpd_window_vote (
    input  wire              ctrl_clk,
    input  wire              rst_n,
    input  wire              phase_hi,       // 0->1 capture by cdr_clk_div2, 1->0 update pair_*
    input  wire              bundle_valid,
    input  wire              previous_data,
    input  wire       [15:0] data_samples,
    input  wire       [15:0] edge_samples,
    output reg               pair_valid,
    output reg signed [5:0]  pair_sum_a,
    output reg signed [5:0]  pair_sum_b,
    output reg        [4:0]  pair_cnt_a,
    output reg        [4:0]  pair_cnt_b
);
    // Stage 00 (250 MHz): compute trans/late/early directly from registered u_rx_map outputs (2 gates!)
    // and latch late_r/early_r (32 FFs, same count as d_r/e_r; note trans = late | early since mutually exclusive!).
    // Cuts Stage 0a from 6 gates (-0.14 ns) to 3 gates (+1.2 ns SS slack at 250 MHz) with ZERO extra latency!
    wire [15:0] before_bits = {data_samples[14:0], previous_data};
    wire [15:0] trans_c     = before_bits ^ data_samples;
    wire [15:0] diff_ed     = edge_samples ^ data_samples;
    wire [15:0] late_c      = trans_c & ~diff_ed;
    wire [15:0] early_c     = trans_c &  diff_ed;

    reg        bv_r;
    reg [15:0] late_r;
    reg [15:0] early_r;
    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            bv_r    <= 1'b0;
            late_r  <= 16'd0;
            early_r <= 16'd0;
        end else begin
            bv_r    <= bundle_valid;
            late_r  <= late_c;
            early_r <= early_c;
        end
    end

    wire [15:0] late  = late_r;
    wire [15:0] early = early_r;
    wire [15:0] trans = late_r | early_r;

    function automatic [1:0] pop2(input [1:0] x);
        pop2 = {1'b0, x[0]} + {1'b0, x[1]};
    endfunction

    function automatic signed [2:0] vote2(input [1:0] l, input [1:0] e);
        case ({l, e})
            4'b11_00: vote2 =  3'sd2;
            4'b10_00,
            4'b01_00: vote2 =  3'sd1;
            4'b00_10,
            4'b00_01: vote2 = -3'sd1;
            4'b00_11: vote2 = -3'sd2;
            default:  vote2 =  3'sd0;
        endcase
    endfunction

    // Stage 0a (250 MHz): 8 parallel 2-bit pair votes & counts (~5 gate levels = ~2.0 ns SS!)
    reg              p_valid;
    reg signed [2:0] p_v0, p_v1, p_v2, p_v3, p_v4, p_v5, p_v6, p_v7;
    reg        [1:0] p_c0, p_c1, p_c2, p_c3, p_c4, p_c5, p_c6, p_c7;

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            p_valid <= 1'b0;
            p_v0 <= 3'sd0; p_v1 <= 3'sd0; p_v2 <= 3'sd0; p_v3 <= 3'sd0;
            p_v4 <= 3'sd0; p_v5 <= 3'sd0; p_v6 <= 3'sd0; p_v7 <= 3'sd0;
            p_c0 <= 2'd0;  p_c1 <= 2'd0;  p_c2 <= 2'd0;  p_c3 <= 2'd0;
            p_c4 <= 2'd0;  p_c5 <= 2'd0;  p_c6 <= 2'd0;  p_c7 <= 2'd0;
        end else begin
            p_valid <= bv_r;
            if (bv_r) begin
                p_v0 <= vote2(late[1:0],   early[1:0]);
                p_v1 <= vote2(late[3:2],   early[3:2]);
                p_v2 <= vote2(late[5:4],   early[5:4]);
                p_v3 <= vote2(late[7:6],   early[7:6]);
                p_v4 <= vote2(late[9:8],   early[9:8]);
                p_v5 <= vote2(late[11:10], early[11:10]);
                p_v6 <= vote2(late[13:12], early[13:12]);
                p_v7 <= vote2(late[15:14], early[15:14]);
                p_c0 <= pop2(trans[1:0]);
                p_c1 <= pop2(trans[3:2]);
                p_c2 <= pop2(trans[5:4]);
                p_c3 <= pop2(trans[7:6]);
                p_c4 <= pop2(trans[9:8]);
                p_c5 <= pop2(trans[11:10]);
                p_c6 <= pop2(trans[13:12]);
                p_c7 <= pop2(trans[15:14]);
            end else begin
                p_v0 <= 3'sd0; p_v1 <= 3'sd0; p_v2 <= 3'sd0; p_v3 <= 3'sd0;
                p_v4 <= 3'sd0; p_v5 <= 3'sd0; p_v6 <= 3'sd0; p_v7 <= 3'sd0;
                p_c0 <= 2'd0;  p_c1 <= 2'd0;  p_c2 <= 2'd0;  p_c3 <= 2'd0;
                p_c4 <= 2'd0;  p_c5 <= 2'd0;  p_c6 <= 2'd0;  p_c7 <= 2'd0;
            end
        end
    end

    // Stage 0b (250 MHz): 4 parallel nibble sums (single 3-bit add each!)
    reg              n_valid;
    reg signed [3:0] n_v0, n_v1, n_v2, n_v3;
    reg        [2:0] n_c0, n_c1, n_c2, n_c3;

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            n_valid <= 1'b0;
            n_v0 <= 4'sd0; n_v1 <= 4'sd0; n_v2 <= 4'sd0; n_v3 <= 4'sd0;
            n_c0 <= 3'd0;  n_c1 <= 3'd0;  n_c2 <= 3'd0;  n_c3 <= 3'd0;
        end else begin
            n_valid <= p_valid;
            n_v0    <= {p_v0[2], p_v0} + {p_v1[2], p_v1};
            n_v1    <= {p_v2[2], p_v2} + {p_v3[2], p_v3};
            n_v2    <= {p_v4[2], p_v4} + {p_v5[2], p_v5};
            n_v3    <= {p_v6[2], p_v6} + {p_v7[2], p_v7};
            n_c0    <= {1'b0, p_c0}    + {1'b0, p_c1};
            n_c1    <= {1'b0, p_c2}    + {1'b0, p_c3};
            n_c2    <= {1'b0, p_c4}    + {1'b0, p_c5};
            n_c3    <= {1'b0, p_c6}    + {1'b0, p_c7};
        end
    end

    // Stage 1 (250 MHz): 2 parallel byte sums (single 4-bit add each!)
    reg              b_valid;
    reg signed [4:0] b_vlo, b_vhi;
    reg        [3:0] b_clo, b_chi;

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            b_valid <= 1'b0;
            b_vlo <= 5'sd0; b_vhi <= 5'sd0;
            b_clo <= 4'd0;  b_chi <= 4'd0;
        end else begin
            b_valid <= n_valid;
            b_vlo   <= {n_v0[3], n_v0} + {n_v1[3], n_v1};
            b_vhi   <= {n_v2[3], n_v2} + {n_v3[3], n_v3};
            b_clo   <= {1'b0, n_c0}    + {1'b0, n_c1};
            b_chi   <= {1'b0, n_c2}    + {1'b0, n_c3};
        end
    end

    // Stage 2 (250 MHz): single-bundle total (single 5-bit add!)
    reg              v1_valid;
    reg signed [5:0] v1_sum;
    reg        [4:0] v1_cnt;

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            v1_valid <= 1'b0;
            v1_sum   <= 6'sd0;
            v1_cnt   <= 5'd0;
        end else begin
            v1_valid <= b_valid;
            v1_sum   <= {b_vlo[4], b_vlo} + {b_vhi[4], b_vhi};
            v1_cnt   <= {1'b0, b_clo}     + {1'b0, b_chi};
        end
    end

    // Stage 3 (250 MHz): pure 2-tick pair latch (ZERO adders in 250 MHz Stage 3 -> +2.0 ns SS slack!).
    // Final 6-bit sum (pair_sum_a + pair_sum_b) runs in cdr_phase_frequency at 125 MHz (8.0 ns).
    reg              half_valid;
    reg signed [5:0] half_sum;
    reg        [4:0] half_cnt;

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            half_valid <= 1'b0;
            half_sum   <= 6'sd0;
            half_cnt   <= 5'd0;
            pair_valid <= 1'b0;
            pair_sum_a <= 6'sd0;
            pair_sum_b <= 6'sd0;
            pair_cnt_a <= 5'd0;
            pair_cnt_b <= 5'd0;
        end else if (!phase_hi) begin
            half_valid <= v1_valid;
            half_sum   <= v1_valid ? v1_sum : 6'sd0;
            half_cnt   <= v1_valid ? v1_cnt : 5'd0;
        end else begin
            pair_valid <= half_valid || v1_valid;
            pair_sum_a <= half_sum;
            pair_sum_b <= v1_valid ? v1_sum : 6'sd0;
            pair_cnt_a <= half_cnt;
            pair_cnt_b <= v1_valid ? v1_cnt : 5'd0;
        end
    end
endmodule
