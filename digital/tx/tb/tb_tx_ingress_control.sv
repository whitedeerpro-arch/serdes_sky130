`timescale 1ns/1ps
module ingress_case #(parameter integer N = 1)(output reg done);
    reg clk = 1, rst_n = 1, enable = 0, good = 0, valid = 0;
    reg [15:0] data = 16'h1234;
    wire ready, cv, av, bv;
    wire [15:0] cd;
    integer checks = 0;
    integer i;
    tx_ingress_control #(.WARMUP_FALLS(N), .IDLE_WORD(16'hdead)) dut (
        .word_clk(clk), .rst_n(rst_n), .enable(enable), .clock_good(good),
        .in_valid(valid), .in_data(data), .word_ready(ready),
        .capture_data(cd), .capture_valid(cv), .a_valid(av), .b_valid(bv));
    task check;
        input condition;
        input [255:0] label_text;
        begin
            checks = checks + 1;
            if (condition !== 1'b1) begin
                $display("FAIL N=%0d %s at %0t ready=%b cv=%b cd=%h a=%b b=%b", N, label_text, $time, ready, cv, cd, av, bv);
                $fatal(1);
            end
        end
    endtask
    task fall; begin clk = 0; #1; end endtask
    task rise; begin clk = 1; #1; end endtask
    initial begin
        done = 0; rst_n = 0;
        #1; rst_n = 1; enable = 1; good = 1; valid = 1; #1;
        check(!ready && !cv && cd == 16'hdead && !av && !bv, "initial high no falling edge");
        for (i = 1; i <= N; i = i + 1) begin
            fall();
            check(ready == (i == N), "warmup falling edge");
            rise();
            check(ready == (i == N), "ready stable rising edge");
        end
        check(av && cv && cd == data, "first captured word");
        fall(); check(bv, "B samples A");
        valid = 0; data = 16'h5678; #1;
        check(!cv && cd == 16'hdead, "bubble selects idle immediately");
        rise(); check(!av && bv, "bubble A and prior B");
        fall(); check(!bv, "bubble drains B");
        valid = 1; data = 16'hbeef; #1;
        check(cv && cd == 16'hbeef, "data combinational no delay");
        rise(); check(av, "new A valid");
        enable = 0; #1; check(ready && cv, "disable waits for falling edge");
        fall(); check(!ready && bv && !cv && cd == 16'hdead, "disable preserves in flight B");
        rise(); check(!av && bv, "disable drains A first");
        enable = 1; good = 1;
        fall(); check(!bv && ready == (N == 1), "reenable starts warmup and drains B");
        rise(); check(av == (N == 1), "reenable first capture");
        for (i = 2; i <= N; i = i + 1) begin
            fall(); check(ready == (i == N), "reenable warmup");
            rise(); check(av == (i == N), "reenable capture timing");
        end
        good = 0; fall(); check(!ready && bv, "bad clock sampled and B drains");
        good = 1; #1; check(!ready, "stopped low cannot warm up");
        #5; check(!ready, "stopped clock retains ready state");
        rise(); check(!ready && !av, "restart rising does not warm up");
        for (i = 1; i <= N; i = i + 1) begin
            fall(); check(ready == (i == N), "restart warmup");
            rise();
        end
        fall(); check(bv, "valid before reset");
        rst_n = 0; #1; check(!ready && !av && !bv && !cv && cd == 16'hdead, "asynchronous reset");
        rst_n = 1; #1; check(!ready, "reset release no edge");
        for (i = 1; i <= N; i = i + 1) begin
            rise(); check(!ready, "reset restart rise");
            fall(); check(ready == (i == N), "reset restart fall");
        end
        $display("PASS WARMUP_FALLS=%0d checks=%0d", N, checks);
        done = 1;
    end
endmodule
module tb_tx_ingress_control;
    wire done1, done2;
    ingress_case #(.N(1)) one(done1);
    ingress_case #(.N(2)) two(done2);
    initial begin wait(done1 && done2); $display("PASS both parameter cases"); $finish; end
    initial begin #1000; $fatal(1, "timeout"); end
endmodule
