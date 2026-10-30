`timescale 1ps/1fs
// Behavioral sampling/clock plant around ACTUAL voter/filter/commutator/SIPO RTL.
// Uses measured PI static code curve. Physical sampler/CMOS/demux/CDC are outside.
module tb_rx_cdr_closed_loop;
    parameter real OFFSET_PPM=300.0, TX_PHASE_PS=73.0, JITTER_PS=0.0;
    parameter integer SIM_BITS=400000, LATENCY_WORDS=2;
    parameter integer HOLDOVER_BITS=0;
    parameter real EDGE_SKEW_PS=0.0, EDGE_DUTY_PS=0.0, MAX_ERROR_PS=25.0;
    reg ctrl=0,rst_n=1,enable=1,bvalid=0,previous=0;
    reg [15:0] dd=0,ee=0;
    wire [5:0] code;
    wire [7:0] sa,sb,ff;
    wire locked,holdover,limited,applied;
    wire signed [31:0] frequency,phase_debt;
    rx_cdr_loop dut(ctrl,rst_n,enable,bvalid,previous,dd,ee,code,sa,sb,ff,
        locked,holdover,limited,applied,frequency,phase_debt);
    reg pair_clk=0,pvalid=0,training=1;
    reg [1:0] pair_bits=0;
    wire [15:0] word_data;
    wire word_valid,aligned;
    rx_deserializer16 deser(pair_clk,rst_n,pvalid,training,pair_bits,word_data,word_valid,aligned);
    reg [31:0] phase_lut[0:63];
    reg prbs[0:126];
    reg [6:0] lfsr;
    reg [15:0] dbuf=0,ebuf=0,dpipe[0:15],epipe[0:15];
    reg prev_pipe[0:15],last_data=0;
    integer phase_steps=0,old_code=0,frames=0,wraps=0;
    integer n,j,k,idx,last_payload_index=-1,word_end,source_end;
    integer data_slips=0,last_data_index=-1,bit_errors=0,words=0,word_errors=0;
    integer fd;
    real tx_ui,te,td,phi,center,err,max_error=0,sum_error2=0,lock_time=-1;
    integer error_samples=0;
    reg [15:0] expected_word;
    function automatic real jitter(input integer i);
        integer h;
        begin h=(i*1103515245+12345)&65535;jitter=JITTER_PS*(2.0*h/65535.0-1.0);end
    endfunction
    function automatic real boundary(input integer i);
        boundary=TX_PHASE_PS+i*tx_ui+jitter(i);
    endfunction
    function automatic integer source_index(input real t);
        integer a;
        begin
            a=$rtoi($floor((t-TX_PHASE_PS)/tx_ui));
            if(t<boundary(a))a=a-1;
            else if(t>=boundary(a+1))a=a+1;
            source_index=a;
        end
    endfunction
    function automatic reg bit_at_index(input integer a);
        integer b;
        begin
            if(a<80000) begin b=((a%16)+16)%16;bit_at_index=(16'hb5e3>>b)&1;end
            else if(a>=200000 && a<200000+HOLDOVER_BITS) bit_at_index=0;
            else begin b=(a-80000)%127;bit_at_index=prbs[b];end
        end
    endfunction
    function automatic reg source_bit(input real t);
        source_bit=bit_at_index(source_index(t));
    endfunction
    function automatic real phase_time;
        integer turns,c;
        begin
            turns=$rtoi($floor(phase_steps/64.0));c=((phase_steps%64)+64)%64;
            phase_time=turns*500.0+phase_lut[c]/1000.0;
        end
    endfunction
    initial begin
        $readmemh("pi_phase_fs.hex",phase_lut);
        tx_ui=250.0/(1.0+OFFSET_PPM*1e-6);lfsr=7'h5d;
        for(j=0;j<127;j=j+1)begin prbs[j]=lfsr[0];lfsr={lfsr[0]^lfsr[1],lfsr[6:1]};end
        for(j=0;j<16;j=j+1)begin dpipe[j]=0;epipe[j]=0;prev_pipe[j]=0;end
        fd=$fopen("tracking.tsv","w");
        $fdisplay(fd,"time_ps code unwrapped_steps frequency_q debt_q locked phase_error_ps");
        #1;rst_n=0;#10;rst_n=1;
        for(n=0;n<SIM_BITS;n=n+1)begin
            te=2000+n*250.0-phase_time();
            if(te<$realtime)$fatal(1,"nonmonotonic edge clock");
            #(te-$realtime);ebuf[n%16]=source_bit($realtime+EDGE_SKEW_PS+((n%2)?EDGE_DUTY_PS:-EDGE_DUTY_PS));
            td=2000+n*250.0+125.0-phase_time();
            if(td<$realtime)$fatal(1,"nonmonotonic data clock");
            #(td-$realtime);idx=source_index($realtime);
            dbuf[n%16]=source_bit($realtime);pair_bits[n%2]=source_bit($realtime);
            center=(boundary(idx)+boundary(idx+1))/2.0;err=$realtime-center;
            if($realtime>30000000)begin
                if(last_data_index>=0 && idx!=last_data_index+1)data_slips=data_slips+1;
                if(err>max_error)max_error=err;if(-err>max_error)max_error=-err;
                sum_error2=sum_error2+err*err;error_samples=error_samples+1;
            end
            last_data_index=idx;
            if(n%2==1)begin
                // Keep shifting samples through transient quality changes; never silently drop bits.
                pvalid=1;training=($realtime<boundary(80000));pair_clk=1;#1;pair_clk=0;
                if(word_valid && idx>81024)begin
                    word_end=idx;
                    if(word_end%16!=15)word_end=idx-1;
                    if(word_end%16!=15)$fatal(1,"word boundary");
                    expected_word=0;
                    for(j=0;j<16;j=j+1)expected_word[j]=bit_at_index(word_end-15+j);
                    if(word_data!==expected_word)word_errors=word_errors+1;
                    if(last_payload_index>=0 && word_end!=last_payload_index+16)bit_errors=bit_errors+1;
                    last_payload_index=word_end;words=words+1;
                end
            end
            if(n%16==15)begin
                dd=dpipe[LATENCY_WORDS-1];ee=epipe[LATENCY_WORDS-1];previous=prev_pipe[LATENCY_WORDS-1];
                bvalid=frames>LATENCY_WORDS;
                for(j=LATENCY_WORDS-1;j>0;j=j-1)begin dpipe[j]=dpipe[j-1];epipe[j]=epipe[j-1];prev_pipe[j]=prev_pipe[j-1];end
                dpipe[0]=dbuf;epipe[0]=ebuf;prev_pipe[0]=last_data;last_data=dbuf[15];frames=frames+1;
                ctrl=1;#1;
                if((^{code,locked,frequency,phase_debt})===1'bx)$fatal(1,"unknown control state");
                k=$signed({1'b0,code})-old_code;
                if(k==1||k==-63)phase_steps=phase_steps+1;
                else if(k==-1||k==63)phase_steps=phase_steps-1;
                else if(k!=0)$fatal(1,"PI jumped");
                if(k==63||k==-63)wraps=wraps+1;
                old_code=code;
                if(locked && lock_time<0)lock_time=$realtime;
                if(frames%16==0)$fdisplay(fd,"%0.3f %0d %0d %0d %0d %0d %0.6f",$realtime,code,phase_steps,frequency,phase_debt,locked,err);
                ctrl=0;
            end
        end
        $display("RESULT ppm=%0.1f jitter=%0.1f latency=%0d lock_ns=%0.3f freq_ppm=%0.3f wraps=%0d words=%0d word_errors=%0d word_gaps=%0d slips=%0d maxerr_ps=%0.3f rms_ps=%0.3f locked=%0d limited=%0d aligned=%0d",OFFSET_PPM,JITTER_PS,LATENCY_WORDS,lock_time/1000.0,$itor(frequency)/65536.0*1953.125,wraps,words,word_errors,bit_errors,data_slips,max_error,$sqrt(sum_error2/error_samples),locked,limited,aligned);
        $fclose(fd);
        if(!locked||limited||!aligned||words<1000||word_errors!=0||bit_errors!=0||data_slips!=0||max_error>MAX_ERROR_PS)$fatal(1,"closed-loop criteria");
        $display("PASS closed-loop behavioral plant / actual CDR and deserializer RTL");$finish;
    end
    initial begin #200000000;$fatal(1,"timeout");end
endmodule
