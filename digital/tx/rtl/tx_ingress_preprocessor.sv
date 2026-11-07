// All inputs are in the PHY word clock domain.
module tx_ingress_preprocessor #(
    parameter [15:0] IDLE_WORD = 16'h0000,
    parameter integer WARMUP_FALLS = 1
)(
    input wire word_clk, rst_n, enable, clock_good,
    input wire mapping_valid, input wire [2:0] mapping_state,
    input wire in_valid, input wire [15:0] in_data,
    output wire word_ready, capture_valid, output wire [15:0] capture_data,
    output wire a_valid, b_valid, output reg [2:0] active_mapping_state
);
    wire [15:0] mapped_data;
    always @(negedge word_clk or negedge rst_n) begin
        if (!rst_n) active_mapping_state <= 3'b0;
        else if (!word_ready && enable && clock_good && mapping_valid)
            active_mapping_state <= mapping_state;
    end
    tx_word_remap_comb remap(.data_in(in_data), .state(active_mapping_state), .data_out(mapped_data));
    tx_ingress_control #(.IDLE_WORD(IDLE_WORD), .WARMUP_FALLS(WARMUP_FALLS)) guard (
        .word_clk(word_clk), .rst_n(rst_n), .enable(enable && mapping_valid),
        .clock_good(clock_good), .in_valid(in_valid), .in_data(mapped_data),
        .word_ready(word_ready), .capture_valid(capture_valid), .capture_data(capture_data),
        .a_valid(a_valid), .b_valid(b_valid));
endmodule
