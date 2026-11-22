// Compact persistence (debounce) filter for 62.5 MHz (16 ns) PLL control domain (v3).
module mon_persist #(
    parameter integer N = 8,
    parameter         RESET = 1'b0
) (
    input  wire clk,
    input  wire rst_n,
    input  wire clear,
    input  wire en,
    input  wire d,
    output reg  q
);
    localparam integer CW = (N < 2) ? 1 : $clog2(N + 1);
    localparam integer LAST_I = (N <= 1) ? 0 : (N - 1);
    localparam [CW-1:0] LAST_CNT = LAST_I[CW-1:0];

    reg [CW-1:0] cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            q   <= RESET;
            cnt <= {CW{1'b0}};
        end else if (clear) begin
            q   <= RESET;
            cnt <= {CW{1'b0}};
        end else if (en) begin
            if (d == q) begin
                cnt <= {CW{1'b0}};
            end else if (cnt == LAST_CNT) begin
                q   <= d;
                cnt <= {CW{1'b0}};
            end else begin
                cnt <= cnt + 1'b1;
            end
        end
    end
endmodule
