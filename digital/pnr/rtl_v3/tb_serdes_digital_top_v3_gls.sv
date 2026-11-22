`timescale 1ns/1ps
// Post-Layout SDF Gate-Level Simulation + SVA Protocol Assertions + Verdi FSDB Testbench
// for unified serdes_digital_top_v3 (v3.1, production default parameters — identical ports
// for both RTL golden and post-route gate-level netlist).
//
// Exercises all 4 subsystems at realistic 250 MHz (4.0 ns) timing:
//   1. PLL: cold startup, 5-bit coarse VCO search & lock, plus mid-cycle pll_abort_async
//      pulse verifying ZERO combinational glitch on precharge_en/pfd_rst_b/cp_en/pll_locked.
//   2. TX: warmup, 16-word deterministic capture stream & A/B pipeline drain.
//   3. RX Align + Async FIFO: misaligned 16'hb5e3 training (offset=11) + 80 payload words
//      across async rx_word_clk (4.000 ns) -> host_clk (3.920 ns) with periodic backpressure,
//      followed by arst_n epoch reset recovery and a 2nd misaligned stream (offset=5).
//   4. RX CDR: live closed-loop +300 ppm and -300 ppm PI phase tracking using measured
//      PI phase LUT (digital/rx/tb/data/pi_phase_fs.hex) through shared rx_word_map.
module tb_serdes_digital_top_v3_gls;
    // -------------------------------------------------------------------------
    // DUT signals
    // -------------------------------------------------------------------------
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

    // Production default parameters (matches synthesized post-route netlist)
    serdes_digital_top_v3 dut (
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

    // -------------------------------------------------------------------------
    // 250 MHz realistic asynchronous root clocks (4.0 ns nominal; staggered
    // phases and slight frequency offset on host_clk to sweep full CDC phase).
    // Clocks start cleanly after cold power-on reset release (t = 30 ns).
    // -------------------------------------------------------------------------
    reg clk_en = 1'b0;
    initial begin wait (clk_en); forever #2.000 ref_clk     = ~ref_clk;     end
    initial begin wait (clk_en); #0.310; forever #2.000 tx_word_clk = ~tx_word_clk; end
    initial begin wait (clk_en); #0.670; forever #2.000 rx_word_clk = ~rx_word_clk; end
    initial begin wait (clk_en); #1.430; forever #1.960 host_clk    = ~host_clk;    end

    // -------------------------------------------------------------------------
    // Verdi FSDB dump (enabled when +FSDB_FILE=<path> plusarg is passed)
    // -------------------------------------------------------------------------
    `ifdef DUMP_FSDB
    string fsdb_file;
    initial begin
        if ($value$plusargs("FSDB_FILE=%s", fsdb_file)) begin
            $display("INFO: Dumping Verdi FSDB to %s", fsdb_file);
            $fsdbDumpfile(fsdb_file);
            $fsdbDumpvars(0, tb_serdes_digital_top_v3_gls);
            $fsdbDumpSVA(0, tb_serdes_digital_top_v3_gls);
        end
    end
    `endif

    // -------------------------------------------------------------------------
    // Behavioral analog PLL VCO frequency comparator (target band [26..28])
    // -------------------------------------------------------------------------
    always @* begin
        if ($isunknown(vco_code)) begin
            lo_async = 1'b0;
            hi_async = 1'b0;
        end else if (vco_code < 5'd26) begin
            lo_async = 1'b1;
            hi_async = 1'b0;
        end else if (vco_code > 5'd28) begin
            lo_async = 1'b0;
            hi_async = 1'b1;
        end else begin
            lo_async = 1'b0;
            hi_async = 1'b0;
        end
    end

    // -------------------------------------------------------------------------
    // SystemVerilog Assertions (SVA) + Continuous Analog-Port Glitch Monitor
    // -------------------------------------------------------------------------
    reg sva_en = 1'b0;
    integer sva_pass_cnt = 0;
    integer sva_fail_cnt = 0;
    integer pll_glitch_cnt = 0;

    // 1. PI select_a strictly one-hot after reset
    property p_pi_sel_a_onehot;
        @(posedge rx_word_clk) disable iff (!rst_n || !sva_en)
            $onehot(rx_select_a);
    endproperty
    ast_pi_sel_a_onehot: assert property (p_pi_sel_a_onehot)
        sva_pass_cnt++;
    else begin
        sva_fail_cnt++;
        $error("SVA FAIL [pi_sel_a_onehot] t=%0.3f rx_select_a=%b", $realtime, rx_select_a);
    end

    // 2. PI select_b strictly one-hot after reset
    property p_pi_sel_b_onehot;
        @(posedge rx_word_clk) disable iff (!rst_n || !sva_en)
            $onehot(rx_select_b);
    endproperty
    ast_pi_sel_b_onehot: assert property (p_pi_sel_b_onehot)
        sva_pass_cnt++;
    else begin
        sva_fail_cnt++;
        $error("SVA FAIL [pi_sel_b_onehot] t=%0.3f rx_select_b=%b", $realtime, rx_select_b);
    end

    // 3. PI select_a and select_b always disjoint
    property p_pi_sel_disjoint;
        @(posedge rx_word_clk) disable iff (!rst_n || !sva_en)
            ((rx_select_a & rx_select_b) === 8'h00);
    endproperty
    ast_pi_sel_disjoint: assert property (p_pi_sel_disjoint)
        sva_pass_cnt++;
    else begin
        sva_fail_cnt++;
        $error("SVA FAIL [pi_sel_disjoint] t=%0.3f selA=%02h selB=%02h", $realtime, rx_select_a, rx_select_b);
    end

    // 4. PI fine_b always a valid thermometer code
    property p_pi_fine_b_therm;
        @(posedge rx_word_clk) disable iff (!rst_n || !sva_en)
            (rx_fine_b inside {8'h00, 8'h01, 8'h03, 8'h07, 8'h0f, 8'h1f, 8'h3f, 8'h7f, 8'hff});
    endproperty
    ast_pi_fine_b_therm: assert property (p_pi_fine_b_therm)
        sva_pass_cnt++;
    else begin
        sva_fail_cnt++;
        $error("SVA FAIL [pi_fine_b_therm] t=%0.3f rx_fine_b=%b", $realtime, rx_fine_b);
    end

    // 5. PLL analog outputs & lock have ZERO X/Z after reset
    property p_pll_analog_no_xz;
        @(posedge ref_clk) disable iff (!rst_n || !sva_en)
            (!$isunknown({precharge_en, pfd_rst_b, cp_en, pll_locked}));
    endproperty
    ast_pll_analog_no_xz: assert property (p_pll_analog_no_xz)
        sva_pass_cnt++;
    else begin
        sva_fail_cnt++;
        $error("SVA FAIL [pll_analog_no_xz] t=%0.3f pre=%b pfd=%b cp=%b lock=%b",
               $realtime, precharge_en, pfd_rst_b, cp_en, pll_locked);
    end

    // 6. RX host_data has ZERO X/Z whenever host_valid == 1
    property p_host_data_no_xz;
        @(posedge host_clk) disable iff (!arst_n || !sva_en)
            (host_valid |-> !$isunknown(host_data));
    endproperty
    ast_host_data_no_xz: assert property (p_host_data_no_xz)
        sva_pass_cnt++;
    else begin
        sva_fail_cnt++;
        $error("SVA FAIL [host_data_no_xz] t=%0.3f host_valid=%b host_data=%h",
               $realtime, host_valid, host_data);
    end

    // 7. TX capture_data has ZERO X/Z whenever tx_capture_valid == 1
    property p_tx_cap_data_no_xz;
        @(posedge tx_word_clk) disable iff (!rst_n || !sva_en)
            (tx_capture_valid |-> !$isunknown(tx_capture_data));
    endproperty
    ast_tx_cap_data_no_xz: assert property (p_tx_cap_data_no_xz)
        sva_pass_cnt++;
    else begin
        sva_fail_cnt++;
        $error("SVA FAIL [tx_cap_data_no_xz] t=%0.3f tx_capture_valid=%b tx_capture_data=%h",
               $realtime, tx_capture_valid, tx_capture_data);
    end

    // Continuous combinational glitch detector on PLL analog outputs
    // (pll_clk_div4 period = 16.0 ns; any valid FF transition is >= 15.0 ns apart;
    //  any pulse < 8.0 ns while rst_n==1 indicates a combinational glitch!)
    real t_last_pre = -100.0, t_last_pfd = -100.0, t_last_cp = -100.0, t_last_lck = -100.0;
    always @(precharge_en) begin
        if (rst_n && sva_en) begin
            if ($isunknown(precharge_en) || ($realtime - t_last_pre) < 8.0) begin
                pll_glitch_cnt++;
                $error("GLITCH FAIL [precharge_en] t=%0.3f val=%b dt=%0.3f ns",
                       $realtime, precharge_en, $realtime - t_last_pre);
            end
            t_last_pre = $realtime;
        end
    end
    always @(pfd_rst_b) begin
        if (rst_n && sva_en) begin
            if ($isunknown(pfd_rst_b) || ($realtime - t_last_pfd) < 8.0) begin
                pll_glitch_cnt++;
                $error("GLITCH FAIL [pfd_rst_b] t=%0.3f val=%b dt=%0.3f ns",
                       $realtime, pfd_rst_b, $realtime - t_last_pfd);
            end
            t_last_pfd = $realtime;
        end
    end
    always @(cp_en) begin
        if (rst_n && sva_en) begin
            if ($isunknown(cp_en) || ($realtime - t_last_cp) < 8.0) begin
                pll_glitch_cnt++;
                $error("GLITCH FAIL [cp_en] t=%0.3f val=%b dt=%0.3f ns",
                       $realtime, cp_en, $realtime - t_last_cp);
            end
            t_last_cp = $realtime;
        end
    end
    always @(pll_locked) begin
        if (rst_n && sva_en) begin
            if ($isunknown(pll_locked) || ($realtime - t_last_lck) < 8.0) begin
                pll_glitch_cnt++;
                $error("GLITCH FAIL [pll_locked] t=%0.3f val=%b dt=%0.3f ns",
                       $realtime, pll_locked, $realtime - t_last_lck);
            end
            t_last_lck = $realtime;
        end
    end

    // -------------------------------------------------------------------------
    // Helper functions & RX physical mapper
    // -------------------------------------------------------------------------
    localparam integer NTRAIN = 16;
    function automatic [15:0] payload_word(input integer m, input integer epoch);
        payload_word = ((m * 257) ^ (epoch == 0 ? 16'h793d : 16'h4c2a));
    endfunction

    function automatic reg sbit_epoch(input integer x, input integer epoch);
        reg [15:0] v;
        begin
            v = ((x / 16) < NTRAIN) ? 16'hb5e3 : payload_word((x / 16) - NTRAIN, epoch);
            sbit_epoch = (v >> (x % 16)) & 1'b1;
        end
    endfunction

    // Pack 16 data samples d[15:0] and 16 post-data edge samples e_after[15:0] into rx_phys[31:0]
    // matching rx_word_map.sv exactly:
    //   d[12-4k]=phys[0*4+k], e_after[12-4k]=phys[2*4+k]
    //   d[13-4k]=phys[5*4+k], e_after[13-4k]=phys[7*4+k]
    //   d[14-4k]=phys[1*4+k], e_after[14-4k]=phys[3*4+k]
    //   d[15-4k]=phys[4*4+k], e_after[15-4k]=phys[6*4+k]
    function automatic [31:0] pack_rx_phys(input [15:0] d, input [15:0] e_after);
        integer k;
        reg [31:0] p;
        begin
            p = 32'd0;
            for (k = 0; k < 4; k = k + 1) begin
                p[0*4 + k] = d[12 - 4*k];  p[2*4 + k] = e_after[12 - 4*k];
                p[5*4 + k] = d[13 - 4*k];  p[7*4 + k] = e_after[13 - 4*k];
                p[1*4 + k] = d[14 - 4*k];  p[3*4 + k] = e_after[14 - 4*k];
                p[4*4 + k] = d[15 - 4*k];  p[6*4 + k] = e_after[15 - 4*k];
            end
            pack_rx_phys = p;
        end
    endfunction

    // Drive rx_phys for RX align/FIFO test (s = bit offset in stream)
    function automatic [31:0] build_align_phys(input integer s, input integer epoch);
        reg [15:0] d, ea;
        integer b;
        begin
            for (b = 0; b < 16; b = b + 1) begin
                d[b]  = sbit_epoch(s + b, epoch);
                ea[b] = sbit_epoch(s + b + 1, epoch);
            end
            build_align_phys = pack_rx_phys(d, ea);
        end
    endfunction

    // -------------------------------------------------------------------------
    // Closed-loop RX CDR behavioral plant using real measured PI LUT
    // -------------------------------------------------------------------------
    reg [31:0] phase_lut [0:63];
    reg        prbs      [0:126];
    integer    cdr_phase_steps;
    integer    cdr_old_code;
    integer    cdr_wraps;
    real       cdr_tx_ui_ps;
    real       cdr_tx_phase_ps;

    function automatic real cdr_boundary(input integer i);
        cdr_boundary = cdr_tx_phase_ps + i * cdr_tx_ui_ps;
    endfunction

    function automatic integer cdr_source_index(input real t_ps);
        integer a;
        begin
            a = $rtoi($floor((t_ps - cdr_tx_phase_ps) / cdr_tx_ui_ps));
            if (t_ps < cdr_boundary(a)) a = a - 1;
            else if (t_ps >= cdr_boundary(a + 1)) a = a + 1;
            cdr_source_index = a;
        end
    endfunction

    function automatic reg cdr_source_bit(input real t_ps);
        integer a, b;
        begin
            a = cdr_source_index(t_ps);
            if (a < 0) begin
                b = ((a % 16) + 16) % 16;
                cdr_source_bit = (16'hb5e3 >> b) & 1'b1;
            end else begin
                b = a % 127;
                cdr_source_bit = prbs[b];
            end
        end
    endfunction

    function automatic real cdr_phase_time_ps(input integer steps);
        integer turns, c;
        begin
            turns = $rtoi($floor(steps / 64.0));
            c     = ((steps % 64) + 64) % 64;
            cdr_phase_time_ps = turns * 500.0 + phase_lut[c] / 1000.0;
        end
    endfunction

    // Run a closed-loop CDR tracking leg at `ppm` offset for `n_words` 16-UI words.
    // Supports both cold start (reset_plant=1) and live continuous frequency step (reset_plant=0)!
    task automatic run_cdr_leg(
        input  real    ppm,
        input  integer n_words,
        input  integer settle_words,
        input  bit     reset_plant,
        output integer out_locked,
        output integer out_limited,
        output integer out_wraps,
        output integer out_freq_q,
        output real    out_lock_us,
        output real    out_max_err_ps,
        output real    out_rms_err_ps
    );
        integer w, b, k, idx, err_cnt, lock_word, locked_steady, total_steady;
        reg [15:0] d_word, ea_word;
        real t_base_ps, ptime_ps, td_ps, te_after_ps, center_ps, err_ps, sum_err2;
        reg [5:0] sampled_code;
        begin
            cdr_tx_ui_ps    = 250.0 / (1.0 + ppm * 1.0e-6);
            cdr_tx_phase_ps = 73.0;
            if (reset_plant) begin
                cdr_phase_steps = 0;
            end
            cdr_wraps       = 0;
            out_max_err_ps  = 0.0;
            sum_err2        = 0.0;
            err_cnt         = 0;
            lock_word       = -1;
            locked_steady   = 0;
            total_steady    = 0;

            // Sample initial code cleanly at posedge rx_word_clk + 3.400 ns
            // (>1.2 ns away from rx_phase_code transitions across RTL, FF, TT, and SS!)
            @(posedge rx_word_clk);
            #0.650;
            rx_cdr_enable = 1'b1;
            #2.750;
            cdr_old_code  = rx_phase_code;

            for (w = 0; w < n_words; w = w + 1) begin
                // Sample 16 UI data & post-data edges with live PI delay, then drive rx_phys
                // strictly inside SDC input window (+0.650 ns after posedge rx_word_clk -> 0 violations!)
                @(posedge rx_word_clk);
                #0.650;
                ptime_ps  = cdr_phase_time_ps(cdr_phase_steps);
                t_base_ps = 2000.0 + w * 4000.0;
                for (b = 0; b < 16; b = b + 1) begin
                    td_ps       = t_base_ps + b * 250.0 + 125.0 - ptime_ps;
                    te_after_ps = t_base_ps + (b + 1) * 250.0 - ptime_ps;
                    d_word[b]   = cdr_source_bit(td_ps);
                    ea_word[b]  = cdr_source_bit(te_after_ps);
                    if (w >= settle_words) begin
                        idx       = cdr_source_index(td_ps);
                        center_ps = 0.5 * (cdr_boundary(idx) + cdr_boundary(idx + 1));
                        err_ps    = td_ps - center_ps;
                        if (err_ps < 0.0) err_ps = -err_ps;
                        if (err_ps > out_max_err_ps) out_max_err_ps = err_ps;
                        sum_err2 = sum_err2 + err_ps * err_ps;
                        err_cnt  = err_cnt + 1;
                    end
                end
                rx_phys = pack_rx_phys(d_word, ea_word);

                // Sample rx_phase_code at posedge + 3.400 ns (settled cleanly in RTL, FF, TT, and SS!)
                #2.750;
                sampled_code = rx_phase_code;
                if ($isunknown(sampled_code))
                    $fatal(1, "CDR X on rx_phase_code at word %0d", w);
                k = $signed({1'b0, sampled_code}) - cdr_old_code;
                if (k == 1 || k == -63) begin
                    cdr_phase_steps = cdr_phase_steps + 1;
                end else if (k == -1 || k == 63) begin
                    cdr_phase_steps = cdr_phase_steps - 1;
                end else if (k != 0) begin
                    $fatal(1, "CDR illegal PI jump by %0d (old=%0d new=%0d) at word %0d",
                           k, cdr_old_code, sampled_code, w);
                end
                if (k == 63 || k == -63) cdr_wraps = cdr_wraps + 1;
                cdr_old_code = sampled_code;
                if (reset_plant) begin
                    if (rx_cdr_locked && lock_word < 0) lock_word = w;
                end else begin
                    if (rx_cdr_locked && rx_cdr_frequency_q < -10000 && lock_word < 0) lock_word = w;
                end
                if (w >= settle_words) begin
                    total_steady = total_steady + 1;
                    if (rx_cdr_locked) locked_steady = locked_steady + 1;
                end
            end

            @(posedge rx_word_clk);
            out_locked     = (rx_cdr_locked || (lock_word >= 0 && locked_steady * 2 >= total_steady)) ? 1 : 0;
            out_limited    = rx_cdr_range_limited;
            out_wraps      = cdr_wraps;
            out_freq_q     = rx_cdr_frequency_q;
            out_lock_us    = (lock_word >= 0) ? (lock_word * 0.004) : -1.0;
            out_rms_err_ps = (err_cnt > 0) ? $sqrt(sum_err2 / err_cnt) : 999.0;
        end
    endtask

    // -------------------------------------------------------------------------
    // Host-side RX FIFO checker (samples cleanly at posedge host_clk)
    // -------------------------------------------------------------------------
    integer rx_got, rx_expect, rx_epoch, rx_mismatch;
    reg     rx_checking, rx_seen_payload;

    always @(posedge host_clk) begin
        if (arst_n && host_valid && host_ready && rx_checking) begin
            if ($isunknown(host_data)) begin
                rx_mismatch = rx_mismatch + 1;
                $fatal(1, "RX host_data X/Z at epoch %0d idx %0d: %h", rx_epoch, rx_expect, host_data);
            end else if (!rx_seen_payload && host_data === 16'hb5e3) begin
                // Trailing training word drained cleanly
            end else begin
                rx_seen_payload = 1'b1;
                if (host_data !== payload_word(rx_expect, rx_epoch)) begin
                    rx_mismatch = rx_mismatch + 1;
                    $fatal(1, "RX host mismatch epoch %0d idx %0d: got %04h expected %04h",
                           rx_epoch, rx_expect, host_data, payload_word(rx_expect, rx_epoch));
                end
                rx_expect = rx_expect + 1;
                rx_got    = rx_got + 1;
            end
        end
    end

    // Bursty realistic host_ready backpressure during RX FIFO phase
    // (stalls for 4 cycles at burst boundaries to exercise the 3-entry FWFT skid
    //  buffer & Gray CDC without overflowing the 16-entry FIFO)
    reg host_bp_en = 1'b0;
    integer bp_cnt = 0;
    always @(posedge host_clk) begin
        if (host_bp_en) begin
            #0.650;
            bp_cnt     = bp_cnt + 1;
            host_ready = ((bp_cnt >= 22 && bp_cnt < 26) || (bp_cnt >= 56 && bp_cnt < 60)) ? 1'b0 : 1'b1;
        end
    end

    // -------------------------------------------------------------------------
    // Clean arst_n epoch reset pulse helper (releases arst_n safely in the middle
    // of rx_word_clk & host_clk LOW half-cycles so all non-sync arst_n endpoints
    // see clean recovery/removal margin across TT/SS/FF corners)
    // -------------------------------------------------------------------------
    task automatic pulse_arst_n();
        integer tries;
        reg aligned_edge;
        begin
            @(negedge rx_word_clk);
            #0.300;
            arst_n = 1'b0;
            #32.0;
            // Wait for a beat where posedge rx_word_clk and posedge host_clk coincide within 0.4 ns,
            // then release arst_n 1.9 ns later (right in the middle of BOTH clocks' 4.0 ns periods ->
            // >1.0 ns recovery & removal margin simultaneously in TT, SS, and FF!).
            aligned_edge = 1'b0;
            tries = 0;
            while (!aligned_edge && tries < 80) begin
                @(posedge rx_word_clk);
                if (host_clk === 1'b0) begin
                    #0.400;
                    if (host_clk === 1'b1) aligned_edge = 1'b1;
                end
                tries = tries + 1;
            end
            #2.100; // ~2.5 ns after posedge rx_word_clk, ~2.2 ns after posedge host_clk -> >350 ps removal & >1.4 ns recovery in TT/SS/FF!
            arst_n = 1'b1;
            repeat (8) @(posedge rx_word_clk);
        end
    endtask

    // -------------------------------------------------------------------------
    // Main test sequence
    // -------------------------------------------------------------------------
    reg [6:0]  lfsr;
    reg [15:0] tx_vec [0:15];
    integer    j, cyc, pll_lock_cyc, tx_checked, rx_words_e0, rx_words_e1;
    integer    cdr_p_lck, cdr_p_lim, cdr_p_wraps, cdr_p_freq;
    integer    cdr_m_lck, cdr_m_lim, cdr_m_wraps, cdr_m_freq;
    real       cdr_p_lock_us, cdr_p_max_ps, cdr_p_rms_ps;
    real       cdr_m_lock_us, cdr_m_max_ps, cdr_m_rms_ps;
    real       t_abort_rise;
    reg        pre_before, pfd_before, cp_before, lck_before;

    initial begin
        $readmemh("digital/rx/tb/data/pi_phase_fs.hex", phase_lut);
        lfsr = 7'h5d;
        for (j = 0; j < 127; j = j + 1) begin
            prbs[j] = lfsr[0];
            lfsr    = {lfsr[0] ^ lfsr[1], lfsr[6:1]};
        end

        rx_got = 0; rx_expect = 0; rx_epoch = 0; rx_mismatch = 0;
        rx_checking = 0; rx_seen_payload = 0;

        // Clean cold power-on reset: assert resets with clocks parked low, release resets,
        // wait 12 ns for full reset tree to settle across SS/TT/FF, then enable clocks!
        rst_n = 1'b0; arst_n = 1'b0; clk_en = 1'b0;
        #20.0;
        rst_n = 1'b1; arst_n = 1'b1;
        #12.0;
        clk_en = 1'b1;
        repeat (8) @(posedge ref_clk);
        sva_en = 1'b1;

        // =====================================================================
        // 1. PLL: Cold startup -> 5-bit coarse search -> lock -> mid-cycle abort
        // =====================================================================
        @(posedge ref_clk); #0.650;
        pll_enable          = 1'b1;
        bias_ready_async    = 1'b1;
        pre_ref_ready_async = 1'b1;
        repeat (16) @(posedge ref_clk);
        #0.650; pll_start = 1'b1;
        @(posedge ref_clk);
        #0.650; pll_start = 1'b0;

        cyc = 0;
        while (!pll_locked && cyc < 16000) begin
            @(posedge ref_clk);
            cyc = cyc + 1;
        end
        pll_lock_cyc = cyc;
        if (!pll_locked || pll_fault || !cp_en || !pfd_rst_b || precharge_en)
            $fatal(1, "PLL failed to lock: locked=%b fault=%b state=%0d vco=%0d pre=%b pfd=%b cp=%b",
                   pll_locked, pll_fault, pll_state_id, vco_code, precharge_en, pfd_rst_b, cp_en);
        if (vco_code < 5'd26 || vco_code > 5'd28)
            $fatal(1, "PLL 5-bit vco_code out of band [26..28]: got %0d", vco_code);
        $display("PASS [1A/4] PLL locked in %0d ref_clk cycles (vco_code=%0d, switches=0x%02h)",
                 pll_lock_cyc, vco_code, switches);

        // Mid-cycle asynchronous pll_abort_async pulse test (Bug A glitch signoff)
        repeat (12) @(posedge ref_clk);
        pre_before   = precharge_en;
        pfd_before   = pfd_rst_b;
        cp_before    = cp_en;
        lck_before   = pll_locked;
        #1.370; // Deliberately mid-cycle asynchronous!
        t_abort_rise    = $realtime;
        pll_abort_async = 1'b1;
        // Verify ZERO combinational reaction within 1.5 ns of async abort edge
        #1.500;
        if (precharge_en !== pre_before || pfd_rst_b !== pfd_before ||
            cp_en !== cp_before || pll_locked !== lck_before)
            $fatal(1, "PLL analog output reacted combinationally to mid-cycle pll_abort_async!");
        // Hold abort across >= 3 pll_clk_div4 periods (48 ns = 12 ref_clk)
        repeat (16) @(posedge ref_clk);
        if (!pll_fault || pll_fault_code !== 3'd5 || precharge_en || pfd_rst_b || cp_en || pll_locked)
            $fatal(1, "PLL abort did not cleanly enter FAULT 5: fault=%b code=%0d pre=%b pfd=%b cp=%b lck=%b",
                   pll_fault, pll_fault_code, precharge_en, pfd_rst_b, cp_en, pll_locked);
        #0.650; pll_abort_async = 1'b0;
        repeat (8) @(posedge ref_clk);
        if (pll_glitch_cnt != 0)
            $fatal(1, "PLL analog outputs had %0d glitches!", pll_glitch_cnt);
        $display("PASS [1B/4] PLL mid-cycle abort_async -> FAULT 5 with 0 glitches (t_abort=%0.3f ns)",
                 t_abort_rise);

        // =====================================================================
        // 2. TX Ingress: Warmup + 16-word deterministic capture & A/B drain
        // =====================================================================
        tx_vec[0]  = 16'ha55a; tx_vec[1]  = 16'h1234; tx_vec[2]  = 16'hdead; tx_vec[3]  = 16'hbeef;
        tx_vec[4]  = 16'h00ff; tx_vec[5]  = 16'hff00; tx_vec[6]  = 16'h5a5a; tx_vec[7]  = 16'h3c3c;
        tx_vec[8]  = 16'h8001; tx_vec[9]  = 16'h7ffe; tx_vec[10] = 16'h1357; tx_vec[11] = 16'h2468;
        tx_vec[12] = 16'hcafe; tx_vec[13] = 16'hbabe; tx_vec[14] = 16'h9669; tx_vec[15] = 16'h0f0f;

        @(posedge tx_word_clk); #0.650;
        tx_enable     = 1'b1;
        tx_clock_good = 1'b1;
        // Wait 2 cycles for warmup to assert tx_word_ready
        repeat (2) @(posedge tx_word_clk);
        if (!tx_word_ready)
            $fatal(1, "TX tx_word_ready did not assert after warmup");

        tx_checked = 0;
        for (j = 0; j < 16; j = j + 1) begin
            #0.650;
            tx_in_valid = 1'b1;
            tx_in_data  = tx_vec[j];
            @(posedge tx_word_clk); // captures tx_vec[j] into dut
            // Sample captured output right before NEXT posedge (actually at next posedge!)
            if (j >= 1) begin
                if (!tx_capture_valid || tx_capture_data !== tx_vec[j-1])
                    $fatal(1, "TX capture mismatch word %0d: valid=%b got=%04h exp=%04h",
                           j-1, tx_capture_valid, tx_capture_data, tx_vec[j-1]);
                if (j >= 2 && !tx_a_valid) $fatal(1, "TX a_valid missing at word %0d", j);
                if (j >= 3 && !tx_b_valid) $fatal(1, "TX b_valid missing at word %0d", j);
                tx_checked = tx_checked + 1;
            end
        end
        // Deassert tx_in_valid and check last captured word + drain
        #0.650; tx_in_valid = 1'b0;
        @(posedge tx_word_clk);
        if (!tx_capture_valid || tx_capture_data !== tx_vec[15] || !tx_a_valid || !tx_b_valid)
            $fatal(1, "TX last word mismatch: valid=%b data=%04h a=%b b=%b",
                   tx_capture_valid, tx_capture_data, tx_a_valid, tx_b_valid);
        tx_checked = tx_checked + 1;
        @(posedge tx_word_clk);
        if (tx_capture_valid || !tx_a_valid || !tx_b_valid)
            $fatal(1, "TX drain step 1 mismatch: cap=%b a=%b b=%b", tx_capture_valid, tx_a_valid, tx_b_valid);
        $display("PASS [2/4] TX ingress (250 MHz) warmup, %0d-word capture & A/B pipeline verified", tx_checked);

        // =====================================================================
        // 3. RX Word Align + Async FIFO (rx_word_clk -> host_clk) + arst_n recovery
        // =====================================================================
        wait (rx_word_online && host_online);
        // Epoch 0: misaligned offset=11 (stream start at 16 + 5 => shift 11 bits)
        rx_epoch = 0; rx_got = 0; rx_expect = 0; rx_seen_payload = 0; bp_cnt = 0; rx_checking = 1'b1;
        @(posedge host_clk); #0.650; host_ready = 1'b1; host_bp_en = 1'b1;
        for (j = 0; j < NTRAIN + 96; j = j + 1) begin
            @(posedge rx_word_clk); #0.650;
            rx_phys            = build_align_phys(16 + 5 + 16*j, 0);
            rx_training_enable = (j < NTRAIN - 1);
        end
        rx_checking = 1'b0;
        host_bp_en  = 1'b0;
        @(posedge host_clk); #0.650; host_ready = 1'b1;
        repeat (16) @(posedge host_clk);
        rx_words_e0 = rx_got;
        if (!rx_aligned || rx_offset !== 4'd11 || rx_words_e0 < 80 || host_error)
            $fatal(1, "RX epoch 0 failed: aligned=%b offset=%0d words=%0d err=%b",
                   rx_aligned, rx_offset, rx_words_e0, host_error);
        $display("PASS [3A/4] RX align+async FIFO epoch 0 verified (offset=%0d, words=%0d, err=%b)",
                 rx_offset, rx_words_e0, host_error);

        // Epoch 1: arst_n reset recovery -> re-align at DIFFERENT offset=5 (16 + 11)
        @(posedge rx_word_clk); #0.650; rx_training_enable = 1'b1;
        @(posedge host_clk);    #0.650; host_ready = 1'b0;
        pulse_arst_n();
        wait (rx_word_online && host_online);
        rx_epoch = 1; rx_got = 0; rx_expect = 0; rx_seen_payload = 0; bp_cnt = 0; rx_checking = 1'b1;
        @(posedge host_clk); #0.650; host_ready = 1'b1; host_bp_en = 1'b1;
        for (j = 0; j < NTRAIN + 48; j = j + 1) begin
            @(posedge rx_word_clk); #0.650;
            rx_phys            = build_align_phys(16 + 11 + 16*j, 1);
            rx_training_enable = (j < NTRAIN - 1);
        end
        rx_checking = 1'b0;
        host_bp_en  = 1'b0;
        @(posedge host_clk); #0.650; host_ready = 1'b1;
        repeat (16) @(posedge host_clk);
        rx_words_e1 = rx_got;
        if (!rx_aligned || rx_offset !== 4'd5 || rx_words_e1 < 32 || host_error)
            $fatal(1, "RX epoch 1 (post-arst_n) failed: aligned=%b offset=%0d words=%0d err=%b",
                   rx_aligned, rx_offset, rx_words_e1, host_error);
        $display("PASS [3B/4] RX arst_n recovery + epoch 1 verified (offset=%0d, words=%0d, err=%b)",
                 rx_offset, rx_words_e1, host_error);

        // =====================================================================
        // 4. RX CDR: Live closed-loop +300 ppm and continuous -300 ppm tracking
        // =====================================================================
        // 4A: +300 ppm cold lock (8,000 words = 32.0 us = 128,000 UI; settle after 5,500 words)
        run_cdr_leg(+300.0, 8000, 5500, 1'b1,
                    cdr_p_lck, cdr_p_lim, cdr_p_wraps, cdr_p_freq,
                    cdr_p_lock_us, cdr_p_max_ps, cdr_p_rms_ps);
        if (!cdr_p_lck || cdr_p_lim || cdr_p_wraps < 2 || cdr_p_freq <= 0 || cdr_p_max_ps > 25.0)
            $fatal(1, "CDR +300 ppm FAILED: lck=%0d lim=%0d wraps=%0d freq_q=%0d max_ps=%0.2f",
                   cdr_p_lck, cdr_p_lim, cdr_p_wraps, cdr_p_freq, cdr_p_max_ps);
        $display("PASS [4A/4] RX CDR +300 ppm closed-loop locked (lock_us=%0.2f wraps=%0d freq_q=%0d max_err=%0.2f ps rms=%0.2f ps)",
                 cdr_p_lock_us, cdr_p_wraps, cdr_p_freq, cdr_p_max_ps, cdr_p_rms_ps);

        // 4B: Live continuous frequency reversal +300 ppm -> -300 ppm (8,000 words = 32.0 us, ZERO reset!)
        run_cdr_leg(-300.0, 8000, 3500, 1'b0,
                    cdr_m_lck, cdr_m_lim, cdr_m_wraps, cdr_m_freq,
                    cdr_m_lock_us, cdr_m_max_ps, cdr_m_rms_ps);
        if (!cdr_m_lck || cdr_m_lim || cdr_m_wraps < 2 || cdr_m_freq >= 0 || cdr_m_max_ps > 25.0)
            $fatal(1, "CDR -300 ppm FAILED: lck=%0d lim=%0d wraps=%0d freq_q=%0d max_ps=%0.2f",
                   cdr_m_lck, cdr_m_lim, cdr_m_wraps, cdr_m_freq, cdr_m_max_ps);
        $display("PASS [4B/4] RX CDR -300 ppm live reversal locked (retrack_us=%0.2f wraps=%0d freq_q=%0d max_err=%0.2f ps rms=%0.2f ps)",
                 cdr_m_lock_us, cdr_m_wraps, cdr_m_freq, cdr_m_max_ps, cdr_m_rms_ps);

        // Final SVA & glitch gate
        if (sva_fail_cnt != 0 || pll_glitch_cnt != 0)
            $fatal(1, "SVA/Glitch failures: sva_fail=%0d pll_glitch=%0d", sva_fail_cnt, pll_glitch_cnt);

        $display("GLS_SUMMARY pll_lock_cyc=%0d pll_vco=%0d pll_glitches=%0d tx_words=%0d rx_e0_words=%0d rx_e1_words=%0d rx_mismatch=%0d cdr_p300_lock_us=%0.3f cdr_p300_wraps=%0d cdr_p300_max_ps=%0.3f cdr_p300_rms_ps=%0.3f cdr_m300_lock_us=%0.3f cdr_m300_wraps=%0d cdr_m300_max_ps=%0.3f cdr_m300_rms_ps=%0.3f sva_pass=%0d sva_fail=%0d",
                 pll_lock_cyc, vco_code, pll_glitch_cnt, tx_checked, rx_words_e0, rx_words_e1, rx_mismatch,
                 cdr_p_lock_us, cdr_p_wraps, cdr_p_max_ps, cdr_p_rms_ps,
                 cdr_m_lock_us, cdr_m_wraps, cdr_m_max_ps, cdr_m_rms_ps,
                 sva_pass_cnt, sva_fail_cnt);
        $display("ALL GLS + SVA CHECKS PASSED for serdes_digital_top_v3!");
        $finish;
    end

    initial begin
        #500000.0; // 500 us hard timeout
        $fatal(1, "GLS testbench hard timeout at %0.3f ns", $realtime);
    end
endmodule
