// Wrapper pairing rx_word_align32 + 8x32 async_word_fifo_32 with shared arst_n tree (D-H3)
module rx_word_host_32 #(
    parameter [15:0]  TRAIN_WORD = 16'hb5e3,
    parameter integer TRAIN_HITS = 4,
    parameter integer ADDR_BITS  = 3
) (
    input  wire        arst_n,
    input  wire        rx_clk_div2,
    input  wire        in_valid,
    input  wire [31:0] in_word,
    input  wire        training_enable,
    output wire        word_online,
    output wire        aligned,
    output wire [3:0]  offset,
    input  wire        host_clk,
    input  wire        host_ready,
    output wire [31:0] host_data,
    output wire        host_valid,
    output wire        host_online,
    output wire        host_error
);
    wire        w_rst_shared_n;
    /* verilator lint_off UNUSED */
    wire        r_rst_unused_n;
    wire        w_ready_unused;
    /* verilator lint_on UNUSED */
    wire [31:0] aligned_word;
    wire        aligned_valid;

    rx_word_align32 #(
        .TRAIN_WORD(TRAIN_WORD),
        .TRAIN_HITS(TRAIN_HITS)
    ) u_align (
        .clk            (rx_clk_div2),
        .rst_n          (w_rst_shared_n),
        .in_valid       (in_valid),
        .training_enable(training_enable),
        .in_word        (in_word),
        .out_word       (aligned_word),
        .out_valid      (aligned_valid),
        .aligned        (aligned),
        .offset         (offset)
    );

    async_word_fifo_32 #(
        .ADDR_BITS(ADDR_BITS),
        .WIDTH    (32)
    ) u_rx_fifo (
        .arst_n     (arst_n),
        .w_clk      (rx_clk_div2),
        .w_valid    (aligned_valid),
        .w_data     (aligned_word),
        .w_ready    (w_ready_unused),
        .w_online   (word_online),
        .w_rst_out_n(w_rst_shared_n),
        .r_clk      (host_clk),
        .r_ready    (host_ready),
        .r_data     (host_data),
        .r_valid    (host_valid),
        .r_online   (host_online),
        .r_error    (host_error),
        .r_rst_out_n(r_rst_unused_n)
    );
endmodule
