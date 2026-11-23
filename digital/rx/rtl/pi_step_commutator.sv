// Synchronous +/-1 requests, registered analog controls; no arbitrary code jumps.
// GUARD_CYCLES * control period must exceed analog endpoint/anchor settling time.
// Reset only while RX is offline. This is NOT a physical CDC/safe-edge retimer.
module pi_step_commutator #(parameter integer GUARD_CYCLES=1)(
    input wire ctrl_clk, rst_n, step_valid, advance,
    output wire step_ready,
    output reg [5:0] phase_code,
    output reg [7:0] select_a, select_b, fine_b,
    output reg applied, done
);
    localparam IDLE=2'd0, PREPARE=2'd1, ENDPOINT=2'd2, SETTLE=2'd3;
    localparam integer CW=(GUARD_CYCLES>1 ? $clog2(GUARD_CYCLES) : 1);
    localparam [CW-1:0] GUARD_LAST=GUARD_CYCLES[CW-1:0]-1'b1;
    reg [1:0] state;
    reg [CW-1:0] wait_count;
    reg [5:0] pending_code;
    reg [7:0] pending_a, pending_b, pending_f;
    function automatic [7:0] decode_a(input [2:0] c);
        integer q;
        begin q={29'd0,c}; decode_a=8'b1 << ((q+(q%2))%8); end
    endfunction
    function automatic [7:0] decode_b(input [2:0] c);
        integer q;
        begin q={29'd0,c}; decode_b=8'b1 << ((q+1-(q%2))%8); end
    endfunction
    function automatic [7:0] decode_f(input [3:0] c);
        integer n;
        begin n=(c[3] ? 8-{29'd0,c[2:0]} : {29'd0,c[2:0]}); decode_f=8'hff >> (8-n); end
    endfunction
    wire [5:0] next_code=phase_code+(advance ? 6'd1 : 6'd63);
    wire [7:0] next_a=decode_a(next_code[5:3]), next_b=decode_b(next_code[5:3]), next_f=decode_f(next_code[3:0]);
    wire coarse_change=(next_a!=select_a)||(next_b!=select_b);
    wire inactive_change=((next_a!=select_a)&&(fine_b==8'hff))||
                         ((next_b!=select_b)&&(fine_b==8'h00));
    assign step_ready=(state==IDLE);
    always @(posedge ctrl_clk or negedge rst_n) begin
        if (!rst_n) begin
            phase_code<=0; select_a<=8'h01; select_b<=8'h02; fine_b<=0;
            pending_code<=0; pending_a<=0; pending_b<=0; pending_f<=0;
            state<=IDLE; wait_count<=0; applied<=0; done<=0;
        end else begin
            applied<=0; done<=0;
            case (state)
                IDLE: if (step_valid) begin
                    pending_code<=next_code; pending_a<=next_a;
                    pending_b<=next_b; pending_f<=next_f; wait_count<=0;
                    if (!coarse_change) begin
                        fine_b<=next_f; phase_code<=next_code; applied<=1; done<=1;
                    end else if (inactive_change) begin
                        select_a<=next_a; select_b<=next_b; state<=PREPARE;
                    end else begin
                        fine_b<=next_f; phase_code<=next_code; applied<=1; state<=ENDPOINT;
                    end
                end
                PREPARE: if (wait_count==GUARD_LAST) begin
                    fine_b<=pending_f; phase_code<=pending_code;
                    applied<=1; done<=1; state<=IDLE; wait_count<=0;
                end else wait_count<=wait_count+1'b1;
                ENDPOINT: if (wait_count==GUARD_LAST) begin
                    select_a<=pending_a; select_b<=pending_b;
                    state<=SETTLE; wait_count<=0;
                end else wait_count<=wait_count+1'b1;
                SETTLE: if (wait_count==GUARD_LAST) begin
                    state<=IDLE; done<=1; wait_count<=0;
                end else wait_count<=wait_count+1'b1;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
