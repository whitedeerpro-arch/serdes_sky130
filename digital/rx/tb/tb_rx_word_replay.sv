`timescale 1ns/1ps
// Replays physical readout words (32 bits per word clock, rx_word_map order, one hex word per line)
// through rx_word_map, bbpd_window_vote and rx_word_align16.  Training is released after the aligner
// has been aligned for 3 consecutive words.  One output line per word:
//   index phys training aligned offset word_valid vote_valid vote word
//   vvp tb.vvp +vec=phys.hex +n=<words> +out=rtl.tsv   (used by analog/rx/top/tb/b2b_stream/run.py)
module tb_rx_word_replay;
    reg clk=0, rst_n=1, training=1;
    reg [31:0] phys=0;
    reg [31:0] vec [0:8191];
    reg [8*512-1:0] vfile, ofile;
    integer n, i, fo, run;
    wire [15:0] data, edges, word;
    wire prev_d, bvalid, vvalid, wvalid, aligned;
    wire signed [5:0] vote;
    wire [4:0] trans;
    wire [3:0] offset;
    rx_word_map map(clk, rst_n, phys, data, edges, prev_d, bvalid);
    bbpd_window_vote voter(clk, rst_n, bvalid, prev_d, data, edges, vvalid, vote, trans);
    rx_word_align16 align(clk, rst_n, bvalid, training, data, word, wvalid, aligned, offset);
    initial begin
        if(!$value$plusargs("vec=%s", vfile) || !$value$plusargs("n=%d", n) || !$value$plusargs("out=%s", ofile))
            $fatal(1, "usage: +vec=FILE +n=N +out=FILE");
        $readmemh(vfile, vec);
        fo = $fopen(ofile, "w");
        #1 rst_n = 0; #1 rst_n = 1; run = 0;   // explicit reset edge (no time-0 race)
        for(i = 0; i < n; i = i + 1) begin
            phys = vec[i];
            #1 clk = 1; #1;
            $fdisplay(fo, "%0d %h %0d %0d %h %0d %0d %0d %h", i, phys, training, aligned, offset, wvalid, vvalid, vote, word);
            run = aligned ? run + 1 : 0;
            if(training && run >= 3) training = 0;
            #1 clk = 0; #1;
        end
        $fclose(fo);
        $finish;
    end
endmodule
