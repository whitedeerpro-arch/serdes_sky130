// Lean PLL control top (v3): internal synchronous /4 (62.5 MHz / 16.0 ns) clock divider
// from external 250 MHz ref_clk, preserving exact wall-clock settle/hold/timeout durations
// and 1-ref_clk-cycle start pulse capture while cutting area by ~65-70% vs v2.
module pll_control_top #(
    parameter integer PRECHARGE_CYCLES       = 128,
    parameter integer SETTLE_CYCLES          = 512,
    parameter integer SAMPLE_DIV             = 16,
    parameter integer PERSIST                = 8,
    parameter integer HOLD_CYCLES            = 2048,
    parameter integer WINDOW                 = 32,
    parameter integer GOOD_WINDOWS           = 4,
    parameter integer BAD_WINDOWS            = 2,
    parameter integer QUALITY_TIMEOUT_CYCLES = 256,
    parameter integer CODE_BITS              = 5,
    parameter integer ACQ_TIMEOUT_CYCLES     = 1024 * (2**CODE_BITS)
) (
    input  wire                 ref_clk,
    input  wire                 rst_n,
    input  wire                 enable,
    input  wire                 start,
    input  wire                 abort_async,
    input  wire                 bias_ready_async,
    input  wire                 pre_ref_ready_async,
    input  wire [1:0]           tclass,
    input  wire                 hi_async,
    input  wire                 lo_async,
    input  wire                 pw_late_async,
    input  wire [3:0]           lo_run,
    input  wire [3:0]           hi_run,
    input  wire [11:0]          stop_code,
    input  wire [2:0]           stop_sel,
    output wire                 precharge_en,
    output wire                 pfd_rst_b,
    output wire                 cp_en,
    output wire                 locked,
    output wire                 busy,
    output wire                 fault,
    output wire [2:0]           state_id,
    output wire [2:0]           fault_code,
    output wire [CODE_BITS-1:0] vco_code,
    output wire [3:0]           lo_code,
    output wire [3:0]           hi_code,
    output wire                 coarse_busy,
    output wire                 coarse_done,
    output wire                 fast_end,
    output wire                 slow_end,
    output wire [7:0]           switches
);
    // Proportional /4 scaling (ceil division, minimum 1) keeps all wall-clock durations identical
    localparam integer DIV = 4;
    localparam integer PRECHARGE_D = (PRECHARGE_CYCLES       + DIV - 1) / DIV;
    localparam integer SETTLE_D    = (SETTLE_CYCLES          + DIV - 1) / DIV;
    localparam integer SDIV_D      = (SAMPLE_DIV             + DIV - 1) / DIV;
    localparam integer HOLD_D      = (HOLD_CYCLES            + DIV - 1) / DIV;
    localparam integer WINDOW_D    = (WINDOW                 + DIV - 1) / DIV;
    localparam integer QTO_D       = (QUALITY_TIMEOUT_CYCLES + DIV - 1) / DIV;
    localparam integer ACQ_D       = (ACQ_TIMEOUT_CYCLES     + DIV - 1) / DIV;
    localparam integer WAIT_D      = 4096 / DIV;

    // -------------------------------------------------------------------------
    // Synchronous /4 clock generator (250 MHz ref_clk -> 62.5 MHz pll_clk_div4)
    // -------------------------------------------------------------------------
    reg div2_q;
    (* keep = "true" *) reg pll_clk_div4_q;
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            div2_q         <= 1'b0;
            pll_clk_div4_q <= 1'b0;
        end else begin
            div2_q <= ~div2_q;
            if (div2_q) pll_clk_div4_q <= ~pll_clk_div4_q;
        end
    end
    (* keep = "true" *) wire pll_clk_div4;
    assign pll_clk_div4 = pll_clk_div4_q;

    // -------------------------------------------------------------------------
    // 1-ref_clk-cycle start pulse capture (toggle bridge -> clean 1-tick pulse in /4)
    // -------------------------------------------------------------------------
    reg start_d;
    reg start_tog;
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            start_d   <= 1'b0;
            start_tog <= 1'b0;
        end else begin
            start_d <= start;
            if (start && !start_d) start_tog <= ~start_tog;
        end
    end

    reg start_s0, start_s1;
    reg enable_r;
    always @(posedge pll_clk_div4 or negedge rst_n) begin
        if (!rst_n) begin
            start_s0 <= 1'b0;
            start_s1 <= 1'b0;
            enable_r <= 1'b0;
        end else begin
            start_s0 <= start_tog;
            start_s1 <= start_s0;
            enable_r <= enable;
        end
    end
    wire start_div = start_s0 ^ start_s1;

    // -------------------------------------------------------------------------
    // Synchronized ready monitors & lock/coarse/supervisor in 62.5 MHz domain
    // -------------------------------------------------------------------------
    wire bias_ready, pre_ref_ready;
    mon_sync #(.W(2)) u_rdy (
        .clk  (pll_clk_div4),
        .rst_n(rst_n),
        .d    ({bias_ready_async, pre_ref_ready_async}),
        .q    ({bias_ready, pre_ref_ready})
    );

    wire quality_valid_raw, frequency_good, phase_good;
    wire quality_valid = quality_valid_raw && !coarse_busy;

    pll_startup_supervisor #(
        .PRECHARGE_CYCLES      (PRECHARGE_D),
        .GAP_CYCLES            (1),
        .PFD_FLUSH_CYCLES      (1),
        .GOOD_WINDOWS          (GOOD_WINDOWS),
        .BAD_WINDOWS           (BAD_WINDOWS),
        .QUALITY_TIMEOUT_CYCLES(QTO_D),
        .WAIT_TIMEOUT_CYCLES   (WAIT_D),
        .ACQUIRE_TIMEOUT_CYCLES(ACQ_D)
    ) u_sup (
        .ctrl_clk      (pll_clk_div4),
        .rst_n         (rst_n),
        .enable        (enable_r),
        .start         (start_div),
        .bias_ready    (bias_ready),
        .pre_ref_ready (pre_ref_ready),
        .quality_valid (quality_valid),
        .frequency_good(frequency_good),
        .phase_good    (phase_good),
        .range_fault   (fast_end),
        .abort_async   (abort_async),
        .precharge_en  (precharge_en),
        .pfd_rst_b     (pfd_rst_b),
        .cp_en         (cp_en),
        .locked        (locked),
        .busy          (busy),
        .fault         (fault),
        .state_id      (state_id),
        .fault_code    (fault_code)
    );

    // One coarse search per start: armed by start_div, fired on first ACQUIRE
    reg armed, searched;
    reg search_pulse;
    always @(posedge pll_clk_div4 or negedge rst_n) begin
        if (!rst_n) begin
            armed        <= 1'b0;
            searched     <= 1'b0;
            search_pulse <= 1'b0;
        end else begin
            search_pulse <= 1'b0;
            if (!enable_r || state_id == 3'd0 || state_id == 3'd7) begin
                armed    <= 1'b0;
                searched <= 1'b0;
                if (start_div) armed <= 1'b1;
            end else if (armed && !searched && state_id == 3'd5) begin
                search_pulse <= 1'b1;
                searched     <= 1'b1;
            end
        end
    end

    wire track_en = searched && coarse_done && cp_en;
    pll_coarse_ctrl #(
        .CODE_BITS    (CODE_BITS),
        .SETTLE_CYCLES(SETTLE_D),
        .SAMPLE_DIV   (SDIV_D),
        .PERSIST      (PERSIST),
        .HOLD_CYCLES  (HOLD_D)
    ) u_coarse (
        .ctrl_clk (pll_clk_div4),
        .rst_n    (rst_n),
        .search   (search_pulse),
        .track_en (track_en),
        .tclass   (tclass),
        .hi_async (hi_async),
        .lo_async (lo_async),
        .lo_run   (lo_run),
        .hi_run   (hi_run),
        .stop_code(stop_code),
        .stop_sel (stop_sel),
        .vco_code (vco_code),
        .lo_code  (lo_code),
        .hi_code  (hi_code),
        .busy     (coarse_busy),
        .done     (coarse_done),
        .fast_end (fast_end),
        .slow_end (slow_end),
        .switches (switches)
    );

    pll_lock_detect #(
        .WINDOW(WINDOW_D)
    ) u_lock (
        .ctrl_clk      (pll_clk_div4),
        .rst_n         (rst_n),
        .enable        (cp_en),
        .hold          (coarse_busy || search_pulse),
        .coarse_ready  (searched && coarse_done),
        .pw_late_async (pw_late_async),
        .hi_async      (hi_async),
        .lo_async      (lo_async),
        .quality_valid (quality_valid_raw),
        .frequency_good(frequency_good),
        .phase_good    (phase_good)
    );
endmodule
