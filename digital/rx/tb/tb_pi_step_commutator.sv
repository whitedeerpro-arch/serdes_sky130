`timescale 1ns/1ps
module tb_pi_step_commutator;
    parameter integer GUARD=1;
    reg clk=0, rst_n=0, valid=0, advance=1;
    wire ready, applied, done;
    wire [5:0] code;
    wire [7:0] a,b,f;
    pi_step_commutator #(.GUARD_CYCLES(GUARD)) dut(clk,rst_n,valid,advance,ready,code,a,b,f,applied,done);
    always #2 clk=~clk;
    integer expected=0, accepted=0, commits=0, completions=0, old_f=0;
    reg [7:0] old_a=1,old_b=2;
    integer fd;
    function automatic integer countbits(input [7:0] x);
        integer i; begin countbits=0;for(i=0;i<8;i=i+1)countbits=countbits+x[i];end
    endfunction
    function automatic [7:0] a_ref(input integer c);
        integer sector;begin sector=c/8;if(sector%2)sector=(sector+1)%8;a_ref=1<<sector;end
    endfunction
    function automatic [7:0] b_ref(input integer c);
        integer sector;begin sector=c/8;if(!(sector%2))sector=(sector+1)%8;b_ref=1<<sector;end
    endfunction
    function automatic [7:0] f_ref(input integer c);
        integer n;begin n=(c/8)%2 ? 8-c%8 : c%8;f_ref=(1<<n)-1;end
    endfunction
    always @(posedge clk) if(rst_n && valid && ready) begin
        accepted=accepted+1;expected=(expected+(advance ? 1 : 63))%64;
    end
    always @(posedge clk) begin
        #0.01;
        if(rst_n) begin
            if(countbits(a)!=1 || countbits(b)!=1) $fatal(1,"onehot");
            if((f & (f+8'd1))!=0) $fatal(1,"thermometer");
            if(a!=old_a && !(old_f==255 && f==255)) $fatal(1,"active A commutation");
            if(b!=old_b && !(old_f==0 && f==0)) $fatal(1,"active B commutation");
            if(countbits(f ^ old_f)>1) $fatal(1,"more than one fine unit changed");
            if(applied) begin
                commits=commits+1;
                if(code!=expected) $fatal(1,"code mismatch");
            end
            if(done) begin
                completions=completions+1;
                if(a!=a_ref(code)||b!=b_ref(code)||f!=f_ref(code)) $fatal(1,"canonical endpoint mismatch");
            end
            old_a=a;old_b=b;old_f=f;
            $fdisplay(fd,"%0.3f %0d %0d %0d %0d %0d %0d",$realtime,code,a,b,f,applied,done);
        end
    end
    task automatic steps(input integer n,input reg direction);
        integer i;begin
            for(i=0;i<n;i=i+1) begin
                @(negedge clk);advance=direction;valid=1;
                @(posedge clk);while(!ready)@(posedge clk);
                @(negedge clk);valid=0;
                while(!ready)@(negedge clk);
            end
        end
    endtask
    initial begin
        fd=$fopen("controls.tsv","w");$fdisplay(fd,"time_ns code select_a select_b fine_b applied done");
        #1;rst_n=0;#4;rst_n=1;
        // Multiple revolutions, every forward/reverse sector seam, reversals at 0/63.
        steps(128,1);steps(128,0);steps(63,1);steps(4,1);steps(4,0);steps(63,0);
        repeat(3)@(negedge clk);
        if(accepted!=390 || commits!=390 || completions!=390 || code!=0) $fatal(1,"transaction counts");
        $display("PASS guard=%0d accepted=%0d applied=%0d done=%0d",GUARD,accepted,commits,completions);
        $fclose(fd);$finish;
    end
    initial begin #100000; $fatal(1,"timeout");end
endmodule
