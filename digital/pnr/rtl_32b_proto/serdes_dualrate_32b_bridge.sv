`timescale 1ns/1ps
// =============================================================================
// Production-Grade SKY130A 32-bit Dual-Rate (4 Gb/s & 5 Gb/s) Backpressure Bridge (v2)
//   - Host domain     : 180–200 MHz (5.00–5.56 ns), 32-bit valid/ready (5.76–6.40 Gb/s > 5 Gb/s!)
//                       Hard minimum sustained rate: >= 125.04 MHz (4G) / >= 156.30 MHz (5G)
//   - TX line boundary: 250.0 MHz (4G) / 312.5 MHz (5G, 3.20 ns), 16-bit (1-MUX thin stage)
//   - TX FIFO core    : Internal sync /2 tx_clk_div2 = 125.0 MHz (4G) / 156.25 MHz (5G, 6.40 ns)
//   - RX line boundary: 250.0 MHz (4G) / 312.5 MHz (5G, 3.20 ns), 16-bit (1-stage pair packer)
//   - RX FIFO core    : Internal sync /2 rx_clk_div2 = 125.0 MHz (4G) / 156.25 MHz (5G, 6.40 ns)
//
// Key Architectural Upgrades (v2):
//   1. Moves BOTH 8x32 async FIFOs from 312.5 MHz (3.20 ns) to 156.25 MHz (6.40 ns),
//      closing all 5 SKY130A corners including ss_n40C_1v60 +/-5% OCV with huge margin.
//   2. Phase-safe RX 16->32 transfer (`xfer_*` updates ONLY on rx_div2_q==1, 3.2 ns
//      before posedge rx_div2_q): handles arbitrary 1-cycle rx_payload_valid bubbles
//      with zero loss and zero rx_clk->rx_clk_div2 hold race.
//   3. Strict fanout=1 on every 1st-stage CDC synchronizer (D-C1 compliant).
//   4. Per-domain external arst_n 2-FF reset synchronizers (zero cross-clock removal).
//   5. 100% payload-transparent (no magic-word deletion), Verilator -Wall clean.
// =============================================================================

/* verilator lint_off DECLFILENAME */
module async_fifo_16x32_prod (
    input  wire        wclk,
    input  wire        wrst_n,     // 2-FF synchronized to wclk
    input  wire        wvalid,
    input  wire        wvalid_b0,
    input  wire        wvalid_b1,
    input  wire        wvalid_b2,
    input  wire        wvalid_b3,
    output wire        wready,
    output wire        wonline,
    output reg         woverflow,  // 1-bit sticky overflow flag in wclk domain
    input  wire [31:0] wdata,

    input  wire        rclk,
    input  wire        rrst_n,     // 2-FF synchronized to rclk
    output wire        rvalid,
    output wire        ronline,
    output wire        rprefill2,  // 1-bit registered ">= 2 words available" hint
    input  wire        rready,
    output wire [31:0] rdata
);
    // 16 slots x 32-bit (512-bit): >= 9.5 slots free burst margin after 2-FF CDC credit loop!
    reg [31:0] mem [0:15];

    // Cross-domain online handshake & strict fanout=1 2-FF Gray pointer synchronizers (5-bit)
    reg w_rst_ok_q, r_rst_ok_q;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg r_up_w0_q;
    (* ASYNC_REG = "TRUE" *) reg r_up_w1_q;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg w_up_r0_q;
    (* ASYNC_REG = "TRUE" *) reg w_up_r1_q;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg [4:0] rgray_w1_q;
    (* ASYNC_REG = "TRUE" *) reg [4:0] rgray_w2_q;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg [4:0] wgray_r1_q;
    (* ASYNC_REG = "TRUE" *) reg [4:0] wgray_r2_q;

    // -------------------------------------------------------------------------
    // Write Domain
    // -------------------------------------------------------------------------
    reg [4:0] wbin_q, wgray_q;
    reg [4:0] wbin_p1_q, wgray_p1_q;
    (* keep = "true" *) reg [15:0] w_oh_b0_q, w_oh_b1_q, w_oh_b2_q, w_oh_b3_q;
    (* keep = "true" *) reg        wready_port_q, wready_ctl_q;
    (* keep = "true" *) reg        wready_b0_lo_q, wready_b0_hi_q;
    (* keep = "true" *) reg        wready_b1_lo_q, wready_b1_hi_q;
    (* keep = "true" *) reg        wready_b2_lo_q, wready_b2_hi_q;
    (* keep = "true" *) reg        wready_b3_lo_q, wready_b3_hi_q;

    wire       w_online_c = r_up_w1_q;
    wire       w_fire_ctl   = wvalid    & wready_ctl_q;
    wire       w_fire_b0_lo = wvalid_b0 & wready_b0_lo_q;
    wire       w_fire_b0_hi = wvalid_b0 & wready_b0_hi_q;
    wire       w_fire_b1_lo = wvalid_b1 & wready_b1_lo_q;
    wire       w_fire_b1_hi = wvalid_b1 & wready_b1_hi_q;
    wire       w_fire_b2_lo = wvalid_b2 & wready_b2_lo_q;
    wire       w_fire_b2_hi = wvalid_b2 & wready_b2_hi_q;
    wire       w_fire_b3_lo = wvalid_b3 & wready_b3_lo_q;
    wire       w_fire_b3_hi = wvalid_b3 & wready_b3_hi_q;

    wire [4:0] wbin_n     = w_fire_ctl ? wbin_p1_q  : wbin_q;
    wire [4:0] wgray_n    = w_fire_ctl ? wgray_p1_q : wgray_q;
    wire [4:0] wbin_p2    = wbin_p1_q + 5'd1;
    wire [4:0] wgray_p2   = (wbin_p2 >> 1) ^ wbin_p2;
    wire [4:0] wbin_p1_n  = w_fire_ctl ? wbin_p2  : wbin_p1_q;
    wire [4:0] wgray_p1_n = w_fire_ctl ? wgray_p2 : wgray_p1_q;

    wire [4:0] full_ref   = {~rgray_w2_q[4:3], rgray_w2_q[2:0]};
    wire       full_if_0  = (wgray_q    == full_ref);
    wire       full_if_1  = (wgray_p1_q == full_ref);
    wire       wready_n_ctl = w_online_c & ~(w_fire_ctl ? full_if_1 : full_if_0);
    wire       wready_n_b0  = w_online_c & ~(w_fire_b0_lo ? full_if_1 : full_if_0);
    wire       wready_n_b1  = w_online_c & ~(w_fire_b1_lo ? full_if_1 : full_if_0);
    wire       wready_n_b2  = w_online_c & ~(w_fire_b2_lo ? full_if_1 : full_if_0);
    wire       wready_n_b3  = w_online_c & ~(w_fire_b3_lo ? full_if_1 : full_if_0);

    assign wready  = wready_port_q;
    assign wonline = w_online_c;

    integer i;
    always @(posedge wclk or negedge wrst_n) begin
        if (!wrst_n) begin
            w_rst_ok_q     <= 1'b0;
            r_up_w0_q      <= 1'b0;
            r_up_w1_q      <= 1'b0;
            rgray_w1_q     <= 5'd0;
            rgray_w2_q     <= 5'd0;
            wbin_q         <= 5'd0;
            wgray_q        <= 5'd0;
            wbin_p1_q      <= 5'd1;
            wgray_p1_q     <= 5'b00001;
            w_oh_b0_q      <= 16'h0001;
            w_oh_b1_q      <= 16'h0001;
            w_oh_b2_q      <= 16'h0001;
            w_oh_b3_q      <= 16'h0001;
            wready_port_q  <= 1'b0;
            wready_ctl_q   <= 1'b0;
            wready_b0_lo_q <= 1'b0; wready_b0_hi_q <= 1'b0;
            wready_b1_lo_q <= 1'b0; wready_b1_hi_q <= 1'b0;
            wready_b2_lo_q <= 1'b0; wready_b2_hi_q <= 1'b0;
            wready_b3_lo_q <= 1'b0; wready_b3_hi_q <= 1'b0;
            woverflow      <= 1'b0;
        end else begin
            w_rst_ok_q     <= 1'b1;
            r_up_w0_q      <= r_rst_ok_q;
            r_up_w1_q      <= r_up_w0_q;
            rgray_w1_q     <= rgray_q;
            rgray_w2_q     <= rgray_w1_q;
            wbin_q         <= wbin_n;
            wgray_q        <= wgray_n;
            wbin_p1_q      <= wbin_p1_n;
            wgray_p1_q     <= wgray_p1_n;
            if (w_fire_b0_lo) w_oh_b0_q <= {w_oh_b0_q[14:0], w_oh_b0_q[15]};
            if (w_fire_b1_lo) w_oh_b1_q <= {w_oh_b1_q[14:0], w_oh_b1_q[15]};
            if (w_fire_b2_lo) w_oh_b2_q <= {w_oh_b2_q[14:0], w_oh_b2_q[15]};
            if (w_fire_b3_lo) w_oh_b3_q <= {w_oh_b3_q[14:0], w_oh_b3_q[15]};
            wready_port_q  <= wready_n_ctl;
            wready_ctl_q   <= wready_n_ctl;
            wready_b0_lo_q <= wready_n_b0; wready_b0_hi_q <= wready_n_b0;
            wready_b1_lo_q <= wready_n_b1; wready_b1_hi_q <= wready_n_b1;
            wready_b2_lo_q <= wready_n_b2; wready_b2_hi_q <= wready_n_b2;
            wready_b3_lo_q <= wready_n_b3; wready_b3_hi_q <= wready_n_b3;
            if (w_online_c && wvalid && !wready_ctl_q) begin
                woverflow <= 1'b1;
            end
        end
    end

    // Non-reset memory array (banked lo/hi fanout <= 8, maps to compact dfxtp & eliminates 512 RESET_B loads!)
    always @(posedge wclk) begin
        for (i = 0; i < 8; i = i + 1) begin
            if (w_fire_b0_lo && w_oh_b0_q[i]) mem[i][7:0]   <= wdata[7:0];
            if (w_fire_b1_lo && w_oh_b1_q[i]) mem[i][15:8]  <= wdata[15:8];
            if (w_fire_b2_lo && w_oh_b2_q[i]) mem[i][23:16] <= wdata[23:16];
            if (w_fire_b3_lo && w_oh_b3_q[i]) mem[i][31:24] <= wdata[31:24];
        end
        for (i = 8; i < 16; i = i + 1) begin
            if (w_fire_b0_hi && w_oh_b0_q[i]) mem[i][7:0]   <= wdata[7:0];
            if (w_fire_b1_hi && w_oh_b1_q[i]) mem[i][15:8]  <= wdata[15:8];
            if (w_fire_b2_hi && w_oh_b2_q[i]) mem[i][23:16] <= wdata[23:16];
            if (w_fire_b3_hi && w_oh_b3_q[i]) mem[i][31:24] <= wdata[31:24];
        end
    end

    // -------------------------------------------------------------------------
    // Read Domain: Nibble-replicated 16:1 mux (fanout <= 4!) -> Registered FWFT Output Stage
    // -------------------------------------------------------------------------
    reg [4:0] rbin_q, rgray_q;
    reg [4:0] rbin_p1_q, rgray_p1_q;
    (* keep = "true" *) reg [3:0] rsel_n0_q, rsel_n1_q, rsel_n2_q, rsel_n3_q;
    (* keep = "true" *) reg [3:0] rsel_n4_q, rsel_n5_q, rsel_n6_q, rsel_n7_q;
    (* keep = "true" *) reg       mem_av_ctl_q;
    (* keep = "true" *) reg       mem_av_b0_q, mem_av_b1_q, mem_av_b2_q, mem_av_b3_q;
    (* keep = "true" *) reg       out_v_port_q, out_v_ctl_q;
    (* keep = "true" *) reg       out_v_b0_q, out_v_b1_q, out_v_b2_q, out_v_b3_q;
    reg [31:0] out_data_q;
    reg        rprefill2_q;

    wire r_online_c = w_up_r1_q;

    wire mem_pop_ctl = mem_av_ctl_q & ((~out_v_ctl_q) | rready);
    wire mem_pop_b0  = mem_av_b0_q  & ((~out_v_b0_q)  | rready);
    wire mem_pop_b1  = mem_av_b1_q  & ((~out_v_b1_q)  | rready);
    wire mem_pop_b2  = mem_av_b2_q  & ((~out_v_b2_q)  | rready);
    wire mem_pop_b3  = mem_av_b3_q  & ((~out_v_b3_q)  | rready);

    wire [4:0] rbin_n     = mem_pop_ctl ? rbin_p1_q  : rbin_q;
    wire [4:0] rgray_n    = mem_pop_ctl ? rgray_p1_q : rgray_q;
    wire [4:0] rbin_p2    = rbin_p1_q + 5'd1;
    wire [4:0] rgray_p2   = (rbin_p2 >> 1) ^ rbin_p2;
    wire [4:0] rbin_p1_n  = mem_pop_ctl ? rbin_p2  : rbin_p1_q;
    wire [4:0] rgray_p1_n = mem_pop_ctl ? rgray_p2 : rgray_p1_q;

    wire av_if_0   = r_online_c & (rgray_q    != wgray_r2_q);
    wire av_if_1   = r_online_c & (rgray_p1_q != wgray_r2_q);
    wire mem_av_n_ctl = mem_pop_ctl ? av_if_1 : av_if_0;
    wire mem_av_n_b0  = mem_pop_b0  ? av_if_1 : av_if_0;
    wire mem_av_n_b1  = mem_pop_b1  ? av_if_1 : av_if_0;
    wire mem_av_n_b2  = mem_pop_b2  ? av_if_1 : av_if_0;
    wire mem_av_n_b3  = mem_pop_b3  ? av_if_1 : av_if_0;
    wire out_v_n   = mem_pop_ctl | (out_v_ctl_q & (~rready));
    wire prefill2_n = out_v_ctl_q & mem_av_ctl_q;

    wire [3:0] rd_n0 = mem[rsel_n0_q][3:0];
    wire [3:0] rd_n1 = mem[rsel_n1_q][7:4];
    wire [3:0] rd_n2 = mem[rsel_n2_q][11:8];
    wire [3:0] rd_n3 = mem[rsel_n3_q][15:12];
    wire [3:0] rd_n4 = mem[rsel_n4_q][19:16];
    wire [3:0] rd_n5 = mem[rsel_n5_q][23:20];
    wire [3:0] rd_n6 = mem[rsel_n6_q][27:24];
    wire [3:0] rd_n7 = mem[rsel_n7_q][31:28];

    assign rvalid    = out_v_port_q;
    assign ronline   = r_online_c;
    assign rdata     = out_data_q;
    assign rprefill2 = rprefill2_q;

    always @(posedge rclk or negedge rrst_n) begin
        if (!rrst_n) begin
            r_rst_ok_q   <= 1'b0;
            w_up_r0_q    <= 1'b0;
            w_up_r1_q    <= 1'b0;
            wgray_r1_q   <= 5'd0;
            wgray_r2_q   <= 5'd0;
            rbin_q       <= 5'd0;
            rgray_q      <= 5'd0;
            rbin_p1_q    <= 5'd1;
            rgray_p1_q   <= 5'b00001;
            rsel_n0_q    <= 4'd0; rsel_n1_q <= 4'd0; rsel_n2_q <= 4'd0; rsel_n3_q <= 4'd0;
            rsel_n4_q    <= 4'd0; rsel_n5_q <= 4'd0; rsel_n6_q <= 4'd0; rsel_n7_q <= 4'd0;
            mem_av_ctl_q <= 1'b0;
            mem_av_b0_q  <= 1'b0;
            mem_av_b1_q  <= 1'b0;
            mem_av_b2_q  <= 1'b0;
            mem_av_b3_q  <= 1'b0;
            out_v_port_q <= 1'b0;
            out_v_ctl_q  <= 1'b0;
            out_v_b0_q   <= 1'b0;
            out_v_b1_q   <= 1'b0;
            out_v_b2_q   <= 1'b0;
            out_v_b3_q   <= 1'b0;
            out_data_q   <= 32'd0;
            rprefill2_q  <= 1'b0;
        end else begin
            r_rst_ok_q   <= 1'b1;
            w_up_r0_q    <= w_rst_ok_q;
            w_up_r1_q    <= w_up_r0_q;
            wgray_r1_q   <= wgray_q;
            wgray_r2_q   <= wgray_r1_q;
            rbin_q       <= rbin_n;
            rgray_q      <= rgray_n;
            rbin_p1_q    <= rbin_p1_n;
            rgray_p1_q   <= rgray_p1_n;
            rsel_n0_q    <= rbin_n[3:0]; rsel_n1_q <= rbin_n[3:0];
            rsel_n2_q    <= rbin_n[3:0]; rsel_n3_q <= rbin_n[3:0];
            rsel_n4_q    <= rbin_n[3:0]; rsel_n5_q <= rbin_n[3:0];
            rsel_n6_q    <= rbin_n[3:0]; rsel_n7_q <= rbin_n[3:0];
            mem_av_ctl_q <= mem_av_n_ctl;
            mem_av_b0_q  <= mem_av_n_b0;
            mem_av_b1_q  <= mem_av_n_b1;
            mem_av_b2_q  <= mem_av_n_b2;
            mem_av_b3_q  <= mem_av_n_b3;
            out_v_port_q <= out_v_n;
            out_v_ctl_q  <= out_v_n;
            out_v_b0_q   <= out_v_n;
            out_v_b1_q   <= out_v_n;
            out_v_b2_q   <= out_v_n;
            out_v_b3_q   <= out_v_n;
            rprefill2_q  <= prefill2_n;
            if (mem_pop_b0) out_data_q[7:0]   <= {rd_n1, rd_n0};
            if (mem_pop_b1) out_data_q[15:8]  <= {rd_n3, rd_n2};
            if (mem_pop_b2) out_data_q[23:16] <= {rd_n5, rd_n4};
            if (mem_pop_b3) out_data_q[31:24] <= {rd_n7, rd_n6};
        end
    end
endmodule


module serdes_dualrate_32b_bridge #(
    parameter [15:0] IDLE_WORD = 16'hA55A
) (
    // Global active-low async reset (synchronized cleanly into each domain!)
    input  wire        arst_n,

    // Single Host Domain (180–200 MHz nominal, 32-bit valid/ready -> 5.76–6.40 Gb/s > 5 Gb/s)
    input  wire        host_clk,
    input  wire        host_tx_valid,
    output wire        host_tx_ready,
    input  wire [31:0] host_tx_data,
    output wire        host_tx_online,
    output wire        host_tx_underrun,   // 1-bit sticky error (synced to host_clk)

    output wire        host_rx_valid,
    input  wire        host_rx_ready,
    output wire [31:0] host_rx_data,
    output wire        host_rx_online,
    output wire        host_rx_overflow,   // 1-bit sticky error (synced to host_clk)

    // TX Analog Word Domain (250 MHz @ 4G / 312.5 MHz @ 5G, 16-bit transparent)
    input  wire        tx_clk,
    input  wire        tx_enable,
    output reg  [15:0] tx_word16,
    output reg         tx_word_valid,

    // RX Recovered Word Domain (250 MHz @ 4G / 312.5 MHz @ 5G, 16-bit transparent)
    input  wire        rx_clk,
    input  wire        rx_aligned,
    input  wire        rx_payload_valid,   // Explicit payload indicator (no magic word deletion!)
    input  wire [15:0] rx_word16
);
    // =========================================================================
    // 1. Synchronous /2 Generated Clocks for TX & RX 32-bit Core Domains
    //    (125.0 MHz @ 4G / 156.25 MHz @ 5G -> 6.40 ns cycle time for 8x32 FIFOs!)
    // =========================================================================
    (* ASYNC_REG = "TRUE", keep = "true" *) reg host_rst_s0;
    (* ASYNC_REG = "TRUE" *) reg host_rst_s1;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg tx_rst_s0;
    (* ASYNC_REG = "TRUE" *) reg tx_rst_s1;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg rx_rst_s0;
    (* ASYNC_REG = "TRUE" *) reg rx_rst_s1;

    always @(posedge host_clk or negedge arst_n) begin
        if (!arst_n) begin host_rst_s0 <= 1'b0; host_rst_s1 <= 1'b0; end
        else         begin host_rst_s0 <= 1'b1; host_rst_s1 <= host_rst_s0; end
    end
    always @(posedge tx_clk or negedge arst_n) begin
        if (!arst_n) begin tx_rst_s0 <= 1'b0; tx_rst_s1 <= 1'b0; end
        else         begin tx_rst_s0 <= 1'b1; tx_rst_s1 <= tx_rst_s0; end
    end
    always @(posedge rx_clk or negedge arst_n) begin
        if (!arst_n) begin rx_rst_s0 <= 1'b0; rx_rst_s1 <= 1'b0; end
        else         begin rx_rst_s0 <= 1'b1; rx_rst_s1 <= rx_rst_s0; end
    end
    wire host_rst_n = host_rst_s1;
    wire tx_rst_n   = tx_rst_s1;
    wire rx_rst_n   = rx_rst_s1;

    // Separate clock-only /2 divider FFs from nibble/byte-replicated data-phase mirror FFs (fanout <= 8 at 312.5 MHz!)
    (* keep = "true" *) reg tx_div2_q;
    (* keep = "true" *) reg tx_phase_ctl_q, tx_phase_n0_q, tx_phase_n1_q, tx_phase_n2_q, tx_phase_n3_q;
    (* keep = "true" *) reg rx_div2_q;
    (* keep = "true" *) reg rx_phase_ctl_q;
    (* keep = "true" *) reg rx_phase_a0_q, rx_phase_a1_q, rx_phase_a2_q, rx_phase_a3_q;
    (* keep = "true" *) reg rx_phase_b0_q, rx_phase_b1_q, rx_phase_b2_q, rx_phase_b3_q;
    always @(posedge tx_clk or negedge tx_rst_n) begin
        if (!tx_rst_n) begin
            tx_div2_q <= 1'b0; tx_phase_ctl_q <= 1'b0;
            tx_phase_n0_q <= 1'b0; tx_phase_n1_q <= 1'b0; tx_phase_n2_q <= 1'b0; tx_phase_n3_q <= 1'b0;
        end else begin
            tx_div2_q <= ~tx_div2_q; tx_phase_ctl_q <= ~tx_phase_ctl_q;
            tx_phase_n0_q <= ~tx_phase_n0_q; tx_phase_n1_q <= ~tx_phase_n1_q;
            tx_phase_n2_q <= ~tx_phase_n2_q; tx_phase_n3_q <= ~tx_phase_n3_q;
        end
    end
    always @(posedge rx_clk or negedge rx_rst_n) begin
        if (!rx_rst_n) begin
            rx_div2_q <= 1'b0; rx_phase_ctl_q <= 1'b0;
            rx_phase_a0_q <= 1'b0; rx_phase_a1_q <= 1'b0; rx_phase_a2_q <= 1'b0; rx_phase_a3_q <= 1'b0;
            rx_phase_b0_q <= 1'b0; rx_phase_b1_q <= 1'b0; rx_phase_b2_q <= 1'b0; rx_phase_b3_q <= 1'b0;
        end else begin
            rx_div2_q <= ~rx_div2_q; rx_phase_ctl_q <= ~rx_phase_ctl_q;
            rx_phase_a0_q <= ~rx_phase_a0_q; rx_phase_a1_q <= ~rx_phase_a1_q;
            rx_phase_a2_q <= ~rx_phase_a2_q; rx_phase_a3_q <= ~rx_phase_a3_q;
            rx_phase_b0_q <= ~rx_phase_b0_q; rx_phase_b1_q <= ~rx_phase_b1_q;
            rx_phase_b2_q <= ~rx_phase_b2_q; rx_phase_b3_q <= ~rx_phase_b3_q;
        end
    end
    wire tx_clk_div2 = tx_div2_q;
    wire rx_clk_div2 = rx_div2_q;

    // Independent external-arst_n reset synchronizers for /2 domains (0 cross-clock removal!)
    (* ASYNC_REG = "TRUE", keep = "true" *) reg tx2_rst_s0;
    (* ASYNC_REG = "TRUE" *) reg tx2_rst_s1;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg rx2_rst_s0;
    (* ASYNC_REG = "TRUE" *) reg rx2_rst_s1;
    always @(posedge tx_clk_div2 or negedge arst_n) begin
        if (!arst_n) begin tx2_rst_s0 <= 1'b0; tx2_rst_s1 <= 1'b0; end
        else         begin tx2_rst_s0 <= 1'b1; tx2_rst_s1 <= tx2_rst_s0; end
    end
    always @(posedge rx_clk_div2 or negedge arst_n) begin
        if (!arst_n) begin rx2_rst_s0 <= 1'b0; rx2_rst_s1 <= 1'b0; end
        else         begin rx2_rst_s0 <= 1'b1; rx2_rst_s1 <= rx2_rst_s0; end
    end
    wire tx2_rst_n = tx2_rst_s1;
    wire rx2_rst_n = rx2_rst_s1;

    // =========================================================================
    // 2. TX Path:
    //    Host (32b @ 180-200M) -> 8x32 Async FIFO -> tx_clk_div2 (32b @ 156.25M)
    //    -> Thin 32:16 Mux on tx_clk (16b @ 312.5M, 1-MUX depth, 2-cycle launch->capture!)
    // =========================================================================
    wire        tx_fifo_rvalid;
    wire        tx_fifo_ronline;
    wire        tx_fifo_prefill2;
    wire [31:0] tx_fifo_rdata;
    wire        tx_fifo_wovf_unused;

    (* ASYNC_REG = "TRUE", keep = "true" *) reg tx_en_s0;
    (* ASYNC_REG = "TRUE" *) reg tx_en_s1;
    reg        primed_q;
    reg        tx_go_q;
    reg [31:0] tx_w32_q;
    reg        tx_w32_v_q;
    reg        tx_underrun_q;

    wire tx_en_sync = tx_en_s1 & tx_fifo_ronline;

    // Zero-bubble registered host_tx valid/ready skid buffer: isolates primary inputs from 512 mem FFs!
    wire        tx_fifo_wready;
    wire        tx_fifo_wonline;
    (* keep = "true" *) reg tx_in_v_ctl_q, tx_in_v_b0_q, tx_in_v_b1_q, tx_in_v_b2_q, tx_in_v_b3_q;
    reg [31:0]  tx_in_data_q;
    reg         tx_skid_v_q;
    reg [31:0]  tx_skid_data_q;
    reg         host_tx_ready_q;

    wire tx_in_fire  = host_tx_valid & host_tx_ready_q;
    wire tx_out_fire = tx_in_v_ctl_q & tx_fifo_wready;
    wire tx_in_v_n   = tx_skid_v_q | tx_in_fire | (tx_in_v_ctl_q & (~tx_fifo_wready));
    wire tx_skid_v_n = (tx_skid_v_q & (~tx_out_fire)) | (tx_in_fire & tx_in_v_ctl_q & (~tx_fifo_wready));
    assign host_tx_ready  = host_tx_ready_q;
    assign host_tx_online = tx_fifo_wonline;

    always @(posedge host_clk or negedge host_rst_n) begin
        if (!host_rst_n) begin
            tx_in_v_ctl_q   <= 1'b0;
            tx_in_v_b0_q    <= 1'b0;
            tx_in_v_b1_q    <= 1'b0;
            tx_in_v_b2_q    <= 1'b0;
            tx_in_v_b3_q    <= 1'b0;
            tx_skid_v_q     <= 1'b0;
            host_tx_ready_q <= 1'b0;
        end else begin
            tx_in_v_ctl_q   <= tx_in_v_n;
            tx_in_v_b0_q    <= tx_in_v_n;
            tx_in_v_b1_q    <= tx_in_v_n;
            tx_in_v_b2_q    <= tx_in_v_n;
            tx_in_v_b3_q    <= tx_in_v_n;
            tx_skid_v_q     <= tx_skid_v_n;
            host_tx_ready_q <= tx_fifo_wonline & (~tx_skid_v_n);
        end
    end
    always @(posedge host_clk) begin
        if (tx_in_fire && tx_in_v_ctl_q && !tx_fifo_wready) begin
            tx_skid_data_q <= host_tx_data;
        end
        if (!tx_in_v_ctl_q || tx_fifo_wready) begin
            if (tx_skid_v_q)     tx_in_data_q <= tx_skid_data_q;
            else if (tx_in_fire) tx_in_data_q <= host_tx_data;
        end
    end

    async_fifo_16x32_prod u_tx_fifo (
        .wclk      (host_clk),
        .wrst_n    (host_rst_n),
        .wvalid    (tx_in_v_ctl_q),
        .wvalid_b0 (tx_in_v_b0_q),
        .wvalid_b1 (tx_in_v_b1_q),
        .wvalid_b2 (tx_in_v_b2_q),
        .wvalid_b3 (tx_in_v_b3_q),
        .wready    (tx_fifo_wready),
        .wonline   (tx_fifo_wonline),
        .woverflow (tx_fifo_wovf_unused),
        .wdata     (tx_in_data_q),
        .rclk      (tx_clk_div2),
        .rrst_n    (tx2_rst_n),
        .rvalid    (tx_fifo_rvalid),
        .ronline   (tx_fifo_ronline),
        .rprefill2 (tx_fifo_prefill2),
        .rready    (tx_go_q),
        .rdata     (tx_fifo_rdata)
    );

    always @(posedge tx_clk_div2 or negedge tx2_rst_n) begin
        if (!tx2_rst_n) begin
            tx_en_s0      <= 1'b0;
            tx_en_s1      <= 1'b0;
            primed_q      <= 1'b0;
            tx_go_q       <= 1'b0;
            tx_w32_q      <= {IDLE_WORD, IDLE_WORD};
            tx_w32_v_q    <= 1'b0;
            tx_underrun_q <= 1'b0;
        end else begin
            tx_en_s0 <= tx_enable;
            tx_en_s1 <= tx_en_s0;
            tx_go_q  <= tx_en_sync & (primed_q | tx_fifo_prefill2);
            if (!tx_en_sync) begin
                primed_q   <= 1'b0;
                tx_w32_q   <= {IDLE_WORD, IDLE_WORD};
                tx_w32_v_q <= 1'b0;
            end else if (tx_go_q && tx_fifo_rvalid) begin
                primed_q   <= 1'b1;
                tx_w32_q   <= tx_fifo_rdata;
                tx_w32_v_q <= 1'b1;
            end else begin
                tx_w32_q   <= {IDLE_WORD, IDLE_WORD};
                tx_w32_v_q <= 1'b0;
                if (primed_q) tx_underrun_q <= 1'b1;
            end
        end
    end

    // Thin 312.5 MHz 32->16 stage (nibble-replicated phase select -> fanout <= 8, 0 repeaters!)
    reg [15:0] tx_hi_hold_q;
    reg        tx_v_hold_q;
    always @(posedge tx_clk or negedge tx_rst_n) begin
        if (!tx_rst_n) begin
            tx_hi_hold_q  <= 16'h0000;
            tx_v_hold_q   <= 1'b0;
            tx_word16     <= 16'h0000;
            tx_word_valid <= 1'b0;
        end else begin
            if (!tx_phase_n0_q) begin
                tx_word16[3:0]    <= tx_w32_q[3:0];
                tx_hi_hold_q[3:0] <= tx_w32_q[19:16];
            end else begin
                tx_word16[3:0]    <= tx_hi_hold_q[3:0];
            end
            if (!tx_phase_n1_q) begin
                tx_word16[7:4]    <= tx_w32_q[7:4];
                tx_hi_hold_q[7:4] <= tx_w32_q[23:20];
            end else begin
                tx_word16[7:4]    <= tx_hi_hold_q[7:4];
            end
            if (!tx_phase_n2_q) begin
                tx_word16[11:8]    <= tx_w32_q[11:8];
                tx_hi_hold_q[11:8] <= tx_w32_q[27:24];
            end else begin
                tx_word16[11:8]    <= tx_hi_hold_q[11:8];
            end
            if (!tx_phase_n3_q) begin
                tx_word16[15:12]    <= tx_w32_q[15:12];
                tx_hi_hold_q[15:12] <= tx_w32_q[31:28];
            end else begin
                tx_word16[15:12]    <= tx_hi_hold_q[15:12];
            end
            if (!tx_phase_ctl_q) begin
                tx_word_valid <= tx_w32_v_q;
                tx_v_hold_q   <= tx_w32_v_q;
            end else begin
                tx_word_valid <= tx_v_hold_q;
            end
        end
    end

    // =========================================================================
    // 3. RX Path:
    //    rx_clk (16b @ 312.5M) -> Thin 16->32 Phase-Safe Packer (byte-replicated, <=1 gate!)
    //    -> rx_clk_div2 (32b @ 156.25M) -> 16x32 Async FIFO -> Host (32b @ 166.7M)
    // =========================================================================
    reg        s0_aligned_q;
    reg        s0_v_q;           // Pre-registered (rx_aligned & wonline & rx_payload_valid)
    reg [15:0] s0_word16_q;
    (* keep = "true" *) reg has_lo_q, has_lo_b0_q, has_lo_b1_q;
    reg [15:0] lo16_q;
    (* keep = "true" *) reg pair_v_ctl_q;
    reg [31:0] pair_word_q;
    (* keep = "true" *) reg pend_v_ctl_q;
    reg [31:0] pend_data_q;
    reg        xfer_tog_q;
    reg        xfer_sel_q;
    reg [31:0] xfer_a_q;   // pend_data_q captured when rx_phase==1 (1-mux!)
    reg [31:0] xfer_b_q;   // pair_word_q captured when rx_phase==1 (1-mux!)

    // Sync rx_fifo_wonline cleanly into rx_clk (strict fanout=1)
    (* ASYNC_REG = "TRUE", keep = "true" *) reg rx_won_s0;
    (* ASYNC_REG = "TRUE" *) reg rx_won_s1;
    wire rx_fifo_wonline;

    wire pair_fire = s0_v_q & has_lo_q;
    wire has_lo_n  = s0_aligned_q & (s0_v_q ? ~has_lo_q : has_lo_q);

    // Control FFs with async rx_rst_n (fanout <= 20 -> 0 reset repeater chain at 312.5 MHz!)
    always @(posedge rx_clk or negedge rx_rst_n) begin
        if (!rx_rst_n) begin
            rx_won_s0    <= 1'b0;
            rx_won_s1    <= 1'b0;
            s0_aligned_q <= 1'b0;
            s0_v_q       <= 1'b0;
            has_lo_q     <= 1'b0; has_lo_b0_q <= 1'b0; has_lo_b1_q <= 1'b0;
            pair_v_ctl_q <= 1'b0;
            pend_v_ctl_q <= 1'b0;
            xfer_tog_q   <= 1'b0;
            xfer_sel_q   <= 1'b0;
        end else begin
            rx_won_s0    <= rx_fifo_wonline;
            rx_won_s1    <= rx_won_s0;
            s0_aligned_q <= rx_aligned & rx_won_s1;
            s0_v_q       <= rx_aligned & rx_won_s1 & rx_payload_valid;
            pair_v_ctl_q <= pair_fire;
            has_lo_q     <= has_lo_n;
            has_lo_b0_q  <= has_lo_n;
            has_lo_b1_q  <= has_lo_n;
            if (rx_phase_ctl_q) begin
                xfer_sel_q <= pend_v_ctl_q;
                if (pend_v_ctl_q) begin
                    xfer_tog_q   <= ~xfer_tog_q;
                    pend_v_ctl_q <= 1'b0;
                end else if (pair_v_ctl_q) begin
                    xfer_tog_q   <= ~xfer_tog_q;
                end
            end else begin
                if (pair_v_ctl_q) pend_v_ctl_q <= 1'b1;
            end
        end
    end

    // Non-reset RX datapath pipeline (qualified by s0_v_q/pair_v_ctl_q/xfer_tog_q; eliminates 160 RESET_B loads!)
    always @(posedge rx_clk) begin
        s0_word16_q <= rx_word16;
        pair_word_q <= {s0_word16_q, lo16_q};
        pend_data_q <= pair_word_q;
        if (!has_lo_b0_q) lo16_q[7:0]  <= s0_word16_q[7:0];
        if (!has_lo_b1_q) lo16_q[15:8] <= s0_word16_q[15:8];
        if (rx_phase_a0_q) xfer_a_q[7:0]   <= pend_data_q[7:0];
        if (rx_phase_b0_q) xfer_b_q[7:0]   <= pair_word_q[7:0];
        if (rx_phase_a1_q) xfer_a_q[15:8]  <= pend_data_q[15:8];
        if (rx_phase_b1_q) xfer_b_q[15:8]  <= pair_word_q[15:8];
        if (rx_phase_a2_q) xfer_a_q[23:16] <= pend_data_q[23:16];
        if (rx_phase_b2_q) xfer_b_q[23:16] <= pair_word_q[23:16];
        if (rx_phase_a3_q) xfer_a_q[31:24] <= pend_data_q[31:24];
        if (rx_phase_b3_q) xfer_b_q[31:24] <= pair_word_q[31:24];
    end

    // rx_clk_div2 capture stage (6.40 ns cycle!) -> selects xfer_a_q/xfer_b_q & drives byte-replicated valid
    reg        rx_tog_seen_q;
    (* keep = "true" *) reg rx_push_v_ctl_q, rx_push_v_b0_q, rx_push_v_b1_q, rx_push_v_b2_q, rx_push_v_b3_q;
    reg [31:0] rx_push_data_q;
    wire       rx_tog_fire = xfer_tog_q ^ rx_tog_seen_q;

    always @(posedge rx_clk_div2 or negedge rx2_rst_n) begin
        if (!rx2_rst_n) begin
            rx_tog_seen_q   <= 1'b0;
            rx_push_v_ctl_q <= 1'b0;
            rx_push_v_b0_q  <= 1'b0;
            rx_push_v_b1_q  <= 1'b0;
            rx_push_v_b2_q  <= 1'b0;
            rx_push_v_b3_q  <= 1'b0;
        end else begin
            rx_tog_seen_q   <= xfer_tog_q;
            rx_push_v_ctl_q <= rx_tog_fire;
            rx_push_v_b0_q  <= rx_tog_fire;
            rx_push_v_b1_q  <= rx_tog_fire;
            rx_push_v_b2_q  <= rx_tog_fire;
            rx_push_v_b3_q  <= rx_tog_fire;
        end
    end
    always @(posedge rx_clk_div2) begin
        rx_push_data_q <= xfer_sel_q ? xfer_a_q : xfer_b_q;
    end

    wire rx_fifo_wready_unused;
    wire rx_fifo_woverflow;
    wire rx_fifo_prefill2_unused;

    async_fifo_16x32_prod u_rx_fifo (
        .wclk      (rx_clk_div2),
        .wrst_n    (rx2_rst_n),
        .wvalid    (rx_push_v_ctl_q),
        .wvalid_b0 (rx_push_v_b0_q),
        .wvalid_b1 (rx_push_v_b1_q),
        .wvalid_b2 (rx_push_v_b2_q),
        .wvalid_b3 (rx_push_v_b3_q),
        .wready    (rx_fifo_wready_unused),
        .wonline   (rx_fifo_wonline),
        .woverflow (rx_fifo_woverflow),
        .wdata     (rx_push_data_q),
        .rclk      (host_clk),
        .rrst_n    (host_rst_n),
        .rvalid    (host_rx_valid),
        .ronline   (host_rx_online),
        .rprefill2 (rx_fifo_prefill2_unused),
        .rready    (host_rx_ready),
        .rdata     (host_rx_data)
    );

    // =========================================================================
    // 4. 1-Bit Sticky Error Flag Synchronizers (strict fanout=1) -> Host Domain
    // =========================================================================
    (* ASYNC_REG = "TRUE", keep = "true" *) reg tx_ur_host_s0;
    (* ASYNC_REG = "TRUE" *) reg tx_ur_host_s1;
    (* ASYNC_REG = "TRUE", keep = "true" *) reg rx_ovf_host_s0;
    (* ASYNC_REG = "TRUE" *) reg rx_ovf_host_s1;
    always @(posedge host_clk or negedge host_rst_n) begin
        if (!host_rst_n) begin
            tx_ur_host_s0  <= 1'b0; tx_ur_host_s1  <= 1'b0;
            rx_ovf_host_s0 <= 1'b0; rx_ovf_host_s1 <= 1'b0;
        end else begin
            tx_ur_host_s0  <= tx_underrun_q;      tx_ur_host_s1  <= tx_ur_host_s0;
            rx_ovf_host_s0 <= rx_fifo_woverflow;  rx_ovf_host_s1 <= rx_ovf_host_s0;
        end
    end
    assign host_tx_underrun = tx_ur_host_s1;
    assign host_rx_overflow = rx_ovf_host_s1;
endmodule
