`timescale 1ns/1ps
// TX 32-bit Host -> Native 8x32 Async FIFO (256-bit) -> 16-bit Real-Time SerDes Bridge
// - Supports 4 Gb/s (250 MHz host -> 250 MHz TX word, exact 1/2 host_ready duty)
// - Supports 5 Gb/s (250 MHz host -> 312.5 MHz TX word, exact 5/8 host_ready duty)
// - Half-word split happens on the TX side: FIFO reads at 125 MHz (4G) / 156.25 MHz (5G)
// - Atomic 32-bit word emission: never tears a 32-bit word; emits IDLE_WORD on empty/prefill
module tx_32to16_bridge #(
    parameter [15:0] IDLE_WORD = 16'hBC50,
    parameter [2:0]  PREFILL_WORDS = 3'd2
) (
    // Host domain (250 MHz, 32-bit = 1 full word)
    input  wire        host_clk,
    input  wire        host_rst_n,
    input  wire        host_valid,
    output wire        host_ready,
    input  wire [31:0] host_data,
    output wire [3:0]  host_fifo_level,

    // TX local word domain (250 MHz @ 4G, 312.5 MHz @ 5G, 16-bit real-time)
    input  wire        tx_clk,
    input  wire        tx_rst_n,
    input  wire        tx_enable,
    output reg  [15:0] tx_word16,
    output reg         tx_is_idle,
    output reg  [15:0] tx_underrun_cnt
);
    wire        fifo_rvalid;
    wire [31:0] fifo_rdata;
    wire [3:0]  tx_fifo_level;

    // Half-word phase: 0 = need new 32-bit word (emit lo16), 1 = emit stored hi16
    reg        half_q;
    reg [15:0] hi16_q;
    reg        primed_q;

    wire start_ok  = primed_q ? fifo_rvalid : (tx_fifo_level >= {1'b0, PREFILL_WORDS});
    wire pop_word  = tx_enable & (~half_q) & start_ok & fifo_rvalid;

    async_fifo_8x32 u_tx_fifo (
        .wclk   (host_clk),
        .wrst_n (host_rst_n),
        .wvalid (host_valid),
        .wready (host_ready),
        .wdata  (host_data),
        .wlevel (host_fifo_level),
        .rclk   (tx_clk),
        .rrst_n (tx_rst_n),
        .rvalid (fifo_rvalid),
        .rready (pop_word),
        .rdata  (fifo_rdata),
        .rlevel (tx_fifo_level)
    );

    always @(posedge tx_clk or negedge tx_rst_n) begin
        if (!tx_rst_n) begin
            half_q          <= 1'b0;
            hi16_q          <= 16'd0;
            primed_q        <= 1'b0;
            tx_word16       <= IDLE_WORD;
            tx_is_idle      <= 1'b1;
            tx_underrun_cnt <= 16'd0;
        end else if (!tx_enable) begin
            half_q          <= 1'b0;
            primed_q        <= 1'b0;
            tx_word16       <= IDLE_WORD;
            tx_is_idle      <= 1'b1;
        end else begin
            if (half_q) begin
                // Second half of an already-popped 32-bit word: always atomic
                tx_word16  <= hi16_q;
                tx_is_idle <= 1'b0;
                half_q     <= 1'b0;
            end else if (pop_word) begin
                primed_q   <= 1'b1;
                tx_word16  <= fifo_rdata[15:0];
                hi16_q     <= fifo_rdata[31:16];
                tx_is_idle <= 1'b0;
                half_q     <= 1'b1;
            end else begin
                tx_word16  <= IDLE_WORD;
                tx_is_idle <= 1'b1;
                if (primed_q) begin
                    tx_underrun_cnt <= tx_underrun_cnt + 16'd1;
                end
            end
        end
    end
endmodule
