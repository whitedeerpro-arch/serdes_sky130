// Timing-closed v2 PLL startup supervisor (250 MHz / 4.0 ns SS-closed).
// Bit- and cycle-exact with v1 pll_startup_supervisor, architected for <=4 SS logic levels:
//   1. 4x4-bit nibble carry-deferred down-counter for cycles (max 4-bit arithmetic = 2 gates!).
//   2. 4+5-bit nibble carry-deferred down-counter for quality_age (eliminating 9-bit ripple).
//   3. Direct 1-bit one-hot state registers & directly registered state_id / busy / fault.
//   4. Preserved asynchronous safety clamp on precharge_en, pfd_rst_b, cp_en, locked.
/* verilator lint_off DECLFILENAME */
module pll_startup_supervisor_core #(
    parameter integer PRECHARGE_CYCLES       = 128,
    parameter integer GAP_CYCLES             = 2,
    parameter integer PFD_FLUSH_CYCLES       = 2,
    parameter integer GOOD_WINDOWS           = 4,
    parameter integer BAD_WINDOWS            = 2,
    parameter integer QUALITY_TIMEOUT_CYCLES = 128,
    parameter integer WAIT_TIMEOUT_CYCLES    = 4096,
    parameter integer ACQUIRE_TIMEOUT_CYCLES = 4096,
    parameter integer SYNC_SAFE_OUT          = 0,
    parameter integer EXT_RAILS_Q            = 0
) (
    input  wire       ref_clk,
    input  wire       rst_n,
    input  wire       enable,
    input  wire       start,
    input  wire       bias_ready,
    input  wire       pre_ref_ready,
    input  wire [5:0] rails_q_in,
    input  wire       quality_valid,
    input  wire       quality_valid_fsm,
    input  wire       frequency_good,
    input  wire       phase_good,
    input  wire       range_fault,
    input  wire       abort_async,
    output wire       precharge_en,
    output wire       pfd_rst_b,
    output wire       cp_en,
    output wire       locked,
    output reg        busy,
    output reg        fault,
    output reg  [2:0] state_id,
    output reg  [2:0] fault_code
);
    function automatic integer max2(input integer a, input integer b);
        max2 = (a > b) ? a : b;
    endfunction

    localparam [15:0] PRE_LOAD     = (PRECHARGE_CYCLES <= 1)       ? 16'd0 : (PRECHARGE_CYCLES[15:0]       - 16'd1);
    localparam [15:0] GAP_LOAD     = (GAP_CYCLES <= 1)             ? 16'd0 : (GAP_CYCLES[15:0]             - 16'd1);
    localparam [15:0] FLUSH_LOAD   = (PFD_FLUSH_CYCLES <= 1)       ? 16'd0 : (PFD_FLUSH_CYCLES[15:0]       - 16'd1);
    localparam [15:0] WAIT_LOAD    = (WAIT_TIMEOUT_CYCLES <= 1)    ? 16'd0 : (WAIT_TIMEOUT_CYCLES[15:0]    - 16'd1);
    localparam [15:0] ACQUIRE_LOAD = (ACQUIRE_TIMEOUT_CYCLES <= 1) ? 16'd0 : (ACQUIRE_TIMEOUT_CYCLES[15:0] - 16'd1);
    localparam [11:0] QAGE_LOAD12  = (QUALITY_TIMEOUT_CYCLES <= 1) ? 12'd0 : (QUALITY_TIMEOUT_CYCLES[11:0] - 12'd1);

    localparam integer GW = max2(1, $clog2(GOOD_WINDOWS + 1));
    localparam integer BW = max2(1, $clog2(BAD_WINDOWS + 1));
    localparam [GW-1:0] GOOD_LOAD = (GOOD_WINDOWS <= 1) ? {GW{1'b0}} : (GOOD_WINDOWS[GW-1:0] - 1'b1);
    localparam [BW-1:0] BAD_LOAD  = (BAD_WINDOWS <= 1)  ? {BW{1'b0}} : (BAD_WINDOWS[BW-1:0]  - 1'b1);
    localparam [GW-1:0] GW_ONE    = {{(GW-1){1'b0}}, 1'b1};
    localparam [BW-1:0] BW_ONE    = {{(BW-1){1'b0}}, 1'b1};
    localparam          GOOD_INIT_Z = (GOOD_LOAD == {GW{1'b0}});
    localparam          BAD_INIT_Z  = (BAD_LOAD  == {BW{1'b0}});

    reg st_idle, st_wait, st_pre, st_gap, st_flush, st_acq, st_trk, st_flt;
    (* keep = "true" *) reg st_trk_lo, st_trk_hi, st_trk_z;
    (* keep = "true" *) reg in_timed_step_q, in_timed_lo, in_timed_hi, in_timed_z;
    (* keep = "true" *) reg st_wait_lo, st_wait_n2, st_wait_hi, st_wait_z;
    // Active-low not_idle_* resets to 0 -> fast dfrtp instead of 1.41 ns dfstp!
    (* keep = "true" *) reg not_idle_lo, not_idle_n2, not_idle_hi, not_idle_z;
    wire st_idle_lo = !not_idle_lo;
    wire st_idle_n2 = !not_idle_n2;
    wire st_idle_hi = !not_idle_hi;
    wire st_idle_z  = !not_idle_z;
    (* keep = "true" *) reg st_flt_lo,  st_flt_n2,  st_flt_hi,  st_flt_z;
    (* keep = "true" *) reg in_active_q, in_active_fc, in_run_mon_q, in_run_mon_trk, in_run_mon_wt;
    reg precharge_raw, pfd_rst_b_raw, cp_en_raw, locked_raw;

    // 4x4-bit nibble down-counter for cycles: store active-high cyc_nz* (resets to 0 -> fast dfrtp
    // instead of slow 1.41ns dfstp async-set FF! Replicated ld_lo/hi/z prevents Yosys net merging!)
    reg [3:0] cn0, cn1, cn2, cn3;
    reg       cn0_is1, cz1, cz2, cz3;
    (* keep = "true" *) reg cyc_nz, cyc_nz_flt, cyc_nz_ld, cyc_nz_ld_lo, cyc_nz_ld_hi, cyc_nz_ld_z, cyc_nz_cnt;
    wire cyc_zero     = !cyc_nz;
    wire cyc_zero_flt = !cyc_nz_flt;
    wire cyc_zero_ld  = !cyc_nz_ld;
    wire cyc_zero_cnt = !cyc_nz_cnt;
    reg       cen1, cen2, cen3;

    // 3x4-bit nibble down-counter for quality_age (pre-gated qen1/qen2 -> <= 3 gates!)
    reg [3:0] qn0, qn1, qn2;
    reg       qn0_is1, qz1, qz2, qen1, qen2, qage_zero;

    reg [GW-1:0] good_rem;
    reg          good_zero;
    reg [BW-1:0] bad_rem;
    reg          bad_zero;

    (* ASYNC_REG = "TRUE" *) reg [1:0] abort_sync;
    wire quality_good    = frequency_good && phase_good;
    wire rails_ready     = (EXT_RAILS_Q != 0) ? rails_q_in[0] : (bias_ready && pre_ref_ready);
    wire rails_ready_sid = (EXT_RAILS_Q != 0) ? rails_q_in[1] : (bias_ready && pre_ref_ready);
    wire rails_ready_raw = (EXT_RAILS_Q != 0) ? rails_q_in[2] : (bias_ready && pre_ref_ready);
    wire rails_ready_lo  = (EXT_RAILS_Q != 0) ? rails_q_in[3] : (bias_ready && pre_ref_ready);
    wire rails_ready_hi  = (EXT_RAILS_Q != 0) ? rails_q_in[4] : (bias_ready && pre_ref_ready);
    wire rails_ready_z   = (EXT_RAILS_Q != 0) ? rails_q_in[5] : (bias_ready && pre_ref_ready);
    // (* keep = "true" *) forces Yosys to keep enable at the FINAL 1-gate AND2 (-1.0 ns on enable->cp_en!)
    wire safe_async   = (SYNC_SAFE_OUT != 0)
                      ? (rst_n && !abort_async)
                      : (rst_n && !abort_async && !abort_sync[1] && rails_ready);
    (* keep = "true" *) wire pre_gated;
    (* keep = "true" *) wire pfd_gated;
    (* keep = "true" *) wire cp_gated;
    (* keep = "true" *) wire lck_gated;
    assign pre_gated = safe_async && precharge_raw;
    assign pfd_gated = safe_async && pfd_rst_b_raw;
    assign cp_gated  = safe_async && cp_en_raw;
    assign lck_gated = safe_async && locked_raw;

    assign precharge_en = enable && pre_gated;
    assign pfd_rst_b    = enable && pfd_gated;
    assign cp_en        = enable && cp_gated;
    assign locked       = enable && lck_gated;

    // Direct 1-bit transition triggers (dedicated per-group normal_ok_* -> cap <= 0.03 pF, 0 repeaters!)
    wire rails_fault   = in_active_q    && !rails_ready;
    wire rng_fault     = in_run_mon_q   && range_fault;
    wire rng_fault_trk = in_run_mon_trk && range_fault;
    wire rng_fault_wt  = in_run_mon_wt  && range_fault;
    wire fault_now     = abort_sync[1] || rails_fault || rng_fault;
    wire fault_now_trk = abort_sync[1] || rails_fault || rng_fault_trk;
    wire fault_now_wt  = abort_sync[1] || rails_fault || rng_fault_wt;
    (* keep = "true" *) wire normal_ok;
    (* keep = "true" *) wire normal_ok_w;
    (* keep = "true" *) wire normal_ok_t;
    (* keep = "true" *) wire normal_ok_trk;
    (* keep = "true" *) wire normal_ok_aux;
    assign normal_ok     = enable && !fault_now;
    assign normal_ok_w   = enable && !fault_now_wt;
    assign normal_ok_t   = enable && !fault_now_wt;
    assign normal_ok_trk = enable && !fault_now_trk;
    assign normal_ok_aux = enable && !fault_now;

    wire acq_win = st_acq && quality_valid_fsm && quality_good && good_zero;
    wire trk_bad = st_trk && quality_valid_fsm && !quality_good && bad_zero;
    wire trk_qto = st_trk && !quality_valid_fsm && qage_zero;

    wire raw_wait  = (st_idle && start) || (st_flt && start && rails_ready_raw) || (st_wait && !rails_ready_raw && !cyc_zero);
    wire raw_pre   = (st_wait && rails_ready_raw) || (st_pre && !cyc_zero);
    wire raw_gap   = (st_pre && cyc_zero) || (st_gap && !cyc_zero);
    wire raw_flush = (st_gap && cyc_zero) || (st_flush && !cyc_zero);
    wire raw_acq   = (st_flush && cyc_zero) || trk_bad || (st_acq && !acq_win && !cyc_zero);
    wire raw_trk   = acq_win || (st_trk && !trk_bad && !trk_qto);

    wire go_wait    = normal_ok && ((st_idle && start) || (st_flt && start && rails_ready_raw));

    // Decoupled counter load signals (mutually exclusive 1-hot groups -> fanout <= 8!)
    wire ld_wait   = (st_idle && start) || (st_flt && start && rails_ready_raw);
    wire ld_pre    = st_wait  && rails_ready_raw;
    wire ld_gap    = st_pre   && cyc_zero_ld;
    wire ld_flush  = st_gap   && cyc_zero_ld;
    wire ld_acq    = (st_flush && cyc_zero_ld) || st_trk_hi;
    wire ld_short  = (st_pre | st_gap) && cyc_zero_ld;

    wire ld_rail_lo = (st_idle_lo && start) || (rails_ready_lo && (st_wait_lo || (st_flt_lo && start)));
    wire ld_w_n2    = start && (st_idle_n2 || (st_flt_n2 && rails_ready_hi));
    wire ld_p_n2    = st_wait_n2 && rails_ready_hi;
    wire ld_w_n3    = start && (st_idle_hi || (st_flt_hi && rails_ready_hi));
    wire ld_p_n3    = st_wait_hi && rails_ready_hi;
    wire ld_rail_z  = (st_idle_z  && start) || (rails_ready_z  && (st_wait_z  || (st_flt_z  && start)));
    wire ld_non_lo  = st_trk_lo || (in_timed_lo && !cyc_nz_ld_lo);
    wire ld_non_hi  = st_trk_hi || (in_timed_hi && !cyc_nz_ld_hi);
    wire ld_non_z   = st_trk_z  || (in_timed_z  && !cyc_nz_ld_z);

    // Compact load nibble mux (when WAIT/PRE/ACQ share low nibble 4'hf and GAP/FLUSH share 4'h1,
    // ld_short selects cn0 in 1 gate instead of a 5-way OR!)
    localparam STD_N0 = (WAIT_LOAD[3:0] == 4'hf) && (PRE_LOAD[3:0] == 4'hf) && (ACQUIRE_LOAD[3:0] == 4'hf) &&
                        (GAP_LOAD[3:0]  == 4'h1) && (FLUSH_LOAD[3:0] == 4'h1);
    localparam STD_NONZERO = (WAIT_LOAD != 16'd0) && (PRE_LOAD != 16'd0) && (GAP_LOAD != 16'd0) &&
                             (FLUSH_LOAD != 16'd0) && (ACQUIRE_LOAD != 16'd0) &&
                             (WAIT_LOAD[3:0] != 4'd0) && (PRE_LOAD[3:0] != 4'd0) && (GAP_LOAD[3:0] != 4'd0) &&
                             (FLUSH_LOAD[3:0] != 4'd0) && (ACQUIRE_LOAD[3:0] != 4'd0);
    // Split non-rail load values vs rail (WAIT/PRE) load values so rails_ready enters at final mux!
    wire [3:0] non_n0 = (STD_N0 != 0) ? (ld_short ? 4'h1 : 4'hf) :
                        ((ld_gap ? GAP_LOAD[3:0] : 4'd0) | (ld_flush ? FLUSH_LOAD[3:0] : 4'd0) | (ld_acq ? ACQUIRE_LOAD[3:0] : 4'd0));
    wire [15:4] non_hi = (ld_gap ? GAP_LOAD[15:4] : 12'd0) | (ld_flush ? FLUSH_LOAD[15:4] : 12'd0) | (ld_acq ? ACQUIRE_LOAD[15:4] : 12'd0);
    wire [7:0] rail_val = st_wait ? PRE_LOAD[7:0] : WAIT_LOAD[7:0];

    // Pre-computed constant load flags (only used when STD_NONZERO == 0 or for cz1..3)
    wire non_z1 = (ld_gap && (GAP_LOAD[7:4]   == 4'd0)) || (ld_flush && (FLUSH_LOAD[7:4]   == 4'd0)) || (ld_acq && (ACQUIRE_LOAD[7:4]   == 4'd0));
    wire non_z2 = (ld_gap && (GAP_LOAD[11:8]  == 4'd0)) || (ld_flush && (FLUSH_LOAD[11:8]  == 4'd0)) || (ld_acq && (ACQUIRE_LOAD[11:8]  == 4'd0));
    wire non_z3 = (ld_gap && (GAP_LOAD[15:12] == 4'd0)) || (ld_flush && (FLUSH_LOAD[15:12] == 4'd0)) || (ld_acq && (ACQUIRE_LOAD[15:12] == 4'd0));
    wire rail_z1 = st_wait ? (PRE_LOAD[7:4]   == 4'd0) : (WAIT_LOAD[7:4]   == 4'd0);
    wire ld_n0_1 = (ld_wait  && (WAIT_LOAD[3:0]    == 4'd1)) ||
                   (ld_pre   && (PRE_LOAD[3:0]     == 4'd1)) ||
                   (ld_gap   && (GAP_LOAD[3:0]     == 4'd1)) ||
                   (ld_flush && (FLUSH_LOAD[3:0]   == 4'd1)) ||
                   (ld_acq   && (ACQUIRE_LOAD[3:0] == 4'd1));
    wire ld_z0   = (ld_wait  && (WAIT_LOAD[3:0]    == 4'd0)) ||
                   (ld_pre   && (PRE_LOAD[3:0]     == 4'd0)) ||
                   (ld_gap   && (GAP_LOAD[3:0]     == 4'd0)) ||
                   (ld_flush && (FLUSH_LOAD[3:0]   == 4'd0)) ||
                   (ld_acq   && (ACQUIRE_LOAD[3:0] == 4'd0));
    wire ld_z01  = (ld_wait  && (WAIT_LOAD[7:0]    == 8'd0)) ||
                   (ld_pre   && (PRE_LOAD[7:0]     == 8'd0)) ||
                   (ld_gap   && (GAP_LOAD[7:0]     == 8'd0)) ||
                   (ld_flush && (FLUSH_LOAD[7:0]   == 8'd0)) ||
                   (ld_acq   && (ACQUIRE_LOAD[7:0] == 8'd0));
    wire ld_z012 = (ld_wait  && (WAIT_LOAD[11:0]    == 12'd0)) ||
                   (ld_pre   && (PRE_LOAD[11:0]     == 12'd0)) ||
                   (ld_gap   && (GAP_LOAD[11:0]     == 12'd0)) ||
                   (ld_flush && (FLUSH_LOAD[11:0]   == 12'd0)) ||
                   (ld_acq   && (ACQUIRE_LOAD[11:0] == 12'd0));
    wire ld_zero = (ld_wait  && (WAIT_LOAD    == 16'd0)) ||
                   (ld_pre   && (PRE_LOAD     == 16'd0)) ||
                   (ld_gap   && (GAP_LOAD     == 16'd0)) ||
                   (ld_flush && (FLUSH_LOAD   == 16'd0)) ||
                   (ld_acq   && (ACQUIRE_LOAD == 16'd0));

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) abort_sync <= 2'b00;
        else        abort_sync <= {abort_sync[0], abort_async};
    end

    // 3x4-bit nibble down-counter for quality_age (pre-gated qen1/qen2 -> <= 3 gates!)
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            qn0       <= QAGE_LOAD12[3:0];
            qn1       <= QAGE_LOAD12[7:4];
            qn2       <= QAGE_LOAD12[11:8];
            qn0_is1   <= (QAGE_LOAD12[3:0]  == 4'd1);
            qz1       <= (QAGE_LOAD12[7:4]  == 4'd0);
            qz2       <= (QAGE_LOAD12[11:8] == 4'd0);
            qen1      <= (QAGE_LOAD12[3:0]  == 4'd0) && (QAGE_LOAD12 != 12'd0);
            qen2      <= (QAGE_LOAD12[7:0]  == 8'd0) && (QAGE_LOAD12 != 12'd0);
            qage_zero <= (QAGE_LOAD12       == 12'd0);
        end else if (!in_run_mon_q || quality_valid) begin
            qn0       <= QAGE_LOAD12[3:0];
            qn1       <= QAGE_LOAD12[7:4];
            qn2       <= QAGE_LOAD12[11:8];
            qn0_is1   <= (QAGE_LOAD12[3:0]  == 4'd1);
            qz1       <= (QAGE_LOAD12[7:4]  == 4'd0);
            qz2       <= (QAGE_LOAD12[11:8] == 4'd0);
            qen1      <= (QAGE_LOAD12[3:0]  == 4'd0) && (QAGE_LOAD12 != 12'd0);
            qen2      <= (QAGE_LOAD12[7:0]  == 8'd0) && (QAGE_LOAD12 != 12'd0);
            qage_zero <= (QAGE_LOAD12       == 12'd0);
        end else begin
            if (!qage_zero) begin
                qn0       <= qn0 - 4'd1;
                qn0_is1   <= (qn0 == 4'd2);
                qage_zero <= qn0_is1 && qz1 && qz2;
                qen1      <= qn0_is1 && !(qz1 && qz2);
                qen2      <= qn0_is1 && qz1 && !qz2;
            end
            if (qen1) qn1 <= qn1 - 4'd1;
            if (qen2) qn2 <= qn2 - 4'd1;
            if (qen1) qz1 <= (qn1 == 4'd1);
            if (qen2) qz2 <= (qn2 == 4'd1);
        end
    end

    // 4x4-bit nibble down-counter for cycles (split lo/hi/z loads -> fanout <= 9, rails_ready at final mux!)
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            cn0 <= 4'd0; cn1 <= 4'd0; cz1 <= 1'b1;
        end else if (ld_rail_lo) begin
            cn0 <= rail_val[3:0];
            cn1 <= rail_val[7:4];
            cz1 <= rail_z1;
        end else if (ld_non_lo) begin
            cn0 <= non_n0;
            cn1 <= non_hi[7:4];
            cz1 <= non_z1;
        end else begin
            if (!cyc_zero_cnt) cn0 <= cn0 - 4'd1;
            if (cen1) begin
                cn1 <= cn1 - 4'd1;
                cz1 <= (cn1 == 4'd1);
            end
        end
    end

    // Separate cn2 & cn3 with direct constant loads (eliminates rail_val mux & halves cap -> -0.8 ns!)
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            cn2 <= 4'd0; cz2 <= 1'b1;
        end else if (ld_w_n2) begin
            cn2 <= WAIT_LOAD[11:8];
            cz2 <= (WAIT_LOAD[11:8] == 4'd0);
        end else if (ld_p_n2) begin
            cn2 <= PRE_LOAD[11:8];
            cz2 <= (PRE_LOAD[11:8] == 4'd0);
        end else if (ld_non_hi) begin
            cn2 <= non_hi[11:8];
            cz2 <= non_z2;
        end else if (cen2) begin
            cn2 <= cn2 - 4'd1;
            cz2 <= (cn2 == 4'd1);
        end
    end

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            cn3 <= 4'd0; cz3 <= 1'b1;
        end else if (ld_w_n3) begin
            cn3 <= WAIT_LOAD[15:12];
            cz3 <= (WAIT_LOAD[15:12] == 4'd0);
        end else if (ld_p_n3) begin
            cn3 <= PRE_LOAD[15:12];
            cz3 <= (PRE_LOAD[15:12] == 4'd0);
        end else if (ld_non_hi) begin
            cn3 <= non_hi[15:12];
            cz3 <= non_z3;
        end else if (cen3) begin
            cn3 <= cn3 - 4'd1;
            cz3 <= (cn3 == 4'd1);
        end
    end

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            cn0_is1    <= 1'b0;
            cyc_nz     <= 1'b0; cyc_nz_flt <= 1'b0; cyc_nz_ld <= 1'b0; cyc_nz_cnt <= 1'b0;
            cyc_nz_ld_lo <= 1'b0; cyc_nz_ld_hi <= 1'b0; cyc_nz_ld_z <= 1'b0;
            cen1       <= 1'b0; cen2 <= 1'b0; cen3 <= 1'b0;
        end else if (ld_rail_z || ld_non_z) begin
            cn0_is1    <= (STD_N0 != 0) ? (ld_non_z && ld_short) : ld_n0_1;
            cyc_nz     <= (STD_NONZERO != 0) ? 1'b1 : !ld_zero;
            cyc_nz_flt <= (STD_NONZERO != 0) ? 1'b1 : !ld_zero;
            cyc_nz_ld  <= (STD_NONZERO != 0) ? 1'b1 : !ld_zero;
            cyc_nz_ld_lo <= (STD_NONZERO != 0) ? 1'b1 : !ld_zero;
            cyc_nz_ld_hi <= (STD_NONZERO != 0) ? 1'b1 : !ld_zero;
            cyc_nz_ld_z  <= (STD_NONZERO != 0) ? 1'b1 : !ld_zero;
            cyc_nz_cnt <= (STD_NONZERO != 0) ? 1'b1 : !ld_zero;
            cen1       <= (STD_NONZERO != 0) ? 1'b0 : (ld_z0   && !ld_zero);
            cen2       <= (STD_NONZERO != 0) ? 1'b0 : (ld_z01  && !ld_zero);
            cen3       <= (STD_NONZERO != 0) ? 1'b0 : (ld_z012 && !ld_zero);
        end else if (cyc_nz_cnt) begin
            cn0_is1    <= (cn0 == 4'd2);
            cyc_nz     <= !(cn0_is1 && cz1 && cz2 && cz3);
            cyc_nz_flt <= !(cn0_is1 && cz1 && cz2 && cz3);
            cyc_nz_ld  <= !(cn0_is1 && cz1 && cz2 && cz3);
            cyc_nz_ld_lo <= !(cn0_is1 && cz1 && cz2 && cz3);
            cyc_nz_ld_hi <= !(cn0_is1 && cz1 && cz2 && cz3);
            cyc_nz_ld_z  <= !(cn0_is1 && cz1 && cz2 && cz3);
            cyc_nz_cnt <= !(cn0_is1 && cz1 && cz2 && cz3);
            cen1       <= cn0_is1 && !(cz1 && cz2 && cz3);
            cen2       <= cn0_is1 && cz1 && !(cz2 && cz3);
            cen3       <= cn0_is1 && cz1 && cz2 && !cz3;
        end
    end

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            good_rem  <= GOOD_LOAD;
            good_zero <= GOOD_INIT_Z;
        end else if (!st_acq || !enable) begin
            good_rem  <= GOOD_LOAD;
            good_zero <= GOOD_INIT_Z;
        end else if (quality_valid) begin
            if (quality_good) begin
                good_rem  <= good_rem - 1'b1;
                good_zero <= (good_rem == GW_ONE);
            end else begin
                good_rem  <= GOOD_LOAD;
                good_zero <= GOOD_INIT_Z;
            end
        end else if (qage_zero) begin
            good_rem  <= GOOD_LOAD;
            good_zero <= GOOD_INIT_Z;
        end
    end

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            bad_rem  <= BAD_LOAD;
            bad_zero <= BAD_INIT_Z;
        end else if (!st_trk || !enable) begin
            bad_rem  <= BAD_LOAD;
            bad_zero <= BAD_INIT_Z;
        end else if (quality_valid) begin
            if (quality_good) begin
                bad_rem  <= BAD_LOAD;
                bad_zero <= BAD_INIT_Z;
            end else begin
                bad_rem  <= bad_rem - 1'b1;
                bad_zero <= (bad_rem == BW_ONE);
            end
        end
    end

    wire nxt_idle  = !enable || (st_idle && !start);
    wire nxt_wait  = normal_ok_w && raw_wait;
    wire nxt_pre   = normal_ok_t && raw_pre;
    wire nxt_gap   = normal_ok_t && raw_gap;
    wire nxt_flush = normal_ok_t && raw_flush;
    wire nxt_timed = normal_ok_t && (raw_pre || raw_gap || raw_flush);
    wire nxt_acq   = normal_ok && raw_acq;
    (* keep = "true" *) wire nxt_trk_a;
    (* keep = "true" *) wire nxt_trk_b;
    assign nxt_trk_a = normal_ok_trk && raw_trk;
    assign nxt_trk_b = normal_ok_trk && raw_trk;

    // Flat 2-level nxt_flt with enable pushed before final OR + 3-way split (kills cap on st_flt_*!)
    wire flt_no_rng_a = enable && (abort_sync[1] || (in_active_fc && !rails_ready_sid) ||
                                   (cyc_zero_flt && ((st_wait && !rails_ready_raw) || (st_acq && !acq_win))) ||
                                   trk_qto || (st_flt && !(start && rails_ready_raw)));
    wire flt_rng_en   = enable && in_run_mon_q && range_fault;
    (* keep = "true" *) wire nxt_flt_a;
    (* keep = "true" *) wire nxt_flt_b1;
    (* keep = "true" *) wire nxt_flt_b2;
    assign nxt_flt_a  = flt_no_rng_a || flt_rng_en;
    assign nxt_flt_b1 = flt_no_rng_a || flt_rng_en;
    assign nxt_flt_b2 = flt_no_rng_a || flt_rng_en;

    // Algebraic minimal-depth state_id (dedicated rails_ready_sid -> zero rebuffers!):
    wire go_even  = (st_idle && !start) || raw_pre || raw_flush || raw_trk;
    wire nxt_sid2 = enable && (
        st_flush || st_acq || st_trk ||
        abort_sync[1] ||
        (st_gap  && (cyc_zero || !rails_ready_sid)) ||
        (st_pre  && !rails_ready_sid) ||
        (st_wait && !rails_ready_sid && cyc_zero) ||
        (st_flt  && !(start && rails_ready_sid))
    );
    wire nxt_sid1 = enable && (
        fault_now || st_pre ||
        (st_wait && (rails_ready_sid || cyc_zero)) ||
        (st_gap  && !cyc_zero) ||
        (st_acq  && (acq_win || cyc_zero)) ||
        (st_trk  && !trk_bad) ||
        (st_flt  && !(start && rails_ready_sid))
    );
    wire nxt_sid0 = enable && (fault_now || !go_even);
    wire [2:0] nxt_state_id = {nxt_sid2, nxt_sid1, nxt_sid0};

    // Flat 2-level SOP fault_code terms (dedicated in_active_fc, simplified fc_bit1!)
    wire en_not_ab = enable && !abort_sync[1];
    wire raw_to    = cyc_zero_flt && ((st_wait && !rails_ready_raw) || (st_acq && !acq_win));
    wire any_to    = raw_to || trk_qto;
    wire fc_clr    = !enable || go_wait;
    wire fc_abort  = enable && !go_wait && abort_sync[1];
    wire fc_rail1  = en_not_ab && in_active_fc && !bias_ready;
    wire fc_rng    = en_not_ab && in_run_mon_q && rails_ready_sid && range_fault;
    wire fc_to_any = en_not_ab && !(in_active_fc && !rails_ready_sid) && !rng_fault && any_to;
    wire fc_bit1   = en_not_ab && ((in_active_fc && bias_ready && !pre_ref_ready) ||
                                   (rails_ready_sid && ((in_run_mon_q && range_fault) || trk_qto)));
    wire [2:0] fc_val = {
        fc_abort | fc_to_any,
        fc_bit1,
        fc_abort | fc_rail1 | fc_rng
    };
    // Compact busy: in_timed_step_q (PRE|GAP|FLUSH) is ALWAYS busy regardless of cyc_zero!
    wire busy_raw = in_timed_step_q || ld_wait || (st_wait && (rails_ready || !cyc_zero_flt)) ||
                    (st_acq && !acq_win && !cyc_zero_flt) || trk_bad;

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            st_idle         <= 1'b1; not_idle_lo <= 1'b0; not_idle_n2 <= 1'b0; not_idle_hi <= 1'b0; not_idle_z <= 1'b0;
            st_wait         <= 1'b0; st_wait_lo <= 1'b0; st_wait_n2 <= 1'b0; st_wait_hi <= 1'b0; st_wait_z <= 1'b0;
            st_pre          <= 1'b0;
            st_gap          <= 1'b0;
            st_flush        <= 1'b0;
            st_acq          <= 1'b0;
            st_trk          <= 1'b0; st_trk_lo <= 1'b0; st_trk_hi <= 1'b0; st_trk_z <= 1'b0;
            in_timed_step_q <= 1'b0; in_timed_lo <= 1'b0; in_timed_hi <= 1'b0; in_timed_z <= 1'b0;
            st_flt          <= 1'b0; st_flt_lo  <= 1'b0; st_flt_n2  <= 1'b0; st_flt_hi  <= 1'b0; st_flt_z  <= 1'b0;
            in_active_q    <= 1'b0;
            in_active_fc   <= 1'b0;
            in_run_mon_q   <= 1'b0;
            in_run_mon_trk <= 1'b0;
            in_run_mon_wt  <= 1'b0;
            state_id      <= 3'd0;
            busy          <= 1'b0;
            fault         <= 1'b0;
            precharge_raw <= 1'b0;
            pfd_rst_b_raw <= 1'b0;
            cp_en_raw     <= 1'b0;
            locked_raw    <= 1'b0;
            fault_code    <= 3'd0;
        end else begin
            st_idle         <= nxt_idle; not_idle_lo <= !nxt_idle; not_idle_n2 <= !nxt_idle; not_idle_hi <= !nxt_idle; not_idle_z <= !nxt_idle;
            st_wait         <= nxt_wait; st_wait_lo <= nxt_wait; st_wait_n2 <= nxt_wait; st_wait_hi <= nxt_wait; st_wait_z <= nxt_wait;
            st_pre          <= nxt_pre;
            st_gap          <= nxt_gap;
            st_flush        <= nxt_flush;
            st_acq          <= nxt_acq;
            st_trk          <= nxt_trk_a; st_trk_lo <= nxt_trk_b; st_trk_hi <= nxt_trk_b; st_trk_z <= nxt_trk_b;
            in_timed_step_q <= nxt_timed;
            in_timed_lo     <= nxt_timed;
            in_timed_hi     <= nxt_timed;
            in_timed_z      <= nxt_timed;
            st_flt          <= nxt_flt_a; st_flt_lo <= nxt_flt_b1; st_flt_n2 <= nxt_flt_b1; st_flt_hi <= nxt_flt_b2; st_flt_z <= nxt_flt_b2;
            in_active_q    <= normal_ok_aux && ((st_wait && rails_ready_raw) || in_timed_step_q || (st_acq && (acq_win || cyc_nz)) || (st_trk && !trk_qto));
            in_active_fc   <= normal_ok_aux && ((st_wait && rails_ready_raw) || in_timed_step_q || (st_acq && (acq_win || cyc_nz)) || (st_trk && !trk_qto));
            in_run_mon_q   <= normal_ok_aux && ((st_flush && cyc_zero) || (st_acq && (acq_win || !cyc_zero)) || (st_trk && !trk_qto));
            in_run_mon_trk <= normal_ok_aux && ((st_flush && cyc_zero) || (st_acq && (acq_win || !cyc_zero)) || (st_trk && !trk_qto));
            in_run_mon_wt  <= normal_ok_aux && ((st_flush && cyc_zero) || (st_acq && (acq_win || !cyc_zero)) || (st_trk && !trk_qto));
            state_id      <= nxt_state_id;
            busy          <= normal_ok_aux && busy_raw;
            fault         <= nxt_flt_a;
            precharge_raw <= nxt_pre;
            pfd_rst_b_raw <= normal_ok_aux && ((st_gap && cyc_zero) || st_flush || (st_acq && (acq_win || !cyc_zero)) || (st_trk && !trk_qto));
            cp_en_raw     <= normal_ok_aux && ((st_flush && cyc_zero) || (st_acq && (acq_win || !cyc_zero)) || (st_trk && !trk_qto));
            locked_raw    <= nxt_trk_a;

            // Direct per-bit fault_code update (eliminates fc_any mux -> cuts 2-3 gates off fault_code[2:0]!)
            fault_code[2] <= fc_clr ? 1'b0 : (st_flt ? (abort_sync[1] ? 1'b1 : fault_code[2]) : fc_val[2]);
            fault_code[1] <= fc_clr ? 1'b0 : (st_flt ? (abort_sync[1] ? 1'b0 : fault_code[1]) : fc_val[1]);
            fault_code[0] <= fc_clr ? 1'b0 : (st_flt ? (abort_sync[1] ? 1'b1 : fault_code[0]) : fc_val[0]);
        end
    end
endmodule

// Exact v1-compatible wrapper for standalone tb_pll_startup_supervisor
module pll_startup_supervisor #(
    parameter integer PRECHARGE_CYCLES       = 128,
    parameter integer GAP_CYCLES             = 2,
    parameter integer PFD_FLUSH_CYCLES       = 2,
    parameter integer GOOD_WINDOWS           = 4,
    parameter integer BAD_WINDOWS            = 2,
    parameter integer QUALITY_TIMEOUT_CYCLES = 128,
    parameter integer WAIT_TIMEOUT_CYCLES    = 4096,
    parameter integer ACQUIRE_TIMEOUT_CYCLES = 4096,
    parameter integer SYNC_SAFE_OUT          = 0
) (
    input  wire       ref_clk,
    input  wire       rst_n,
    input  wire       enable,
    input  wire       start,
    input  wire       bias_ready,
    input  wire       pre_ref_ready,
    input  wire       quality_valid,
    input  wire       frequency_good,
    input  wire       phase_good,
    input  wire       range_fault,
    input  wire       abort_async,
    output wire       precharge_en,
    output wire       pfd_rst_b,
    output wire       cp_en,
    output wire       locked,
    output wire       busy,
    output wire       fault,
    output wire [2:0] state_id,
    output wire [2:0] fault_code
);
    pll_startup_supervisor_core #(
        .PRECHARGE_CYCLES(PRECHARGE_CYCLES), .GAP_CYCLES(GAP_CYCLES),
        .PFD_FLUSH_CYCLES(PFD_FLUSH_CYCLES), .GOOD_WINDOWS(GOOD_WINDOWS),
        .BAD_WINDOWS(BAD_WINDOWS), .QUALITY_TIMEOUT_CYCLES(QUALITY_TIMEOUT_CYCLES),
        .WAIT_TIMEOUT_CYCLES(WAIT_TIMEOUT_CYCLES), .ACQUIRE_TIMEOUT_CYCLES(ACQUIRE_TIMEOUT_CYCLES),
        .SYNC_SAFE_OUT(SYNC_SAFE_OUT), .EXT_RAILS_Q(0)
    ) u_core (
        .ref_clk(ref_clk), .rst_n(rst_n), .enable(enable), .start(start),
        .bias_ready(bias_ready), .pre_ref_ready(pre_ref_ready), .rails_q_in(6'b000000),
        .quality_valid(quality_valid), .quality_valid_fsm(quality_valid), .frequency_good(frequency_good), .phase_good(phase_good),
        .range_fault(range_fault), .abort_async(abort_async),
        .precharge_en(precharge_en), .pfd_rst_b(pfd_rst_b), .cp_en(cp_en),
        .locked(locked), .busy(busy), .fault(fault),
        .state_id(state_id), .fault_code(fault_code)
    );
endmodule
