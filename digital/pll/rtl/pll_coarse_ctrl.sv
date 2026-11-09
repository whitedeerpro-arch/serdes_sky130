// PLL coarse-code controller (I-18): power-up code search and run-time re-coding from the Vctrl window detector
// (analog/pll/coarse/spice/vctrl_window.spice).  Reference-clock domain; hi/lo arrive asynchronous.
//
// Codes: vco_code 0 = fastest .. 15 = slowest.  The detector compares z (loop-filter integrator node) with
//   vlo = ladder_lo(lo_code)   (ground-referenced)  -> lo = z < vlo
//   vhi = ladder_hi(hi_code)   (VDD-referenced)     -> hi = z > vhi
//
// Power-up search (the loop is closed and the CP on: run it inside the supervisor's ACQUIRE):
//   start at code 15 and step one code faster at a time, so the VCO is never more than ~one code step above 2 GHz
//   (the divider is characterized at 2 GHz only).  The stop threshold depends on the temperature class tclass:
//   stop_sel[c] = 1 -> the hi comparator with hi_code = stop_code[c] ("above" = hi), 0 -> the lo comparator with
//   lo_code = stop_code[c] ("above" = !lo).  After SETTLE_CYCLES per step: above -> next faster code; not above ->
//   this code.  Then the ladders return to the run-time codes; if Vctrl is now below vlo (a code step wider than the
//   room under the stop threshold) the controller goes back one code.  done = 1.
// Run-time (track_en): every SAMPLE_DIV cycles the synchronized hi / lo are sampled into persistence filters
//   (PERSIST samples); hi -> one code faster, lo -> one code slower, then HOLD_CYCLES without a decision (the loop
//   re-captures and z settles).  At code 0 with hi: fast_end (Vctrl beyond the window with no faster code; the loop
//   keeps running).  At code 15 with lo: slow_end (expected for fast chips: the loop holds at low Vctrl).
// Configuration inputs must be static while busy.
module pll_coarse_ctrl #(
    parameter integer SETTLE_CYCLES = 512,
    parameter integer SAMPLE_DIV = 16,
    parameter integer PERSIST = 8,
    parameter integer HOLD_CYCLES = 2048
) (
    input wire ref_clk, rst_n,
    input wire search,                    // pulse: start the power-up search
    input wire track_en,                  // run-time re-coding allowed
    input wire [1:0] tclass,              // 0 .. 2 (cold .. hot); 3 is treated as 2
    input wire hi_async, lo_async,
    input wire [3:0] lo_run, hi_run,      // run-time ladder codes
    input wire [11:0] stop_code,          // per class {c2, c1, c0}
    input wire [2:0] stop_sel,            // per class: 1 = hi comparator / VDD-referenced ladder
    output reg [3:0] vco_code,
    output reg [3:0] lo_code, hi_code,
    output reg busy, done, fast_end, slow_end,
    output reg [7:0] switches
);
    function automatic integer clog2p(input integer x);
        integer i;
        begin clog2p = 1; for (i = 2; i < x; i = i * 2) clog2p = clog2p + 1; end
    endfunction
    localparam integer SW = clog2p(SETTLE_CYCLES + 1);
    localparam integer HW = clog2p(HOLD_CYCLES + 1);
    localparam integer DW = clog2p(SAMPLE_DIV + 1);
    localparam [2:0] IDLE = 3'd0, STEP = 3'd1, CHECK = 3'd2, BACK = 3'd3, RUN = 3'd4;

    wire hi, lo;
    mon_sync #(.W(2)) u_sync (.clk(ref_clk), .rst_n(rst_n), .d({hi_async, lo_async}), .q({hi, lo}));

    reg [2:0] state;
    reg [SW-1:0] wait_n;
    reg [HW-1:0] hold_n;
    reg [DW-1:0] div_n;
    wire [1:0] cls = (tclass == 2'd3) ? 2'd2 : tclass;
    wire [3:0] my_stop = stop_code[4*cls +: 4];
    wire my_sel = stop_sel[cls];
    wire above = my_sel ? hi : !lo;

    // run-time persistence filters, sampled on strobe; cleared outside RUN and during hold
    wire strobe = (state == RUN) && (div_n == 0);
    wire filt_rst_n = rst_n;
    reg clear_f;
    wire hi_f, lo_f;
    mon_persist #(.N(PERSIST)) u_ph (.clk(ref_clk), .rst_n(filt_rst_n), .en(strobe || clear_f), .d(hi && !clear_f), .q(hi_f));
    mon_persist #(.N(PERSIST)) u_pl (.clk(ref_clk), .rst_n(filt_rst_n), .en(strobe || clear_f), .d(lo && !clear_f), .q(lo_f));

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; vco_code <= 4'd15; lo_code <= 4'd8; hi_code <= 4'd8;
            busy <= 1'b0; done <= 1'b0; fast_end <= 1'b0; slow_end <= 1'b0; switches <= 8'd0;
            wait_n <= 0; hold_n <= 0; div_n <= 0; clear_f <= 1'b1;
        end else begin
            if (search && (state == IDLE || state == RUN)) begin
                // (re)start the power-up search from the slow end
                state <= STEP; busy <= 1'b1; done <= 1'b0; fast_end <= 1'b0; slow_end <= 1'b0;
                vco_code <= 4'd15;
                lo_code <= my_sel ? lo_run : my_stop;
                hi_code <= my_sel ? my_stop : hi_run;
                wait_n <= SETTLE_CYCLES[SW-1:0];
                clear_f <= 1'b1;
            end else case (state)
                IDLE: clear_f <= 1'b1;
                STEP: begin                              // settle at this code with the stop threshold
                    if (wait_n != 0) wait_n <= wait_n - 1'b1;
                    else if (above && vco_code != 4'd0) begin
                        vco_code <= vco_code - 1'b1;
                        wait_n <= SETTLE_CYCLES[SW-1:0];
                    end else begin
                        lo_code <= lo_run; hi_code <= hi_run;
                        wait_n <= SETTLE_CYCLES[SW-1:0];
                        state <= CHECK;
                    end
                end
                CHECK: begin                             // run-time thresholds: below vlo -> back one code
                    if (wait_n != 0) wait_n <= wait_n - 1'b1;
                    else if (lo && vco_code != 4'd15) begin
                        vco_code <= vco_code + 1'b1;
                        wait_n <= SETTLE_CYCLES[SW-1:0];
                        state <= BACK;
                    end else begin
                        state <= RUN; busy <= 1'b0; done <= 1'b1;
                        hold_n <= HOLD_CYCLES[HW-1:0]; div_n <= 0;
                    end
                end
                BACK: begin
                    if (wait_n != 0) wait_n <= wait_n - 1'b1;
                    else begin
                        state <= RUN; busy <= 1'b0; done <= 1'b1;
                        hold_n <= HOLD_CYCLES[HW-1:0]; div_n <= 0;
                    end
                end
                RUN: begin
                    begin
                        div_n <= (div_n == 0) ? SAMPLE_DIV[DW-1:0] - 1'b1 : div_n - 1'b1;
                        if (hold_n != 0) begin
                            hold_n <= hold_n - 1'b1;
                            clear_f <= 1'b1;
                        end else begin
                            clear_f <= 1'b0;
                            if (track_en && hi_f) begin
                                if (vco_code != 4'd0) begin
                                    vco_code <= vco_code - 1'b1; switches <= switches + 1'b1;
                                    hold_n <= HOLD_CYCLES[HW-1:0]; clear_f <= 1'b1;
                                end else fast_end <= 1'b1;
                            end else if (track_en && lo_f) begin
                                if (vco_code != 4'd15) begin
                                    vco_code <= vco_code + 1'b1; switches <= switches + 1'b1;
                                    hold_n <= HOLD_CYCLES[HW-1:0]; clear_f <= 1'b1;
                                end else slow_end <= 1'b1;
                            end
                            if (!hi_f) fast_end <= 1'b0;
                            if (!lo_f) slow_end <= 1'b0;
                        end
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
