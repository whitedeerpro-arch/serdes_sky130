// mon_persist: chatter shorter than N samples never moves q; a sustained change moves it after exactly N.
module tb_mon_persist;
    timeunit 1ns;
    timeprecision 1ps;
    reg clk = 0, rst_n = 0, en = 0, d = 0;
    wire q;
    integer i, errors = 0, changed_at;
    mon_persist #(.N(5)) dut (.clk(clk), .rst_n(rst_n), .en(en), .d(d), .q(q));
    always #2 clk = ~clk;
    task strobe(input v);
        begin @(negedge clk); d = v; en = 1; @(negedge clk); en = 0; end
    endtask
    initial begin
        #5 rst_n = 1;
        // chatter: runs of 1..4 ones between zeros
        for (i = 1; i < 5; i = i + 1) begin
            repeat (i) strobe(1);
            strobe(0);
            if (q) begin $display("FAIL q rose after a run of %0d", i); errors = errors + 1; end
        end
        // sustained
        changed_at = -1;
        for (i = 1; i <= 8; i = i + 1) begin strobe(1); if (q && changed_at < 0) changed_at = i; end
        if (changed_at != 5) begin $display("FAIL rose after %0d samples, expected 5", changed_at); errors = errors + 1; end
        changed_at = -1;
        for (i = 1; i <= 8; i = i + 1) begin strobe(0); if (!q && changed_at < 0) changed_at = i; end
        if (changed_at != 5) begin $display("FAIL fell after %0d samples, expected 5", changed_at); errors = errors + 1; end
        if (errors) $fatal(1, "%0d failures", errors);
        $display("PASS");
        $finish;
    end
endmodule
