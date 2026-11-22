// Timing-closed v2 PLL coarse-code controller (250 MHz / 4.0 ns SS-closed).
// Bit- and cycle-exact with v1 pll_coarse_ctrl:
//   - Registered static config inputs (tclass_q, lo_run_q, hi_run_q, stop_code_q, stop_sel_q)
//     eliminate hold-buffer insertion on lo_code/hi_code paths!
//   - Replicated st_run_fsm/st_run_sw/st_run_mon and wait_zero/wait_z_ctrl split high fanout.
//   - Pre-registered sw_any_cond_q and dedicated fast_end_int break switches/fault paths.
/* verilator lint_off DECLFILENAME */
module pll_coarse_ctrl_core #(
    parameter integer SETTLE_CYCLES = 512,
    parameter integer SAMPLE_DIV    = 16,
    parameter integer PERSIST       = 8,
    parameter integer HOLD_CYCLES   = 2048,
    parameter integer CODE_BITS     = 4
) (
    input  wire                 ref_clk,
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
    (* keep = "true" *) output reg fast_end_sup,
    output reg                  slow_end,
    output reg  [7:0]           switches
);
    function automatic integer clog2p(input integer x);
        integer i;
        begin clog2p = 1; for (i = 2; i < x; i = i * 2) clog2p = clog2p + 1; end
    endfunction

    localparam integer DW = clog2p(SAMPLE_DIV + 1);
    localparam [CODE_BITS-1:0] MAX_CODE   = {CODE_BITS{1'b1}};
    localparam [CODE_BITS-1:0] ONE_CODE   = {{(CODE_BITS-1){1'b0}}, 1'b1};
    localparam [CODE_BITS-1:0] MAXM1_CODE = MAX_CODE - ONE_CODE;

    localparam [15:0] SETTLE_LOAD = SETTLE_CYCLES[15:0];
    localparam [15:0] HOLD_LOAD   = HOLD_CYCLES[15:0];
    localparam [DW-1:0] DIV_LOAD  = (SAMPLE_DIV <= 1) ? {DW{1'b0}} : (SAMPLE_DIV[DW-1:0] - 1'b1);
    localparam [DW-1:0] DIV_ONE   = {{(DW-1){1'b0}}, 1'b1};

    // 2-stage async synchronizer with stage-0 tap so above_q & chk_lo_q are pre-registered
    // on the EXACT same cycle as hi/lo (cuts 3 gates off lo_code/hi_code and hold_load_en!)
    (* ASYNC_REG = "TRUE" *) reg hi_s0, lo_s0, hi, lo;
    reg above_q;
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            hi_s0 <= 1'b0; lo_s0 <= 1'b0; hi <= 1'b0; lo <= 1'b0; above_q <= 1'b0;
        end else begin
            hi_s0   <= hi_async;
            lo_s0   <= lo_async;
            hi      <= hi_s0;
            lo      <= lo_s0;
            above_q <= my_sel_q ? hi_s0 : !lo_s0;
        end
    end

    // Register static config ports -> zero input-port hold buffers on lo_code/hi_code!
    reg [3:0] lo_run_q, hi_run_q, my_stop_q;
    reg       my_sel_q;
    wire [1:0] cls_in  = (tclass == 2'd3) ? 2'd2 : tclass;
    wire [3:0] stop_in = (cls_in == 2'd0) ? stop_code[3:0] :
                         (cls_in == 2'd1) ? stop_code[7:4] : stop_code[11:8];
    wire       sel_in  = (cls_in == 2'd0) ? stop_sel[0] :
                         (cls_in == 2'd1) ? stop_sel[1] : stop_sel[2];
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            lo_run_q <= 4'd8; hi_run_q <= 4'd8; my_stop_q <= 4'd8; my_sel_q <= 1'b0;
        end else begin
            lo_run_q  <= lo_run;
            hi_run_q  <= hi_run;
            my_stop_q <= stop_in;
            my_sel_q  <= sel_in;
        end
    end

    reg st_idle, st_step, st_check, st_back;
    (* keep = "true" *) reg st_step_ld, st_check_ld, can_search_ld;
    (* keep = "true" *) reg st_run_fsm, st_run_sw, st_run_mon, st_run_end, can_search_q;

    // 4x4-bit nibble down-counter for wait_n: store active-high wait_nz* (resets to 0 -> fast dfrtp
    // instead of slow 1.44 ns dfstp_4 async-set FF! Dedicated wait_nz_vco splits vco_code fanout!)
    reg [3:0] wn0, wn1, wn2, wn3;
    reg       wn0_is1, wz1, wz2, wz3;
    (* keep = "true" *) reg wait_nz, wait_nz_ctrl, wait_nz_code, wait_nz_vco, wait_nz_hold;
    wire wait_zero   = !wait_nz;
    wire wait_z_ctrl = !wait_nz_ctrl;
    wire wait_z_code = !wait_nz_code;
    wire wait_z_vco  = !wait_nz_vco;
    wire wait_z_hold = !wait_nz_hold;
    reg       wen1, wen2, wen3;

    // 4x4-bit nibble down-counter for hold_n: store active-high hold_nz* (resets to 0 -> fast dfrtp!)
    reg [3:0] hn0, hn1, hn2, hn3;
    reg       hn0_is1, hz1, hz2, hz3;
    (* keep = "true" *) reg hold_nz, hold_nz_ctrl, hold_nz_mon, hold_nz_end;
    wire hold_zero   = !hold_nz;
    wire hold_z_ctrl = !hold_nz_ctrl;
    wire hold_z_end  = !hold_nz_end;
    reg       hen1, hen2, hen3;
    reg       sw_lo_is_f;

    reg [DW-1:0] div_n;
    // Active-high replicated div_nz resets to 0 -> fast dfrtp & fanout <= 6 (-0.45 ns!)
    (* keep = "true" *) reg div_nz, div_nz_ph, div_nz_pl;
    wire strobe_ph  = st_run_mon && !div_nz_ph;
    wire strobe_pl  = st_run_mon && !div_nz_pl;
    reg          vco_is_zero, vco_is_max;
    // Pre-registered vco_code +/- 1 & switches + 1 (changes >= SETTLE/HOLD cycles apart -> 1 mux!)
    reg [CODE_BITS-1:0] vco_m1_q, vco_p1_q;
    reg                 vco_m1_is_z_q, vco_p1_is_max_q;
    reg [7:0]           sw_p1_q;
    reg          sw_hi_cond_q, sw_lo_cond_q, sw_any_cond_q;
    reg          step_dec_cond_q, chk_back_cond_q;

    wire hi_f, lo_f;
    wire run_active = st_run_mon && !search;
    wire switch_hi  = sw_hi_cond_q  && !search;
    wire switch_lo  = sw_lo_cond_q  && !search;
    wire switch_now = sw_any_cond_q && !search;
    wire clear_f    = !st_run_mon || search || !track_en || hold_nz_mon || sw_any_cond_q;

    mon_persist #(.N(PERSIST)) u_ph (.clk(ref_clk), .rst_n(rst_n), .clear(clear_f), .en(strobe_ph), .d(hi), .q(hi_f));
    mon_persist #(.N(PERSIST)) u_pl (.clk(ref_clk), .rst_n(rst_n), .clear(clear_f), .en(strobe_pl), .d(lo), .q(lo_f));

    (* keep = "true" *) wire start_search;
    (* keep = "true" *) wire start_search_code;
    assign start_search      = search && can_search_q;
    assign start_search_code = search && can_search_q;
    wire step_done    = st_step  && wait_z_ctrl;
    wire step_dec_vco = st_step  && wait_z_vco && step_dec_cond_q;
    wire step_to_chk  = step_done && !step_dec_cond_q;
    wire step_to_chk_code = st_step && wait_z_code && !step_dec_cond_q;
    wire chk_done     = st_check && wait_z_ctrl;
    wire chk_to_back  = chk_done && chk_back_cond_q;
    wire chk_back_vco = st_check && wait_z_vco && chk_back_cond_q;
    wire chk_to_run   = chk_done && !chk_back_cond_q;
    wire back_to_run  = st_back  && wait_z_ctrl;
    wire enter_run    = chk_to_run || back_to_run;
    wire enter_run_h  = ((st_check && !chk_back_cond_q) || st_back) && wait_z_hold;

    wire wait_load_en = start_search || step_done || chk_to_back;
    wire wait_load_z  = (search && can_search_ld) || (st_step_ld && wait_z_vco) || (st_check_ld && wait_z_vco && chk_back_cond_q);
    (* keep = "true" *) wire hold_load_lo;
    (* keep = "true" *) wire hold_load_z;
    assign hold_load_lo = enter_run_h || switch_now;
    assign hold_load_z  = enter_run_h || switch_now;

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            wn0 <= 4'd0; wn1 <= 4'd0; wn2 <= 4'd0; wn3 <= 4'd0;
            wz1 <= 1'b1; wz2 <= 1'b1; wz3 <= 1'b1;
        end else if (wait_load_en) begin
            wn0 <= SETTLE_LOAD[3:0];
            wn1 <= SETTLE_LOAD[7:4];
            wn2 <= SETTLE_LOAD[11:8];
            wn3 <= SETTLE_LOAD[15:12];
            wz1 <= (SETTLE_LOAD[7:4]   == 4'd0);
            wz2 <= (SETTLE_LOAD[11:8]  == 4'd0);
            wz3 <= (SETTLE_LOAD[15:12] == 4'd0);
        end else begin
            if (!wait_zero) wn0 <= wn0 - 4'd1;
            if (wen1) wn1 <= wn1 - 4'd1;
            if (wen2) wn2 <= wn2 - 4'd1;
            if (wen3) wn3 <= wn3 - 4'd1;
            if (wen1) wz1 <= (wn1 == 4'd1);
            if (wen2) wz2 <= (wn2 == 4'd1);
            if (wen3) wz3 <= (wn3 == 4'd1);
        end
    end

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            wn0_is1 <= 1'b0;
            wait_nz <= 1'b0; wait_nz_ctrl <= 1'b0; wait_nz_code <= 1'b0; wait_nz_vco <= 1'b0; wait_nz_hold <= 1'b0;
            wen1 <= 1'b0; wen2 <= 1'b0; wen3 <= 1'b0;
        end else if (wait_load_z) begin
            wn0_is1      <= (SETTLE_LOAD[3:0]   == 4'd1);
            wait_nz      <= (SETTLE_LOAD        != 16'd0);
            wait_nz_ctrl <= (SETTLE_LOAD        != 16'd0);
            wait_nz_code <= (SETTLE_LOAD        != 16'd0);
            wait_nz_vco  <= (SETTLE_LOAD        != 16'd0);
            wait_nz_hold <= (SETTLE_LOAD        != 16'd0);
            wen1         <= (SETTLE_LOAD[3:0]   == 4'd0) && (SETTLE_LOAD != 16'd0);
            wen2         <= (SETTLE_LOAD[7:0]   == 8'd0) && (SETTLE_LOAD != 16'd0);
            wen3         <= (SETTLE_LOAD[11:0]  == 12'd0) && (SETTLE_LOAD != 16'd0);
        end else if (!wait_zero) begin
            wn0_is1      <= (wn0 == 4'd2);
            wait_nz      <= !(wn0_is1 && wz1 && wz2 && wz3);
            wait_nz_ctrl <= !(wn0_is1 && wz1 && wz2 && wz3);
            wait_nz_code <= !(wn0_is1 && wz1 && wz2 && wz3);
            wait_nz_vco  <= !(wn0_is1 && wz1 && wz2 && wz3);
            wait_nz_hold <= !(wn0_is1 && wz1 && wz2 && wz3);
            wen1         <= wn0_is1 && !(wz1 && wz2 && wz3);
            wen2         <= wn0_is1 && wz1 && !(wz2 && wz3);
            wen3         <= wn0_is1 && wz1 && wz2 && !wz3;
        end
    end

    // Split hold_n counter into data (hold_load_lo) & flags (hold_load_z) -> halves fanout (-0.35 ns!)
    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            hn0 <= 4'd0; hn1 <= 4'd0; hn2 <= 4'd0; hn3 <= 4'd0;
            hz1 <= 1'b1; hz2 <= 1'b1; hz3 <= 1'b1;
        end else if (hold_load_lo) begin
            hn0 <= HOLD_LOAD[3:0];
            hn1 <= HOLD_LOAD[7:4];
            hn2 <= HOLD_LOAD[11:8];
            hn3 <= HOLD_LOAD[15:12];
            hz1 <= (HOLD_LOAD[7:4]   == 4'd0);
            hz2 <= (HOLD_LOAD[11:8]  == 4'd0);
            hz3 <= (HOLD_LOAD[15:12] == 4'd0);
        end else begin
            if (!hold_zero) hn0 <= hn0 - 4'd1;
            if (hen1) hn1 <= hn1 - 4'd1;
            if (hen2) hn2 <= hn2 - 4'd1;
            if (hen3) hn3 <= hn3 - 4'd1;
            if (hen1) hz1 <= (hn1 == 4'd1);
            if (hen2) hz2 <= (hn2 == 4'd1);
            if (hen3) hz3 <= (hn3 == 4'd1);
        end
    end

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            hn0_is1 <= 1'b0;
            hold_nz <= 1'b0; hold_nz_ctrl <= 1'b0; hold_nz_mon <= 1'b0; hold_nz_end <= 1'b0;
            hen1 <= 1'b0; hen2 <= 1'b0; hen3 <= 1'b0;
        end else if (hold_load_z) begin
            hn0_is1      <= (HOLD_LOAD[3:0]   == 4'd1);
            hold_nz      <= (HOLD_LOAD        != 16'd0);
            hold_nz_ctrl <= (HOLD_LOAD        != 16'd0);
            hold_nz_mon  <= (HOLD_LOAD        != 16'd0);
            hold_nz_end  <= (HOLD_LOAD        != 16'd0);
            hen1         <= (HOLD_LOAD[3:0]   == 4'd0) && (HOLD_LOAD != 16'd0);
            hen2         <= (HOLD_LOAD[7:0]   == 8'd0) && (HOLD_LOAD != 16'd0);
            hen3         <= (HOLD_LOAD[11:0]  == 12'd0) && (HOLD_LOAD != 16'd0);
        end else if (!hold_zero) begin
            hn0_is1      <= (hn0 == 4'd2);
            hold_nz      <= !(hn0_is1 && hz1 && hz2 && hz3);
            hold_nz_ctrl <= !(hn0_is1 && hz1 && hz2 && hz3);
            hold_nz_mon  <= !(hn0_is1 && hz1 && hz2 && hz3);
            hold_nz_end  <= !(hn0_is1 && hz1 && hz2 && hz3);
            hen1         <= hn0_is1 && !(hz1 && hz2 && hz3);
            hen2         <= hn0_is1 && hz1 && !(hz2 && hz3);
            hen3         <= hn0_is1 && hz1 && hz2 && !hz3;
        end
    end

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            div_n     <= {DW{1'b0}};
            div_nz    <= 1'b0;
            div_nz_ph <= 1'b0;
            div_nz_pl <= 1'b0;
        end else if (enter_run) begin
            div_n     <= {DW{1'b0}};
            div_nz    <= 1'b0;
            div_nz_ph <= 1'b0;
            div_nz_pl <= 1'b0;
        end else if (run_active) begin
            if (!div_nz) begin
                div_n     <= DIV_LOAD;
                div_nz    <= (DIV_LOAD != {DW{1'b0}});
                div_nz_ph <= (DIV_LOAD != {DW{1'b0}});
                div_nz_pl <= (DIV_LOAD != {DW{1'b0}});
            end else begin
                div_n     <= div_n - 1'b1;
                div_nz    <= (div_n != DIV_ONE);
                div_nz_ph <= (div_n != DIV_ONE);
                div_nz_pl <= (div_n != DIV_ONE);
            end
        end
    end

    wire sw_hi_nxt  = !switch_now && !search && st_run_sw && hold_z_ctrl && track_en && hi_f && !vco_is_zero;
    wire sw_lo_nxt  = !switch_now && !search && st_run_sw && hold_z_ctrl && track_en && !hi_f && lo_f && !vco_is_max;
    wire nxt_st_run = enter_run || (st_run_fsm && !search);

    always @(posedge ref_clk or negedge rst_n) begin
        if (!rst_n) begin
            st_idle       <= 1'b1;
            st_step       <= 1'b0; st_step_ld <= 1'b0;
            st_check      <= 1'b0; st_check_ld <= 1'b0;
            st_back       <= 1'b0;
            st_run_fsm    <= 1'b0; st_run_sw <= 1'b0; st_run_mon <= 1'b0; st_run_end <= 1'b0;
            can_search_q  <= 1'b1; can_search_ld <= 1'b1;
            vco_code      <= MAX_CODE;
            vco_is_zero   <= 1'b0;
            vco_is_max    <= 1'b1;
            vco_m1_q      <= MAXM1_CODE;
            vco_p1_q      <= {CODE_BITS{1'b0}};
            vco_m1_is_z_q   <= 1'b0;
            vco_p1_is_max_q <= 1'b0;
            sw_p1_q       <= 8'd1;
            sw_hi_cond_q    <= 1'b0;
            sw_lo_cond_q    <= 1'b0;
            sw_any_cond_q   <= 1'b0;
            step_dec_cond_q <= 1'b0;
            chk_back_cond_q <= 1'b0;
            lo_code       <= 4'd8;
            hi_code       <= 4'd8;
            busy          <= 1'b0;
            done          <= 1'b0;
            fast_end      <= 1'b0;
            fast_end_sup  <= 1'b0;
            slow_end      <= 1'b0;
            switches      <= 8'd0;
            sw_lo_is_f    <= 1'b0;
        end else begin
            st_idle       <= st_idle && !search;
            st_step       <= start_search || (st_step && !step_to_chk);
            st_step_ld    <= start_search || (st_step && !step_to_chk);
            st_check      <= step_to_chk  || (st_check && !chk_done);
            st_check_ld   <= step_to_chk  || (st_check && !chk_done);
            st_back       <= chk_to_back  || (st_back && !wait_z_ctrl);
            st_run_fsm    <= nxt_st_run;
            st_run_sw     <= nxt_st_run;
            st_run_mon    <= nxt_st_run;
            st_run_end    <= nxt_st_run;
            can_search_q  <= (st_idle && !search) || nxt_st_run;
            can_search_ld <= (st_idle && !search) || nxt_st_run;
            sw_hi_cond_q    <= sw_hi_nxt;
            sw_lo_cond_q    <= sw_lo_nxt;
            sw_any_cond_q   <= sw_hi_nxt || sw_lo_nxt;
            step_dec_cond_q <= above_q && !vco_is_zero;
            chk_back_cond_q <= lo && !vco_is_max;

            // Pre-registered next values (vco_code/switches change >= 512 cycles apart -> 1 mux!)
            vco_m1_q        <= vco_code - 1'b1;
            vco_p1_q        <= vco_code + 1'b1;
            vco_m1_is_z_q   <= (vco_code == ONE_CODE);
            vco_p1_is_max_q <= (vco_code == MAXM1_CODE);
            sw_p1_q         <= {sw_lo_is_f ? (switches[7:4] + 4'd1) : switches[7:4], switches[3:0] + 4'd1};

            if (start_search_code) begin
                lo_code <= my_sel_q ? lo_run_q : my_stop_q;
                hi_code <= my_sel_q ? my_stop_q : hi_run_q;
            end else if (step_to_chk_code) begin
                lo_code <= lo_run_q;
                hi_code <= hi_run_q;
            end

            if (start_search) begin
                busy        <= 1'b1;
                done        <= 1'b0;
                vco_code    <= MAX_CODE;
                vco_is_zero <= 1'b0;
                vco_is_max  <= 1'b1;
            end else begin
                if (enter_run) begin
                    busy <= 1'b0;
                    done <= 1'b1;
                end

                if (step_dec_vco || switch_hi) begin
                    vco_code    <= vco_m1_q;
                    vco_is_zero <= vco_m1_is_z_q;
                    vco_is_max  <= 1'b0;
                end else if (chk_back_vco || switch_lo) begin
                    vco_code    <= vco_p1_q;
                    vco_is_zero <= 1'b0;
                    vco_is_max  <= vco_p1_is_max_q;
                end
            end

            // Decoupled fast_end (output port) vs fast_end_sup (internal u_sup.range_fault -> kills repeater156!)
            if (search) begin
                fast_end     <= 1'b0;
                fast_end_sup <= 1'b0;
                slow_end     <= 1'b0;
            end else if (st_run_end && hold_z_end) begin
                if (track_en && hi_f && vco_is_zero) begin
                    fast_end     <= 1'b1;
                    fast_end_sup <= 1'b1;
                end else if (!hi_f) begin
                    fast_end     <= 1'b0;
                    fast_end_sup <= 1'b0;
                end
                if (track_en && !hi_f && lo_f && vco_is_max) slow_end <= 1'b1;
                else if (!lo_f)                              slow_end <= 1'b0;
            end

            // 1-gate switch_now + pre-registered sw_p1_q (1 mux!)
            if (switch_now) begin
                switches   <= sw_p1_q;
                sw_lo_is_f <= (sw_p1_q[3:0] == 4'hf);
            end
        end
    end
endmodule

module pll_coarse_ctrl #(
    parameter integer SETTLE_CYCLES = 512,
    parameter integer SAMPLE_DIV    = 16,
    parameter integer PERSIST       = 8,
    parameter integer HOLD_CYCLES   = 2048,
    parameter integer CODE_BITS     = 4
) (
    input  wire                 ref_clk,
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
    output wire [CODE_BITS-1:0] vco_code,
    output wire [3:0]           lo_code,
    output wire [3:0]           hi_code,
    output wire                 busy,
    output wire                 done,
    output wire                 fast_end,
    output wire                 slow_end,
    output wire [7:0]           switches
);
    /* verilator lint_off UNUSED */
    wire fast_end_sup_unused;
    /* verilator lint_on UNUSED */
    pll_coarse_ctrl_core #(
        .SETTLE_CYCLES(SETTLE_CYCLES), .SAMPLE_DIV(SAMPLE_DIV),
        .PERSIST(PERSIST), .HOLD_CYCLES(HOLD_CYCLES), .CODE_BITS(CODE_BITS)
    ) u_core (
        .ref_clk(ref_clk), .rst_n(rst_n), .search(search), .track_en(track_en), .tclass(tclass),
        .hi_async(hi_async), .lo_async(lo_async), .lo_run(lo_run), .hi_run(hi_run),
        .stop_code(stop_code), .stop_sel(stop_sel),
        .vco_code(vco_code), .lo_code(lo_code), .hi_code(hi_code),
        .busy(busy), .done(done), .fast_end(fast_end), .fast_end_sup(fast_end_sup_unused),
        .slow_end(slow_end), .switches(switches)
    );
endmodule
