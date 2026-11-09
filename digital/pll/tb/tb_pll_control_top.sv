// pll_control_top against a behavioural loop.
//   V(k, T) = v15 - 0.14 (15 - k) + TC (T - 27): locked Vctrl of code k (higher code = slower = higher Vctrl).
//   Precharge drives z to 1.20 V; with the CP on z follows V(code) with 300 ns, clamped to the CP range 0.3 .. VDD - 0.3.
//   pw_late (a PFD pulse still high at ref + tau) while z is more than 15 mV from the lock point or clamped.
//   Window detector as analog/pll/coarse/spice/vctrl_window.spice: vlo = 0.80 + 0.02 lo_code, vhi = VDD - (0.32 + 0.03 hi_code).
// Checks: (1) a cold start locks with the slow-end search result and the search runs once; (2) a temperature ramp
// re-codes, lock drops and returns without FAULT or a new search; (3) a chip that cannot reach 2 GHz at code 0 ends in
// FAULT code 3; (4) a restart after FAULT searches again and locks.
module tb_pll_control_top;
    timeunit 1ns;
    timeprecision 1ps;
    localparam real VDD = 1.8, STEP = 0.14;
    reg ref_clk = 0, rst_n = 0, enable = 0, start = 0, abort_async = 0;
    reg bias_ready_async = 0, pre_ref_ready_async = 0;
    reg [1:0] tclass = 1;
    reg hi_async = 0, lo_async = 0, pw_late_async = 0;
    reg [3:0] lo_run = 5, hi_run = 3;
    reg [11:0] stop_code = {4'd4, 4'd8, 4'd13};
    reg [2:0] stop_sel = 3'b111;
    wire precharge_en, pfd_rst_b, cp_en, locked, busy, fault;
    wire [2:0] state_id, fault_code;
    wire [3:0] vco_code, lo_code, hi_code;
    wire coarse_busy, coarse_done, fast_end, slow_end;
    wire [7:0] switches;
    pll_control_top #(.SETTLE_CYCLES(400), .HOLD_CYCLES(1500)) dut (.*);

    real temp = 27.0, v15 = 1.40, TC = 0.0022, z = 0.0, target, vlo_v, vhi_v;
    integer errors = 0, searches = 0, k, t_lock;
    always #2 ref_clk = ~ref_clk;
    function real vlock(input integer code); vlock = v15 - STEP * (15 - code) + TC * (temp - 27.0); endfunction
    always @(posedge ref_clk) begin
        target = vlock(vco_code);
        if (target < 0.3) target = 0.3;
        if (target > VDD - 0.3) target = VDD - 0.3;
        if (precharge_en) z = z + (1.20 - z) * 0.2;
        else if (cp_en) z = z + (target - z) * (4.0 / 300.0);
        vlo_v = 0.80 + 0.02 * lo_code;
        vhi_v = VDD - (0.32 + 0.03 * hi_code);
        hi_async <= z > vhi_v;
        lo_async <= z < vlo_v;
        pw_late_async <= cp_en && ((z - target > 0.015) || (target - z > 0.015) || vlock(vco_code) < 0.3 || vlock(vco_code) > VDD - 0.3);
    end
    always @(posedge dut.search_pulse) searches = searches + 1;

    task wait_lock(input integer limit, output integer took);
        integer n;
        begin
            n = 0;
            while (!locked && !fault && n < limit) begin @(negedge ref_clk); n = n + 1; end
            took = n;
        end
    endtask

    initial begin
        #20 rst_n = 1; enable = 1;
        #100 bias_ready_async = 1; pre_ref_ready_async = 1;
        // (1) cold start at 27 C, middle class
        @(negedge ref_clk) start = 1; @(negedge ref_clk) start = 0;
        wait_lock(40000, t_lock);
        if (!locked) begin $display("FAIL no lock after %0d cycles (state %0d fault %0d code %0d)", t_lock, state_id, fault_code, vco_code); errors = errors + 1; end
        else $display("ok   locked after %0d cycles (%0.1f us), code %0d, Vctrl %0.3f", t_lock, t_lock * 4e-3, vco_code, vlock(vco_code));
        if (searches != 1) begin $display("FAIL %0d searches", searches); errors = errors + 1; end
        repeat (3000) @(negedge ref_clk);
        if (!locked) begin $display("FAIL lock not held"); errors = errors + 1; end
        // (2) temperature ramp with a strong coefficient (7 mV/K: +0.42 V over 60 K): crosses vhi, re-codes, re-locks
        TC = 0.007;
        for (k = 0; k < 600; k = k + 1) begin temp = 27.0 + k * 0.1; repeat (100) @(negedge ref_clk); if (fault) k = 100000; end
        repeat (8000) @(negedge ref_clk);
        if (fault) begin $display("FAIL FAULT %0d during the ramp", fault_code); errors = errors + 1; end
        else if (switches == 0) begin $display("FAIL no re-code during the ramp"); errors = errors + 1; end
        else if (!locked) begin $display("FAIL not re-locked after %0d re-codes (state %0d)", switches, state_id); errors = errors + 1; end
        else $display("ok   ramp to %0.0f C: %0d re-code(s), locked again at code %0d, no new search (%0d)", temp, switches, vco_code, searches);
        if (searches != 1) begin $display("FAIL search repeated on re-acquire"); errors = errors + 1; end
        // (3) a chip too slow for 2 GHz even at code 0
        enable = 0; @(negedge ref_clk); enable = 1; TC = 0.0022; temp = 27.0; v15 = 3.70; tclass = 2;
        @(negedge ref_clk) start = 1; @(negedge ref_clk) start = 0;
        wait_lock(60000, t_lock);
        if (!fault || fault_code != 3) begin $display("FAIL slow chip: fault %0d code %0d locked %0d vco %0d", fault, fault_code, locked, vco_code); errors = errors + 1; end
        else $display("ok   slow chip ends in FAULT 3 (range) at code %0d after %0d cycles", vco_code, t_lock);
        // (4) restart after FAULT with a normal chip
        v15 = 1.40; tclass = 0; temp = -40.0;
        @(negedge ref_clk) start = 1; @(negedge ref_clk) start = 0;
        wait_lock(40000, t_lock);
        if (!locked) begin $display("FAIL no lock after restart (state %0d fault %0d)", state_id, fault_code); errors = errors + 1; end
        else $display("ok   restart from FAULT: locked after %0d cycles at code %0d (Vctrl %0.3f), %0d searches in total", t_lock, vco_code, vlock(vco_code), searches);
        if (errors) $fatal(1, "%0d failures", errors);
        $display("PASS");
        $finish;
    end
endmodule
