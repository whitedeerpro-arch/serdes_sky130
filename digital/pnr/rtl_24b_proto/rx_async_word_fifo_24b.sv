`timescale 1ns/1ps

// 3-Byte-Sliced 24-bit (26-bit = {keep[1:0], data[23:0]}) Timing-Friendly Gray-Coded Async FIFO
// Eliminates the v3.2 hardcoded 16-bit slice limitation (xx1000 high-byte X bug) via 3 explicit 8-bit lanes.
module rx_async_word_fifo_24b #(
    parameter integer DATA_W  = 26,
    parameter integer ADDR_W  = 4
) (
    input  wire              wr_clk,
    input  wire              wr_rst_n,
    input  wire              wr_valid,
    output wire              wr_ready,
    input  wire [DATA_W-1:0] wr_data,
    output reg               overflow_pulse,

    input  wire              rd_clk,
    input  wire              rd_rst_n,
    output wire              rd_valid,
    input  wire              rd_ready,
    output wire [DATA_W-1:0] rd_data
);
    localparam integer DEPTH = 1 << ADDR_W;

    reg [7:0]         mem_b0 [0:DEPTH-1];
    reg [7:0]         mem_b1 [0:DEPTH-1];
    reg [7:0]         mem_b2 [0:DEPTH-1];
    reg [DATA_W-25:0] mem_sb [0:DEPTH-1];
    integer           i;

    reg [ADDR_W:0] wr_bin, wr_gray;
    reg [ADDR_W:0] rd_bin, rd_gray;
    (* ASYNC_REG = "TRUE" *) reg [ADDR_W:0] rd_gray_ws1, rd_gray_ws2;
    (* ASYNC_REG = "TRUE" *) reg [ADDR_W:0] wr_gray_rs1, wr_gray_rs2;

    wire wr_full_now = (wr_gray == {~rd_gray_ws2[ADDR_W:ADDR_W-1], rd_gray_ws2[ADDR_W-2:0]});
    assign wr_ready  = !wr_full_now;

    wire [ADDR_W:0] wr_bin_next  = wr_bin + ((wr_valid && wr_ready) ? {{ADDR_W{1'b0}}, 1'b1} : {(ADDR_W+1){1'b0}});
    wire [ADDR_W:0] wr_gray_next = wr_bin_next ^ (wr_bin_next >> 1);

    always @(posedge wr_clk or negedge wr_rst_n) begin
        if (!wr_rst_n) begin
            wr_bin         <= {(ADDR_W+1){1'b0}};
            wr_gray        <= {(ADDR_W+1){1'b0}};
            rd_gray_ws1    <= {(ADDR_W+1){1'b0}};
            rd_gray_ws2    <= {(ADDR_W+1){1'b0}};
            overflow_pulse <= 1'b0;
            for (i = 0; i < DEPTH; i = i + 1) begin
                mem_b0[i] <= 8'h00;
                mem_b1[i] <= 8'h00;
                mem_b2[i] <= 8'h00;
                mem_sb[i] <= {(DATA_W-24){1'b0}};
            end
        end else begin
            rd_gray_ws1    <= rd_gray;
            rd_gray_ws2    <= rd_gray_ws1;
            overflow_pulse <= wr_valid && wr_full_now;
            if (wr_valid && wr_ready) begin
                mem_b0[wr_bin[ADDR_W-1:0]] <= wr_data[7:0];
                mem_b1[wr_bin[ADDR_W-1:0]] <= wr_data[15:8];
                mem_b2[wr_bin[ADDR_W-1:0]] <= wr_data[23:16];
                mem_sb[wr_bin[ADDR_W-1:0]] <= wr_data[DATA_W-1:24];
                wr_bin                     <= wr_bin_next;
                wr_gray                    <= wr_gray_next;
            end
        end
    end

    reg              out_valid_q;
    reg [DATA_W-1:0] out_data_q;

    wire fifo_empty = (rd_gray == wr_gray_rs2);
    wire pop_mem    = !fifo_empty && (!out_valid_q || rd_ready);

    wire [ADDR_W:0] rd_bin_next  = rd_bin + (pop_mem ? {{ADDR_W{1'b0}}, 1'b1} : {(ADDR_W+1){1'b0}});
    wire [ADDR_W:0] rd_gray_next = rd_bin_next ^ (rd_bin_next >> 1);

    assign rd_valid = out_valid_q;
    assign rd_data  = out_data_q;

    always @(posedge rd_clk or negedge rd_rst_n) begin
        if (!rd_rst_n) begin
            rd_bin      <= {(ADDR_W+1){1'b0}};
            rd_gray     <= {(ADDR_W+1){1'b0}};
            wr_gray_rs1 <= {(ADDR_W+1){1'b0}};
            wr_gray_rs2 <= {(ADDR_W+1){1'b0}};
            out_valid_q <= 1'b0;
            out_data_q  <= {DATA_W{1'b0}};
        end else begin
            wr_gray_rs1 <= wr_gray;
            wr_gray_rs2 <= wr_gray_rs1;
            if (pop_mem) begin
                out_data_q  <= {mem_sb[rd_bin[ADDR_W-1:0]],
                                mem_b2[rd_bin[ADDR_W-1:0]],
                                mem_b1[rd_bin[ADDR_W-1:0]],
                                mem_b0[rd_bin[ADDR_W-1:0]]};
                out_valid_q <= 1'b1;
                rd_bin      <= rd_bin_next;
                rd_gray     <= rd_gray_next;
            end else if (rd_ready) begin
                out_valid_q <= 1'b0;
            end
        end
    end
endmodule
