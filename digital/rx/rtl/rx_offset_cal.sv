// Foreground offset calibration of the four RX samplers (d0 d1 e0 e1), word clock domain (w).
// Precondition: zero differential input at the samplers (far-end TX in electrical idle; see
// docs/design/rx_pi_sampler.md), clocks running.  Each sampler has a 6-bit threshold trim
// (analog/rx/sampler/spice/rx_offset_trim.spice): a larger code raises its decision threshold, so a
// sampler that outputs mostly 1 at zero input needs a larger code.
// The sampler has memory at idle input: after a 1 it keeps deciding 1 until the threshold is raised
// HYST above the memory-free one, after a 0 until it is lowered HYST below (link_pvt bench, TT,
// analog/rx/sampler/tb/offset_dac/idle_sweep.py: 5 codes / about +-2.5 mV; the memory-free
// threshold is the one random data sees).  A single SAR lands anywhere in that band depending on its
// path (start-up cosim: 2-5 codes off).  So each lane gets two SAR passes, MSB first, 6 trials each:
//   pass 0: before every trial the lane's code is 0 for PRE words (it decides 1), then the trial code;
//           the lane stays 1 up to the upper band edge -> U = largest code still deciding 1;
//   pass 1: the same with code 63 before every trial (it decides 0) -> L = largest code deciding 1
//           from 0 (lower band edge - 1);
//   code = (U + L + 1) / 2: the band centre within 1 LSB (both edges truncate).
// A trial: PRE words at the precondition code, SETTLE words at the trial code (DAC settling +
// readout pipeline, discarded), NW words counted; the bit stays if ones > half.  From code 0 to the
// trial code bits are only set, from 63 only cleared, so no intermediate code (bit skew) lies beyond
// the trial code.  PRE >= 1.  With noise the edges blur and the two passes still average to the
// centre.  A lane beyond the DAC range saturates at 0 or 63 on the correct side.
// Lanes in phys (rx_word_map order a0 b0 ae1 be1 a1 b1 ae0 be0, 4 outputs each): sampler d0 feeds
// demux outputs a0 and b0, d1 -> a1 b1, e0 -> ae0 be0, e1 -> ae1 be1.
// codes = {e1, e0, d1, d0}, 6 bits each; 32 (mid) after reset.
// SEQ = 1 (default): one lane at a time; meanwhile the other three lanes' codes alternate 0 / 63 every
// word, so their decisions alternate 1 / 0 at zero input.  Reason: the four samplers share the input
// buffer and kick back into it (about 1 mV between "others all 1" and "others all 0"); alternating
// neighbours make the kickback average that of random data.  Time: 4 x 2 x 6 x (PRE + SETTLE + NW)
// words (SEQ = 0: a quarter).
module rx_offset_cal #(parameter integer NW = 16, SETTLE = 8, PRE = 1, SEQ = 1) (
    input wire clk, rst_n, start,
    input wire [31:0] phys,
    output wire [23:0] codes,
    output reg busy, done
);
    localparam integer CW = 12;                 // count width: 8 * NW <= 4095
    localparam [CW-1:0] HALF = 4 * NW;
    localparam [1:0] S_PRE = 0, S_SETTLE = 1, S_COUNT = 2;
    reg [5:0] code [0:3];
    reg [5:0] upper [0:3];                      // pass 0 result
    reg [CW-1:0] ones [0:3];
    reg [2:0] bitpos;
    reg [7:0] wcnt;
    reg [1:0] state;
    reg pass;
    reg [1:0] cur;                              // lane being calibrated (SEQ)
    reg dith;                                   // neighbour code toggle (SEQ)
    wire [3:0] act = SEQ ? (4'b0001 << cur) : 4'b1111;
    wire [7:0] lane_bits [0:3];
    assign lane_bits[0] = {phys[7:4], phys[3:0]};       // a0 b0
    assign lane_bits[1] = {phys[23:20], phys[19:16]};   // a1 b1
    assign lane_bits[2] = {phys[31:28], phys[27:24]};   // ae0 be0
    assign lane_bits[3] = {phys[15:12], phys[11:8]};    // ae1 be1
    wire [5:0] out_code [0:3];
    genvar g;
    generate for (g = 0; g < 4; g = g + 1) begin : outc
        assign out_code[g] = !busy ? code[g]
                           : !act[g] ? (dith ? 6'd63 : 6'd0)
                           : (state == S_PRE) ? (pass ? 6'd63 : 6'd0)
                           : code[g];
    end endgenerate
    assign codes = {out_code[3], out_code[2], out_code[1], out_code[0]};

    function [3:0] pop8(input [7:0] x);
        integer i;
        begin
            pop8 = 0;
            for (i = 0; i < 8; i = i + 1) pop8 = pop8 + {3'b000, x[i]};
        end
    endfunction

    function [6:0] centre(input [5:0] u, input [5:0] lo);   // (u + lo + 1) / 2, 7 bits before the shift
        centre = ({1'b0, u} + {1'b0, lo} + 7'd1) >> 1;
    endfunction

    integer l;
    reg [CW-1:0] sum [0:3];
    reg [5:0] edge_code [0:3];                  // code after this trial's decision
    always @* for (l = 0; l < 4; l = l + 1) begin
        sum[l] = ones[l] + pop8(lane_bits[l]);
        edge_code[l] = code[l];
        if (sum[l] <= HALF) edge_code[l][bitpos] = 1'b0;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy <= 0; done <= 0; bitpos <= 0; wcnt <= 0; state <= S_PRE; pass <= 0; cur <= 0; dith <= 0;
            for (l = 0; l < 4; l = l + 1) begin code[l] <= 6'd32; upper[l] <= 0; ones[l] <= 0; end
        end else if (start && !busy) begin
            busy <= 1; done <= 0; bitpos <= 5; wcnt <= 0; state <= S_PRE; pass <= 0; cur <= 0; dith <= 0;
            for (l = 0; l < 4; l = l + 1) begin code[l] <= 6'b100000; ones[l] <= 0; end
        end else if (busy) begin
            dith <= ~dith;
            case (state)
            S_PRE: begin                                          // precondition the lane's decision
                wcnt <= (wcnt == PRE - 1) ? 8'd0 : wcnt + 8'd1;
                if (wcnt == PRE - 1) state <= S_SETTLE;
            end
            S_SETTLE: begin                                       // trial code settling: discard words
                wcnt <= (wcnt == SETTLE - 1) ? 8'd0 : wcnt + 8'd1;
                if (wcnt == SETTLE - 1) begin
                    state <= S_COUNT;
                    for (l = 0; l < 4; l = l + 1) ones[l] <= 0;
                end
            end
            default: begin
                if (wcnt != NW - 1) begin                         // counting
                    wcnt <= wcnt + 8'd1;
                    for (l = 0; l < 4; l = l + 1) ones[l] <= sum[l];
                end else begin                                    // last counted word: decide
                    wcnt <= 0; state <= S_PRE;
                    if (bitpos != 0) begin
                        for (l = 0; l < 4; l = l + 1) if (act[l]) begin
                            code[l] <= edge_code[l];
                            code[l][bitpos - 1] <= 1'b1;
                        end
                        bitpos <= bitpos - 3'd1;
                    end else if (!pass) begin                     // upper edge found: second pass
                        for (l = 0; l < 4; l = l + 1) if (act[l]) begin upper[l] <= edge_code[l]; code[l] <= 6'b100000; end
                        pass <= 1; bitpos <= 5;
                    end else begin                                // lower edge found: centre
                        for (l = 0; l < 4; l = l + 1) if (act[l]) code[l] <= centre(upper[l], edge_code[l]);
                        pass <= 0; bitpos <= 5;
                        if (SEQ && cur != 2'd3) cur <= cur + 2'd1;    // next lane (its code is 32)
                        else begin busy <= 0; done <= 1; end
                    end
                end
            end
            endcase
        end
    end
endmodule
