`timescale 1ns/1ps
module tb_bbpd_window_vote;
    reg clk=0,rst_n=0,valid=0,prev=0;
    reg [15:0] data=0,edge_bits=0;
    wire vv;
    wire signed [5:0] vote;
    wire [4:0] transitions;
    integer cases=0;
    always #2 clk=~clk;
    bbpd_window_vote dut(clk,rst_n,valid,prev,data,edge_bits,vv,vote,transitions);
    task automatic check(input [15:0] dd,ee,input reg pp,input integer want,count);
        begin
            @(negedge clk);data=dd;edge_bits=ee;prev=pp;valid=1;
            @(posedge clk);#0.01;
            if(!vv || vote!=want || transitions!=count)$fatal(1,"vote expected %0d/%0d got %0d/%0d",want,count,vote,transitions);
            cases=cases+1;
        end
    endtask
    initial begin
        #1;rst_n=0;#4;rst_n=1;
        check(16'haaaa,16'haaaa,1,16,16); // all late, includes first boundary
        check(16'haaaa,16'h5555,1,-16,16); // all early
        check(16'haaaa,16'h00ff,1,0,16); // equal early/late votes
        check(16'h0000,16'hffff,0,0,0); // no data transition
        check(16'hffff,16'h0000,1,0,0);
        check(16'h0000,16'h0000,1,1,1); // previous-window transition only
        check(16'h0000,16'h0001,1,-1,1);
        @(negedge clk);valid=0;
        @(posedge clk);#0.01;if(vv)$fatal(1,"invalid bundle emitted vote");
        $display("PASS bbpd %0d directed cases + invalid bundle",cases);$finish;
    end
    initial begin #1000;$fatal(1,"timeout");end
endmodule
