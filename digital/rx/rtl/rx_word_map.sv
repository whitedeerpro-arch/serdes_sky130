// Physical 16-UI word of the analog readout (analog/rx/sampler/spice/rx_readout_deser16.spice) ->
// chronological data / edge samples for bbpd_window_vote and rx_word_align16.  Word clock domain (w).
// phys[4*L+k] = output <lane>_<k> of the readout, lanes L in order a0 b0 ae1 be1 a1 b1 ae0 be0,
// k = 0 newest .. 3 oldest of the lane.  The chronological position (0 = oldest) of data output
// <lane>_<k> is a0: 12-4k, b1: 13-4k, b0: 14-4k, a1: 15-4k (fixed by the structure, checked on 45
// PVT conditions by tb/readout_deser).  Edge outputs pair with the data output of the same clock
// phase and stage (ae1-a0, be1-b0, ae0-a1, be0-b1) and lie just AFTER that data bit; the vote wants
// edge[k] between data[k-1] and data[k], so edge[0] is the previous word's last edge.
// The word is an arbitrary 16-UI window of the stream (divider / counter start states, PI position);
// rx_word_align16 finds the word boundary.  The vote does not need it.
module rx_word_map(
    input wire clk, rst_n,
    input wire [31:0] phys,
    output reg [15:0] data_samples, edge_samples,
    output reg previous_data, bundle_valid
);
    localparam integer A0=0, B0=1, AE1=2, BE1=3, A1=4, B1=5, AE0=6, BE0=7;
    reg [15:0] d, e_after;
    reg last_data, last_edge, primed;
    integer k;
    always @* begin
        for(k=0;k<4;k=k+1) begin
            d[12-4*k]=phys[4*A0+k];  e_after[12-4*k]=phys[4*AE1+k];
            d[13-4*k]=phys[4*B1+k];  e_after[13-4*k]=phys[4*BE0+k];
            d[14-4*k]=phys[4*B0+k];  e_after[14-4*k]=phys[4*BE1+k];
            d[15-4*k]=phys[4*A1+k];  e_after[15-4*k]=phys[4*AE0+k];
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            data_samples<=0;edge_samples<=0;previous_data<=0;bundle_valid<=0;last_data<=0;last_edge<=0;primed<=0;
        end else begin
            data_samples<=d;
            edge_samples<={e_after[14:0],last_edge};
            previous_data<=last_data;
            last_data<=d[15];last_edge<=e_after[15];
            primed<=1;bundle_valid<=primed;      // first word has no predecessor
        end
    end
endmodule
