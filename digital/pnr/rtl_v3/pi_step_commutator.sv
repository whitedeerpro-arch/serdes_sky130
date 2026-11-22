// Compact PI step commutator running on synchronous /2 (125 MHz / 8.0 ns) clock (v3).
// Preserves exact one-hot select_a/select_b and thermometer fine_b glitch-free sequencing.
module pi_step_commutator #(
    parameter integer GUARD_CYCLES = 1
) (
    input  wire       ctrl_clk,
    input  wire       rst_n,
    input  wire       step_valid,
    input  wire       advance,
    output wire       step_ready,
    output reg  [5:0] phase_code,
    output reg  [7:0] select_a,
    output reg  [7:0] select_b,
    output reg  [7:0] fine_b,
    output reg        applied,
    output reg        done
);
    localparam [1:0] IDLE = 2'd0, PREPARE = 2'd1, ENDPOINT = 2'd2, SETTLE = 2'd3;
    localparam integer CW = (GUARD_CYCLES > 1) ? $clog2(GUARD_CYCLES) : 1;
    localparam integer GL_I = (GUARD_CYCLES > 1) ? (GUARD_CYCLES - 1) : 0;
    localparam [CW-1:0] GUARD_LAST = GL_I[CW-1:0];

    reg [1:0]    state;
    reg [CW-1:0] wait_count;
    reg [5:0]    pending_code;
    reg [7:0]    pending_a, pending_b, pending_f;

    function automatic [7:0] decode_a(input [2:0] c);
        case (c)
            3'd0: decode_a = 8'b0000_0001;
            3'd1: decode_a = 8'b0000_0100;
            3'd2: decode_a = 8'b0000_0100;
            3'd3: decode_a = 8'b0001_0000;
            3'd4: decode_a = 8'b0001_0000;
            3'd5: decode_a = 8'b0100_0000;
            3'd6: decode_a = 8'b0100_0000;
            3'd7: decode_a = 8'b0000_0001;
        endcase
    endfunction

    function automatic [7:0] decode_b(input [2:0] c);
        case (c)
            3'd0: decode_b = 8'b0000_0010;
            3'd1: decode_b = 8'b0000_0010;
            3'd2: decode_b = 8'b0000_1000;
            3'd3: decode_b = 8'b0000_1000;
            3'd4: decode_b = 8'b0010_0000;
            3'd5: decode_b = 8'b0010_0000;
            3'd6: decode_b = 8'b1000_0000;
            3'd7: decode_b = 8'b1000_0000;
        endcase
    endfunction

    function automatic [7:0] decode_f(input [3:0] c);
        case (c)
            4'd0:  decode_f = 8'b0000_0000;
            4'd1:  decode_f = 8'b0000_0001;
            4'd2:  decode_f = 8'b0000_0011;
            4'd3:  decode_f = 8'b0000_0111;
            4'd4:  decode_f = 8'b0000_1111;
            4'd5:  decode_f = 8'b0001_1111;
            4'd6:  decode_f = 8'b0011_1111;
            4'd7:  decode_f = 8'b0111_1111;
            4'd8:  decode_f = 8'b1111_1111;
            4'd9:  decode_f = 8'b0111_1111;
            4'd10: decode_f = 8'b0011_1111;
            4'd11: decode_f = 8'b0001_1111;
            4'd12: decode_f = 8'b0000_1111;
            4'd13: decode_f = 8'b0000_0111;
            4'd14: decode_f = 8'b0000_0011;
            4'd15: decode_f = 8'b0000_0001;
        endcase
    endfunction

    wire [5:0] code_p1 = phase_code + 6'd1;
    wire [5:0] code_m1 = phase_code + 6'd63;
    wire [5:0] next_code = advance ? code_p1 : code_m1;
    wire [7:0] next_a    = advance ? decode_a(code_p1[5:3]) : decode_a(code_m1[5:3]);
    wire [7:0] next_b    = advance ? decode_b(code_p1[5:3]) : decode_b(code_m1[5:3]);
    wire [7:0] next_f    = advance ? decode_f(code_p1[3:0]) : decode_f(code_m1[3:0]);

    // Exact algebraic octant-crossing identities (eliminates 8-bit decoded bus comparators!):
    //   advance=1 crosses octant only at code[2:0]==3'b111 (active endpoint -> ENDPOINT)
    //   advance=0 crosses octant only at code[2:0]==3'b000 (inactive leg at 0x00/0xff -> PREPARE)
    wire coarse_change   = advance ? (&phase_code[2:0]) : (~|phase_code[2:0]);
    wire inactive_change = (!advance) && (~|phase_code[2:0]);

    assign step_ready = (state == IDLE);

    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            phase_code   <= 6'd0;
            select_a     <= 8'h01;
            select_b     <= 8'h02;
            fine_b       <= 8'h00;
            pending_code <= 6'd0;
            pending_a    <= 8'h00;
            pending_b    <= 8'h00;
            pending_f    <= 8'h00;
            state        <= IDLE;
            wait_count   <= {CW{1'b0}};
            applied      <= 1'b0;
            done         <= 1'b0;
        end else begin
            applied <= 1'b0;
            done    <= 1'b0;
            case (state)
                IDLE: begin
                    if (step_valid) begin
                        pending_code <= next_code;
                        pending_a    <= next_a;
                        pending_b    <= next_b;
                        pending_f    <= next_f;
                        wait_count   <= {CW{1'b0}};
                        if (!coarse_change) begin
                            fine_b     <= next_f;
                            phase_code <= next_code;
                            applied    <= 1'b1;
                            done       <= 1'b1;
                        end else if (inactive_change) begin
                            select_a <= next_a;
                            select_b <= next_b;
                            state    <= PREPARE;
                        end else begin
                            fine_b     <= next_f;
                            phase_code <= next_code;
                            applied    <= 1'b1;
                            state      <= ENDPOINT;
                        end
                    end
                end
                PREPARE: begin
                    if (wait_count == GUARD_LAST) begin
                        fine_b     <= pending_f;
                        phase_code <= pending_code;
                        applied    <= 1'b1;
                        done       <= 1'b1;
                        state      <= IDLE;
                        wait_count <= {CW{1'b0}};
                    end else begin
                        wait_count <= wait_count + 1'b1;
                    end
                end
                ENDPOINT: begin
                    if (wait_count == GUARD_LAST) begin
                        select_a   <= pending_a;
                        select_b   <= pending_b;
                        state      <= SETTLE;
                        wait_count <= {CW{1'b0}};
                    end else begin
                        wait_count <= wait_count + 1'b1;
                    end
                end
                SETTLE: begin
                    if (wait_count == GUARD_LAST) begin
                        state      <= IDLE;
                        done       <= 1'b1;
                        wait_count <= {CW{1'b0}};
                    end else begin
                        wait_count <= wait_count + 1'b1;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
