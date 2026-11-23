// Timing-closed v2 PI step commutator (250 MHz / 4.0 ns SS-closed).
//   - Active-high st_busy_* & not_bot0_* (reset to 0 -> fast dfrtp instead of 1.41 ns dfstp!).
//   - Compact 4-bit select_a/select_b encodings (odd select_a & even select_b tied to 0).
//   - PIPE_IN=0 (default): bit- and cycle-exact with v1 pi_step_commutator (tb_pi_step_commutator).
//   - PIPE_IN=1 (rx_cdr_loop): 1-cycle pre-decoded command capture bank splits advance fanout
//     into per-group registered enables (1-2 SS gates per sink, ZERO repeaters!).
module pi_step_commutator #(
    parameter integer GUARD_CYCLES = 1,
    parameter integer PIPE_IN      = 0
) (
    input  wire       ctrl_clk,
    input  wire       rst_n,
    input  wire       step_valid,
    input  wire       advance,
    output wire       step_ready,
    output reg  [5:0] phase_code,
    output wire [7:0] select_a,
    output wire [7:0] select_b,
    output reg  [7:0] fine_b,
    output reg        applied,
    output reg        done
);
    localparam integer CW = (GUARD_CYCLES > 1) ? $clog2(GUARD_CYCLES) : 1;
    localparam [CW-1:0] GUARD_LAST = GUARD_CYCLES[CW-1:0] - 1'b1;

    // Active-high st_busy_* (resets to 0 -> fast dfrtp instead of slow dfstp!)
    (* keep = "true" *) reg st_busy_out, st_busy_p0, st_busy_p1;
    (* keep = "true" *) reg st_busy_fbl, st_busy_fbh, st_busy_fc0, st_busy_fc1, st_busy_fc2;
    (* keep = "true" *) reg st_busy_a, st_busy_b, st_busy_c;
    (* keep = "true" *) reg st_prep, st_prep_luta, st_prep_lutb, st_endp, st_endp_luta, st_endp_lutb, st_settle;

    wire st_idle_out = !st_busy_out;
    wire st_idle_p0  = !st_busy_p0;
    wire st_idle_p1  = !st_busy_p1;
    wire st_idle_fbl = !st_busy_fbl;
    wire st_idle_fbh = !st_busy_fbh;
    wire st_idle_fc0 = !st_busy_fc0;
    wire st_idle_fc1 = !st_busy_fc1;
    wire st_idle_fc2 = !st_busy_fc2;
    wire st_idle_a   = !st_busy_a;
    wire st_idle_b   = !st_busy_b;
    wire st_idle_c   = !st_busy_c;

    reg [CW-1:0] wait_count;
    reg [5:0]    pending_code;
    reg [7:0]    pending_f;

    // Compact 4-bit select_a (bits 6,4,2,0) & select_b (bits 7,5,3,1)
    reg [3:0]    sel_a4, sel_b4;
    reg [3:0]    pending_a4, pending_b4;
    reg [3:0]    c_p1_a4, c_m1_a4, c_p1_b4, c_m1_b4;

    // Active-low not_bot0_* (resets to 0 -> fast dfrtp!)
    reg          at_top7_q, not_bot0_q;
    (* keep = "true" *) reg at_top7_p, not_bot0_ab, pc3_fl, pc3_fh, pc3_p;
    (* keep = "true" *) reg f_up0_l, f_up0_h, f_dn0_l, f_dn0_h;
    reg [2:0]    pc_hi_p1_q, pc_hi_m1_q;

    wire at_bot0_q  = !not_bot0_q;
    wire at_bot0_ab = !not_bot0_ab;

    // Optional 1-cycle pre-decoded command capture bank (active only when PIPE_IN != 0)
    reg cmd_pend, cmd_pend_out;
    reg cmd_imm, cmd_prep, cmd_endp, cmd_prep_a, cmd_prep_b;
    reg cmd_up_l, cmd_dn_l, cmd_up_h, cmd_dn_h;
    reg cmd_fc0_go, cmd_adv_fc0, cmd_fc1_tog, cmd_fc2_go, cmd_adv_fc2, cmd_coarse_fc2;

    assign select_a = {1'b0, sel_a4[3], 1'b0, sel_a4[2], 1'b0, sel_a4[1], 1'b0, sel_a4[0]};
    assign select_b = {sel_b4[3], 1'b0, sel_b4[2], 1'b0, sel_b4[1], 1'b0, sel_b4[0], 1'b0};

    // Direct 3-input LUTs for decode_a4/b4(c +/- 1) (eliminates 3-bit adder before LUT -> +0.6 ns!)
    function automatic [3:0] decode_a4_p1(input [2:0] c);
        case (c)
            3'd0: decode_a4_p1 = 4'b0010;
            3'd1: decode_a4_p1 = 4'b0010;
            3'd2: decode_a4_p1 = 4'b0100;
            3'd3: decode_a4_p1 = 4'b0100;
            3'd4: decode_a4_p1 = 4'b1000;
            3'd5: decode_a4_p1 = 4'b1000;
            3'd6: decode_a4_p1 = 4'b0001;
            3'd7: decode_a4_p1 = 4'b0001;
        endcase
    endfunction

    function automatic [3:0] decode_a4_m1(input [2:0] c);
        case (c)
            3'd0: decode_a4_m1 = 4'b0001;
            3'd1: decode_a4_m1 = 4'b0001;
            3'd2: decode_a4_m1 = 4'b0010;
            3'd3: decode_a4_m1 = 4'b0010;
            3'd4: decode_a4_m1 = 4'b0100;
            3'd5: decode_a4_m1 = 4'b0100;
            3'd6: decode_a4_m1 = 4'b1000;
            3'd7: decode_a4_m1 = 4'b1000;
        endcase
    endfunction

    function automatic [3:0] decode_b4_p1(input [2:0] c);
        case (c)
            3'd0: decode_b4_p1 = 4'b0001;
            3'd1: decode_b4_p1 = 4'b0010;
            3'd2: decode_b4_p1 = 4'b0010;
            3'd3: decode_b4_p1 = 4'b0100;
            3'd4: decode_b4_p1 = 4'b0100;
            3'd5: decode_b4_p1 = 4'b1000;
            3'd6: decode_b4_p1 = 4'b1000;
            3'd7: decode_b4_p1 = 4'b0001;
        endcase
    endfunction

    function automatic [3:0] decode_b4_m1(input [2:0] c);
        case (c)
            3'd0: decode_b4_m1 = 4'b1000;
            3'd1: decode_b4_m1 = 4'b0001;
            3'd2: decode_b4_m1 = 4'b0001;
            3'd3: decode_b4_m1 = 4'b0010;
            3'd4: decode_b4_m1 = 4'b0010;
            3'd5: decode_b4_m1 = 4'b0100;
            3'd6: decode_b4_m1 = 4'b0100;
            3'd7: decode_b4_m1 = 4'b1000;
        endcase
    endfunction

    // Fast 3+3 split phase_code +/- 1
    wire adv_fc0 = (PIPE_IN != 0) ? cmd_adv_fc0 : advance;
    wire adv_fc2 = (PIPE_IN != 0) ? cmd_adv_fc2 : advance;
    wire [1:0] lo_p1_hi = phase_code[2:1] + {1'b0,  phase_code[0]};
    wire [1:0] lo_m1_hi = phase_code[2:1] - {1'b0, !phase_code[0]};
    wire       hi_inc   = adv_fc0 && at_top7_q;
    wire [2:0] nxt_lo   = {adv_fc0 ? lo_p1_hi : lo_m1_hi, !phase_code[0]};
    wire [2:0] nxt_hi   = hi_inc ? pc_hi_p1_q : phase_code[5:3];

    wire coarse_change_in   = (advance && at_top7_q) || (!advance && at_bot0_q);
    wire inactive_change_in = !advance && at_bot0_q;
    wire coarse_fc2         = (PIPE_IN != 0) ? cmd_coarse_fc2 : coarse_change_in;

    wire [7:0] next_f_up = {fine_b[6:0], 1'b1};
    wire [7:0] next_f_dn = {1'b0, fine_b[7:1]};

    wire nxt_top7_imm = adv_fc2 ? (phase_code[2:0] == 3'd6) : at_bot0_q;
    wire nxt_bot0_imm = adv_fc2 ? at_top7_q : (phase_code[2:0] == 3'd1);

    wire [2:0] lut_ca_base = st_prep_luta ? pending_code[5:3] : phase_code[5:3];
    wire [2:0] lut_cb_base = st_prep_lutb ? pending_code[5:3] : phase_code[5:3];
    wire [2:0] lut_ca_p1   = lut_ca_base + 3'd1;
    wire [2:0] lut_ca_m1   = lut_ca_base - 3'd1;
    wire       lut_en_a    = st_prep_luta || st_endp_luta;
    wire       lut_en_b    = st_prep_lutb || st_endp_lutb;

    wire wait_done    = (wait_count == GUARD_LAST);
    wire fire_in      = st_idle_c && !cmd_pend && step_valid;
    wire idle_fire    = st_idle_c && step_valid;
    wire idle_imm     = (PIPE_IN != 0) ? cmd_imm  : (idle_fire && !coarse_change_in);
    wire idle_prep    = (PIPE_IN != 0) ? cmd_prep : (idle_fire &&  inactive_change_in);
    wire idle_endp    = (PIPE_IN != 0) ? cmd_endp : (idle_fire &&  coarse_change_in && !inactive_change_in);
    wire prep_done    = st_prep   && wait_done;
    wire endp_done    = st_endp   && wait_done;
    wire settle_done  = st_settle && wait_done;

    // Dedicated fanout-4 enables for sel_a4 and sel_b4
    wire idle_prep_a  = (PIPE_IN != 0) ? cmd_prep_a : (st_idle_a && step_valid && !advance && at_bot0_ab);
    wire idle_prep_b  = (PIPE_IN != 0) ? cmd_prep_b : (st_idle_b && step_valid && !advance && at_bot0_ab);

    // Split 4+4 fine_b controls
    wire fb_go_l        = st_idle_fbl && step_valid;
    wire fb_go_h        = st_idle_fbh && step_valid;
    wire fine_fire_up_l = (PIPE_IN != 0) ? cmd_up_l : (fb_go_l && (advance ? !pc3_fl : f_up0_l));
    wire fine_fire_dn_l = (PIPE_IN != 0) ? cmd_dn_l : (fb_go_l && (advance ?  pc3_fl : f_dn0_l));
    wire fine_fire_up_h = (PIPE_IN != 0) ? cmd_up_h : (fb_go_h && (advance ? !pc3_fh : f_up0_h));
    wire fine_fire_dn_h = (PIPE_IN != 0) ? cmd_dn_h : (fb_go_h && (advance ?  pc3_fh : f_dn0_h));

    // Split 3 small update enables for phase_code / pc3 / boundary flags
    wire fc0_go  = (PIPE_IN != 0) ? cmd_fc0_go  : (st_idle_fc0 && step_valid && !inactive_change_in);
    wire fc1_tog = (PIPE_IN != 0) ? cmd_fc1_tog : (st_idle_fc1 && step_valid && advance && at_top7_p);
    wire fc2_go  = (PIPE_IN != 0) ? cmd_fc2_go  : (st_idle_fc2 && step_valid && !inactive_change_in);

    wire nxt_prep   = idle_prep || (st_prep   && !wait_done);
    wire nxt_endp   = idle_endp || (st_endp   && !wait_done);
    wire nxt_settle = endp_done || (st_settle && !wait_done);
    wire nxt_busy   = nxt_prep || nxt_endp || nxt_settle;

    assign step_ready = (PIPE_IN != 0) ? (st_idle_out && !cmd_pend_out) : st_idle_out;

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            st_busy_out <= 1'b0; st_busy_p0 <= 1'b0; st_busy_p1 <= 1'b0;
            st_busy_fbl <= 1'b0; st_busy_fbh <= 1'b0;
            st_busy_fc0 <= 1'b0; st_busy_fc1 <= 1'b0; st_busy_fc2 <= 1'b0;
            st_busy_a   <= 1'b0; st_busy_b  <= 1'b0; st_busy_c  <= 1'b0;
            st_prep     <= 1'b0; st_prep_luta <= 1'b0; st_prep_lutb <= 1'b0;
            st_endp     <= 1'b0; st_endp_luta <= 1'b0; st_endp_lutb <= 1'b0;
            st_settle   <= 1'b0;
            cmd_pend    <= 1'b0; cmd_pend_out <= 1'b0;
            cmd_imm     <= 1'b0; cmd_prep <= 1'b0; cmd_endp <= 1'b0;
            cmd_prep_a  <= 1'b0; cmd_prep_b <= 1'b0;
            cmd_up_l    <= 1'b0; cmd_dn_l <= 1'b0; cmd_up_h <= 1'b0; cmd_dn_h <= 1'b0;
            cmd_fc0_go  <= 1'b0; cmd_adv_fc0 <= 1'b0; cmd_fc1_tog <= 1'b0;
            cmd_fc2_go  <= 1'b0; cmd_adv_fc2 <= 1'b0; cmd_coarse_fc2 <= 1'b0;
            wait_count  <= {CW{1'b0}};
            phase_code  <= 6'd0;
            pc_hi_p1_q  <= 3'd1; pc_hi_m1_q <= 3'd7;
            pc3_fl      <= 1'b0; pc3_fh <= 1'b0; pc3_p <= 1'b0;
            f_up0_l     <= 1'b0; f_up0_h <= 1'b0;
            f_dn0_l     <= 1'b0; f_dn0_h <= 1'b0;
            sel_a4      <= 4'b0001;
            sel_b4      <= 4'b0001;
            fine_b      <= 8'h00;
            pending_code <= 6'd0;
            pending_a4   <= 4'b0000;
            pending_b4   <= 4'b0000;
            pending_f    <= 8'h00;
            at_top7_q    <= 1'b0; at_top7_p <= 1'b0;
            not_bot0_q   <= 1'b0; not_bot0_ab <= 1'b0;
            c_p1_a4      <= 4'b0010;
            c_m1_a4      <= 4'b0001;
            c_p1_b4      <= 4'b0001;
            c_m1_b4      <= 4'b1000;
            applied      <= 1'b0;
            done         <= 1'b0;
        end else begin
            st_busy_out <= nxt_busy; st_busy_p0 <= nxt_busy; st_busy_p1 <= nxt_busy;
            st_busy_fbl <= nxt_busy; st_busy_fbh <= nxt_busy;
            st_busy_fc0 <= nxt_busy; st_busy_fc1 <= nxt_busy; st_busy_fc2 <= nxt_busy;
            st_busy_a   <= nxt_busy; st_busy_b  <= nxt_busy; st_busy_c  <= nxt_busy;
            st_prep     <= nxt_prep; st_prep_luta <= nxt_prep; st_prep_lutb <= nxt_prep;
            st_endp     <= nxt_endp; st_endp_luta <= nxt_endp; st_endp_lutb <= nxt_endp;
            st_settle   <= nxt_settle;

            if (PIPE_IN != 0) begin
                cmd_pend       <= fire_in;
                cmd_pend_out   <= fire_in;
                cmd_imm        <= fire_in && !coarse_change_in;
                cmd_prep       <= fire_in &&  inactive_change_in;
                cmd_endp       <= fire_in &&  coarse_change_in && !inactive_change_in;
                cmd_prep_a     <= fire_in && !advance && at_bot0_ab;
                cmd_prep_b     <= fire_in && !advance && at_bot0_ab;
                cmd_up_l       <= fire_in && (advance ? !pc3_fl : f_up0_l);
                cmd_dn_l       <= fire_in && (advance ?  pc3_fl : f_dn0_l);
                cmd_up_h       <= fire_in && (advance ? !pc3_fh : f_up0_h);
                cmd_dn_h       <= fire_in && (advance ?  pc3_fh : f_dn0_h);
                cmd_fc0_go     <= fire_in && !inactive_change_in;
                cmd_adv_fc0    <= advance;
                cmd_fc1_tog    <= fire_in && advance && at_top7_p;
                cmd_fc2_go     <= fire_in && !inactive_change_in;
                cmd_adv_fc2    <= advance;
                cmd_coarse_fc2 <= coarse_change_in;
            end

            applied <= idle_imm || idle_endp || prep_done;
            done    <= idle_imm || prep_done || settle_done;

            if (st_idle_c || wait_done) wait_count <= {CW{1'b0}};
            else                        wait_count <= wait_count + 1'b1;

            // pending_code/pending_f ONLY used on prep_done (advance==0, at_bot0==1 -> ZERO advance!)
            if (st_idle_p0) begin
                pending_code <= {pc_hi_m1_q, 3'd7};
                pending_f    <= (!pc3_p) ? next_f_up : next_f_dn;
            end

            // pending_a4/b4 ONLY used on endp_done (advance==1 -> ALWAYS c_p1_a4/b4, ZERO advance!)
            if (st_idle_p1) begin
                pending_a4 <= c_p1_a4;
                pending_b4 <= c_p1_b4;
            end

            if (lut_en_a) begin
                c_p1_a4    <= decode_a4_p1(lut_ca_base);
                c_m1_a4    <= decode_a4_m1(lut_ca_base);
                pc_hi_p1_q <= lut_ca_p1;
                pc_hi_m1_q <= lut_ca_m1;
            end
            if (lut_en_b) begin
                c_p1_b4    <= decode_b4_p1(lut_cb_base);
                c_m1_b4    <= decode_b4_m1(lut_cb_base);
            end

            // Parallel flat 4+4 fine_b update (fanout = 4, 1-2 SS gates!)
            if (fine_fire_up_l)      fine_b[3:0] <= next_f_up[3:0];
            else if (fine_fire_dn_l) fine_b[3:0] <= next_f_dn[3:0];
            else if (prep_done)      fine_b[3:0] <= pending_f[3:0];

            if (fine_fire_up_h)      fine_b[7:4] <= next_f_up[7:4];
            else if (fine_fire_dn_h) fine_b[7:4] <= next_f_dn[7:4];
            else if (prep_done)      fine_b[7:4] <= pending_f[7:4];

            // Split 1: phase_code (6 FFs)
            if (fc0_go)         phase_code <= {nxt_hi, nxt_lo};
            else if (prep_done) phase_code <= pending_code;

            // Split 2: pc3_fl/fh/p (3 FFs)
            if (fc1_tog) begin
                pc3_fl <= !pc3_fl;
                pc3_fh <= !pc3_fh;
                pc3_p  <= !pc3_p;
            end else if (prep_done) begin
                pc3_fl <= pending_code[3];
                pc3_fh <= pending_code[3];
                pc3_p  <= pending_code[3];
            end

            // Split 3: boundary & pre-decoded fine flags (8 FFs)
            if (fc2_go) begin
                at_top7_q   <= coarse_fc2 ? 1'b0 : nxt_top7_imm;
                at_top7_p   <= coarse_fc2 ? 1'b0 : nxt_top7_imm;
                not_bot0_q  <= coarse_fc2 ? 1'b0 : !nxt_bot0_imm;
                not_bot0_ab <= coarse_fc2 ? 1'b0 : !nxt_bot0_imm;
                f_up0_l     <= !coarse_fc2 && !nxt_bot0_imm &&  pc3_p;
                f_up0_h     <= !coarse_fc2 && !nxt_bot0_imm &&  pc3_p;
                f_dn0_l     <= !coarse_fc2 && !nxt_bot0_imm && !pc3_p;
                f_dn0_h     <= !coarse_fc2 && !nxt_bot0_imm && !pc3_p;
            end else if (prep_done) begin
                at_top7_q   <= 1'b1;
                at_top7_p   <= 1'b1;
                not_bot0_q  <= 1'b1;
                not_bot0_ab <= 1'b1;
                f_up0_l     <=  pending_code[3];
                f_up0_h     <=  pending_code[3];
                f_dn0_l     <= !pending_code[3];
                f_dn0_h     <= !pending_code[3];
            end

            // 4-bit select_a & select_b: on idle_prep advance==0 so ALWAYS load c_m1_a4/b4!
            if (idle_prep_a)    sel_a4 <= c_m1_a4;
            else if (endp_done) sel_a4 <= pending_a4;

            if (idle_prep_b)    sel_b4 <= c_m1_b4;
            else if (endp_done) sel_b4 <= pending_b4;
        end
    end
endmodule
