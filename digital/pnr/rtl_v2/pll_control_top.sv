// Timing-closed v2 PLL control top (exact same interface & cycle-exact behavior as v1).
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
    parameter integer ACQ_TIMEOUT_CYCLES     = 1024 * (2**CODE_BITS),
    parameter integer CODE_BITS              = 4
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
    // 2-stage async synchronizer with stage-0 tap so 6x replicated rails_ready_q FFs launch on the
    // EXACT same clock edge as bias_ready/pre_ref_ready (zero latency change, fanout <= 5 each!)
    (* ASYNC_REG = "TRUE" *) reg bias_s0, pre_s0, bias_ready, pre_ref_ready;
    (* keep = "true" *)      reg [5:0] rails_ready_q;
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            bias_s0       <= 1'b0;
            pre_s0        <= 1'b0;
            bias_ready    <= 1'b0;
            pre_ref_ready <= 1'b0;
            rails_ready_q <= 6'b000000;
        end else begin
            bias_s0       <= bias_ready_async;
            pre_s0        <= pre_ref_ready_async;
            bias_ready    <= bias_s0;
            pre_ref_ready <= pre_s0;
            rails_ready_q <= {6{bias_s0 && pre_s0}};
        end
    end

    // u_lock already gates quality_valid_raw with !hold (where hold = coarse_busy || search_pulse),
    // so quality_valid_raw is already 0 on every cycle coarse_busy is asserted.
    wire quality_valid_raw, quality_valid_fsm, frequency_good, phase_good;
    wire quality_valid = quality_valid_raw;
    wire fast_end_sup;

    pll_startup_supervisor_core #(
        .PRECHARGE_CYCLES(PRECHARGE_CYCLES),
        .GOOD_WINDOWS(GOOD_WINDOWS),
        .BAD_WINDOWS(BAD_WINDOWS),
        .QUALITY_TIMEOUT_CYCLES(QUALITY_TIMEOUT_CYCLES),
        .ACQUIRE_TIMEOUT_CYCLES(ACQ_TIMEOUT_CYCLES),
        .SYNC_SAFE_OUT(1),
        .EXT_RAILS_Q(1)
    ) u_sup (
        .ref_clk(ref_clk), .rst_n(rst_n), .enable(enable), .start(start),
        .bias_ready(bias_ready), .pre_ref_ready(pre_ref_ready),
        .rails_q_in(rails_ready_q),
        .quality_valid(quality_valid), .quality_valid_fsm(quality_valid_fsm),
        .frequency_good(frequency_good), .phase_good(phase_good),
        .range_fault(fast_end_sup), .abort_async(abort_async),
        .precharge_en(precharge_en), .pfd_rst_b(pfd_rst_b), .cp_en(cp_en),
        .locked(locked), .busy(busy), .fault(fault),
        .state_id(state_id), .fault_code(fault_code)
    );

    reg armed, searched;
    (* keep = "true" *) reg search_pulse, search_lock;
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            armed        <= 1'b0;
            searched     <= 1'b0;
            search_pulse <= 1'b0;
            search_lock  <= 1'b0;
        end else begin
            search_pulse <= 1'b0;
            search_lock  <= 1'b0;
            if (!enable || fault || (!busy && !locked)) begin
                armed    <= 1'b0;
                searched <= 1'b0;
                if (start) armed <= 1'b1;
            end else if (armed && !searched && state_id == 3'd5) begin
                search_pulse <= 1'b1;
                search_lock  <= 1'b1;
                searched     <= 1'b1;
            end
        end
    end

    // Registered track_en breaks the bias_ready/safe_out -> cp_en -> coarse switch/hold path
    reg track_en_q;
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) track_en_q <= 1'b0;
        else        track_en_q <= searched && coarse_done && cp_en;
    end
    pll_coarse_ctrl_core #(
        .CODE_BITS(CODE_BITS),
        .SETTLE_CYCLES(SETTLE_CYCLES),
        .SAMPLE_DIV(SAMPLE_DIV),
        .PERSIST(PERSIST),
        .HOLD_CYCLES(HOLD_CYCLES)
    ) u_coarse (
        .ref_clk(ref_clk), .rst_n(rst_n), .search(search_pulse), .track_en(track_en_q), .tclass(tclass),
        .hi_async(hi_async), .lo_async(lo_async), .lo_run(lo_run), .hi_run(hi_run),
        .stop_code(stop_code), .stop_sel(stop_sel),
        .vco_code(vco_code), .lo_code(lo_code), .hi_code(hi_code),
        .busy(coarse_busy), .done(coarse_done), .fast_end(fast_end), .fast_end_sup(fast_end_sup),
        .slow_end(slow_end), .switches(switches)
    );

    pll_lock_detect_core #(.WINDOW(WINDOW)) u_lock (
        .ref_clk(ref_clk), .rst_n(rst_n), .enable(cp_en),
        .hold(coarse_busy || search_lock), .coarse_ready(searched && coarse_done),
        .pw_late_async(pw_late_async), .hi_async(hi_async), .lo_async(lo_async),
        .quality_valid(quality_valid_raw), .quality_valid_fsm(quality_valid_fsm),
        .frequency_good(frequency_good), .phase_good(phase_good)
    );
endmodule
