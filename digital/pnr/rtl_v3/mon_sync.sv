// 2-stage async synchronizer (v3).
module mon_sync #(
    parameter integer W = 1,
    parameter integer STAGES = 2,
    parameter [W-1:0] RESET = {W{1'b0}}
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire [W-1:0] d,
    output wire [W-1:0] q
);
    (* ASYNC_REG = "TRUE" *) reg [W-1:0] s [0:STAGES-1];
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < STAGES; i = i + 1) s[i] <= RESET;
        end else begin
            s[0] <= d;
            for (i = 1; i < STAGES; i = i + 1) s[i] <= s[i-1];
        end
    end
    assign q = s[STAGES-1];
endmodule
