// Undo the serializer's divider-start-state bit permutation at the parallel input.
// The TX 500 MHz (/4, 4 states) and 1 GHz (/2, 2 states) dividers start in an
// unknown state relative to the 250 MHz word clock. Each state permutes the four
// bit pairs of both half-words in the same way and leaves the eye intact
// (measured in analog/tx/serializer/tb/clock_states, identical over the stress
// corners). state = {c500[1:0], c1g} comes from the start-up state detector;
// data_out is what the serializer must see for data_in bit0 to be sent first.
module tx_word_remap(
    input wire word_clk, rst_n,
    input wire [2:0] state,
    input wire [15:0] data_in,
    output reg [15:0] data_out
);
    wire [15:0] mapped;
    tx_word_remap_comb comb(.data_in(data_in), .state(state), .data_out(mapped));
    always @(posedge word_clk or negedge rst_n)
        if (!rst_n) data_out <= 16'b0; else data_out <= mapped;
endmodule

/* verilator lint_off DECLFILENAME */
module tx_word_remap_comb(
    input wire [15:0] data_in,
    input wire [2:0] state,
    output reg [15:0] data_out
);
    // Slot pair p is carried by input pair src[2p+1:2p] in each half-word.
    function automatic [7:0] src(input [2:0] s);
        case(s)
            3'd0: src={2'd3,2'd2,2'd1,2'd0};
            3'd1: src={2'd2,2'd3,2'd0,2'd1};
            3'd2: src={2'd3,2'd0,2'd1,2'd2};
            3'd3: src={2'd2,2'd1,2'd0,2'd3};
            3'd4: src={2'd1,2'd0,2'd3,2'd2};
            3'd5: src={2'd0,2'd1,2'd2,2'd3};
            3'd6: src={2'd1,2'd2,2'd3,2'd0};
            default: src={2'd0,2'd3,2'd2,2'd1};
        endcase
    endfunction
    reg [7:0] map;
    integer h,p;
    always @* begin
        map=src(state);data_out=16'b0;
        for(h=0;h<2;h=h+1)
            for(p=0;p<4;p=p+1)
                data_out[8*h+2*map[2*p+:2]+:2]=data_in[8*h+2*p+:2];
    end
endmodule
/* verilator lint_on DECLFILENAME */
