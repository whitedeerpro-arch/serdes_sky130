// Timing-closed v2 persistence (debounce) filter using a pre-registered terminal flag.
// Bit- and cycle-exact with v1 mon_persist.
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
    localparam integer LAST_M1_I = (N <= 2) ? 0 : (N - 2);
    localparam [CW-1:0] LAST_M1   = LAST_M1_I[CW-1:0];
    localparam          INIT_LAST = (N <= 1) ? 1'b1 : 1'b0;

    // Count UP from 0 so every bit uses fast dfrtp (eliminates slow 1.4 ns dfstp on rem!)
    reg [CW-1:0] cnt;
    reg          cnt_last;

    // Pre-compute next state before clear so clear enters at the FINAL 1-gate AND2B (-1.0 ns!)
    (* keep = "true" *) wire [CW-1:0] cnt_pre;
    (* keep = "true" *) wire          last_pre;
    (* keep = "true" *) wire          q_pre;
    assign cnt_pre  = en ? ((d == q || cnt_last) ? {CW{1'b0}} : (cnt + 1'b1)) : cnt;
    assign last_pre = en ? ((d == q || cnt_last) ? INIT_LAST  : (cnt == LAST_M1)) : cnt_last;
    assign q_pre    = (en && (d != q) && cnt_last) ? d : q;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            q        <= RESET;
            cnt      <= {CW{1'b0}};
            cnt_last <= INIT_LAST;
        end else begin
            q        <= clear ? RESET      : q_pre;
            cnt      <= clear ? {CW{1'b0}} : cnt_pre;
            cnt_last <= clear ? INIT_LAST  : last_pre;
        end
    end
endmodule
