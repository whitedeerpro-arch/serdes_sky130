module tb_pll_startup_default_timing;
    timeunit 1ns;
    timeprecision 1ps;
    reg ref_clk=0, rst_n=0, enable=0, start=0;
    reg bias_ready=1, pre_ref_ready=1, quality_valid=0;
    reg frequency_good=0, phase_good=0, range_fault=0, abort_async=0;
    wire precharge_en, pfd_rst_b, cp_en, locked, busy, fault;
    wire [2:0] state_id, fault_code;
    realtime mark;
    pll_startup_supervisor dut(.*);
    always #2 ref_clk=~ref_clk;
    initial begin
        #5; rst_n=1; enable=1; start=1;
        @(negedge ref_clk); start=0;
        @(posedge precharge_en); mark=$realtime;
        @(negedge precharge_en);
        if($realtime-mark!=512.0) $fatal(1,"Default precharge duration differs from SPICE template");
        mark=$realtime; @(posedge pfd_rst_b);
        if($realtime-mark!=8.0 || cp_en) $fatal(1,"Default dead time mismatch");
        mark=$realtime; @(posedge cp_en);
        if($realtime-mark!=8.0 || precharge_en || locked) $fatal(1,"Default flush mismatch");
        $display("PASS default 250MHz timing: precharge512ns, gap8ns, PFD flush8ns");
        $finish;
    end
    initial begin #2000; $fatal(1,"Default timing test timeout"); end
endmodule
