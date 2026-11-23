// Worst-length abstract search: code 31 -> 0 at the default 512-cycle settle.
// A second instance retains the old timeout to demonstrate the failure boundary.
// No analog transfer map, capture dynamics, or physical r6 qualification implied.
module tb_pll_control_5bit;
    timeunit 1ns;
    timeprecision 1ps;
    reg ref_clk=0, rst_n=0, enable=0, start=0;
    wire [4:0] vco_code, old_code;
    wire locked, fault, coarse_busy, coarse_done, old_locked, old_fault;
    wire [2:0] fault_code, old_fault_code, state_id;
    integer searches=0, cycles=0, acquire_cycles=0;
    pll_control_top #(.CODE_BITS(5)) dut (
        .ref_clk(ref_clk),.rst_n(rst_n),.enable(enable),.start(start),.abort_async(1'b0),
        .bias_ready_async(1'b1),.pre_ref_ready_async(1'b1),.tclass(2'd1),
        .hi_async(vco_code!=0),.lo_async(1'b0),.pw_late_async(1'b0),
        .lo_run(4'd5),.hi_run(4'd10),.stop_code(12'hEEE),.stop_sel(3'b111),
        .locked(locked),.fault(fault),.fault_code(fault_code),.state_id(state_id),
        .vco_code(vco_code),.coarse_busy(coarse_busy),.coarse_done(coarse_done)
    );
    pll_control_top #(.CODE_BITS(5),.ACQ_TIMEOUT_CYCLES(16384)) old_timeout (
        .ref_clk(ref_clk),.rst_n(rst_n),.enable(enable),.start(start),.abort_async(1'b0),
        .bias_ready_async(1'b1),.pre_ref_ready_async(1'b1),.tclass(2'd1),
        .hi_async(old_code!=0),.lo_async(1'b0),.pw_late_async(1'b0),
        .lo_run(4'd5),.hi_run(4'd10),.stop_code(12'hEEE),.stop_sel(3'b111),
        .locked(old_locked),.fault(old_fault),.fault_code(old_fault_code),.vco_code(old_code)
    );
    always #2 ref_clk=~ref_clk;
    always @(posedge dut.search_pulse) searches=searches+1;
    always @(negedge ref_clk) begin
        if (state_id==5) acquire_cycles=acquire_cycles+1;
        if (coarse_busy && locked) $fatal(1,"FAIL premature lock during search");
        if (old_locked) $fatal(1,"FAIL insufficient timeout unexpectedly locks");
    end
    initial begin
        repeat (4) @(negedge ref_clk);
        rst_n=1; enable=1;
        repeat (5) @(negedge ref_clk);
        start=1; @(negedge ref_clk) start=0;
        while (!locked && !fault && cycles<33000) begin @(negedge ref_clk); cycles=cycles+1; end
        if (!locked || fault || !coarse_done || vco_code!=0 || searches!=1)
            $fatal(1,"FAIL lock=%0d fault=%0d/%0d done=%0d code=%0d searches=%0d",locked,fault,fault_code,coarse_done,vco_code,searches);
        if (acquire_cycles<=16384 || acquire_cycles>=32768)
            $fatal(1,"FAIL worst search not exercised: %0d",acquire_cycles);
        if (!old_fault || old_fault_code!=4) $fatal(1,"FAIL old timeout must end in FAULT 4");
        repeat (256) @(negedge ref_clk);
        if (!locked || searches!=1) $fatal(1,"FAIL lock retention or repeated search");
        $display("PASS 5-bit code31->0 locks after %0d ACQUIRE cycles; old 16384 timeout gives FAULT 4",acquire_cycles);
        $finish;
    end
endmodule
