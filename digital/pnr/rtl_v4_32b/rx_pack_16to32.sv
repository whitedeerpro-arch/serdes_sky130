// Ultra-thin phase-safe 16->32 RX boundary packer on rx_word_clk (v4.3).
// Generates dedicated clock-only rx_clk_div2 (rx_word_clk / 2: 125 MHz @ 4G / 156.25 MHz @ 5G)
// and packs 2 consecutive 16-bit (data, edge, prev) bundles into a 32-bit bundle strictly on
// rx_phase == 1 (falling edge of rx_clk_div2, 1 full rx_word_clk cycle away from posedge rx_clk_div2!).
// 4-bit nibble phase mirrors (fanout == 4 FFs each -> ZERO repeaters -> +0.35 ns @ 312.5 MHz ss_n40C_1v60!).
module rx_pack_16to32 (
    input  wire        rx_word_clk,
    input  wire        rst_n,
    input  wire        in_valid,
    input  wire [15:0] word_data,
    input  wire [15:0] word_edge,
    input  wire        prev_data,
    output wire        rx_clk_div2,
    output wire        rx_word_rst_n,
    output reg         pack_valid,
    output reg         pack_prev,
    output reg  [31:0] pack_data,
    output reg  [31:0] pack_edge
);
    // Per-domain external rst_n 2-FF sync + 2 leaves on rx_word_clk
    (* ASYNC_REG = "TRUE", keep = "true" *) reg rx_rst_s0, rx_rst_s1;
    (* keep = "true" *) reg rx_rst_a, rx_rst_b;
    always @(posedge rx_word_clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_rst_s0 <= 1'b0;
            rx_rst_s1 <= 1'b0;
            rx_rst_a  <= 1'b0;
            rx_rst_b  <= 1'b0;
        end else begin
            rx_rst_s0 <= 1'b1;
            rx_rst_s1 <= rx_rst_s0;
            rx_rst_a  <= rx_rst_s1;
            rx_rst_b  <= rx_rst_s1;
        end
    end
    assign rx_word_rst_n = rx_rst_a;

    // Dedicated 100% pure clock-only /2 divider + 24 nibble-level phase mirrors (fanout == 5 incl. self!)
    (* keep = "true" *) reg rx_div2_q;
    (* keep = "true" *) reg rx_ph_ctrl;
    (* keep = "true" *) reg [7:0]  rx_ph_lo;
    (* keep = "true" *) reg [15:0] rx_ph_pk;
    always @(posedge rx_word_clk or negedge rx_rst_a) begin
        if (!rx_rst_a) begin
            rx_div2_q  <= 1'b0;
            rx_ph_ctrl <= 1'b0;
            rx_ph_lo   <= 8'd0;
            rx_ph_pk   <= 16'd0;
        end else begin
            rx_div2_q  <= ~rx_ph_ctrl;
            rx_ph_ctrl <= ~rx_ph_ctrl;
            rx_ph_lo   <= ~rx_ph_lo;
            rx_ph_pk   <= ~rx_ph_pk;
        end
    end
    assign rx_clk_div2 = rx_div2_q;

    // 2-word holding registers (non-reset data/edge -> dfxtp, ZERO RESET_B fanout!)
    reg [15:0] lo_data;
    reg [15:0] lo_edge;
    reg        lo_prev;
    reg        have_lo;

    always @(posedge rx_word_clk or negedge rx_rst_b) begin
        if (!rx_rst_b) begin
            have_lo    <= 1'b0;
            pack_valid <= 1'b0;
            lo_prev    <= 1'b0;
            pack_prev  <= 1'b0;
        end else if (!rx_ph_ctrl) begin
            have_lo <= in_valid;
            lo_prev <= prev_data;
        end else begin
            pack_valid <= have_lo && in_valid;
            pack_prev  <= lo_prev;
        end
    end

    // Every phase FF drives ONLY 4 data/edge FFs (+ self = fanout 5 -> ZERO repeaters at 312.5 MHz 5G!)
    genvar gn;
    generate
        for (gn = 0; gn < 4; gn = gn + 1) begin : g_nib
            always @(posedge rx_word_clk) begin
                if (!rx_ph_lo[gn])     lo_data[gn*4 +: 4]          <= word_data[gn*4 +: 4];
                if (!rx_ph_lo[gn + 4]) lo_edge[gn*4 +: 4]          <= word_edge[gn*4 +: 4];
                if (rx_ph_pk[gn])      pack_data[gn*4 +: 4]        <= lo_data[gn*4 +: 4];
                if (rx_ph_pk[gn + 4])  pack_data[16 + gn*4 +: 4]   <= word_data[gn*4 +: 4];
                if (rx_ph_pk[gn + 8])  pack_edge[gn*4 +: 4]        <= lo_edge[gn*4 +: 4];
                if (rx_ph_pk[gn + 12]) pack_edge[16 + gn*4 +: 4]   <= word_edge[gn*4 +: 4];
            end
        end
    endgenerate
endmodule
