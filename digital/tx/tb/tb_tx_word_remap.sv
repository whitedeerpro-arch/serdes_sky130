`timescale 1ns/1ps
// Checks tx_word_remap against the serializer permutations measured by SPICE
// (data/serializer_state_permutations.hex, exported by clock_states/run.py table):
// remap followed by the measured permutation must restore the original order.
module tb_tx_word_remap;
    reg clk=0,rst_n=0;reg[2:0]state=0;reg[15:0]data=0;
    wire[15:0]out;
    tx_word_remap dut(clk,rst_n,state,data,out);
    always #2 clk=~clk;
    reg[3:0]perm[0:127];
    reg[15:0]sent;
    integer s,n,j,checks=0;
    initial begin
        $readmemh("digital/tx/tb/data/serializer_state_permutations.hex",perm);
        #5 rst_n=1;
        for(s=0;s<8;s=s+1)begin
            state=s;
            for(n=0;n<64;n=n+1)begin
                @(negedge clk);data=$random;
                @(posedge clk);#0.1;
                for(j=0;j<16;j=j+1)sent[j]=out[perm[16*s+j]];   // serializer slot j
                if(sent!==data)$fatal(1,"state %0d word %h sent as %h",s,data,sent);
                checks=checks+1;
            end
        end
        $display("PASS tx_word_remap: 8 measured states, %0d words restored",checks);$finish;
    end
endmodule
