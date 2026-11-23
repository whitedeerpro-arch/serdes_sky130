`timescale 1ns/1ps
module preprocess_case #(parameter integer N=1)(output reg done);
    reg clk=1, rst_n=1, enable=0, good=0, mv=0, valid=0;
    reg [2:0] state=0;
    reg [15:0] data=0;
    wire ready, cv, av, bv;
    wire [15:0] cd;
    wire [2:0] active;
    reg [3:0] perm [0:127];
    reg [15:0] sent;
    integer checks=0, s, i, j, n;
    tx_ingress_preprocessor #(.IDLE_WORD(16'hdead), .WARMUP_FALLS(N)) dut (
        .word_clk(clk), .rst_n(rst_n), .enable(enable), .clock_good(good),
        .mapping_valid(mv), .mapping_state(state), .in_valid(valid), .in_data(data),
        .word_ready(ready), .capture_valid(cv), .capture_data(cd),
        .a_valid(av), .b_valid(bv), .active_mapping_state(active));
    task check;
        input cond; input [255:0] label_text;
        begin checks=checks+1; if (cond !== 1'b1) begin
            $display("FAIL N=%0d %s time=%0t ready=%b cv=%b A=%b B=%b active=%0d", N,label_text,$time,ready,cv,av,bv,active);
            $fatal(1);
        end end
    endtask
    task fall; begin clk=0; #1; end endtask
    task rise; begin clk=1; #1; end endtask
    task check_mapping;
        input integer map_state;
        begin
            for (j=0;j<16;j=j+1) sent[j]=cd[perm[16*map_state+j]];
            check(cv && sent === data, "measured permutation oracle");
        end
    endtask
    initial begin
        done=0; $readmemh("digital/tx/tb/data/serializer_state_permutations.hex",perm);
        rst_n=0; #1; check(!ready && !av && !bv && active==0 && cd==16'hdead, "async reset");
        rst_n=1; enable=1; good=1; mv=1; valid=1;
        for (s=0;s<8;s=s+1) begin
            state=s; data=16'h965a ^ (s * 16'h1111);
            for (i=1;i<=N;i=i+1) begin
                fall(); check(active==s && ready==(i==N), "new state during warmup");
                if (i==N) check_mapping(s);
                rise(); check(av==(i==N), "first capture timing");
            end
            for(n=0;n<16;n=n+1) begin
                data=16'h0001 << n; #1; check_mapping(s);
            end
            data=16'h5aa5; state=(s+1)%8; #1;
            check(active==s, "state frozen while ready"); check_mapping(s);
            fall(); check(bv, "B valid before disable");
            rise(); check(av, "A valid before disable");
            mv=0; #1; check(ready && cv, "loss sampled on fall");
            fall(); check(!ready && bv && !cv && cd==16'hdead, "loss preserves B and inserts idle");
            rise(); check(!av && bv, "A drains before B");
            mv=1;
            // Next iteration's first fall drains B and begins new warmup.
        end
        fall(); check(!bv, "B drained");
        rst_n=0; #1; check(!ready && !av && !bv && active==0, "async reset after activity");
        $display("PASS preprocessor WARMUP_FALLS=%0d checks=%0d",N,checks);
        done=1;
    end
endmodule
module tb_tx_ingress_preprocessor;
    wire d1,d2;
    preprocess_case #(.N(1)) one(d1);
    preprocess_case #(.N(2)) two(d2);
    initial begin wait(d1 && d2); $display("PASS both warmup configurations"); $finish; end
    initial begin #10000; $fatal(1,"timeout"); end
endmodule
