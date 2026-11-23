`timescale 1ns/1ps
module tb_rx_word_host_path;
    reg word_clk=0,host_clk=0,arst_n=0,training_enable=1,host_ready=1;
    reg [31:0] phys=0;
    wire [15:0] host_data;
    wire host_valid,word_online,host_online,aligned,host_error;
    wire [3:0] offset;
    rx_word_host_path #(.ADDR_BITS(4)) dut (.*);
    always #2 word_clk=~word_clk;
    initial begin #0.7; forever #1.7 host_clk=~host_clk; end
    localparam integer NTRAIN=12;
    integer P,J,k,n,got,expect_m,total_checked=0;
    reg checking=0,seen_payload=0,stalled=0;
    reg [15:0] held;
    function automatic [15:0] payload(input integer m);
        payload=(m*257)^16'h793d;
    endfunction
    function automatic reg sbit(input integer x);
        reg [15:0] v;
        begin v=(x/16)<NTRAIN ? 16'hb5e3 : payload(x/16-NTRAIN); sbit=(v>>(x%16))&1; end
    endfunction
    task automatic drive(input integer s);
        begin
            for(k=0;k<4;k=k+1) begin
                phys[0*4+k]=sbit(s+12-4*k); phys[2*4+k]=sbit(s+12-4*k);
                phys[5*4+k]=sbit(s+13-4*k); phys[7*4+k]=sbit(s+13-4*k);
                phys[1*4+k]=sbit(s+14-4*k); phys[3*4+k]=sbit(s+14-4*k);
                phys[4*4+k]=sbit(s+15-4*k); phys[6*4+k]=sbit(s+15-4*k);
            end
        end
    endtask
    always @(posedge host_clk or negedge arst_n) begin
        if (!arst_n) stalled<=0;
        else begin
            if(stalled && (!host_valid || host_data!==held)) $fatal(1,"stalled output changed");
            stalled<=host_valid && !host_ready;
            held<=host_data;
        end
    end
    always @(posedge host_clk) if(arst_n && host_valid && host_ready && checking) begin
        if (!seen_payload && host_data===16'hb5e3) begin end
        else begin
            seen_payload=1;
            if(host_data!==payload(expect_m)) $fatal(1,"P%0d got %h expected %h index %0d",P,host_data,payload(expect_m),expect_m);
            expect_m=expect_m+1;got=got+1;
        end
    end
    task automatic reset_epoch;
        begin
            @(negedge word_clk); arst_n=0; training_enable=1; host_ready=0;checking=0;
            repeat(6) @(negedge word_clk); arst_n=1;
            wait(word_online && host_online);
            @(negedge word_clk); got=0;expect_m=0;seen_payload=0;
        end
    endtask
    task automatic run_words(input integer phase,input integer count);
        begin
            for(J=0;J<count;J=J+1) begin
                @(negedge word_clk);n=16+phase+16*J;drive(n);training_enable=(J<NTRAIN-1);
            end
        end
    endtask
    initial begin
        #0.1 arst_n=1;#0.1 arst_n=0;
        for(P=0;P<16;P=P+1) begin
            reset_epoch;host_ready=1;checking=1;run_words(P,42);
            if(!aligned || offset!==((16-P)%16) || got<20 || host_error) $fatal(1,"offset %0d got=%0d off=%0d error=%b",P,got,offset,host_error);
            $display("OFFSET %0d payload_prefix=%0d",P,got); total_checked=total_checked+got;
            checking=0;
        end
        if(total_checked<320) $fatal(1,"insufficient prefix coverage");
        $display("OFFSETS_TOTAL %0d",total_checked);
        // Stall the host while payload arrives; accepted words persist until capacity, then report loss.
        P=3;reset_epoch;host_ready=0;run_words(P,45);
        repeat(8) @(negedge host_clk);
        if(!host_error || !host_valid) $fatal(1,"missing full/overflow error");
        // Flush unread words with common reset, then check fresh stream against payload(0).
        reset_epoch;host_ready=1;checking=1;run_words(P,38);
        if(host_error || got<15) $fatal(1,"fresh epoch after reset failed");
        checking=0;
        // Re-training after payload must report fault and not append a second sequence.
        @(negedge word_clk);host_ready=0;training_enable=1;
        repeat(10) @(negedge word_clk);
        repeat(6) @(negedge host_clk);
        if(!host_error) $fatal(1,"missing retraining fault");
        host_ready=1;repeat(80) @(negedge host_clk);
        if(host_valid) $fatal(1,"faulted epoch appended retraining words");
        // Retrain on first pending output boundary: error even before prior FIFO acceptance.
        reset_epoch;host_ready=0;
        run_words(0,NTRAIN-1);
        @(negedge word_clk); drive(16+16*(NTRAIN-1)); training_enable=0;
        wait(dut.u_align.word_valid); @(negedge word_clk); training_enable=1;
        repeat(12) @(negedge word_clk);repeat(6) @(negedge host_clk);
        if(!host_error) $fatal(1,"pending first valid lost without epoch fault");
        $display("PASS host path: 16 offsets, overflow, reset, retrain and pending boundary");$finish;
    end
    initial begin #100000; $fatal(1,"timeout");end
endmodule
