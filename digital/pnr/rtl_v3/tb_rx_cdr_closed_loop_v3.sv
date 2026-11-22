`timescale 1ps/1fs
// Closed-loop behavioral sampling/clock plant around ACTUAL v3 rx_cdr_loop (/2 125 MHz)
// and rx_deserializer16 using the measured PI static phase LUT (pi_phase_fs.hex).
// Parameterizable OFFSET_PPM (verified at BOTH +300 ppm and -300 ppm).
module tb_rx_cdr_closed_loop_v3;
    parameter real OFFSET_PPM = 300.0, TX_PHASE_PS = 73.0, JITTER_PS = 0.0;
    parameter integer SIM_BITS = 400000, LATENCY_WORDS = 2;
    parameter integer HOLDOVER_BITS = 0;
    parameter real EDGE_SKEW_PS = 0.0, EDGE_DUTY_PS = 0.0, MAX_ERROR_PS = 25.0;

    reg ctrl = 0, rst_n = 1, enable = 1, bvalid = 0, previous = 0;
    reg [15:0] dd = 0, ee = 0;
    wire [5:0] code;
    wire [7:0] sa, sb, ff;
    wire locked, holdover, limited, applied;
    wire signed [16:0] frequency;
    wire signed [22:0] phase_debt;

    rx_cdr_loop dut (
        .ctrl_clk     (ctrl),
        .rst_n        (rst_n),
        .enable       (enable),
        .bundle_valid (bvalid),
        .previous_data(previous),
        .data_samples (dd),
        .edge_samples (ee),
        .phase_code   (code),
        .select_a     (sa),
        .select_b     (sb),
        .fine_b       (ff),
        .locked       (locked),
        .holdover     (holdover),
        .range_limited(limited),
        .phase_applied(applied),
        .frequency_q  (frequency),
        .phase_debt_q (phase_debt)
    );

    reg pair_clk = 0, pvalid = 0, training = 1;
    reg [1:0] pair_bits = 0;
    wire [15:0] word_data;
    wire word_valid, aligned;
    rx_deserializer16 deser (pair_clk, rst_n, pvalid, training, pair_bits, word_data, word_valid, aligned);

    reg [31:0] phase_lut [0:63];
    reg prbs [0:126];
    reg [6:0] lfsr;
    reg [15:0] dbuf = 0, ebuf = 0, dpipe [0:15], epipe [0:15];
    reg prev_pipe [0:15], last_data = 0;
    integer phase_steps = 0, old_code = 0, frames = 0, wraps = 0;
    integer n, j, k, idx, last_payload_index = -1, word_end;
    integer data_slips = 0, last_data_index = -1, bit_errors = 0, words = 0, word_errors = 0;
    real tx_ui, te, td, center, err, max_error = 0, sum_error2 = 0, lock_time = -1;
    integer error_samples = 0;
    reg [15:0] expected_word;

    function automatic real jitter(input integer i);
        integer h;
        begin h = (i * 1103515245 + 12345) & 65535; jitter = JITTER_PS * (2.0 * h / 65535.0 - 1.0); end
    endfunction
    function automatic real boundary(input integer i);
        boundary = TX_PHASE_PS + i * tx_ui + jitter(i);
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
            if (a < 80000) begin b = ((a % 16) + 16) % 16; bit_at_index = (16'hb5e3 >> b) & 1; end
            else if (a >= 200000 && a < 200000 + HOLDOVER_BITS) bit_at_index = 0;
            else begin b = (a - 80000) % 127; bit_at_index = prbs[b]; end
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

    initial begin
        $readmemh("digital/rx/tb/data/pi_phase_fs.hex", phase_lut);
        tx_ui = 250.0 / (1.0 + OFFSET_PPM * 1e-6);
        lfsr = 7'h5d;
        for (j = 0; j < 127; j = j + 1) begin prbs[j] = lfsr[0]; lfsr = {lfsr[0] ^ lfsr[1], lfsr[6:1]}; end
        for (j = 0; j < 16; j = j + 1) begin dpipe[j] = 0; epipe[j] = 0; prev_pipe[j] = 0; end
        #1; rst_n = 0; #10; rst_n = 1;
        for (n = 0; n < SIM_BITS; n = n + 1) begin
            te = 2000 + n * 250.0 - phase_time();
            if (te < $realtime) $fatal(1, "nonmonotonic edge clock");
            #(te - $realtime);
            ebuf[n % 16] = source_bit($realtime + EDGE_SKEW_PS + ((n % 2) ? EDGE_DUTY_PS : -EDGE_DUTY_PS));
            td = 2000 + n * 250.0 + 125.0 - phase_time();
            if (td < $realtime) $fatal(1, "nonmonotonic data clock");
            #(td - $realtime);
            idx = source_index($realtime);
            dbuf[n % 16] = source_bit($realtime);
            pair_bits[n % 2] = source_bit($realtime);
            center = (boundary(idx) + boundary(idx + 1)) / 2.0;
            err = $realtime - center;
            if ($realtime > 30000000) begin
                if (last_data_index >= 0 && idx != last_data_index + 1) data_slips = data_slips + 1;
                if (err > max_error) max_error = err;
                if (-err > max_error) max_error = -err;
                sum_error2 = sum_error2 + err * err;
                error_samples = error_samples + 1;
            end
            last_data_index = idx;
            if (n % 2 == 1) begin
                pvalid = 1;
                training = ($realtime < boundary(80000));
                pair_clk = 1; #1; pair_clk = 0;
                if (word_valid && idx > 81024) begin
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
                dd = dpipe[LATENCY_WORDS - 1];
                ee = epipe[LATENCY_WORDS - 1];
                previous = prev_pipe[LATENCY_WORDS - 1];
                bvalid = frames > LATENCY_WORDS;
                for (j = LATENCY_WORDS - 1; j > 0; j = j - 1) begin
                    dpipe[j] = dpipe[j - 1]; epipe[j] = epipe[j - 1]; prev_pipe[j] = prev_pipe[j - 1];
                end
                dpipe[0] = dbuf; epipe[0] = ebuf; prev_pipe[0] = last_data; last_data = dbuf[15];
                frames = frames + 1;
                #0;
                ctrl = 1; #1;
                if ((^{code, locked, frequency, phase_debt}) === 1'bx) $fatal(1, "unknown control state");
                k = $signed({1'b0, code}) - old_code;
                if (k == 1 || k == -63) phase_steps = phase_steps + 1;
                else if (k == -1 || k == 63) phase_steps = phase_steps - 1;
                else if (k != 0) $fatal(1, "PI jumped by %0d", k);
                if (k == 63 || k == -63) wraps = wraps + 1;
                old_code = code;
                if (locked && lock_time < 0) lock_time = $realtime;
                ctrl = 0;
            end
        end
        // Note: frequency_q is PI steps per 32-UI tick => ppm = (freq_q / 65536) * (7.8125 ps / 8000 ps) * 1e6 = (freq_q / 65536) * 976.5625
        $display("RESULT v3_cdr ppm=%0.1f lock_ns=%0.3f freq_ppm=%0.3f wraps=%0d words=%0d word_errors=%0d word_gaps=%0d slips=%0d maxerr_ps=%0.3f rms_ps=%0.3f locked=%0d limited=%0d aligned=%0d",
                 OFFSET_PPM, lock_time / 1000.0, $itor(frequency) / 65536.0 * 976.5625,
                 wraps, words, word_errors, bit_errors, data_slips, max_error, $sqrt(sum_error2 / error_samples),
                 locked, limited, aligned);
        if (!locked || limited || !aligned || words < 1000 || word_errors != 0 || bit_errors != 0 || data_slips != 0 || max_error > MAX_ERROR_PS)
            $fatal(1, "v3 closed-loop CDR criteria FAILED");
        $display("PASS v3 closed-loop CDR (%0.1f ppm, /2 125 MHz, exact bitwidths)!", OFFSET_PPM);
        $finish;
    end
    initial begin #200000000; $fatal(1, "timeout"); end
endmodule
