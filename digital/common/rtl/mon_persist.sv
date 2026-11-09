// Persistence (debounce) filter: q takes the value of d after d has differed from q at N consecutive sample
// strobes (en).  Symmetric for both directions.  d must already be synchronous to clk (mon_sync).
// Use: a comparator that sits near its threshold while a slow quantity drifts through it chatters; q changes
// once, after the input has stayed on the new side for N samples.
module mon_persist #(
    parameter integer N = 8,
    parameter RESET = 1'b0
) (
    input wire clk, rst_n, en, d,
    output reg q
);
    localparam integer CW = (N < 2) ? 1 : $clog2(N + 1);
    localparam [CW-1:0] LAST = N[CW-1:0] - 1'b1;
    reg [CW-1:0] n;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            q <= RESET;
            n <= 0;
        end else if (en) begin
            if (d == q) n <= 0;
            else if (n == LAST) begin
                q <= d;
                n <= 0;
            end else n <= n + 1'b1;
        end
    end
endmodule
