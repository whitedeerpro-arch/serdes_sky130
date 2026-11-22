// Timing-closed v2 rx_word_map (identical zero-comb-depth input register stage;
// only primed/bundle_valid use async rst_n to keep word_online reset fanout <= 16!).
module rx_word_map (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [31:0] phys,
    output reg  [15:0] data_samples,
    output reg  [15:0] edge_samples,
    output reg         previous_data,
    output reg         bundle_valid
);
    localparam integer A0 = 0, B0 = 1, AE1 = 2, BE1 = 3, A1 = 4, B1 = 5, AE0 = 6, BE0 = 7;
    reg [15:0] d, e_after;
    reg last_data, last_edge, primed;
    integer k;

    always @* begin
        for (k = 0; k < 4; k = k + 1) begin
            d[12-4*k] = phys[4*A0+k];  e_after[12-4*k] = phys[4*AE1+k];
            d[13-4*k] = phys[4*B1+k];  e_after[13-4*k] = phys[4*BE0+k];
            d[14-4*k] = phys[4*B0+k];  e_after[14-4*k] = phys[4*BE1+k];
            d[15-4*k] = phys[4*A1+k];  e_after[15-4*k] = phys[4*AE0+k];
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            primed       <= 1'b0;
            bundle_valid <= 1'b0;
        end else begin
            primed       <= 1'b1;
            bundle_valid <= primed;
        end
    end

    always @(posedge clk) begin
        data_samples  <= d;
        edge_samples  <= {e_after[14:0], last_edge};
        previous_data <= last_data;
        last_data     <= d[15];
        last_edge     <= e_after[15];
    end
endmodule
