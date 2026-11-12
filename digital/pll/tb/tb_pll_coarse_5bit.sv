// Abstract comparator oracle: checks code arithmetic and ladder independence,
// not the physical r6 frequency map, settling, or PVT qualification.
module tb_pll_coarse_5bit;
    timeunit 1ns;
    timeprecision 1ps;
    reg ref_clk=0, rst_n=0, search=0, track_en=0;
    reg [1:0] tclass=1;
    reg [3:0] lo_run=5, hi_run=10;
    reg [11:0] stop_code={4'd3,4'd14,4'd9};
    reg [2:0] stop_sel=3'b111;
    integer target=0;
    reg back_request=0, manual=0, manual_hi=0, manual_lo=0;
    wire hi_async=manual ? manual_hi : (vco_code > target);
    wire lo_async=manual ? manual_lo : (back_request && hi_code==hi_run);
    wire [4:0] vco_code;
    wire [3:0] lo_code, hi_code;
    wire busy, done, fast_end, slow_end;
    wire [7:0] switches;
    pll_coarse_ctrl #(.CODE_BITS(5), .SETTLE_CYCLES(8), .SAMPLE_DIV(1), .PERSIST(2), .HOLD_CYCLES(4)) dut (.*);
    always #2 ref_clk=~ref_clk;

    task find_code(input integer wanted, input bit back_one);
        integer n, expected_code;
        begin
            track_en=0; manual=0; target=wanted; back_request=back_one;
            @(negedge ref_clk) search=1;
            @(negedge ref_clk) search=0;
            if (!busy || vco_code!=31 || hi_code!=14 || lo_code!=lo_run)
                $fatal(1,"FAIL search start: code=%0d busy=%0d ladders=%0d/%0d",vco_code,busy,lo_code,hi_code);
            n=0;
            while (!done && n<350) begin @(negedge ref_clk); n=n+1; end
            expected_code=wanted+((back_one && wanted<31) ? 1 : 0);
            if (!done || busy || vco_code!=expected_code || lo_code!=lo_run || hi_code!=hi_run)
                $fatal(1,"FAIL target=%0d back=%0d got=%0d done=%0d ladders=%0d/%0d",wanted,back_one,vco_code,done,lo_code,hi_code);
            back_request=0;
        end
    endtask

    task run_step(input integer start_code, input bit go_slower, input integer expected_code);
        integer n;
        reg [7:0] before_switches;
        begin
            find_code(start_code,0);
            manual=1; manual_hi=!go_slower; manual_lo=go_slower;
            before_switches=switches;
            track_en=1; n=0;
            while (vco_code==start_code && n<40) begin @(negedge ref_clk); n=n+1; end
            track_en=0; manual_hi=0; manual_lo=0;
            repeat (12) @(negedge ref_clk);
            if (vco_code!=expected_code || switches!=before_switches+1)
                $fatal(1,"FAIL runtime crossing %0d -> %0d (wanted %0d), switches=%0d",start_code,vco_code,expected_code,switches);
        end
    endtask

    integer k;
    initial begin
        repeat (3) @(negedge ref_clk);
        rst_n=1;
        if (vco_code!=31) $fatal(1,"FAIL reset maximum");
        for (k=0;k<32;k=k+1) find_code(k,0);
        // CHECK/BACK must cross bit 4 and clamp at the real slow end.
        find_code(15,1); find_code(30,1); find_code(31,1);
        run_step(15,1,16); run_step(16,0,15);
        find_code(31,0);
        manual=1; manual_lo=1; manual_hi=0; track_en=1;
        repeat (40) @(negedge ref_clk);
        if (!slow_end || vco_code!=31) $fatal(1,"FAIL slow end wraps/truncates");
        track_en=0; manual_lo=0;
        find_code(0,0);
        manual=1; manual_hi=1; manual_lo=0; track_en=1;
        repeat (40) @(negedge ref_clk);
        if (!fast_end || vco_code!=0) $fatal(1,"FAIL fast end wraps");
        $display("PASS 5-bit all 32 search results, CHECK/BACK, 15/16 crossings and endpoints");
        $finish;
    end
endmodule
