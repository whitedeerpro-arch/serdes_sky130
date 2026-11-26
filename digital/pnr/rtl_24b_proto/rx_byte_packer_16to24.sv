`timescale 1ns/1ps

// Byte-Aligned RX 16-bit (2-Byte) -> 24-bit (3-Byte) Packer
// Packs every 3 valid 16-bit payload words (48 bits) into 2 clean 24-bit words for the 24-bit async FIFO.
module rx_byte_packer_16to24 #(
    parameter [15:0] IDLE_WORD = 16'hBC50
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        enable,
    input  wire        in_valid,
    input  wire [15:0] in_word,
    input  wire        drop_idle,

    output reg         out_valid,
    output reg  [23:0] out_data
);
    reg [1:0]  rem_cnt;
    reg [15:0] rem_bytes;

    wire accept_word = enable && in_valid && !(drop_idle && (in_word == IDLE_WORD));

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rem_cnt   <= 2'd0;
            rem_bytes <= 16'd0;
            out_valid <= 1'b0;
            out_data  <= 24'd0;
        end else if (!enable) begin
            rem_cnt   <= 2'd0;
            rem_bytes <= 16'd0;
            out_valid <= 1'b0;
        end else if (accept_word) begin
            case (rem_cnt)
                2'd0: begin
                    rem_bytes <= in_word;
                    rem_cnt   <= 2'd2;
                    out_valid <= 1'b0;
                end
                2'd1: begin
                    out_data  <= {in_word, rem_bytes[7:0]};
                    out_valid <= 1'b1;
                    rem_cnt   <= 2'd0;
                end
                default: begin
                    out_data  <= {in_word[7:0], rem_bytes};
                    out_valid <= 1'b1;
                    rem_bytes <= {8'h00, in_word[15:8]};
                    rem_cnt   <= 2'd1;
                end
            endcase
        end else begin
            out_valid <= 1'b0;
        end
    end
endmodule
