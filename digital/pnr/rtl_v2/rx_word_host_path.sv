// Timing-closed v2 rx_word_host_path (dual 250 MHz async word_clk & host_clk).
// Preserves exact port list, submodule instance names (u_map, u_align, u_fifo),
// and epoch/retraining/overflow semantics, with clean low-fanout write-enable
// and isolated word_online reset tree (fanout <= 15).
module rx_word_host_path #(
    parameter [15:0]  TRAIN_WORD = 16'hb5e3,
    parameter integer TRAIN_HITS = 4,
    parameter integer ADDR_BITS  = 4
) (
    input  wire        word_clk,
    input  wire        host_clk,
    input  wire        arst_n,
    input  wire [31:0] phys,
    input  wire        training_enable,
    output wire [15:0] host_data,
    output wire        host_valid,
    input  wire        host_ready,
    output wire        word_online,
    output wire        host_online,
    output wire        aligned,
    output wire [3:0]  offset,
    output wire        host_error
);
    wire [15:0] samples, edges, aligned_data;
    wire previous_data, bundle_valid, aligned_valid;
    wire fifo_ready, fifo_overflow, host_overflow, word_online_rst;
    reg  payload_started, source_fault;
    (* ASYNC_REG = "TRUE" *) reg [1:0] fault_host;

    rx_word_map u_map (
        .clk(word_clk), .rst_n(word_online_rst), .phys(phys),
        .data_samples(samples), .edge_samples(edges),
        .previous_data(previous_data), .bundle_valid(bundle_valid)
    );

    rx_word_align16 #(.TRAIN_WORD(TRAIN_WORD), .TRAIN_HITS(TRAIN_HITS)) u_align (
        .clk(word_clk), .rst_n(word_online_rst),
        .chunk_valid(bundle_valid), .training_enable(training_enable),
        .chunk(samples), .word_data(aligned_data),
        .word_valid(aligned_valid), .aligned(aligned), .offset(offset)
    );

    wire wv_a       = aligned_valid && !training_enable;
    wire retraining = training_enable && (payload_started || aligned_valid);
    // ovf_hit matches u_fifo.w_overflow on the exact same clock edge (w_online_int === word_online_rst,
    // fifo_ready === w_ready_q), so source_fault is already 1 on every cycle fifo_overflow is 1!
    wire ovf_hit    = word_online_rst && wv_a && !source_fault && !fifo_ready;
    always @(posedge word_clk or negedge word_online_rst) begin
        if (!word_online_rst) begin
            payload_started <= 1'b0;
            source_fault    <= 1'b0;
        end else begin
            if (wv_a)                  payload_started <= 1'b1;
            if (retraining || ovf_hit) source_fault    <= 1'b1;
        end
    end

    rx_async_word_fifo_core #(.DATA_WIDTH(16), .ADDR_BITS(ADDR_BITS)) u_fifo (
        .w_clk(word_clk), .r_clk(host_clk), .arst_n(arst_n),
        .w_valid(wv_a && !source_fault),
        .w_data(aligned_data), .w_ready(fifo_ready),
        .w_online(word_online), .w_online_rst(word_online_rst),
        .w_overflow(fifo_overflow),
        .r_valid(host_valid), .r_online(host_online), .r_overflow(host_overflow),
        .r_data(host_data), .r_ready(host_ready)
    );

    always @(posedge host_clk or negedge host_online) begin
        if (!host_online) fault_host <= 2'b00;
        else              fault_host <= {fault_host[0], source_fault};
    end

    assign host_error = host_overflow | fault_host[1];
endmodule
