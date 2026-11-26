`timescale 1ns/1ps

// Byte-Managed 24-bit (3-Byte) -> 16-bit (2-Byte) Elastic TX Gearbox
// Synthesizable in Yosys 0.9 / OpenROAD / Icarus 10.3 / Verilator 4.028.
// - Producer (from 24-bit async FIFO): 24-bit word (3 bytes) with valid/ready + optional keep_bytes (1..3).
// - Consumer (tx_word_clk: 250 MHz @ 4 Gb/s OR 312.5 MHz @ 5 Gb/s): hard real-time 16-bit word every cycle.
// - Internally uses an 8-byte circular byte buffer (DEPTH_BYTES=8 >= LCM(3,2)=6 + margin):
//     * 4 Gb/s (250->250 MHz): natural 2/3 ready cadence (1,1,0,1,1,0...)
//     * 5 Gb/s (250->312.5 MHz): natural 5/6 ready cadence — IDENTICAL hardware!
module tx_byte_gearbox_24to16 #(
    parameter [15:0]  IDLE_WORD     = 16'hBC50,
    parameter integer PREFILL_BYTES = 4,
    parameter integer DEPTH_BYTES   = 8
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        enable,

    input  wire        in_valid,
    output wire        in_ready,
    input  wire [23:0] in_data,        // Byte0=[7:0], Byte1=[15:8], Byte2=[23:16] (LSB-first)
    input  wire [1:0]  in_keep_bytes,  // 2'd0 or 2'd3 -> 3 bytes; 2'd1 -> 1 byte; 2'd2 -> 2 bytes

    output reg  [15:0] tx_word,
    output reg         tx_word_is_idle,
    output reg  [15:0] underrun_cnt,
    output wire [3:0]  fill_bytes_dbg
);
    localparam integer PTR_W = $clog2(DEPTH_BYTES);

    reg [7:0]       mem [0:DEPTH_BYTES-1];
    reg [PTR_W-1:0] wr_ptr;
    reg [PTR_W-1:0] rd_ptr;
    reg [PTR_W:0]   fill_bytes;
    reg             active_stream;
    integer         i;

    reg [2:0] push_bytes;
    always @(*) begin
        case (in_keep_bytes)
            2'd1:    push_bytes = 3'd1;
            2'd2:    push_bytes = 3'd2;
            default: push_bytes = 3'd3;
        endcase
    end

    reg will_pop;
    reg next_active;
    always @(*) begin
        if (!enable) begin
            next_active = 1'b0;
            will_pop    = 1'b0;
        end else if (active_stream) begin
            will_pop    = (fill_bytes >= 4'd2);
            next_active = will_pop;
        end else begin
            next_active = (fill_bytes >= PREFILL_BYTES[PTR_W:0]);
            will_pop    = next_active && (fill_bytes >= 4'd2);
        end
    end

    wire [PTR_W:0] fill_after_pop = fill_bytes - (will_pop ? 4'd2 : 4'd0);
    wire [PTR_W:0] free_after_pop = DEPTH_BYTES[PTR_W:0] - fill_after_pop;
    assign in_ready       = enable && (free_after_pop >= 4'd3);
    wire   do_push        = in_valid && in_ready;
    assign fill_bytes_dbg = fill_bytes;

    wire [PTR_W-1:0] wr_p0 = wr_ptr;
    wire [PTR_W-1:0] wr_p1 = wr_ptr + {{(PTR_W-1){1'b0}}, 1'b1};
    wire [PTR_W-1:0] wr_p2 = wr_ptr + {{(PTR_W-2){1'b0}}, 2'd2};
    wire [PTR_W-1:0] rd_p0 = rd_ptr;
    wire [PTR_W-1:0] rd_p1 = rd_ptr + {{(PTR_W-1){1'b0}}, 1'b1};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr          <= {PTR_W{1'b0}};
            rd_ptr          <= {PTR_W{1'b0}};
            fill_bytes      <= {(PTR_W+1){1'b0}};
            active_stream   <= 1'b0;
            tx_word         <= IDLE_WORD;
            tx_word_is_idle <= 1'b1;
            underrun_cnt    <= 16'd0;
            for (i = 0; i < DEPTH_BYTES; i = i + 1) begin
                mem[i] <= 8'h00;
            end
        end else if (!enable) begin
            wr_ptr          <= {PTR_W{1'b0}};
            rd_ptr          <= {PTR_W{1'b0}};
            fill_bytes      <= {(PTR_W+1){1'b0}};
            active_stream   <= 1'b0;
            tx_word         <= IDLE_WORD;
            tx_word_is_idle <= 1'b1;
        end else begin
            if (will_pop) begin
                tx_word         <= {mem[rd_p1], mem[rd_p0]};
                tx_word_is_idle <= 1'b0;
                rd_ptr          <= rd_ptr + {{(PTR_W-2){1'b0}}, 2'd2};
            end else begin
                tx_word         <= IDLE_WORD;
                tx_word_is_idle <= 1'b1;
                if (active_stream && !will_pop && (underrun_cnt != 16'hFFFF)) begin
                    underrun_cnt <= underrun_cnt + 16'd1;
                end
            end

            if (do_push) begin
                mem[wr_p0] <= in_data[7:0];
                if (push_bytes >= 3'd2) mem[wr_p1] <= in_data[15:8];
                if (push_bytes >= 3'd3) mem[wr_p2] <= in_data[23:16];
                wr_ptr <= wr_ptr + push_bytes[PTR_W-1:0];
            end

            fill_bytes    <= fill_after_pop + (do_push ? {1'b0, push_bytes} : 4'd0);
            active_stream <= next_active;
        end
    end
endmodule
