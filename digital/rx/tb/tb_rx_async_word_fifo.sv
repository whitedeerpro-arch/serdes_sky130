// Unrelated clocks, full/empty, pointer wraps, host stalls and reset epochs.
// Scoreboard records only accepted words; overflow cannot silently overwrite.
module tb_rx_async_word_fifo #(
    parameter integer ADDR_BITS = 4
);
    timeunit 1ns;
    timeprecision 1ps;
    reg w_clk=0, r_clk=0, arst_n=0, w_valid=0, r_ready=0;
    reg w_clock_run=1, r_clock_run=1;
    real w_half=2.0, r_half=2.3;
    reg [15:0] w_data=0;
    wire w_ready, w_online, w_overflow, r_valid, r_online, r_overflow;
    wire [15:0] r_data;
    rx_async_word_fifo #(.ADDR_BITS(ADDR_BITS)) dut (.*);
    always begin #(w_half); if (w_clock_run) w_clk=~w_clk; else w_clk=0; end
    initial begin #0.7; forever begin #(r_half); if (r_clock_run) r_clk=~r_clk; else r_clk=0; end end
    reg [15:0] expected [0:20000];
    integer head=0, tail=0, rejected=0, sent=0, total_read=0, reset_discarded=0;
    reg stalled=0;
    reg [15:0] held;
    always @(posedge w_clk) if (arst_n && w_online && w_valid) begin
        sent=sent+1;
        if (w_ready) begin expected[tail]=w_data; tail=tail+1; end
        else rejected=rejected+1;
    end
    always @(posedge r_clk) if (arst_n) begin
        if (stalled && (!r_valid || r_data!==held)) $fatal(1,"FAIL host stall changes pending word");
        stalled=r_valid && !r_ready;
        held=r_data;
        if (r_valid && r_ready) begin
            if (head>=tail || r_data!==expected[head])
                $fatal(1,"FAIL reorder/corruption head=%0d tail=%0d got=%h expected=%h",head,tail,r_data,expected[head]);
            head=head+1; total_read=total_read+1;
        end
    end

    task common_reset(input bit stop_writer, input bit stop_reader);
        begin
            #0.1 arst_n=0; w_valid=0; r_ready=0;
            #0.1 reset_discarded=reset_discarded+tail-head; head=0; tail=0; stalled=0;
            w_clock_run=!stop_writer; r_clock_run=!stop_reader;
            #40 arst_n=1;
            #40;
            if (w_overflow || r_overflow || r_valid) $fatal(1,"FAIL stale state after reset");
            if ((stop_writer || stop_reader) && (w_online || r_online || w_ready))
                $fatal(1,"FAIL link online while a reset domain has no clock");
            w_clock_run=1; r_clock_run=1;
            wait (w_online && r_online);
            @(negedge w_clk);
        end
    endtask
    task drain;
        integer n;
        begin
            @(negedge w_clk) w_valid=0;
            @(negedge r_clk) r_ready=1;
            n=0;
            while ((head<tail || r_valid) && n<500) begin @(negedge r_clk); n=n+1; end
            repeat (8) @(negedge r_clk);
            if (head!=tail || r_valid) $fatal(1,"FAIL did not drain head=%0d tail=%0d",head,tail);
        end
    endtask
    integer i, before_rejected, accepted_at_full;
    reg [31:0] random_state=32'h51a7b92d;
    initial begin
        // Explicit first assertion even when simulation starts with reset low.
        #0.1 arst_n=1; #0.1 arst_n=0;
        common_reset(0,0);
        // Fill with reader stopped, then keep arriving: reject rather than overwrite.
        r_ready=0; before_rejected=rejected;
        for (i=0;i<(2**ADDR_BITS)+8;i=i+1) begin
            @(negedge w_clk); w_valid=1; w_data=16'h1000+i;
        end
        @(negedge w_clk) w_valid=0;
        accepted_at_full=tail-head;
        if (accepted_at_full!=(2**ADDR_BITS) || w_ready || !w_overflow || rejected-before_rejected!=8)
            $fatal(1,"FAIL full handling accepted=%0d ready=%0d overflow=%0d rejected=%0d",accepted_at_full,w_ready,w_overflow,rejected-before_rejected);
        drain;
        if (!w_overflow || !r_overflow) $fatal(1,"FAIL overflow not sticky / not delivered to host");
        common_reset(0,0);
        // Host faster: repeated empty->nonempty and many pointer wraps without loss.
        // Depth 2/4 also need spacing for the synchronized read credit to return.
        r_half=1.7; r_ready=1;
        for (i=0;i<700;i=i+1) begin
            @(negedge w_clk); w_valid=(ADDR_BITS<3) ? (i%8==0) : ((i%5)!=0); w_data=16'h2000+i;
        end
        drain;
        if (w_overflow) $fatal(1,"FAIL overflow with faster host");
        // Slower host plus deterministic bursts/stalls: deliberate overflow, preserve survivors.
        r_half=2.7;
        fork
            begin
                for (i=0;i<2200;i=i+1) begin
                    @(negedge w_clk);
                    random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
                    w_valid=random_state[0] || random_state[3]; w_data=16'h4000+i;
                end
                @(negedge w_clk) w_valid=0;
            end
            begin
                repeat (2000) begin @(negedge r_clk); r_ready=($time%53)<35; end
            end
        join
        drain;
        if (!w_overflow) $fatal(1,"FAIL overflow stress not exercised");
        // Discard pending old-epoch words; neither stopped clock may release the link.
        r_ready=0;
        repeat (2) begin @(negedge w_clk); w_valid=1; w_data=16'hdead; end
        common_reset(1,0);
        r_ready=1;
        for (i=0;i<100;i=i+1) begin @(negedge w_clk); w_valid=i%4==0; w_data=16'h8000+i; end
        drain;
        common_reset(0,1);
        r_ready=1;
        for (i=0;i<100;i=i+1) begin @(negedge w_clk); w_valid=i%4==0; w_data=16'ha000+i; end
        drain;
        // Running read clock stops: online is not a clock-health watchdog.
        common_reset(0,0);
        @(negedge r_clk); r_ready=0; r_clock_run=0;
        for (i=0;i<(2**ADDR_BITS)+8;i=i+1) begin
            @(negedge w_clk); w_valid=1; w_data=16'hb000+i;
        end
        @(negedge w_clk) w_valid=0;
        if (!w_online || !w_overflow || tail-head!=(2**ADDR_BITS))
            $fatal(1,"FAIL stopped reader capacity/error reporting");
        r_clock_run=1;
        drain;
        if (!r_overflow) $fatal(1,"FAIL host misses stopped-clock overflow");
        // Running write clock stops: buffered words still drain once synchronized.
        common_reset(0,0);
        r_ready=0;
        for (i=0;i<2;i=i+1) begin @(negedge w_clk); w_valid=1; w_data=16'hc000+i; end
        @(negedge w_clk); w_valid=0; w_clock_run=0;
        @(negedge r_clk) r_ready=1;
        repeat (40) @(negedge r_clk);
        if (head!=tail || r_valid || r_overflow) $fatal(1,"FAIL stopped writer drain");
        w_clock_run=1;
        @(negedge w_clk);
        for (i=0;i<40;i=i+1) begin @(negedge w_clk); w_valid=i%8==0; w_data=16'hd000+i; end
        drain;
        if (total_read<400 || rejected<8) $fatal(1,"FAIL insufficient exercise");
        if (sent!=total_read+rejected+reset_discarded || head!=tail) $fatal(1,"FAIL unaccounted word loss");
        $display("PASS depth=%0d accepted reads=%0d rejected=%0d arrivals=%0d reset_discarded=%0d",2**ADDR_BITS,total_read,rejected,sent,reset_discarded);
        $finish;
    end
    initial begin #100000; $fatal(1,"FAIL timeout"); end
endmodule
