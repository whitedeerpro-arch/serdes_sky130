// All inputs are synchronous to ref_clk except rst_n and abort_async.
// Quality inputs come from a separate windowed frequency/phase frontend.
// This supervisor never infers lock from Vctrl flatness or frequency alone.
module pll_startup_supervisor #(
    parameter integer PRECHARGE_CYCLES = 128,
    parameter integer GAP_CYCLES = 2,
    parameter integer PFD_FLUSH_CYCLES = 2,
    parameter integer GOOD_WINDOWS = 4,
    parameter integer BAD_WINDOWS = 2,
    parameter integer QUALITY_TIMEOUT_CYCLES = 128,
    parameter integer WAIT_TIMEOUT_CYCLES = 4096,
    parameter integer ACQUIRE_TIMEOUT_CYCLES = 4096
) (
    input wire ref_clk, rst_n, enable, start,
    input wire bias_ready, pre_ref_ready,
    input wire quality_valid, frequency_good, phase_good, range_fault,
    input wire abort_async,
    output reg precharge_en, pfd_rst_b, cp_en, locked, busy, fault,
    output reg [2:0] state_id,
    output reg [2:0] fault_code
);
    localparam [7:0] IDLE=8'b00000001, WAIT_READY=8'b00000010,
                     PRECHARGE=8'b00000100, GAP=8'b00001000,
                     FLUSH=8'b00010000, ACQUIRE=8'b00100000,
                     TRACK=8'b01000000, FAULT=8'b10000000;
    function automatic integer max2(input integer a, input integer b);
        max2=(a>b ? a : b);
    endfunction
    localparam integer MAX_CYCLES=max2(max2(PRECHARGE_CYCLES,GAP_CYCLES),
        max2(PFD_FLUSH_CYCLES,max2(WAIT_TIMEOUT_CYCLES,ACQUIRE_TIMEOUT_CYCLES)));
    localparam integer CW=max2(1,$clog2(MAX_CYCLES));
    localparam integer GW=max2(1,$clog2(GOOD_WINDOWS));
    localparam integer BW=max2(1,$clog2(BAD_WINDOWS));
    localparam integer QW=max2(1,$clog2(QUALITY_TIMEOUT_CYCLES));
    // Explicitly sized terminal counts also support older synthesis parsers.
    // All cycle/window parameters must be positive and fit a 32-bit integer.
    localparam [CW-1:0] PRE_LAST=PRECHARGE_CYCLES[CW-1:0]-1'b1;
    localparam [CW-1:0] GAP_LAST=GAP_CYCLES[CW-1:0]-1'b1;
    localparam [CW-1:0] FLUSH_LAST=PFD_FLUSH_CYCLES[CW-1:0]-1'b1;
    localparam [CW-1:0] WAIT_LAST=WAIT_TIMEOUT_CYCLES[CW-1:0]-1'b1;
    localparam [CW-1:0] ACQUIRE_LAST=ACQUIRE_TIMEOUT_CYCLES[CW-1:0]-1'b1;
    localparam [QW-1:0] QUALITY_LAST=QUALITY_TIMEOUT_CYCLES[QW-1:0]-1'b1;
    localparam [GW-1:0] GOOD_LAST=GOOD_WINDOWS[GW-1:0]-1'b1;
    localparam [BW-1:0] BAD_LAST=BAD_WINDOWS[BW-1:0]-1'b1;
    // Analog controls use one-hot state bits, avoiding binary-decode glitches.
    // Preserve this encoding through synthesis; state_id is diagnostics only.
    (* fsm_encoding = "none" *) reg [7:0] state;
    reg [CW-1:0] cycles;
    reg [GW-1:0] good_count;
    reg [BW-1:0] bad_count;
    reg [QW-1:0] quality_age;
    (* ASYNC_REG = "TRUE" *) reg [1:0] abort_sync;
    wire quality_good = frequency_good && phase_good;
    wire rails_ready = bias_ready && pre_ref_ready;

    always @* begin
        precharge_en=0; pfd_rst_b=0; cp_en=0; locked=0;
        busy=|state[5:1]; fault=state[7]; state_id=7;
        case (state)
            IDLE: state_id=0;
            WAIT_READY: state_id=1;
            PRECHARGE: state_id=2;
            GAP: state_id=3;
            FLUSH: state_id=4;
            ACQUIRE: state_id=5;
            TRACK: state_id=6;
            default: state_id=7;
        endcase
        if (rst_n && enable && !abort_async && !abort_sync[1] && rails_ready) begin
            precharge_en=state[2];
            pfd_rst_b=state[4] || state[5] || state[6];
            cp_en=state[5] || state[6];
            locked=state[6];
        end
    end

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) abort_sync<=0;
        else abort_sync<={abort_sync[0],abort_async};
    end

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) quality_age<=0;
        else if ((state!=ACQUIRE && state!=TRACK) || quality_valid) quality_age<=0;
        else if (quality_age<QUALITY_LAST) quality_age<=quality_age+1;
    end

    // abort_async clamps the outputs above even if ref_clk has stopped.
    // Its source must hold it until acknowledged; it is not a CDC pulse catcher.
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; cycles<=0; good_count<=0; bad_count<=0; fault_code<=0;
        end else if (!enable) begin
            state<=IDLE; cycles<=0; good_count<=0; bad_count<=0; fault_code<=0;
        end else if (abort_sync[1]) begin
            state<=FAULT; fault_code<=5; cycles<=0; good_count<=0; bad_count<=0;
        end else if (state!=IDLE && state!=WAIT_READY && state!=FAULT && !rails_ready) begin
            state<=FAULT; fault_code<=(!bias_ready ? 1 : 2);
        end else if ((state==ACQUIRE || state==TRACK) && range_fault) begin
            state<=FAULT; fault_code<=3;
        end else begin
            case (state)
                IDLE: if (start) begin
                    state<=WAIT_READY; cycles<=0; good_count<=0; bad_count<=0; fault_code<=0;
                end
                WAIT_READY: begin
                    if (rails_ready) begin state<=PRECHARGE; cycles<=0; end
                    else if (cycles>=WAIT_LAST) begin state<=FAULT; fault_code<=4; end
                    else cycles<=cycles+1;
                end
                PRECHARGE: begin
                    if (cycles>=PRE_LAST) begin state<=GAP; cycles<=0; end
                    else cycles<=cycles+1;
                end
                GAP: begin
                    if (cycles>=GAP_LAST) begin state<=FLUSH; cycles<=0; end
                    else cycles<=cycles+1;
                end
                FLUSH: begin
                    if (cycles>=FLUSH_LAST) begin state<=ACQUIRE; cycles<=0; good_count<=0; end
                    else cycles<=cycles+1;
                end
                ACQUIRE: begin
                    if (quality_valid && quality_good && good_count>=GOOD_LAST) begin
                        state<=TRACK; cycles<=0; bad_count<=0;
                    end else if (cycles>=ACQUIRE_LAST) begin
                        state<=FAULT; fault_code<=4;
                    end else begin
                        cycles<=cycles+1;
                        if (quality_valid) begin
                            if (quality_good) good_count<=good_count+1;
                            else good_count<=0;
                        end else if (quality_age>=QUALITY_LAST) good_count<=0;
                    end
                end
                TRACK: begin
                    if (quality_valid) begin
                        cycles<=0;
                        if (quality_good) bad_count<=0;
                        else if (bad_count>=BAD_LAST) begin
                            // Preserve filter state on ordinary lock loss.
                            state<=ACQUIRE; cycles<=0; good_count<=0; bad_count<=0;
                        end else bad_count<=bad_count+1;
                    end else if (quality_age>=QUALITY_LAST) begin
                        state<=FAULT; fault_code<=6;
                    end
                end
                FAULT: if (start && rails_ready) begin
                    state<=WAIT_READY; cycles<=0; good_count<=0; bad_count<=0; fault_code<=0;
                end
                default: begin state<=FAULT; fault_code<=4; end
            endcase
        end
    end
endmodule
