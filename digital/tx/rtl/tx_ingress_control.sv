// Inputs are synchronous to word_clk; this block is not a CDC synchronizer.
module tx_ingress_control #(
    parameter [15:0] IDLE_WORD = 16'h0000,
    parameter integer WARMUP_FALLS = 1
) (
    input wire word_clk, input wire rst_n,
    input wire enable, input wire clock_good,
    input wire in_valid, input wire [15:0] in_data,
    output reg word_ready, output wire [15:0] capture_data,
    output wire capture_valid, output reg a_valid, output reg b_valid
);
    localparam integer COUNT_WIDTH = (WARMUP_FALLS <= 1) ? 1 : $clog2(WARMUP_FALLS);
    reg [COUNT_WIDTH-1:0] warmup_count;
    localparam integer LAST_COUNT_INT = WARMUP_FALLS - 1;
    localparam [COUNT_WIDTH-1:0] LAST_COUNT = LAST_COUNT_INT[COUNT_WIDTH-1:0];

    assign capture_valid = word_ready && in_valid;
    assign capture_data = capture_valid ? in_data : IDLE_WORD;

    always @(negedge word_clk or negedge rst_n) begin
        if (!rst_n) begin
            word_ready <= 1'b0;
            warmup_count <= {COUNT_WIDTH{1'b0}};
            b_valid <= 1'b0;
        end else begin
            b_valid <= a_valid;
            if (!enable || !clock_good) begin
                word_ready <= 1'b0;
                warmup_count <= {COUNT_WIDTH{1'b0}};
            end else if (!word_ready) begin
                if (warmup_count == LAST_COUNT) begin
                    word_ready <= 1'b1;
                end else begin
                    warmup_count <= warmup_count + 1'b1;
                end
            end
        end
    end

    always @(posedge word_clk or negedge rst_n) begin
        if (!rst_n) a_valid <= 1'b0;
        else a_valid <= capture_valid;
    end
endmodule
