`timescale 1ns/1ps
// Verification testbench for timing-closed v2 tx_ingress_control (full posedge pipeline).
module ingress_case_v2 #(parameter integer N = 1) (output reg done);
    reg clk = 0, rst_n = 1, enable = 0, good = 0, valid = 0;
    reg [15:0] data = 16'h1234;
    wire ready, cv, av, bv;
    wire [15:0] cd;
    integer checks = 0;
    integer i;

    tx_ingress_control #(.WARMUP_FALLS(N), .IDLE_WORD(16'hdead)) dut (
        .word_clk(clk), .rst_n(rst_n), .enable(enable), .clock_good(good),
        .in_valid(valid), .in_data(data), .word_ready(ready),
        .capture_data(cd), .capture_valid(cv), .a_valid(av), .b_valid(bv)
    );

    task check;
        input condition;
        input [255:0] label_text;
        begin
            checks = checks + 1;
            if (condition !== 1'b1) begin
                $display("FAIL N=%0d %s at %0t ready=%b cv=%b cd=%h a=%b b=%b",
                         N, label_text, $time, ready, cv, cd, av, bv);
                $fatal(1);
            end
        end
    endtask

    task tick;
        begin
            #1 clk = 1;
            #1 clk = 0;
        end
    endtask

    initial begin
        done = 0;
        rst_n = 0;
        #1;
        check(!ready && !cv && cd == 16'hdead && !av && !bv, "async reset idle");
        rst_n = 1; enable = 1; good = 1; valid = 1; data = 16'h1234; #1;
        check(!ready && !cv && cd == 16'hdead && !av && !bv, "post-reset before edge");

        // Warmup for N posedges
        for (i = 1; i <= N; i = i + 1) begin
            tick();
            check(ready == (i == N), "warmup edge");
            check(!cv && cd == 16'hdead && !av && !bv, "no capture during warmup");
        end

        // First captured word (1-cycle registered capture)
        tick();
        check(ready && cv && cd == 16'h1234 && !av && !bv, "first registered capture");

        // Second word + A valid
        data = 16'h5678;
        tick();
        check(ready && cv && cd == 16'h5678 && av && !bv, "second capture + A valid");

        // Bubble: valid=0 -> idle word on capture, A and B drain
        valid = 0; data = 16'h9abc;
        tick();
        check(ready && !cv && cd == 16'hdead && av && bv, "bubble captures idle, A+B valid");
        tick();
        check(ready && !cv && cd == 16'hdead && !av && bv, "bubble drains A, B still valid");
        tick();
        check(ready && !cv && cd == 16'hdead && !av && !bv, "bubble drains B");

        // Resume valid
        valid = 1; data = 16'hbeef;
        tick();
        check(ready && cv && cd == 16'hbeef && !av && !bv, "resume capture");

        // Disable while in-flight: ready drops on next posedge, in-flight drains cleanly
        enable = 0; data = 16'hcafe;
        tick();
        check(!ready && cv && cd == 16'hcafe && av && !bv, "disable captures last ready word");
        tick();
        check(!ready && !cv && cd == 16'hdead && av && bv, "disable drains A and B");
        tick();
        check(!ready && !cv && cd == 16'hdead && !av && bv, "disable drains B");

        // Re-enable restarts full warmup
        enable = 1; good = 1; valid = 1; data = 16'h4321;
        for (i = 1; i <= N; i = i + 1) begin
            tick();
            check(ready == (i == N), "reenable warmup");
        end
        tick();
        check(ready && cv && cd == 16'h4321, "reenable first capture");

        // Bad clock drops ready and prevents warmup until restored
        good = 0;
        tick();
        check(!ready, "clock_good=0 drops ready");
        good = 1;
        #5;
        check(!ready, "stopped clock cannot warm up");
        for (i = 1; i <= N; i = i + 1) begin
            tick();
            check(ready == (i == N), "restart warmup after clock_good");
        end
        tick();
        check(cv && cd == 16'h4321, "post-clock_good capture");
        tick();
        check(av, "post-clock_good A valid");
        tick();
        check(bv, "post-clock_good B valid");

        // Async reset clears everything immediately without a clock edge
        rst_n = 0; #1;
        check(!ready && !cv && cd == 16'hdead && !av && !bv, "async reset clears in-flight");
        rst_n = 1; #1;
        check(!ready && !cv && cd == 16'hdead, "reset release stays idle");
        for (i = 1; i <= N; i = i + 1) begin
            tick();
            check(ready == (i == N), "post-reset warmup");
        end

        $display("PASS tx_ingress_control_v2 WARMUP_FALLS=%0d checks=%0d", N, checks);
        done = 1;
    end
endmodule

module tb_tx_ingress_control_v2;
    wire done1, done2;
    ingress_case_v2 #(.N(1)) one(done1);
    ingress_case_v2 #(.N(2)) two(done2);
    initial begin
        wait (done1 && done2);
        $display("PASS tx_ingress_control_v2 both parameter cases");
        $finish;
    end
    initial begin
        #1000;
        $fatal(1, "timeout");
    end
endmodule
