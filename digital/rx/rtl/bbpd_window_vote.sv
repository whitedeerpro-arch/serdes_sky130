// Retimed, demultiplexed chronological samples ONLY. Bit0 is oldest.
// edge[k] is between data[k-1] (previous_data at k0) and data[k].
// Positive vote means clocks are late: advance PI code. No transition -> no vote.
// Analog metastability, CML-to-CMOS, demux and CDC are outside this module.
module bbpd_window_vote #(parameter integer SAMPLES=16,
    parameter integer COUNT_W=$clog2(SAMPLES+1), SUM_W=COUNT_W+1)(
    input wire ctrl_clk, rst_n, bundle_valid, previous_data,
    input wire [SAMPLES-1:0] data_samples, edge_samples,
    output reg vote_valid,
    output reg signed [SUM_W-1:0] vote_sum,
    output reg [COUNT_W-1:0] transition_count
);
    integer i;
    reg before_bit;
    reg signed [SUM_W-1:0] sum;
    reg [COUNT_W-1:0] count;
    always @* begin
        sum=0;count=0;before_bit=previous_data;
        for(i=0;i<SAMPLES;i=i+1) begin
            if(before_bit!=data_samples[i]) begin
                count=count+1'b1;
                if(edge_samples[i]==data_samples[i]) sum=sum+1'b1;
                else sum=sum-1'b1;
            end
            before_bit=data_samples[i];
        end
    end
    always @(posedge ctrl_clk or negedge rst_n) begin
        if(!rst_n) begin vote_valid<=0;vote_sum<=0;transition_count<=0;end
        else begin
            vote_valid<=bundle_valid;
            if(bundle_valid) begin vote_sum<=sum;transition_count<=count;end
        end
    end
endmodule
