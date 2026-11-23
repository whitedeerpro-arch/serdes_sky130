// PLL control top: startup supervisor + coarse-code controller + lock detector (reference-clock domain).
//
//   start -> WAIT_READY -> PRECHARGE -> GAP -> FLUSH -> ACQUIRE (CP on)
//     first ACQUIRE after a start: the coarse search runs (maximum code -> faster, per-class stop threshold); quality
//     windows are not reported meanwhile, so the supervisor cannot lock on a code that is still being chosen
//     -> lock detector windows: phase_good (no PFD pulse past tau) and frequency_good (Vctrl inside the window)
//     -> TRACK (locked).  Run-time re-coding is enabled from then on; a re-code disturbs the loop, the next windows
//        are bad and the supervisor goes back to ACQUIRE with the loop filter kept, then re-locks.  The search is
//        not repeated on such a re-acquire, only after a new start.
//   range_fault = the coarse controller's fast_end (Vctrl still above the window at code 0, persistence-filtered):
//     the VCO cannot reach 2 GHz -> supervisor FAULT code 3. slow_end (maximum code below the window) is normal.
//
// Asynchronous inputs (bias_ready, pre_ref_ready, hi/lo, pw_late) are synchronized here or in the sub-blocks; the
// ready inputs must come from qualified logic (see pll_startup_supervisor).  ACQ_TIMEOUT must exceed the worst search,
// up to (2**CODE_BITS + 2) x (SETTLE_CYCLES + 1), plus handoff and capture time.
// The default timeout scales with code count; nondefault settling/capture times need their own budget.
module pll_control_top #(
    parameter integer PRECHARGE_CYCLES = 128,
    parameter integer SETTLE_CYCLES = 512,
    parameter integer SAMPLE_DIV = 16,
    parameter integer PERSIST = 8,
    parameter integer HOLD_CYCLES = 2048,
    parameter integer WINDOW = 32,
    parameter integer GOOD_WINDOWS = 4,
    parameter integer BAD_WINDOWS = 2,
    parameter integer QUALITY_TIMEOUT_CYCLES = 256,
    parameter integer ACQ_TIMEOUT_CYCLES = 1024 * (2**CODE_BITS),
    parameter integer CODE_BITS = 4
) (
    input wire ref_clk, rst_n, enable, start, abort_async,
    input wire bias_ready_async, pre_ref_ready_async,
    input wire [1:0] tclass,
    input wire hi_async, lo_async, pw_late_async,
    input wire [3:0] lo_run, hi_run,
    input wire [11:0] stop_code,
    input wire [2:0] stop_sel,
    output wire precharge_en, pfd_rst_b, cp_en, locked, busy, fault,
    output wire [2:0] state_id, fault_code,
    output wire [CODE_BITS-1:0] vco_code,
    output wire [3:0] lo_code, hi_code,
    output wire coarse_busy, coarse_done, fast_end, slow_end,
    output wire [7:0] switches
);
    wire bias_ready, pre_ref_ready;
    mon_sync #(.W(2)) u_rdy (.clk(ref_clk), .rst_n(rst_n), .d({bias_ready_async, pre_ref_ready_async}), .q({bias_ready, pre_ref_ready}));

    wire quality_valid_raw, frequency_good, phase_good;
    wire quality_valid = quality_valid_raw && !coarse_busy;

    pll_startup_supervisor #(
        .PRECHARGE_CYCLES(PRECHARGE_CYCLES), .GOOD_WINDOWS(GOOD_WINDOWS), .BAD_WINDOWS(BAD_WINDOWS),
        .QUALITY_TIMEOUT_CYCLES(QUALITY_TIMEOUT_CYCLES), .ACQUIRE_TIMEOUT_CYCLES(ACQ_TIMEOUT_CYCLES)
    ) u_sup (
        .ref_clk(ref_clk), .rst_n(rst_n), .enable(enable), .start(start),
        .bias_ready(bias_ready), .pre_ref_ready(pre_ref_ready),
        .quality_valid(quality_valid), .frequency_good(frequency_good), .phase_good(phase_good),
        .range_fault(fast_end), .abort_async(abort_async),
        .precharge_en(precharge_en), .pfd_rst_b(pfd_rst_b), .cp_en(cp_en), .locked(locked), .busy(busy), .fault(fault),
        .state_id(state_id), .fault_code(fault_code)
    );

    // one search per start: armed by start, fired on the first ACQUIRE
    reg armed, searched;
    reg search_pulse;
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            armed <= 1'b0; searched <= 1'b0; search_pulse <= 1'b0;
        end else begin
            search_pulse <= 1'b0;
            if (!enable || state_id == 3'd0 || state_id == 3'd7) begin          // IDLE or FAULT: next start re-arms
                armed <= 1'b0; searched <= 1'b0;
                if (start) armed <= 1'b1;
            end else if (armed && !searched && state_id == 3'd5) begin
                search_pulse <= 1'b1; searched <= 1'b1;
            end
        end
    end

    wire track_en = searched && coarse_done && cp_en;
    pll_coarse_ctrl #(.CODE_BITS(CODE_BITS), .SETTLE_CYCLES(SETTLE_CYCLES), .SAMPLE_DIV(SAMPLE_DIV), .PERSIST(PERSIST), .HOLD_CYCLES(HOLD_CYCLES)) u_coarse (
        .ref_clk(ref_clk), .rst_n(rst_n), .search(search_pulse), .track_en(track_en), .tclass(tclass),
        .hi_async(hi_async), .lo_async(lo_async), .lo_run(lo_run), .hi_run(hi_run), .stop_code(stop_code), .stop_sel(stop_sel),
        .vco_code(vco_code), .lo_code(lo_code), .hi_code(hi_code),
        .busy(coarse_busy), .done(coarse_done), .fast_end(fast_end), .slow_end(slow_end), .switches(switches)
    );

    pll_lock_detect #(.WINDOW(WINDOW)) u_lock (
        .ref_clk(ref_clk), .rst_n(rst_n), .enable(cp_en), .hold(coarse_busy || search_pulse), .coarse_ready(searched && coarse_done),
        .pw_late_async(pw_late_async), .hi_async(hi_async), .lo_async(lo_async),
        .quality_valid(quality_valid_raw), .frequency_good(frequency_good), .phase_good(phase_good)
    );
endmodule
