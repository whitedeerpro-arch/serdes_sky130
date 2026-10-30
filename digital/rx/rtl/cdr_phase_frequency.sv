// Type-II bang-bang tracking at one control tick /16 recovered UI.
// Q16 phase debt and frequency (PI steps/control tick), applied-step feedback.
// Atomic commands remain outstanding until the commutator reports done.
module cdr_phase_frequency #(
    parameter integer KP=8192, KI=32,
    parameter integer FREQ_LIMIT=32768,
    parameter integer QUALITY_TICKS=128, GOOD_WINDOWS=4, BAD_WINDOWS=4,
    parameter integer NO_TRANSITION_TICKS=256
)(
    input wire ctrl_clk, rst_n, enable, vote_valid,
    input wire signed [5:0] vote_sum,
    input wire [4:0] transition_count,
    input wire step_ready, step_applied, step_done,
    output wire step_valid, advance,
    output reg signed [31:0] frequency_q, phase_debt_q,
    output reg locked, holdover, range_limited
);
    localparam integer ONE=65536, DEBT_LIMIT=2097152;
    reg inflight, issued_advance;
    reg [31:0] age, quality_ticks, quality_transitions, good_count, bad_count;
    reg signed [31:0] quality_sum;
    reg signed [31:0] fnext, pnext, error_sign, qsum_next;
    reg [31:0] qtrans_next;
    reg quality_good;
    assign step_valid=enable && !inflight && ((phase_debt_q>=ONE)||(phase_debt_q<=-ONE));
    assign advance=(phase_debt_q>0);
    always @* begin
        error_sign=0;
        if(vote_valid && transition_count!=0) begin
            if(vote_sum>0) error_sign=1;
            else if(vote_sum<0) error_sign=-1;
        end
        fnext=frequency_q+KI*error_sign;
        if(fnext>FREQ_LIMIT) fnext=FREQ_LIMIT;
        if(fnext<-FREQ_LIMIT) fnext=-FREQ_LIMIT;
        pnext=phase_debt_q+frequency_q+KP*error_sign;
        if(step_applied) pnext=pnext+(issued_advance ? -ONE : ONE);
        if(pnext>DEBT_LIMIT) pnext=DEBT_LIMIT;
        if(pnext<-DEBT_LIMIT) pnext=-DEBT_LIMIT;
        qsum_next=quality_sum+{{26{vote_sum[5]}},vote_sum};
        qtrans_next=quality_transitions+{27'd0,transition_count};
        quality_good=(qtrans_next>=128) &&
            (qsum_next<=$signed(qtrans_next>>2)) && (qsum_next>=-$signed(qtrans_next>>2)) &&
            (phase_debt_q<2*ONE) && (phase_debt_q>-2*ONE) && !range_limited;
    end
    always @(posedge ctrl_clk or negedge rst_n) begin
        if(!rst_n) begin
            frequency_q<=0;phase_debt_q<=0;inflight<=0;issued_advance<=0;
            locked<=0;holdover<=0;range_limited<=0;age<=0;
            quality_ticks<=0;quality_sum<=0;quality_transitions<=0;good_count<=0;bad_count<=0;
        end else begin
            if(step_valid && step_ready) begin inflight<=1;issued_advance<=advance;end
            if(step_done) inflight<=0;
            if(enable) begin
                frequency_q<=fnext;phase_debt_q<=pnext;
                if((fnext==FREQ_LIMIT)||(fnext==-FREQ_LIMIT)||(pnext==DEBT_LIMIT)||(pnext==-DEBT_LIMIT)) begin
                    range_limited<=1;locked<=0;
                end
                if(vote_valid && transition_count!=0) begin age<=0;holdover<=0;end
                else begin
                    if(age<NO_TRANSITION_TICKS) age<=age+1'b1;
                    holdover<=1;
                end
                if(age>=NO_TRANSITION_TICKS) begin locked<=0;good_count<=0;end
                if(vote_valid) begin
                    if(quality_ticks==QUALITY_TICKS-1) begin
                        quality_ticks<=0;quality_sum<=0;quality_transitions<=0;
                        if(quality_good && age<NO_TRANSITION_TICKS) begin
                            bad_count<=0;
                            if(good_count<GOOD_WINDOWS) good_count<=good_count+1'b1;
                            if(good_count>=GOOD_WINDOWS-1) locked<=1;
                        end else if(qtrans_next>=128) begin
                            good_count<=0;
                            if(bad_count<BAD_WINDOWS) bad_count<=bad_count+1'b1;
                            if(bad_count>=BAD_WINDOWS-1) locked<=0;
                        end
                    end else begin
                        quality_ticks<=quality_ticks+1'b1;quality_sum<=qsum_next;quality_transitions<=qtrans_next;
                    end
                end
                if(range_limited) locked<=0;
            end else begin
                locked<=0;holdover<=0;age<=0;good_count<=0;bad_count<=0;
                quality_ticks<=0;quality_sum<=0;quality_transitions<=0;
                // Disable only after draining the commutator; reset to restart acquisition.
                if(step_applied) phase_debt_q<=phase_debt_q+(issued_advance ? -ONE : ONE);
            end
        end
    end
endmodule
