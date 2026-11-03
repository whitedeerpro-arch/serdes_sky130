// rx_offset_cal against a behavioural sampler model.  Per trial: random static offsets of the four
// samplers (uniform within +-RANGE_UV), comparator noise sigma NOISE_UV; a sampler decides 1 when
// noise > threshold, threshold = offset + LSB_UV * (code - 31.5) (a larger code raises it, as the DAC
// does); the samples reach the calibration through a LAT-word pipeline (readout latency).
// Pass: after done, every in-range lane has |threshold| <= LSB_UV (SAR + neighbour choice, any noise),
// lanes beyond the DAC range end at code 0 or 63 on the correct side.
// iverilog -g2012 -o tb tb_rx_offset_cal.sv ../rtl/rx_offset_cal.sv && vvp tb [+trials=200 +noise=500 +lsb=1840]
`timescale 1ns/1ps
module tb_rx_offset_cal;
    reg clk = 0, rst_n = 0, start = 0;
    wire [23:0] codes;
    wire busy, done;
    reg [31:0] phys;
    integer LAT = 5;
    integer trials = 200, noise = 500, lsb = 1840, range_uv = 60000;
    integer seed = 7;
    integer off [0:3];
    reg [31:0] pipe [0:15];
    integer i, k, l, t, thr, res, worst, fails, rounds;
    integer worst_sat;

    rx_offset_cal #(.NW(16), .SETTLE(8)) dut(.clk(clk), .rst_n(rst_n), .start(start), .phys(phys),
                                             .codes(codes), .busy(busy), .done(done));
    always #2 clk = ~clk;

    function integer code_of(input integer lane);
        code_of = (codes >> (6 * lane)) & 63;
    endfunction
    function integer thr_of(input integer lane);       // threshold in uV (x2 to keep the half LSB exact)
        thr_of = 2 * off[lane] + lsb * (2 * code_of(lane) - 63);
    endfunction

    // one word: 8 samples per lane, packed as rx_word_map / rx_offset_cal expect
    function [31:0] word();
        reg [7:0] s [0:3];
        integer a, b;
        begin
            for (a = 0; a < 4; a = a + 1)
                for (b = 0; b < 8; b = b + 1)
                    s[a][b] = (2 * $dist_normal(seed, 0, noise) > thr_of(a));
            word = 0;
            word[3:0] = s[0][3:0];   word[7:4] = s[0][7:4];        // a0 b0  <- d0
            word[19:16] = s[1][3:0]; word[23:20] = s[1][7:4];      // a1 b1  <- d1
            word[27:24] = s[2][3:0]; word[31:28] = s[2][7:4];      // be0 ae0 <- e0
            word[11:8] = s[3][3:0];  word[15:12] = s[3][7:4];      // be1 ae1 <- e1
        end
    endfunction

    always @(posedge clk) begin
        for (i = 15; i > 0; i = i - 1) pipe[i] <= pipe[i - 1];
        pipe[0] <= word();
    end
    always @* phys = pipe[LAT - 1];

    initial begin
        if ($value$plusargs("trials=%d", trials)) ;
        if ($value$plusargs("noise=%d", noise)) ;
        if ($value$plusargs("lsb=%d", lsb)) ;
        if ($value$plusargs("range=%d", range_uv)) ;
        for (i = 0; i < 16; i = i + 1) pipe[i] = 0;
        worst = 0; worst_sat = 0; fails = 0;
        #10 rst_n = 1;
        for (t = 0; t < trials; t = t + 1) begin
            for (l = 0; l < 4; l = l + 1) off[l] = $dist_uniform(seed, -range_uv, range_uv);
            @(negedge clk) start = 1;
            @(negedge clk) start = 0;
            rounds = 0;
            while (!done && rounds < 5000) begin @(negedge clk); rounds = rounds + 1; end
            if (!done) begin $display("FAIL trial %0d: no done", t); fails = fails + 1; end
            for (l = 0; l < 4; l = l + 1) begin
                thr = thr_of(l);                            // 2 x threshold
                res = (thr < 0) ? -thr : thr;
                if (2 * off[l] > 63 * lsb || 2 * off[l] < -63 * lsb) begin
                    // beyond range: code saturated on the correct side
                    if (!((2 * off[l] > 0 && code_of(l) == 0) || (2 * off[l] < 0 && code_of(l) == 63))) begin
                        $display("FAIL trial %0d lane %0d: offset %0d uV out of range, code %0d", t, l, off[l], code_of(l));
                        fails = fails + 1;
                    end
                    worst_sat = worst_sat + 1;
                end else begin
                    if (res > worst) worst = res;
                    if (res > 2 * lsb) begin
                        $display("FAIL trial %0d lane %0d: offset %0d uV code %0d residual %0d uV", t, l, off[l], code_of(l), thr / 2);
                        fails = fails + 1;
                    end
                end
            end
        end
        $display("rx_offset_cal: %0d trials x 4 lanes, noise %0d uV, LSB %0d uV, %0d word clocks per run: worst in-range |residual| %0d uV (%0.2f LSB), %0d saturated lanes, %0d failures",
                 trials, noise, lsb, rounds + 2, worst / 2, worst / (2.0 * lsb), worst_sat, fails);
        $display(fails == 0 ? "PASS" : "FAIL");
        $finish;
    end
endmodule
