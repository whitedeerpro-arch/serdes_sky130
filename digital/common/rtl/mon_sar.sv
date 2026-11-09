// Successive-approximation search of a W-bit threshold code against an external comparator.
// The comparator answers cmp = 1 when the sensed quantity is at or above the threshold of the code on `code`
// (asynchronous: synchronized here).  From the MSB down, each bit is set, the analog side is given `settle`
// clk cycles (ladder mux, comparator delay, plus the synchronizer), and the bit is kept when cmp = 1.
// Result: the largest code whose threshold is at or below the quantity (0 when even code 0 is above it, then
// `under` = 1; `over` = 1 when the quantity is above the top threshold).  The thresholds must rise with the code.
module mon_sar #(
    parameter integer W = 4,
    parameter integer SW = 8
) (
    input wire clk, rst_n, start,
    input wire [SW-1:0] settle,
    input wire cmp_async,
    output reg [W-1:0] code,
    output reg busy, valid, under, over
);
    wire cmp;
    mon_sync #(.W(1)) u_sync (.clk(clk), .rst_n(rst_n), .d(cmp_async), .q(cmp));
    localparam integer BW = (W < 2) ? 1 : $clog2(W + 1);
    reg [W-1:0] result;
    reg [BW-1:0] bit_i;          // bit under test + 1 (W .. 1); 0 = final check
    reg [SW-1:0] wait_n;
    reg final_check;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            code <= 0; result <= 0; busy <= 0; valid <= 0; under <= 0; over <= 0;
            bit_i <= 0; wait_n <= 0; final_check <= 0;
        end else begin
            valid <= 1'b0;
            if (!busy) begin
                if (start) begin
                    busy <= 1'b1;
                    result <= 0;
                    bit_i <= W[BW-1:0];
                    code <= {1'b1, {(W-1){1'b0}}};
                    wait_n <= settle;
                    final_check <= 1'b0;
                    under <= 1'b0; over <= 1'b0;
                end
            end else if (wait_n != 0) begin
                wait_n <= wait_n - 1'b1;
            end else if (!final_check) begin
                // decide bit (bit_i - 1)
                if (cmp) result[bit_i-1] <= 1'b1;
                if (bit_i == 1) begin
                    // all bits decided: code 0 or all-ones need one more look to flag under / over
                    final_check <= 1'b1;
                    code <= cmp ? (result | ({{(W-1){1'b0}}, 1'b1} << (bit_i-1))) : result;
                    wait_n <= settle;
                end else begin
                    bit_i <= bit_i - 1'b1;
                    code <= (cmp ? (result | ({{(W-1){1'b0}}, 1'b1} << (bit_i-1))) : result) | ({{(W-1){1'b0}}, 1'b1} << (bit_i-2));
                    wait_n <= settle;
                end
            end else begin
                // code holds the result; cmp = 0 there means even code 0 is above the quantity
                under <= (code == 0) && !cmp;
                over <= (&code) && cmp;
                busy <= 1'b0;
                valid <= 1'b1;
            end
        end
    end
endmodule
