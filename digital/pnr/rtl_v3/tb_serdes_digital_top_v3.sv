`timescale 1ns/1ps
// Full 4-subsystem integration testbench for unified serdes_digital_top_v3:
//   1. PLL startup + 5-bit coarse VCO search + lock detect (internal /4 62.5 MHz from 250 MHz ref_clk)
//   2. TX ingress warmup + word capture + A/B in-flight pipeline (250 MHz tx_word_clk)
//   3. Shared rx_word_map -> RX word aligner + async FIFO across async rx_word_clk/host_clk (250 MHz)
//   4. Shared rx_word_map -> RX CDR loop (/2 125 MHz, exact bitwidths) tracking across arst_n epoch reset
module tb_serdes_digital_top_v3;
    localparam integer PLL_PRECHARGE = 16;
    localparam integer PLL_SETTLE    = 16;
    localparam integer PLL_SDIV      = 8;
    localparam integer PLL_PERSIST   = 2;
    localparam integer PLL_HOLD      = 32;
    localparam integer PLL_WIN       = 16;
    localparam integer PLL_GOOD_W    = 2;
    localparam integer PLL_BAD_W     = 2;
    localparam integer PLL_QTO       = 256;
    localparam integer PLL_ATO       = 4096;

    reg         rst_n               = 1'b0;
    reg         arst_n              = 1'b0;
    reg         ref_clk             = 1'b0;
    reg         tx_word_clk         = 1'b0;
    reg         rx_word_clk         = 1'b0;
    reg         host_clk            = 1'b0;

    reg         bias_ready_async    = 1'b0;
    reg         pre_ref_ready_async = 1'b0;
    reg         hi_async            = 1'b0;
    reg         lo_async            = 1'b0;
    reg         pw_late_async       = 1'b0;
    reg         pll_enable          = 1'b0;
    reg         pll_start           = 1'b0;
    reg         pll_abort_async     = 1'b0;
    reg  [1:0]  pll_tclass          = 2'd1;
    reg  [3:0]  pll_lo_run          = 4'd2;
    reg  [3:0]  pll_hi_run          = 4'd2;
    reg  [11:0] pll_stop_code       = 12'd0;
    reg  [2:0]  pll_stop_sel        = 3'd0;
    wire        precharge_en, pfd_rst_b, cp_en;
    wire [4:0]  vco_code;
    wire [7:0]  switches;
    wire        pll_locked, pll_busy, pll_fault;
    wire [2:0]  pll_state_id, pll_fault_code;
    wire [3:0]  pll_lo_code, pll_hi_code;
    wire        pll_coarse_busy, pll_coarse_done, pll_fast_end, pll_slow_end;

    reg         tx_clock_good       = 1'b0;
    reg         tx_enable           = 1'b0;
    reg         tx_in_valid         = 1'b0;
    reg  [15:0] tx_in_data          = 16'h0000;
    wire        tx_word_ready;
    wire [15:0] tx_capture_data;
    wire        tx_capture_valid, tx_a_valid, tx_b_valid;

    reg  [31:0] rx_phys             = 32'd0;
    reg         host_ready          = 1'b0;
    reg         rx_training_enable  = 1'b1;
    reg         rx_cdr_enable       = 1'b0;
    wire [5:0]  rx_phase_code;
    wire [7:0]  rx_select_a, rx_select_b, rx_fine_b;
    wire [15:0] host_data;
    wire        host_valid, host_online, host_error;
    wire        rx_word_online, rx_aligned;
    wire [3:0]  rx_offset;
    wire        rx_cdr_locked, rx_cdr_holdover, rx_cdr_range_limited, rx_cdr_phase_applied;
    wire signed [16:0] rx_cdr_frequency_q;
    wire signed [22:0] rx_cdr_phase_debt_q;

    serdes_digital_top_v3 #(
        .PLL_PRECHARGE_CYCLES      (PLL_PRECHARGE),
        .PLL_SETTLE_CYCLES         (PLL_SETTLE),
        .PLL_SAMPLE_DIV            (PLL_SDIV),
        .PLL_PERSIST               (PLL_PERSIST),
        .PLL_HOLD_CYCLES           (PLL_HOLD),
        .PLL_WINDOW                (PLL_WIN),
        .PLL_GOOD_WINDOWS          (PLL_GOOD_W),
        .PLL_BAD_WINDOWS           (PLL_BAD_W),
        .PLL_QUALITY_TIMEOUT_CYCLES(PLL_QTO),
        .PLL_CODE_BITS             (5),
        .PLL_ACQ_TIMEOUT_CYCLES    (PLL_ATO)
    ) dut (
        .rst_n               (rst_n),
        .arst_n              (arst_n),
        .ref_clk             (ref_clk),
        .bias_ready_async    (bias_ready_async),
        .pre_ref_ready_async (pre_ref_ready_async),
        .hi_async            (hi_async),
        .lo_async            (lo_async),
        .pw_late_async       (pw_late_async),
        .precharge_en        (precharge_en),
        .pfd_rst_b           (pfd_rst_b),
        .cp_en               (cp_en),
        .vco_code            (vco_code),
        .switches            (switches),
        .pll_enable          (pll_enable),
        .pll_start           (pll_start),
        .pll_abort_async     (pll_abort_async),
        .pll_tclass          (pll_tclass),
        .pll_lo_run          (pll_lo_run),
        .pll_hi_run          (pll_hi_run),
        .pll_stop_code       (pll_stop_code),
        .pll_stop_sel        (pll_stop_sel),
        .pll_locked          (pll_locked),
        .pll_busy            (pll_busy),
        .pll_fault           (pll_fault),
        .pll_state_id        (pll_state_id),
        .pll_fault_code      (pll_fault_code),
        .pll_lo_code         (pll_lo_code),
        .pll_hi_code         (pll_hi_code),
        .pll_coarse_busy     (pll_coarse_busy),
        .pll_coarse_done     (pll_coarse_done),
        .pll_fast_end        (pll_fast_end),
        .pll_slow_end        (pll_slow_end),
        .tx_word_clk         (tx_word_clk),
        .tx_clock_good       (tx_clock_good),
        .tx_capture_data     (tx_capture_data),
        .tx_capture_valid    (tx_capture_valid),
        .tx_a_valid          (tx_a_valid),
        .tx_b_valid          (tx_b_valid),
        .tx_enable           (tx_enable),
        .tx_in_valid         (tx_in_valid),
        .tx_in_data          (tx_in_data),
        .tx_word_ready       (tx_word_ready),
        .rx_word_clk         (rx_word_clk),
        .rx_phys             (rx_phys),
        .rx_phase_code       (rx_phase_code),
        .rx_select_a         (rx_select_a),
        .rx_select_b         (rx_select_b),
        .rx_fine_b           (rx_fine_b),
        .host_clk            (host_clk),
        .host_ready          (host_ready),
        .host_data           (host_data),
        .host_valid          (host_valid),
        .host_online         (host_online),
        .host_error          (host_error),
        .rx_training_enable  (rx_training_enable),
        .rx_word_online      (rx_word_online),
        .rx_aligned          (rx_aligned),
        .rx_offset           (rx_offset),
        .rx_cdr_enable       (rx_cdr_enable),
        .rx_cdr_locked       (rx_cdr_locked),
        .rx_cdr_holdover     (rx_cdr_holdover),
        .rx_cdr_range_limited(rx_cdr_range_limited),
        .rx_cdr_phase_applied(rx_cdr_phase_applied),
        .rx_cdr_frequency_q  (rx_cdr_frequency_q),
        .rx_cdr_phase_debt_q (rx_cdr_phase_debt_q)
    );

    always #2.000 ref_clk     = ~ref_clk;
    initial begin #0.31; forever #2.003 tx_word_clk = ~tx_word_clk; end
    initial begin #0.67; forever #1.997 rx_word_clk = ~rx_word_clk; end
    initial begin #1.13; forever #1.770 host_clk    = ~host_clk;    end

    always @* begin
        if (vco_code < 5'd18) begin
            lo_async = 1'b1; hi_async = 1'b0;
        end else if (vco_code > 5'd20) begin
            lo_async = 1'b0; hi_async = 1'b1;
        end else begin
            lo_async = 1'b0; hi_async = 1'b0;
        end
    end

    function automatic integer popcount8(input [7:0] v);
        integer i;
        begin
            popcount8 = 0;
            for (i = 0; i < 8; i = i + 1) popcount8 = popcount8 + v[i];
        end
    endfunction

    localparam integer NTRAIN = 12;
    function automatic [15:0] payload_word(input integer m);
        payload_word = (m * 257) ^ 16'h793d;
    endfunction

    function automatic reg sbit(input integer x);
        reg [15:0] v;
        begin
            v = ((x / 16) < NTRAIN) ? 16'hb5e3 : payload_word((x / 16) - NTRAIN);
            sbit = (v >> (x % 16)) & 1'b1;
        end
    endfunction

    task automatic drive_rx_phys(input integer s, input reg edge_late);
        integer k;
        reg d0, d1, d2, d3, e0, e1, e2, e3;
        begin
            for (k = 0; k < 4; k = k + 1) begin
                d0 = sbit(s + 12 - 4*k); d1 = sbit(s + 13 - 4*k);
                d2 = sbit(s + 14 - 4*k); d3 = sbit(s + 15 - 4*k);
                e0 = edge_late ? sbit(s + 13 - 4*k) : d0;
                e1 = edge_late ? sbit(s + 14 - 4*k) : d1;
                e2 = edge_late ? sbit(s + 15 - 4*k) : d2;
                e3 = edge_late ? sbit(s + 16 - 4*k) : d3;
                rx_phys[0*4 + k] = d0; rx_phys[2*4 + k] = e0;
                rx_phys[5*4 + k] = d1; rx_phys[7*4 + k] = e1;
                rx_phys[1*4 + k] = d2; rx_phys[3*4 + k] = e2;
                rx_phys[4*4 + k] = d3; rx_phys[6*4 + k] = e3;
            end
        end
    endtask

    integer rx_got, rx_expect, j, phase_before, phase_after, cyc;
    reg rx_checking, rx_seen_payload;
    reg [15:0] tx_sent [0:3];

    always @(posedge host_clk) begin
        if (arst_n && host_valid && host_ready && rx_checking) begin
            if (!rx_seen_payload && host_data === 16'hb5e3) begin
            end else begin
                rx_seen_payload = 1'b1;
                if (host_data !== payload_word(rx_expect))
                    $fatal(1, "RX host mismatch at idx %0d: got %04h expected %04h",
                           rx_expect, host_data, payload_word(rx_expect));
                rx_expect = rx_expect + 1;
                rx_got    = rx_got + 1;
            end
        end
    end

    initial begin
        rx_got = 0; rx_expect = 0; rx_checking = 0; rx_seen_payload = 0;
        rx_phys = 32'hffff_ffff; #0.5; rx_phys = 32'h0000_0000; #0.5;
        rst_n = 1; arst_n = 1; #1; rst_n = 0; arst_n = 0; #12; rst_n = 1; arst_n = 1;

        // 1. PLL startup + 5-bit coarse search + lock (via /4 62.5 MHz internal domain)
        @(negedge ref_clk);
        pll_enable = 1; bias_ready_async = 1; pre_ref_ready_async = 1;
        repeat (6) @(negedge ref_clk);
        pll_start = 1; @(negedge ref_clk); pll_start = 0;

        cyc = 0;
        while (!pll_locked && cyc < 5000) begin
            @(posedge ref_clk);
            cyc = cyc + 1;
        end
        if (!pll_locked || pll_fault || !cp_en || !pfd_rst_b || precharge_en)
            $fatal(1, "PLL failed to lock: locked=%b fault=%b state=%0d vco_code=%0d",
                   pll_locked, pll_fault, pll_state_id, vco_code);
        if (vco_code < 5'd17 || vco_code > 5'd21)
            $fatal(1, "PLL 5-bit coarse code out of expected band [17..21]: got %0d", vco_code);
        $display("PASS [1/4] PLL (/4 62.5 MHz) locked in %0d ref_clk cycles (vco_code=%0d, switches=0x%02h)",
                 cyc, vco_code, switches);

        // 2. TX ingress warmup + capture + A/B pipeline (250 MHz)
        tx_sent[0] = 16'ha55a; tx_sent[1] = 16'h1234; tx_sent[2] = 16'hdead; tx_sent[3] = 16'hbeef;
        @(negedge tx_word_clk); tx_enable = 1; tx_clock_good = 1;
        @(posedge tx_word_clk); #0.2;
        if (!tx_word_ready) $fatal(1, "TX word_ready did not assert");
        for (j = 0; j < 4; j = j + 1) begin
            @(negedge tx_word_clk); tx_in_valid = 1; tx_in_data = tx_sent[j];
            @(posedge tx_word_clk); #0.2;
            if (!tx_capture_valid || tx_capture_data !== tx_sent[j])
                $fatal(1, "TX capture mismatch word %0d", j);
            if (j >= 1 && !tx_a_valid) $fatal(1, "TX a_valid missing");
            if (j >= 2 && !tx_b_valid) $fatal(1, "TX b_valid missing");
        end
        @(negedge tx_word_clk); tx_in_valid = 0;
        @(posedge tx_word_clk); #0.2;
        if (tx_capture_valid || !tx_a_valid || !tx_b_valid) $fatal(1, "TX drain mismatch");
        $display("PASS [2/4] TX ingress (250 MHz) warmup, 4-word capture & A/B pipeline verified");

        // 3. Shared rx_word_map -> RX align (offset=11) + async FIFO (250 MHz)
        wait (rx_word_online && host_online);
        @(negedge rx_word_clk);
        rx_cdr_enable = 1; rx_training_enable = 1; host_ready = 1; rx_checking = 1;
        phase_before = rx_phase_code;
        for (j = 0; j < 80; j = j + 1) begin
            @(negedge rx_word_clk);
            drive_rx_phys(16 + 5 + 16*j, 1'b1);
            rx_training_enable = (j < NTRAIN - 1);
        end
        rx_checking = 0;
        if (!rx_aligned || rx_offset !== 4'd11 || rx_got < 45 || host_error)
            $fatal(1, "RX host path failed: aligned=%b offset=%0d got=%0d err=%b",
                   rx_aligned, rx_offset, rx_got, host_error);
        $display("PASS [3/4] RX shared-map align & async FIFO (250 MHz) verified (offset=%0d, words=%0d, err=%b)",
                 rx_offset, rx_got, host_error);

        // 4. Shared rx_word_map -> RX CDR (/2 125 MHz) tracking across arst_n epoch reset
        for (j = 80; j < 280; j = j + 1) begin
            @(negedge rx_word_clk);
            drive_rx_phys(16 + 5 + 16*j, 1'b1);
            if (j == 140) arst_n = 1'b0;
            if (j == 148) arst_n = 1'b1;
        end
        phase_after = rx_phase_code;
        if ((^{rx_phase_code, rx_select_a, rx_select_b, rx_fine_b, rx_cdr_frequency_q, rx_cdr_phase_debt_q}) === 1'bx)
            $fatal(1, "RX CDR produced X");
        if (phase_after == phase_before && rx_cdr_phase_debt_q == 0 && rx_cdr_frequency_q == 0)
            $fatal(1, "RX CDR failed to track");
        if (popcount8(rx_select_a) != 1 || popcount8(rx_select_b) != 1)
            $fatal(1, "RX PI select_a/select_b not one-hot");
        $display("PASS [4/4] RX CDR (/2 125 MHz) tracked via shared rx_word_map across arst_n (phase %0d->%0d, freq_q=%0d, debt_q=%0d, selA=0x%02h, selB=0x%02h)",
                 phase_before, phase_after, rx_cdr_frequency_q, rx_cdr_phase_debt_q, rx_select_a, rx_select_b);

        $display("ALL 4 SUBSYSTEM INTEGRATION CHECKS PASSED for serdes_digital_top_v3!");
        $finish;
    end

    initial begin #300000; $fatal(1, "Integration testbench timeout"); end
endmodule
