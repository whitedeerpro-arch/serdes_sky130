// Recovered-word -> host-clock CDC with finite buffering.
// w_valid is a word-arrival strobe; an arrival while full is rejected and sets
// w_overflow until common reset. The raw receiver cannot be backpressured.
// Start an epoch only after w_online. Both clocks share arst_n; resetting one
// side alone is unsupported. Data is meaningful only with r_valid.
// Frequency-offset compensation / idle insertion or deletion is external.
module rx_async_word_fifo #(
    parameter integer DATA_WIDTH = 16,
    parameter integer ADDR_BITS = 4       // >= 1, depth = 2**ADDR_BITS
) (
    input wire w_clk, r_clk, arst_n,
    input wire w_valid,
    input wire [DATA_WIDTH-1:0] w_data,
    output wire w_ready, w_online,
    output reg w_overflow,
    output wire r_valid, r_online, r_overflow,
    output wire [DATA_WIDTH-1:0] r_data,
    input wire r_ready
);
    localparam integer PTR_BITS = ADDR_BITS + 1;
    localparam [PTR_BITS-1:0] FULL_MASK = {2'b11, {(ADDR_BITS-1){1'b0}}};
    reg [DATA_WIDTH-1:0] mem [0:(2**ADDR_BITS)-1];

    // Asynchronous assertion, separate synchronous release in each clock domain.
    (* ASYNC_REG = "TRUE" *) reg [1:0] w_reset_pipe, r_reset_pipe;
    always @(posedge w_clk or negedge arst_n)
        if (!arst_n) w_reset_pipe <= 0;
        else w_reset_pipe <= {w_reset_pipe[0], 1'b1};
    always @(posedge r_clk or negedge arst_n)
        if (!arst_n) r_reset_pipe <= 0;
        else r_reset_pipe <= {r_reset_pipe[0], 1'b1};
    wire w_reset_n = w_reset_pipe[1];
    wire r_reset_n = r_reset_pipe[1];

    (* ASYNC_REG = "TRUE" *) reg [1:0] r_up_w, w_up_r;
    (* ASYNC_REG = "TRUE" *) reg [1:0] overflow_r;
    (* ASYNC_REG = "TRUE" *) reg [PTR_BITS-1:0] r_gray_w1, r_gray_w2;
    (* ASYNC_REG = "TRUE" *) reg [PTR_BITS-1:0] w_gray_r1, w_gray_r2;
    reg [PTR_BITS-1:0] w_bin, w_gray, r_bin, r_gray;
    reg full, empty;
    assign w_online = w_reset_n && r_up_w[1];
    assign r_online = r_reset_n && w_up_r[1];
    assign w_ready = w_online && !full;
    assign r_valid = r_online && !empty;
    assign r_overflow = overflow_r[1];
    wire w_take = w_valid && w_ready;
    wire r_take = r_valid && r_ready;
    wire [PTR_BITS-1:0] w_next = w_bin + {{ADDR_BITS{1'b0}}, w_take};
    wire [PTR_BITS-1:0] r_next = r_bin + {{ADDR_BITS{1'b0}}, r_take};
    wire [PTR_BITS-1:0] w_gray_next = (w_next >> 1) ^ w_next;
    wire [PTR_BITS-1:0] r_gray_next = (r_next >> 1) ^ r_next;

    always @(posedge w_clk or negedge w_reset_n) begin
        if (!w_reset_n) begin
            r_up_w <= 0; r_gray_w1 <= 0; r_gray_w2 <= 0;
        end else begin
            r_up_w <= {r_up_w[0], r_reset_n};
            r_gray_w1 <= r_gray; r_gray_w2 <= r_gray_w1;
        end
    end
    always @(posedge r_clk or negedge r_reset_n) begin
        if (!r_reset_n) begin
            w_up_r <= 0; w_gray_r1 <= 0; w_gray_r2 <= 0; overflow_r <= 0;
        end else begin
            w_up_r <= {w_up_r[0], w_reset_n};
            w_gray_r1 <= w_gray; w_gray_r2 <= w_gray_r1;
            overflow_r <= {overflow_r[0], w_overflow};
        end
    end
    always @(posedge w_clk or negedge w_reset_n) begin
        if (!w_reset_n) begin
            w_bin <= 0; w_gray <= 0; full <= 0; w_overflow <= 0;
        end else begin
            w_bin <= w_next; w_gray <= w_gray_next;
            full <= (w_gray_next == (r_gray_w2 ^ FULL_MASK));
            if (w_online && w_valid && !w_ready) w_overflow <= 1;
        end
    end
    always @(posedge r_clk or negedge r_reset_n) begin
        if (!r_reset_n) begin
            r_bin <= 0; r_gray <= 0; empty <= 1;
        end else begin
            r_bin <= r_next; r_gray <= r_gray_next;
            empty <= (r_gray_next == w_gray_r2);
        end
    end
    always @(posedge w_clk)
        if (w_take) mem[w_bin[ADDR_BITS-1:0]] <= w_data;
    assign r_data = mem[r_bin[ADDR_BITS-1:0]];
endmodule
