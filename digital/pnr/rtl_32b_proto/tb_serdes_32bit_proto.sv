`timescale 1ns/1ps
// Dual-Rate (4 Gb/s 250->250 MHz & 5 Gb/s 250->312.5 MHz) 32-bit Native 8x32 Async FIFO Loopback Testbench
module tb_serdes_32bit_proto;
    reg host_clk = 1'b0;
    reg line_clk = 1'b0;
    reg mode_5g  = 1'b0;

    // Host: 250 MHz (4.0 ns period)
    always #2.000 host_clk = ~host_clk;
    // Line word clock: 250 MHz (4.0 ns @ 4G) or 312.5 MHz (3.2 ns @ 5G)
    always begin
        if (mode_5g) #1.600 line_clk = ~line_clk;
        else         #2.000 line_clk = ~line_clk;
    end

    reg         rst_n;
    reg         tx_en;
    reg         host_tx_valid;
    wire        host_tx_ready;
    reg  [31:0] host_tx_data;
    wire [3:0]  tx_level;
    wire [15:0] tx_word16;
    wire        tx_is_idle;
    wire [15:0] tx_underrun_cnt;

    wire        host_rx_valid;
    reg         host_rx_ready;
    wire [31:0] host_rx_data;
    wire [3:0]  rx_level;
    wire [15:0] rx_idle_cnt;
    wire [15:0] rx_overflow_cnt;

    tx_32to16_bridge u_tx (
        .host_clk        (host_clk),
        .host_rst_n      (rst_n),
        .host_valid      (host_tx_valid),
        .host_ready      (host_tx_ready),
        .host_data       (host_tx_data),
        .host_fifo_level (tx_level),
        .tx_clk          (line_clk),
        .tx_rst_n        (rst_n),
        .tx_enable       (tx_en),
        .tx_word16       (tx_word16),
        .tx_is_idle      (tx_is_idle),
        .tx_underrun_cnt (tx_underrun_cnt)
    );

    rx_16to32_bridge u_rx (
        .rx_clk          (line_clk),
        .rx_rst_n        (rst_n),
        .rx_aligned      (tx_en),
        .rx_word_valid   (1'b1),
        .rx_word16       (tx_word16),
        .rx_idle_cnt     (rx_idle_cnt),
        .rx_overflow_cnt (rx_overflow_cnt),
        .host_clk        (host_clk),
        .host_rst_n      (rst_n),
        .host_valid      (host_rx_valid),
        .host_ready      (host_rx_ready),
        .host_data       (host_rx_data),
        .host_fifo_level (rx_level)
    );

    reg [31:0] exp_q [0:4095];
    integer w_idx, r_idx, err_cnt;
    integer ready_cycles, total_cycles;
    integer seed;

    function [31:0] next_word(input integer n);
        reg [15:0] lo, hi;
        begin
            lo = 16'h1000 + (n[15:0] * 16'h0103);
            hi = 16'h8000 ^ (n[15:0] * 16'h0215);
            // Avoid accidental collision with IDLE_WORD (16'hBC50)
            if (lo == 16'hBC50) lo = 16'hBC51;
            if (hi == 16'hBC50) hi = 16'hBC52;
            next_word = {hi, lo};
        end
    endfunction

    task run_rate(input reg is_5g, input integer n_words);
        integer cyc;
        reg [31:0] w;
        begin
            mode_5g       = is_5g;
            rst_n         = 1'b0;
            tx_en         = 1'b0;
            host_tx_valid = 1'b0;
            host_tx_data  = 32'd0;
            host_rx_ready = 1'b1;
            w_idx         = 0;
            r_idx         = 0;
            ready_cycles  = 0;
            total_cycles  = 0;
            repeat (10) @(posedge host_clk);
            rst_n = 1'b1;
            repeat (4) @(posedge host_clk);
            tx_en = 1'b1;

            // Phase 1: Full-rate continuous stream (measure steady-state host_ready duty!)
            for (cyc = 0; cyc < n_words * 3; cyc = cyc + 1) begin
                @(negedge host_clk);
                host_tx_data = next_word(w_idx);
                if (w_idx < n_words) begin
                    // First 70% full-speed continuous; last 30% intermittent host stalls (realistic bursts)
                    if (w_idx < (n_words * 7) / 10)
                        host_tx_valid = 1'b1;
                    else
                        host_tx_valid = (($random(seed) & 3) != 0);
                end else begin
                    host_tx_valid = 1'b0;
                end
                // Light realistic RX host stalls (never exceed 8-word burst)
                host_rx_ready = (($random(seed) & 7) != 0);

                @(posedge host_clk);
                if (w_idx < (n_words * 7) / 10) begin
                    total_cycles = total_cycles + 1;
                    if (host_tx_ready) ready_cycles = ready_cycles + 1;
                end
                if (host_tx_valid && host_tx_ready) begin
                    exp_q[w_idx] = host_tx_data;
                    w_idx = w_idx + 1;
                end
                if (host_rx_valid && host_rx_ready) begin
                    if (^host_rx_data === 1'bx || host_rx_data !== exp_q[r_idx]) begin
                        $display("ERR mode_5g=%0d idx=%0d got=%h exp=%h", is_5g, r_idx, host_rx_data, exp_q[r_idx]);
                        err_cnt = err_cnt + 1;
                    end
                    r_idx = r_idx + 1;
                end
                if (w_idx == n_words && r_idx == n_words) begin
                    cyc = n_words * 3;
                end
            end

            // Drain any remaining words
            host_tx_valid = 1'b0;
            host_rx_ready = 1'b1;
            repeat (64) begin
                @(posedge host_clk);
                if (host_rx_valid && host_rx_ready) begin
                    if (^host_rx_data === 1'bx || host_rx_data !== exp_q[r_idx]) begin
                        $display("ERR(drain) mode_5g=%0d idx=%0d got=%h exp=%h", is_5g, r_idx, host_rx_data, exp_q[r_idx]);
                        err_cnt = err_cnt + 1;
                    end
                    r_idx = r_idx + 1;
                end
            end

            if (r_idx != n_words || rx_overflow_cnt != 0) begin
                $display("ERR(count/ovf) mode_5g=%0d sent=%0d recv=%0d ovf=%0d", is_5g, w_idx, r_idx, rx_overflow_cnt);
                err_cnt = err_cnt + 1;
            end
            $display("PASS mode=%s | words=%0d/%0d (bytes=%0d) | full_rate_ready_duty=%.4f | idle_words=%0d | underrun=%0d | ovf=%0d | err=%0d",
                     is_5g ? "5G(250->312.5MHz)" : "4G(250->250.0MHz)",
                     r_idx, n_words, r_idx * 4,
                     (1.0 * ready_cycles) / total_cycles,
                     rx_idle_cnt, tx_underrun_cnt, rx_overflow_cnt, err_cnt);
        end
    endtask

    initial begin
        err_cnt = 0;
        seed    = 32'h20261124;
        run_rate(1'b0, 1600);
        run_rate(1'b1, 1600);
        if (err_cnt == 0)
            $display("ALL_32BIT_PROTO_PASS");
        else
            $fatal(1, "FAIL err_cnt=%0d", err_cnt);
        $finish;
    end
endmodule
