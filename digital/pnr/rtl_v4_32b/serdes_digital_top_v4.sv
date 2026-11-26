// 32-Bit Down-Clocked Unified Digital Top Macro (serdes_digital_top_v4).
//
// Architectural highlights:
//   - Preserves ALL 106 South analog-facing pins identically to v3.3 for seamless chip-top drop-in!
//   - Sustained host throughput >= 5.0 Gb/s: 32-bit TX & RX host ports on host_clk = 180 MHz
//     (5.76 Gb/s peak, safely above 5.0 Gb/s 5G & 4.0 Gb/s 4G line rates!).
//   - Thin 250 / 312.5 MHz analog boundaries ONLY:
//       * tx_word_clk (~41 FFs): dedicated clock-only tx_div2_q + 1-MUX 32->16 gearbox (2-cycle safe handoff)
//       * rx_word_clk (~140 FFs): u_rx_map (33 FFs on RXMAP_SHORT_TAP) + zero-logic 16->32 phase-safe packer
//   - All heavy digital cores run at 1/2 word rate (125 MHz @ 4G / 156.25 MHz @ 5G = 6.40 ns!):
//       * tx_clk_div2: 16x32 TX async FIFO read side + warmup/idle (32'hA55A_A55A)
//       * rx_clk_div2: rx_word_align32 + 16x32 RX async FIFO write side + native 32-UI rx_cdr_loop_v4
//       * pll_clk_div4 (62.5 MHz): 5-bit PLL startup/coarse/lock (262 us LDO cold-boot timeout, shared u_hilo)
//   - Tapeout-Audit clean: strict D-C1 sync1 fanout=1 on ALL CDC FFs, M2 write-gated non-reset FIFO mems,
//     per-domain external rst_n/arst_n synchronizers (zero cross-clock async removal violations!).
module serdes_digital_top_v4 #(
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
    parameter integer PLL_WAIT_TIMEOUT_CYCLES    = 65536,
    parameter integer PLL_CODE_BITS              = 5,
    parameter integer PLL_ACQ_TIMEOUT_CYCLES     = 1024 * (2**PLL_CODE_BITS),
    // TX ingress parameters
    parameter [15:0]  TX_IDLE_WORD               = 16'hA55A,
    parameter integer TX_WARMUP_FALLS            = 1,
    parameter integer TX_FIFO_ADDR_BITS          = 3,
    // RX word host path parameters
    parameter [15:0]  RX_TRAIN_WORD              = 16'hb5e3,
    parameter integer RX_TRAIN_HITS              = 4,
    parameter integer RX_FIFO_ADDR_BITS          = 3
) (
    // -------------------------------------------------------------------------
    // Global resets
    // -------------------------------------------------------------------------
    input  wire                        rst_n,    // Async active-low reset for PLL, TX, RX pack & CDR
    input  wire                        arst_n,   // Async active-low epoch reset for RX align32 & RX async FIFO

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
    // Mid-South: TX analog/serializer interface (250 / 312.5 MHz tx_word_clk)
    // -------------------------------------------------------------------------
    input  wire                        tx_word_clk,
    input  wire                        tx_clock_good,
    output wire [15:0]                 tx_capture_data,
    output wire                        tx_capture_valid,
    output wire                        tx_a_valid,
    output wire                        tx_b_valid,

    // -------------------------------------------------------------------------
    // North (West-Mid): 32-bit TX host interface (180 MHz host_clk -> 5.76 Gb/s!)
    // -------------------------------------------------------------------------
    input  wire                        tx_enable,
    input  wire                        tx_in_valid,
    input  wire [31:0]                 tx_in_data,
    output wire                        tx_word_ready,
    output wire                        tx_underrun,

    // -------------------------------------------------------------------------
    // East-South: RX analog/deserializer & PI interface (250 / 312.5 MHz rx_word_clk)
    // -------------------------------------------------------------------------
    input  wire                        rx_word_clk,
    input  wire [31:0]                 rx_phys,
    output wire [5:0]                  rx_phase_code,
    output wire [7:0]                  rx_select_a,
    output wire [7:0]                  rx_select_b,
    output wire [7:0]                  rx_fine_b,

    // -------------------------------------------------------------------------
    // North (Mid-East): 32-bit RX host FIFO & word alignment (180 MHz host_clk & rx_clk_div2)
    // -------------------------------------------------------------------------
    input  wire                        host_clk,
    input  wire                        host_ready,
    output wire [31:0]                 host_data,
    output wire                        host_valid,
    output wire                        host_online,
    output wire                        host_error,
    input  wire                        rx_training_enable,
    output wire                        rx_word_online,
    output wire                        rx_aligned,
    output wire [3:0]                  rx_offset,

    // -------------------------------------------------------------------------
    // East: RX CDR control, status & exact-width telemetry (rx_clk_div2 125 / 156.25 MHz)
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
    // 1. PLL Control Top (5-bit coarse VCO code, /4 62.5 MHz internal domain)
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
        .WAIT_TIMEOUT_CYCLES   (PLL_WAIT_TIMEOUT_CYCLES),
        .CODE_BITS             (PLL_CODE_BITS),
        .ACQ_TIMEOUT_CYCLES    (PLL_ACQ_TIMEOUT_CYCLES)
    ) u_pll (
        .ref_clk            (ref_clk),
        .rst_n              (rst_n),
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
    // 2. TX 32-bit Ingress + 16x32 Async FIFO + Thin 32->16 Output Gearbox
    // =========================================================================
    tx_ingress_control_32 #(
        .IDLE_WORD     (TX_IDLE_WORD),
        .WARMUP_FALLS  (TX_WARMUP_FALLS),
        .FIFO_ADDR_BITS(TX_FIFO_ADDR_BITS)
    ) u_tx (
        .rst_n           (rst_n),
        .host_clk        (host_clk),
        .tx_enable       (tx_enable),
        .tx_in_valid     (tx_in_valid),
        .tx_in_data      (tx_in_data),
        .tx_word_ready   (tx_word_ready),
        .tx_underrun     (tx_underrun),
        .tx_word_clk     (tx_word_clk),
        .tx_clock_good   (tx_clock_good),
        .tx_capture_data (tx_capture_data),
        .tx_capture_valid(tx_capture_valid),
        .tx_a_valid      (tx_a_valid),
        .tx_b_valid      (tx_b_valid)
    );

    // =========================================================================
    // 3. RX Thin Analog Boundary (rx_word_clk: u_rx_map + 16->32 phase-safe packer)
    // =========================================================================
    wire [15:0] rx_map_data;
    wire [15:0] rx_map_edge;
    wire        rx_map_prev;
    wire        rx_map_valid;
    wire        rx_word_rst_n;
    (* keep = "true" *) wire rx_clk_div2;
    wire        rx_pack_valid;
    wire        rx_pack_prev;
    wire [31:0] rx_pack_data;
    wire [31:0] rx_pack_edge;

    rx_word_map u_rx_map (
        .clk          (rx_word_clk),
        .rst_n        (rx_word_rst_n),
        .phys         (rx_phys),
        .data_samples (rx_map_data),
        .edge_samples (rx_map_edge),
        .previous_data(rx_map_prev),
        .bundle_valid (rx_map_valid)
    );

    rx_pack_16to32 u_rx_pack (
        .rx_word_clk  (rx_word_clk),
        .rst_n        (rst_n),
        .in_valid     (rx_map_valid),
        .word_data    (rx_map_data),
        .word_edge    (rx_map_edge),
        .prev_data    (rx_map_prev),
        .rx_clk_div2  (rx_clk_div2),
        .rx_word_rst_n(rx_word_rst_n),
        .pack_valid   (rx_pack_valid),
        .pack_prev    (rx_pack_prev),
        .pack_data    (rx_pack_data),
        .pack_edge    (rx_pack_edge)
    );

    // =========================================================================
    // 4. RX 32-bit Word Aligner + 16x32 Async FIFO (rx_clk_div2 -> host_clk)
    //    Shares single arst_n reset synchronizer between aligner & RX FIFO (D-H3)!
    // =========================================================================
    rx_word_host_32 #(
        .TRAIN_WORD(RX_TRAIN_WORD),
        .TRAIN_HITS(RX_TRAIN_HITS),
        .ADDR_BITS (RX_FIFO_ADDR_BITS)
    ) u_rx_host (
        .arst_n         (arst_n),
        .rx_clk_div2    (rx_clk_div2),
        .in_valid       (rx_pack_valid),
        .in_word        (rx_pack_data),
        .training_enable(rx_training_enable),
        .word_online    (rx_word_online),
        .aligned        (rx_aligned),
        .offset         (rx_offset),
        .host_clk       (host_clk),
        .host_ready     (host_ready),
        .host_data      (host_data),
        .host_valid     (host_valid),
        .host_online    (host_online),
        .host_error     (host_error)
    );

    // =========================================================================
    // 5. Native 32-UI RX CDR Loop (rx_clk_div2, 125 / 156.25 MHz)
    // =========================================================================
    rx_cdr_loop_v4 u_rx_cdr (
        .rx_clk_div2  (rx_clk_div2),
        .rst_n        (rst_n),
        .enable       (rx_cdr_enable),
        .bundle_valid (rx_pack_valid),
        .previous_data(rx_pack_prev),
        .data_samples (rx_pack_data),
        .edge_samples (rx_pack_edge),
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
