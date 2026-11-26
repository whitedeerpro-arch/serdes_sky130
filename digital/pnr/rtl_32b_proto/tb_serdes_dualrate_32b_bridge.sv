`timescale 1ns/1ps
// Production verification TB for serdes_dualrate_32b_bridge (v2):
//   - Tests 4G (180 MHz Host -> 250.0 MHz line, 5.76 Gb/s peak > 4 Gb/s)
//   - Tests 5G (180 MHz Host -> 312.5 MHz line, 5.76 Gb/s peak > 5 Gb/s)
//   - Tests 5G (200 MHz Host -> 312.5 MHz line, 6.40 Gb/s peak > 5 Gb/s)
//   - Explicitly injects 0x0000, 0xA55A, and 0xBC50 inside payload (100% transparency!)
//   - Exercises intermittent TX bursts (testing arbitrary 1-cycle RX payload bubbles!)
//     and periodic RX host backpressure bursts.
module tb_serdes_dualrate_32b_bridge;
    reg host_clk = 1'b0;
    reg line_clk = 1'b0;
    reg mode_5g  = 1'b0;
    real host_half_ns = 2.7778; // 180.0 MHz default (5.76 Gb/s > 5.0 Gb/s)

    always #(host_half_ns) host_clk = ~host_clk;
    always begin
        if (mode_5g) #1.600 line_clk = ~line_clk; // 312.5 MHz (5 Gb/s)
        else         #2.000 line_clk = ~line_clk; // 250.0 MHz (4 Gb/s)
    end

    reg         arst_n;
    reg         tx_en;
    reg         host_tx_valid;
    wire        host_tx_ready;
    reg  [31:0] host_tx_data;
    wire        host_tx_online;
    wire        host_tx_underrun;

    wire        host_rx_valid;
    reg         host_rx_ready;
    wire [31:0] host_rx_data;
    wire        host_rx_online;
    wire        host_rx_overflow;

    wire [15:0] tx_word16;
    wire        tx_word_valid;

    serdes_dualrate_32b_bridge u_dut (
        .arst_n           (arst_n),
        .host_clk         (host_clk),
        .host_tx_valid    (host_tx_valid),
        .host_tx_ready    (host_tx_ready),
        .host_tx_data     (host_tx_data),
        .host_tx_online   (host_tx_online),
        .host_tx_underrun (host_tx_underrun),
        .host_rx_valid    (host_rx_valid),
        .host_rx_ready    (host_rx_ready),
        .host_rx_data     (host_rx_data),
        .host_rx_online   (host_rx_online),
        .host_rx_overflow (host_rx_overflow),
        .tx_clk           (line_clk),
        .tx_enable        (tx_en),
        .tx_word16        (tx_word16),
        .tx_word_valid    (tx_word_valid),
        .rx_clk           (line_clk),
        .rx_aligned       (tx_en),
        .rx_payload_valid (tx_word_valid),
        .rx_word16        (tx_word16)
    );

    reg [31:0] exp_q [0:4095];
    integer w_idx, r_idx, err_cnt;
    integer ready_cycles, total_cycles;
    integer seed;

    function [31:0] next_word(input integer n);
        begin
            // Deliberately inject 0x0000, 0xA55A (IDLE!), and 0xBC50 inside payload!
            if (n == 5)       next_word = 32'hA55A_0000;
            else if (n == 6)  next_word = 32'h0000_A55A;
            else if (n == 7)  next_word = 32'hA55A_BC50;
            else              next_word = {16'h8000 ^ (n[15:0] * 16'h0215), 16'h1000 + (n[15:0] * 16'h0103)};
        end
    endfunction

    task run_rate(input reg is_5g, input real h_mhz, input integer n_words);
        integer cyc;
        begin
            mode_5g       = is_5g;
            host_half_ns  = 500.0 / h_mhz;
            arst_n        = 1'b0;
            tx_en         = 1'b0;
            host_tx_valid = 1'b0;
            host_tx_data  = 32'd0;
            host_rx_ready = 1'b1;
            w_idx         = 0;
            r_idx         = 0;
            ready_cycles  = 0;
            total_cycles  = 0;
            repeat (16) @(posedge host_clk);
            arst_n = 1'b1;
            while (!(host_tx_online && host_rx_online)) @(posedge host_clk);
            tx_en = 1'b1;

            for (cyc = 0; cyc < n_words * 3; cyc = cyc + 1) begin
                @(negedge host_clk);
                host_tx_data = next_word(w_idx);
                if (w_idx < n_words) begin
                    if (w_idx < (n_words * 7) / 10)
                        host_tx_valid = 1'b1;
                    else
                        host_tx_valid = (($random(seed) & 3) != 0);
                end else begin
                    host_tx_valid = 1'b0;
                end
                // Periodic RX host backpressure bursts within sustainable drain rate (h_mhz * (1 - stall) > line_rate)
                if ((h_mhz >= 166.5) ? ((cyc % 64) >= 60) : ((cyc % 128) == 127))
                    host_rx_ready = 1'b0;
                else
                    host_rx_ready = 1'b1;

                @(posedge host_clk);
                if (w_idx < (n_words * 7) / 10) begin
                    total_cycles = total_cycles + 1;
                    if (host_tx_ready) ready_cycles = ready_cycles + 1;
                    if (host_tx_underrun) begin
                        $display("ERR unexpected TX underrun during full-rate phase mode_5g=%0d h=%.1f cyc=%0d", is_5g, h_mhz, cyc);
                        err_cnt = err_cnt + 1;
                    end
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

            host_tx_valid = 1'b0;
            host_rx_ready = 1'b1;
            repeat (100) begin
                @(posedge host_clk);
                if (host_rx_valid && host_rx_ready) begin
                    if (^host_rx_data === 1'bx || host_rx_data !== exp_q[r_idx]) begin
                        $display("ERR(drain) mode_5g=%0d idx=%0d got=%h exp=%h", is_5g, r_idx, host_rx_data, exp_q[r_idx]);
                        err_cnt = err_cnt + 1;
                    end
                    r_idx = r_idx + 1;
                end
            end

            if (r_idx != n_words || host_rx_overflow) begin
                $display("ERR(count/ovf) mode_5g=%0d sent=%0d recv=%0d rx_ovf=%0d", is_5g, w_idx, r_idx, host_rx_overflow);
                err_cnt = err_cnt + 1;
            end
            $display("PASS mode=%s(host=%.1fMHz->%.2fGb/s peak) | words=%0d/%0d (%0d B) | ready_duty=%.4f | rx_ovf=%0d | err=%0d",
                     is_5g ? "5G" : "4G", h_mhz, h_mhz * 0.032,
                     r_idx, n_words, r_idx * 4,
                     (1.0 * ready_cycles) / total_cycles,
                     host_rx_overflow, err_cnt);
        end
    endtask

    initial begin
        err_cnt = 0;
        seed    = 32'h51A7_9C23;
        run_rate(1'b0, 158.73, 1600);
        run_rate(1'b1, 158.73, 1600);
        run_rate(1'b0, 166.67, 1600);
        run_rate(1'b1, 166.67, 1600);
        run_rate(1'b1, 180.0,  1600);
        run_rate(1'b1, 200.0,  1600);
        if (err_cnt == 0) begin
            $display("ALL_TESTS_PASSED");
        end else begin
            $display("TESTS_FAILED err_cnt=%0d", err_cnt);
            $fatal(1);
        end
        $finish;
    end
endmodule
