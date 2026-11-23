// Timing-closed v2 PLL lock detector with 3+3 nibble down-counter (max 3-bit arithmetic!).
// Bit- and cycle-exact with v1 pll_lock_detect.
/* verilator lint_off DECLFILENAME */
module pll_lock_detect_core #(
    parameter integer WINDOW = 32
) (
    input  wire ref_clk,
    input  wire rst_n,
    input  wire enable,
    input  wire hold,
    input  wire coarse_ready,
    input  wire pw_late_async,
    input  wire hi_async,
    input  wire lo_async,
    output reg  quality_valid,
    (* keep = "true" *) output reg quality_valid_fsm,
    output reg  frequency_good,
    output reg  phase_good
);
    localparam [5:0] INIT_CNT = (WINDOW <= 1) ? 6'd0 : (WINDOW[5:0] - 6'd1);

    wire pw_late, hi, lo;
    mon_sync #(.W(3)) u_sync (.clk(ref_clk), .rst_n(rst_n), .d({pw_late_async, hi_async, lo_async}), .q({pw_late, hi, lo}));

    reg [2:0] rem_lo, rem_hi;
    reg       lo_is1, lo_z, hi_z, rem_zero;
    reg       phase_bad, window_bad, tainted;

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            rem_lo         <= INIT_CNT[2:0];
            rem_hi         <= INIT_CNT[5:3];
            lo_is1         <= (INIT_CNT[2:0] == 3'd1);
            lo_z           <= (INIT_CNT[2:0] == 3'd0);
            hi_z           <= (INIT_CNT[5:3] == 3'd0);
            rem_zero       <= (INIT_CNT      == 6'd0);
            phase_bad      <= 1'b0;
            window_bad     <= 1'b0;
            tainted        <= 1'b1;
            quality_valid     <= 1'b0;
            quality_valid_fsm <= 1'b0;
            frequency_good    <= 1'b0;
            phase_good        <= 1'b0;
        end else begin
            quality_valid     <= 1'b0;
            quality_valid_fsm <= 1'b0;
            if (!enable) begin
                rem_lo     <= INIT_CNT[2:0];
                rem_hi     <= INIT_CNT[5:3];
                lo_is1     <= (INIT_CNT[2:0] == 3'd1);
                lo_z       <= (INIT_CNT[2:0] == 3'd0);
                hi_z       <= (INIT_CNT[5:3] == 3'd0);
                rem_zero   <= (INIT_CNT      == 6'd0);
                phase_bad  <= 1'b0;
                window_bad <= 1'b0;
                tainted    <= 1'b1;
            end else if (rem_zero) begin
                if (!tainted && !hold) begin
                    quality_valid     <= 1'b1;
                    quality_valid_fsm <= 1'b1;
                    phase_good        <= !(phase_bad || pw_late);
                    frequency_good    <= coarse_ready && !(window_bad || hi || lo);
                end
                rem_lo     <= INIT_CNT[2:0];
                rem_hi     <= INIT_CNT[5:3];
                lo_is1     <= (INIT_CNT[2:0] == 3'd1);
                lo_z       <= (INIT_CNT[2:0] == 3'd0);
                hi_z       <= (INIT_CNT[5:3] == 3'd0);
                rem_zero   <= (INIT_CNT      == 6'd0);
                phase_bad  <= 1'b0;
                window_bad <= 1'b0;
                tainted    <= hold;
            end else begin
                rem_lo   <= rem_lo - 3'd1;
                lo_is1   <= (rem_lo == 3'd2);
                if (lo_z) rem_hi <= rem_hi - 3'd1;
                if (lo_z) hi_z   <= (rem_hi == 3'd1);
                lo_z     <= lo_is1;
                rem_zero <= lo_is1 && hi_z;
                phase_bad  <= phase_bad || pw_late;
                window_bad <= window_bad || hi || lo;
                tainted    <= tainted || hold;
            end
        end
    end
endmodule

module pll_lock_detect #(
    parameter integer WINDOW = 32
) (
    input  wire ref_clk,
    input  wire rst_n,
    input  wire enable,
    input  wire hold,
    input  wire coarse_ready,
    input  wire pw_late_async,
    input  wire hi_async,
    input  wire lo_async,
    output wire quality_valid,
    output wire frequency_good,
    output wire phase_good
);
    /* verilator lint_off UNUSED */
    wire qv_fsm_unused;
    /* verilator lint_on UNUSED */
    pll_lock_detect_core #(.WINDOW(WINDOW)) u_core (
        .ref_clk(ref_clk), .rst_n(rst_n), .enable(enable), .hold(hold),
        .coarse_ready(coarse_ready), .pw_late_async(pw_late_async),
        .hi_async(hi_async), .lo_async(lo_async),
        .quality_valid(quality_valid), .quality_valid_fsm(qv_fsm_unused),
        .frequency_good(frequency_good), .phase_good(phase_good)
    );
endmodule
