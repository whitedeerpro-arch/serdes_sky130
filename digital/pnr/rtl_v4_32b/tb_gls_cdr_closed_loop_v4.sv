`timescale 1ps/1fs
// End-to-end Zero-Delay Gate-Level Simulation (GLS) closed-loop +/-300 ppm CDR testbench
// instantiating the ACTUAL routed serdes_digital_top_v4 macro (u_rx_map -> u_rx_pack -> u_rx_cdr)!
// Drives rx_phys[31:0] on negedge rx_word_clk every 16 UI, clocks rx_word_clk, checks one-hot
// rx_select_a/rx_select_b, tracks rx_phase_code feedback into the PI model over > 60 us (> 32 us spec!),
// and asserts maxerr_ps < 25.0 ps, word_errors == 0, slips == 0, locked == 1, range_limited == 0.
module tb_gls_cdr_closed_loop_v4;
    parameter real OFFSET_PPM   = 300.0;
    parameter real TX_PHASE_PS  = 73.0;
    parameter real MAX_ERROR_PS = 25.0;
    parameter integer SIM_BITS  = 240000; // 60 us at 4 Gb/s (measures 30..60 us >> 32 us!)

    reg rst_n = 0, arst_n = 0;
    reg ref_clk = 0, tx_word_clk = 0, rx_word_clk = 1, host_clk = 0;
    reg [31:0] rx_phys = 32'd0;
    reg rx_cdr_enable = 1'b1;

    wire precharge_en, pfd_rst_b, cp_en, pll_pw_clr_b;
    wire [4:0] vco_code;
    wire [7:0] switches;
    wire pll_locked, pll_busy, pll_fault, pll_coarse_busy, pll_coarse_done, pll_fast_end, pll_slow_end;
    wire [2:0] pll_state_id, pll_fault_code;
    wire [3:0] pll_lo_code, pll_hi_code;
    wire [15:0] tx_capture_data;
    wire tx_capture_valid, tx_a_valid, tx_b_valid, tx_word_ready, tx_underrun;
    wire [5:0] rx_phase_code;
    wire [7:0] rx_select_a, rx_select_b, rx_fine_b;
    wire [31:0] host_data;
    wire host_valid, host_online, host_error, rx_word_online, rx_aligned;
    wire [3:0] rx_offset;
    wire rx_cdr_locked, rx_cdr_holdover, rx_cdr_range_limited, rx_cdr_phase_applied;
    wire signed [16:0] rx_cdr_frequency_q;
    wire signed [22:0] rx_cdr_phase_debt_q;

    serdes_digital_top_v4 dut (
        .rst_n(rst_n), .arst_n(arst_n),
        .ref_clk(ref_clk), .bias_ready_async(1'b0), .pre_ref_ready_async(1'b0),
        .hi_async(1'b0), .lo_async(1'b0), .pw_late_async(1'b0),
        .precharge_en(precharge_en), .pfd_rst_b(pfd_rst_b), .cp_en(cp_en), .pll_pw_clr_b(pll_pw_clr_b),
        .vco_code(vco_code), .switches(switches),
        .pll_enable(1'b0), .pll_start(1'b0), .pll_abort_async(1'b0),
        .pll_tclass(2'd0), .pll_lo_run(4'd0), .pll_hi_run(4'd0),
        .pll_stop_code(12'd0), .pll_stop_sel(3'd0),
        .pll_locked(pll_locked), .pll_busy(pll_busy), .pll_fault(pll_fault),
        .pll_state_id(pll_state_id), .pll_fault_code(pll_fault_code),
        .pll_lo_code(pll_lo_code), .pll_hi_code(pll_hi_code),
        .pll_coarse_busy(pll_coarse_busy), .pll_coarse_done(pll_coarse_done),
        .pll_fast_end(pll_fast_end), .pll_slow_end(pll_slow_end),
        .tx_word_clk(tx_word_clk), .tx_clock_good(1'b0),
        .tx_capture_data(tx_capture_data), .tx_capture_valid(tx_capture_valid),
        .tx_a_valid(tx_a_valid), .tx_b_valid(tx_b_valid),
        .tx_enable(1'b0), .tx_in_valid(1'b0), .tx_in_data(32'd0),
        .tx_word_ready(tx_word_ready), .tx_underrun(tx_underrun),
        .rx_word_clk(rx_word_clk), .rx_phys(rx_phys),
        .rx_phase_code(rx_phase_code), .rx_select_a(rx_select_a),
        .rx_select_b(rx_select_b), .rx_fine_b(rx_fine_b),
        .host_clk(host_clk), .host_ready(1'b1),
        .host_data(host_data), .host_valid(host_valid),
        .host_online(host_online), .host_error(host_error),
        .rx_training_enable(1'b0), .rx_word_online(rx_word_online),
        .rx_aligned(rx_aligned), .rx_offset(rx_offset),
        .rx_cdr_enable(rx_cdr_enable), .rx_cdr_locked(rx_cdr_locked),
        .rx_cdr_holdover(rx_cdr_holdover), .rx_cdr_range_limited(rx_cdr_range_limited),
        .rx_cdr_phase_applied(rx_cdr_phase_applied),
        .rx_cdr_frequency_q(rx_cdr_frequency_q), .rx_cdr_phase_debt_q(rx_cdr_phase_debt_q)
    );

    reg pair_clk = 0, pvalid = 0, training = 1;
    reg [1:0] pair_bits = 0;
    wire [15:0] word_data;
    wire word_valid, aligned;
    rx_deserializer16 deser (pair_clk, rst_n, pvalid, training, pair_bits, word_data, word_valid, aligned);

    reg [31:0] phase_lut [0:63];
    reg prbs [0:126];
    reg [6:0] lfsr;
    reg [15:0] dbuf16 = 0, ebuf16 = 0;
    integer phase_steps = 0, old_code = 0, wraps = 0;
    integer n, j, k, idx, last_payload_index = -1, word_end;
    integer data_slips = 0, last_data_index = -1, bit_errors = 0, words = 0, word_errors = 0;
    integer onehot_errs = 0;
    real tx_ui, te, td, center, err, max_error = 0, sum_error2 = 0, lock_time = -1;
    integer error_samples = 0;
    reg [15:0] expected_word;

    function automatic real boundary(input integer i);
        boundary = TX_PHASE_PS + i * tx_ui;
    endfunction
    function automatic integer source_index(input real t);
        integer a;
        begin
            a = $rtoi($floor((t - TX_PHASE_PS) / tx_ui));
            if (t < boundary(a)) a = a - 1;
            else if (t >= boundary(a + 1)) a = a + 1;
            source_index = a;
        end
    endfunction
    function automatic reg bit_at_index(input integer a);
        integer b;
        begin
            if (a < 64000) begin b = ((a % 16) + 16) % 16; bit_at_index = (16'hb5e3 >> b) & 1; end
            else begin b = (a - 64000) % 127; bit_at_index = prbs[b]; end
        end
    endfunction
    function automatic reg source_bit(input real t);
        source_bit = bit_at_index(source_index(t));
    endfunction
    function automatic real phase_time;
        integer turns, c;
        begin
            turns = $rtoi($floor(phase_steps / 64.0));
            c = ((phase_steps % 64) + 64) % 64;
            phase_time = turns * 500.0 + phase_lut[c] / 1000.0;
        end
    endfunction
    function automatic integer popcnt8(input [7:0] x);
        popcnt8 = x[0] + x[1] + x[2] + x[3] + x[4] + x[5] + x[6] + x[7];
    endfunction

    initial begin
        $readmemh("digital/rx/tb/data/pi_phase_fs.hex", phase_lut);
        tx_ui = 250.0 / (1.0 + OFFSET_PPM * 1e-6);
        lfsr = 7'h5d;
        for (j = 0; j < 127; j = j + 1) begin prbs[j] = lfsr[0]; lfsr = {lfsr[0] ^ lfsr[1], lfsr[6:1]}; end

        // Clean async reset & 8 rx_word_clk release cycles so all synchronizers exit reset cleanly
        rst_n = 0; arst_n = 0; rx_word_clk = 1;
        #100;
        for (j = 0; j < 4; j = j + 1) begin #20 rx_word_clk = 0; #20 rx_word_clk = 1; end
        rst_n = 1; arst_n = 1;
        for (j = 0; j < 12; j = j + 1) begin #20 rx_word_clk = 0; #20 rx_word_clk = 1; end

        for (n = 0; n < SIM_BITS; n = n + 1) begin
            te = 4000 + n * 250.0 + phase_time();
            if (te < $realtime) $fatal(1, "nonmonotonic edge clock");
            #(te - $realtime);
            ebuf16[n % 16] = source_bit($realtime);
            td = 4000 + n * 250.0 + 125.0 + phase_time();
            if (td < $realtime) $fatal(1, "nonmonotonic data clock");
            #(td - $realtime);
            idx = source_index($realtime);
            dbuf16[n % 16] = source_bit($realtime);
            pair_bits[n % 2] = source_bit($realtime);
            center = (boundary(idx) + boundary(idx + 1)) / 2.0;
            err = $realtime - center;
            if ($realtime > 28000000) begin
                if (last_data_index >= 0 && idx != last_data_index + 1) data_slips = data_slips + 1;
                if (err > max_error) max_error = err;
                if (-err > max_error) max_error = -err;
                sum_error2 = sum_error2 + err * err;
                error_samples = error_samples + 1;
            end
            last_data_index = idx;
            if (n % 2 == 1) begin
                pvalid = 1;
                training = ($realtime < boundary(64000));
                pair_clk = 1; #1; pair_clk = 0;
                if (word_valid && idx > 65024) begin
                    word_end = idx;
                    if (word_end % 16 != 15) word_end = idx - 1;
                    if (word_end % 16 != 15) $fatal(1, "word boundary");
                    expected_word = 0;
                    for (j = 0; j < 16; j = j + 1) expected_word[j] = bit_at_index(word_end - 15 + j);
                    if (word_data !== expected_word) word_errors = word_errors + 1;
                    if (last_payload_index >= 0 && word_end != last_payload_index + 16) bit_errors = bit_errors + 1;
                    last_payload_index = word_end;
                    words = words + 1;
                end
            end
            if (n % 16 == 15) begin
                rx_phys = {ebuf16, dbuf16};
                #5; rx_word_clk = 0; // negedge: u_rx_map captures rx_phys
                #10; rx_word_clk = 1; // posedge: u_rx_pack packs & clocks rx_clk_div2 every 2nd word
                #5;
                if ((^{rx_phase_code, rx_cdr_locked, rx_select_a, rx_select_b, rx_fine_b}) === 1'bx)
                    $fatal(1, "GLS X detected on CDR/PI outputs at n=%0d!", n);
                if (popcnt8(rx_select_a) != 1 || popcnt8(rx_select_b) != 1)
                    onehot_errs = onehot_errs + 1;
                k = $signed({1'b0, rx_phase_code}) - old_code;
                if (k == 1 || k == -63) phase_steps = phase_steps + 1;
                else if (k == -1 || k == 63) phase_steps = phase_steps - 1;
                else if (k != 0) $fatal(1, "GLS PI jumped by %0d", k);
                if (k == 63 || k == -63) wraps = wraps + 1;
                old_code = rx_phase_code;
                if (rx_cdr_locked && lock_time < 0) lock_time = $realtime;
            end
        end
        $display("RESULT gls_top_cdr ppm=%0.1f lock_ns=%0.3f freq_ppm=%0.3f wraps=%0d words=%0d word_errors=%0d slips=%0d onehot_errs=%0d maxerr_ps=%0.3f rms_ps=%0.3f locked=%0d limited=%0d aligned=%0d",
                 OFFSET_PPM, lock_time / 1000.0, $itor(rx_cdr_frequency_q) / 65536.0 * 976.5625,
                 wraps, words, word_errors, data_slips, onehot_errs, max_error, $sqrt(sum_error2 / error_samples),
                 rx_cdr_locked, rx_cdr_range_limited, aligned);
        if (!rx_cdr_locked || rx_cdr_range_limited || !aligned || words < 1000 ||
            word_errors != 0 || bit_errors != 0 || data_slips != 0 || onehot_errs != 0 || max_error > MAX_ERROR_PS)
            $fatal(1, "GLS top closed-loop CDR criteria FAILED");
        $display("PASS ZERO-DELAY GLS serdes_digital_top_v4 closed-loop CDR (%0.1f ppm, >60us, onehot_errs=0)!", OFFSET_PPM);
        $finish;
    end
    initial begin #150000000; $fatal(1, "GLS CDR timeout"); end
endmodule
