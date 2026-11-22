`timescale 1ns/1ps
// Verification testbench for timing-closed v2 6-stage pipelined bbpd_window_vote.
module tb_bbpd_window_vote_v2;
    reg clk = 0, rst_n = 0, valid = 0, prev = 0;
    reg [15:0] data = 0, edge_bits = 0;
    wire vv;
    wire signed [5:0] vote;
    wire [4:0] transitions;
    integer cases = 0;

    always #2 clk = ~clk;

    bbpd_window_vote dut (
        .ctrl_clk(clk), .rst_n(rst_n), .bundle_valid(valid),
        .previous_data(prev), .data_samples(data), .edge_samples(edge_bits),
        .vote_valid(vv), .vote_sum(vote), .transition_count(transitions)
    );

    function automatic integer ref_vote(input [15:0] dd, input [15:0] ee, input reg pp);
        integer i, s;
        reg b;
        begin
            s = 0; b = pp;
            for (i = 0; i < 16; i = i + 1) begin
                if (b != dd[i]) s = s + ((ee[i] == dd[i]) ? 1 : -1);
                b = dd[i];
            end
            ref_vote = s;
        end
    endfunction

    function automatic integer ref_cnt(input [15:0] dd, input reg pp);
        integer i, c;
        reg b;
        begin
            c = 0; b = pp;
            for (i = 0; i < 16; i = i + 1) begin
                if (b != dd[i]) c = c + 1;
                b = dd[i];
            end
            ref_cnt = c;
        end
    endfunction

    task automatic check_6cyc(input [15:0] dd, input [15:0] ee, input reg pp, input integer want, input integer count);
        begin
            @(negedge clk);
            data = dd; edge_bits = ee; prev = pp; valid = 1;
            @(posedge clk); // Stage 0 captures
            @(negedge clk);
            valid = 0;
            @(posedge clk); // Stage 0b
            @(posedge clk); // Stage 1
            @(posedge clk); // Stage 2
            @(posedge clk); // Stage 3
            @(posedge clk); // Stage 4 outputs
            #0.01;
            if (!vv || vote != want || transitions != count)
                $fatal(1, "FAIL vote expected %0d/%0d got %0d/%0d", want, count, vote, transitions);
            cases = cases + 1;
        end
    endtask

    reg [15:0] pipe_d [0:5], pipe_e [0:5];
    reg        pipe_p [0:5], pipe_v [0:5];
    reg [31:0] lfsr = 32'h13579bdf;
    integer k, j, exp_v, exp_c;

    initial begin
        #1; rst_n = 0; #4; rst_n = 1;
        check_6cyc(16'haaaa, 16'haaaa, 1'b1,  16, 16);
        check_6cyc(16'haaaa, 16'h5555, 1'b1, -16, 16);
        check_6cyc(16'haaaa, 16'h00ff, 1'b1,   0, 16);
        check_6cyc(16'h0000, 16'hffff, 1'b0,   0,  0);
        check_6cyc(16'hffff, 16'h0000, 1'b1,   0,  0);
        check_6cyc(16'h0000, 16'h0000, 1'b1,   1,  1);
        check_6cyc(16'h0000, 16'h0001, 1'b1,  -1,  1);
        @(negedge clk); valid = 0;
        @(posedge clk); #0.01;
        if (vv) $fatal(1, "FAIL invalid bundle emitted vote");

        // 256 back-to-back pseudo-random bundles at full throughput (6-cycle latency)
        for (j = 0; j < 6; j = j + 1) pipe_v[j] = 0;
        for (k = 0; k < 256; k = k + 1) begin
            @(negedge clk);
            lfsr = {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
            data      = lfsr[15:0];
            edge_bits = lfsr[31:16];
            prev      = lfsr[7];
            valid     = (k % 7 != 0);
            @(posedge clk); #0.01;
            if (pipe_v[4]) begin
                exp_v = ref_vote(pipe_d[4], pipe_e[4], pipe_p[4]);
                exp_c = ref_cnt(pipe_d[4], pipe_p[4]);
                if (!vv || vote !== exp_v || transitions !== exp_c)
                    $fatal(1, "FAIL stream k=%0d exp=%0d/%0d got=%0d/%0d", k, exp_v, exp_c, vote, transitions);
                cases = cases + 1;
            end else if (vv) begin
                $fatal(1, "FAIL spurious vote_valid at k=%0d", k);
            end
            for (j = 5; j > 0; j = j - 1) begin
                pipe_d[j] = pipe_d[j-1]; pipe_e[j] = pipe_e[j-1];
                pipe_p[j] = pipe_p[j-1]; pipe_v[j] = pipe_v[j-1];
            end
            pipe_d[0] = data; pipe_e[0] = edge_bits; pipe_p[0] = prev; pipe_v[0] = valid;
        end

        $display("PASS bbpd_window_vote_v2 %0d directed+streaming cases", cases);
        $finish;
    end

    initial begin
        #5000;
        $fatal(1, "timeout");
    end
endmodule
