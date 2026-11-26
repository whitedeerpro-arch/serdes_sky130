`timescale 1ns/1ps
// RX 16-bit Recovered Word -> IDLE Drop & 16->32 Pair Packer -> Native 8x32 Async FIFO -> 32-bit Host
// - Pushes to 8x32 async FIFO at half line-word rate (125 MHz @ 4G, 156.25 MHz @ 5G)
module rx_16to32_bridge #(
    parameter [15:0] IDLE_WORD = 16'hBC50
) (
    // RX recovered word domain (250 MHz @ 4G, 312.5 MHz @ 5G)
    input  wire        rx_clk,
    input  wire        rx_rst_n,
    input  wire        rx_aligned,
    input  wire        rx_word_valid,
    input  wire [15:0] rx_word16,
    output reg  [15:0] rx_idle_cnt,
    output reg  [15:0] rx_overflow_cnt,

    // Host domain (250 MHz, 32-bit = 1 full word)
    input  wire        host_clk,
    input  wire        host_rst_n,
    output wire        host_valid,
    input  wire        host_ready,
    output wire [31:0] host_data,
    output wire [3:0]  host_fifo_level
);
    reg        has_lo_q;
    reg [15:0] lo16_q;

    wire is_idle   = (rx_word16 == IDLE_WORD);
    wire payload_v = rx_aligned & rx_word_valid & (~is_idle);

    wire        fifo_wvalid = payload_v & has_lo_q;
    wire [31:0] fifo_wdata  = {rx_word16, lo16_q};
    wire        fifo_wready;
    wire [3:0]  rx_fifo_level_unused;

    async_fifo_8x32 u_rx_fifo (
        .wclk   (rx_clk),
        .wrst_n (rx_rst_n),
        .wvalid (fifo_wvalid),
        .wready (fifo_wready),
        .wdata  (fifo_wdata),
        .wlevel (rx_fifo_level_unused),
        .rclk   (host_clk),
        .rrst_n (host_rst_n),
        .rvalid (host_valid),
        .rready (host_ready),
        .rdata  (host_data),
        .rlevel (host_fifo_level)
    );

    always @(posedge rx_clk or negedge rx_rst_n) begin
        if (!rx_rst_n) begin
            has_lo_q        <= 1'b0;
            lo16_q          <= 16'd0;
            rx_idle_cnt     <= 16'd0;
            rx_overflow_cnt <= 16'd0;
        end else if (!rx_aligned) begin
            has_lo_q <= 1'b0;
        end else if (rx_word_valid) begin
            if (is_idle) begin
                rx_idle_cnt <= rx_idle_cnt + 16'd1;
            end else if (!has_lo_q) begin
                lo16_q   <= rx_word16;
                has_lo_q <= 1'b1;
            end else begin
                has_lo_q <= 1'b0;
                if (!fifo_wready) begin
                    rx_overflow_cnt <= rx_overflow_cnt + 16'd1;
                end
            end
        end
    end
endmodule
