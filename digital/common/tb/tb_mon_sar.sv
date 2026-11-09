// mon_sar: behavioural comparator with thresholds 0.5 + 0.1 * code and a 30 ns response; every quantity from
// below the range to above it gives the largest code at or below it and the under / over flags.
module tb_mon_sar;
    timeunit 1ns;
    timeprecision 1ps;
    reg clk = 0, rst_n = 0, start = 0;
    wire [3:0] code;
    wire busy, valid, under, over;
    real x;
    reg cmp_async = 0;
    integer i, expect_c, errors = 0;
    mon_sar #(.W(4), .SW(8)) dut (.clk(clk), .rst_n(rst_n), .start(start), .settle(8'd12), .cmp_async(cmp_async),
                                  .code(code), .busy(busy), .valid(valid), .under(under), .over(over));
    always #2 clk = ~clk;
    always @(code or x) cmp_async <= #30 (x >= 0.5 + 0.1 * code);
    initial begin
        #5 rst_n = 1;
        for (i = 0; i < 40; i = i + 1) begin
            x = 0.37 + 0.0453 * i;
            #50;
            @(negedge clk); start = 1; @(negedge clk); start = 0;
            wait (valid); @(negedge clk);
            expect_c = (x < 0.5) ? 0 : ((x >= 2.0) ? 15 : $rtoi((x - 0.5) / 0.1));
            if (code != expect_c || under != (x < 0.5) || over != (x >= 2.0)) begin
                $display("FAIL x=%0.4f code %0d expected %0d under %0d over %0d", x, code, expect_c, under, over);
                errors = errors + 1;
            end
        end
        if (errors) $fatal(1, "%0d failures", errors);
        $display("PASS (40 quantities)");
        $finish;
    end
endmodule
