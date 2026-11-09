// Switching and disabled tracking must discard old filter output and count.
module tb_pll_coarse_persist;
    timeunit 1ns; timeprecision 1ps;
    reg clk=0, rst_n=0, search=0, track_en=0, hi_async=0, lo_async=0;
    reg [1:0] tclass=0;
    reg [3:0] lo_run=5, hi_run=3;
    reg [11:0] stop_code=0;
    reg [2:0] stop_sel=3'b111;
    wire [3:0] vco_code, lo_code, hi_code;
    wire busy, done, fast_end, slow_end;
    wire [7:0] switches;
    integer before_count, i;
    pll_coarse_ctrl #(.SETTLE_CYCLES(1), .SAMPLE_DIV(1), .PERSIST(8), .HOLD_CYCLES(1)) dut
        (.ref_clk(clk), .*);
    always #2 clk=~clk;
    initial begin
        #10 rst_n=1;
        @(negedge clk); search=1;
        @(negedge clk); search=0;
        wait(done); @(negedge clk); track_en=1;
        repeat(4) @(negedge clk);
        hi_async=1;
        wait(switches==1); @(negedge clk); hi_async=0;
        repeat(16) @(negedge clk);
        if(switches!=1 || vco_code!=14) $fatal(1,"stale switch repeated: switches=%0d code=%0d",switches,vco_code);
        // Accumulate most of a high run, disable and remove it. After the sync
        // pipeline settles, re-enable and require a fresh eight sample run.
        hi_async=1;
        wait(dut.hi); repeat(5) @(negedge clk);
        track_en=0; hi_async=0; repeat(5) @(negedge clk);
        before_count=switches; track_en=1;
        repeat(12) @(negedge clk);
        if(switches!=before_count) $fatal(1,"stale disabled-track sample switched");
        track_en=0; hi_async=1; repeat(20) @(negedge clk);
        hi_async=0; repeat(5) @(negedge clk); track_en=1;
        repeat(12) @(negedge clk);
        if(switches!=before_count) $fatal(1,"disabled-track confirmed event switched");
        hi_async=1; wait(dut.hi);
        // Sampling occurs at rising edges, so only count samples after sync is high.
        for(i=0;i<7;i=i+1) begin @(negedge clk); if(switches!=before_count) $fatal(1,"switched before eight fresh samples"); end
        wait(switches==before_count+1);
        @(negedge clk); hi_async=0; repeat(16) @(negedge clk);
        if(switches!=before_count+1) $fatal(1,"fresh event repeated");
        $display("PASS"); $finish;
    end
    initial begin #10000; $fatal(1,"timeout"); end
endmodule
