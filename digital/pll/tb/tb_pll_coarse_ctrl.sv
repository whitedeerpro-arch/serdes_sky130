// pll_coarse_ctrl against a behavioural loop: locked Vctrl of code k at temperature T is
//   V(k, T) = v15 - STEP * (15 - k) + TC * (T - 27)        (higher code = slower = higher Vctrl; warming raises it)
// z follows V with a 300 ns first-order lag, clamped to the CP range 0.3 .. VDD - 0.3 V; the comparators see z with
// +-2 mV noise.  Ladders as analog/pll/coarse/spice/vctrl_window.spice: vlo = 0.80 + 0.02 code, vhi = VDD - (0.32 + 0.03 code).
// Checks: (1) power-up code = an independent evaluation of the slow-end rule for each class and chip offset;
// (2) a -40 -> 85 -> -40 C sweep keeps z inside the window except within one hold after a switch, with no two
// switches closer than HOLD, and each switch moves the code the right way; (3) slow_end / fast_end at the range ends.
module tb_pll_coarse_ctrl;
    timeunit 1ns;
    timeprecision 1ps;
    localparam real VDD = 1.8, STEP = 0.14;
    real TC = 0.0022;
    localparam integer SETTLE = 400, HOLD = 1500;
    reg ref_clk = 0, rst_n = 0, search = 0, track_en = 0;
    reg [1:0] tclass = 0;
    reg hi_async = 0, lo_async = 0;
    reg [3:0] lo_run = 5, hi_run = 3;               // vlo 0.90 V, vhi VDD - 0.41 V
    reg [11:0] stop_code;
    reg [2:0] stop_sel;
    wire [3:0] vco_code, lo_code, hi_code;
    wire busy, done, fast_end, slow_end;
    wire [7:0] switches;
    pll_coarse_ctrl #(.SETTLE_CYCLES(SETTLE), .SAMPLE_DIV(16), .PERSIST(8), .HOLD_CYCLES(HOLD)) dut (.*);

    real temp = 27.0, v15 = 1.40, z = 1.0, target, vlo_v, vhi_v, n;
    integer errors = 0, seed = 7, last_switch_t = -100000, k, sw_prev, cyc = 0, ups = 0, downs = 0;
    reg [3:0] code_prev;
    always #2 ref_clk = ~ref_clk;
    always @(posedge ref_clk) cyc <= cyc + 1;

    function real vlock(input integer code, input real t);
        vlock = v15 - STEP * (15 - code) + TC * (t - 27.0);
    endfunction
    function real vlo_of(input [3:0] c); vlo_of = 0.80 + 0.02 * c; endfunction
    function real vhi_of(input [3:0] c); vhi_of = VDD - (0.32 + 0.03 * c); endfunction

    // loop + detector, 4 ns steps
    always @(posedge ref_clk) begin
        target = vlock(vco_code, temp);
        if (target < 0.3) target = 0.3;
        if (target > VDD - 0.3) target = VDD - 0.3;
        z = z + (target - z) * (4.0 / 300.0);
        n = ($dist_uniform(seed, -2000, 2000)) * 1e-6;
        hi_async <= (z + n) > vhi_of(hi_code);
        lo_async <= (z + n) < vlo_of(lo_code);
    end

    // independent slow-end rule
    function integer expect_code(input integer cls, input real t, input real dv);
        integer c, i;
        real vstop;
        reg found;
        begin
            vstop = (stop_sel[cls] ? vhi_of(stop_code[4*cls +: 4]) : vlo_of(stop_code[4*cls +: 4])) + dv;
            found = 0; c = 0;
            for (i = 15; i >= 0 && !found; i = i - 1) begin
                if (vlock(i, t) <= vstop) begin c = i; found = 1; end
            end
            if (!found) c = 0;
            if (vlock(c, t) < vlo_of(lo_run) && c != 15) c = c + 1;
            expect_code = c;
        end
    endfunction

    task powerup(input real t, input real v15_chip, input integer cls);
        integer e;
        begin
            temp = t; v15 = v15_chip; tclass = cls; track_en = 0;
            z = 0.9; repeat (20) @(negedge ref_clk);
            search = 1; @(negedge ref_clk); search = 0;
            wait (done); repeat (4) @(negedge ref_clk);
            // a lock point within the noise (+-2 mV) and settling residue of the stop threshold may go either way
            e = expect_code(cls, t, 0.0);
            if (vco_code != expect_code(cls, t, -0.003) && vco_code != expect_code(cls, t, 0.003)) begin
                $display("FAIL power-up T=%0.0f v15=%0.2f class %0d: code %0d expected %0d", t, v15_chip, cls, vco_code, e);
                errors = errors + 1;
            end else $display("ok   power-up T=%0.0f v15=%0.2f class %0d: code %0d (Vctrl %0.3f)", t, v15_chip, cls, vco_code, vlock(vco_code, t));
        end
    endtask

    initial begin
        // stops: cold -> VDD - 0.71 (hi ladder, code 13), middle -> VDD - 0.56 (code 8), hot -> VDD - 0.44 (code 4)
        stop_code = {4'd4, 4'd8, 4'd13};
        stop_sel = 3'b111;
        #20 rst_n = 1;
        for (k = 0; k < 4; k = k + 1) begin
            powerup(-40.0, 1.30 + 0.07 * k, 0);
            powerup(27.0, 1.30 + 0.07 * k, 1);
            powerup(85.0, 1.30 + 0.07 * k, 2);
        end
        // ground-referenced stop for the cold class
        stop_sel = 3'b110; stop_code = {4'd4, 4'd8, 4'd8};
        powerup(-40.0, 1.37, 0);
        stop_sel = 3'b111; stop_code = {4'd4, 4'd8, 4'd13};
        // (2) temperature sweep, re-coding on: power-up at -40 C with the hot class (a sensor error) and a strong
        // temperature coefficient (4.5 mV/K, ~0.56 V over the range), so the window is crossed both ways
        TC = 0.0045;
        powerup(-40.0, 1.37, 2);
        track_en = 1; sw_prev = switches; code_prev = vco_code;
        for (k = 0; k < 2 * 125 * 10; k = k + 1) begin
            temp = (k < 1250) ? -40.0 + k * 0.1 : 85.0 - (k - 1250) * 0.1;
            repeat (100) @(negedge ref_clk);                 // 0.1 K per 400 ns
            if (switches != sw_prev) begin
                if (cyc - last_switch_t < HOLD) begin $display("FAIL two switches %0d cycles apart", cyc - last_switch_t); errors = errors + 1; end
                last_switch_t = cyc; sw_prev = switches;
                // warming raises Vctrl -> faster code (down); cooling -> slower code (up)
                if (vco_code < code_prev) begin downs = downs + 1; if (k >= 1250) begin $display("FAIL faster code while cooling"); errors = errors + 1; end end
                else begin ups = ups + 1; if (k < 1250) begin $display("FAIL slower code while warming"); errors = errors + 1; end end
                code_prev = vco_code;
                $display("     switch at T=%0.1f C -> code %0d", temp, vco_code);
            end
            if (cyc - last_switch_t > HOLD + 400 && (z > vhi_of(hi_run) + 0.01 || z < vlo_of(lo_run) - 0.01)) begin
                $display("FAIL z %0.3f outside the window at T=%0.1f code %0d", z, temp, vco_code); errors = errors + 1;
                k = 1000000;
            end
        end
        $display("     %0d switches over the -40 -> 85 -> -40 C sweep", switches);
        if (ups == 0 || downs == 0) begin $display("FAIL the sweep did not re-code both ways (%0d faster, %0d slower)", downs, ups); errors = errors + 1; end
        TC = 0.0022;
        // (3) range ends: a fast chip (code 15 below vlo) and a slow chip (code 0 above vhi)
        powerup(-40.0, 0.80, 0); track_en = 1; repeat (HOLD + 400) @(negedge ref_clk);
        if (!slow_end || vco_code != 15) begin $display("FAIL slow_end %0d code %0d", slow_end, vco_code); errors = errors + 1; end
        else $display("ok   fast chip holds at code 15 with slow_end");
        powerup(85.0, 3.70, 2); track_en = 1; repeat (HOLD + 400) @(negedge ref_clk);
        if (!fast_end || vco_code != 0) begin $display("FAIL fast_end %0d code %0d", fast_end, vco_code); errors = errors + 1; end
        else $display("ok   slow chip at code 0 flags fast_end");
        if (errors) $fatal(1, "%0d failures", errors);
        $display("PASS");
        $finish;
    end
endmodule
