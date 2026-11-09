// Frequency meter: counts rising edges of meas_clk during a gate of `window` ref_clk cycles.
// meas_clk is asynchronous to ref_clk (a VCO or divider output); it may be stopped or far off frequency.
//   ref domain : start -> gate high for `window` cycles -> wait for the meas domain's done toggle (or `timeout`
//                cycles) -> capture count, one-cycle `valid`.
//   meas domain: the gate (2-flop synchronized) clears the counter on its rising edge, counts while high,
//                freezes on its falling edge and flips done; the frozen count is stable while ref captures it
//                after synchronizing the toggle (no multi-bit synchronizer needed).
// Accuracy: the gate is delayed by the same synchronizer at both edges, so count = window * f_meas / f_ref
// within +-1.  `stalled` (with valid, count 0): no done toggle within `timeout` ref cycles after the gate --
// meas_clk stopped or slower than the synchronizer can follow.  A stalled meas domain that wakes up later
// may flip done late; the next start re-reads the toggle level, so a late flip is ignored unless it lands
// inside the next gate (then that one result is wrong: callers that care repeat a measurement).
module mon_freq_meter #(
    parameter integer CW = 12,          // count width (saturates)
    parameter integer NW = 10,          // window width
    parameter integer TW = 8            // timeout width
) (
    input wire ref_clk, rst_n, start,
    input wire meas_clk,
    input wire [NW-1:0] window,         // >= 1
    input wire [TW-1:0] timeout,        // >= 8 recommended
    output reg busy, valid, stalled,
    output reg [CW-1:0] count
);
    // ---- ref domain
    reg gate;
    reg [NW-1:0] gcnt;
    reg [TW-1:0] tcnt;
    reg waiting, done_seen;
    wire done_ref;
    // ---- meas domain
    wire gate_m;
    reg gate_m_d, done_m;
    reg [CW-1:0] mcount;

    mon_sync #(.W(1)) u_gate (.clk(meas_clk), .rst_n(rst_n), .d(gate), .q(gate_m));
    mon_sync #(.W(1)) u_done (.clk(ref_clk), .rst_n(rst_n), .d(done_m), .q(done_ref));

    always @(posedge meas_clk or negedge rst_n) begin
        if (!rst_n) begin
            gate_m_d <= 1'b0; done_m <= 1'b0; mcount <= 0;
        end else begin
            gate_m_d <= gate_m;
            if (gate_m && !gate_m_d) mcount <= 1;                  // first edge inside the gate
            else if (gate_m && !(&mcount)) mcount <= mcount + 1'b1;
            if (!gate_m && gate_m_d) done_m <= ~done_m;
        end
    end

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            gate <= 1'b0; gcnt <= 0; tcnt <= 0; waiting <= 1'b0; done_seen <= 1'b0;
            busy <= 1'b0; valid <= 1'b0; stalled <= 1'b0; count <= 0;
        end else begin
            valid <= 1'b0;
            if (!busy) begin
                if (start) begin
                    busy <= 1'b1; gate <= 1'b1; gcnt <= window - 1'b1;
                    done_seen <= done_ref; stalled <= 1'b0;
                end
            end else if (gate) begin
                if (gcnt == 0) begin
                    gate <= 1'b0; waiting <= 1'b1; tcnt <= timeout;
                end else gcnt <= gcnt - 1'b1;
            end else if (waiting) begin
                if (done_ref != done_seen) begin
                    count <= mcount; waiting <= 1'b0; busy <= 1'b0; valid <= 1'b1;
                end else if (tcnt == 0) begin
                    count <= 0; stalled <= 1'b1; waiting <= 1'b0; busy <= 1'b0; valid <= 1'b1;
                end else tcnt <= tcnt - 1'b1;
            end
        end
    end
endmodule
