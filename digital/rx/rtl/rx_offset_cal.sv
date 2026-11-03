// Foreground offset calibration of the four RX samplers (d0 d1 e0 e1), word clock domain (w).
// Precondition: zero differential input at the samplers (far-end TX in electrical idle; see
// docs/design/rx_pi_sampler.md), clocks running.  Each sampler has a 6-bit current-steering trim DAC
// (analog/rx/sampler/spice/rx_offset_dac.spice): a larger code raises its decision threshold, so a
// sampler that outputs mostly 1 at zero input needs a larger code.
// Successive approximation, all four lanes at once, MSB first: set the trial bit, wait SETTLE words
// (DAC settling + readout pipeline), count the lane's ones over NW words (8 samples per word per
// lane), keep the bit if ones > half.  SAR alone truncates (threshold left in [-1, 0) LSB).  After
// the bit-0 decision the lane knows the count of the code it just measured (c_known); it then
// measures the other neighbour of the truncation (c_known + 1 if bit 0 was kept, c_known - 1 if not)
// and keeps whichever count is closer to half: rounding when noise dithers the decisions.  Ties:
// counts on opposite sides (no noise, the two codes straddle zero) keep c_known; equal counts on the
// same side (offset at or beyond the DAC end) take the code toward zero, so such a lane saturates.
// Lanes in phys (rx_word_map order a0 b0 ae1 be1 a1 b1 ae0 be0, 4 outputs each): sampler d0 feeds
// demux outputs a0 and b0, d1 -> a1 b1, e0 -> ae0 be0, e1 -> ae1 be1.
// codes = {e1, e0, d1, d0}, 6 bits each; 32 (mid) after reset.
module rx_offset_cal #(parameter integer NW = 16, SETTLE = 8) (
    input wire clk, rst_n, start,
    input wire [31:0] phys,
    output wire [23:0] codes,
    output reg busy, done
);
    localparam integer CW = 12;                 // count width: 8 * NW <= 4095
    localparam [CW-1:0] HALF = 4 * NW;
    reg [5:0] code [0:3];
    reg [5:0] c_known [0:3];
    reg [CW-1:0] n_known [0:3];
    reg [CW-1:0] ones [0:3];
    reg [2:0] bitpos;
    reg [7:0] wcnt;
    reg counting, final_step;
    wire [7:0] lane_bits [0:3];
    assign lane_bits[0] = {phys[7:4], phys[3:0]};       // a0 b0
    assign lane_bits[1] = {phys[23:20], phys[19:16]};   // a1 b1
    assign lane_bits[2] = {phys[31:28], phys[27:24]};   // ae0 be0
    assign lane_bits[3] = {phys[15:12], phys[11:8]};    // ae1 be1
    assign codes = {code[3], code[2], code[1], code[0]};

    function [3:0] pop8(input [7:0] x);
        integer i;
        begin
            pop8 = 0;
            for (i = 0; i < 8; i = i + 1) pop8 = pop8 + {3'b000, x[i]};
        end
    endfunction

    function [CW-1:0] half_dev(input [CW-1:0] n);   // |n - HALF|
        half_dev = (n > HALF) ? n - HALF : HALF - n;
    endfunction

    integer l;
    reg [CW-1:0] sum [0:3];
    always @* for (l = 0; l < 4; l = l + 1) sum[l] = ones[l] + pop8(lane_bits[l]);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy <= 0; done <= 0; bitpos <= 0; wcnt <= 0; counting <= 0; final_step <= 0;
            for (l = 0; l < 4; l = l + 1) begin code[l] <= 6'd32; c_known[l] <= 0; n_known[l] <= 0; ones[l] <= 0; end
        end else if (start && !busy) begin
            busy <= 1; done <= 0; bitpos <= 5; wcnt <= 0; counting <= 0; final_step <= 0;
            for (l = 0; l < 4; l = l + 1) begin code[l] <= 6'b100000; ones[l] <= 0; end
        end else if (busy) begin
            if (!counting) begin                                  // settling: discard words
                wcnt <= (wcnt == SETTLE - 1) ? 8'd0 : wcnt + 8'd1;
                if (wcnt == SETTLE - 1) begin
                    counting <= 1;
                    for (l = 0; l < 4; l = l + 1) ones[l] <= 0;
                end
            end else if (wcnt != NW - 1) begin                    // counting
                wcnt <= wcnt + 8'd1;
                for (l = 0; l < 4; l = l + 1) ones[l] <= sum[l];
            end else begin                                        // last counted word: decide
                wcnt <= 0; counting <= 0;
                if (!final_step && bitpos != 0) begin
                    for (l = 0; l < 4; l = l + 1) begin
                        if (sum[l] <= HALF) code[l][bitpos] <= 1'b0;
                        code[l][bitpos - 1] <= 1'b1;
                    end
                    bitpos <= bitpos - 3'd1;
                end else if (!final_step) begin                   // bit 0: remember, go to the neighbour
                    final_step <= 1;
                    for (l = 0; l < 4; l = l + 1) begin
                        c_known[l] <= code[l];
                        n_known[l] <= sum[l];
                        if (sum[l] > HALF) code[l] <= (code[l] == 6'd63) ? code[l] : code[l] + 6'd1;
                        else code[l] <= code[l] - 6'd1;          // bit 0 cleared (code[0] was 1)
                    end
                end else begin                                    // neighbour measured: choose
                    final_step <= 0; busy <= 0; done <= 1;
                    // closer count wins; on a tie with both counts on the same side of half (both
                    // thresholds on one side of zero: offset at or beyond the DAC end) the code
                    // that moves the threshold toward zero wins; otherwise c_known stays
                    for (l = 0; l < 4; l = l + 1)
                        if (half_dev(sum[l]) < half_dev(n_known[l])) ;
                        else if (sum[l] == n_known[l] && sum[l] <= HALF && code[l] < c_known[l]) ;
                        else if (sum[l] == n_known[l] && sum[l] > HALF && code[l] > c_known[l]) ;
                        else code[l] <= c_known[l];
                end
            end
        end
    end
endmodule
