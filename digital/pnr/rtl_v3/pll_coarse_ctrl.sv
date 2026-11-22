// Compact PLL coarse-code controller running on synchronous /4 (62.5 MHz / 16 ns) clock (v3).
// Cycle-count parameters are in slow ctrl_clk ticks (scaled proportionally by pll_control_top).
module pll_coarse_ctrl #(
    parameter integer SETTLE_CYCLES = 128,
    parameter integer SAMPLE_DIV    = 4,
    parameter integer PERSIST       = 8,
    parameter integer HOLD_CYCLES   = 512,
    parameter integer CODE_BITS     = 5
) (
    input  wire                 ctrl_clk,
    input  wire                 rst_n,
    input  wire                 search,
    input  wire                 track_en,
    input  wire [1:0]           tclass,
    input  wire                 hi_async,
    input  wire                 lo_async,
    input  wire [3:0]           lo_run,
    input  wire [3:0]           hi_run,
    input  wire [11:0]          stop_code,
    input  wire [2:0]           stop_sel,
    output reg  [CODE_BITS-1:0] vco_code,
    output reg  [3:0]           lo_code,
    output reg  [3:0]           hi_code,
    output reg                  busy,
    output reg                  done,
    output reg                  fast_end,
    output reg                  slow_end,
    output reg  [7:0]           switches
);
    localparam integer SW = (SETTLE_CYCLES < 1) ? 1 : $clog2(SETTLE_CYCLES + 1);
    localparam integer HW = (HOLD_CYCLES < 1)   ? 1 : $clog2(HOLD_CYCLES + 1);
    localparam integer DW = (SAMPLE_DIV < 2)    ? 1 : $clog2(SAMPLE_DIV + 1);
    localparam integer SDIV_M1 = (SAMPLE_DIV > 1) ? (SAMPLE_DIV - 1) : 0;

    localparam [CODE_BITS-1:0] MAX_CODE = {CODE_BITS{1'b1}};
    localparam [2:0] IDLE = 3'd0, STEP = 3'd1, CHECK = 3'd2, BACK = 3'd3, RUN = 3'd4;

    wire hi, lo;
    mon_sync #(.W(2)) u_sync (
        .clk  (ctrl_clk),
        .rst_n(rst_n),
        .d    ({hi_async, lo_async}),
        .q    ({hi, lo})
    );

    reg [2:0]    state;
    reg [SW-1:0] wait_n;
    reg [HW-1:0] hold_n;
    reg [DW-1:0] div_n;

    wire [1:0] cls     = (tclass == 2'd3) ? 2'd2 : tclass;
    wire [3:0] my_stop = (cls == 2'd0) ? stop_code[3:0] :
                         (cls == 2'd1) ? stop_code[7:4] : stop_code[11:8];
    wire       my_sel  = (cls == 2'd0) ? stop_sel[0] :
                         (cls == 2'd1) ? stop_sel[1] : stop_sel[2];
    wire       above   = my_sel ? hi : !lo;

    wire strobe = (state == RUN) && (div_n == {DW{1'b0}});
    wire hi_f, lo_f;
    wire switch_now = (state == RUN) && !search && track_en && (hold_n == {HW{1'b0}}) &&
                      ((hi_f && vco_code != {CODE_BITS{1'b0}}) ||
                       (!hi_f && lo_f && vco_code != MAX_CODE));
    wire clear_f = (state != RUN) || search || !track_en || (hold_n != {HW{1'b0}}) || switch_now;

    mon_persist #(.N(PERSIST)) u_ph (
        .clk  (ctrl_clk),
        .rst_n(rst_n),
        .clear(clear_f),
        .en   (strobe),
        .d    (hi),
        .q    (hi_f)
    );
    mon_persist #(.N(PERSIST)) u_pl (
        .clk  (ctrl_clk),
        .rst_n(rst_n),
        .clear(clear_f),
        .en   (strobe),
        .d    (lo),
        .q    (lo_f)
    );

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= IDLE;
            vco_code <= MAX_CODE;
            lo_code  <= 4'd8;
            hi_code  <= 4'd8;
            busy     <= 1'b0;
            done     <= 1'b0;
            fast_end <= 1'b0;
            slow_end <= 1'b0;
            switches <= 8'd0;
            wait_n   <= {SW{1'b0}};
            hold_n   <= {HW{1'b0}};
            div_n    <= {DW{1'b0}};
        end else if (search && (state == IDLE || state == RUN)) begin
            state    <= STEP;
            busy     <= 1'b1;
            done     <= 1'b0;
            fast_end <= 1'b0;
            slow_end <= 1'b0;
            vco_code <= MAX_CODE;
            lo_code  <= my_sel ? lo_run : my_stop;
            hi_code  <= my_sel ? my_stop : hi_run;
            wait_n   <= SETTLE_CYCLES[SW-1:0];
        end else begin
            case (state)
                IDLE: begin end
                STEP: begin
                    if (wait_n != {SW{1'b0}}) begin
                        wait_n <= wait_n - 1'b1;
                    end else if (above && vco_code != {CODE_BITS{1'b0}}) begin
                        vco_code <= vco_code - 1'b1;
                        wait_n   <= SETTLE_CYCLES[SW-1:0];
                    end else begin
                        lo_code <= lo_run;
                        hi_code <= hi_run;
                        wait_n  <= SETTLE_CYCLES[SW-1:0];
                        state   <= CHECK;
                    end
                end
                CHECK: begin
                    if (wait_n != {SW{1'b0}}) begin
                        wait_n <= wait_n - 1'b1;
                    end else if (lo && vco_code != MAX_CODE) begin
                        vco_code <= vco_code + 1'b1;
                        wait_n   <= SETTLE_CYCLES[SW-1:0];
                        state    <= BACK;
                    end else begin
                        state  <= RUN;
                        busy   <= 1'b0;
                        done   <= 1'b1;
                        hold_n <= HOLD_CYCLES[HW-1:0];
                        div_n  <= {DW{1'b0}};
                    end
                end
                BACK: begin
                    if (wait_n != {SW{1'b0}}) begin
                        wait_n <= wait_n - 1'b1;
                    end else begin
                        state  <= RUN;
                        busy   <= 1'b0;
                        done   <= 1'b1;
                        hold_n <= HOLD_CYCLES[HW-1:0];
                        div_n  <= {DW{1'b0}};
                    end
                end
                RUN: begin
                    div_n <= (div_n == {DW{1'b0}}) ? SDIV_M1[DW-1:0] : (div_n - 1'b1);
                    if (hold_n != {HW{1'b0}}) begin
                        hold_n <= hold_n - 1'b1;
                    end else begin
                        if (track_en && hi_f) begin
                            if (vco_code != {CODE_BITS{1'b0}}) begin
                                vco_code <= vco_code - 1'b1;
                                switches <= switches + 1'b1;
                                hold_n   <= HOLD_CYCLES[HW-1:0];
                            end else begin
                                fast_end <= 1'b1;
                            end
                        end else if (track_en && lo_f) begin
                            if (vco_code != MAX_CODE) begin
                                vco_code <= vco_code + 1'b1;
                                switches <= switches + 1'b1;
                                hold_n   <= HOLD_CYCLES[HW-1:0];
                            end else begin
                                slow_end <= 1'b1;
                            end
                        end
                        if (!hi_f) fast_end <= 1'b0;
                        if (!lo_f) slow_end <= 1'b0;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
