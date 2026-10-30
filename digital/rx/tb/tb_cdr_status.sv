`timescale 1ns/1ps
module tb_cdr_status;
    reg clk=0,rst=1,enable=1,valid=1;
    reg signed[5:0]vote=0;reg[4:0]count=8;
    wire ready,step,advance,applied,done,locked,holdover,limited;
    wire signed[31:0]freq,debt;wire[5:0]code;wire[7:0]a,b,f;
    always #2 clk=~clk;
    cdr_phase_frequency filter(clk,rst,enable,valid,vote,count,ready,applied,done,step,advance,freq,debt,locked,holdover,limited);
    pi_step_commutator comm(clk,rst,step,advance,ready,code,a,b,f,applied,done);
    task automatic ticks(input integer n);
        integer i;begin for(i=0;i<n;i=i+1)begin @(posedge clk);#0.01;end end
    endtask
    initial begin
        #1;rst=0;#4;rst=1;
        ticks(600);if(!locked||holdover||limited)$fatal(1,"quality acquire");
        @(negedge clk);count=0;
        ticks(128);if(!locked||!holdover||freq!=0)$fatal(1,"short holdover");
        ticks(150);if(locked||!holdover)$fatal(1,"transition timeout");
        @(negedge clk);count=8;
        ticks(600);if(!locked||holdover)$fatal(1,"reacquire");
        @(negedge clk);vote=8;
        ticks(1200);if(!limited||locked||freq!=32768)$fatal(1,"range saturation");
        $display("PASS status acquire /512ns holdover /timeout /reacquire /range fault");$finish;
    end
    initial begin #20000;$fatal(1,"timeout");end
endmodule
