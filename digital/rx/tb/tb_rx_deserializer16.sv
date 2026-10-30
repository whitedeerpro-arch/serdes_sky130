`timescale 1ns/1ps
module tb_rx_deserializer16;
    reg clk=0,rst=1,valid=0,training=1;reg[1:0]pair=0;
    wire [15:0]word;wire wvalid,aligned;
    rx_deserializer16 dut(clk,rst,valid,training,pair,word,wvalid,aligned);
    always #0.25 clk=~clk;
    integer offset,i,j,ending,checks=0,per_case;
    reg[15:0]expected;
    function automatic [15:0] payload(input integer w);
        payload=(w*257)^16'h793d;
    endfunction
    function automatic reg source_bit(input integer n);
        reg[15:0]v;
        begin v=n<192 ? 16'hb5e3 : payload((n-192)/16);source_bit=(v>>(n%16))&1;end
    endfunction
    initial begin
        for(offset=0;offset<16;offset=offset+1)begin
            @(negedge clk);rst=0;valid=0;training=1;
            @(negedge clk);rst=1;per_case=0;
            for(i=offset;i<512;i=i+2)begin
                @(negedge clk);valid=1;training=i<192;pair={source_bit(i+1),source_bit(i)};
                @(posedge clk);#0.01;
                if(wvalid)begin
                    if(!aligned)$fatal(1,"word without alignment");
                    ending=((i+1)%16==15)?i+1:i;
                    if(ending%16!=15)$fatal(1,"boundary");
                    expected=payload((ending-192)/16);
                    if(word!==expected)$fatal(1,"offset%0d word mismatch",offset);
                    checks=checks+1;per_case=per_case+1;
                end
            end
            if(per_case!=20)$fatal(1,"offset%0d word count%0d",offset,per_case);
        end
        $display("PASS SIPO/training: all16 bit offsets, %0d payload words",checks);$finish;
    end
    initial begin #10000;$fatal(1,"timeout");end
endmodule
