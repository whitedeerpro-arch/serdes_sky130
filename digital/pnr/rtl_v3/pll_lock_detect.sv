// Compact PLL lock detector running on synchronous /4 (62.5 MHz / 16 ns) clock (v3).
module pll_lock_detect #(
    parameter integer WINDOW = 8
) (
    input  wire ctrl_clk,
    input  wire rst_n,
    input  wire enable,
    input  wire hold,
    input  wire coarse_ready,
    input  wire pw_late_async,
    input  wire hi_async,
    input  wire lo_async,
    output reg  quality_valid,
    output reg  frequency_good,
    output reg  phase_good,
    output reg  pw_clr_b
);
    localparam integer CW = (WINDOW < 2) ? 1 : $clog2(WINDOW + 1);
    localparam integer LAST_I = (WINDOW > 1) ? (WINDOW - 1) : 0;
    localparam [CW-1:0] LAST = LAST_I[CW-1:0];

    wire pw_late, hi, lo;
    mon_sync #(.W(3)) u_sync (
        .clk  (ctrl_clk),
        .rst_n(rst_n),
        .d    ({pw_late_async, hi_async, lo_async}),
        .q    ({pw_late, hi, lo})
    );

    reg [CW-1:0] n;
    reg          phase_bad, window_bad, tainted;
    // Mask synchronized pw_late during the first 2 slow ticks after pulsing pw_clr_b=0
    // so stale pre-clear sticky values in u_sync do not poison the new measurement window.
    wire         pw_sample_en = (n >= 2);

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            n              <= {CW{1'b0}};
            phase_bad      <= 1'b0;
            window_bad     <= 1'b0;
            tainted        <= 1'b1;
            quality_valid  <= 1'b0;
            frequency_good <= 1'b0;
            phase_good     <= 1'b0;
            pw_clr_b       <= 1'b0;
        end else begin
            quality_valid <= 1'b0;
            if (!enable) begin
                n          <= {CW{1'b0}};
                phase_bad  <= 1'b0;
                window_bad <= 1'b0;
                tainted    <= 1'b1;
                pw_clr_b   <= 1'b0;
            end else if (n == LAST) begin
                if (!tainted && !hold) begin
                    quality_valid  <= 1'b1;
                    phase_good     <= !(phase_bad || (pw_sample_en && pw_late));
                    frequency_good <= coarse_ready && !(window_bad || hi || lo);
                end
                n          <= {CW{1'b0}};
                phase_bad  <= 1'b0;
                window_bad <= 1'b0;
                tainted    <= hold;
                pw_clr_b   <= 1'b0; // Pulse active-low clear for sticky pll_phase_window on new window
            end else begin
                n          <= n + 1'b1;
                phase_bad  <= phase_bad || (pw_sample_en && pw_late);
                window_bad <= window_bad || hi || lo;
                tainted    <= tainted || hold;
                pw_clr_b   <= !hold; // Keep sticky latch cleared while hold/coarse search is active
            end
        end
    end
endmodule
