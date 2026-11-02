`timescale 1ns/1ps
// rx_word_map + bbpd_window_vote + rx_word_align16 on a behavioural model of the readout outputs
// (rx_readout_deser16 lane/stage -> bit positions as in rx_word_map).  For every word start P (0..15)
// of the physical window: training (b5e3 x 12), then payload words; edges alternate between "clock
// late" (edge = next bit) and "clock early" (edge = previous bit) per word.  Checks every vote
// against a direct computation on the stream and every aligned output word against the payload.
module tb_rx_word_path;
    reg clk=0, rst_n=0, training=1;
    reg [31:0] phys=0;
    wire [15:0] data, edges, word;
    wire prev_d, bvalid, vvalid, wvalid, aligned;
    wire signed [5:0] vote;
    wire [4:0] trans;
    wire [3:0] offset;
    rx_word_map map(clk, rst_n, phys, data, edges, prev_d, bvalid);
    bbpd_window_vote voter(clk, rst_n, bvalid, prev_d, data, edges, vvalid, vote, trans);
    rx_word_align16 align(clk, rst_n, bvalid, training, data, word, wvalid, aligned, offset);
    always #2 clk=~clk;
    localparam integer NTRAIN=12, NWORDS=60;
    integer P, J, k, n, i, checks_v, checks_w, expect_m, total_v=0, total_w=0;
    integer exp_vote [0:NWORDS+4];
    function automatic [15:0] payload(input integer m);
        payload=(m*257)^16'h793d;
    endfunction
    function automatic reg sbit(input integer x);
        reg [15:0] v;
        begin v = (x/16) < NTRAIN ? 16'hb5e3 : payload(x/16-NTRAIN); sbit=(v>>(x%16))&1; end
    endfunction
    // edge sample just after bit x (between x and x+1); word parity selects late / early
    function automatic reg ebit(input integer x, input integer late);
        ebit = late ? sbit(x+1) : sbit(x);
    endfunction
    task automatic drive(input integer s, input integer late);  // physical word starting at bit s
        begin
            for(k=0;k<4;k=k+1) begin
                phys[0*4+k]=sbit(s+12-4*k); phys[2*4+k]=ebit(s+12-4*k,late);   // a0, ae1
                phys[5*4+k]=sbit(s+13-4*k); phys[7*4+k]=ebit(s+13-4*k,late);   // b1, be0
                phys[1*4+k]=sbit(s+14-4*k); phys[3*4+k]=ebit(s+14-4*k,late);   // b0, be1
                phys[4*4+k]=sbit(s+15-4*k); phys[6*4+k]=ebit(s+15-4*k,late);   // a1, ae0
            end
        end
    endtask
    function automatic integer vote_of(input integer s, input integer late, input integer late_prev);
        integer v, x, e;
        begin
            v=0;
            for(x=s;x<s+16;x=x+1) if(sbit(x-1)!=sbit(x)) begin
                e = (x-1 < s) ? ebit(x-1,late_prev) : ebit(x-1,late);
                v = v + ((e==sbit(x)) ? 1 : -1);
            end
            vote_of=v;
        end
    endfunction
    initial begin
        for(P=0;P<16;P=P+1) begin
            rst_n=0; training=1; checks_v=0; checks_w=0; expect_m=-1;
            @(negedge clk); rst_n=1;
            for(J=0;J<NWORDS;J=J+1) begin
                @(negedge clk);
                n = 16 + P + 16*J;                  // stream starts one word in, so bit s-1 exists
                drive(n, J%2);
                exp_vote[J] = vote_of(n, J%2, (J+1)%2);
                training = (J < NTRAIN - 1);
                @(posedge clk); #0.01;
                // after this edge the voter holds the word driven one cycle ago (map, then voter register)
                if(vvalid && J>=2) begin   // word 0 follows a stale word left from the previous case
                    if(vote!==exp_vote[J-1]) $fatal(1,"P%0d word%0d vote %0d expected %0d",P,J-1,vote,exp_vote[J-1]);
                    checks_v=checks_v+1;
                end
                if(wvalid) begin
                    if(!aligned) $fatal(1,"P%0d word without alignment",P);
                    // training words until the payload starts, then payload(0), payload(1), ... without gaps
                    if(expect_m<0 && word===16'hb5e3) ;
                    else begin
                        if(expect_m<0) expect_m=0;
                        if(word!==payload(expect_m)) $fatal(1,"P%0d word %h expected %h",P,word,payload(expect_m));
                        expect_m=expect_m+1; checks_w=checks_w+1;
                    end
                end
            end
            if(offset!==((16-P)%16)) $fatal(1,"P%0d offset %0d",P,offset);
            if(checks_w < NWORDS-NTRAIN-6) $fatal(1,"P%0d only %0d words",P,checks_w);
            total_v=total_v+checks_v; total_w=total_w+checks_w;
        end
        $display("PASS word path: 16 window offsets, %0d votes, %0d aligned words", total_v, total_w);
        $finish;
    end
endmodule
