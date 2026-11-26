`timescale 1ns/1ps
// Native 8 x 32-bit Asynchronous FIFO (Exact 256-bit storage, 4-bit standard Gray-code CDC)
// Universal dialect: Yosys 0.9 / Icarus 10.3 / Verilator 4.028 (-Wall clean)
module async_fifo_8x32 (
    input  wire        wclk,
    input  wire        wrst_n,
    input  wire        wvalid,
    output wire        wready,
    input  wire [31:0] wdata,
    output wire [3:0]  wlevel,

    input  wire        rclk,
    input  wire        rrst_n,
    output wire        rvalid,
    input  wire        rready,
    output wire [31:0] rdata,
    output wire [3:0]  rlevel
);
    // Exact 256-bit storage: 8 slots x 32-bit (4-bit Gray pointers, 8:1 read mux)
    reg [31:0] mem [0:7];

    // Write domain
    reg [3:0] wbin_q, wgray_q;
    reg [3:0] rgray_w1_q, rgray_w2_q;

    // Read domain
    reg [3:0] rbin_q, rgray_q;
    reg [3:0] wgray_r1_q, wgray_r2_q;

    wire w_fire = wvalid & wready;
    wire r_fire = rvalid & rready;

    wire [3:0] wbin_n  = wbin_q + {3'd0, w_fire};
    wire [3:0] wgray_n = (wbin_n >> 1) ^ wbin_n;

    wire [3:0] rbin_n  = rbin_q + {3'd0, r_fire};
    wire [3:0] rgray_n = (rbin_n >> 1) ^ rbin_n;

    // 4-bit Gray -> Binary helpers for approximate level / watermark telemetry
    function [3:0] gray4_to_bin(input [3:0] g);
        begin
            gray4_to_bin[3] = g[3];
            gray4_to_bin[2] = g[3] ^ g[2];
            gray4_to_bin[1] = g[3] ^ g[2] ^ g[1];
            gray4_to_bin[0] = g[3] ^ g[2] ^ g[1] ^ g[0];
        end
    endfunction

    wire [3:0] rbin_w = gray4_to_bin(rgray_w2_q);
    wire [3:0] wbin_r = gray4_to_bin(wgray_r2_q);

    wire full  = (wgray_q == {~rgray_w2_q[3:2], rgray_w2_q[1:0]});
    wire empty = (rgray_q == wgray_r2_q);

    assign wready = ~full;
    assign rvalid = ~empty;
    assign rdata  = mem[rbin_q[2:0]];
    assign wlevel = wbin_q - rbin_w;
    assign rlevel = wbin_r - rbin_q;

    integer i;
    always @(posedge wclk or negedge wrst_n) begin
        if (!wrst_n) begin
            wbin_q     <= 4'd0;
            wgray_q    <= 4'd0;
            rgray_w1_q <= 4'd0;
            rgray_w2_q <= 4'd0;
            for (i = 0; i < 8; i = i + 1) begin
                mem[i] <= 32'd0;
            end
        end else begin
            rgray_w1_q <= rgray_q;
            rgray_w2_q <= rgray_w1_q;
            wbin_q     <= wbin_n;
            wgray_q    <= wgray_n;
            if (w_fire) begin
                mem[wbin_q[2:0]] <= wdata;
            end
        end
    end

    always @(posedge rclk or negedge rrst_n) begin
        if (!rrst_n) begin
            rbin_q     <= 4'd0;
            rgray_q    <= 4'd0;
            wgray_r1_q <= 4'd0;
            wgray_r2_q <= 4'd0;
        end else begin
            wgray_r1_q <= wgray_q;
            wgray_r2_q <= wgray_r1_q;
            rbin_q     <= rbin_n;
            rgray_q    <= rgray_n;
        end
    end
endmodule
