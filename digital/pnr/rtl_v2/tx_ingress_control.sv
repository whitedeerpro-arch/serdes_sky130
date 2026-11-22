// Timing-closed v2 TX ingress control (250 MHz / 4.0 ns full-cycle posedge design).
// Eliminates v1's negedge-to-posedge half-cycle path (dfrtn_1 -> capture_data/a_valid).
//
// Latency & contract:
// - Exact same port list and parameters as v1.
// - All state and outputs (word_ready, capture_valid, capture_data, a_valid, b_valid)
//   are synchronously registered on posedge word_clk with asynchronous active-low rst_n.
// - Warmup: after WARMUP_FALLS consecutive posedge word_clk edges with enable && clock_good,
//   word_ready asserts (1-cycle synchronous warmup when WARMUP_FALLS==1).
// - Capture pipeline (1-cycle registered capture):
//   * capture_valid <= word_ready && in_valid
//   * capture_data  <= (word_ready && in_valid) ? in_data : IDLE_WORD
//   * a_valid       <= capture_valid
//   * b_valid       <= a_valid
// - Disabling enable or losing clock_good deasserts word_ready on the next posedge while
//   allowing already-captured words in capture/a_valid/b_valid to drain cleanly.
// - Async rst_n immediately clears all outputs (capture_data = IDLE_WORD).
module tx_ingress_control #(
    parameter [15:0] IDLE_WORD = 16'h0000,
    parameter integer WARMUP_FALLS = 1
) (
    input  wire        word_clk,
    input  wire        rst_n,
    input  wire        enable,
    input  wire        clock_good,
    input  wire        in_valid,
    input  wire [15:0] in_data,
    output reg         word_ready,
    output reg  [15:0] capture_data,
    output reg         capture_valid,
    output reg         a_valid,
    output reg         b_valid
);
    localparam integer COUNT_WIDTH = (WARMUP_FALLS <= 1) ? 1 : $clog2(WARMUP_FALLS);
    localparam integer LAST_COUNT_INT = (WARMUP_FALLS <= 1) ? 0 : (WARMUP_FALLS - 1);
    localparam [COUNT_WIDTH-1:0] LAST_COUNT = LAST_COUNT_INT[COUNT_WIDTH-1:0];

    reg [COUNT_WIDTH-1:0] warmup_count;
    wire accept_word = word_ready && in_valid;

    always @(posedge word_clk or negedge rst_n) begin
        if (!rst_n) begin
            word_ready    <= 1'b0;
            warmup_count  <= {COUNT_WIDTH{1'b0}};
            capture_valid <= 1'b0;
            capture_data  <= IDLE_WORD;
            a_valid       <= 1'b0;
            b_valid       <= 1'b0;
        end else begin
            // Registered capture stage + A/B in-flight pipeline tracking
            capture_valid <= accept_word;
            capture_data  <= accept_word ? in_data : IDLE_WORD;
            a_valid       <= capture_valid;
            b_valid       <= a_valid;

            // Warmup & readiness FSM (posedge-only, full 4.0 ns cycle)
            if (!enable || !clock_good) begin
                word_ready   <= 1'b0;
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
endmodule
