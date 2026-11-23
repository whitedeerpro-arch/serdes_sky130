module tb_pll_startup_supervisor;
    timeunit 1ns;
    timeprecision 1ps;
    reg ref_clk=0, run_clock=1, rst_n=0, enable=0, start=0;
    reg bias_ready=0, pre_ref_ready=0, quality_valid=0;
    reg frequency_good=0, phase_good=0, range_fault=0, abort_async=0;
    wire precharge_en, pfd_rst_b, cp_en, locked, busy, fault;
    wire [2:0] state_id, fault_code;
    integer seen;
    pll_startup_supervisor #(
        .PRECHARGE_CYCLES(4), .GAP_CYCLES(2), .PFD_FLUSH_CYCLES(2),
        .GOOD_WINDOWS(3), .BAD_WINDOWS(2), .QUALITY_TIMEOUT_CYCLES(6),
        .WAIT_TIMEOUT_CYCLES(8), .ACQUIRE_TIMEOUT_CYCLES(24)
    ) dut (.*);
    always #2 begin
        if (run_clock) ref_clk=~ref_clk;
        else ref_clk=0;
    end
    task tick(input integer n);
        repeat(n) begin @(negedge ref_clk); #0.1; end
    endtask
    task wait_state(input [2:0] wanted);
        integer count;
        begin
            count=0;
            while (state_id!==wanted && count<100) begin tick(1); count=count+1; end
            if (state_id!==wanted) $fatal(1,"State wait timeout wanted=%0d got=%0d",wanted,state_id);
        end
    endtask
    task restart;
        begin start=1; tick(1); start=0; end
    endtask
    always @(negedge ref_clk) begin
        #0.05;
        if (precharge_en && cp_en) $fatal(1,"Precharge and CP overlap");
        if (cp_en && !pfd_rst_b) $fatal(1,"CP active with PFD in reset");
        if (locked && (!cp_en || precharge_en)) $fatal(1,"Unsafe locked outputs");
        if (fault && (cp_en || precharge_en || locked)) $fatal(1,"Fault did not clamp outputs");
    end
    initial begin
        $dumpfile("supervisor.vcd"); $dumpvars(0,tb_pll_startup_supervisor);
        tick(2); rst_n=1; enable=1; restart();
        tick(2);
        if (state_id!=1 || precharge_en) $fatal(1,"Started before readiness");
        bias_ready=1; pre_ref_ready=1; wait_state(2);
        seen=0; while(state_id==2) begin seen=seen+1; tick(1); end
        if(seen!=4) $fatal(1,"Precharge duration %0d",seen);
        seen=0; while(state_id==3) begin seen=seen+1; tick(1); end
        if(seen!=2) $fatal(1,"Break interval %0d",seen);
        seen=0; while(state_id==4) begin seen=seen+1; tick(1); end
        if(seen!=2 || !cp_en) $fatal(1,"PFD flush or CP handoff failed");
        quality_valid=1; frequency_good=1; phase_good=0; tick(5);
        if(locked) $fatal(1,"Frequency alone caused lock");
        phase_good=1; tick(2); if(locked) $fatal(1,"Locked before required windows");
        tick(1); if(!locked) $fatal(1,"No lock after required windows");
        phase_good=0; tick(1); if(!locked) $fatal(1,"Single bad window removed lock");
        tick(1); if(state_id!=5 || precharge_en || !cp_en) $fatal(1,"Loss did not preserve loop state");
        phase_good=1; tick(2);
        quality_valid=0; tick(7); quality_valid=1; tick(1);
        if(locked) $fatal(1,"Stale acquisition windows accumulated into lock");
        tick(2); if(!locked) $fatal(1,"Reacquire failed");
        quality_valid=0; tick(6); if(!fault || fault_code!=6) $fatal(1,"Stale quality was not rejected");
        restart(); wait_state(5); wait_state(7);
        if(fault_code!=4) $fatal(1,"Acquisition timeout absent");
        restart(); wait_state(5); range_fault=1; tick(1);
        if(!fault || fault_code!=3) $fatal(1,"Range fault absent");
        range_fault=0; restart(); wait_state(5); bias_ready=0; #0.1;
        if(cp_en) $fatal(1,"Readiness loss did not immediately clamp CP");
        tick(1); if(!fault || fault_code!=1) $fatal(1,"Bias fault absent");
        bias_ready=1; restart(); wait_state(5);
        quality_valid=1; phase_good=1; tick(3); if(!locked) $fatal(1,"Watchdog setup did not lock");
        run_clock=0; #3; abort_async=1; #0.1;
        if(cp_en || precharge_en || pfd_rst_b || locked) $fatal(1,"Stopped-reference abort clamp failed");
        run_clock=1; tick(4); if(!fault || fault_code!=5) $fatal(1,"Abort status not latched");
        abort_async=0; tick(4); restart(); wait_state(2); enable=0; #0.1;
        if(precharge_en || cp_en || locked) $fatal(1,"Disable did not cancel precharge");
        tick(1); if(state_id!=0) $fatal(1,"Disable did not return idle");
        enable=1; bias_ready=0; pre_ref_ready=0; restart(); wait_state(7);
        if(fault_code!=4) $fatal(1,"Readiness timeout absent");
        $display("PASS startup sequence, no overlap, quality qualification, lock loss, stale monitor, timeouts, range/bias faults and stopped-clock abort");
        $finish;
    end
    initial begin #20000; $fatal(1,"Global test timeout"); end
endmodule
