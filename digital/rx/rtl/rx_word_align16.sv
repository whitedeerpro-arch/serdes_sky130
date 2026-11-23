// Word boundary for the physical 16-UI words (rx_word_map data_samples, bit0 oldest).  Word clock domain.
// The readout delivers an arbitrary 16-UI window of the bit stream; the boundary offset s (0..15) is
// found from TRAIN_HITS consecutive words in which the window starting s bits into the previous
// word equals TRAIN_WORD at the same s.  Output word = bits s .. s+15 of {current, previous}, bit0
// oldest, so it lags the input by one word.  Retraining: assert training_enable again.
// The recovered word clock tracks the far end (the PI follows the frequency offset), so the
// boundary does not drift; a lost lock (divider or counter disturbed) needs retraining.
module rx_word_align16 #(parameter [15:0] TRAIN_WORD=16'hb5e3, parameter integer TRAIN_HITS=4)(  // TRAIN_HITS 1..15
    input wire clk, rst_n, chunk_valid, training_enable,
    input wire [15:0] chunk,
    output reg [15:0] word_data,
    output reg word_valid, aligned,
    output reg [3:0] offset
);
    localparam [3:0] NHITS = TRAIN_HITS[3:0];
    reg [15:0] prev;
    reg [3:0] cand;
    reg [3:0] hits;
    reg found;
    reg [3:0] at;
    wire [31:0] stream = {chunk, prev};
    integer s;
    always @* begin
        found=0;at=0;
        for(s=15;s>=0;s=s-1) if(stream[s+:16]==TRAIN_WORD) begin found=1;at=s[3:0];end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            prev<=0;cand<=0;hits<=0;aligned<=0;offset<=0;word_data<=0;word_valid<=0;
        end else begin
            word_valid<=0;
            if(chunk_valid) begin
                prev<=chunk;
                if(training_enable) begin
                    if(found && at==cand && hits!=0) begin
                        if(hits<NHITS) hits<=hits+4'd1;
                        if(hits+4'd1>=NHITS) begin aligned<=1;offset<=at;end
                    end else if(found) begin cand<=at;hits<=1;aligned<=0; end
                    else begin hits<=0;aligned<=0; end
                end else if(aligned) begin
                    word_data<=stream[{1'b0,offset}+:16];word_valid<=1;
                end
            end
        end
    end
endmodule
