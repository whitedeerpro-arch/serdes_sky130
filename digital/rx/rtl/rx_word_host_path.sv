// Recovered-word capture -> host FIFO. phys and training_enable are word_clk synchronous.
// Common reset starts a new epoch; physical input capture timing and clock compensation are external.
module rx_word_host_path #(
    parameter [15:0] TRAIN_WORD = 16'hb5e3,
    parameter integer TRAIN_HITS = 4,
    parameter integer ADDR_BITS = 4
) (
    input wire word_clk, host_clk, arst_n,
    input wire [31:0] phys,
    input wire training_enable,
    output wire [15:0] host_data,
    output wire host_valid,
    input wire host_ready,
    output wire word_online, host_online,
    output wire aligned,
    output wire [3:0] offset,
    output wire host_error
);
    wire [15:0] samples, edges, aligned_data;
    wire previous_data, bundle_valid, aligned_valid;
    wire fifo_ready, fifo_overflow, host_overflow;
    reg payload_started, source_fault;
    (* ASYNC_REG = "TRUE" *) reg [1:0] fault_host;

    rx_word_map u_map (.clk(word_clk), .rst_n(word_online), .phys(phys),
        .data_samples(samples), .edge_samples(edges), .previous_data(previous_data), .bundle_valid(bundle_valid));
    rx_word_align16 #(.TRAIN_WORD(TRAIN_WORD), .TRAIN_HITS(TRAIN_HITS)) u_align (
        .clk(word_clk), .rst_n(word_online), .chunk_valid(bundle_valid), .training_enable(training_enable),
        .chunk(samples), .word_data(aligned_data), .word_valid(aligned_valid), .aligned(aligned), .offset(offset));
    // The valid register can hold a last payload on the first retraining edge.
    // Treat that case as an epoch violation even if no earlier word entered the FIFO.
    wire retraining = training_enable && (payload_started || aligned_valid);
    always @(posedge word_clk or negedge word_online) begin
        if (!word_online) begin payload_started <= 1'b0; source_fault <= 1'b0; end
        else begin
            if (aligned_valid && !training_enable) payload_started <= 1'b1;
            if (retraining || fifo_overflow) source_fault <= 1'b1;
        end
    end
    rx_async_word_fifo #(.DATA_WIDTH(16), .ADDR_BITS(ADDR_BITS)) u_fifo (
        .w_clk(word_clk), .r_clk(host_clk), .arst_n(arst_n),
        .w_valid(aligned_valid && !training_enable && !source_fault && !fifo_overflow),
        .w_data(aligned_data), .w_ready(fifo_ready), .w_online(word_online), .w_overflow(fifo_overflow),
        .r_valid(host_valid), .r_online(host_online), .r_overflow(host_overflow),
        .r_data(host_data), .r_ready(host_ready));
    always @(posedge host_clk or negedge host_online) begin
        if (!host_online) fault_host <= 2'b00;
        else fault_host <= {fault_host[0], source_fault};
    end
    assign host_error = host_overflow | fault_host[1];
endmodule
