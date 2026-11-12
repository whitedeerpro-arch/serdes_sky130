// PLL lock quality without a frequency counter: one measurement every WINDOW reference cycles.
//   phase_good     : in the whole window the PFD's phase-error pulse (UP xor DN, whose width is |phase error|
//                    without the common reset pulse) never lasted longer than tau_d.  The analog side samples the
//                    xor pulse with a flop clocked by the same pulse delayed by tau_d and hands the sampled bit in as
//                    pw_late_async (asynchronous to ref_clk: synchronized here).  Sampling (UP | DN) at "ref + tau"
//                    instead would need tau above the common reset width (legacy PFD: 290-746 ps over 45
//                    conditions, analog/pll/pfd/tb/reset_pvt), mixing reset timing with phase error. The analog
//                    cell is pll_phase_window (analog/pll/pfd/spice/phase_window.spice, six inverters of 10 fF
//                    each): with the adopted pll_pfd_sc_dly its threshold is 225-750 ps over 45 conditions
//                    (analog/pll/pfd/tb/phase_window --pfd sc_dly). The SF/SS low-voltage cold thresholds are
//                    650/750 ps against static mismatch bounds 239/256 ps, ratios 2.7/2.9. Legacy 3.9x and
//                    51-189 ps bounds belong to the old PFD. An xor pulse that stays high after the clear has no new
//                    edge and does not set the flag; that case (UP stuck, VCO stopped) puts Vctrl at a rail, which
//                    frequency_good reports.
//   frequency_good : the coarse search is over (coarse_ready) and the Vctrl window detector reported neither hi nor
//                    lo during the window (hi_async / lo_async synchronized here).  A loop locked inside the window
//                    is at 2 GHz / 8 with zero frequency error; a code that cannot reach 2 GHz pushes Vctrl past a
//                    threshold, which is what the window detector sees.  The tri-state PFD keeps pulling the
//                    frequency within the code's range, so no counter is needed (it would compare the same divided
//                    clock with the same reference).
// quality_valid pulses for one cycle at the end of each window; a window that starts while hold is high (the coarse
// search or a re-code in progress) is not reported.
module pll_lock_detect #(
    parameter integer WINDOW = 32
) (
    input wire ref_clk, rst_n,
    input wire enable,                  // CP on (supervisor ACQUIRE or TRACK)
    input wire hold,                    // coarse search or re-code settling: discard the current window
    input wire coarse_ready,
    input wire pw_late_async,
    input wire hi_async, lo_async,
    output reg quality_valid, frequency_good, phase_good
);
    function automatic integer clog2p(input integer x);
        integer i;
        begin clog2p = 1; for (i = 2; i < x; i = i * 2) clog2p = clog2p + 1; end
    endfunction
    localparam integer CW = clog2p(WINDOW + 1);
    localparam [CW-1:0] LAST = WINDOW[CW-1:0] - 1'b1;
    wire pw_late, hi, lo;
    mon_sync #(.W(3)) u_sync (.clk(ref_clk), .rst_n(rst_n), .d({pw_late_async, hi_async, lo_async}), .q({pw_late, hi, lo}));
    reg [CW-1:0] n;
    reg phase_bad, window_bad, tainted;
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            n <= 0; phase_bad <= 1'b0; window_bad <= 1'b0; tainted <= 1'b1;
            quality_valid <= 1'b0; frequency_good <= 1'b0; phase_good <= 1'b0;
        end else begin
            quality_valid <= 1'b0;
            if (!enable) begin
                n <= 0; phase_bad <= 1'b0; window_bad <= 1'b0; tainted <= 1'b1;
            end else if (n == LAST) begin
                if (!tainted && !hold) begin
                    quality_valid <= 1'b1;
                    phase_good <= !(phase_bad || pw_late);
                    frequency_good <= coarse_ready && !(window_bad || hi || lo);
                end
                n <= 0; phase_bad <= 1'b0; window_bad <= 1'b0; tainted <= hold;
            end else begin
                n <= n + 1'b1;
                phase_bad <= phase_bad || pw_late;
                window_bad <= window_bad || hi || lo;
                tainted <= tainted || hold;
            end
        end
    end
endmodule
