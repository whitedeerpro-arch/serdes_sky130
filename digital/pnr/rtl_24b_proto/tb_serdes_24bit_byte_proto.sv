`timescale 1ns/1ps

// Dual-Rate (4 Gb/s 250->250 MHz + 5 Gb/s 250->312.5 MHz) Stress Testbench for Byte-Managed 24-bit TX/RX Prototype
module tb_serdes_24bit_byte_proto;
    reg host_clk = 1'b0;
    reg tx_clk   = 1'b0;
    reg mode_5g  = 1'b0;
    reg host_rst_n = 1'b0;
    reg tx_rst_n   = 1'b0;
    reg enable     = 1'b0;

    always #2.0 host_clk = ~host_clk;
    always begin
        if (mode_5g) #1.6 tx_clk = ~tx_clk;
        else         #2.0 tx_clk = ~tx_clk;
    end

    reg         h_tx_valid;
    wire        h_tx_ready;
    reg  [23:0] h_tx_data;
    reg  [1:0]  h_tx_keep;
    wire        tx_fifo_ovf;

    wire        gb_in_valid;
    wire        gb_in_ready;
    wire [25:0] gb_in_pack;

    rx_async_word_fifo_24b #(.DATA_W(26), .ADDR_W(4)) u_tx_fifo (
        .wr_clk(host_clk), .wr_rst_n(host_rst_n),
        .wr_valid(h_tx_valid), .wr_ready(h_tx_ready),
        .wr_data({h_tx_keep, h_tx_data}), .overflow_pulse(tx_fifo_ovf),
        .rd_clk(tx_clk), .rd_rst_n(tx_rst_n),
        .rd_valid(gb_in_valid), .rd_ready(gb_in_ready), .rd_data(gb_in_pack)
    );

    wire [15:0] wire_word;
    wire        wire_is_idle;
    wire [15:0] underrun_cnt;
    wire [3:0]  fill_dbg;

    tx_byte_gearbox_24to16 #(.IDLE_WORD(16'hBC50), .PREFILL_BYTES(4), .DEPTH_BYTES(8)) u_tx_gb (
        .clk(tx_clk), .rst_n(tx_rst_n), .enable(enable),
        .in_valid(gb_in_valid), .in_ready(gb_in_ready),
        .in_data(gb_in_pack[23:0]), .in_keep_bytes(gb_in_pack[25:24]),
        .tx_word(wire_word), .tx_word_is_idle(wire_is_idle),
        .underrun_cnt(underrun_cnt), .fill_bytes_dbg(fill_dbg)
    );

    wire        rx_pk_valid;
    wire [23:0] rx_pk_data;
    rx_byte_packer_16to24 #(.IDLE_WORD(16'hBC50)) u_rx_pk (
        .clk(tx_clk), .rst_n(tx_rst_n), .enable(enable),
        .in_valid(enable), .in_word(wire_word), .drop_idle(1'b1),
        .out_valid(rx_pk_valid), .out_data(rx_pk_data)
    );

    wire        rx_fifo_wr_ready, rx_fifo_ovf;
    wire        h_rx_valid;
    reg         h_rx_ready;
    wire [25:0] h_rx_pack;

    rx_async_word_fifo_24b #(.DATA_W(26), .ADDR_W(4)) u_rx_fifo (
        .wr_clk(tx_clk), .wr_rst_n(tx_rst_n),
        .wr_valid(rx_pk_valid), .wr_ready(rx_fifo_wr_ready),
        .wr_data({2'd3, rx_pk_data}), .overflow_pulse(rx_fifo_ovf),
        .rd_clk(host_clk), .rd_rst_n(host_rst_n),
        .rd_valid(h_rx_valid), .rd_ready(h_rx_ready), .rd_data(h_rx_pack)
    );

    reg [7:0] exp_q [0:32767];
    integer exp_wr, exp_rd;
    integer err_cnt, idle_seen, words_rx;
    integer ready_hi_cyc, total_burst_cyc;
    reg [7:0] byte_gen;

    function [7:0] next_safe_byte;
        input [7:0] cur;
        reg [7:0] nxt;
        begin
            nxt = cur + 8'd1;
            if (nxt == 8'hBC || nxt == 8'h50) nxt = nxt + 8'd1;
            next_safe_byte = nxt;
        end
    endfunction

    task run_mode;
        input is_5g;
        input integer n_burst_words;
        input integer n_rand_words;
        integer sent_w;
        integer wait_cyc;
        reg [7:0] b0, b1, b2;
        reg [1:0] kp;
        integer nb;
        begin
            mode_5g    = is_5g;
            host_rst_n = 1'b0;
            tx_rst_n   = 1'b0;
            enable     = 1'b0;
            h_tx_valid = 1'b0;
            h_tx_data  = 24'd0;
            h_tx_keep  = 2'd3;
            h_rx_ready = 1'b1;
            exp_wr     = 0;
            exp_rd     = 0;
            idle_seen  = 0;
            words_rx   = 0;
            ready_hi_cyc    = 0;
            total_burst_cyc = 0;
            byte_gen   = is_5g ? 8'h21 : 8'h01;

            repeat (8) @(posedge host_clk);
            host_rst_n = 1'b1;
            repeat (4) @(posedge tx_clk);
            tx_rst_n   = 1'b1;
            enable     = 1'b1;
            repeat (4) @(posedge host_clk);

            // Phase 1: Full-rate sustained burst (measure steady-state ready duty cycle!)
            sent_w = 0;
            while (sent_w < n_burst_words) begin
                b0 = next_safe_byte(byte_gen);
                b1 = next_safe_byte(b0);
                b2 = next_safe_byte(b1);
                @(negedge host_clk);
                h_tx_valid = 1'b1;
                h_tx_keep  = 2'd3;
                h_tx_data  = {b2, b1, b0};
                @(posedge host_clk);
                if (sent_w >= 24) begin
                    total_burst_cyc = total_burst_cyc + 1;
                    if (h_tx_ready) ready_hi_cyc = ready_hi_cyc + 1;
                end
                if (h_tx_ready) begin
                    exp_q[exp_wr]     = b0;
                    exp_q[exp_wr + 1] = b1;
                    exp_q[exp_wr + 2] = b2;
                    exp_wr = exp_wr + 3;
                    byte_gen = b2;
                    sent_w = sent_w + 1;
                end
            end

            // Phase 2: Host pause (IDLE insertion + underflow recovery) + partial-byte keep=1/2/3 transfers!
            @(negedge host_clk);
            h_tx_valid = 1'b0;
            repeat (20) @(posedge host_clk);

            sent_w = 0;
            while (sent_w < n_rand_words) begin
                if ((sent_w % 17) == 5) begin
                    @(negedge host_clk);
                    h_tx_valid = 1'b0;
                    repeat (3) @(posedge host_clk);
                end
                case (sent_w % 6)
                    0: kp = 2'd1;
                    1: kp = 2'd2;
                    default: kp = 2'd3;
                endcase
                nb = (kp == 2'd1) ? 1 : ((kp == 2'd2) ? 2 : 3);
                b0 = next_safe_byte(byte_gen);
                b1 = (nb >= 2) ? next_safe_byte(b0) : 8'hAA;
                b2 = (nb >= 3) ? next_safe_byte(b1) : 8'h55;
                @(negedge host_clk);
                h_tx_valid = 1'b1;
                h_tx_keep  = kp;
                h_tx_data  = {b2, b1, b0};
                @(posedge host_clk);
                if (h_tx_ready) begin
                    exp_q[exp_wr] = b0;
                    exp_wr = exp_wr + 1;
                    if (nb >= 2) begin exp_q[exp_wr] = b1; exp_wr = exp_wr + 1; end
                    if (nb >= 3) begin exp_q[exp_wr] = b2; exp_wr = exp_wr + 1; end
                    byte_gen = (nb == 1) ? b0 : ((nb == 2) ? b1 : b2);
                    sent_w = sent_w + 1;
                end
            end

            // Pad tail so total bytes is multiple of 6 (LCM(2,3)) -> drains both TX gearbox & RX packer cleanly
            while ((exp_wr % 6) != 0) begin
                b0 = next_safe_byte(byte_gen);
                @(negedge host_clk);
                h_tx_valid = 1'b1;
                h_tx_keep  = 2'd1;
                h_tx_data  = {16'h0000, b0};
                @(posedge host_clk);
                if (h_tx_ready) begin
                    exp_q[exp_wr] = b0;
                    exp_wr = exp_wr + 1;
                    byte_gen = b0;
                end
            end
            @(negedge host_clk);
            h_tx_valid = 1'b0;

            wait_cyc = 0;
            while ((exp_rd < exp_wr) && (wait_cyc < 400)) begin
                @(posedge host_clk);
                wait_cyc = wait_cyc + 1;
            end

            $display("[MODE %s] bytes_sent=%0d bytes_checked=%0d rx_words=%0d idle_words=%0d underrun=%0d ready_duty=%.4f err=%0d",
                     is_5g ? "5Gb/s (250->312.5MHz)" : "4Gb/s (250->250.0MHz)",
                     exp_wr, exp_rd, words_rx, idle_seen, underrun_cnt,
                     (total_burst_cyc > 0) ? (1.0 * ready_hi_cyc / total_burst_cyc) : 0.0,
                     err_cnt);
            if (exp_rd != exp_wr) begin
                $display("FAIL: Missing drained bytes (%0d != %0d)", exp_rd, exp_wr);
                err_cnt = err_cnt + 1;
            end
            if (idle_seen == 0) begin
                $display("FAIL: Expected IDLE words during pause");
                err_cnt = err_cnt + 1;
            end
        end
    endtask

    always @(posedge host_clk) begin
        if (host_rst_n && h_rx_valid && h_rx_ready) begin
            words_rx = words_rx + 1;
            if (^h_rx_pack[23:0] === 1'bx) begin
                $display("FAIL: X detected on 24-bit RX output: %h at t=%0t", h_rx_pack[23:0], $time);
                err_cnt = err_cnt + 1;
            end else begin
                if (h_rx_pack[7:0]   !== exp_q[exp_rd])     begin $display("MISMATCH b0 @%0d got %h exp %h", exp_rd,   h_rx_pack[7:0],   exp_q[exp_rd]);   err_cnt = err_cnt + 1; end
                if (h_rx_pack[15:8]  !== exp_q[exp_rd + 1]) begin $display("MISMATCH b1 @%0d got %h exp %h", exp_rd+1, h_rx_pack[15:8],  exp_q[exp_rd+1]); err_cnt = err_cnt + 1; end
                if (h_rx_pack[23:16] !== exp_q[exp_rd + 2]) begin $display("MISMATCH b2 @%0d got %h exp %h", exp_rd+2, h_rx_pack[23:16], exp_q[exp_rd+2]); err_cnt = err_cnt + 1; end
                exp_rd = exp_rd + 3;
            end
        end
        if (host_rst_n && rx_fifo_ovf) begin
            $display("FAIL: RX FIFO overflow rx=%b", rx_fifo_ovf);
            err_cnt = err_cnt + 1;
        end
    end

    always @(posedge tx_clk) begin
        if (tx_rst_n && enable && wire_is_idle) idle_seen = idle_seen + 1;
    end

    initial begin
        err_cnt = 0;
        run_mode(1'b0, 1200, 1200);
        run_mode(1'b1, 1200, 1200);
        if (err_cnt == 0) begin
            $display("PASS: Dual-rate 4G/5G 24-bit byte-managed TX/RX prototype 100%% bit-exact (0 errors, 0 X-states)!");
        end else begin
            $display("FAIL: %0d errors detected!", err_cnt);
            $finish_and_return(1);
        end
        $finish;
    end
endmodule
