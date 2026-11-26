// Direct 1:1 chronological capture matching analog/rx/cmos_rx/spice/rx_cmos_deser16.spice (v3.2):
//   phys[15:0]  = wd[15:0] (chronological data: wd[0] oldest .. wd[15] newest)
//   phys[31:16] = we[15:0] (chronological pre-data edges: we[k] lies strictly between wd[k-1] and wd[k];
//                           we[0] = e3_4 lies between previous word's wd[15] and current wd[0])
// Zero-comb-depth input register stage; only primed/bundle_valid use async rst_n (fanout <= 2).
module rx_word_map (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [31:0] phys,
    output reg  [15:0] data_samples,
    output reg  [15:0] edge_samples,
    output reg         previous_data,
    output reg         bundle_valid
);
    reg last_data, primed;

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
        data_samples  <= phys[15:0];
        edge_samples  <= phys[31:16];
        previous_data <= last_data;
        last_data     <= phys[15];
    end
endmodule
