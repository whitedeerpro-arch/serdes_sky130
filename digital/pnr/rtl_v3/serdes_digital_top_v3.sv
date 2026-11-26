// Lean Architecture-Optimized Unified Digital Top Macro (serdes_digital_top_v3).
//
// Combines all 4 SKY130A SerDes digital subsystems into one ultra-compact macro while
// keeping exact external 250 MHz clock ports:
//   1. tx_ingress_control            — full-rate 250 MHz (4.0 ns) tx_word_clk
//   2. rx_word_map (shared) + rx_word_host_shared (rx_word_align16 + rx_async_word_fifo_core)
//                                    — full-rate 250 MHz (4.0 ns) rx_word_clk & host_clk
//   3. rx_cdr_loop (v3)              — 250 MHz 2-tick BBPD pre-accumulator -> internal
//                                      synchronous /2 (125 MHz / 8.0 ns) filter + PI commutator
//                                      with exact physical bitwidths (17b freq, 23b debt)
//   4. pll_control_top (v3, 5-bit)   — internal synchronous /4 (62.5 MHz / 16.0 ns) control
//                                      domain from ref_clk with identical wall-clock timers
module serdes_digital_top_v3 #(
    // PLL control parameters (specified in 250 MHz ref_clk cycles; scaled /4 internally)
    parameter integer PLL_PRECHARGE_CYCLES       = 128,
    parameter integer PLL_SETTLE_CYCLES          = 512,
    parameter integer PLL_SAMPLE_DIV             = 16,
    parameter integer PLL_PERSIST                = 8,
    parameter integer PLL_HOLD_CYCLES            = 2048,
    parameter integer PLL_WINDOW                 = 32,
    parameter integer PLL_GOOD_WINDOWS           = 4,
    parameter integer PLL_BAD_WINDOWS            = 2,
    parameter integer PLL_QUALITY_TIMEOUT_CYCLES = 256,
    parameter integer PLL_CODE_BITS              = 5,
    parameter integer PLL_ACQ_TIMEOUT_CYCLES     = 1024 * (2**PLL_CODE_BITS),
    // TX ingress parameters
    parameter [15:0]  TX_IDLE_WORD               = 16'h0000,
    parameter integer TX_WARMUP_FALLS            = 1,
    // RX word host path parameters
    parameter [15:0]  RX_TRAIN_WORD              = 16'hb5e3,
    parameter integer RX_TRAIN_HITS              = 4,
    parameter integer RX_FIFO_ADDR_BITS          = 4
) (
    // -------------------------------------------------------------------------
    // Global resets
    // -------------------------------------------------------------------------
    input  wire                        rst_n,    // Async active-low reset for PLL, TX, RX map & CDR
    input  wire                        arst_n,   // Async active-low epoch reset for RX align & async FIFO

    // -------------------------------------------------------------------------
    // West-South: PLL analog interface (250 MHz ref_clk -> internal /4 62.5 MHz)
    // -------------------------------------------------------------------------
    input  wire                        ref_clk,
    input  wire                        bias_ready_async,
    input  wire                        pre_ref_ready_async,
    input  wire                        hi_async,
    input  wire                        lo_async,
    input  wire                        pw_late_async,
    output wire                        precharge_en,
    output wire                        pfd_rst_b,
    output wire                        cp_en,
    output wire                        pll_pw_clr_b,
    output wire [PLL_CODE_BITS-1:0]    vco_code,
    output wire [7:0]                  switches,

    // -------------------------------------------------------------------------
    // West & North-West: PLL host control, calibration & status
    // -------------------------------------------------------------------------
    input  wire                        pll_enable,
    input  wire                        pll_start,
    input  wire                        pll_abort_async,
    input  wire [1:0]                  pll_tclass,
    input  wire [3:0]                  pll_lo_run,
    input  wire [3:0]                  pll_hi_run,
    input  wire [11:0]                 pll_stop_code,
    input  wire [2:0]                  pll_stop_sel,
    output wire                        pll_locked,
    output wire                        pll_busy,
    output wire                        pll_fault,
    output wire [2:0]                  pll_state_id,
    output wire [2:0]                  pll_fault_code,
    output wire [3:0]                  pll_lo_code,
    output wire [3:0]                  pll_hi_code,
    output wire                        pll_coarse_busy,
    output wire                        pll_coarse_done,
    output wire                        pll_fast_end,
    output wire                        pll_slow_end,

    // -------------------------------------------------------------------------
    // Mid-South: TX analog/serializer interface (250 MHz tx_word_clk)
    // -------------------------------------------------------------------------
    input  wire                        tx_word_clk,
    input  wire                        tx_clock_good,
    output wire [15:0]                 tx_capture_data,
    output wire                        tx_capture_valid,
    output wire                        tx_a_valid,
    output wire                        tx_b_valid,

    // -------------------------------------------------------------------------
    // North (West-Mid): TX host interface (250 MHz tx_word_clk)
    // -------------------------------------------------------------------------
    input  wire                        tx_enable,
    input  wire                        tx_in_valid,
    input  wire [15:0]                 tx_in_data,
    output wire                        tx_word_ready,

    // -------------------------------------------------------------------------
    // East-South: RX analog/deserializer & PI interface (250 MHz rx_word_clk)
    // -------------------------------------------------------------------------
    input  wire                        rx_word_clk,
    input  wire [31:0]                 rx_phys,
    output wire [5:0]                  rx_phase_code,
    output wire [7:0]                  rx_select_a,
    output wire [7:0]                  rx_select_b,
    output wire [7:0]                  rx_fine_b,

    // -------------------------------------------------------------------------
    // North (Mid-East): RX host FIFO & word alignment (250 MHz host_clk & rx_word_clk)
    // -------------------------------------------------------------------------
    input  wire                        host_clk,
    input  wire                        host_ready,
    output wire [15:0]                 host_data,
    output wire                        host_valid,
    output wire                        host_online,
    output wire                        host_error,
    input  wire                        rx_training_enable,
    output wire                        rx_word_online,
    output wire                        rx_aligned,
    output wire [3:0]                  rx_offset,

    // -------------------------------------------------------------------------
    // East: RX CDR control, status & exact-width telemetry (internal /2 125 MHz)
    // -------------------------------------------------------------------------
    input  wire                        rx_cdr_enable,
    output wire                        rx_cdr_locked,
    output wire                        rx_cdr_holdover,
    output wire                        rx_cdr_range_limited,
    output wire                        rx_cdr_phase_applied,
    output wire signed [16:0]          rx_cdr_frequency_q,
    output wire signed [22:0]          rx_cdr_phase_debt_q
);
    // =========================================================================
    // 0. Per-Domain 2-FF Async-Assert / Sync-Deassert Reset Synchronizers
    //    Guarantees clean synchronous release in every independent clock domain
    //    (prevents cdr_clk_div2_q / phase_hi_q split-release & TX word_ready split).
    // =========================================================================
    (* ASYNC_REG = "TRUE" *) reg [1:0] ref_rst_sync;
    (* ASYNC_REG = "TRUE" *) reg [1:0] tx_rst_sync;
    (* ASYNC_REG = "TRUE" *) reg [1:0] rx_rst_sync;

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) ref_rst_sync <= 2'b00;
        else        ref_rst_sync <= {ref_rst_sync[0], 1'b1};
    end
    always @(posedge tx_word_clk or negedge rst_n) begin
        if (!rst_n) tx_rst_sync <= 2'b00;
        else        tx_rst_sync <= {tx_rst_sync[0], 1'b1};
    end
    always @(posedge rx_word_clk or negedge rst_n) begin
        if (!rst_n) rx_rst_sync <= 2'b00;
        else        rx_rst_sync <= {rx_rst_sync[0], 1'b1};
    end

    wire ref_rst_n = ref_rst_sync[1];
    wire tx_rst_n  = tx_rst_sync[1];
    wire rx_rst_n  = rx_rst_sync[1];

    // =========================================================================
    // 1. PLL Control Top v3 (5-bit coarse VCO code, /4 62.5 MHz internal domain)
    // =========================================================================
    pll_control_top #(
        .PRECHARGE_CYCLES      (PLL_PRECHARGE_CYCLES),
        .SETTLE_CYCLES         (PLL_SETTLE_CYCLES),
        .SAMPLE_DIV            (PLL_SAMPLE_DIV),
        .PERSIST               (PLL_PERSIST),
        .HOLD_CYCLES           (PLL_HOLD_CYCLES),
        .WINDOW                (PLL_WINDOW),
        .GOOD_WINDOWS          (PLL_GOOD_WINDOWS),
        .BAD_WINDOWS           (PLL_BAD_WINDOWS),
        .QUALITY_TIMEOUT_CYCLES(PLL_QUALITY_TIMEOUT_CYCLES),
        .CODE_BITS             (PLL_CODE_BITS),
        .ACQ_TIMEOUT_CYCLES    (PLL_ACQ_TIMEOUT_CYCLES)
    ) u_pll (
        .ref_clk            (ref_clk),
        .rst_n              (ref_rst_n),
        .enable             (pll_enable),
        .start              (pll_start),
        .abort_async        (pll_abort_async),
        .bias_ready_async   (bias_ready_async),
        .pre_ref_ready_async(pre_ref_ready_async),
        .tclass             (pll_tclass),
        .hi_async           (hi_async),
        .lo_async           (lo_async),
        .pw_late_async      (pw_late_async),
        .lo_run             (pll_lo_run),
        .hi_run             (pll_hi_run),
        .stop_code          (pll_stop_code),
        .stop_sel           (pll_stop_sel),
        .precharge_en       (precharge_en),
        .pfd_rst_b          (pfd_rst_b),
        .cp_en              (cp_en),
        .pw_clr_b           (pll_pw_clr_b),
        .locked             (pll_locked),
        .busy               (pll_busy),
        .fault              (pll_fault),
        .state_id           (pll_state_id),
        .fault_code         (pll_fault_code),
        .vco_code           (vco_code),
        .lo_code            (pll_lo_code),
        .hi_code            (pll_hi_code),
        .coarse_busy        (pll_coarse_busy),
        .coarse_done        (pll_coarse_done),
        .fast_end           (pll_fast_end),
        .slow_end           (pll_slow_end),
        .switches           (switches)
    );

    // =========================================================================
    // 2. TX Ingress Control (250 MHz tx_word_clk)
    // =========================================================================
    tx_ingress_control #(
        .IDLE_WORD   (TX_IDLE_WORD),
        .WARMUP_FALLS(TX_WARMUP_FALLS)
    ) u_tx (
        .word_clk     (tx_word_clk),
        .rst_n        (tx_rst_n),
        .enable       (tx_enable),
        .clock_good   (tx_clock_good),
        .in_valid     (tx_in_valid),
        .in_data      (tx_in_data),
        .word_ready   (tx_word_ready),
        .capture_data (tx_capture_data),
        .capture_valid(tx_capture_valid),
        .a_valid      (tx_a_valid),
        .b_valid      (tx_b_valid)
    );

    // =========================================================================
    // 3. Shared RX Word Mapper (250 MHz rx_word_clk) -> Align/FIFO + CDR
    // =========================================================================
    wire [15:0] rx_map_data;
    wire [15:0] rx_map_edges;
    wire        rx_map_prev;
    wire        rx_map_bundle_valid;

    rx_word_map u_rx_map (
        .clk          (rx_word_clk),
        .rst_n        (rx_rst_n),
        .phys         (rx_phys),
        .data_samples (rx_map_data),
        .edge_samples (rx_map_edges),
        .previous_data(rx_map_prev),
        .bundle_valid (rx_map_bundle_valid)
    );

    // =========================================================================
    // 4. RX Word Align + Async Word FIFO (250 MHz rx_word_clk -> 250 MHz host_clk)
    // =========================================================================
    rx_word_host_shared #(
        .TRAIN_WORD(RX_TRAIN_WORD),
        .TRAIN_HITS(RX_TRAIN_HITS),
        .ADDR_BITS (RX_FIFO_ADDR_BITS)
    ) u_rx_host (
        .word_clk       (rx_word_clk),
        .host_clk       (host_clk),
        .arst_n         (arst_n),
        .data_samples   (rx_map_data),
        .bundle_valid   (rx_map_bundle_valid),
        .training_enable(rx_training_enable),
        .host_data      (host_data),
        .host_valid     (host_valid),
        .host_ready     (host_ready),
        .word_online    (rx_word_online),
        .host_online    (host_online),
        .aligned        (rx_aligned),
        .offset         (rx_offset),
        .host_error     (host_error)
    );

    // =========================================================================
    // 5. RX CDR Loop v3 (250 MHz pre-accum -> /2 125 MHz filter + commutator)
    // =========================================================================
    rx_cdr_loop u_rx_cdr (
        .ctrl_clk     (rx_word_clk),
        .rst_n        (rx_rst_n),
        .enable       (rx_cdr_enable),
        .bundle_valid (rx_map_bundle_valid),
        .previous_data(rx_map_prev),
        .data_samples (rx_map_data),
        .edge_samples (rx_map_edges),
        .phase_code   (rx_phase_code),
        .select_a     (rx_select_a),
        .select_b     (rx_select_b),
        .fine_b       (rx_fine_b),
        .locked       (rx_cdr_locked),
        .holdover     (rx_cdr_holdover),
        .range_limited(rx_cdr_range_limited),
        .phase_applied(rx_cdr_phase_applied),
        .frequency_q  (rx_cdr_frequency_q),
        .phase_debt_q (rx_cdr_phase_debt_q)
    );
endmodule

/* verilator lint_off DECLFILENAME */
module rx_word_host_shared #(
    parameter [15:0]  TRAIN_WORD = 16'hb5e3,
    parameter integer TRAIN_HITS = 4,
    parameter integer ADDR_BITS  = 4
) (
    input  wire        word_clk,
    input  wire        host_clk,
    input  wire        arst_n,
    input  wire [15:0] data_samples,
    input  wire        bundle_valid,
    input  wire        training_enable,
    output wire [15:0] host_data,
    output wire        host_valid,
    input  wire        host_ready,
    output wire        word_online,
    output wire        host_online,
    output wire        aligned,
    output wire [3:0]  offset,
    output wire        host_error
);
    wire [15:0] aligned_data;
    wire        aligned_valid;
    wire        fifo_ready;
    wire        fifo_overflow;
    wire        host_overflow;
    wire        word_online_int;
    reg         align_prime0;
    reg         align_prime1;
    reg         payload_started;
    reg         source_fault;
    (* ASYNC_REG = "TRUE" *) reg [1:0] fault_host;
    (* ASYNC_REG = "TRUE" *) reg [1:0] rx_arst_sync;
    (* ASYNC_REG = "TRUE" *) reg [1:0] host_arst_sync;

    always @(posedge word_clk or negedge arst_n) begin
        if (!arst_n) rx_arst_sync <= 2'b00;
        else         rx_arst_sync <= {rx_arst_sync[0], 1'b1};
    end
    always @(posedge host_clk or negedge arst_n) begin
        if (!arst_n) host_arst_sync <= 2'b00;
        else         host_arst_sync <= {host_arst_sync[0], 1'b1};
    end
    wire rx_arst_n   = rx_arst_sync[1];
    wire host_arst_n = host_arst_sync[1];

    // Clean per-domain synchronized async reset + synchronous clear on !word_online_int
    always @(posedge word_clk or negedge rx_arst_n) begin
        if (!rx_arst_n) begin
            align_prime0 <= 1'b0;
            align_prime1 <= 1'b0;
        end else if (!word_online_int) begin
            align_prime0 <= 1'b0;
            align_prime1 <= 1'b0;
        end else begin
            align_prime0 <= 1'b1;
            align_prime1 <= align_prime0;
        end
    end

    wire align_chunk_valid = bundle_valid && align_prime1;

    rx_word_align16 #(
        .TRAIN_WORD(TRAIN_WORD),
        .TRAIN_HITS(TRAIN_HITS)
    ) u_align (
        .clk            (word_clk),
        .rst_n          (rx_arst_n),
        .sclr           (!word_online_int),
        .chunk_valid    (align_chunk_valid),
        .training_enable(training_enable),
        .chunk          (data_samples),
        .word_data      (aligned_data),
        .word_valid     (aligned_valid),
        .aligned        (aligned),
        .offset         (offset)
    );

    wire wv_a       = aligned_valid && !training_enable;
    wire retraining = training_enable && (payload_started || aligned_valid);
    wire ovf_hit    = word_online_int && wv_a && !source_fault && !fifo_ready;

    always @(posedge word_clk or negedge rx_arst_n) begin
        if (!rx_arst_n) begin
            payload_started <= 1'b0;
            source_fault    <= 1'b0;
        end else if (!word_online_int) begin
            payload_started <= 1'b0;
            source_fault    <= 1'b0;
        end else begin
            if (wv_a)                  payload_started <= 1'b1;
            if (retraining || ovf_hit) source_fault    <= 1'b1;
        end
    end

    rx_async_word_fifo_core #(
        .DATA_WIDTH(16),
        .ADDR_BITS (ADDR_BITS)
    ) u_fifo (
        .w_clk       (word_clk),
        .r_clk       (host_clk),
        .arst_n      (arst_n),
        .w_valid     (wv_a && !source_fault),
        .w_data      (aligned_data),
        .w_ready     (fifo_ready),
        .w_online    (word_online),
        .w_online_rst(word_online_int),
        .w_overflow  (fifo_overflow),
        .r_valid     (host_valid),
        .r_online    (host_online),
        .r_overflow  (host_overflow),
        .r_data      (host_data),
        .r_ready     (host_ready)
    );

    reg host_error_r;
    // Clean per-domain synchronized async reset + synchronous clear on !host_online
    always @(posedge host_clk or negedge host_arst_n) begin
        if (!host_arst_n) begin
            fault_host   <= 2'b00;
            host_error_r <= 1'b0;
        end else if (!host_online) begin
            fault_host   <= 2'b00;
            host_error_r <= 1'b0;
        end else begin
            fault_host   <= {fault_host[0], source_fault};
            host_error_r <= host_overflow | fault_host[1];
        end
    end

    assign host_error = host_error_r;

    wire _unused_fifo_overflow = fifo_overflow;
endmodule
