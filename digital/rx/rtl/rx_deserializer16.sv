// Chronological retimed CMOS pair: bit0 first, bit1 second. Recovered pair clock.
// Programmable repeated training word defines bit/word boundary; not 8b/10b.
// Physical high-speed sample alignment and timing closure are external.
module rx_deserializer16 #(parameter [15:0] TRAIN_WORD=16'hb5e3,
    parameter integer TRAIN_HITS=4)(
    input wire pair_clk, rst_n, pair_valid, training_enable,
    input wire [1:0] pair_bits,
    output reg [15:0] word_data,
    output reg word_valid, aligned
);
    reg [15:0] rolling, next_rolling;
    reg [4:0] age, next_age;
    reg [3:0] phase, next_phase;
    reg [31:0] hits, next_hits;
    reg next_aligned, emit;
    reg [15:0] emitted;
    integer j;
    always @* begin
        next_rolling=rolling;next_age=age;next_phase=phase;
        next_hits=hits;next_aligned=aligned;emit=0;emitted=word_data;
        for(j=0;j<2;j=j+1) begin
            next_rolling={pair_bits[j],next_rolling[15:1]};
            if(next_age<17) next_age=next_age+1'b1;
            next_phase=next_phase+1'b1;
            if(training_enable && next_rolling==TRAIN_WORD) begin
                if(next_age==16) begin if(next_hits<TRAIN_HITS)next_hits=next_hits+1'b1;end
                else next_hits=1;
                next_age=0;next_phase=0;
                if(next_hits>=TRAIN_HITS)next_aligned=1;
            end
            if(!training_enable && next_aligned && next_phase==0) begin emit=1;emitted=next_rolling;end
        end
    end
    always @(posedge pair_clk or negedge rst_n) begin
        if(!rst_n) begin rolling<=0;age<=17;phase<=0;hits<=0;word_data<=0;word_valid<=0;aligned<=0;end
        else begin
            word_valid<=0;
            if(pair_valid) begin
                rolling<=next_rolling;age<=next_age;phase<=next_phase;hits<=next_hits;
                aligned<=next_aligned;word_valid<=emit;if(emit)word_data<=emitted;
            end
        end
    end
endmodule
