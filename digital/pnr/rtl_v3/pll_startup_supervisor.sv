// Compact PLL startup supervisor running on synchronous /4 (62.5 MHz / 16 ns) clock (v3).
// Cycle-count parameters are in slow ctrl_clk ticks (scaled proportionally by pll_control_top
// so wall-clock durations remain identical to the 250 MHz specification).
module pll_startup_supervisor #(
    parameter integer PRECHARGE_CYCLES       = 32,
    parameter integer GAP_CYCLES             = 1,
    parameter integer PFD_FLUSH_CYCLES       = 1,
    parameter integer GOOD_WINDOWS           = 4,
    parameter integer BAD_WINDOWS            = 2,
    parameter integer QUALITY_TIMEOUT_CYCLES = 64,
    parameter integer WAIT_TIMEOUT_CYCLES    = 1024,
    parameter integer ACQUIRE_TIMEOUT_CYCLES = 8192
) (
    input  wire       ctrl_clk,
    input  wire       rst_n,
    input  wire       enable,
    input  wire       start,
    input  wire       bias_ready,
    input  wire       pre_ref_ready,
    input  wire       quality_valid,
    input  wire       frequency_good,
    input  wire       phase_good,
    input  wire       range_fault,
    input  wire       abort_async,
    output reg        precharge_en,
    output reg        pfd_rst_b,
    output reg        cp_en,
    output reg        locked,
    output reg        busy,
    output reg        fault,
    output reg  [2:0] state_id,
    output reg  [2:0] fault_code
);
    localparam [7:0] IDLE       = 8'b0000_0001,
                     WAIT_READY = 8'b0000_0010,
                     PRECHARGE  = 8'b0000_0100,
                     GAP        = 8'b0000_1000,
                     FLUSH      = 8'b0001_0000,
                     ACQUIRE    = 8'b0010_0000,
                     TRACK      = 8'b0100_0000,
                     FAULT      = 8'b1000_0000;

    function automatic integer max2(input integer a, input integer b);
        max2 = (a > b) ? a : b;
    endfunction

    localparam integer MAX_CYCLES = max2(
        max2(PRECHARGE_CYCLES, GAP_CYCLES),
        max2(PFD_FLUSH_CYCLES, max2(WAIT_TIMEOUT_CYCLES, ACQUIRE_TIMEOUT_CYCLES))
    );
    localparam integer CW = max2(1, $clog2(MAX_CYCLES + 1));
    localparam integer GW = max2(1, $clog2(GOOD_WINDOWS + 1));
    localparam integer BW = max2(1, $clog2(BAD_WINDOWS + 1));
    localparam integer QW = max2(1, $clog2(QUALITY_TIMEOUT_CYCLES + 1));

    localparam integer PRE_M1     = (PRECHARGE_CYCLES > 1)       ? (PRECHARGE_CYCLES - 1)       : 0;
    localparam integer GAP_M1     = (GAP_CYCLES > 1)             ? (GAP_CYCLES - 1)             : 0;
    localparam integer FLUSH_M1   = (PFD_FLUSH_CYCLES > 1)       ? (PFD_FLUSH_CYCLES - 1)       : 0;
    localparam integer WAIT_M1    = (WAIT_TIMEOUT_CYCLES > 1)    ? (WAIT_TIMEOUT_CYCLES - 1)    : 0;
    localparam integer ACQUIRE_M1 = (ACQUIRE_TIMEOUT_CYCLES > 1) ? (ACQUIRE_TIMEOUT_CYCLES - 1) : 0;
    localparam integer QUAL_M1    = (QUALITY_TIMEOUT_CYCLES > 1) ? (QUALITY_TIMEOUT_CYCLES - 1) : 0;
    localparam integer GOOD_M1    = (GOOD_WINDOWS > 1)           ? (GOOD_WINDOWS - 1)           : 0;
    localparam integer BAD_M1     = (BAD_WINDOWS > 1)            ? (BAD_WINDOWS - 1)            : 0;

    localparam [CW-1:0] PRE_LAST     = PRE_M1[CW-1:0];
    localparam [CW-1:0] GAP_LAST     = GAP_M1[CW-1:0];
    localparam [CW-1:0] FLUSH_LAST   = FLUSH_M1[CW-1:0];
    localparam [CW-1:0] WAIT_LAST    = WAIT_M1[CW-1:0];
    localparam [CW-1:0] ACQUIRE_LAST = ACQUIRE_M1[CW-1:0];
    localparam [QW-1:0] QUALITY_LAST = QUAL_M1[QW-1:0];
    localparam [GW-1:0] GOOD_LAST    = GOOD_M1[GW-1:0];
    localparam [BW-1:0] BAD_LAST     = BAD_M1[BW-1:0];

    (* fsm_encoding = "none" *) reg [7:0] state;
    reg [7:0] next_state;
    reg [CW-1:0] cycles;
    reg [GW-1:0] good_count;
    reg [BW-1:0] bad_count;
    reg [QW-1:0] quality_age;
    (* ASYNC_REG = "TRUE" *) reg [1:0] abort_sync;

    wire quality_good = frequency_good && phase_good;
    wire rails_ready  = bias_ready && pre_ref_ready;
    wire outputs_ok   = enable && !abort_sync[1] && rails_ready;

    // Pure combinational next-state & digital host status decode
    always @* begin
        busy  = |state[5:1];
        fault = state[7];
        case (state)
            IDLE:       state_id = 3'd0;
            WAIT_READY: state_id = 3'd1;
            PRECHARGE:  state_id = 3'd2;
            GAP:        state_id = 3'd3;
            FLUSH:      state_id = 3'd4;
            ACQUIRE:    state_id = 3'd5;
            TRACK:      state_id = 3'd6;
            default:    state_id = 3'd7;
        endcase

        next_state = state;
        if (!enable) begin
            next_state = IDLE;
        end else if (abort_sync[1]) begin
            next_state = FAULT;
        end else if (state != IDLE && state != WAIT_READY && state != FAULT && !rails_ready) begin
            next_state = FAULT;
        end else if ((state == ACQUIRE || state == TRACK) && range_fault) begin
            next_state = FAULT;
        end else begin
            case (state)
                IDLE: begin
                    if (start) next_state = WAIT_READY;
                end
                WAIT_READY: begin
                    if (rails_ready)           next_state = PRECHARGE;
                    else if (cycles >= WAIT_LAST) next_state = FAULT;
                end
                PRECHARGE: begin
                    if (cycles >= PRE_LAST) next_state = GAP;
                end
                GAP: begin
                    if (cycles == GAP_LAST) next_state = FLUSH;
                end
                FLUSH: begin
                    if (cycles == FLUSH_LAST) next_state = ACQUIRE;
                end
                ACQUIRE: begin
                    if (quality_valid && quality_good && good_count >= GOOD_LAST)
                        next_state = TRACK;
                    else if (cycles >= ACQUIRE_LAST)
                        next_state = FAULT;
                end
                TRACK: begin
                    if (quality_valid) begin
                        if (!quality_good && bad_count >= BAD_LAST)
                            next_state = ACQUIRE;
                    end else if (quality_age >= QUALITY_LAST) begin
                        next_state = FAULT;
                    end
                end
                FAULT: begin
                    if (start && rails_ready) next_state = WAIT_READY;
                end
                default: begin
                    next_state = FAULT;
                end
            endcase
        end
    end

    // Glitch-free pure FF analog control & lock outputs (updated synchronously from next_state
    // & synchronized abort_sync[1], asynchronously cleared to safe 0 on !rst_n; zero cycle shift).
    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            precharge_en <= 1'b0;
            pfd_rst_b    <= 1'b0;
            cp_en        <= 1'b0;
            locked       <= 1'b0;
        end else begin
            precharge_en <= outputs_ok && (next_state == PRECHARGE);
            pfd_rst_b    <= outputs_ok && (next_state == FLUSH || next_state == ACQUIRE || next_state == TRACK);
            cp_en        <= outputs_ok && (next_state == ACQUIRE || next_state == TRACK);
            locked       <= outputs_ok && (next_state == TRACK);
        end
    end

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) abort_sync <= 2'b00;
        else        abort_sync <= {abort_sync[0], abort_async};
    end

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            quality_age <= {QW{1'b0}};
        end else if ((state != ACQUIRE && state != TRACK) || quality_valid) begin
            quality_age <= {QW{1'b0}};
        end else if (quality_age < QUALITY_LAST) begin
            quality_age <= quality_age + 1'b1;
        end
    end

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= IDLE;
            cycles     <= {CW{1'b0}};
            good_count <= {GW{1'b0}};
            bad_count  <= {BW{1'b0}};
            fault_code <= 3'd0;
        end else if (!enable) begin
            state      <= IDLE;
            cycles     <= {CW{1'b0}};
            good_count <= {GW{1'b0}};
            bad_count  <= {BW{1'b0}};
            fault_code <= 3'd0;
        end else if (abort_sync[1]) begin
            state      <= FAULT;
            fault_code <= 3'd5;
            cycles     <= {CW{1'b0}};
            good_count <= {GW{1'b0}};
            bad_count  <= {BW{1'b0}};
        end else if (state != IDLE && state != WAIT_READY && state != FAULT && !rails_ready) begin
            state      <= FAULT;
            fault_code <= !bias_ready ? 3'd1 : 3'd2;
        end else if ((state == ACQUIRE || state == TRACK) && range_fault) begin
            state      <= FAULT;
            fault_code <= 3'd3;
        end else begin
            case (state)
                IDLE: begin
                    if (start) begin
                        state      <= WAIT_READY;
                        cycles     <= {CW{1'b0}};
                        good_count <= {GW{1'b0}};
                        bad_count  <= {BW{1'b0}};
                        fault_code <= 3'd0;
                    end
                end
                WAIT_READY: begin
                    if (rails_ready) begin
                        state  <= PRECHARGE;
                        cycles <= {CW{1'b0}};
                    end else if (cycles >= WAIT_LAST) begin
                        state      <= FAULT;
                        fault_code <= 3'd4;
                    end else begin
                        cycles <= cycles + 1'b1;
                    end
                end
                PRECHARGE: begin
                    if (cycles >= PRE_LAST) begin
                        state  <= GAP;
                        cycles <= {CW{1'b0}};
                    end else begin
                        cycles <= cycles + 1'b1;
                    end
                end
                GAP: begin
                    if (cycles == GAP_LAST) begin
                        state  <= FLUSH;
                        cycles <= {CW{1'b0}};
                    end else begin
                        cycles <= cycles + 1'b1;
                    end
                end
                FLUSH: begin
                    if (cycles == FLUSH_LAST) begin
                        state      <= ACQUIRE;
                        cycles     <= {CW{1'b0}};
                        good_count <= {GW{1'b0}};
                    end else begin
                        cycles <= cycles + 1'b1;
                    end
                end
                ACQUIRE: begin
                    if (quality_valid && quality_good && good_count >= GOOD_LAST) begin
                        state     <= TRACK;
                        cycles    <= {CW{1'b0}};
                        bad_count <= {BW{1'b0}};
                    end else if (cycles >= ACQUIRE_LAST) begin
                        state      <= FAULT;
                        fault_code <= 3'd4;
                    end else begin
                        cycles <= cycles + 1'b1;
                        if (quality_valid) begin
                            if (quality_good) good_count <= good_count + 1'b1;
                            else              good_count <= {GW{1'b0}};
                        end else if (quality_age >= QUALITY_LAST) begin
                            good_count <= {GW{1'b0}};
                        end
                    end
                end
                TRACK: begin
                    if (quality_valid) begin
                        cycles <= {CW{1'b0}};
                        if (quality_good) begin
                            bad_count <= {BW{1'b0}};
                        end else if (bad_count >= BAD_LAST) begin
                            state      <= ACQUIRE;
                            cycles     <= {CW{1'b0}};
                            good_count <= {GW{1'b0}};
                            bad_count  <= {BW{1'b0}};
                        end else begin
                            bad_count <= bad_count + 1'b1;
                        end
                    end else if (quality_age >= QUALITY_LAST) begin
                        state      <= FAULT;
                        fault_code <= 3'd6;
                    end
                end
                FAULT: begin
                    if (start && rails_ready) begin
                        state      <= WAIT_READY;
                        cycles     <= {CW{1'b0}};
                        good_count <= {GW{1'b0}};
                        bad_count  <= {BW{1'b0}};
                        fault_code <= 3'd0;
                    end
                end
                default: begin
                    state      <= FAULT;
                    fault_code <= 3'd4;
                end
            endcase
        end
    end
endmodule
