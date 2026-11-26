// Native 32-UI BBPD window voter running on rx_clk_div2 (125 MHz @ 4G / 156.25 MHz @ 5G, 6.40 ns!).
// Zero 250/312.5 MHz voting logic! 3 ultra-shallow registered stages (~2.5 ns each << 6.40 ns):
//   Stage 0: 32-bit trans/late/early -> 16 parallel 2-bit pair votes & counts (~4 gates)
//   Stage 1: 4 parallel 8-UI byte sums (signed 5b vote & 4b count each, ~5 gates)
//   Stage 2: 32-UI total vote_sum (signed 7b), trans_cnt (6b), plus REGISTERED err_pos/err_neg/has_trans!
// Registering err_pos/err_neg/has_trans here removes the entire 6-gate vote-add prefix from cdr_phase_frequency!
module bbpd_window_vote32 (
    input  wire              ctrl_clk,
    input  wire              rst_n_0,
    input  wire              rst_n_1,
    input  wire              bundle_valid,
    input  wire              previous_data,
    input  wire       [31:0] data_samples,
    input  wire       [31:0] edge_samples,
    output reg               vote_valid,
    output reg               has_trans,
    output reg               err_pos,
    output reg               err_neg,
    output reg signed [6:0]  vote_sum,
    output reg        [5:0]  trans_cnt
);
    // Stage 0 (ONLY 2 gates on 3.20 ns half-cycle rx_word_clk -> rx_clk_div2 crossing!):
    // Register early/late 32-bit flags directly; trans_r = late_r | early_r (mutually exclusive!).
    wire [31:0] before_bits = {data_samples[30:0], previous_data};
    wire [31:0] trans_c     = before_bits ^ data_samples;
    wire [31:0] diff_ed     = edge_samples ^ data_samples;
    wire [31:0] late_c      = trans_c & ~diff_ed;
    wire [31:0] early_c     = trans_c &  diff_ed;

    reg        v0_valid;
    reg [31:0] late_r, early_r;

    always @(posedge ctrl_clk or negedge rst_n_0) begin
        if (!rst_n_0) begin
            v0_valid <= 1'b0;
            late_r   <= 32'd0;
            early_r  <= 32'd0;
        end else begin
            v0_valid <= bundle_valid;
            late_r   <= bundle_valid ? late_c  : 32'd0;
            early_r  <= bundle_valid ? early_c : 32'd0;
        end
    end

    // Stage 1 (full 6.40 ns rx_clk_div2): 8 parallel 4-UI nibble votes & counts (~4 gates!)
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

    wire [31:0] trans_r = late_r | early_r;
    wire signed [2:0] pv [0:15];
    wire        [1:0] pc [0:15];
    genvar g;
    generate
        for (g = 0; g < 16; g = g + 1) begin : gen_pair
            assign pv[g] = vote2(late_r[2*g +: 2], early_r[2*g +: 2]);
            assign pc[g] = pop2(trans_r[2*g +: 2]);
        end
    endgenerate

    reg              n_valid;
    reg signed [3:0] n_v [0:7];
    reg        [2:0] n_c [0:7];

    integer i;
    always @(posedge ctrl_clk or negedge rst_n_0) begin
        if (!rst_n_0) begin
            n_valid <= 1'b0;
            for (i = 0; i < 8; i = i + 1) begin
                n_v[i] <= 4'sd0;
                n_c[i] <= 3'd0;
            end
        end else begin
            n_valid <= v0_valid;
            for (i = 0; i < 8; i = i + 1) begin
                n_v[i] <= {pv[2*i][2], pv[2*i]} + {pv[2*i+1][2], pv[2*i+1]};
                n_c[i] <= {1'b0, pc[2*i]}       + {1'b0, pc[2*i+1]};
            end
        end
    end

    // Stage 1: 2 parallel 16-UI half sums via 2-level 4b+5b add tree (~6 gates!)
    wire signed [4:0] b_v0 = {n_v[0][3], n_v[0]} + {n_v[1][3], n_v[1]};
    wire signed [4:0] b_v1 = {n_v[2][3], n_v[2]} + {n_v[3][3], n_v[3]};
    wire signed [4:0] b_v2 = {n_v[4][3], n_v[4]} + {n_v[5][3], n_v[5]};
    wire signed [4:0] b_v3 = {n_v[6][3], n_v[6]} + {n_v[7][3], n_v[7]};

    wire [3:0] b_c0 = {1'b0, n_c[0]} + {1'b0, n_c[1]};
    wire [3:0] b_c1 = {1'b0, n_c[2]} + {1'b0, n_c[3]};
    wire [3:0] b_c2 = {1'b0, n_c[4]} + {1'b0, n_c[5]};
    wire [3:0] b_c3 = {1'b0, n_c[6]} + {1'b0, n_c[7]};

    reg              h_valid;
    reg signed [5:0] h_vlo, h_vhi;
    reg        [4:0] h_clo, h_chi;

    always @(posedge ctrl_clk or negedge rst_n_1) begin
        if (!rst_n_1) begin
            h_valid <= 1'b0;
            h_vlo   <= 6'sd0;
            h_vhi   <= 6'sd0;
            h_clo   <= 5'd0;
            h_chi   <= 5'd0;
        end else begin
            h_valid <= n_valid;
            h_vlo   <= {b_v0[4], b_v0} + {b_v1[4], b_v1};
            h_vhi   <= {b_v2[4], b_v2} + {b_v3[4], b_v3};
            h_clo   <= {1'b0, b_c0}    + {1'b0, b_c1};
            h_chi   <= {1'b0, b_c2}    + {1'b0, b_c3};
        end
    end

    // Stage 2: single 3+4 carry-select add of h_vlo + h_vhi + direct 2-gate tot_ht (~5 gates, 0 extra cycles!)
    wire [3:0] v_lo  = {1'b0, h_vlo[2:0]} + {1'b0, h_vhi[2:0]};
    wire [3:0] v_hi0 = {h_vlo[5], h_vlo[5:3]} + {h_vhi[5], h_vhi[5:3]};
    wire [3:0] v_hi1 = {h_vlo[5], h_vlo[5:3]} + {h_vhi[5], h_vhi[5:3]} + 4'd1;
    wire signed [6:0] tot_v = $signed({v_lo[3] ? v_hi1 : v_hi0, v_lo[2:0]});

    wire [3:0] c_lo  = {1'b0, h_clo[2:0]} + {1'b0, h_chi[2:0]};
    wire [2:0] c_hi0 = {1'b0, h_clo[4:3]} + {1'b0, h_chi[4:3]};
    wire [2:0] c_hi1 = {1'b0, h_clo[4:3]} + {1'b0, h_chi[4:3]} + 3'd1;
    wire [5:0] tot_c = {c_lo[3] ? c_hi1 : c_hi0, c_lo[2:0]};

    wire tot_ht = h_valid && ((|h_clo) || (|h_chi));

    always @(posedge ctrl_clk or negedge rst_n_1) begin
        if (!rst_n_1) begin
            vote_valid <= 1'b0;
            has_trans  <= 1'b0;
            err_pos    <= 1'b0;
            err_neg    <= 1'b0;
            vote_sum   <= 7'sd0;
            trans_cnt  <= 6'd0;
        end else begin
            vote_valid <= h_valid;
            has_trans  <= tot_ht;
            err_pos    <= tot_ht && (!tot_v[6]) && (tot_v[5:0] != 6'd0);
            err_neg    <= tot_ht && tot_v[6];
            vote_sum   <= tot_v;
            trans_cnt  <= tot_c;
        end
    end
endmodule
