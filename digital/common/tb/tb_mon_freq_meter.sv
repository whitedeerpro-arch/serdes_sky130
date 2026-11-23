// mon_freq_meter: counts against the ideal window * f_meas / f_ref (+-1) for slow, nominal, fast and very fast
// measured clocks at random phase, and the stalled flag when the measured clock stops.
module tb_mon_freq_meter;
    timeunit 1ns;
    timeprecision 1ps;
    reg ref_clk = 0, meas_clk = 0, rst_n = 0, start = 0, run_meas = 1;
    reg [9:0] window = 64;
    reg [7:0] timeout = 16;
    wire busy, valid, stalled;
    wire [11:0] count;
    real tmeas = 4.0;
    integer errors = 0, k;
    real expect_c;
    mon_freq_meter dut (.ref_clk(ref_clk), .rst_n(rst_n), .start(start), .meas_clk(meas_clk), .window(window),
                        .timeout(timeout), .busy(busy), .valid(valid), .stalled(stalled), .count(count));
    always #2 ref_clk = ~ref_clk;
    always begin
        #(tmeas / 2);
        if (run_meas) meas_clk = ~meas_clk;
    end
    task measure(input real t, input integer n);
        begin
            tmeas = t; window = n;
            #(37.3 + 2.1 * k);                  // vary the phase between the clocks
            @(negedge ref_clk); start = 1; @(negedge ref_clk); start = 0;
            wait (valid); @(negedge ref_clk);
            expect_c = n * 4.0 / t;
            if (stalled || (count > expect_c + 1.0) || (count < expect_c - 1.0)) begin
                $display("FAIL T=%0.3f ns window %0d: count %0d expected %0.2f stalled %0d", t, n, count, expect_c, stalled);
                errors = errors + 1;
            end else $display("ok   T=%0.3f ns window %0d: count %0d expected %0.2f", t, n, count, expect_c);
        end
    endtask
    initial begin
        #10 rst_n = 1;
        for (k = 0; k < 4; k = k + 1) begin
            measure(4.0, 64);       // 250 MHz feedback, locked
            measure(3.47, 64);      // 2.31 GHz / 8
            measure(4.6, 64);       // 1.74 GHz / 8
            measure(0.5, 256);      // undivided 2 GHz
            measure(4.016, 512);    // 0.4 % slow
        end
        // stopped measured clock
        run_meas = 0;
        @(negedge ref_clk); start = 1; @(negedge ref_clk); start = 0;
        wait (valid); @(negedge ref_clk);
        if (!stalled || count != 0) begin $display("FAIL stopped clock: stalled %0d count %0d", stalled, count); errors = errors + 1; end
        else $display("ok   stopped clock flagged");
        run_meas = 1; k = 0;
        measure(4.0, 64);           // recovers
        if (errors) $fatal(1, "%0d failures", errors);
        $display("PASS");
        $finish;
    end
endmodule
